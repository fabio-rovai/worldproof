#!/usr/bin/env python3
"""WORLDPROOF-proposer: generate the fine-tune curriculum FROM the compiled
world model.

The world model (worldproof/build/world_model.json + invariant code) generates
its own training data: real AI4I observations plus synthetic states sampled
from the invariant regions and their boundaries. Gold completions are the
diagnosis claims the verifier would certify (or, for hazard-window TWF,
accept as plausible; healthy states get explicit no_failure claims).

Output: data/mlx/{train,valid,test}.jsonl in mlx_lm chat format, and
data/test_states.jsonl (held-out states for verifier-in-the-loop evaluation).
Test rows are REAL observations only; synthetic augmentation goes to train.
"""
import json, pathlib, random, sys

sys.path.insert(0, str(pathlib.Path.home() / "projects" / "worldproof"))
from compile import INVARIANTS, STATE_SPACE, read_rows  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent
SEED = 20261028
SYSTEM = (
    "You are a maintenance diagnosis engine for a machine fleet, grounded in the "
    "Industrial Ontologies Foundry maintenance vocabulary. Given one observation "
    "as JSON, output ONLY a JSON claim object: "
    '{"machine": "<id>", "failure_mode": "TWF|HDF|PWF|OSF|no_failure", '
    '"evidence": {<the sensor fields your diagnosis relies on, with their exact '
    'observed values>}}. Rules: TWF (tool wear failure) is only PLAUSIBLE when '
    "tool_wear_min is in [200,240]. HDF requires (process_temp_K - air_temp_K) < 8.6 "
    "and speed_rpm < 1380. PWF requires mechanical power torque_Nm*speed_rpm*2*pi/60 "
    "outside [3500,9000] W. OSF requires tool_wear_min*torque_Nm above the variant "
    "limit (L:11000, M:12000, H:13000). Never invent machines, modes or values."
)


def obs_json(row):
    return {k: row[k] for k in
            ["machine_id", "variant", "air_temp_K", "process_temp_K",
             "speed_rpm", "torque_Nm", "tool_wear_min"]}


def gold_claim(row):
    fired = [m for m, inv in INVARIANTS.items() if inv["fn"](row)]
    det = [m for m in fired if INVARIANTS[m]["semantics"] == "deterministic"]
    mode = det[0] if det else (fired[0] if fired else "no_failure")
    if mode == "no_failure":
        ev_vars = ["tool_wear_min", "torque_Nm", "speed_rpm"]
    else:
        ev_vars = INVARIANTS[mode]["state_vars"]
    return {"machine": row["machine_id"], "failure_mode": mode,
            "evidence": {v: row[v] for v in ev_vars}}


def example(row):
    return {"messages": [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": json.dumps(obs_json(row))},
        {"role": "assistant", "content": json.dumps(gold_claim(row))},
    ]}


def synth_state(rng, mid):
    """Sample a synthetic state, biased to invariant regions and boundaries."""
    variant = rng.choice(["L", "M", "H"])
    row = {"machine_id": mid, "variant": variant,
           "air_temp_K": round(rng.uniform(295.0, 304.0), 1),
           "process_temp_K": 0.0,
           "speed_rpm": float(rng.randint(1170, 2900)),
           "torque_Nm": round(rng.uniform(10.0, 77.0), 1),
           "tool_wear_min": float(rng.randint(0, 253))}
    row["process_temp_K"] = round(row["air_temp_K"] + rng.uniform(7.4, 12.0), 1)
    target = rng.choice(["HDF", "PWF", "OSF", "TWF", "healthy", "boundary"])
    if target == "HDF":
        row["process_temp_K"] = round(row["air_temp_K"] + rng.uniform(7.5, 8.55), 1)
        row["speed_rpm"] = float(rng.randint(1170, 1379))
    elif target == "PWF":
        if rng.random() < 0.5:
            row["torque_Nm"], row["speed_rpm"] = round(rng.uniform(3.5, 12.0), 1), float(rng.randint(1200, 1700))
        else:
            row["torque_Nm"], row["speed_rpm"] = round(rng.uniform(55.0, 77.0), 1), float(rng.randint(1900, 2860))
    elif target == "OSF":
        row["tool_wear_min"] = float(rng.randint(180, 253))
        limit = {"L": 11000.0, "M": 12000.0, "H": 13000.0}[variant]
        row["torque_Nm"] = round(limit / row["tool_wear_min"] * rng.uniform(1.02, 1.25), 1)
    elif target == "TWF":
        row["tool_wear_min"] = float(rng.randint(200, 240))
    elif target == "boundary":
        row["tool_wear_min"] = float(rng.choice([198, 199, 200, 240, 241, 242]))
        row["speed_rpm"] = float(rng.choice([1378, 1379, 1380, 1381, 1382]))
    # clamp to state space
    for var, spec in STATE_SPACE.items():
        if spec["type"] == "float":
            row[var] = min(max(row[var], spec["min"]), spec["max"])
    row["labels"] = {}
    return row


def main():
    rng = random.Random(SEED)
    rows = read_rows()
    rng.shuffle(rows)

    failure = [r for r in rows if any(inv["fn"](r) for inv in INVARIANTS.values())]
    healthy = [r for r in rows if r not in failure]  # slow but fine at 10k? no:
    # (identity-based split instead, cheap)
    fail_ids = {id(r) for r in failure}
    healthy = [r for r in rows if id(r) not in fail_ids]

    # held-out test: real observations only (200 failure-region + 100 healthy)
    test_rows = failure[:200] + healthy[:100]
    train_fail = failure[200:]
    train_healthy = healthy[100:1300]  # keep classes balanced-ish

    synth = [synth_state(rng, f"S{i:05d}") for i in range(2400)]

    train_pool = ([example(r) for r in train_fail]
                  + [example(r) for r in train_healthy]
                  + [example(r) for r in synth])
    rng.shuffle(train_pool)
    valid, train = train_pool[:150], train_pool[150:]

    out = ROOT / "data" / "mlx"
    out.mkdir(parents=True, exist_ok=True)
    for name, data in [("train", train), ("valid", valid),
                       ("test", [example(r) for r in test_rows])]:
        with open(out / f"{name}.jsonl", "w") as f:
            for ex in data:
                f.write(json.dumps(ex) + "\n")
    with open(ROOT / "data" / "test_states.jsonl", "w") as f:
        for r in test_rows:
            rec = {k: v for k, v in r.items()}
            f.write(json.dumps(rec) + "\n")

    n_fail_train = len(train_fail)
    print(f"train={len(train)} (real failure {n_fail_train}, real healthy "
          f"{len(train_healthy)}, synthetic {len(synth)}), valid={len(valid)}, "
          f"test={len(test_rows)} (real only: 200 failure-region, 100 healthy)")


if __name__ == "__main__":
    main()
