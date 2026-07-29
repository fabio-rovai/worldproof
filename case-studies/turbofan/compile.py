#!/usr/bin/env python3
"""WORLDPROOF case study 2 (turbofan), step 1: compile ontology + dataset
binding into an executable, certified world model for engine degradation.

Same contract as the AI4I pilot, different epistemics: C-MAPSS FD001 is
field-like run-to-failure data with NO documented generative rule set, so the
end-of-life invariant here is LEARNED (calibrated on a train split of engines)
and carries "hazard_window" semantics from birth - it can never certify, only
attest plausibility. The deterministic invariants of this domain are the sanity
invariants (cycle monotonicity, compiled sensor ranges), and those CAN refute
outright.

Inputs:
  - IOF Core + Maintenance ontologies   (shared, repo root sources/, hash-pinned)
  - NASA C-MAPSS train_FD001.txt        (100 run-to-failure engines, 20,631 cycles)

Everything below is computed, not assumed: sensor selection (per-engine rank
correlation with cycle), health-index normalisation (calibration-split stats),
and the end-of-life threshold (F1-optimal on the calibration split only).
fidelity.py then measures the compiled model on the 30 HELD-OUT engines.
"""
import hashlib, json, math, pathlib, random, sys

import rdflib
from rdflib.namespace import OWL, RDF, RDFS

ROOT = pathlib.Path(__file__).resolve().parent
REPO = ROOT.parent.parent
SRC = ROOT / "sources"
BUILD = ROOT / "build"
IOF_CORE = "https://spec.industrialontologies.org/ontology/core/Core/"
IOF_MAINT = "https://spec.industrialontologies.org/ontology/maintenance/Maintenance/"
WP = "https://w3id.org/worldproof/cmapss#"

SEED = 20261028
N_CALIBRATION = 70          # engines used to fit; the other 30 are held out
EOL_WINDOW = 30             # "within 30 cycles of failure"
HI_SMOOTH = 5               # trailing (causal) moving-average window for HI
N_SENSORS = 8               # size of the compiled state space (computed ranking)
SENSOR_NAMES = [f"s{i}" for i in range(1, 22)]


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_vocab():
    """Bind the IOF vocabulary the world model is typed against (shared with
    the AI4I pilot; same fetched, hash-pinned files)."""
    g = rdflib.Graph()
    g.parse(REPO / "sources" / "iof-core.rdf")
    g.parse(REPO / "sources" / "iof-maintenance.rdf")
    wanted = [
        "MaintainableMaterialItem", "DegradedState", "FailedState",
        "OperatingState", "FailureEvent", "FailureProcess",
        "MaintenanceActivity", "MaintenanceProcess",
    ]
    vocab = {}
    for s in g.subjects(RDF.type, OWL.Class):
        local = str(s).rstrip("/").split("/")[-1]
        if local in wanted:
            vocab[local] = {"iri": str(s), "label": str(g.value(s, RDFS.label) or local)}
    missing = [w for w in wanted if w not in vocab]
    return vocab, missing, len(g)


def read_engines():
    """train_FD001: space-separated columns unit, cycle, 3 op settings, s1..s21.
    Returns {unit: [row, ...]} with per-cycle true RUL (run-to-failure data)."""
    engines = {}
    for line in (SRC / "train_FD001.txt").read_text().splitlines():
        parts = line.split()
        if not parts:
            continue
        unit, cycle = int(parts[0]), int(parts[1])
        sensors = {SENSOR_NAMES[i]: float(parts[5 + i]) for i in range(21)}
        engines.setdefault(unit, []).append({"unit": unit, "cycle": cycle, **sensors})
    for unit, rows in engines.items():
        rows.sort(key=lambda r: r["cycle"])
        last = rows[-1]["cycle"]
        for r in rows:
            r["rul"] = last - r["cycle"]
    return engines


def split_units(engines):
    units = sorted(engines)
    rng = random.Random(SEED)
    rng.shuffle(units)
    return sorted(units[:N_CALIBRATION]), sorted(units[N_CALIBRATION:])


