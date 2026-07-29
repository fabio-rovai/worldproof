#!/bin/zsh
# WORLDPROOF-proposer overnight: baseline eval -> LoRA train -> adapter eval -> report.
set -u
cd /Users/fabio/projects/worldproof-ft
PY=/Users/fabio/projects/qwen-ies-ft/.venv311/bin/python
BASE=mlx-community/Qwen3-Coder-30B-A3B-Instruct-8bit
L=night.log
say(){ echo "[$(date +%H:%M:%S)] $1" | tee -a $L }

say "1/4 baseline eval (150 held-out real observations)"
$PY eval_proposer.py --max 150 --tag base >> $L 2>&1

say "2/4 LoRA train (1200 iters, num-layers 16, batch 2)"
$PY -m mlx_lm lora \
  --model $BASE --train --data data/mlx \
  --fine-tune-type lora --num-layers 16 --batch-size 2 \
  --iters 1200 --learning-rate 1e-4 --max-seq-length 2048 \
  --steps-per-report 20 --steps-per-eval 150 --val-batches 20 \
  --save-every 200 --adapter-path adapters --grad-checkpoint >> train.log 2>&1
say "training done: $(grep -E 'Iter [0-9]+: Val' train.log | tail -1)"

say "3/4 adapter eval (same 150 observations, same verifier)"
$PY eval_proposer.py --adapter adapters --max 150 --tag adapter >> $L 2>&1

say "4/4 report"
$PY - << 'EOF' > NIGHT_REPORT.md
import json
b=json.load(open('data/eval_base.json')); a=json.load(open('data/eval_adapter.json'))
print("# WORLDPROOF-proposer overnight report\n")
print("Verifier-in-the-loop: the compiled world model judges the LLM. Same 150 held-out REAL observations, same symbolic verifier, no LLM judge.\n")
print("| metric | base Qwen3-Coder-30B | + WORLDPROOF LoRA |")
print("|---|---|---|")
for k in ["schema_valid_rate","accepted_rate","certified_rate","gold_mode_accuracy"]:
    print(f"| {k} | {b[k]} | {a[k]} |")
print(f"| verdicts | {b['verdicts']} | {a['verdicts']} |")
print(f"\ntrain: 4,250 examples (2,000 real AI4I + 2,400 synthetic states sampled from the compiled invariant regions and boundaries - the world model generated its own curriculum). 1,200 iters LoRA (16 layers, 8-bit base) on M3 Max.")
EOF
say "DONE -> NIGHT_REPORT.md"
