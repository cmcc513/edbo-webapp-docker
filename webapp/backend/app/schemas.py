"""Pydantic request/response models."""
from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel


# --------------------------------------------------------------------- projects
class ProjectCreate(BaseModel):
    name: str
    target: str = "yield"
    direction: str = "max"
    created_by: str = "anonymous"


class ProjectOut(BaseModel):
    id: str
    name: str
    target: str
    direction: str
    status: str
    current_round: int
    space_size: Optional[int] = None
    created_by: Optional[str] = None
    n_experiments: int = 0
    best_value: Optional[float] = None
    archived: bool = False
    pending_prior: int = 0

    class Config:
        from_attributes = True


# ----------------------------------------------------------------- rebuild
class RebuildIn(BaseModel):
    name: Optional[str] = None      # defaults to "<orig> (重建)"
    copy_data: bool = True          # copy completed experiments as prior import
    # Edited configuration confirmed in the rebuild wizard. When empty, the
    # source project's stored configuration is cloned as-is.
    components: list["ComponentSpec"] = []
    model_config_: Optional["ModelConfig"] = None


class ComponentConfig(BaseModel):
    name: str
    values: list[Any] = []
    encoding: str = "ohe"
    descriptor_file: Optional[str] = None
    id_column: Optional[str] = None


class ProjectConfigOut(BaseModel):
    components: list[ComponentConfig] = []
    model: str = "GP"
    init_method: str = "rand"


# ------------------------------------------------------------------------ space
class ComponentSpec(BaseModel):
    name: str
    values: list[Any] = []
    encoding: str = "ohe"  # ohe | numeric | mordred | resolve | descriptor
    descriptor_file: Optional[str] = None  # stored filename for 'descriptor'
    id_column: Optional[str] = None        # identifier column in descriptor CSV


class ModelConfig(BaseModel):
    model: str = "GP"
    init_method: str = "rand"


class SpaceCreate(BaseModel):
    components: list[ComponentSpec]
    model_config_: ModelConfig = ModelConfig()


class SpaceValidateOut(BaseModel):
    ok: bool
    space_size: int
    warnings: list[str] = []
    errors: list[str] = []


# ------------------------------------------------------------------- optimization
class PriorExperiment(BaseModel):
    components: dict[str, Any]
    observed_value: float


class InitRequest(BaseModel):
    seed: Optional[int] = None
    batch_size: int = 5
    init_method: str = "rand"  # rand | pam | kmeans | import
    prior_experiments: list[PriorExperiment] = []


# ------------------------------------------------------------- recommendations
class RecommendIn(BaseModel):
    acq_function: str = "EI"
    top_n: int = 20
    jitter: float = 0.01


class RecommendItem(BaseModel):
    domain_index: int
    components: dict[str, Any]
    predicted_mean: Optional[float] = None
    predicted_var: Optional[float] = None
    acq_score: Optional[float] = None


class RecommendOut(BaseModel):
    ok: bool
    reason: Optional[str] = None
    acq_function: str
    items: list[RecommendItem] = []


class AdoptItem(BaseModel):
    domain_index: int
    rank: Optional[int] = None          # 1-based rank in the leaderboard
    acq_score: Optional[float] = None


class AdoptIn(BaseModel):
    domain_indices: list[int] = []      # legacy: indices without rank context
    items: list[AdoptItem] = []         # preferred: carries rank + score
    acq_function: Optional[str] = None
    acq_params: dict[str, Any] = {}
    adopted_by: str = "anonymous"


class NewRoundOut(BaseModel):
    ok: bool
    round_index: int
    skipped: int = 0


# ----------------------------------------------------------------- descriptors
class DescriptorComputeIn(BaseModel):
    tool_id: str
    identifiers: list[str] = []


class DescriptorComputeOut(BaseModel):
    ok: bool
    id_column: str = "identifier"
    columns: list[str] = []
    rows: list[dict[str, Any]] = []
    stats: dict[str, Any] = {}
    invalid: list[str] = []
    source_file: Optional[str] = None  # raw token for import mode (reused by compose)
    error: Optional[str] = None