def _ranks(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(xs, ys):
    rx, ry = _ranks(xs), _ranks(ys)
    n = len(rx)
    mx, my = sum(rx) / n, sum(ry) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    if sxx == 0 or syy == 0:
        return 0.0
    return sxy / math.sqrt(sxx * syy)


def select_sensors(engines, cal_units):
    """Rank all 21 sensors by mean per-engine |Spearman rho(sensor, cycle)| on
    the calibration split. Computed, not assumed: flat sensors score ~0."""
    table = {}
    for s in SENSOR_NAMES:
        rhos = []
        for u in cal_units:
            rows = engines[u]
            rhos.append(spearman([r[s] for r in rows], [r["cycle"] for r in rows]))
        mean_rho = sum(rhos) / len(rhos)
        table[s] = round(mean_rho, 4)
    ranked = sorted(table, key=lambda s: -abs(table[s]))
    return ranked[:N_SENSORS], table


def fit_health_index(engines, cal_units, sensors):
    """Per-sensor z-scoring on calibration cycles, oriented so degradation is
    positive; HI = mean oriented z, smoothed by a trailing 5-cycle mean."""
    stats = {}
    for s in sensors:
        vals = [r[s] for u in cal_units for r in engines[u]]
        mu = sum(vals) / len(vals)
        sd = math.sqrt(sum((v - mu) ** 2 for v in vals) / len(vals)) or 1.0
        stats[s] = {"mu": mu, "sd": sd}
    return stats


def hi_series(rows, sensors, stats, signs):
    raw = []
    for r in rows:
        z = [signs[s] * (r[s] - stats[s]["mu"]) / stats[s]["sd"] for s in sensors]
        raw.append(sum(z) / len(z))
    out = []
    for i in range(len(raw)):
        w = raw[max(0, i - HI_SMOOTH + 1): i + 1]
        out.append(sum(w) / len(w))
    return out


def calibrate_threshold(engines, cal_units, sensors, stats, signs):
    """F1-optimal threshold for (HI >= theta) <=> (RUL <= 30), fitted on the
    calibration split ONLY."""
    his, labels = [], []
    for u in cal_units:
        rows = engines[u]
        h = hi_series(rows, sensors, stats, signs)
        his.extend(h)
        labels.extend(1 if r["rul"] <= EOL_WINDOW else 0 for r in rows)
    lo, hi = min(his), max(his)
    best = (None, -1.0, 0.0, 0.0)
    for k in range(1, 400):
        theta = lo + (hi - lo) * k / 400.0
        tp = fp = fn = 0
        for h, y in zip(his, labels):
            pred = h >= theta
            if pred and y:
                tp += 1
            elif pred and not y:
                fp += 1
            elif y and not pred:
                fn += 1
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * p * r / (p + r) if p + r else 0.0
        if f1 > best[1]:
            best = (theta, f1, p, r)
    return {"theta": round(best[0], 4), "f1": round(best[1], 4),
            "precision": round(best[2], 4), "recall": round(best[3], 4),
            "n_cycles": len(his), "positives": sum(labels)}


def sensor_ranges(engines, cal_units, sensors):
    """Compiled per-sensor ranges: calibration min/max widened by 2% of span.
    Deterministic conformance invariant; coverage on held-out is MEASURED
    (fidelity.py), not assumed."""
    ranges = {}
    for s in sensors:
        vals = [r[s] for u in cal_units for r in engines[u]]
        lo, hi = min(vals), max(vals)
        pad = 0.02 * (hi - lo) or 0.01
        ranges[s] = {"min": round(lo - pad, 4), "max": round(hi + pad, 4)}
    return ranges


def emit_instances_sample(vocab, engines, holdout, sensors, stats, signs, theta, n_engines=2):
    g = rdflib.Graph()
    g.bind("iofm", IOF_MAINT)
    g.bind("wp", WP)
    W = rdflib.Namespace(WP)
    for u in holdout[:n_engines]:
        rows = engines[u]
        h = hi_series(rows, sensors, stats, signs)
        eng = W[f"engine{u}"]
        g.add((eng, RDF.type, rdflib.URIRef(vocab["MaintainableMaterialItem"]["iri"])))
        for i, r in enumerate(rows[-25:], start=len(rows) - 25):
            obs = W[f"obs_u{u}_c{r['cycle']}"]
            g.add((obs, W.observedItem, eng))
            g.add((obs, W.cycle, rdflib.Literal(r["cycle"])))
            for s in sensors:
                g.add((obs, W[s], rdflib.Literal(r[s])))
            if h[i] >= theta:
                st = W[f"state_u{u}_c{r['cycle']}"]
                g.add((st, RDF.type, rdflib.URIRef(vocab["DegradedState"]["iri"])))
                g.add((st, W.stateOf, eng))
                g.add((st, W.evidencedBy, obs))
        ev = W[f"failure_u{u}"]
        g.add((ev, RDF.type, rdflib.URIRef(vocab["FailureEvent"]["iri"])))
        g.add((ev, W.failedItem, eng))
        g.add((ev, W.atCycle, rdflib.Literal(rows[-1]["cycle"])))
        fs = W[f"failedstate_u{u}"]
        g.add((fs, RDF.type, rdflib.URIRef(vocab["FailedState"]["iri"])))
        g.add((fs, W.stateOf, eng))
    return g


def shacl_shapes(ranges):
    props = "\n".join(
        f"""    sh:property [ sh:path wp:{s} ; sh:minCount 1 ; sh:maxCount 1 ;
        sh:datatype xsd:double ; sh:minInclusive {r["min"]} ; sh:maxInclusive {r["max"]} ] ;"""
        for s, r in ranges.items())
    return f"""@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix wp: <https://w3id.org/worldproof/cmapss#> .

wp:ObservationShape a sh:NodeShape ;
    sh:targetSubjectsOf wp:observedItem ;
    sh:property [ sh:path wp:cycle ; sh:minCount 1 ; sh:maxCount 1 ;
        sh:datatype xsd:integer ; sh:minInclusive 1 ] ;
{props}
    .
"""


def compiled_model():
    """Build (or rebuild) the full compiled model in memory. Shared entry point
    for fidelity.py and verify.py."""
    engines = read_engines()
    cal, holdout = split_units(engines)
    sensors, rho_table = select_sensors(engines, cal)
    signs = {s: (1 if rho_table[s] >= 0 else -1) for s in sensors}
    stats = fit_health_index(engines, cal, sensors)
    calib = calibrate_threshold(engines, cal, sensors, stats, signs)
    ranges = sensor_ranges(engines, cal, sensors)
    return {
        "engines": engines, "cal": cal, "holdout": holdout, "sensors": sensors,
        "rho_table": rho_table, "signs": signs, "stats": stats,
        "calibration": calib, "ranges": ranges,
    }


def main():
    BUILD.mkdir(exist_ok=True)
    vocab, missing, n_triples = load_vocab()
    if missing:
        print(f"WARNING: ontology classes not found: {missing}", file=sys.stderr)
    m = compiled_model()
    engines, cal, holdout = m["engines"], m["cal"], m["holdout"]
    n_cycles = sum(len(r) for r in engines.values())

    model = {
        "name": "worldproof-cmapss-fd001-v0.1",
        "grounding": {
            "ontologies": [
                {"iri": IOF_CORE, "sha256": sha256(REPO / "sources" / "iof-core.rdf")},
                {"iri": IOF_MAINT, "sha256": sha256(REPO / "sources" / "iof-maintenance.rdf")},
            ],
            "dataset": {
                "name": "NASA C-MAPSS FD001 (PCoE; Saxena & Goebel 2008)",
                "engines": len(engines), "cycles": n_cycles,
                "sha256_train": sha256(SRC / "train_FD001.txt"),
                "sha256_test": sha256(SRC / "test_FD001.txt"),
                "sha256_rul": sha256(SRC / "RUL_FD001.txt"),
            },
            "vocabulary": vocab,
        },
        "split": {"seed": SEED, "calibration_units": cal, "holdout_units": holdout},
        "sensor_selection": {
            "method": "mean per-engine Spearman rho(sensor, cycle) on calibration split",
            "rho_by_sensor": m["rho_table"], "selected": m["sensors"],
        },
        "state_space": {
            "engine_id": {"type": "identifier", "iof_type": vocab.get("MaintainableMaterialItem", {}).get("iri")},
            "cycle": {"type": "int", "min": 1},
            **{s: {"type": "float", **m["ranges"][s]} for s in m["sensors"]},
        },
        "health_index": {
            "sensors": m["sensors"], "orientation": m["signs"],
            "z_stats": {s: {"mu": round(v["mu"], 4), "sd": round(v["sd"], 4)}
                        for s, v in m["stats"].items()},
            "smoothing": f"trailing {HI_SMOOTH}-cycle mean (causal)",
            "threshold": m["calibration"]["theta"],
            "calibration_fit": m["calibration"],
        },
        "invariants": {
            "EOL30": {"text": f"engine within {EOL_WINDOW} cycles of failure iff "
                              f"health index >= {m['calibration']['theta']}",
                      "semantics": "hazard_window", "provenance": "learned",
                      "iof_type": vocab.get("FailureEvent", {}).get("iri")},
            "CYCLE_MONOTONE": {"text": "cycle counter strictly increasing by 1 per engine, from 1",
                               "semantics": "deterministic", "provenance": "structural"},
            "SENSOR_RANGE": {"text": "selected sensors within compiled calibration ranges",
                             "semantics": "deterministic", "provenance": "compiled percentile ranges"},
        },
    }
    (BUILD / "world_model.json").write_text(json.dumps(model, indent=2))

    g = emit_instances_sample(vocab, engines, holdout, m["sensors"], m["stats"],
                              m["signs"], m["calibration"]["theta"])
    g.serialize(BUILD / "instances_sample.ttl", format="turtle")
    (BUILD / "observation_shapes.ttl").write_text(shacl_shapes(m["ranges"]))

    import pyshacl
    conforms, _, report_text = pyshacl.validate(
        data_graph=g, shacl_graph=rdflib.Graph().parse(BUILD / "observation_shapes.ttl"))

    print(f"ontology triples loaded: {n_triples}")
    print(f"vocabulary classes bound: {len(vocab)} (missing: {missing or 'none'})")
    print(f"engines: {len(engines)}  cycles: {n_cycles}  "
          f"split: {len(cal)} calibration / {len(holdout)} held-out (seed {SEED})")
    print("sensor ranking (|mean rho|): " + ", ".join(
        f"{s}={m['rho_table'][s]:+.3f}" for s in m["sensors"]))
    c = m["calibration"]
    print(f"EOL{EOL_WINDOW} threshold theta={c['theta']} "
          f"(calibration F1={c['f1']}, P={c['precision']}, R={c['recall']})")
    print(f"instances sample: {len(g)} triples; SHACL conforms: {conforms}")
    if not conforms:
        print(report_text)
    print(f"compiled model -> {BUILD / 'world_model.json'}")


if __name__ == "__main__":
    main()
