#!/usr/bin/env python3
"""Fetch the NASA C-MAPSS turbofan degradation dataset (FD001) and verify
against pinned hashes. Ontologies (IOF Core + Maintenance) are reused from the
repository root: run ../../fetch_sources.py first.

Source: NASA Prognostics Center of Excellence data repository
(A. Saxena, K. Goebel, D. Simon, N. Eklund, "Damage Propagation Modeling for
Aircraft Engine Run-to-Failure Simulation", PHM 2008). US Government work;
fetched by URL, hash-pinned, not redistributed here.
"""
import hashlib, pathlib, sys, urllib.request, zipfile

ROOT = pathlib.Path(__file__).resolve().parent
SRC = ROOT / "sources"
REPO = ROOT.parent.parent
URL = ("https://phm-datasets.s3.amazonaws.com/NASA/"
       "6.+Turbofan+Engine+Degradation+Simulation+Data+Set.zip")
INNER = "6. Turbofan Engine Degradation Simulation Data Set/CMAPSSData.zip"
FD001 = ["train_FD001.txt", "test_FD001.txt", "RUL_FD001.txt", "readme.txt"]


def main():
    SRC.mkdir(exist_ok=True)
    for onto in ["iof-core.rdf", "iof-maintenance.rdf"]:
        if not (REPO / "sources" / onto).exists():
            sys.exit(f"missing {REPO / 'sources' / onto}: run the repo-root "
                     "fetch_sources.py first (ontologies are shared)")

    pinned = {}
    lock = SRC / "SHA256SUMS"
    if lock.exists():
        for line in lock.read_text().splitlines():
            h, name = line.split()
            pinned[name.lstrip("*")] = h

    dest = SRC / "cmapss.zip"
    if not dest.exists():
        print(f"fetching {URL}")
        req = urllib.request.Request(URL, headers={"User-Agent": "worldproof/0.1"})
        dest.write_bytes(urllib.request.urlopen(req).read())

    with zipfile.ZipFile(dest) as z:
        (SRC / "CMAPSSData.zip").write_bytes(z.read(INNER))
    with zipfile.ZipFile(SRC / "CMAPSSData.zip") as z:
        for name in FD001:
            (SRC / name).write_bytes(z.read(name))

    ok = True
    for name in ["cmapss.zip", "CMAPSSData.zip"] + FD001[:3]:
        h = hashlib.sha256((SRC / name).read_bytes()).hexdigest()
        status = "OK" if pinned.get(name) == h else ("UNPINNED" if name not in pinned else "MISMATCH")
        print(f"{status:9} {name}  {h}")
        ok = ok and status != "MISMATCH"
    if not ok:
        sys.exit("hash mismatch: upstream changed; review before trusting")
    print("sources ready.")


if __name__ == "__main__":
    main()
