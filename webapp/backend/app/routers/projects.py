from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models, schemas, services

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _to_out(db, p: models.Project) -> schemas.ProjectOut:
    return schemas.ProjectOut(
        id=p.id, name=p.name, target=p.target, direction=p.direction,
        status=p.status, current_round=p.current_round, space_size=p.space_size,
        created_by=p.created_by,
        n_experiments=services.count_done(db, p.id),
        best_value=services.best_value(db, p),
        archived=p.archived_at is not None,
        pending_prior=len(p.pending_prior_json or []),
    )


@router.post("", response_model=schemas.ProjectOut)
def create_project(payload: schemas.ProjectCreate, db: Session = Depends(get_db)):
    p = models.Project(
        name=payload.name, target=payload.target,
        direction=payload.direction, created_by=payload.created_by,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return _to_out(db, p)


@router.get("", response_model=list[schemas.ProjectOut])
def list_projects(archived: bool = False, db: Session = Depends(get_db)):
    """List projects. By default only active ones; ?archived=true for the
    archive view."""
    q = db.query(models.Project)
    if archived:
        q = q.filter(models.Project.archived_at.isnot(None))
    else:
        q = q.filter(models.Project.archived_at.is_(None))
    return [_to_out(db, p) for p in q.order_by(models.Project.created_at.desc()).all()]


@router.get("/{project_id}", response_model=schemas.ProjectOut)
def get_project(project_id: str, db: Session = Depends(get_db)):
    p = db.get(models.Project, project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    return _to_out(db, p)


@router.get("/{project_id}/config", response_model=schemas.ProjectConfigOut)
def get_config(project_id: str, db: Session = Depends(get_db)):
    """Reconstruct the space/model configuration for prefilling the wizard."""
    p = db.get(models.Project, project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    comps_vals = p.components_json or {}
    enc = p.encoding_json or {}
    desc = p.descriptors_json or {}
    components = []
    for name, values in comps_vals.items():
        d = desc.get(name) or {}
        components.append(schemas.ComponentConfig(
            name=name, values=values,
            encoding=enc.get(name, "ohe"),
            descriptor_file=d.get("filename"),
            id_column=d.get("id_column"),
        ))
    mc = p.model_config_json or {}
    return schemas.ProjectConfigOut(
        components=components,
        model=mc.get("model", "GP"),
        init_method=mc.get("init_method", "rand"),
    )


@router.get("/{project_id}/pending-prior", response_model=list[schemas.PriorExperiment])
def get_pending_prior(project_id: str, db: Session = Depends(get_db)):
    """Completed experiments copied from a rebuild source, awaiting import."""
    p = db.get(models.Project, project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    return [schemas.PriorExperiment(**it) for it in (p.pending_prior_json or [])]


def _source_components(src: models.Project) -> list[schemas.ComponentSpec]:
    """Reconstruct ComponentSpecs from a project's stored configuration."""
    comps_vals = src.components_json or {}
    enc = src.encoding_json or {}
    desc = src.descriptors_json or {}
    out: list[schemas.ComponentSpec] = []
    for name, values in comps_vals.items():
        d = desc.get(name) or {}
        out.append(schemas.ComponentSpec(
            name=name, values=values, encoding=enc.get(name, "ohe"),
            descriptor_file=d.get("filename"), id_column=d.get("id_column"),
        ))
    return out


@router.post("/{project_id}/rebuild")
def rebuild_project(project_id: str, background: BackgroundTasks,
                    payload: schemas.RebuildIn = schemas.RebuildIn(),
                    db: Session = Depends(get_db)):
    """Create a rebuilt project *on confirmation*: clone the (possibly edited)
    configuration and optionally the completed results into a fresh project, then
    build the reaction space. The project only appears after this call, so the
    rebuild wizard can be abandoned without leaving a stray draft behind.

    Returns ``{project_id, task_id}`` — poll the task then open the new project.
    """
    import shutil
    from ..config import DESC_DIR

    src = db.get(models.Project, project_id)
    if not src:
        raise HTTPException(404, "Project not found")

    # Use the edited config confirmed in the wizard, falling back to the source.
    comps = list(payload.components) if payload.components else _source_components(src)
    if not comps:
        raise HTTPException(400, "No components to build.")
    model_cfg = payload.model_config_ or (
        schemas.ModelConfig(**(src.model_config_json or {}))
    )

    new = models.Project(
        name=payload.name or f"{src.name} (重建)",
        target=src.target, direction=src.direction, created_by=src.created_by,
        status="building", current_round=-1,
        rules_json=src.rules_json,
    )
    db.add(new)
    db.commit()
    db.refresh(new)

    # Copy referenced descriptor CSVs into the new namespace and rewrite refs so
    # the new project owns its descriptor files (source may later be deleted).
    new_desc = {}
    for c in comps:
        if c.encoding != "descriptor" or not c.descriptor_file:
            continue
        fname = c.descriptor_file
        old_path = DESC_DIR / fname
        suffix = fname.split("__", 1)[-1] if "__" in fname else fname
        new_fname = f"{new.id}__{suffix}"
        if old_path.exists():
            shutil.copyfile(old_path, DESC_DIR / new_fname)
        c.descriptor_file = new_fname
        new_desc[c.name] = {"filename": new_fname, "id_column": c.id_column}

    new.components_json = {c.name: c.values for c in comps}
    new.encoding_json = {c.name: c.encoding for c in comps}
    new.descriptors_json = new_desc
    new.model_config_json = model_cfg.model_dump()

    # Copy completed experiments as prior results to import after (re)building.
    if payload.copy_data:
        done = (
            db.query(models.Experiment).join(models.Round)
            .filter(models.Round.project_id == project_id)
            .filter(models.Experiment.status == "done")
            .filter(models.Experiment.observed_value.isnot(None))
            .all()
        )
        new.pending_prior_json = [
            {"components": e.components_json, "observed_value": e.observed_value}
            for e in done
        ]
    db.commit()
    db.refresh(new)

    task = models.Task(project_id=new.id, kind="build_space", status="pending")
    db.add(task)
    db.commit()
    db.refresh(task)
    background.add_task(
        services.build_space_task, new.id, task.id, comps, model_cfg,
    )
    return {"project_id": new.id, "task_id": task.id}


@router.post("/{project_id}/archive", response_model=schemas.ProjectOut)
def archive_project(project_id: str, db: Session = Depends(get_db)):
    """Archive a project: hide it from the dashboard while preserving all data.
    The in-memory optimizer is evicted to free RAM (reloaded on restore)."""
    p = db.get(models.Project, project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    p.archived_at = datetime.utcnow()
    db.commit()
    from ..instance_manager import manager
    manager.evict(project_id)
    return _to_out(db, p)


@router.post("/{project_id}/restore", response_model=schemas.ProjectOut)
def restore_project(project_id: str, db: Session = Depends(get_db)):
    """Restore a previously archived project back to the dashboard."""
    p = db.get(models.Project, project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    p.archived_at = None
    db.commit()
    return _to_out(db, p)


@router.delete("/{project_id}")
def delete_project(project_id: str, db: Session = Depends(get_db)):
    p = db.get(models.Project, project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    db.delete(p)
    db.commit()
    from ..instance_manager import manager
    from ..config import pkl_path
    manager.evict(project_id)
    path = pkl_path(project_id)
    if path.exists():
        path.unlink()
    return {"ok": True}
