#!/usr/bin/env python3
"""WORLDPROOF case study 2 (turbofan), step 2: measure the compiled model
against reality it has NOT seen.

Three measurements, all published:
  1. EOL30 hazard-window invariant on the 30 HELD-OUT engines (never used in
     sensor selection, normalisation or threshold fit). This is learned,
     field-like fidelity: precision/recall will NOT be 1.0 - that is the point,
     and the reason the invariant carries hazard_window semantics.
  2. The same invariant spot-checked at the final cycle of each of the 100
     official TEST engines (truth from RUL_FD001.txt; trajectories end
     mid-life, so this probes the window at arbitrary distances from failure).
  3. The deterministic invariants (cycle monotonicity, compiled sensor ranges):
     pass/fail counts over all engines / all held-out cycles.
"""
import json, pathlib

from compile import (EOL_WINDOW, SENSOR_NAMES, SRC, compiled_model, hi_series)

ROOT = pathlib.Path(__file__).resolve().parent
BUILD = ROOT / "build"


def prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    return round(p, 4), round(r, 4), round(f1, 4)


def eval_split(engines, units, sensors, stats, signs, theta):
    tp = fp = fn = tn = 0
    for u in units:
        rows = engines[u]
        h = hi_series(rows, sensors, stats, signs)
        for hi, r in zip(h, rows):
            pred, y = hi >= theta, r["rul"] <= EOL_WINDOW
            if pred and y:
                tp += 1
            elif pred and not y:
                fp += 1
            elif y and not pred:
                fn += 1
            else:
                tn += 1
    p, r, f1 = prf(tp, fp, fn)
    return {"n_cycles": tp + fp + fn + tn, "positives": tp + fn,
            "tp": tp, "fp": fp, "fn": fn, "precision": p, "recall": r, "f1": f1}


def read_test_engines():
    engines = {}
    for line in (SRC / "test_FD001.txt").read_text().splitlines():
        parts = line.split()
        if not parts:
            continue
        unit = int(parts[0])
        sensors = {SENSOR_NAMES[i]: float(parts[5 + i]) for i in range(21)}
        engines.setdefault(unit, []).append({"unit": unit, "cycle": int(parts[1]), **sensors})
    ruls = [int(float(x)) for x in (SRC / "RUL_FD001.txt").read_text().split()]
    return engines, ruls


def eval_test_final_cycles(sensors, stats, signs, theta):
    engines, ruls = read_test_engines()
    tp = fp = fn = tn = 0
    for u in sorted(engines):
        rows = sorted(engines[u], key=lambda r: r["cycle"])
        h = hi_series(rows, sensors, stats, signs)
        pred, y = h[-1] >= theta, ruls[u - 1] <= EOL_WINDOW
        if pred and y:
            tp += 1
        elif pred and not y:
            fp += 1
        elif y and not pred:
            fn += 1
        else:
            tn += 1
    p, r, f1 = prf(tp, fp, fn)
    return {"n_engines": tp + fp + fn + tn, "positives": tp + fn,
            "tp": tp, "fp": fp, "fn": fn, "precision": p, "recall": r, "f1": f1}


def eval_deterministic(engines, holdout, sensors, ranges):
    mono_pass = sum(
        1 for u in engines
        if [r["cycle"] for r in engines[u]] == list(range(1, len(engines[u]) + 1)))
    in_range = total = 0
    for u in holdout:
        for r in engines[u]:
            total += 1
            if all(ranges[s]["min"] <= r[s] <= ranges[s]["max"] for s in sensors):
                in_range += 1
    return {"cycle_monotone": {"engines_pass": mono_pass, "engines_total": len(engines)},
            "sensor_range_holdout": {"cycles_in_range": in_range, "cycles_total": total,
                                     "coverage": round(in_range / total, 4)}}


def main():
    m = compiled_model()
    theta = m["calibration"]["theta"]
    args = (m["sensors"], m["stats"], m["signs"], theta)

    holdout = eval_split(m["engines"], m["holdout"], *args)
    calib = eval_split(m["engines"], m["cal"], *args)
    test_final = eval_test_final_cycles(*args)
    det = eval_deterministic(m["engines"], m["holdout"], m["sensors"], m["ranges"])

    out = {"eol_window_cycles": EOL_WINDOW, "theta": theta,
           "EOL30_holdout": holdout, "EOL30_calibration_fit": calib,
           "EOL30_test_final_cycles": test_final, "deterministic": det}
    (BUILD / "fidelity.json").write_text(json.dumps(out, indent=2))

    print(f"EOL{EOL_WINDOW} (HI >= {theta}), held-out 30 engines "
          f"({holdout['n_cycles']} cycles, {holdout['positives']} in-window):")
    print(f"  precision={holdout['precision']} recall={holdout['recall']} "
          f"f1={holdout['f1']}  (tp={holdout['tp']} fp={holdout['fp']} fn={holdout['fn']})")
    print(f"  [calibration-split fit for reference: f1={calib['f1']}]")
    print(f"EOL{EOL_WINDOW} at final cycles of 100 official test engines "
          f"({test_final['positives']} truly in-window):")
    print(f"  precision={test_final['precision']} recall={test_final['recall']} "
          f"f1={test_final['f1']}  (tp={test_final['tp']} fp={test_final['fp']} fn={test_final['fn']})")
    d = det["cycle_monotone"]
    print(f"CYCLE_MONOTONE: {d['engines_pass']}/{d['engines_total']} engines pass")
    s = det["sensor_range_holdout"]
    print(f"SENSOR_RANGE (held-out): {s['cycles_in_range']}/{s['cycles_total']} "
          f"cycles in compiled ranges (coverage {s['coverage']})")
    print("-> build/fidelity.json")


if __name__ == "__main__":
    main()
