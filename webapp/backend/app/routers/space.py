import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks
from sqlalchemy.orm import Session

from ..database import get_db
from ..config import DESC_DIR, MAX_SPACE_SIZE
from ..instance_manager import manager
from .. import models, schemas, services

router = APIRouter(prefix="/api/projects", tags=["space"])


@router.post("/{project_id}/descriptors")
async def upload_descriptor(
    project_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)
):
    """Upload a descriptor CSV (e.g. DFT) and return its columns for mapping."""
    if not db.get(models.Project, project_id):
        raise HTTPException(404, "Project not found")
    filename = f"{project_id}__{file.filename}"
    dest = DESC_DIR / filename
    content = await file.read()
    dest.write_bytes(content)
    try:
        df = pd.read_csv(dest)
    except Exception as exc:  # noqa: BLE001
        dest.unlink(missing_ok=True)
        raise HTTPException(400, f"Could not parse CSV: {exc}")
    return {
        "filename": filename,
        "columns": list(df.columns),
        "id_column": df.columns[0],
        "n_rows": len(df),
        "identifiers": df.iloc[:, 0].astype(str).tolist(),
    }


@router.post("/{project_id}/import/preview")
async def import_preview(
    project_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)
):
    """Parse an uploaded results CSV and return its columns + rows so the user
    can map columns to components + yield before importing prior experiments."""
    if not db.get(models.Project, project_id):
        raise HTTPException(404, "Project not found")
    import io
    content = await file.read()
    try:
        df = pd.read_csv(io.BytesIO(content))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Could not parse CSV: {exc}")
    df = df.where(pd.notnull(df), None)
    rows = df.astype(object).where(pd.notnull(df), None).to_dict(orient="records")
    return {
        "columns": list(df.columns),
        "rows": rows[:2000],
        "n_rows": len(df),
    }


@router.post("/{project_id}/space/validate", response_model=schemas.SpaceValidateOut)
def validate_space(
    project_id: str, payload: schemas.SpaceCreate, db: Session = Depends(get_db)
):
    warnings: list[str] = []
    errors: list[str] = []
    size = 1
    for c in payload.components:
        n = len([v for v in c.values]) if c.values else 0
        if n == 0:
            errors.append(f"Component '{c.name}' has no values.")
            continue
        size *= n
        # descriptor coverage check
        if c.encoding == "descriptor" and c.descriptor_file:
            path = DESC_DIR / c.descriptor_file
            if not path.exists():
                errors.append(f"Descriptor file for '{c.name}' not found.")
            else:
                df = pd.read_csv(path)
                idcol = c.id_column or df.columns[0]
                ids = set(df[idcol].astype(str))
                missing = [str(v) for v in c.values if str(v) not in ids]
                if missing:
                    errors.append(
                        f"'{c.name}': {len(missing)} value(s) missing in descriptor "
                        f"CSV: {missing[:5]}"
                    )
    if size > MAX_SPACE_SIZE:
        errors.append(f"Space too large ({size} > {MAX_SPACE_SIZE}).")
    elif size > 100_000:
        warnings.append(f"Large space ({size} points); building may be slow.")
    return schemas.SpaceValidateOut(
        ok=len(errors) == 0, space_size=size, warnings=warnings, errors=errors
    )


@router.post("/{project_id}/space")
def build_space(
    project_id: str,
    payload: schemas.SpaceCreate,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
):
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    if project.status in ("building", "training"):
        raise HTTPException(409, f"Project busy ({project.status}).")

    # Persist configuration
    project.components_json = {c.name: c.values for c in payload.components}
    project.encoding_json = {c.name: c.encoding for c in payload.components}
    project.descriptors_json = {
        c.name: {"filename": c.descriptor_file, "id_column": c.id_column}
        for c in payload.components if c.encoding == "descriptor"
    }
    project.model_config_json = payload.model_config_.model_dump()
    project.status = "building"
    db.commit()

    task = models.Task(project_id=project_id, kind="build_space", status="pending")
    db.add(task)
    db.commit()
    db.refresh(task)

    background.add_task(
        services.build_space_task, project_id, task.id,
        payload.components, payload.model_config_,
    )
    return {"task_id": task.id}


@router.get("/{project_id}/components")
def get_components(project_id: str, db: Session = Depends(get_db)):
    """Selectable component values (for the human-experiment entry panel)."""
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    try:
        session = manager.get(project_id)
    except KeyError:
        raise HTTPException(409, "Reaction space not built yet.")
    return {"components": session.component_options(), "target": project.target}
