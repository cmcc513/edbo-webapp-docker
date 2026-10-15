"""SQLAlchemy ORM models: projects, space/model config, rounds, experiments, tasks."""
import uuid
from datetime import datetime

from sqlalchemy import Column, String, Integer, Float, DateTime, ForeignKey, JSON, Text
from sqlalchemy.orm import relationship

from .database import Base


def _uuid() -> str:
    return uuid.uuid4().hex


class Project(Base):
    __tablename__ = "projects"

    id = Column(String, primary_key=True, default=_uuid)
    name = Column(String, nullable=False)
    target = Column(String, nullable=False, default="yield")
    direction = Column(String, nullable=False, default="max")  # max | min
    status = Column(String, nullable=False, default="created")
    current_round = Column(Integer, nullable=False, default=-1)  # -1 = not initialized
    created_by = Column(String, default="anonymous")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    archived_at = Column(DateTime, default=None)   # non-null => archived (hidden)

    # Configuration (populated once the space is built)
    components_json = Column(JSON, default=None)   # {name: [values...]}
    encoding_json = Column(JSON, default=None)     # {name: encoding}
    descriptors_json = Column(JSON, default=None)  # {name: {filename, id_column}}
    model_config_json = Column(JSON, default=None) # {model, init_method, gp params}
    space_size = Column(Integer, default=None)
    rules_json = Column(JSON, default=None)        # [{id,name,active,clauses:[...]}]
    pending_prior_json = Column(JSON, default=None)  # rebuild: copied results to import

    rounds = relationship("Round", back_populates="project", cascade="all, delete-orphan")


class Round(Base):
    __tablename__ = "rounds"

    id = Column(String, primary_key=True, default=_uuid)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    round_index = Column(Integer, nullable=False)
    kind = Column(String, nullable=False)  # init | bo
    acq_function = Column(String, default=None)
    batch_size = Column(Integer, default=None)
    acq_params_json = Column(JSON, default=None)
    seed = Column(Integer, default=None)
    created_at = Column(DateTime, default=datetime.utcnow)
    imported_at = Column(DateTime, default=None)

    project = relationship("Project", back_populates="rounds")
    experiments = relationship(
        "Experiment", back_populates="round", cascade="all, delete-orphan"
    )


class Experiment(Base):
    __tablename__ = "experiments"

    id = Column(String, primary_key=True, default=_uuid)
    round_id = Column(String, ForeignKey("rounds.id"), nullable=False)
    domain_index = Column(Integer, nullable=False)
    source = Column(String, nullable=False)   # machine | human
    status = Column(String, nullable=False)   # proposed | done | skipped
    components_json = Column(JSON, nullable=False)  # {name: value}
    predicted_mean = Column(Float, default=None)
    predicted_var = Column(Float, default=None)
    observed_value = Column(Float, default=None)
    entered_by = Column(String, default=None)
    entered_at = Column(DateTime, default=None)
    note = Column(Text, default=None)
    imported = Column(Integer, default=0)  # 0/1 whether fed to optimizer already
    provenance_json = Column(JSON, default=None)  # adoption/decision context (Phase 2)

    round = relationship("Round", back_populates="experiments")


class Task(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True, default=_uuid)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    kind = Column(String, nullable=False)  # build_space | init | run
    status = Column(String, nullable=False, default="pending")  # pending|running|done|error
    progress = Column(Float, default=0.0)
    message = Column(String, default=None)
    error = Column(Text, default=None)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
