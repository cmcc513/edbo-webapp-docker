"""Run simulated human-in-the-loop campaigns against the running edbo platform.

Usage (from webapp/backend):
    python -m tests.sim.run_all                # all three reactions
    python -m tests.sim.run_all suzuki         # a subset
    python -m tests.sim.run_all --base http://127.0.0.1:8100
"""
from __future__ import annotations

import sys
import argparse

from .campaign import Sim, run_campaign
from .reactions import REACTIONS


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("reactions", nargs="*", default=list(REACTIONS),
                    help="subset of: " + ", ".join(REACTIONS))
    ap.add_argument("--base", default="http://127.0.0.1:8100")
    args = ap.parse_args()

    keys = args.reactions or list(REACTIONS)
    unknown = [k for k in keys if k not in REACTIONS]
    if unknown:
        print("Unknown reactions:", unknown, "\nAvailable:", list(REACTIONS))
        sys.exit(2)

    sim = Sim(args.base)
    try:
        sim.h.get("/api/health").raise_for_status()
    except Exception as exc:  # noqa: BLE001
        print(f"Cannot reach backend at {args.base}: {exc}")
        print("Start it with: python -m uvicorn app.main:app --port 8100")
        sys.exit(1)

    results = []
    for k in keys:
        results.append(run_campaign(sim, REACTIONS[k]))

    # -------- summary --------
    print("\n" + "=" * 74)
    print("SIMULATION SUMMARY")
    print("=" * 74)
    header = f"{'reaction':<34}{'space':>7}{'best/max':>12}{'exp':>5}{'skip':>5}{'human':>6}{'R2':>6}"
    print(header)
    print("-" * 74)
    all_checks_ok = True
    for r in results:
        all_checks_ok &= r.ok
        print(f"{r.reaction[:33]:<34}{r.space_size:>7}"
              f"{r.best_found:>6.1f}/{r.global_max:<5.1f}"
              f"{r.n_experiments:>5}{r.n_skipped:>5}{r.n_human:>6}"
              f"{(f'{r.r2:.2f}' if r.r2 is not None else '-'):>6}")

    print("\nChecks:")
    total = passed = 0
    for r in results:
        for name, ok, detail in r.checks:
            total += 1
            passed += int(ok)
            if not ok:
                print(f"  FAIL [{r.reaction[:20]}] {name} {detail}")
    print(f"\n{passed}/{total} checks passed across {len(results)} reactions.")
    print("RESULT:", "ALL OK" if (all_checks_ok and passed == total) else "FAILURES PRESENT")
    sys.exit(0 if (all_checks_ok and passed == total) else 1)


if __name__ == "__main__":
    main()
