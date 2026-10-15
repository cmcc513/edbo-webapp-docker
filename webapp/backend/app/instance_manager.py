"""In-memory LRU cache of EdboSession instances with per-project locks.

edbo instances are heavy (large encoded domains), so we keep at most
MAX_CACHED_INSTANCES resident and lazily reload the rest from their dill
pickles. A per-project re-entrant lock serializes mutating operations so two
chemists cannot corrupt shared optimizer state by training simultaneously.
"""
from __future__ import annotations

import threading
from collections import OrderedDict

from .config import MAX_CACHED_INSTANCES, pkl_path
from .edbo_session import EdboSession


class InstanceManager:
    def __init__(self, capacity: int = MAX_CACHED_INSTANCES):
        self.capacity = capacity
        self._cache: "OrderedDict[str, EdboSession]" = OrderedDict()
        self._locks: dict[str, threading.RLock] = {}
        self._guard = threading.Lock()

    def lock(self, project_id: str) -> threading.RLock:
        with self._guard:
            if project_id not in self._locks:
                self._locks[project_id] = threading.RLock()
            return self._locks[project_id]

    def put(self, project_id: str, session: EdboSession) -> None:
        with self._guard:
            self._cache[project_id] = session
            self._cache.move_to_end(project_id)
            self._evict_if_needed()

    def get(self, project_id: str) -> EdboSession:
        """Return the cached session or lazily load it from disk."""
        with self._guard:
            if project_id in self._cache:
                self._cache.move_to_end(project_id)
                return self._cache[project_id]

        path = pkl_path(project_id)
        if not path.exists():
            raise KeyError(f"No saved session for project {project_id}")
        session = EdboSession.load(str(path))
        with self._guard:
            self._cache[project_id] = session
            self._cache.move_to_end(project_id)
            self._evict_if_needed()
        return session

    def save(self, project_id: str, session: EdboSession) -> None:
        session.save(str(pkl_path(project_id)))
        self.put(project_id, session)

    def evict(self, project_id: str) -> None:
        with self._guard:
            self._cache.pop(project_id, None)

    def _evict_if_needed(self) -> None:
        # caller holds self._guard
        while len(self._cache) > self.capacity:
            oldest_id, oldest = next(iter(self._cache.items()))
            try:
                oldest.save(str(pkl_path(oldest_id)))
            except Exception:  # noqa: BLE001
                pass
            self._cache.popitem(last=False)


manager = InstanceManager()
