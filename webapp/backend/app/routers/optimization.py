from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from ..database import get_db
from ..instance_manager import manager
from ..rules import is_excluded
from .. import models, schemas, services

router = APIRouter(prefix="/api/projects", tags=["optimization"])

BUSY = ("building", "training", "sampling")


@router.post("/{project_id}/init")
def init(
    project_id: str,
    payload: schemas.InitRequest,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
):
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    if project.status == "created":
        raise HTTPException(409, "Build the reaction space first.")
    if project.status in BUSY:
        raise HTTPException(409, f"Project busy ({project.status}).")

    project.status = "sampling"
    db.commit()
    task = models.Task(project_id=project_id, kind="init", status="pending")
    db.add(task)
    db.commit()
    db.refresh(task)

    prior = [p.model_dump() for p in payload.prior_experiments]
    background.add_task(
        services.init_task, project_id, task.id,
        payload.seed, payload.batch_size, payload.init_method, prior,
    )
    return {"task_id": task.id}


@router.post("/{project_id}/recommendations", response_model=schemas.RecommendOut)
def recommendations(
    project_id: str, payload: schemas.RecommendIn, db: Session = Depends(get_db)
):
    """Live ranked leaderboard of candidate conditions for a chosen acquisition
    function. Trains on all completed experiments; excludes already-run points,
    the current run-list, and rule-excluded conditions. Does not persist."""
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    try:
        session, trained = services.ensure_model(db, project_id)
    except KeyError:
        raise HTTPException(409, "Reaction space not built yet.")
    if not trained:
        return schemas.RecommendOut(
            ok=False, reason="需要至少一个已完成实验才能训练模型给出推荐。",
            acq_function=payload.acq_function, items=[],
        )

    exclude = {
        e.domain_index
        for e in db.query(models.Experiment).join(models.Round)
        .filter(models.Round.project_id == project_id)
        .filter(models.Experiment.status.in_(("done", "proposed", "skipped")))
        .all()
    }
    rules = project.rules_json or []
    items = session.leaderboard(
        acq_function=payload.acq_function,
        top_n=payload.top_n,
        exclude_indices=exclude,
        exclude_fn=(lambda c: is_excluded(c, rules)) if rules else None,
        jitter=payload.jitter,
    )
    return schemas.RecommendOut(
        ok=True, acq_function=payload.acq_function,
        items=[schemas.RecommendItem(**it) for it in items],
    )


@router.post("/{project_id}/rounds/{round_index}/adopt",
             response_model=list[schemas.ProposalOut])
def adopt(
    project_id: str, round_index: int, payload: schemas.AdoptIn,
    db: Session = Depends(get_db),
):
    """Adopt selected leaderboard candidates into the current round's run-list."""
    from .experiments import _exp_out

    rnd = (
        db.query(models.Round)
        .filter_by(project_id=project_id, round_index=round_index)
        .first()
    )
    if not rnd:
        raise HTTPException(404, "Round not found")
    try:
        session = manager.get(project_id)
    except KeyError:
        raise HTTPException(409, "Reaction space not built yet.")

    project = db.get(models.Project, project_id)
    # Accept either the rich `items` (with rank/score) or legacy `domain_indices`.
    rank_by_idx: dict[int, dict] = {}
    if payload.items:
        indices = [it.domain_index for it in payload.items]
        rank_by_idx = {
            it.domain_index: {"rank": it.rank, "acq_score": it.acq_score}
            for it in payload.items
        }
    else:
        indices = payload.domain_indices

    snapshot = services.descriptor_snapshot(project) if project else {}
    now = datetime.utcnow().isoformat()
    existing = {e.domain_index for e in rnd.experiments}
    infos = session.points_info(indices)
    created = []
    for info in infos:
        di = info["domain_index"]
        if di in existing:
            continue
        ctx = rank_by_idx.get(di, {})
        provenance = {
            "source": "machine",
            "adopted_from": "leaderboard",
            "acq_function": payload.acq_function,
            "acq_params": payload.acq_params or {},
            "rank": ctx.get("rank"),
            "acq_score": ctx.get("acq_score"),
            "by": payload.adopted_by,
            "at": now,
            **snapshot,
        }
        exp = models.Experiment(
            round_id=rnd.id, domain_index=di, source="machine",
            status="proposed", components_json=info["components"],
            predicted_mean=info.get("predicted_mean"),
            predicted_var=info.get("predicted_var"),
            provenance_json=provenance,
        )
        db.add(exp)
        created.append(exp)
    db.commit()
    for e in created:
        db.refresh(e)
    return [_exp_out(e) for e in created]


@router.post("/{project_id}/rounds/new", response_model=schemas.NewRoundOut)
def new_round(project_id: str, db: Session = Depends(get_db)):
    """Finalize the current round (unrun proposals -> skipped) and open a new one."""
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    if project.current_round < 0:
        raise HTTPException(409, "Initialize the project first.")

    current = (
        db.query(models.Round)
        .filter_by(project_id=project_id, round_index=project.current_round)
        .first()
    )
    skipped = 0
    if current:
        for e in current.experiments:
            if e.status == "proposed":
                e.status = "skipped"
                skipped += 1
        current.imported_at = datetime.utcnow()
    new_index = project.current_round + 1
    db.add(models.Round(
        project_id=project_id, round_index=new_index, kind="bo",
    ))
    project.current_round = new_index
    project.status = "awaiting_results"
    db.commit()
    return schemas.NewRoundOut(ok=True, round_index=new_index, skipped=skipped)


@router.post("/{project_id}/run")
def run(
    project_id: str,
    payload: schemas.RunRequest,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
):
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    if project.current_round < 0:
        raise HTTPException(409, "Initialize the project first.")
    if project.status in BUSY:
        raise HTTPException(409, f"Project busy ({project.status}).")

    project.status = "training"
    db.commit()
    task = models.Task(project_id=project_id, kind="run", status="pending")
    db.add(task)
    db.commit()
    db.refresh(task)

    background.add_task(
        services.import_and_run_task, project_id, task.id,
        payload.acq_function, payload.batch_size, payload.acq_params,
    )
    return {"task_id": task.id}


@router.get("/{project_id}/tasks/{task_id}", response_model=schemas.TaskOut)
def get_task(project_id: str, task_id: str, db: Session = Depends(get_db)):
    task = db.get(models.Task, task_id)
    if not task or task.project_id != project_id:
        raise HTTPException(404, "Task not found")
    return task
