"""Business logic shared across routers: background tasks and helpers."""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from .config import DESC_DIR, MAX_SPACE_SIZE, pkl_path
from .database import SessionLocal
from .edbo_session import EdboSession, SpaceValidationError
from .instance_manager import manager
from . import models


# --------------------------------------------------------------------- helpers
def _load_descriptor_matrices(components) -> dict[str, pd.DataFrame]:
    matrices: dict[str, pd.DataFrame] = {}
    for c in components:
        if c.encoding == "descriptor" and c.descriptor_file:
            path = DESC_DIR / c.descriptor_file
            df = pd.read_csv(path)
            matrices[c.name] = df
    return matrices


def _session_from_payload(components_payload, model_cfg, target: str) -> EdboSession:
    """Build a fresh EdboSession from component specs (shared by build/whatif/apply)."""
    components = {c.name: c.values for c in components_payload if c.values}
    encoding = {
        c.name: (c.encoding if c.encoding != "descriptor" else "ohe")
        for c in components_payload
    }
    matrices = _load_descriptor_matrices(components_payload)
    size = 1
    for v in components.values():
        size *= max(1, len(v))
    if size > MAX_SPACE_SIZE:
        raise SpaceValidationError(
            f"Space too large ({size} > {MAX_SPACE_SIZE}). Narrow the space."
        )
    return EdboSession.build(
        components=components, encoding=encoding, descriptor_matrices=matrices,
        model=model_cfg.model, init_method=model_cfg.init_method, target=target,
    )


def _set_task(db, task_id, **fields):
    task = db.get(models.Task, task_id)
    if task is None:
        return
    for k, v in fields.items():
        setattr(task, k, v)
    task.updated_at = datetime.utcnow()
    db.commit()


def _record_proposals(db, round_row, session: EdboSession, provenance: dict | None = None):
    """Persist current optimizer proposals as machine experiments."""
    proposals = session.proposals_with_prediction()
    for p in proposals:
        exp = models.Experiment(
            round_id=round_row.id,
            domain_index=p["domain_index"],
            source="machine",
            status="proposed",
            components_json=p["components"],
            predicted_mean=p.get("predicted_mean"),
            predicted_var=p.get("predicted_var"),
            provenance_json=provenance,
        )
        db.add(exp)
    db.commit()


def best_value(db, project: models.Project):
    q = (
        db.query(models.Experiment)
        .join(models.Round)
        .filter(models.Round.project_id == project.id)
        .filter(models.Experiment.status == "done")
        .filter(models.Experiment.observed_value.isnot(None))
    )
    values = [e.observed_value for e in q.all()]
    if not values:
        return None
    return max(values) if project.direction == "max" else min(values)


def all_done_observations(db, project_id: str) -> list[tuple[int, float]]:
    """Every completed experiment (across all rounds) as (domain_index, value)."""
    rows = (
        db.query(models.Experiment)
        .join(models.Round)
        .filter(models.Round.project_id == project_id)
        .filter(models.Experiment.status == "done")
        .filter(models.Experiment.observed_value.isnot(None))
        .all()
    )
    return [(e.domain_index, e.observed_value) for e in rows]


def _obs_signature(obs: list[tuple[int, float]]) -> int:
    return hash(tuple(sorted((int(i), round(float(v), 6)) for i, v in obs)))


def descriptor_snapshot(project: models.Project) -> dict:
    """Snapshot of the encoding/descriptor/model config in effect right now.

    Stored on each experiment's provenance so we can always tell *which*
    descriptor set produced a given recommendation, even after later changes.
    """
    descriptors = {
        name: (info or {}).get("filename")
        for name, info in (project.descriptors_json or {}).items()
    }
    model = (project.model_config_json or {}).get("model")
    return {
        "encoding": project.encoding_json or {},
        "descriptors": descriptors,
        "model": model,
    }


def ensure_model(db, project_id: str):
    """Return (session, trained). Refits the model on ALL completed experiments
    only when the data changed since the last fit (so switching acquisition
    function is cheap)."""
    lock = manager.lock(project_id)
    with lock:
        session = manager.get(project_id)
        obs = all_done_observations(db, project_id)
        sig = _obs_signature(obs)
        if getattr(session, "_trained_sig", None) == sig and session.has_model():
            if session._ms_cache is None:
                session._compute_ms()
            return session, len(obs) > 0
        trained = session.refresh_model(obs)
        session._trained_sig = sig
        manager.save(project_id, session)
        return session, trained


