#!/usr/bin/env python3
"""WORLDPROOF case study 2 (turbofan), step 3: certified inference under
seeded fault injection.

A deliberately noisy prognoser proposes claims of the form "engine E is within
30 cycles of failure at cycle C" over the 30 HELD-OUT engines. Every proposal
passes the same three-layer symbolic verifier as the AI4I pilot:

  L1 grounding    - does the claimed engine exist in the compiled fleet, and is
                    the claimed cycle inside its recorded trajectory?
  L2 conformance  - does the claimed sensor evidence match the observation
                    record and the compiled SHACL ranges?
  L3 invariant    - does the EOL30 hazard-window invariant fire on the recorded
                    state? hazard_window semantics: fires -> PLAUSIBLE (never
                    certified - the invariant is learned), does not fire ->
                    REFUTED.

Domain-honest consequence of hazard_window-only causal invariants: the verdict
"certified" is unreachable for EOL claims in this domain, and because the
invariant is imperfect (fidelity.json), the verifier both misses some
wrong-window claims (the invariant co-fires near the boundary) and wrongly
refutes some correct claims (invariant false negatives). Both rates are
measured and published below - certificates make the imperfection inspectable
instead of hiding it.

This evaluates the VERIFIER, not the prognoser: the prognoser is intentionally
error-prone to exercise every failure route. Seed 20261028; injection mix
documented in the output.
"""
import hashlib, json, pathlib, random, statistics, time

from compile import EOL_WINDOW, compiled_model, hi_series

ROOT = pathlib.Path(__file__).resolve().parent
BUILD = ROOT / "build"
SEED = 20261028
PROPOSALS_PER_ENGINE = 10

# fault-injection mix over held-out engines (documented, seeded):
MIX = [("correct", 0.55), ("wrong_window", 0.20), ("fabricated_entity", 0.10),
       ("tampered_evidence", 0.15)]


def model_hash():
    return hashlib.sha256((BUILD / "world_model.json").read_bytes()).hexdigest()


def make_proposals(m, rng):
    """Noisy prognoser over the held-out engines."""
    engines, sensors = m["engines"], m["sensors"]
    proposals = []
    for u in m["holdout"]:
        rows = engines[u]
        in_window = [r for r in rows if r["rul"] <= EOL_WINDOW]
        out_window = [r for r in rows if r["rul"] > EOL_WINDOW]
        for _ in range(PROPOSALS_PER_ENGINE):
            kind = rng.choices([k for k, _ in MIX], weights=[w for _, w in MIX])[0]
            unit, row = u, rng.choice(in_window)
            if kind == "wrong_window":
                row = rng.choice(out_window)
            elif kind == "fabricated_entity":
                if rng.random() < 0.5:
                    unit = rng.randint(900, 999)          # engine not in fleet
                else:
                    row = dict(row, cycle=len(rows) + rng.randint(10, 60))  # cycle beyond record
            evidence = {s: row[s] for s in sensors}
            if kind == "tampered_evidence":
                s = rng.choice(sensors)
                evidence = dict(evidence)
                evidence[s] = round(evidence[s] * rng.choice([0.9, 1.1]), 4)
            proposals.append({"unit": unit, "cycle": row["cycle"],
                              "evidence": evidence, "_injected": kind})
    return proposals


