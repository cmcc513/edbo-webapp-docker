"""End-to-end API smoke test using FastAPI TestClient.

Exercises: create project -> build space -> init -> submit machine results
(some skipped) -> add human experiment -> run -> analytics.
Background tasks run synchronously to completion under TestClient.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from app.database import init_db  # noqa: E402

init_db()
client = TestClient(app)


def wait_task(pid, tid, timeout=120):
    for _ in range(timeout):
        r = client.get(f"/api/projects/{pid}/tasks/{tid}").json()
        if r["status"] in ("done", "error"):
            return r
        time.sleep(1)
    raise TimeoutError("task did not finish")


def main():
    assert client.get("/api/health").json()["status"] == "ok"

    pid = client.post("/api/projects", json={
        "name": "E2E Suzuki", "target": "yield", "direction": "max"}).json()["id"]
    print("project", pid)

    space = {
        "components": [
            {"name": "base", "values": ["DBU", "MTBD", "K2CO3"], "encoding": "ohe"},
            {"name": "solvent", "values": ["THF", "Toluene", "DMSO"], "encoding": "ohe"},
            {"name": "temperature", "values": [20, 30, 40], "encoding": "numeric"},
        ],
        "model_config_": {"model": "GP", "init_method": "rand"},
    }
    val = client.post(f"/api/projects/{pid}/space/validate", json=space).json()
    print("validate:", val)
    assert val["ok"] and val["space_size"] == 27

    tid = client.post(f"/api/projects/{pid}/space", json=space).json()["task_id"]
    assert wait_task(pid, tid)["status"] == "done"

    tid = client.post(f"/api/projects/{pid}/init",
                      json={"seed": 0, "batch_size": 3, "init_method": "rand"}
                      ).json()["task_id"]
    assert wait_task(pid, tid)["status"] == "done"

    props = client.get(f"/api/projects/{pid}/proposals").json()
    print("round0 proposals:", [(p["domain_index"], p["components"]) for p in props])
    assert len(props) == 3

    # Fill 2 machine results, skip 1 (leave value None)
    results = [
        {"experiment_id": props[0]["id"], "observed_value": 30.0},
        {"experiment_id": props[1]["id"], "observed_value": 55.0},
        {"experiment_id": props[2]["id"], "observed_value": None},
    ]
    r = client.post(f"/api/projects/{pid}/rounds/0/machine-results",
                    json={"results": results, "entered_by": "tester"}).json()
    print("machine-results:", r)

    # Add a human-decided experiment within the space
    human = {"experiments": [{
        "components": {"base": "DBU", "solvent": "DMSO", "temperature": 40},
        "observed_value": 71.0, "note": "chemist hunch"}], "entered_by": "tester"}
    r = client.post(f"/api/projects/{pid}/rounds/0/human-experiments", json=human).json()
    print("human-experiments:", r)
    assert r["ok"] and r["accepted"] == 1

    # Reject out-of-space human experiment
    bad = {"experiments": [{
        "components": {"base": "DBU", "solvent": "DMSO", "temperature": 999},
        "observed_value": 10.0}]}
    r = client.post(f"/api/projects/{pid}/rounds/0/human-experiments", json=bad).json()
    assert not r["ok"] and len(r["rejected"]) == 1
    print("rejected out-of-space ok")

    # Run BO round 1
    tid = client.post(f"/api/projects/{pid}/run",
                      json={"acq_function": "EI", "batch_size": 3}).json()["task_id"]
    assert wait_task(pid, tid)["status"] == "done"

    props1 = client.get(f"/api/projects/{pid}/proposals").json()
    print("round1 proposals:", len(props1))
    assert len(props1) == 3
    assert props1[0]["predicted_mean"] is not None

    # Analytics
    a = client.get(f"/api/projects/{pid}/analytics").json()
    print("analytics best:", a["best_value"], "n:", a["n_experiments"],
          "r2:", (a.get("regression") or {}).get("r2"))
    assert a["n_experiments"] == 3  # 2 machine-done + 1 human

    summary = client.get(f"/api/projects/{pid}/rounds/0/summary").json()
    print("round0 summary:", {k: summary[k] for k in
          ("n_machine", "n_human", "n_done", "n_skipped", "best_value")})
    assert summary["n_skipped"] == 1 and summary["n_human"] == 1

    client.delete(f"/api/projects/{pid}")
    print("\nAPI E2E ALL OK")


if __name__ == "__main__":
    main()
