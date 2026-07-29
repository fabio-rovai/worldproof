#!/usr/bin/env python3
"""Verifier-in-the-loop evaluation: the WORLDPROOF symbolic verifier judges the
LLM proposer. No LLM judge anywhere; the compiled world model is the metric.

Usage:
  python eval_proposer.py --max 150                 # base model
  python eval_proposer.py --adapter adapters --max 150   # fine-tuned
Writes data/eval_<tag>.json
"""
import argparse, json, pathlib, re, sys, time

sys.path.insert(0, str(pathlib.Path.home() / "projects" / "worldproof"))
from compile import INVARIANTS, STATE_SPACE  # noqa: E402
from gen_data import SYSTEM, obs_json, gold_claim  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent
BASE = "mlx-community/Qwen3-Coder-30B-A3B-Instruct-8bit"
MODES = set(INVARIANTS) | {"no_failure"}


def extract_json(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def verify_claim(claim, row):
    """Three-layer verdict for a proposer claim against the observation row."""
    if not isinstance(claim, dict):
        return "invalid_schema"
    mode = claim.get("failure_mode")
    if claim.get("machine") != row["machine_id"] or mode not in MODES:
        return "refuted"          # L1 grounding
    ev = claim.get("evidence")
    if not isinstance(ev, dict) or not ev:
        return "refuted"
    for var, val in ev.items():   # L2 conformance: cited evidence must be real
        if var not in STATE_SPACE or not isinstance(val, (int, float)):
            return "refuted"
        spec = STATE_SPACE[var]
        if spec["type"] == "float" and abs(float(val) - row[var]) > 1e-6:
            return "refuted"
    fired = [m for m, inv in INVARIANTS.items() if inv["fn"](row)]
    det = [m for m in fired if INVARIANTS[m]["semantics"] == "deterministic"]
    if mode == "no_failure":      # L3 physics
        return "certified" if not fired else "refuted"
    if mode not in fired:
        return "refuted"
    return "certified" if INVARIANTS[mode]["semantics"] == "deterministic" else "plausible"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", default=None)
    ap.add_argument("--max", type=int, default=150)
    ap.add_argument("--tag", default=None)
    args = ap.parse_args()
    tag = args.tag or ("adapter" if args.adapter else "base")

    from mlx_lm import load, generate
    model, tokenizer = load(BASE, adapter_path=args.adapter)

    rows = [json.loads(l) for l in open(ROOT / "data" / "test_states.jsonl")][:args.max]
    counts = {"certified": 0, "plausible": 0, "refuted": 0, "invalid_schema": 0}
    mode_correct = 0
    t0 = time.time()
    for i, row in enumerate(rows):
        prompt = tokenizer.apply_chat_template(
            [{"role": "system", "content": SYSTEM},
             {"role": "user", "content": json.dumps(obs_json(row))}],
            add_generation_prompt=True)
        text = generate(model, tokenizer, prompt=prompt, max_tokens=160)
        claim = extract_json(text)
        verdict = verify_claim(claim, row)
        counts[verdict] += 1
        gold = gold_claim(row)["failure_mode"]
        if isinstance(claim, dict) and claim.get("failure_mode") == gold:
            mode_correct += 1
        if (i + 1) % 25 == 0:
            print(f"  {i+1}/{len(rows)} {counts} mode_acc={mode_correct/(i+1):.3f}",
                  flush=True)

    n = len(rows)
    accepted = counts["certified"] + counts["plausible"]
    result = {"tag": tag, "model": BASE, "adapter": args.adapter, "n": n,
              "verdicts": counts,
              "accepted_rate": round(accepted / n, 4),
              "certified_rate": round(counts["certified"] / n, 4),
              "schema_valid_rate": round(1 - counts["invalid_schema"] / n, 4),
              "gold_mode_accuracy": round(mode_correct / n, 4),
              "minutes": round((time.time() - t0) / 60, 1)}
    (ROOT / "data" / f"eval_{tag}.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
