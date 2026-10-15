"""Drive the edbo web platform through a simulated human-in-the-loop campaign.

Talks to the running FastAPI server over HTTP exactly as the browser UI does:
build space -> init -> (look up yields, skip some, add human picks) -> run -> ...
"""
from __future__ import annotations

import io
import time
import tempfile
from dataclasses import dataclass, field

import numpy as np
import httpx

from .ground_truth import GroundTruth
from .reactions import Reaction, component_values, prep_descriptor


@dataclass
class CampaignResult:
    reaction: str
    space_size: int
    global_max: float
    convergence: list[float]
    best_found: float
    n_experiments: int
    n_skipped: int
    n_human: int
    r2: float | None
    checks: list[tuple[str, bool, str]] = field(default_factory=list)

    @property
    def ratio(self) -> float:
        return self.best_found / self.global_max if self.global_max else 0.0

    @property
    def ok(self) -> bool:
        return all(passed for _, passed, _ in self.checks)


class Sim:
    def __init__(self, base_url: str):
        self.h = httpx.Client(base_url=base_url, timeout=900.0)

    def poll(self, pid: str, task_id: str, label: str = "") -> dict:
        while True:
            t = self.h.get(f"/api/projects/{pid}/tasks/{task_id}").json()
            if t["status"] in ("done", "error"):
                if t["status"] == "error":
                    raise RuntimeError(f"{label} task failed: {t.get('error')}")
                return t
            time.sleep(1.0)


