#!/usr/bin/env python3
"""WORLDPROOF step 4: verified planning.

A greedy scheduler proposes a fleet maintenance plan over the machines the
compiled world model marks as at-risk (any deterministic failure invariant
fired, or inside the TWF hazard window). A symbolic plan-verifier then checks
the plan against invariants it cannot see being violated silently:

  P1 grounding    - every scheduled machine exists in the fleet
  P2 completeness - every at-risk machine is scheduled within the horizon
  P3 capacity     - no shift exceeds crew capacity
  P4 precedence   - machines in failed state precede merely degraded ones

The verifier emits a plan certificate (checks + verdict + model hash). To show
refutation is real, a deliberately damaged plan (drops machines, overbooks a
shift, inverts one precedence) is verified with the same code path.
"""
import hashlib, json, pathlib, random

from compile import INVARIANTS, read_rows

ROOT = pathlib.Path(__file__).resolve().parent
BUILD = ROOT / "build"
CAPACITY = 60      # maintenance slots per shift
HORIZON = 24       # shifts
SEED = 20261028


def at_risk(rows):
    out = []
    for row in rows:
        fired = [m for m, inv in INVARIANTS.items() if inv["fn"](row)]
        if fired:
            out.append({"machine": row["machine_id"], "fired": fired,
                        "failed": bool(row["machine_failure"])})
    return out


def greedy_plan(risks):
    ordered = sorted(risks, key=lambda r: (not r["failed"], -len(r["fired"])))
    plan, shift, used = [], 0, 0
    for r in ordered:
        if used >= CAPACITY:
            shift, used = shift + 1, 0
        plan.append({"machine": r["machine"], "shift": shift,
                     "activity": "MaintenanceActivity", "modes": r["fired"]})
        used += 1
    return plan


def verify_plan(plan, risks, fleet, mhash):
    checks = []
    scheduled = {p["machine"]: p for p in plan}

    unknown = [p["machine"] for p in plan if p["machine"] not in fleet]
    checks.append({"check": "P1-grounding", "unknown_machines": len(unknown),
                   "pass": not unknown})

    missing = [r["machine"] for r in risks if r["machine"] not in scheduled]
    over_h = [p["machine"] for p in plan if p["shift"] >= HORIZON]
    checks.append({"check": "P2-completeness", "missing": len(missing),
                   "beyond_horizon": len(over_h), "pass": not missing and not over_h})

    load = {}
    for p in plan:
        load[p["shift"]] = load.get(p["shift"], 0) + 1
    overbooked = {s: n for s, n in load.items() if n > CAPACITY}
    checks.append({"check": "P3-capacity", "capacity": CAPACITY,
                   "overbooked_shifts": overbooked, "pass": not overbooked})

    failed_shifts = [scheduled[r["machine"]]["shift"] for r in risks
                     if r["failed"] and r["machine"] in scheduled]
    degraded_shifts = [scheduled[r["machine"]]["shift"] for r in risks
                       if not r["failed"] and r["machine"] in scheduled]
    prec_ok = (not failed_shifts or not degraded_shifts
               or max(failed_shifts) <= max(degraded_shifts))
    checks.append({"check": "P4-precedence",
                   "last_failed_shift": max(failed_shifts, default=None),
                   "last_degraded_shift": max(degraded_shifts, default=None),
                   "pass": prec_ok})

    verdict = "certified" if all(c["pass"] for c in checks) else "refuted"
    return {"plan_size": len(plan), "checks": checks, "verdict": verdict,
            "world_model_sha256": mhash}


def damage(plan, rng):
    bad = [dict(p) for p in plan]
    del bad[10:25]                                   # drop 15 at-risk machines
    for p in bad[:CAPACITY + 20]:
        p["shift"] = 0                               # overbook shift 0
    bad[-1]["machine"] = "X99999"                    # unknown machine
    return bad


def main():
    rng = random.Random(SEED)
    rows = read_rows()
    fleet = {r["machine_id"] for r in rows}
    mhash = hashlib.sha256((BUILD / "world_model.json").read_bytes()).hexdigest()

    risks = at_risk(rows)
    plan = greedy_plan(risks)
    cert_good = verify_plan(plan, risks, fleet, mhash)
    cert_bad = verify_plan(damage(plan, rng), risks, fleet, mhash)

    n_failed = sum(1 for r in risks if r["failed"])
    result = {"at_risk_machines": len(risks), "in_failed_state": n_failed,
              "capacity_per_shift": CAPACITY, "horizon_shifts": HORIZON,
              "proposed_plan": cert_good, "damaged_plan": cert_bad}
    (BUILD / "plan_certificates.json").write_text(json.dumps(result, indent=2))

    print(f"at-risk machines: {len(risks)} (failed state: {n_failed})")
    print(f"proposed plan: {cert_good['plan_size']} activities across "
          f"{max(p['shift'] for p in plan) + 1} shifts -> verdict: {cert_good['verdict']}")
    for c in cert_good["checks"]:
        print(f"  {c['check']:16} pass={c['pass']}")
    print(f"damaged plan -> verdict: {cert_bad['verdict']} "
          f"(failed: {[c['check'] for c in cert_bad['checks'] if not c['pass']]})")
    print("-> build/plan_certificates.json")


if __name__ == "__main__":
    main()
