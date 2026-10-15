from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..instance_manager import manager
from ..rules import matched_rules
from .. import models, schemas, services

router = APIRouter(prefix="/api/projects", tags=["experiments"])


def _exp_out(e: models.Experiment) -> schemas.ProposalOut:
    return schemas.ProposalOut(
        id=e.id, domain_index=e.domain_index, source=e.source, status=e.status,
        components=e.components_json, predicted_mean=e.predicted_mean,
        predicted_var=e.predicted_var, observed_value=e.observed_value, note=e.note,
        provenance=e.provenance_json,
    )


def _get_round(db, project_id, round_index):
    return (
        db.query(models.Round)
        .filter_by(project_id=project_id, round_index=round_index)
        .first()
    )


@router.get("/{project_id}/rounds/{round_index}/experiments",
            response_model=list[schemas.ProposalOut])
def list_round_experiments(project_id: str, round_index: int,
                           db: Session = Depends(get_db)):
    rnd = _get_round(db, project_id, round_index)
    if not rnd:
        raise HTTPException(404, "Round not found")
    return [_exp_out(e) for e in rnd.experiments]


@router.get("/{project_id}/proposals", response_model=list[schemas.ProposalOut])
def current_proposals(project_id: str, db: Session = Depends(get_db)):
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    rnd = _get_round(db, project_id, project.current_round)
    if not rnd:
        return []
    return [_exp_out(e) for e in rnd.experiments]


@router.post("/{project_id}/rounds/{round_index}/machine-results")
def submit_machine_results(project_id: str, round_index: int,
                           payload: schemas.MachineResultsIn,
                           db: Session = Depends(get_db)):
    """Fill in yields for machine proposals. Empty value => skipped."""
    rnd = _get_round(db, project_id, round_index)
    if not rnd:
        raise HTTPException(404, "Round not found")
    by_id = {e.id: e for e in rnd.experiments}
    updated = 0
    for item in payload.results:
        e = by_id.get(item.experiment_id)
        if not e or e.source != "machine":
            continue
        if item.observed_value is None:
            e.status = "skipped"
            e.observed_value = None
        else:
            e.status = "done"
            e.observed_value = item.observed_value
            e.entered_by = payload.entered_by
            e.entered_at = datetime.utcnow()
        e.note = item.note
        updated += 1
    db.commit()
    return {"ok": True, "updated": updated}


@router.post("/{project_id}/rounds/{round_index}/human-conditions",
             response_model=schemas.HumanExperimentResult)
def add_human_conditions(project_id: str, round_index: int,
                         payload: schemas.HumanConditionsIn,
                         db: Session = Depends(get_db)):
    """Add chemist-chosen conditions to the current run-list. Yield is optional
    (enter later). Conditions must lie in the reaction space; rule violations are
    allowed but reported as warnings (human override)."""
    project = db.get(models.Project, project_id)
    rnd = _get_round(db, project_id, round_index)
    if not rnd:
        raise HTTPException(404, "Round not found")
    try:
        session = manager.get(project_id)
    except KeyError:
        raise HTTPException(409, "Reaction space not built yet.")

    rules = (project.rules_json or []) if project else []
    existing = {e.domain_index for e in rnd.experiments}
    accepted, rejected, warnings = 0, [], []
    for item in payload.experiments:
        di = session.resolve_domain_index(item.components)
        if di is None:
            rejected.append({"components": item.components,
                             "reason": "组合不在反应空间内。"})
            continue
        if di in existing:
            continue
        hit = matched_rules(item.components, rules)
        if hit:
            warnings.append({"components": item.components, "rules": hit})
        has_val = item.observed_value is not None
        provenance = {
            "source": "human",
            "adopted_from": "manual",
            "by": payload.entered_by,
            "at": datetime.utcnow().isoformat(),
            **(services.descriptor_snapshot(project) if project else {}),
        }
        if hit:
            provenance["rule_overrides"] = hit
        exp = models.Experiment(
            round_id=rnd.id, domain_index=di, source="human",
            status="done" if has_val else "proposed",
            components_json=item.components,
            observed_value=item.observed_value,
            note=item.note, entered_by=payload.entered_by,
            entered_at=datetime.utcnow() if has_val else None,
            provenance_json=provenance,
        )
        db.add(exp)
        existing.add(di)
        accepted += 1
    db.commit()
    return schemas.HumanExperimentResult(
        ok=len(rejected) == 0, accepted=accepted,
        rejected=rejected, warnings=warnings,
    )


