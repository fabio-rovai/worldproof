#!/usr/bin/env python3
"""WORLDPROOF step 2: measure the compiled world model against reality.

For each failure mode, compare the compiled invariant's prediction against the
dataset's ground-truth label over all 10,000 observations. A certified world
model earns its certificates only if this fidelity is measured and published.
RNF (random failures) is reported as irreducible noise, not modelled.
"""
import json, pathlib

from compile import INVARIANTS, read_rows

ROOT = pathlib.Path(__file__).resolve().parent


def prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f1


def main():
    rows = read_rows()
    out = {}
    print(f"{'mode':5} {'label+':>7} {'pred+':>7} {'TP':>5} {'FP':>5} {'FN':>5} "
          f"{'prec':>7} {'rec':>7} {'F1':>7}")
    for mode, inv in INVARIANTS.items():
        tp = fp = fn = pred_pos = label_pos = 0
        for row in rows:
            pred = inv["fn"](row)
            label = bool(row["labels"][mode])
            pred_pos += pred
            label_pos += label
            if pred and label:
                tp += 1
            elif pred and not label:
                fp += 1
            elif label and not pred:
                fn += 1
        p, r, f1 = prf(tp, fp, fn)
        out[mode] = {"label_pos": label_pos, "pred_pos": pred_pos, "tp": tp,
                     "fp": fp, "fn": fn, "precision": round(p, 4),
                     "recall": round(r, 4), "f1": round(f1, 4)}
        print(f"{mode:5} {label_pos:7} {pred_pos:7} {tp:5} {fp:5} {fn:5} "
              f"{p:7.4f} {r:7.4f} {f1:7.4f}")

    rnf = sum(r["labels"]["RNF"] for r in rows)
    out["RNF"] = {"label_pos": rnf, "note": "documented random noise; excluded from model"}
    print(f"RNF   {rnf:7} (irreducible label noise, not modelled)")

    (ROOT / "build" / "fidelity.json").write_text(json.dumps(out, indent=2))
    print(f"-> build/fidelity.json")


if __name__ == "__main__":
    main()
