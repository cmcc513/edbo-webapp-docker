"""Rule management: exclude chemically-impossible reaction conditions."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..instance_manager import manager
from ..rules import is_excluded
from .. import models, schemas

router = APIRouter(prefix="/api/projects", tags=["rules"])


@router.get("/{project_id}/rules", response_model=schemas.RulesOut)
def get_rules(project_id: str, db: Session = Depends(get_db)):
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    rules = project.rules_json or []
    excluded = _count_excluded(project_id, rules)
    return schemas.RulesOut(rules=rules, excluded_count=excluded)


@router.put("/{project_id}/rules", response_model=schemas.RulesOut)
def set_rules(project_id: str, payload: schemas.RulesIn,
              db: Session = Depends(get_db)):
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    rules = []
    for r in payload.rules:
        d = r.model_dump()
        if not d.get("id"):
            d["id"] = uuid.uuid4().hex[:8]
        rules.append(d)
    project.rules_json = rules
    db.commit()
    return schemas.RulesOut(rules=rules, excluded_count=_count_excluded(project_id, rules))


def _count_excluded(project_id: str, rules) -> int | None:
    """How many points of the reaction space these rules exclude (best effort)."""
    if not rules:
        return 0
    try:
        session = manager.get(project_id)
    except KeyError:
        return None
    try:
        options = session.component_options()
        keys = list(options.keys())
        import itertools
        # Guard against huge spaces: only enumerate if manageable
        size = 1
        for k in keys:
            size *= len(options[k])
        if size > 200_000:
            return None
        count = 0
        for combo in itertools.product(*[options[k] for k in keys]):
            comps = dict(zip(keys, combo))
            if is_excluded(comps, rules):
                count += 1
        return count
    except Exception:  # noqa: BLE001
        return None