def retrain_from_db(db, project_id: str) -> bool:
    """Rebuild the optimizer from ALL completed experiments (reflecting any
    corrected yields) and refit. Past rounds/proposals are left untouched."""
    lock = manager.lock(project_id)
    with lock:
        try:
            session = manager.get(project_id)
        except KeyError:
            return False
        obs = all_done_observations(db, project_id)
        trained = session.refresh_model(obs)
        session._trained_sig = _obs_signature(obs)
        manager.save(project_id, session)
        return trained


def count_done(db, project_id: str) -> int:
    return (
        db.query(models.Experiment)
        .join(models.Round)
        .filter(models.Round.project_id == project_id)
        .filter(models.Experiment.status == "done")
        .count()
    )


# ----------------------------------------------------------------- background tasks
def build_space_task(project_id: str, task_id: str, components_payload, model_cfg):
    """Heavy: construct the BO_express reaction space."""
    db = SessionLocal()
    lock = manager.lock(project_id)
    try:
        with lock:
            _set_task(db, task_id, status="running", progress=0.1,
                      message="Building reaction space...")
            project = db.get(models.Project, project_id)

            session = _session_from_payload(
                components_payload, model_cfg, project.target
            )
            _set_task(db, task_id, progress=0.8, message="Saving session...")
            manager.save(project_id, session)

            project.space_size = session.space_size()
            project.status = "ready"
            project.updated_at = datetime.utcnow()
            db.commit()
            _set_task(db, task_id, status="done", progress=1.0,
                      message=f"Space built ({project.space_size} points).")
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        proj = db.get(models.Project, project_id)
        if proj:
            proj.status = "error"
            db.commit()
        _set_task(db, task_id, status="error", error=str(exc))
    finally:
        db.close()


def init_task(project_id: str, task_id: str, seed, batch_size, init_method,
              prior_experiments=None):
    db = SessionLocal()
    lock = manager.lock(project_id)
    try:
        with lock:
            project = db.get(models.Project, project_id)
            session = manager.get(project_id)

            round_row = models.Round(
                project_id=project_id, round_index=0, kind="init",
                batch_size=batch_size, seed=seed,
            )
            db.add(round_row)
            db.commit()

            if init_method == "import":
                _set_task(db, task_id, status="running", progress=0.3,
                          message="Importing prior experiments...")
                accepted, rejected = 0, []
                for item in (prior_experiments or []):
                    comps = item["components"]
                    val = item["observed_value"]
                    di = session.resolve_domain_index(comps)
                    if di is None:
                        rejected.append(comps)
                        continue
                    db.add(models.Experiment(
                        round_id=round_row.id, domain_index=di, source="prior",
                        status="done", components_json=comps,
                        observed_value=float(val), entered_by="import",
                        entered_at=datetime.utcnow(), imported=1,
                        provenance_json={
                            "source": "prior", "adopted_from": "import",
                            "at": datetime.utcnow().isoformat(),
                            **descriptor_snapshot(project),
                        },
                    ))
                    accepted += 1
                db.commit()
                if accepted == 0:
                    raise SpaceValidationError(
                        "No prior experiments matched the reaction space."
                    )
                _set_task(db, task_id, progress=0.7, message="Training model...")
                session.refresh_model(all_done_observations(db, project_id))
                session._trained_sig = _obs_signature(
                    all_done_observations(db, project_id))
                msg = f"Imported {accepted} prior experiment(s)."
                if rejected:
                    msg += f" {len(rejected)} skipped (not in space)."
            else:
                _set_task(db, task_id, status="running", progress=0.2,
                          message="Selecting initial experiments...")
                session.init_sample(seed=seed, batch_size=batch_size,
                                    init_method=init_method)
                _record_proposals(db, round_row, session, provenance={
                    "source": "machine", "adopted_from": "init",
                    "init_method": init_method, "seed": seed,
                    "at": datetime.utcnow().isoformat(),
                    **descriptor_snapshot(project),
                })
                msg = "Initial experiments ready."

            manager.save(project_id, session)
            project.current_round = 0
            project.status = "awaiting_results"
            project.pending_prior_json = None   # consumed / no longer needed
            db.commit()
            _set_task(db, task_id, status="done", progress=1.0, message=msg)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        proj = db.get(models.Project, project_id)
        if proj:
            proj.status = "ready"
            db.commit()
        _set_task(db, task_id, status="error", error=str(exc))
    finally:
        db.close()


