#!/usr/bin/env python3
"""WORLDPROOF step 1: compile an ontology + dataset binding into an executable,
certified world model.

Inputs (all fetched by IRI / stable URL, pinned in sources/SHA256SUMS):
  - IOF Core ontology            https://spec.industrialontologies.org/ontology/core/Core/
  - IOF Maintenance ontology     https://spec.industrialontologies.org/ontology/maintenance/Maintenance/
  - AI4I 2020 dataset (UCI 601)  10,000 milling-machine observations, 5 failure modes

Output: build/world_model.json — a typed state space + invariant set whose every
element is grounded in an ontology IRI, plus build/instances_sample.ttl and
build/observation_shapes.ttl (SHACL).

The invariants encode the documented generative physics of the AI4I dataset
(S. Matzka, "Explainable Artificial Intelligence for Predictive Maintenance
Applications", 2020): tool-wear (TWF), heat-dissipation (HDF), power (PWF) and
overstrain (OSF) failure conditions. fidelity.py measures how faithfully this
compiled model reproduces the dataset's labels; nothing is asserted without
that measurement.
"""
import csv, hashlib, json, math, pathlib, sys

import rdflib
from rdflib.namespace import OWL, RDF, RDFS

ROOT = pathlib.Path(__file__).resolve().parent
BUILD = ROOT / "build"
IOF_CORE = "https://spec.industrialontologies.org/ontology/core/Core/"
IOF_MAINT = "https://spec.industrialontologies.org/ontology/maintenance/Maintenance/"
WP = "https://w3id.org/worldproof/ai4i#"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_vocab():
    """Extract the ontology vocabulary the world model is typed against."""
    g = rdflib.Graph()
    g.parse(ROOT / "sources" / "iof-core.rdf")
    g.parse(ROOT / "sources" / "iof-maintenance.rdf")
    wanted = [
        "MaintainableMaterialItem", "DegradedState", "FailedState",
        "OperatingState", "FailureEvent", "FailureProcess", "FailureModeCode",
        "FunctioningProcess", "MaintenanceActivity", "MaintenanceProcess",
    ]
    vocab = {}
    for s in g.subjects(RDF.type, OWL.Class):
        local = str(s).rstrip("/").split("/")[-1]
        if local in wanted:
            vocab[local] = {"iri": str(s), "label": str(g.value(s, RDFS.label) or local)}
    missing = [w for w in wanted if w not in vocab]
    return vocab, missing, len(g)


# Failure-mode invariants: the documented generative rules of AI4I 2020.
# Each is expressed over the typed state space and grounded in an IOF class.
def rule_twf(row):
    return 200.0 <= row["tool_wear_min"] <= 240.0


def rule_hdf(row):
    return (row["process_temp_K"] - row["air_temp_K"]) < 8.6 and row["speed_rpm"] < 1380.0


def power_W(row):
    return row["torque_Nm"] * row["speed_rpm"] * 2.0 * math.pi / 60.0


def rule_pwf(row):
    return not (3500.0 <= power_W(row) <= 9000.0)


OSF_LIMIT = {"L": 11000.0, "M": 12000.0, "H": 13000.0}


def rule_osf(row):
    return row["tool_wear_min"] * row["torque_Nm"] > OSF_LIMIT[row["variant"]]


INVARIANTS = {
    # semantics: "deterministic" invariants certify or refute a causal claim
    # outright; "hazard_window" invariants are necessary conditions - a claim
    # outside the window is refuted, a claim inside it is plausible, never
    # certified-causal (measured: fidelity.py).
    "TWF": {"fn": rule_twf, "text": "tool wear within 200-240 min replacement window",
            "state_vars": ["tool_wear_min"], "semantics": "hazard_window"},
    "HDF": {"fn": rule_hdf, "text": "air/process temperature delta < 8.6 K at speed < 1380 rpm",
            "state_vars": ["air_temp_K", "process_temp_K", "speed_rpm"],
            "semantics": "deterministic"},
    "PWF": {"fn": rule_pwf, "text": "mechanical power outside [3500, 9000] W",
            "state_vars": ["torque_Nm", "speed_rpm"], "semantics": "deterministic"},
    "OSF": {"fn": rule_osf, "text": "tool wear x torque above variant overstrain limit",
            "state_vars": ["tool_wear_min", "torque_Nm", "variant"],
            "semantics": "deterministic"},
}

STATE_SPACE = {
    "machine_id": {"type": "identifier", "iof_type": "MaintainableMaterialItem"},
    "variant": {"type": "categorical", "values": ["L", "M", "H"]},
    "air_temp_K": {"type": "float", "min": 290.0, "max": 310.0},
    "process_temp_K": {"type": "float", "min": 300.0, "max": 320.0},
    "speed_rpm": {"type": "float", "min": 1100.0, "max": 3000.0},
    "torque_Nm": {"type": "float", "min": 3.0, "max": 80.0},
    "tool_wear_min": {"type": "float", "min": 0.0, "max": 260.0},
}


