# Training the proposer

**The compiled world model writes its own training curriculum, and the symbolic
verifier is the evaluation metric. There is no LLM judge anywhere in this
loop.**

The rest of this repository builds a certified world model and uses it to
verify a synthetic diagnoser. This directory closes the other half of the
contract: it takes a real language model, trains it against the world model,
and measures the result with the same verifier that certifies everything else.

## The idea

A compiled world model is a typed state space plus grounded invariants. That is
enough to do two things a language model cannot do for itself:

1. **Generate supervision.** For any observation, the invariants determine which
   failure modes fire, which evidence variables are relevant, and therefore what
   claim the verifier would certify. `gen_data.py` turns that into a curriculum
   of 4,400 examples: 2,000 real AI4I observations (800 in the failure region,
   1,200 healthy) and 2,400 synthetic states sampled from the invariant regions
   and, deliberately, from their decision boundaries - tool wear at 198/199/200
   and 240/241/242, speed at 1378 through 1382, torque set just above each
   variant's overstrain limit. 150 of those are held out as the validation split,
   leaving 4,250 for training. The world model is the annotator.
2. **Grade the output.** `eval_proposer.py` runs the same three-layer verdict as
   `verify.py`: L1 grounding (does the claimed machine exist, is the mode in
   vocabulary), L2 conformance (does every cited evidence value match the actual
   observation to 1e-6), L3 physics (does the claimed invariant actually fire).
   Deterministic invariants yield **certified**, the stochastic tool-wear hazard
   window yields **plausible**, anything else is **refuted**. The metric is the
   verifier, not a rubric and not another model.

The held-out test set is real observations only: 200 from the failure region and
100 healthy. Synthetic augmentation goes to training exclusively, so nothing the
model is scored on was invented.

## Setup

| | |
|---|---|
| Base model | `mlx-community/Qwen3-Coder-30B-A3B-Instruct-8bit` |
| Method | LoRA, 16 layers, gradient checkpointing |
| Hyperparameters | batch 2, 1,200 iters, lr 1e-4, max-seq-length 2048 |
| Data | 4,250 train / 150 valid / 300 test |
| Hardware | one Apple M3 Max, 128 GB unified memory |
| Peak memory | 36.3 GB |
| Trained tokens | 882,112 |
| Wall clock | 32m41s for training; 38m38s for the whole pipeline including both evals |

Validation loss goes 2.799 at iter 1 to 0.104 by iter 150, sits at 0.101 to
0.116 for the remaining 1,050 iterations, and finishes at 0.116. The task is
learned almost entirely in the first 150 steps; the rest of the run buys
nothing measurable and could be cut.

## Results

n = 300 held-out real observations (200 failure-region, 100 healthy), same
verifier, same prompts, no LLM judge.

| metric | base Qwen3-Coder-30B | + WORLDPROOF LoRA |
|---|---|---|
| schema_valid_rate | 1.0000 | 1.0000 |
| accepted_rate (certified + plausible) | 0.5567 | 0.8800 |
| certified_rate | 0.1667 | 0.3633 |
| gold_mode_accuracy | 0.5067 | 0.8300 |
| certified | 50 | 109 |
| plausible | 117 | 155 |
| refuted | 133 | 36 |
| invalid_schema | 0 | 0 |
| eval wall clock | 5.8 min | 6.4 min |

Refutations drop from 133 to 36, a 73% reduction. Certified claims more than
double. Agreement with the world model's own gold mode rises from roughly a coin
flip to 0.83. Schema validity was already perfect in the base model, so none of
the gain is the trivial one of teaching a 30B coder model to emit JSON.

A first pass on the first 150 of the same held-out states, run before the full
test set, is in `data/eval_base.json` and `data/eval_adapter.json`: accepted
0.6333 to 0.8667, certified 0.0467 to 0.1200, gold mode accuracy 0.5533 to
0.7933. The direction is the same; the certified rate on that subset is much
lower for both models because the first 150 rows are all failure-region states,
where the stochastic tool-wear mode caps how much can be certified rather than
merely accepted.

