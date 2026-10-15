"""Application configuration and filesystem paths."""
from pathlib import Path

# Base directory of the backend package (…/webapp/backend)
BASE_DIR = Path(__file__).resolve().parent.parent

# Data directory holds the SQLite DB, edbo pickles and uploaded descriptor CSVs
DATA_DIR = BASE_DIR / "data"
PKL_DIR = DATA_DIR / "sessions"
DESC_DIR = DATA_DIR / "descriptors"

for _d in (DATA_DIR, PKL_DIR, DESC_DIR):
    _d.mkdir(parents=True, exist_ok=True)

DATABASE_URL = f"sqlite:///{(DATA_DIR / 'edbo.db').as_posix()}"

# Maximum number of edbo instances kept in memory at once (LRU eviction)
MAX_CACHED_INSTANCES = 8

# Guard rail: refuse to build reaction spaces larger than this many points
MAX_SPACE_SIZE = 500_000


def pkl_path(project_id: str) -> Path:
    return PKL_DIR / f"{project_id}.pkl"
