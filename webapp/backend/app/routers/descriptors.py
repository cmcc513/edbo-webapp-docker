"""Descriptor computation tools + the feature-composition workflow.

Chemists pick a tool (RDKit / Mordred / ...), preview the computed feature
matrix for a component's values, then compose a descriptor set by selecting a
subset of features (optionally standardized, with derived features and PCA).
The composed set is written as a CSV following the shared descriptor spec, so
it plugs into the exact same ``encoding=descriptor`` path as an imported CSV.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, UploadFile, File, Form
from sqlalchemy.orm import Session

from ..config import DESC_DIR
from ..database import get_db
from .. import descriptor_tools as dt
from .. import models, schemas, services
from ..edbo_session import SpaceValidationError

router = APIRouter(prefix="/api", tags=["descriptors"])


@router.get("/descriptor-tools")
def descriptor_tools():
    """List registered descriptor computation tools (and availability)."""
    return {"tools": dt.list_tools()}


def _jsonify(df: pd.DataFrame) -> list[dict]:
    safe = df.replace([np.inf, -np.inf], np.nan)
    safe = safe.where(pd.notnull(safe), None)
    return safe.to_dict(orient="records")


def _safe_name(name: str) -> str:
    s = re.sub(r"[^0-9A-Za-z_.-]+", "_", name.strip()) or "descriptor"
    return s[:60]


def _reindex_to_ids(df: pd.DataFrame, ids: list[str]) -> pd.DataFrame:
    """Return a raw matrix (ID_COL + numeric features) with exactly one row per
    requested identifier; rows missing from ``df`` become all-NaN so the caller
    reports them as invalid (same contract as ``DescriptorTool.compute``)."""
    df = df.rename(columns={df.columns[0]: dt.ID_COL})
    df[dt.ID_COL] = df[dt.ID_COL].astype(str)
    feats = df.drop(columns=[dt.ID_COL]).apply(pd.to_numeric, errors="coerce")
    df = pd.concat([df[dt.ID_COL], feats], axis=1)
    df = df.drop_duplicates(subset=[dt.ID_COL]).set_index(dt.ID_COL)
    df = df.reindex([str(i) for i in ids])
    return df.reset_index().rename(columns={"index": dt.ID_COL})


def _raw_matrix(project_id: str, tool_id: str, source_file: str | None,
                ids: list[str]) -> pd.DataFrame:
    """Feature matrix for ``ids`` from either an imported CSV or a tool."""
    if source_file:
        path = DESC_DIR / source_file
        if not path.exists():
            raise HTTPException(400, "导入文件已失效，请重新导入。")
        return _reindex_to_ids(pd.read_csv(path), ids)
    tool = dt.get_tool(tool_id)
    if tool is None:
        raise HTTPException(404, f"未知工具 '{tool_id}'")
    if not tool.available():
        raise RuntimeError(f"工具 {tool.name} 不可用。")
    return tool.compute(ids)


@router.post("/projects/{project_id}/descriptors/import",
             response_model=schemas.DescriptorComputeOut)
async def import_descriptors(
    project_id: str,
    file: UploadFile = File(...),
    identifiers: str = Form("[]"),
    db: Session = Depends(get_db),
):
    """Import a custom descriptor CSV and expose it for feature selection.

    The uploaded matrix is reindexed to the component's values and stored as a
    raw token so ``compose`` can reuse it (selection / derived / PCA), exactly
    like a computed tool result."""
    import json

    if not db.get(models.Project, project_id):
        raise HTTPException(404, "Project not found")
    try:
        ids = [str(x) for x in json.loads(identifiers) if str(x).strip()]
    except Exception:  # noqa: BLE001
        ids = []
    raw_token = f"{project_id}__rawimport__{_safe_name(file.filename or 'import')}.csv"
    dest = DESC_DIR / raw_token
    dest.write_bytes(await file.read())
    try:
        uploaded = pd.read_csv(dest)
    except Exception as exc:  # noqa: BLE001
        dest.unlink(missing_ok=True)
        return schemas.DescriptorComputeOut(ok=False, error=f"CSV 解析失败：{exc}")
    if uploaded.shape[1] < 2:
        return schemas.DescriptorComputeOut(ok=False, error="CSV 至少需要标识符列 + 1 个特征列。")
    if not ids:
        # No component context: keep the file's own identifiers.
        ids = uploaded.iloc[:, 0].astype(str).tolist()

    raw = _reindex_to_ids(uploaded, ids)
    # Persist the reindexed matrix so compose reuses the exact same rows.
    raw.to_csv(dest, index=False)
    cleaned, invalid, stats = dt.clean_features(raw)
    cols = [c for c in cleaned.columns if c != dt.ID_COL]
    return schemas.DescriptorComputeOut(
        ok=True, id_column=dt.ID_COL, columns=cols, rows=_jsonify(cleaned),
        stats=stats, invalid=invalid, source_file=raw_token,
    )


@router.post("/projects/{project_id}/descriptors/compute",
             response_model=schemas.DescriptorComputeOut)
def compute_descriptors(project_id: str, payload: schemas.DescriptorComputeIn,
                        db: Session = Depends(get_db)):
    """Compute the full feature matrix for a set of identifiers (SMILES)."""
    if not db.get(models.Project, project_id):
        raise HTTPException(404, "Project not found")
    tool = dt.get_tool(payload.tool_id)
    if tool is None:
        raise HTTPException(404, f"未知工具 '{payload.tool_id}'")
    if not tool.available():
        return schemas.DescriptorComputeOut(ok=False, error=f"工具 {tool.name} 不可用。")
    ids = [str(x) for x in payload.identifiers if str(x).strip()]
    if not ids:
        return schemas.DescriptorComputeOut(ok=False, error="没有可计算的取值。")
    try:
        raw = tool.compute(ids)
        cleaned, invalid, stats = dt.clean_features(raw)
    except Exception as exc:  # noqa: BLE001
        return schemas.DescriptorComputeOut(ok=False, error=str(exc))

    cols = [c for c in cleaned.columns if c != dt.ID_COL]
    return schemas.DescriptorComputeOut(
        ok=True, id_column=dt.ID_COL, columns=cols,
        rows=_jsonify(cleaned), stats=stats, invalid=invalid,
    )


@router.post("/projects/{project_id}/descriptors/compose",
             response_model=schemas.DescriptorComposeOut)
def compose_descriptors(project_id: str, payload: schemas.DescriptorComposeIn,
                        db: Session = Depends(get_db)):
    """Compose + persist a descriptor CSV from a selection/transform spec."""
    if not db.get(models.Project, project_id):
        raise HTTPException(404, "Project not found")
    if not payload.source_file and dt.get_tool(payload.tool_id) is None:
        raise HTTPException(404, f"未知工具 '{payload.tool_id}'")
    ids = [str(x) for x in payload.identifiers if str(x).strip()]
    if not ids:
        return schemas.DescriptorComposeOut(ok=False, error="没有可计算的取值。")
    if not payload.selected and not payload.derived:
        return schemas.DescriptorComposeOut(ok=False, error="请至少选择一个特征。")

    try:
        raw = _raw_matrix(project_id, payload.tool_id, payload.source_file, ids)
        cleaned, invalid, _ = dt.clean_features(raw)
        if invalid:
            return schemas.DescriptorComposeOut(
                ok=False, invalid=invalid,
                error=f"{len(invalid)} 个取值无法解析，无法保证全覆盖：{invalid[:5]}",
            )
        derived = [d.model_dump() for d in payload.derived]
        out = dt.compose(
            cleaned, selected=payload.selected, derived=derived,
            standardize=payload.standardize, pca_n=payload.pca_n,
        )
    except Exception as exc:  # noqa: BLE001
        return schemas.DescriptorComposeOut(ok=False, error=str(exc))

    if out.shape[1] < 2:
        return schemas.DescriptorComposeOut(ok=False, error="组合后没有有效特征列。")

    filename = f"{project_id}__{_safe_name(payload.out_name)}.csv"
    out.to_csv(DESC_DIR / filename, index=False)
    cols = [c for c in out.columns if c != dt.ID_COL]
    return schemas.DescriptorComposeOut(
        ok=True, filename=filename, id_column=dt.ID_COL, columns=cols,
        n_rows=int(len(out)), preview=_jsonify(out.head(20)),
    )


@router.post("/projects/{project_id}/descriptors/whatif",
             response_model=schemas.WhatIfOut)
def whatif(project_id: str, payload: schemas.SpaceCreate,
           db: Session = Depends(get_db)):
    """Preview the effect of modified descriptors/encoding (non-destructive)."""
    if not db.get(models.Project, project_id):
        raise HTTPException(404, "Project not found")
    try:
        res = services.whatif_descriptors(
            db, project_id, payload.components, payload.model_config_)
    except SpaceValidationError as exc:
        return schemas.WhatIfOut(ok=False, error=str(exc))
    except Exception as exc:  # noqa: BLE001
        return schemas.WhatIfOut(ok=False, error=str(exc))
    return schemas.WhatIfOut(ok=True, **res)


@router.post("/projects/{project_id}/descriptors/apply")
def apply(project_id: str, payload: schemas.SpaceCreate,
          background: BackgroundTasks, db: Session = Depends(get_db)):
    """Permanently rebuild the space with modified descriptors and retrain."""
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    if project.status in ("building", "training", "sampling"):
        raise HTTPException(409, f"Project busy ({project.status}).")
    project.status = "building"
    db.commit()
    task = models.Task(project_id=project_id, kind="apply_descriptors", status="pending")
    db.add(task)
    db.commit()
    db.refresh(task)
    background.add_task(
        services.apply_descriptors_task, project_id, task.id,
        payload.components, payload.model_config_,
    )
    return {"task_id": task.id}