## Reproduce

Requires an environment with `mlx-lm` installed, on Apple silicon, and the
WORLDPROOF repository root on `sys.path` (both scripts insert
`~/projects/worldproof` themselves; edit that line if you cloned elsewhere).
Run `compile.py` in the repository root first, so `build/world_model.json` and
the invariants exist.

```bash
cd training

# 1. the world model writes the curriculum
python gen_data.py
#    -> data/mlx/{train,valid,test}.jsonl, data/test_states.jsonl

# 2. baseline: the untrained proposer, judged by the verifier
python eval_proposer.py --max 300 --tag base300

# 3. LoRA fine-tune, 1,200 iters
python -m mlx_lm lora \
  --model mlx-community/Qwen3-Coder-30B-A3B-Instruct-8bit --train \
  --data data/mlx --fine-tune-type lora --num-layers 16 --batch-size 2 \
  --iters 1200 --learning-rate 1e-4 --max-seq-length 2048 \
  --steps-per-report 20 --steps-per-eval 150 --val-batches 20 \
  --save-every 200 --adapter-path adapters --grad-checkpoint

# 4. same 300 observations, same verifier, adapter loaded
python eval_proposer.py --adapter adapters --max 300 --tag adapter300
```

`orchestrate_night.sh` is the script that actually ran this, committed verbatim
including its n=150 first pass. Its `cd` and `PY` lines point at the author's
machine and must be edited before it will run anywhere else.

Data generation is seeded (`SEED = 20261028`) and deterministic. Generation from
the model is not pinned, so exact counts will move by a few states between runs.
Adapters (3.7 GB of safetensors) and the generated `.jsonl` curriculum are
gitignored; both are reproduced by the commands above.

## Limitations

These are real and they bound the claim.

- **The gold labels come from the same compiled invariants the verifier uses.**
  This is the key caveat. What is measured here is how well the proposer
  conforms to the world model, not whether the world model is right about the
  world. That second question is answered separately and elsewhere in this
  repository: `fidelity.py` measures the three deterministic invariants against
  all 10,000 real observations at precision = recall = 1.0000, and exposes the
  tool-wear invariant as a stochastic hazard window rather than pretending it is
  deterministic. Conformance to a measured model is worth something. It is not
  independent real-world truth, and nothing in this directory establishes that.
- **One task family, one domain.** Single-observation failure-mode diagnosis on
  one milling-machine dataset. No multi-step reasoning, no planning, no
  transfer. The turbofan case study transfers the verifier but not this
  fine-tune.
- **The base model is not prompt-optimised.** Both conditions use the identical
  system prompt, which was written for the training data rather than tuned for
  the base model. Some unknown share of the gain is format and convention
  adherence that few-shot prompting or a hand-tuned prompt would also buy. No
  prompt-engineering baseline was run, so that share is not separated out.
- **8-bit quantised base.** Results are for the 8-bit MoE build. Full precision
  was not tested and could move both numbers.
- **No frontier-model comparison.** Nothing here says a larger closed model
  would not clear 0.88 accepted zero-shot. The comparison run is base versus
  adapter on the same local model, which is the cost-controlled question, not
  the capability-frontier one.
- **Certified rate is capped by the physics, not the model.** The tool-wear
  hazard window can only ever return plausible. A perfect proposer does not
  reach certified_rate 1.0 on this test set, so the headline 0.3633 should be
  read against that ceiling and not against 1.0.

## Files

| file | what it does |
|---|---|
| `gen_data.py` | compiles the curriculum from the world model; writes `data/mlx/*.jsonl` and the held-out `data/test_states.jsonl` |
| `eval_proposer.py` | verifier-in-the-loop evaluation; three-layer verdict per claim |
| `orchestrate_night.sh` | the pipeline as it was run |
| `data/eval_base300.json`, `data/eval_adapter300.json` | headline results, n=300 |
| `data/eval_base.json`, `data/eval_adapter.json` | first pass, n=150 |