def read_rows():
    rows = []
    with open(ROOT / "sources" / "ai4i2020.csv", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            rows.append({
                "udi": int(r["UDI"]), "machine_id": r["Product ID"], "variant": r["Type"],
                "air_temp_K": float(r["Air temperature [K]"]),
                "process_temp_K": float(r["Process temperature [K]"]),
                "speed_rpm": float(r["Rotational speed [rpm]"]),
                "torque_Nm": float(r["Torque [Nm]"]),
                "tool_wear_min": float(r["Tool wear [min]"]),
                "labels": {m: int(r[m]) for m in ["TWF", "HDF", "PWF", "OSF", "RNF"]},
                "machine_failure": int(r["Machine failure"]),
            })
    return rows


def emit_instances_sample(vocab, rows, n=50):
    g = rdflib.Graph()
    g.bind("iofm", IOF_MAINT)
    g.bind("wp", WP)
    W = rdflib.Namespace(WP)
    for row in rows[:n]:
        obs = W[f"obs{row['udi']}"]
        machine = W[row["machine_id"]]
        g.add((machine, RDF.type, rdflib.URIRef(vocab["MaintainableMaterialItem"]["iri"])))
        g.add((obs, W.observedItem, machine))
        for var in ["air_temp_K", "process_temp_K", "speed_rpm", "torque_Nm", "tool_wear_min"]:
            g.add((obs, W[var], rdflib.Literal(row[var])))
        fired = [m for m, inv in INVARIANTS.items() if inv["fn"](row)]
        for m in fired:
            ev = W[f"failure{row['udi']}{m}"]
            g.add((ev, RDF.type, rdflib.URIRef(vocab["FailureEvent"]["iri"])))
            g.add((ev, W.failureModeCode, rdflib.Literal(m)))
            g.add((ev, W.observedIn, obs))
    return g


SHACL_SHAPES = """@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix wp: <https://w3id.org/worldproof/ai4i#> .

wp:ObservationShape a sh:NodeShape ;
    sh:targetSubjectsOf wp:observedItem ;
    sh:property [ sh:path wp:air_temp_K ; sh:minCount 1 ; sh:maxCount 1 ;
        sh:datatype xsd:double ; sh:minInclusive 290.0 ; sh:maxInclusive 310.0 ] ;
    sh:property [ sh:path wp:process_temp_K ; sh:minCount 1 ; sh:maxCount 1 ;
        sh:datatype xsd:double ; sh:minInclusive 300.0 ; sh:maxInclusive 320.0 ] ;
    sh:property [ sh:path wp:speed_rpm ; sh:minCount 1 ; sh:maxCount 1 ;
        sh:datatype xsd:double ; sh:minInclusive 1100.0 ; sh:maxInclusive 3000.0 ] ;
    sh:property [ sh:path wp:torque_Nm ; sh:minCount 1 ; sh:maxCount 1 ;
        sh:datatype xsd:double ; sh:minInclusive 3.0 ; sh:maxInclusive 80.0 ] ;
    sh:property [ sh:path wp:tool_wear_min ; sh:minCount 1 ; sh:maxCount 1 ;
        sh:datatype xsd:double ; sh:minInclusive 0.0 ; sh:maxInclusive 260.0 ] .
"""


def main():
    BUILD.mkdir(exist_ok=True)
    vocab, missing, n_triples = load_vocab()
    if missing:
        print(f"WARNING: ontology classes not found: {missing}", file=sys.stderr)
    rows = read_rows()

    model = {
        "name": "worldproof-ai4i-v0.1",
        "grounding": {
            "ontologies": [
                {"iri": IOF_CORE, "sha256": sha256(ROOT / "sources" / "iof-core.rdf")},
                {"iri": IOF_MAINT, "sha256": sha256(ROOT / "sources" / "iof-maintenance.rdf")},
            ],
            "dataset": {"name": "AI4I 2020 (UCI 601)", "rows": len(rows),
                        "sha256_zip": sha256(ROOT / "sources" / "ai4i2020.zip")},
            "vocabulary": vocab,
        },
        "state_space": STATE_SPACE,
        "invariants": {m: {"text": inv["text"], "state_vars": inv["state_vars"],
                           "semantics": inv["semantics"],
                           "iof_type": vocab.get("FailureEvent", {}).get("iri")}
                       for m, inv in INVARIANTS.items()},
        "noise_model": {"RNF": "0.1% label noise documented in dataset; not claimable as caused"},
    }
    (BUILD / "world_model.json").write_text(json.dumps(model, indent=2))

    g = emit_instances_sample(vocab, rows)
    g.serialize(BUILD / "instances_sample.ttl", format="turtle")
    (BUILD / "observation_shapes.ttl").write_text(SHACL_SHAPES)

    import pyshacl
    conforms, _, report_text = pyshacl.validate(
        data_graph=g, shacl_graph=rdflib.Graph().parse(BUILD / "observation_shapes.ttl"))
    print(f"ontology triples loaded: {n_triples}")
    print(f"vocabulary classes bound: {len(vocab)} (missing: {missing or 'none'})")
    print(f"dataset rows: {len(rows)}")
    print(f"instances sample: {len(g)} triples; SHACL conforms: {conforms}")
    if not conforms:
        print(report_text)
    print(f"compiled model -> {BUILD / 'world_model.json'}")


if __name__ == "__main__":
    main()