def verify(prop, m, theta, mhash):
    checks, t0 = [], time.perf_counter()
    engines, sensors, ranges = m["engines"], m["sensors"], m["ranges"]

    rows = engines.get(prop["unit"])
    ok_engine = rows is not None
    ok_cycle = ok_engine and 1 <= prop["cycle"] <= len(rows)
    checks.append({"layer": "L1-grounding", "engine_resolves": ok_engine,
                   "cycle_in_record": ok_cycle, "pass": ok_engine and ok_cycle})

    ok_conf = False
    if checks[-1]["pass"]:
        row = rows[prop["cycle"] - 1]
        ok_conf = all(
            ranges[s]["min"] <= v <= ranges[s]["max"] and abs(v - row[s]) <= 1e-9
            for s, v in prop["evidence"].items())
        checks.append({"layer": "L2-conformance", "pass": ok_conf})

    verdict = "refuted"
    if ok_conf:
        h = hi_series(rows[:prop["cycle"]], sensors, m["stats"], m["signs"])
        fired = h[-1] >= theta
        verdict = "plausible" if fired else "refuted"
        checks.append({"layer": "L3-invariant", "invariant": "EOL30",
                       "invariant_fired": fired, "semantics": "hazard_window",
                       "pass": fired})

    latency_ms = (time.perf_counter() - t0) * 1000.0
    cert = {"claim": {"engine": prop["unit"], "cycle": prop["cycle"],
                      "assertion": f"within {EOL_WINDOW} cycles of failure"},
            "checks": checks, "verdict": verdict,
            "world_model_sha256": mhash, "latency_ms": round(latency_ms, 4)}
    return cert, latency_ms


def main():
    rng = random.Random(SEED)
    m = compiled_model()
    theta = m["calibration"]["theta"]
    mhash = model_hash()
    proposals = make_proposals(m, rng)

    certs, latencies, stats = [], [], {}
    for prop in proposals:
        cert, ms = verify(prop, m, theta, mhash)
        latencies.append(ms)
        kind = prop["_injected"]
        s = stats.setdefault(kind, {"n": 0, "accepted": 0, "refuted": 0})
        s["n"] += 1
        s["accepted" if cert["verdict"] == "plausible" else "refuted"] += 1
        cert["_injected"] = kind  # kept in eval output only
        certs.append(cert)

    bad = [c for c in certs if c["_injected"] != "correct"]
    good = [c for c in certs if c["_injected"] == "correct"]
    tp = sum(1 for c in bad if c["verdict"] == "refuted")
    fp = sum(1 for c in good if c["verdict"] == "refuted")
    fn = len(bad) - tp
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0

    lat_sorted = sorted(latencies)
    p50 = statistics.median(lat_sorted)
    p95 = lat_sorted[int(0.95 * len(lat_sorted)) - 1]

    result = {
        "seed": SEED, "proposals": len(proposals), "injection_mix": dict(MIX),
        "per_injection": stats,
        "fault_detection": {"tp": tp, "fp": fp, "fn": fn,
                            "precision": round(precision, 4), "recall": round(recall, 4)},
        "correct_claims": {"n": len(good),
                           "certified": 0,
                           "plausible": sum(1 for c in good if c["verdict"] == "plausible"),
                           "wrongly_refuted": fp,
                           "note": "certified unreachable by design: the EOL30 invariant "
                                   "is learned (hazard_window), never deterministic"},
        "certificate_coverage": 1.0,
        "latency_ms": {"p50": round(p50, 4), "p95": round(p95, 4)},
        "world_model_sha256": mhash,
    }
    (BUILD / "certificates_sample.json").write_text(
        json.dumps([{k: v for k, v in c.items() if k != "_injected"} for c in certs[:20]], indent=2))
    (BUILD / "verification_results.json").write_text(json.dumps(result, indent=2))

    print(f"proposals: {len(proposals)} (every one receives a certificate)")
    for kind, s in stats.items():
        print(f"  {kind:18} n={s['n']:4}  accepted={s['accepted']:4}  refuted={s['refuted']:4}")
    print(f"fault detection: precision={precision:.4f} recall={recall:.4f} "
          f"(tp={tp} fp={fp} fn={fn})")
    print(f"correct claims: plausible={result['correct_claims']['plausible']} "
          f"wrongly_refuted={fp} certified=0 (unreachable for learned invariants)")
    print(f"latency ms: p50={p50:.4f} p95={p95:.4f}")
    print("-> build/verification_results.json, build/certificates_sample.json")


if __name__ == "__main__":
    main()
