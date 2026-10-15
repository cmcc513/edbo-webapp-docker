"""Full-space yield lookup — the 'virtual laboratory'.

Wraps an edbo example experiment_index.csv (the complete combinatorial space with
measured yields) and answers: given a set of component values, what yield was
observed? This lets us replace real experiments with a table lookup while
driving the platform through a realistic human-in-the-loop campaign.
"""
from __future__ import annotations

from pathlib import Path
import pandas as pd


def norm(v) -> str:
    """Mirror EdboSession._norm so keys match the platform's readable values."""
    try:
        f = float(v)
        if f.is_integer():
            return str(int(f))
        return str(f)
    except (TypeError, ValueError):
        return str(v)


class GroundTruth:
    def __init__(self, index_csv: str, component_cols: list[str], yield_col: str):
        self.df = pd.read_csv(index_csv)
        self.component_cols = component_cols
        self.yield_col = yield_col
        self._table: dict[tuple, float] = {}
        for _, row in self.df.iterrows():
            key = tuple(norm(row[c]) for c in component_cols)
            self._table[key] = float(row[yield_col])

    def lookup(self, components: dict) -> float | None:
        """Return the yield for a component-value dict, or None if not measured."""
        try:
            key = tuple(norm(components[c]) for c in self.component_cols)
        except KeyError:
            return None
        return self._table.get(key)

    @property
    def global_max(self) -> float:
        return float(self.df[self.yield_col].max())

    @property
    def global_min(self) -> float:
        return float(self.df[self.yield_col].min())

    @property
    def size(self) -> int:
        return len(self._table)

    def random_measured_point(self, rng) -> tuple[dict, float]:
        """Pick a random measured experiment (for simulating a human decision)."""
        row = self.df.sample(1, random_state=int(rng.integers(0, 1 << 30))).iloc[0]
        comps = {c: _py(row[c]) for c in self.component_cols}
        return comps, float(row[self.yield_col])


def _py(v):
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if hasattr(v, "item"):
        return v.item()
    return v
