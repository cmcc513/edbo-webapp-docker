"""SQLAlchemy engine, session factory and declarative base."""
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import DATABASE_URL

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def get_db():
    """FastAPI dependency yielding a scoped DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from . import models  # noqa: F401  (register mappers)
    Base.metadata.create_all(bind=engine)
    _migrate()


def _migrate():
    """Additive, data-preserving migrations for existing SQLite databases."""
    from sqlalchemy import text

    # New columns introduced after the initial release. ALTER TABLE ADD COLUMN
    # is safe in SQLite and keeps all existing rows/data intact.
    additions = {
        "projects": [
            ("rules_json", "JSON"), ("archived_at", "DATETIME"),
            ("pending_prior_json", "JSON"),
        ],
        "experiments": [("provenance_json", "JSON")],
    }
    with engine.begin() as conn:
        for table, cols in additions.items():
            existing = {
                row[1]
                for row in conn.execute(text(f"PRAGMA table_info({table})"))
            }
            for name, coltype in cols:
                if name not in existing:
                    conn.execute(
                        text(f"ALTER TABLE {table} ADD COLUMN {name} {coltype}")
                    )
