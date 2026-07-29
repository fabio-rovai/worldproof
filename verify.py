#!/usr/bin/env python3
"""WORLDPROOF step 3: certified inference.

A (deliberately noisy) diagnoser proposes failure-mode diagnoses for the
dataset's failure events. Every proposal passes through a three-layer symbolic
verifier grounded in the compiled world model:

  L1 grounding   - do the claimed machine and failure-mode code resolve against
                   the compiled vocabulary and fleet?
  L2 conformance - do the claimed sensor readings match the observation record
                   and the SHACL-derived ranges?
  L3 physics     - does the claimed mode's invariant actually fire on the
                   observation's state? (three-valued: certified / plausible /
                   refuted, per invariant semantics)

Every proposal receives a certificate JSON carrying the full check chain and
the sha256 of the compiled model it was verified against. Controlled fault
injection (seeded, documented rates) measures what the verifier catches.
This evaluates the VERIFIER, not the diagnoser: the diagnoser is intentionally
error-prone to exercise every failure route.
"""
import hashlib, json, pathlib, random, statistics, time

from compile import INVARIANTS, STATE_SPACE, read_rows

ROOT = pathlib.Path(__file__).resolve().parent
BUILD = ROOT / "build"
SEED = 20261028  # DeepRAP deadline, for the record
MODES = list(INVARIANTS.keys())

# fault-injection mix over failure observations (documented, seeded):
MIX = [("correct", 0.55), ("wrong_mode", 0.20), ("fabricated_entity", 0.10),
       ("tampered_evidence", 0.15)]


def model_hash():
    return hashlib.sha256((BUILD / "world_model.json").read_bytes()).hexdigest()


def make_proposals(rows, rng):
    """Noisy diagnoser over all observations with a true failure label."""
    fleet = {r["machine_id"] for r in rows}
    proposals = []
    for row in rows:
        true_modes = [m for m in MODES if row["labels"][m]]
        if not true_modes:
            continue
        kind = rng.choices([k for k, _ in MIX], weights=[w for _, w in MIX])[0]
        claim_mode = rng.choice(true_modes)
        machine = row["machine_id"]
        evidence = {v: row[v] for v in STATE_SPACE if v in row}
        if kind == "wrong_mode":
            claim_mode = rng.choice([m for m in MODES if m not in true_modes])
        elif kind == "fabricated_entity":
            if rng.random() < 0.5:
                machine = f"X{rng.randint(90000, 99999)}"  # machine not in fleet
            else:
                claim_mode = rng.choice(["VBF", "EMF", "CFF"])  # mode not in ontology binding
        elif kind == "tampered_evidence":
            var = rng.choice(["torque_Nm", "speed_rpm", "tool_wear_min"])
            evidence = dict(evidence)
            evidence[var] = round(evidence[var] * rng.choice([0.4, 2.5]), 1)
        proposals.append({"udi": row["udi"], "machine": machine, "mode": claim_mode,
                          "evidence": evidence, "_injected": kind, "_row": row})
    return proposals


def verify(prop, fleet, mhash):
    checks, t0 = [], time.perf_counter()
    row = prop["_row"]

    ok_machine = prop["machine"] in fleet
    ok_mode = prop["mode"] in MODES
    checks.append({"layer": "L1-grounding", "machine_resolves": ok_machine,
                   "mode_resolves": ok_mode, "pass": ok_machine and ok_mode})

    ok_conf = True
    if checks[-1]["pass"]:
        for var, val in prop["evidence"].items():
            spec = STATE_SPACE[var]
            if spec["type"] == "float":
                if not (spec["min"] <= val <= spec["max"]) or abs(val - row[var]) > 1e-9:
                    ok_conf = False
        checks.append({"layer": "L2-conformance", "pass": ok_conf})
    else:
        ok_conf = False

    verdict = "refuted"
    if ok_conf:
        inv = INVARIANTS[prop["mode"]]
        fired = inv["fn"](row)
        if not fired:
            verdict = "refuted"
        elif inv["semantics"] == "deterministic":
            verdict = "certified"
        else:
            verdict = "plausible"
        checks.append({"layer": "L3-physics", "invariant_fired": fired,
                       "semantics": inv["semantics"], "pass": fired})

    latency_ms = (time.perf_counter() - t0) * 1000.0
    cert = {"claim": {"machine": prop["machine"], "failure_mode": prop["mode"],
                      "observation_udi": prop["udi"]},
            "checks": checks, "verdict": verdict,
            "world_model_sha256": mhash, "latency_ms": round(latency_ms, 4)}
    return cert, latency_ms


def main():
    rng = random.Random(SEED)
    rows = read_rows()
    fleet = {r["machine_id"] for r in rows}
    mhash = model_hash()
    proposals = make_proposals(rows, rng)

    certs, latencies = [], []
    stats = {}
    for prop in proposals:
        cert, ms = verify(prop, fleet, mhash)
        latencies.append(ms)
        kind = prop["_injected"]
        s = stats.setdefault(kind, {"n": 0, "accepted": 0, "refuted": 0})
        s["n"] += 1
        accepted = cert["verdict"] in ("certified", "plausible")
        s["accepted" if accepted else "refuted"] += 1
        cert["_injected"] = kind  # kept in eval output only
        certs.append(cert)

    # verifier detection metrics: an injected fault "caught" = refuted;
    # a correct claim "passed" = certified or plausible.
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
                           "certified": sum(1 for c in good if c["verdict"] == "certified"),
                           "plausible": sum(1 for c in good if c["verdict"] == "plausible"),
                           "wrongly_refuted": fp},
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
    print(f"correct claims: certified={result['correct_claims']['certified']} "
          f"plausible={result['correct_claims']['plausible']} wrongly_refuted={fp}")
    print(f"latency ms: p50={p50:.4f} p95={p95:.4f}")
    print("-> build/verification_results.json, build/certificates_sample.json")


if __name__ == "__main__":
    main()
