# BUILD_REPORT — worldproof v0.1

Built 29 July 2026. This report states exactly what was fetched, what was
computed, what worked, and what the pilot does NOT show.

## Fetched (all by IRI/URL, sha256-pinned in sources/SHA256SUMS)

- IOF Core ontology (spec.industrialontologies.org): parsed, 3,889 triples.
- IOF Maintenance ontology: parsed, 445 triples, 34 OWL classes; all 10
  vocabulary classes required by the pilot resolved (none missing).
- AI4I 2020 dataset, UCI ML Repository id 601 (S. Matzka, 2020, CC BY 4.0):
  10,000 rows, 5 failure-mode label columns. Extracted from the official zip.

## Computed (deterministic; seed 20261028 recorded in outputs)

1. `compile.py` — bound vocabulary, emitted `build/world_model.json` (typed
   state space, 4 grounded invariants), 50-observation instance sample (350
   triples) and SHACL shapes. SHACL conforms: True.
2. `fidelity.py` — invariants vs labels over all 10,000 rows:
   HDF 115/115, PWF 95/95, OSF 98/98 at precision = recall = 1.0000.
   TWF: recall 0.9348, precision 0.0544 as a point predictor — reclassified as
   a hazard-window (necessary-condition) invariant accordingly. 3 of 46 TWF
   labels sit outside the documented 200–240 min window. RNF (19 labels) is
   documented dataset noise and excluded from the model.
3. `verify.py` — 330 diagnoses (one per observation with a modelled failure
   label; the 9 RNF-only failures have no modelled cause and are excluded).
   Injection mix 55% correct / 20% wrong-mode / 10% fabricated-entity / 15%
   tampered-evidence. Results: fault detection precision 1.0000, recall
   0.9671; 0 correct claims wrongly refuted; certificate coverage 100%;
   latency p50 0.0010 ms, p95 0.0013 ms on an Apple M3 Max (single thread).
4. `plan_check.py` — 1,000 at-risk machines (329 failed state). Greedy plan:
   1,000 activities over 17 shifts, certified (P1–P4 all pass). Damaged plan
   (15 machines dropped, shift 0 overbooked, 1 unknown machine): refuted,
   violations named (P1, P2, P3).

## Honest limitations (do not overclaim)

- The "diagnoser" is a seeded synthetic noise process, not an LLM. This pilot
  evaluates the VERIFIER and the compiled-model contract, not neural
  diagnosis quality.
- Invariants were hand-derived from the dataset's documented generative
  physics (Matzka 2020), not learned or extracted automatically from the
  ontology. Automating ontology→invariant compilation is the research gap
  this pilot motivates; here the ontology contributes typing, vocabulary and
  grounding, not the physics.
- AI4I 2020 is itself synthetic (published, widely used, but generated data);
  the perfect fidelity of the three deterministic invariants reflects that
  the generative rules are documented. On field data, fidelity would be
  learned and imperfect — which is precisely why fidelity measurement is a
  first-class pipeline stage.
- The 5 undetected wrong-mode injections are claims whose invariant co-fired
  with the true mode (physically consistent misattribution). Certificates
  record invariant firing, so downstream consumers can see the ambiguity;
  resolving attribution needs causal machinery beyond this pilot.
- Latency numbers are for microsecond-scale flat checks on compiled state;
  they do not include RDF parsing or SHACL validation, which run at compile
  time by design.
- Single domain, single dataset, no cross-domain transfer demonstrated here.

## Could not be obtained / not attempted

- IOF ontology licence text was not vendored; sources are fetched by IRI and
  hash-pinned instead of redistributed.
- No Coq/mechanised soundness proof of the certificate calculus exists yet;
  the calculus here is code, not a formal object.
