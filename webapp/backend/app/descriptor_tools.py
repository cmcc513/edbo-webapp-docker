"""Pluggable descriptor computation tools + the descriptor composition engine.

Descriptor format spec (shared by *imported* and *computed* descriptor sets)
---------------------------------------------------------------------------
A descriptor set for a reaction component is a table where:
  * the FIRST column is the identifier and must exactly match the component's
    values (e.g. the SMILES / name / label the chemist entered);
  * every remaining column is a NUMERIC feature (float, no missing values);
  * there is exactly one row per component value (full coverage).

This is exactly the shape edbo's ``descriptor_matrices`` expects, so imported
CSVs and tool-composed sets flow through the same code path.

Adding a new tool
-----------------
Subclass :class:`DescriptorTool`, implement ``available`` and ``compute``, then
register it in ``_REGISTRY``. Nothing else needs to change.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

ID_COL = "identifier"


# --------------------------------------------------------------------- plugins
class DescriptorTool:
    """Base class for a descriptor computation backend."""

    id: str = ""
    name: str = ""
    input_kind: str = "smiles"  # smiles | name | any
    kind: str = "compute"       # compute | import

    def available(self) -> bool:  # pragma: no cover - trivial
        return True

    def compute(self, identifiers: list[str]) -> pd.DataFrame:
        """Return a DataFrame: first column ``identifier`` + numeric features.

        Failed identifiers (e.g. unparsable SMILES) should yield an all-NaN
        feature row so the caller can report them.
        """
        raise NotImplementedError


class RDKit2DTool(DescriptorTool):
    id = "rdkit_2d"
    name = "RDKit 2D 描述符"
    input_kind = "smiles"

    def available(self) -> bool:
        try:
            import rdkit  # noqa: F401
            return True
        except Exception:  # noqa: BLE001
            return False

    def compute(self, identifiers: list[str]) -> pd.DataFrame:
        from rdkit import Chem
        from rdkit.Chem import Descriptors

        names = [n for n, _ in Descriptors._descList]
        funcs = [f for _, f in Descriptors._descList]
        rows: list[list[float]] = []
        idx: list[str] = []
        for ident in identifiers:
            idx.append(str(ident))
            mol = Chem.MolFromSmiles(str(ident))
            if mol is None:
                rows.append([np.nan] * len(funcs))
                continue
            vals: list[float] = []
            for f in funcs:
                try:
                    vals.append(float(f(mol)))
                except Exception:  # noqa: BLE001
                    vals.append(np.nan)
            rows.append(vals)
        df = pd.DataFrame(rows, columns=names)
        df.insert(0, ID_COL, idx)
        return df


class Mordred2DTool(DescriptorTool):
    id = "mordred_2d"
    name = "Mordred 2D 描述符"
    input_kind = "smiles"

    def available(self) -> bool:
        try:
            import mordred  # noqa: F401
            return True
        except Exception:  # noqa: BLE001
            return False

    def compute(self, identifiers: list[str]) -> pd.DataFrame:
        from rdkit import Chem
        from mordred import Calculator, descriptors

        calc = Calculator(descriptors, ignore_3D=True)
        mols = [Chem.MolFromSmiles(str(i)) for i in identifiers]
        idx = [str(i) for i in identifiers]
        good = [m for m in mols if m is not None]
        res = calc.pandas(good, quiet=True, nproc=1) if good else pd.DataFrame()
        res = res.apply(pd.to_numeric, errors="coerce").reset_index(drop=True)

        out = pd.DataFrame(np.nan, index=range(len(mols)), columns=res.columns)
        gi = 0
        for i, m in enumerate(mols):
            if m is not None:
                out.iloc[i] = res.iloc[gi].to_numpy()
                gi += 1
        out.insert(0, ID_COL, idx)
        return out.reset_index(drop=True)


_REGISTRY: dict[str, DescriptorTool] = {
    t.id: t for t in (RDKit2DTool(), Mordred2DTool())
}


#: Synthetic entry so the composition panel can offer "import a custom CSV"
#: right next to the computation tools. It is handled specially by the router
#: (upload a file) rather than through ``compute``.
IMPORT_TOOL = {
    "id": "import_csv",
    "name": "导入自定义描述符 (CSV)",
    "input_kind": "any",
    "available": True,
    "kind": "import",
}


def list_tools() -> list[dict]:
    tools = [
        {"id": t.id, "name": t.name, "input_kind": t.input_kind,
         "available": t.available(), "kind": t.kind}
        for t in _REGISTRY.values()
    ]
    tools.append(dict(IMPORT_TOOL))
    return tools


def get_tool(tool_id: str) -> DescriptorTool | None:
    return _REGISTRY.get(tool_id)


# --------------------------------------------------------------- feature table
def clean_features(raw: pd.DataFrame) -> tuple[pd.DataFrame, list[str], dict]:
    """Drop non-informative feature columns and report unusable identifiers.

    Returns (cleaned_df, invalid_identifiers, stats). ``cleaned_df`` keeps the
    identifier column plus numeric features that are finite & non-constant across
    the valid rows. ``stats`` maps feature -> {variance}.
    """
    ids = raw[ID_COL].astype(str)
    feats = raw.drop(columns=[ID_COL]).apply(pd.to_numeric, errors="coerce")

    all_nan_row = feats.isna().all(axis=1)
    invalid = [ids.iloc[i] for i in range(len(ids)) if bool(all_nan_row.iloc[i])]
    valid = feats[~all_nan_row]

    keep: list[str] = []
    stats: dict[str, dict] = {}
    if len(valid) > 0:
        finite = valid.replace([np.inf, -np.inf], np.nan)
        for col in finite.columns:
            s = finite[col]
            if s.notna().all() and s.nunique() > 1:
                keep.append(col)
                stats[col] = {"variance": float(s.var(ddof=0))}

    cleaned = pd.concat([ids, feats[keep]], axis=1)
    return cleaned, invalid, stats


def _apply_op(a: pd.Series, b: pd.Series, op: str) -> pd.Series:
    if op == "add":
        return a + b
    if op == "sub":
        return a - b
    if op == "mul":
        return a * b
    if op == "div":
        return a / b.replace(0, np.nan)
    raise ValueError(f"Unknown op '{op}'")


def compose(
    cleaned: pd.DataFrame,
    selected: list[str],
    derived: list[dict] | None = None,
    standardize: bool = False,
    pca_n: int | None = None,
) -> pd.DataFrame:
    """Build the final descriptor matrix from a composition spec.

    ``derived`` items: {"a": col, "b": col, "op": add|sub|mul|div, "name": str}.
    """
    ids = cleaned[ID_COL].astype(str).reset_index(drop=True)
    cols = [c for c in selected if c in cleaned.columns]
    X = cleaned[cols].astype(float).reset_index(drop=True).copy()

    for d in derived or []:
        a, b, op = d["a"], d["b"], d.get("op", "div")
        name = d.get("name") or f"{a}_{op}_{b}"
        X[name] = _apply_op(
            cleaned[a].astype(float).reset_index(drop=True),
            cleaned[b].astype(float).reset_index(drop=True),
            op,
        )

    X = X.replace([np.inf, -np.inf], np.nan)

    if standardize or pca_n:
        std = X.std(ddof=0).replace(0, 1.0)
        Xs = (X - X.mean()) / std
    else:
        Xs = X

    if pca_n:
        from sklearn.decomposition import PCA

        n = int(min(pca_n, Xs.shape[1], max(1, Xs.shape[0])))
        comps = PCA(n_components=n).fit_transform(Xs.fillna(0.0).to_numpy())
        result = pd.DataFrame(comps, columns=[f"PC{i + 1}" for i in range(n)])
    else:
        result = Xs if standardize else X

    out = pd.concat([ids, result.reset_index(drop=True)], axis=1)
    return out


# ------------------------------------------------------------------ validation
def validate_descriptor_df(df: pd.DataFrame, required_values: list[Any]) -> dict:
    """Validate a descriptor table against the spec and required coverage."""
    errors: list[str] = []
    if df.shape[1] < 2:
        errors.append("描述符表至少需要标识符列 + 1 个特征列。")
        return {"ok": False, "errors": errors, "n_features": 0}

    id_col = df.columns[0]
    ids = set(df[id_col].astype(str))
    feats = df.drop(columns=[id_col])
    non_numeric = [c for c in feats.columns
                   if not pd.api.types.is_numeric_dtype(pd.to_numeric(feats[c], errors="coerce"))]
    coerced = feats.apply(pd.to_numeric, errors="coerce")
    if coerced.isna().any().any():
        bad = [c for c in coerced.columns if coerced[c].isna().any()]
        errors.append(f"存在非数值/缺失特征列：{bad[:5]}")
    if non_numeric:
        errors.append(f"非数值列：{non_numeric[:5]}")

    missing = [str(v) for v in required_values if str(v) not in ids]
    if missing:
        errors.append(f"{len(missing)} 个取值在描述符表中缺失：{missing[:5]}")

    return {"ok": len(errors) == 0, "errors": errors,
            "n_features": int(feats.shape[1])}
