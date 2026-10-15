"""Configuration of the three benchmark reactions used for simulation tests.

Each reaction exercises a different descriptor / encoding strategy:
  * Suzuki           -> DFT descriptors (ligand) + one-hot (others)
  * Buchwald amination-> Mordred descriptors (ligand + aryl halide) + one-hot
  * Direct arylation -> DFT (ligand) + one-hot (base/solvent) + numeric (conc/temp)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import pandas as pd

DATA = Path(__file__).resolve().parents[4] / "experiments" / "data"


@dataclass
class Comp:
    db_col: str                     # column name in the experiment_index (== API key)
    encoding: str                   # ohe | numeric | descriptor
    descriptor_path: str | None = None
    smiles_col: str | None = None   # identifier column inside the descriptor CSV
    drop: list[str] = field(default_factory=list)


@dataclass
class Reaction:
    key: str
    name: str
    index_csv: str
    yield_col: str
    components: list[Comp]
    acq: str
    batch: int
    init_batch: int
    rounds: int
    seed: int
    model: str = "GP"
    init_method: str = "rand"


def prep_descriptor(comp: Comp, db_col: str) -> pd.DataFrame:
    """Load a descriptor CSV, put the SMILES identifier first and rename it to
    match the experiment_index column so the built space aligns with the DB."""
    df = pd.read_csv(comp.descriptor_path)
    df = df.drop(columns=[c for c in comp.drop if c in df.columns])
    cols = [comp.smiles_col] + [c for c in df.columns if c != comp.smiles_col]
    df = df[cols].rename(columns={comp.smiles_col: db_col})
    return df


def component_values(reaction: Reaction, comp: Comp) -> list:
    """Selectable identifiers for a component (aligned with the yield DB)."""
    if comp.encoding == "descriptor":
        df = prep_descriptor(comp, comp.db_col)
        return df[comp.db_col].astype(str).tolist()
    idx = pd.read_csv(reaction.index_csv)
    vals = idx[comp.db_col].drop_duplicates().tolist()
    if comp.encoding == "numeric":
        return [float(v) for v in sorted(vals)]
    return [str(v) for v in vals]


REACTIONS: dict[str, Reaction] = {
    "suzuki": Reaction(
        key="suzuki",
        name="Suzuki 偶联 (DFT 描述符)",
        index_csv=str(DATA / "suzuki" / "experiment_index.csv"),
        yield_col="yield",
        acq="EI", batch=5, init_batch=5, rounds=6, seed=0,
        components=[
            Comp("Electrophile_SMILES", "ohe"),
            Comp("Nucleophile_SMILES", "ohe"),
            Comp(
                "Ligand_SMILES", "descriptor",
                descriptor_path=str(DATA / "suzuki" / "ligand-random_dft.csv"),
                smiles_col="ligand_SMILES", drop=["ligand_file_name"],
            ),
            Comp("Base_SMILES", "ohe"),
            Comp("Solvent_SMILES", "ohe"),
        ],
    ),
    "amination": Reaction(
        key="amination",
        name="Buchwald–Hartwig 胺化 (Mordred 描述符)",
        index_csv=str(DATA / "aryl_amination" / "experiment_index.csv"),
        yield_col="yield",
        acq="TS", batch=4, init_batch=4, rounds=6, seed=1,
        components=[
            Comp(
                "Aryl_halide_SMILES", "descriptor",
                descriptor_path=str(DATA / "aryl_amination" / "aryl_halide_mordred.csv"),
                smiles_col="aryl_halide_SMILES",
            ),
            Comp("Additive_SMILES", "ohe"),
            Comp("Base_SMILES", "ohe"),
            Comp(
                "Ligand_SMILES", "descriptor",
                descriptor_path=str(DATA / "aryl_amination" / "ligand_mordred.csv"),
                smiles_col="ligand_SMILES",
            ),
        ],
    ),
    "arylation": Reaction(
        key="arylation",
        name="C–H 直接芳基化 (混合编码 DFT+数值)",
        index_csv=str(DATA / "direct_arylation" / "experiment_index.csv"),
        yield_col="yield",
        acq="EI-TS", batch=6, init_batch=6, rounds=5, seed=2,
        components=[
            Comp("Base_SMILES", "ohe"),
            Comp(
                "Ligand_SMILES", "descriptor",
                descriptor_path=str(DATA / "direct_arylation" / "ligand-random_dft.csv"),
                smiles_col="ligand_SMILES", drop=["ligand_file_name"],
            ),
            Comp("Solvent_SMILES", "ohe"),
            Comp("Concentration", "numeric"),
            Comp("Temp_C", "numeric"),
        ],
    ),
}
