"""Headless smoke test of the EdboSession optimization loop (no HTTP)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.edbo_session import EdboSession  # noqa: E402


def main():
    components = {
        "base": ["DBU", "MTBD", "potassium carbonate"],
        "solvent": ["THF", "Toluene", "DMSO"],
        "temperature": [20, 30, 40],
    }
    encoding = {"base": "ohe", "solvent": "ohe", "temperature": "numeric"}

    print("Building space...")
    s = EdboSession.build(
        components=components, encoding=encoding,
        acquisition_function="EI", init_method="rand", target="yield", batch_size=3,
    )
    print("  space size:", s.space_size())
    print("  component keys:", s.component_keys)
    print("  options:", s.component_options())

    print("Init sample...")
    s.init_sample(seed=0, batch_size=3, init_method="rand")
    props = s.proposals_with_prediction()
    print("  proposals:", len(props))
    for p in props:
        print("   ", p["domain_index"], p["components"], p.get("predicted_mean"))

    # Simulate lab results: only do 2 of the 3 machine proposals
    obs = [(props[0]["domain_index"], 25.0), (props[1]["domain_index"], 60.0)]
    print("Add observations (2 of 3 done, 1 skipped)...")
    s.add_observations(obs)

    print("Run BO round...")
    s.run(acq_function="EI", batch_size=3)
    props2 = s.proposals_with_prediction()
    print("  next proposals:", len(props2))
    for p in props2:
        print("   ", p["domain_index"], p["components"],
              "mean=", p.get("predicted_mean"), "var=", p.get("predicted_var"))

    # Human experiment reverse lookup
    human = {"base": "DBU", "solvent": "DMSO", "temperature": 40}
    di = s.resolve_domain_index(human)
    print("Human experiment", human, "-> domain_index", di)
    assert di is not None, "reverse lookup failed"

    bad = {"base": "DBU", "solvent": "DMSO", "temperature": 999}
    assert s.resolve_domain_index(bad) is None, "should reject out-of-space combo"

    print("Regression:", (s.regression() or {}).get("r2"))

    # Persistence round-trip
    tmp = Path(__file__).parent / "_tmp_bo.pkl"
    s.save(str(tmp))
    s2 = EdboSession.load(str(tmp))
    assert s2.resolve_domain_index(human) == di
    tmp.unlink(missing_ok=True)

    print("\nALL OK")


if __name__ == "__main__":
    main()