def import_and_run_task(project_id: str, task_id: str, acq_function, batch_size,
                        acq_params):
    """Feed this round's completed experiments to the optimizer, then acquire."""
    db = SessionLocal()
    lock = manager.lock(project_id)
    try:
        with lock:
            _set_task(db, task_id, status="running", progress=0.1,
                      message="Importing results...")
            project = db.get(models.Project, project_id)
            session = manager.get(project_id)

            current = (
                db.query(models.Round)
                .filter_by(project_id=project_id, round_index=project.current_round)
                .first()
            )
            # Collect done, not-yet-imported experiments from the current round
            done = [
                e for e in current.experiments
                if e.status == "done" and e.observed_value is not None
                and not e.imported
            ]
            observations = [(e.domain_index, e.observed_value) for e in done]
            session.add_observations(observations)
            for e in done:
                e.imported = 1
            current.imported_at = datetime.utcnow()
            db.commit()

            _set_task(db, task_id, progress=0.5, message="Training model & acquiring...")
            session.run(acq_function=acq_function, batch_size=batch_size)

            new_index = project.current_round + 1
            round_row = models.Round(
                project_id=project_id, round_index=new_index, kind="bo",
                acq_function=acq_function, batch_size=batch_size,
                acq_params_json=acq_params or {},
            )
            db.add(round_row)
            db.commit()
            _record_proposals(db, round_row, session, provenance={
                "source": "machine", "adopted_from": "batch",
                "acq_function": acq_function, "acq_params": acq_params or {},
                "at": datetime.utcnow().isoformat(),
                **descriptor_snapshot(project),
            })

            manager.save(project_id, session)
            project.current_round = new_index
            project.status = "awaiting_results"
            db.commit()
            _set_task(db, task_id, status="done", progress=1.0,
                      message=f"Round {new_index} proposals ready.")
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        proj = db.get(models.Project, project_id)
        if proj:
            proj.status = "awaiting_results"
            db.commit()
        _set_task(db, task_id, status="error", error=str(exc))
    finally:
        db.close()


def whatif_descriptors(db, project_id: str, components_payload, model_cfg) -> dict:
    """Non-destructive preview: build a scratch space with modified descriptors,
    refit on the same completed experiments, and compare against the current
    model. Nothing is persisted."""
    project = db.get(models.Project, project_id)
    obs = all_done_observations(db, project_id)

    current_reg = None
    try:
        cur, _ = ensure_model(db, project_id)
        current_reg = cur.regression()
    except KeyError:
        pass

    scratch = _session_from_payload(components_payload, model_cfg, project.target)
    trained = scratch.refresh_model(obs)
    whatif_reg = scratch.regression() if trained else None
    return {
        "n_obs": len(obs),
        "space_size": scratch.space_size(),
        "current": current_reg,
        "whatif": whatif_reg,
    }


def apply_descriptors_task(project_id: str, task_id: str, components_payload, model_cfg):
    """Permanently rebuild the project's space with the modified descriptors,
    re-align stored experiments, refit, and persist. Historical results and
    recommendations are preserved (only the encoding/descriptors change)."""
    db = SessionLocal()
    lock = manager.lock(project_id)
    try:
        with lock:
            _set_task(db, task_id, status="running", progress=0.1,
                      message="重建反应空间…")
            project = db.get(models.Project, project_id)
            session = _session_from_payload(
                components_payload, model_cfg, project.target
            )

            project.components_json = {c.name: c.values for c in components_payload}
            project.encoding_json = {c.name: c.encoding for c in components_payload}
            project.descriptors_json = {
                c.name: {"filename": c.descriptor_file, "id_column": c.id_column}
                for c in components_payload if c.encoding == "descriptor"
            }
            project.model_config_json = model_cfg.model_dump()
            project.space_size = session.space_size()

            # Re-align stored experiments to the new grid (indices may shift).
            _set_task(db, task_id, progress=0.5, message="对齐历史实验…")
            exps = (
                db.query(models.Experiment).join(models.Round)
                .filter(models.Round.project_id == project_id).all()
            )
            for e in exps:
                di = session.resolve_domain_index(e.components_json)
                if di is not None:
                    e.domain_index = di
            db.commit()

            _set_task(db, task_id, progress=0.7, message="重新训练模型…")
            obs = all_done_observations(db, project_id)
            session.refresh_model(obs)
            session._trained_sig = _obs_signature(obs)
            manager.save(project_id, session)

            project.status = "awaiting_results" if project.current_round >= 0 else "ready"
            db.commit()
            _set_task(db, task_id, status="done", progress=1.0,
                      message="已应用新描述符并重训模型。")
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        proj = db.get(models.Project, project_id)
        if proj:
            proj.status = "awaiting_results" if proj.current_round >= 0 else "ready"
            db.commit()
        _set_task(db, task_id, status="error", error=str(exc))
    finally:
        db.close()
