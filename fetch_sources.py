#!/usr/bin/env python3
"""Fetch all third-party sources by IRI/URL and verify against pinned hashes.

Nothing from a standards body or data repository is redistributed here: run
this script to obtain identical bytes, verified by sha256 (sources/SHA256SUMS).
"""
import hashlib, pathlib, sys, urllib.request, zipfile

ROOT = pathlib.Path(__file__).resolve().parent
SRC = ROOT / "sources"
SOURCES = [
    ("iof-core.rdf", "https://spec.industrialontologies.org/ontology/core/Core/",
     {"Accept": "application/rdf+xml"}),
    ("iof-maintenance.rdf", "https://spec.industrialontologies.org/ontology/maintenance/Maintenance/",
     {"Accept": "application/rdf+xml"}),
    ("ai4i2020.zip", "https://archive.ics.uci.edu/static/public/601/ai4i+2020+predictive+maintenance+dataset.zip",
     {}),
]


def main():
    SRC.mkdir(exist_ok=True)
    pinned = {}
    lock = SRC / "SHA256SUMS"
    if lock.exists():
        for line in lock.read_text().splitlines():
            h, name = line.split()
            pinned[name.lstrip("*")] = h

    for name, url, headers in SOURCES:
        dest = SRC / name
        if not dest.exists():
            print(f"fetching {url}")
            req = urllib.request.Request(url, headers={"User-Agent": "worldproof/0.1", **headers})
            dest.write_bytes(urllib.request.urlopen(req).read())
        h = hashlib.sha256(dest.read_bytes()).hexdigest()
        status = "OK" if pinned.get(name) == h else ("UNPINNED" if name not in pinned else "MISMATCH")
        print(f"{status:9} {name}  {h}")
        if status == "MISMATCH":
            sys.exit(f"hash mismatch for {name}: upstream changed; review before trusting")

    with zipfile.ZipFile(SRC / "ai4i2020.zip") as z:
        z.extract("ai4i2020.csv", SRC)
    print("sources ready.")


if __name__ == "__main__":
    main()
