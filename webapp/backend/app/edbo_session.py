"""Wrapper around edbo's BO_express that is safe for use behind a web API.

Responsibilities
----------------
* Build reaction spaces without ever triggering edbo's interactive terminal bot.
* Provide a component-values -> domain_index reverse lookup so human-decided
  experiments can be aligned with the encoded grid.
* Feed observations to the optimizer in a *provenance agnostic* way (the
  optimizer only ever sees experiments that were actually run).
* Reconfigure the acquisition function / batch size before every acquisition.
* Persist and restore the whole optimizer via edbo's dill pickle.
"""
from __future__ import annotations

import io
import contextlib
from typing import Any

import numpy as np
import pandas as pd

from edbo.bro import BO_express
from edbo.acq_func import acquisition
from edbo.init_scheme import Init
from edbo.objective import objective
from edbo.models import GP_Model, RF_Model, Bayesian_Linear_Model, Random

MODEL_MAP = {
    "GP": GP_Model,
    "RF": RF_Model,
    "Bayesian_Linear": Bayesian_Linear_Model,
    "Random": Random,
}


class SpaceValidationError(Exception):
    """Raised when a reaction space / descriptor set cannot be built."""


class EdboSession:
    """Owns a single BO_express instance for one project."""

    def __init__(self, bo: BO_express | None = None):
        self.bo = bo
        self._lookup: dict[tuple, int] | None = None
        self._component_keys: list[str] = []
        self._ms_cache: tuple | None = None  # (mean_std, std_std) over domain

    # ------------------------------------------------------------------ build
    @classmethod
    def build(
        cls,
        components: dict[str, list],
        encoding: dict[str, str],
        descriptor_matrices: dict[str, pd.DataFrame] | None = None,
        model: str = "GP",
        init_method: str = "rand",
        acquisition_function: str = "EI",
        target: str = "yield",
        batch_size: int = 5,
    ) -> "EdboSession":
        model_cls = MODEL_MAP.get(model, GP_Model)
        # edbo prints to stdout and may attempt to resolve names; capture output.
        with contextlib.redirect_stdout(io.StringIO()):
            try:
                bo = BO_express(
                    reaction_components=components,
                    encoding=encoding or {},
                    descriptor_matrices=descriptor_matrices or {},
                    model=model_cls,
                    acquisition_function=acquisition_function,
                    init_method=init_method,
                    target=target,
                    batch_size=batch_size,
                )
            except Exception as exc:  # noqa: BLE001
                raise SpaceValidationError(str(exc)) from exc
        session = cls(bo)
        session._build_lookup()
        return session

    # -------------------------------------------------------------- internals
    def _build_lookup(self) -> None:
        """Map a tuple of human-readable component values -> domain_index."""
        reaction = self.bo.reaction
        headers = list(reaction.index_headers)
        # component order matches index_headers order (built in the same loop)
        self._component_keys = [h[:-6] if h.endswith("_index") else h for h in headers]
        readable = reaction.base_data[headers]
        lookup: dict[tuple, int] = {}
        for idx, row in zip(readable.index.values, readable.values):
            lookup[tuple(_norm(v) for v in row)] = int(idx)
        self._lookup = lookup

    def _ensure_lookup(self) -> None:
        if self._lookup is None:
            self._build_lookup()

    @property
    def component_keys(self) -> list[str]:
        self._ensure_lookup()
        return self._component_keys

    @property
    def target(self) -> str:
        return self.bo.obj.target

    def space_size(self) -> int:
        return int(len(self.bo.reaction.base_data))

    def component_options(self) -> dict[str, list]:
        """Distinct selectable values per component (as shown to chemists)."""
        self._ensure_lookup()
        reaction = self.bo.reaction
        headers = list(reaction.index_headers)
        out: dict[str, list] = {}
        for key, header in zip(self._component_keys, headers):
            values = reaction.base_data[header].drop_duplicates().tolist()
            out[key] = values
        return out

    # ---------------------------------------------------------- proposals I/O
    def _decode(self, index_values) -> list[dict]:
        """Return list of {component: value} for the given domain indices."""
        self._ensure_lookup()
        experiments = self.bo.reaction.get_experiments(list(index_values))
        records = []
        for idx, row in zip(index_values, experiments.values):
            comp = {k: _py(v) for k, v in zip(self._component_keys, row)}
            records.append({"domain_index": int(idx), "components": comp})
        return records

    def proposals_with_prediction(self) -> list[dict]:
        """Current proposed experiments, decoded, with predicted mean/variance."""
        proposed = self.bo.proposed_experiments
        if proposed is None or len(proposed) == 0:
            return []
        index_values = list(proposed.index.values)
        records = self._decode(index_values)

        mean = var = None
        # A fitted model exists after run(); init proposals have no prediction.
        if getattr(self.bo, "model", None) is not None and not isinstance(
            self.bo.model, type
        ):
            try:
                from edbo.pd_utils import to_torch

                X = to_torch(proposed.copy(), gpu=self.bo.gpu)
                mean = self.bo.obj.scaler.unstandardize(self.bo.model.predict(X))
                var = (np.sqrt(self.bo.model.variance(X)) * self.bo.obj.scaler.std) ** 2
                mean = np.asarray(mean).ravel()
                var = np.asarray(var).ravel()
            except Exception:  # noqa: BLE001
                mean = var = None

        for i, rec in enumerate(records):
            rec["predicted_mean"] = float(mean[i]) if mean is not None else None
            rec["predicted_var"] = float(var[i]) if var is not None else None
        return records

    def resolve_domain_index(self, components: dict[str, Any]) -> int | None:
        """Reverse lookup: component values -> domain_index (or None if absent)."""
        self._ensure_lookup()
        try:
            key = tuple(_norm(components[k]) for k in self._component_keys)
        except KeyError:
            return None
        return self._lookup.get(key)

    # ------------------------------------------------------------- optimize
    def init_sample(self, seed: int | None, batch_size: int, init_method: str) -> None:
        self.bo.batch_size = batch_size
        self.bo.init_seq = Init(init_method, batch_size)
        with contextlib.redirect_stdout(io.StringIO()):
            self.bo.init_sample(seed=seed)

    def _set_objective(self, results: pd.DataFrame) -> None:
        target = self.target
        self.bo.obj = objective(
            domain=self.bo.obj.domain,
            results=results,
            exindex=self.bo.obj.exindex,
            target=target,
            gpu=self.bo.obj.gpu,
            computational_objective=self.bo.obj.computational_objective,
        )

    def _results_frame(self, observations: list[tuple[int, float]]) -> pd.DataFrame:
        """Build a results frame (encoded descriptors + target) for observations."""
        idx = [int(i) for i, _ in observations]
        vals = [float(v) for _, v in observations]
        result_descriptors = self.bo.obj.domain.iloc[idx]
        new_target = pd.DataFrame(
            {self.target: vals}, index=result_descriptors.index
        )
        return pd.concat([result_descriptors, new_target[[self.target]]], axis=1)

    def add_observations(self, observations: list[tuple[int, float]]) -> None:
        """Append actually-run experiments to the optimizer's results.

        Mirrors edbo.BO_express.add_results but works in memory (no CSV, no bot).
        """
        if not observations:
            return
        results = self._results_frame(observations)
        if len(self.bo.obj.results) > 0:
            results = pd.concat([self.bo.obj.results_input(), results])
        self._set_objective(results)

    def set_all_observations(self, observations: list[tuple[int, float]]) -> None:
        """Replace *all* imported results with the given full set (used after a
        yield is corrected). The optimizer is rebuilt from the corrected data."""
        results = (
            self._results_frame(observations) if observations else pd.DataFrame()
        )
        self._set_objective(results)

    def fit(self) -> None:
        """(Re)train the surrogate model on the current results, if any."""
        if len(self.bo.obj.results) == 0:
            self._ms_cache = None
            return
        with contextlib.redirect_stdout(io.StringIO()):
            self.bo.fit()
        self._ms_cache = None

    def refresh_model(self, observations: list[tuple[int, float]]) -> bool:
        """Rebuild the optimizer from *all* observed experiments and refit.

        Returns True if a model was trained (i.e. there was data). This is the
        single source of truth for the recommendation leaderboard.
        """
        self.set_all_observations(observations)
        if len(self.bo.obj.results) == 0:
            self._ms_cache = None
            return False
        with contextlib.redirect_stdout(io.StringIO()):
            self.bo.fit()
        self._compute_ms()
        return True

    def _compute_ms(self) -> None:
        """Cache standardized posterior mean/std over the whole domain."""
        from edbo.pd_utils import to_torch

        domain = to_torch(self.bo.obj.domain, gpu=self.bo.gpu)
        m = np.asarray(self.bo.model.predict(domain)).ravel()
        s = np.sqrt(np.asarray(self.bo.model.variance(domain)).ravel()) + 1e-6
        self._ms_cache = (m, s)

    def has_model(self) -> bool:
        model = getattr(self.bo, "model", None)
        return model is not None and not isinstance(model, type)

    def leaderboard(
        self,
        acq_function: str,
        top_n: int = 20,
        exclude_indices: set[int] | None = None,
        exclude_fn=None,
        jitter: float = 0.01,
        delta: float = 0.5,
    ) -> list[dict]:
        """Rank candidate domain points by an acquisition function.

        Uses the cached posterior (so switching acquisition function is cheap).
        Returns decoded candidates with real-scale predicted mean/std + score.
        """
        from scipy.stats import norm

        if self._ms_cache is None:
            if not self.has_model():
                return []
            self._compute_ms()
        m, s = self._ms_cache
        results = self.bo.obj.results
        max_obs = float(np.asarray(self.bo.obj.y).max()) if len(results) else 0.0

        acq = acq_function.lower()
        if acq in ("ei", "ei-ts"):
            z = (m - max_obs - jitter) / s
            score = (m - max_obs - jitter) * norm.cdf(z) + s * norm.pdf(z)
            score = np.where(s < jitter, 0.0, score)
        elif acq in ("pi", "pi-ts"):
            score = norm.cdf((m - max_obs - jitter) / s)
        elif acq in ("ucb", "ucb-ts"):
            dim = len(self.bo.obj.domain.columns)
            iters = max(1, len(results))
            beta = np.sqrt(2 * np.log(dim * iters ** 2 * np.pi ** 2 / (6 * delta)))
            score = m + beta * s
        elif acq in ("meanmax", "mean"):
            score = m
        elif acq in ("varmax", "var", "variance"):
            score = s ** 2
        else:  # default to EI
            z = (m - max_obs - jitter) / s
            score = (m - max_obs - jitter) * norm.cdf(z) + s * norm.pdf(z)

        exclude = exclude_indices or set()
        order = np.argsort(score)[::-1]
        scaler = self.bo.obj.scaler
        mean_real = scaler.unstandardize(m)
        std_real = s * scaler.std

        mean_flat = np.asarray(mean_real).ravel()
        std_flat = np.asarray(std_real).ravel()
        score_flat = np.asarray(score).ravel()
        out: list[dict] = []
        for idx in order:
            i = int(idx)
            if i in exclude:
                continue
            rec = self._decode([i])[0]
            if exclude_fn is not None and exclude_fn(rec["components"]):
                continue
            rec["predicted_mean"] = float(mean_flat[i])
            rec["predicted_var"] = float(std_flat[i] ** 2)
            rec["acq_score"] = float(score_flat[i])
            out.append(rec)
            if len(out) >= top_n:
                break
        return out

    def points_info(self, indices: list[int]) -> list[dict]:
        """Decode domain indices with predicted mean/var (from cache if present)."""
        recs = self._decode([int(i) for i in indices])
        if self._ms_cache is not None:
            m, s = self._ms_cache
            scaler = self.bo.obj.scaler
            mean_real = np.asarray(scaler.unstandardize(m)).ravel()
            std_real = np.asarray(s * scaler.std).ravel()
            for rec in recs:
                i = rec["domain_index"]
                rec["predicted_mean"] = float(mean_real[i])
                rec["predicted_var"] = float(std_real[i] ** 2)
        else:
            for rec in recs:
                rec["predicted_mean"] = None
                rec["predicted_var"] = None
        return recs

    def observed_indices(self) -> set[int]:
        """Domain indices that already have results (positional in domain)."""
        if len(self.bo.obj.results) == 0:
            return set()
        results_desc = self.bo.obj.results.drop(self.bo.obj.target, axis=1)
        # match rows of results back to domain positions
        domain = self.bo.obj.domain.reset_index(drop=True)
        idx_map = {tuple(r): i for i, r in enumerate(domain.values)}
        found = set()
        for r in results_desc.values:
            i = idx_map.get(tuple(r))
            if i is not None:
                found.add(i)
        return found

    def predict(self, components: dict[str, Any]) -> dict | None:
        """Predict mean yield and uncertainty for an arbitrary point in the space.

        Returns None if the point is outside the space or no model is trained.
        """
        domain_index = self.resolve_domain_index(components)
        if domain_index is None:
            return {"error": "out_of_space"}
        model = getattr(self.bo, "model", None)
        if model is None or isinstance(model, type):
            return {"error": "no_model"}
        try:
            from edbo.pd_utils import to_torch

            row = self.bo.obj.domain.iloc[[int(domain_index)]]
            X = to_torch(row, gpu=self.bo.gpu)
            mean = self.bo.obj.scaler.unstandardize(model.predict(X))
            std = np.sqrt(model.variance(X)) * self.bo.obj.scaler.std
            return {
                "domain_index": int(domain_index),
                "mean": float(np.asarray(mean).ravel()[0]),
                "std": float(np.asarray(std).ravel()[0]),
            }
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}

    def run(self, acq_function: str, batch_size: int) -> None:
        self.bo.batch_size = batch_size
        self.bo.acq = acquisition(
            acq_function, batch_size=batch_size, duplicates=self.bo.duplicate_experiments
        )
        with contextlib.redirect_stdout(io.StringIO()):
            self.bo.run()

    # ------------------------------------------------------------- analytics
    def results_table(self) -> pd.DataFrame:
        """Unstandardized observed results (encoded descriptors + target)."""
        if len(self.bo.obj.results) == 0:
            return pd.DataFrame()
        return self.bo.obj.results_input()

    def regression(self) -> dict | None:
        """Predicted vs observed on the training data (+ R^2) if a model exists."""
        model = getattr(self.bo, "model", None)
        if model is None or isinstance(model, type) or len(self.bo.obj.results) == 0:
            return None
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                predobs = model.regression(return_data=True)
            pred = self.bo.obj.scaler.unstandardize(
                np.asarray(predobs["pred"]).ravel())
            obs = self.bo.obj.scaler.unstandardize(
                np.asarray(predobs["obs"]).ravel())
            ss_res = float(np.sum((obs - pred) ** 2))
            ss_tot = float(np.sum((obs - np.mean(obs)) ** 2))
            r2 = 1 - ss_res / ss_tot if ss_tot > 0 else None
            return {
                "predicted": [float(x) for x in pred],
                "observed": [float(x) for x in obs],
                "r2": r2,
            }
        except Exception:  # noqa: BLE001
            return None

    # ------------------------------------------------------------- persistence
    def save(self, path: str) -> None:
        self.bo.save(str(path))

    @classmethod
    def load(cls, path: str) -> "EdboSession":
        bo = BO_express()
        bo.load(str(path))
        session = cls(bo)
        session._build_lookup()
        return session


def _norm(v: Any) -> str:
    """Normalize a value into a stable string key for reverse lookup."""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _py(v: Any):
    """Convert numpy scalars to native python for JSON serialization."""
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        f = float(v)
        return int(f) if f.is_integer() else f
    return v
