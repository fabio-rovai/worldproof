# Case study 2: turbofan degradation — transfer to field-like data

**The same certified-world-model contract, second domain, learned invariants.**
Where the [AI4I pilot](../../README.md) compiles *documented physics* (perfect
fidelity, deterministic certificates), this case study compiles *learned*
degradation behaviour from NASA's C-MAPSS turbofan data — and shows what the
certificate machinery honestly does when the world model itself is imperfect.

## What transfers

Everything structural: IOF ontology grounding (same `DegradedState` /
`FailedState` / `FailureEvent` vocabulary), hash-pinned sources, a compiled
typed state space with SHACL shapes, three-layer verification (grounding /
conformance / invariant), three-valued certificates, seeded fault injection.
What changes is the epistemic status of the invariants:

- **Deterministic invariants** (cycle monotonicity, compiled sensor ranges)
  still certify and refute outright: 100/100 engines pass monotonicity;
  compiled ranges cover 99.98% of held-out cycles.
- **The end-of-life invariant is learned**, so it can never certify — only
  mark claims *plausible* or *refuted*. A health index (per-sensor z-scores
  over the 8 sensors with the strongest monotone degradation signal, ranked by
  Spearman correlation with cycle age on calibration engines only) feeds an
  F1-optimal threshold for "within 30 cycles of failure", fitted on the
  calibration split only.

## At a glance (all numbers from the scripts in this directory)

- **Compiled-model fidelity, measured on 30 held-out engines (6,440 cycles):**
  the learned EOL-30 hazard window detects true end-of-life cycles at
  precision 0.809, recall 0.875 (F1 0.841); at the final observed cycle of the
  100 official test engines: precision 0.90, recall 0.72. Imperfect by
  construction — and published, because a world model that is not measured
  cannot ground a certificate.
- **Certified inference under seeded fault injection** (300 claims of the form
  "engine E is within 30 cycles of failure at cycle C"): injected faults
  (wrong-window claims, fabricated engines, tampered sensor evidence) caught
  at **recall 0.992, precision 0.848**; tampered evidence and fabricated
  entities are caught at 100%. The cost of a learned invariant is visible and
  quantified: 22 of 176 correct claims (12.5%) are wrongly refuted where the
  health index disagrees with ground-truth RUL. Median verification latency
  0.12 ms.
- **Certificate coverage 100%** — every claim gets a certificate carrying the
  checks it passed, the invariant's epistemic status (learned vs
  deterministic) and the sha256 of the compiled model.

## Reproduce it

```bash
cd case-studies/turbofan
../../.venv/bin/python fetch_sources.py   # NASA C-MAPSS FD001 (hash-pinned)
../../.venv/bin/python compile.py         # sensors, health index, threshold -> world model
../../.venv/bin/python fidelity.py        # measure the hazard window honestly
../../.venv/bin/python verify.py          # certified inference under fault injection
```

Deterministic throughout (seed 20261028; calibration/held-out engine split is
seeded and disjoint).

## Honest limitations

- FD001 only: single operating condition, single fault mode; the health index
  is a deliberately simple linear composite. Field data would need richer
  models — the contract stays the same.
- The 30-cycle window is a modelling choice, not a physical constant.
- "Wrongly refuted" correct claims are the price of an imperfect learned
  invariant; the certificate records *why* (which check failed), so the error
  is inspectable, not silent.
- C-MAPSS is simulated (NASA's engine model); it is field-*like*, not field
  data.

## Sources

| Source | Licence | Use here |
|---|---|---|
| [NASA C-MAPSS Turbofan Engine Degradation Simulation](https://data.nasa.gov/dataset/c-mapss-aircraft-engine-simulator-data) (Saxena & Goebel, NASA PCoE) | NASA open data | fetched, hash-pinned in `sources/SHA256SUMS`, not redistributed |
| IOF Core + Maintenance ontologies | see IOF spec site | reused from repo root `sources/` |