class DerivedFeature(BaseModel):
    a: str
    b: str
    op: str = "div"           # add | sub | mul | div
    name: Optional[str] = None


class DescriptorComposeIn(BaseModel):
    tool_id: str
    identifiers: list[str] = []
    selected: list[str] = []
    derived: list[DerivedFeature] = []
    standardize: bool = False
    pca_n: Optional[int] = None
    out_name: str = "descriptor"   # used to name the saved CSV (e.g. component)
    source_file: Optional[str] = None  # import mode: raw token from /descriptors/import


class DescriptorComposeOut(BaseModel):
    ok: bool
    filename: Optional[str] = None
    id_column: str = "identifier"
    columns: list[str] = []
    n_rows: int = 0
    preview: list[dict[str, Any]] = []
    invalid: list[str] = []
    error: Optional[str] = None


class WhatIfOut(BaseModel):
    ok: bool
    n_obs: int = 0
    space_size: Optional[int] = None
    current: Optional[dict[str, Any]] = None
    whatif: Optional[dict[str, Any]] = None
    error: Optional[str] = None


# --------------------------------------------------------------------- rules
class RuleClause(BaseModel):
    component: str
    op: str = "eq"  # eq | ne | in | nin | ge | le | gt | lt
    value: Any = None


class Rule(BaseModel):
    id: Optional[str] = None
    name: str = ""
    active: bool = True
    clauses: list[RuleClause] = []


class RulesIn(BaseModel):
    rules: list[Rule] = []


class RulesOut(BaseModel):
    rules: list[Rule] = []
    excluded_count: Optional[int] = None


class RunRequest(BaseModel):
    acq_function: str = "EI"
    batch_size: int = 5
    acq_params: dict[str, Any] = {}


class TaskOut(BaseModel):
    id: str
    kind: str
    status: str
    progress: float
    message: Optional[str] = None
    error: Optional[str] = None

    class Config:
        from_attributes = True


# ------------------------------------------------------------------- experiments
class ProposalOut(BaseModel):
    id: str
    domain_index: int
    source: str
    status: str
    components: dict[str, Any]
    predicted_mean: Optional[float] = None
    predicted_var: Optional[float] = None
    observed_value: Optional[float] = None
    note: Optional[str] = None
    provenance: Optional[dict[str, Any]] = None


class MachineResultItem(BaseModel):
    experiment_id: str
    observed_value: Optional[float] = None  # None/empty -> skipped
    note: Optional[str] = None


class MachineResultsIn(BaseModel):
    results: list[MachineResultItem]
    entered_by: str = "anonymous"


class HumanExperimentItem(BaseModel):
    components: dict[str, Any]
    observed_value: float
    note: Optional[str] = None


class HumanExperimentsIn(BaseModel):
    experiments: list[HumanExperimentItem]
    entered_by: str = "anonymous"


class HumanConditionItem(BaseModel):
    components: dict[str, Any]
    observed_value: Optional[float] = None  # None -> add to run-list without yield
    note: Optional[str] = None


class HumanConditionsIn(BaseModel):
    experiments: list[HumanConditionItem]
    entered_by: str = "anonymous"


class HumanExperimentResult(BaseModel):
    ok: bool
    accepted: int
    rejected: list[dict] = []
    warnings: list[dict] = []


# ------------------------------------------------------------------ edit / predict
class EditExperimentIn(BaseModel):
    observed_value: Optional[float] = None   # None -> mark as skipped / remove
    note: Optional[str] = None
    entered_by: str = "anonymous"


class EditExperimentOut(BaseModel):
    ok: bool
    retrained: bool
    experiment: ProposalOut


class PredictIn(BaseModel):
    components: dict[str, Any]


class PredictOut(BaseModel):
    ok: bool
    mean: Optional[float] = None
    std: Optional[float] = None
    domain_index: Optional[int] = None
    error: Optional[str] = None


# --------------------------------------------------------------------- analytics
class RoundSummary(BaseModel):
    round_index: int
    kind: str
    acq_function: Optional[str] = None
    batch_size: Optional[int] = None
    n_machine: int
    n_human: int
    n_done: int
    n_skipped: int
    best_value: Optional[float] = None
    experiments: list[ProposalOut] = []