def run_campaign(
    sim: Sim,
    reaction: Reaction,
    *,
    skip_prob: float = 0.15,
    human_every: int = 2,
    verbose: bool = True,
) -> CampaignResult:
    rng = np.random.default_rng(reaction.seed)
    h = sim.h
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, cond: bool, detail: str = ""):
        checks.append((name, bool(cond), detail))
        if verbose:
            mark = "PASS" if cond else "FAIL"
            print(f"    [{mark}] {name} {('- ' + detail) if detail else ''}")

    # Ground-truth virtual lab
    comp_cols = [c.db_col for c in reaction.components]
    gt = GroundTruth(reaction.index_csv, comp_cols, reaction.yield_col)
    if verbose:
        print(f"\n=== {reaction.name} ===")
        print(f"  virtual lab: {gt.size} measured points, "
              f"global max = {gt.global_max:.2f}")

    # 1) create project
    pid = h.post("/api/projects", json={
        "name": reaction.name, "target": "yield", "direction": "max"
    }).json()["id"]

    # 2) prepare components (upload descriptor CSVs where needed)
    comps_payload = []
    for c in reaction.components:
        values = component_values(reaction, c)
        spec = {"name": c.db_col, "values": values, "encoding": c.encoding}
        if c.encoding == "descriptor":
            df = prep_descriptor(c, c.db_col)
            buf = io.BytesIO(df.to_csv(index=False).encode())
            files = {"file": (f"{c.db_col}.csv", buf, "text/csv")}
            up = h.post(f"/api/projects/{pid}/descriptors", files=files).json()
            spec["descriptor_file"] = up["filename"]
            spec["id_column"] = c.db_col
            check(f"descriptor upload {c.db_col}",
                  up["n_rows"] == len(values),
                  f"{up['n_rows']} rows")
        comps_payload.append(spec)

    space = {"components": comps_payload,
             "model_config_": {"model": reaction.model, "init_method": reaction.init_method}}

    # 3) validate + build space
    val = h.post(f"/api/projects/{pid}/space/validate", json=space).json()
    check("space validation ok", val["ok"], f"size={val['space_size']}")
    check("space size == virtual lab (±missing combos)",
          val["space_size"] >= gt.size,
          f"{val['space_size']} vs {gt.size}")
    tid = h.post(f"/api/projects/{pid}/space", json=space).json()["task_id"]
    sim.poll(pid, tid, "build_space")
    proj = h.get(f"/api/projects/{pid}").json()
    check("space built", proj["status"] == "ready", proj["status"])

    # 4) initialize (round 0)
    tid = h.post(f"/api/projects/{pid}/init", json={
        "seed": reaction.seed, "batch_size": reaction.init_batch,
        "init_method": reaction.init_method,
    }).json()["task_id"]
    sim.poll(pid, tid, "init")

    total_skipped = 0
    total_human = 0
    rejected_probe_ok = False

    # 5) human-in-the-loop rounds
    for r in range(reaction.rounds):
        proj = h.get(f"/api/projects/{pid}").json()
        rnd = proj["current_round"]
        proposals = h.get(f"/api/projects/{pid}/proposals").json()
        machine = [p for p in proposals if p["source"] == "machine" and p["status"] == "proposed"]

        # simulate the chemist running (most of) the proposed experiments
        results = []
        for p in machine:
            y = gt.lookup(p["components"])
            skip = (y is None) or (rng.random() < skip_prob)
            results.append({
                "experiment_id": p["id"],
                "observed_value": None if skip else round(y, 3),
            })
            if skip:
                total_skipped += 1
        h.post(f"/api/projects/{pid}/rounds/{rnd}/machine-results",
               json={"results": results})

        # occasionally the chemist injects their own decision (a DB point)
        if r % human_every == 0:
            comps, y = gt.random_measured_point(rng)
            res = h.post(f"/api/projects/{pid}/rounds/{rnd}/human-experiments", json={
                "experiments": [{"components": comps, "observed_value": round(y, 3),
                                 "note": "chemist decision (simulated)"}]
            }).json()
            if res["accepted"] == 1:
                total_human += 1

        # probe out-of-space rejection once
        if r == 0:
            bad = {c.db_col: ("__nope__" if c.encoding != "numeric" else 99999.0)
                   for c in reaction.components}
            rej = h.post(f"/api/projects/{pid}/rounds/{rnd}/human-experiments", json={
                "experiments": [{"components": bad, "observed_value": 1.0}]
            }).json()
            rejected_probe_ok = (not rej["ok"]) and len(rej["rejected"]) == 1

        # train + acquire next batch
        tid = h.post(f"/api/projects/{pid}/run", json={
            "acq_function": reaction.acq, "batch_size": reaction.batch,
        }).json()["task_id"]
        sim.poll(pid, tid, f"run r{r}")

        analytics = h.get(f"/api/projects/{pid}/analytics").json()
        if verbose:
            print(f"  round {r}: done={analytics['n_experiments']:3d}  "
                  f"best={analytics['best_value']:.2f}  "
                  f"({100*analytics['best_value']/gt.global_max:.0f}% of global max)")

    # 6) prediction panel
    comps, _ = gt.random_measured_point(rng)
    pred = h.post(f"/api/projects/{pid}/predict", json={"components": comps}).json()
    check("prediction returns mean+std",
          pred["ok"] and pred.get("mean") is not None and pred.get("std") is not None,
          f"mean={pred.get('mean')}, std={pred.get('std')}")
    bad = {c.db_col: ("__nope__" if c.encoding != "numeric" else 99999.0)
           for c in reaction.components}
    pred_bad = h.post(f"/api/projects/{pid}/predict", json={"components": bad}).json()
    check("prediction rejects out-of-space point", not pred_bad["ok"])

    # 7) correct a past yield and confirm the model retrains
    rounds = h.get(f"/api/projects/{pid}/rounds").json()
    r0 = next((r for r in rounds if r["round_index"] == 0), None)
    tgt = next((e for e in r0["experiments"]
                if e["status"] == "done" and e["source"] == "machine"), None) if r0 else None
    if tgt:
        orig = tgt["observed_value"]
        new_val = round((orig or 0) + 1.23, 3)
        res = h.patch(f"/api/projects/{pid}/experiments/{tgt['id']}",
                      json={"observed_value": new_val}).json()
        check("edit past yield accepted",
              res["ok"] and abs(res["experiment"]["observed_value"] - new_val) < 1e-6)
        check("edit triggered model retrain", res["retrained"])
        # restore the true value
        h.patch(f"/api/projects/{pid}/experiments/{tgt['id']}",
                json={"observed_value": orig})
    else:
        check("edit past yield accepted", False, "no done experiment in round 0")

    # 8) final checks
    analytics = h.get(f"/api/projects/{pid}/analytics").json()
    conv = [c["best"] for c in analytics["convergence"]]
    reg = analytics.get("regression") or {}

    check("convergence-by-round available",
          len(analytics.get("convergence_rounds", [])) >= 1)
    check("out-of-space human experiment rejected", rejected_probe_ok)
    check("human experiments accepted", total_human >= 1, f"{total_human} added")
    check("some proposals skipped (ignored on import)", total_skipped >= 1,
          f"{total_skipped} skipped")
    check("convergence monotonic non-decreasing",
          all(conv[i] <= conv[i + 1] + 1e-9 for i in range(len(conv) - 1)))
    check("model trained (R^2 available)", reg.get("r2") is not None,
          f"R2={reg.get('r2')}")
    best = analytics["best_value"]
    check("BO reached >=70% of global optimum",
          best >= 0.70 * gt.global_max,
          f"{best:.1f}/{gt.global_max:.1f} = {100*best/gt.global_max:.0f}%")

    # round summary integrity (round 0)
    s0 = h.get(f"/api/projects/{pid}/rounds/0/summary").json()
    check("round-0 summary tracks sources/skips",
          s0["n_machine"] >= 1 and (s0["n_skipped"] + s0["n_done"]) >= 1)

    return CampaignResult(
        reaction=reaction.name,
        space_size=val["space_size"],
        global_max=gt.global_max,
        convergence=conv,
        best_found=best,
        n_experiments=analytics["n_experiments"],
        n_skipped=total_skipped,
        n_human=total_human,
        r2=reg.get("r2"),
        checks=checks,
    )
