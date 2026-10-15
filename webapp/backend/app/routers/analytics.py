from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..instance_manager import manager
from .. import models, schemas

router = APIRouter(prefix="/api/projects", tags=["analytics"])


def _all_done_ordered(db, project_id):
    return (
        db.query(models.Experiment)
        .join(models.Round)
        .filter(models.Round.project_id == project_id)
        .filter(models.Experiment.status == "done")
        .filter(models.Experiment.observed_value.isnot(None))
        .order_by(models.Round.round_index, models.Experiment.entered_at)
        .all()
    )


@router.get("/{project_id}/rounds/{round_index}/summary",
            response_model=schemas.RoundSummary)
def round_summary(project_id: str, round_index: int, db: Session = Depends(get_db)):
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    rnd = (
        db.query(models.Round)
        .filter_by(project_id=project_id, round_index=round_index)
        .first()
    )
    if not rnd:
        raise HTTPException(404, "Round not found")
    exps = rnd.experiments
    done = [e for e in exps if e.status == "done" and e.observed_value is not None]
    best = None
    if done:
        vals = [e.observed_value for e in done]
        best = max(vals) if project.direction == "max" else min(vals)
    from .experiments import _exp_out
    return schemas.RoundSummary(
        round_index=round_index, kind=rnd.kind, acq_function=rnd.acq_function,
        batch_size=rnd.batch_size,
        n_machine=len([e for e in exps if e.source == "machine"]),
        n_human=len([e for e in exps if e.source == "human"]),
        n_done=len(done),
        n_skipped=len([e for e in exps if e.status == "skipped"]),
        best_value=best,
        experiments=[_exp_out(e) for e in exps],
    )


@router.get("/{project_id}/rounds", response_model=list[schemas.RoundSummary])
def list_rounds(project_id: str, db: Session = Depends(get_db)):
    """All rounds with their experiments (for browsing / correcting history)."""
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    from .experiments import _exp_out
    rounds = (
        db.query(models.Round)
        .filter_by(project_id=project_id)
        .order_by(models.Round.round_index)
        .all()
    )
    out = []
    for rnd in rounds:
        exps = rnd.experiments
        done = [e for e in exps if e.status == "done" and e.observed_value is not None]
        best = None
        if done:
            vals = [e.observed_value for e in done]
            best = max(vals) if project.direction == "max" else min(vals)
        out.append(schemas.RoundSummary(
            round_index=rnd.round_index, kind=rnd.kind,
            acq_function=rnd.acq_function, batch_size=rnd.batch_size,
            n_machine=len([e for e in exps if e.source == "machine"]),
            n_human=len([e for e in exps if e.source == "human"]),
            n_done=len(done),
            n_skipped=len([e for e in exps if e.status == "skipped"]),
            best_value=best,
            experiments=[_exp_out(e) for e in sorted(
                exps, key=lambda e: (e.source != "machine", e.id))],
        ))
    return out


@router.get("/{project_id}/analytics")
def analytics(project_id: str, db: Session = Depends(get_db)):
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    done = _all_done_ordered(db, project_id)
    direction = project.direction

    # Convergence: running best over experiment sequence
    convergence = []
    running = None
    for i, e in enumerate(done):
        v = e.observed_value
        if running is None:
            running = v
        else:
            running = max(running, v) if direction == "max" else min(running, v)
        convergence.append({"n": i + 1, "value": v, "best": running})

    # Per-round yield distribution & best
    rounds_out = []
    rounds = (
        db.query(models.Round)
        .filter_by(project_id=project_id)
        .order_by(models.Round.round_index)
        .all()
    )
    # Convergence grouped by round: cumulative best after each round completes
    convergence_rounds = []
    run_best = None
    for rnd in rounds:
        vals = [e.observed_value for e in rnd.experiments
                if e.status == "done" and e.observed_value is not None]
        rounds_out.append({
            "round_index": rnd.round_index, "kind": rnd.kind,
            "values": vals,
            "best": (max(vals) if direction == "max" else min(vals)) if vals else None,
        })
        if vals:
            round_best = max(vals) if direction == "max" else min(vals)
            round_mean = sum(vals) / len(vals)
            if run_best is None:
                run_best = round_best
            else:
                run_best = (max(run_best, round_best) if direction == "max"
                            else min(run_best, round_best))
        else:
            round_best = round_mean = None
        convergence_rounds.append({
            "round_index": rnd.round_index, "kind": rnd.kind,
            "n_done": len(vals),
            "round_best": round_best, "round_mean": round_mean,
            "cumulative_best": run_best,
        })

    # Best Top-N
    top = sorted(done, key=lambda e: e.observed_value,
                 reverse=(direction == "max"))[:10]
    top_out = [{
        "domain_index": e.domain_index, "components": e.components_json,
        "observed_value": e.observed_value, "source": e.source,
    } for e in top]

    # Predicted vs observed regression from the fitted model
    regression = None
    try:
        session = manager.get(project_id)
        regression = session.regression()
    except KeyError:
        pass

    return {
        "target": project.target,
        "direction": direction,
        "n_experiments": len(done),
        "best_value": convergence[-1]["best"] if convergence else None,
        "convergence": convergence,
        "convergence_rounds": convergence_rounds,
        "rounds": rounds_out,
        "top": top_out,
        "regression": regression,
    }
