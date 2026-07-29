PY=.venv/bin/python
all: fetch compile fidelity verify plan
fetch: ; $(PY) fetch_sources.py
compile: ; $(PY) compile.py
fidelity: ; $(PY) fidelity.py
verify: ; $(PY) verify.py
plan: ; $(PY) plan_check.py
.PHONY: all fetch compile fidelity verify plan
