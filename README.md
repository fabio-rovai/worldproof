# WORLDPROOF

**Compile an ontology and a dataset into an executable world model whose every
inference and every plan carries a machine-checkable certificate.**

Maintained by [Tesseract Academy](https://gov.tesseract.academy). v0.1, working
pilot on real industrial-maintenance data.

## The claim

Neural systems propose; a compiled symbolic world model verifies. If the world
model is compiled from a formal ontology and measured against reality, its
verdicts can be certified - not "the model seems confident", but "this claim
passed these named checks against this hashed model, or it was refuted".

This repository is a small, end-to-end, fully reproducible demonstration of
that loop on 10,000 real milling-machine observations:

```
IOF ontologies + AI4I 2020 data
        |  compile.py
        v
 typed state space + grounded invariants        (build/world_model.json)
        |  fidelity.py   -> is the compiled model TRUE? measured, published
        |  verify.py     -> certified inference: 3-layer verifier + certificates
        |  plan_check.py -> verified planning: plan certificates + refutation
```

## At a glance (all numbers computed by the scripts in this repo)

- **Grounding is real:** 10 classes bound from the [Industrial Ontologies
  Foundry](https://spec.industrialontologies.org/) Core + Maintenance
  ontologies (4,334 triples); instance graph passes SHACL.
- **The compiled model is measured, not assumed.** Against all 10,000
  observations, the three deterministic failure invariants (heat dissipation,
  power, overstrain) reproduce the dataset's labels at **precision = recall =
  1.0000**. The tool-wear invariant is exposed as what it really is - a
  stochastic *hazard window* (recall 0.93 as a necessary condition) - so the
  verifier treats it three-valued: **certified / plausible / refuted**.
- **Certified inference:** a deliberately noisy diagnoser makes 330 failure
  diagnoses under seeded fault injection (wrong mode, fabricated entities,
  tampered evidence). The symbolic verifier catches injected faults at
  **precision 1.0000, recall 0.9671**, wrongly refutes **zero** correct
  claims, and emits a certificate for **100%** of proposals at **~1 microsecond
  median latency** (compiled flat checks, no reasoner in the loop).
  The 5 misses are wrong-mode claims whose invariant genuinely co-fires - an
  attribution ambiguity the certificate records rather than hides.
- **Verified planning:** a greedy scheduler plans maintenance for the 1,000
  at-risk machines (329 in failed state); the plan verifier certifies it
  against grounding, completeness, capacity and precedence invariants - and
  demonstrably **refutes** a damaged plan, naming the violated checks.
- **The known LLM-planner failure taxonomy, answered with measurements.**
  Published planning evaluations report five recurring failure classes for
  language-model planners. `plan_robustness.py` constructs each and records
  what the verifier does: **symbol obfuscation** - verdict identical on 30/30
  fully renamed instances (structural verification cannot memorise surface
  forms); **incomplete plans** - 5/5 truncations caught, down to 10 dropped
  activities in 1,000; **hallucinated actions** - 3/3 out-of-vocabulary
  activities caught; **unsolvability detection** - 4/4 correct, refusing to
  certify when capacity times horizon falls below demand; **scale** -
  verification cost stays flat at 0.20 to 0.24 microseconds per activity from
  1,000 to 10,000 activities.

## Reproduce it

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python fetch_sources.py   # IOF Core + Maintenance, AI4I 2020 (hash-pinned)
.venv/bin/python compile.py         # ontology + data -> world_model.json (+SHACL)
.venv/bin/python fidelity.py        # measure the model against all 10,000 rows
.venv/bin/python verify.py          # certified inference under fault injection
.venv/bin/python plan_check.py      # plan certificates + refutation demo
```

Everything is deterministic (seed recorded in the outputs). Committed results
in `build/` were produced by exactly these scripts; the certificate JSONs
carry the sha256 of the compiled model they were verified against.

## Why this matters

Large models fail at exactly the point where high-stakes deployment begins:
they cannot show *why* an output should be trusted. Post-hoc monitoring flags
errors after they act; constrained decoding limits expressiveness; human
review does not scale. The alternative demonstrated here is architectural:
**compile the domain's formal knowledge into an executable world model, and
make passage through it the condition for an output to exist.** Reasoning,
abstraction and planning then inherit certificates from the same substrate.

This pilot is deliberately small and deliberately honest about scope: the
"diagnoser" is a synthetic noise process (it evaluates the verifier, not an
LLM); one dataset, one domain, invariants hand-derived from the dataset's
documented physics rather than learned. What it demonstrates is the contract:
grounded state, measured fidelity, three-valued certificates, refutable plans.
The research programme that scales this - ontology-to-model compilation,
neural proposers, formal soundness of the certificate calculus, cross-domain
transfer - is where this is heading.

## Case studies

- **[Turbofan degradation](case-studies/turbofan/)** - the same certified-world-model contract transferred to NASA C-MAPSS field-like data: learned hazard-window invariants, measured imperfect fidelity (F1 0.84), fault detection at recall 0.992, and the honest cost of learned invariants quantified (12.5% wrongly-refuted rate, inspectable via certificates).

## Lineage

Built on [open-ontologies](https://github.com/fabio-rovai/open-ontologies)
(validation primitives; developed from work delivered for the UK National
Digital Twin Programme) and the measurement methodology of
[industrial-ontology-crosswalks](https://github.com/fabio-rovai/industrial-ontology-crosswalks)
(falsifiability of industrial standards). Related instruments:
[worldkernel](https://github.com/fabio-rovai/worldkernel) (world-model
benchmark witnesses).

## Sources and licences

| Source | Licence | Use here |
|---|---|---|
| [IOF Core](https://spec.industrialontologies.org/ontology/core/Core/) + [Maintenance](https://spec.industrialontologies.org/ontology/maintenance/Maintenance/) | see IOF spec site | fetched by IRI, hash-pinned, not redistributed |
| [AI4I 2020](https://archive.ics.uci.edu/dataset/601/ai4i+2020+predictive+maintenance+dataset) (UCI ML Repository; S. Matzka 2020) | CC BY 4.0 | fetched by URL, hash-pinned, not redistributed |

Code and results in this repository: Apache-2.0.

## Work with us

Tesseract Academy builds certified AI and data infrastructure for government
and industry (UK National Digital Twin Programme, Innovate UK, Welsh
Government). If your organisation needs AI whose outputs can be *proved*
grounded - not just monitored - write to
**fabio@thetesseractacademy.com** or visit
[gov.tesseract.academy](https://gov.tesseract.academy).