@router.patch("/{project_id}/experiments/{experiment_id}",
              response_model=schemas.EditExperimentOut)
def edit_experiment(project_id: str, experiment_id: str,
                    payload: schemas.EditExperimentIn,
                    db: Session = Depends(get_db)):
    """Correct a previously entered yield (fix data-entry mistakes).

    If the experiment had already been fed to the optimizer, the model is
    rebuilt from the corrected data and refit. Past proposals are not changed.
    """
    exp = db.get(models.Experiment, experiment_id)
    if not exp:
        raise HTTPException(404, "Experiment not found")
    rnd = db.get(models.Round, exp.round_id)
    if not rnd or rnd.project_id != project_id:
        raise HTTPException(404, "Experiment not in project")

    was_imported = bool(exp.imported)
    if payload.observed_value is None:
        # blank out -> treat as not run
        exp.status = "skipped"
        exp.observed_value = None
        if exp.source == "human":
            # human rows are only meaningful when observed; drop from optimizer
            exp.imported = 0
    else:
        exp.status = "done"
        exp.observed_value = payload.observed_value
        exp.entered_by = payload.entered_by
        exp.entered_at = datetime.utcnow()
    if payload.note is not None:
        exp.note = payload.note
    db.commit()

    # Retrain only when the change affects data already given to the optimizer.
    retrained = False
    if was_imported or exp.imported:
        retrained = services.retrain_from_db(db, project_id)

    db.refresh(exp)
    return schemas.EditExperimentOut(
        ok=True, retrained=retrained, experiment=_exp_out(exp)
    )


@router.delete("/{project_id}/experiments/{experiment_id}")
def delete_experiment(project_id: str, experiment_id: str,
                      db: Session = Depends(get_db)):
    """Remove an experiment from the run-list. Only *proposed* (not-yet-run)
    experiments can be deleted — completed data is protected."""
    exp = db.get(models.Experiment, experiment_id)
    if not exp:
        raise HTTPException(404, "Experiment not found")
    rnd = db.get(models.Round, exp.round_id)
    if not rnd or rnd.project_id != project_id:
        raise HTTPException(404, "Experiment not in project")
    if exp.status != "proposed":
        raise HTTPException(409, "只能移除尚未执行(proposed)的实验；已完成数据受保护。")
    db.delete(exp)
    db.commit()
    return {"ok": True}


@router.post("/{project_id}/predict", response_model=schemas.PredictOut)
def predict(project_id: str, payload: schemas.PredictIn,
            db: Session = Depends(get_db)):
    """Predict yield (mean + std) for an arbitrary point using the trained model."""
    if not db.get(models.Project, project_id):
        raise HTTPException(404, "Project not found")
    try:
        session = manager.get(project_id)
    except KeyError:
        raise HTTPException(409, "Reaction space not built yet.")
    res = session.predict(payload.components)
    if res is None or "error" in res:
        err = (res or {}).get("error", "unknown")
        msg = {
            "out_of_space": "该组合不在反应空间内。",
            "no_model": "模型尚未训练，请先运行一轮优化。",
        }.get(err, err)
        return schemas.PredictOut(ok=False, error=msg)
    return schemas.PredictOut(
        ok=True, mean=res["mean"], std=res["std"], domain_index=res["domain_index"]
    )


@router.post("/{project_id}/rounds/{round_index}/human-experiments",
             response_model=schemas.HumanExperimentResult)
def submit_human_experiments(project_id: str, round_index: int,
                             payload: schemas.HumanExperimentsIn,
                             db: Session = Depends(get_db)):
    """Add chemist-decided experiments. Each combination must lie in the space."""
    rnd = _get_round(db, project_id, round_index)
    if not rnd:
        raise HTTPException(404, "Round not found")
    try:
        session = manager.get(project_id)
    except KeyError:
        raise HTTPException(409, "Reaction space not built yet.")

    accepted = 0
    rejected: list[dict] = []
    for item in payload.experiments:
        domain_index = session.resolve_domain_index(item.components)
        if domain_index is None:
            rejected.append({
                "components": item.components,
                "reason": "Combination not found in reaction space.",
            })
            continue
        exp = models.Experiment(
            round_id=rnd.id, domain_index=domain_index, source="human",
            status="done", components_json=item.components,
            observed_value=item.observed_value, note=item.note,
            entered_by=payload.entered_by, entered_at=datetime.utcnow(),
        )
        db.add(exp)
        accepted += 1
    db.commit()
    return schemas.HumanExperimentResult(
        ok=len(rejected) == 0, accepted=accepted, rejected=rejected
    )
