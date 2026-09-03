.PHONY: install install-unlocked lock lint fmt test test-integration eval gate audit run-api \
        demo demo-selftest demo-static demo-server portability docs-check \
        ui-install ui-check ui-dev drop-ui

# Name the offline profile DELIBERATELY. Absence is not consent: an unset profile variable is a
# distinct state that refuses the seeded dev personas and every other relaxation, so every target
# here (which IS an offline local run) says so rather than relying on a fallback. `?=` keeps an
# override from the environment working: `EXAMPLE_PROFILE=gcp make run-api` still does.
export CONTRACT_PROFILE ?= local

# The demo surface runs from a source checkout, so it works before `pip install -e .` as well as
# after. One variable, used by every demo target: a target that forgot it would work on the
# author's machine and nowhere else.
PYTHON ?= python
PYRUN = PYTHONPATH=src $(if $(wildcard .venv/bin/python),.venv/bin/python,$(PYTHON))

# Locked, reproducible install (practices check D1): every version comes from the committed
# lockfile, then the project itself with --no-deps so the lock stays authoritative. This is the
# same install CI and the Dockerfile perform, so "works on my machine" and "works in CI" mean
# the same set of versions.
install:
	pip install -r requirements-dev.lock
	pip install --no-deps -e .

# The unlocked resolve. Use it only to see what a dependency change WOULD pull; then run
# `make lock` and commit the result, so nothing ships from an uncommitted resolution.
install-unlocked:
	pip install -e ".[dev]"

# Recompile both lockfiles from pyproject.toml. Needs `uv` on PATH and network access; it is an
# authoring step, never a gate step. --universal resolves across the supported interpreters so
# one lockfile installs on every version in the CI matrix.
lock:
	python3 scripts/lock.py

lint:
	ruff check src tests eval scripts
	ruff format --check src tests eval scripts
	mypy src

fmt:
	ruff format src tests eval scripts
	ruff check --fix src tests eval scripts

# tests/unit + tests/contract. tests/integration is deselected by the marker, so the gate needs
# no credentials, no network and no cloud SDK.
test:
	pytest -m 'not integration'

# The other half, run deliberately: it needs a live project and a reachable console, and each
# test skips (never passes) when its configuration is absent.
test-integration:
	pytest -m integration

eval:
	python eval/run_eval.py

# The full OFFLINE gate. It is deliberately network-free, so it runs on a plane and in a
# no-egress environment; the dependency audit needs a vulnerability feed and therefore lives in
# `make audit` locally and in the hard-gate workflow's supply-chain job, where it is a HARD
# failure, not an advisory one.
gate: lint test eval

# The supply-chain half of the gate (needs network). CI runs the same two commands.
audit:
	pip-audit -r requirements-dev.lock --disable-pip --no-deps
	pip-audit -r requirements-gcp.lock --disable-pip --no-deps

run-api:
	python -m contract_obligation_extraction.api.app

# --------------------------------------------------------------------------------------- #
# The demo surface. Deliberately OUTSIDE `make gate`: the gate proves the service and must stay
# fast and offline, while these prove the story the service is presented with. They are still
# enforced, by the hosted GitHub Actions check on every pull request and push to main, and by
# tests/unit/test_demo_surface.py in the offline gate. See scripts/README.md.
# --------------------------------------------------------------------------------------- #

# Presenter-paced: starts its own loopback server, opens the page, narrates on THIS terminal and
# waits for you at each step. Enter runs the step, a number jumps, r restarts, q quits.
demo:
	$(PYRUN) scripts/walkthrough.py

# The same walkthrough, unattended and headless, asserting every step. Non-zero on failure. No
# browser engine is installed or needed: it drives the demo server over loopback HTTP.
demo-selftest:
	$(PYRUN) scripts/walkthrough.py --auto --headless

# The screenshots path: run the arc to the end, then render static pages with no framework.
demo-static:
	$(PYRUN) scripts/demo.py demo.json
	$(PYRUN) scripts/render_ui.py demo.json out

# Just the live server, to drive by hand in a browser at http://127.0.0.1:8099.
demo-server:
	$(PYRUN) scripts/demo_server.py

# The executable portability claim: named checks, pass or fail each, non-zero if any fails.
portability:
	$(PYRUN) scripts/portability_demo.py

# Relative links resolve, code fences close, no em-dash or en-dash in shipped prose.
docs-check:
	$(PYRUN) scripts/check_docs_links.py

# --------------------------------------------------------------------------------------- #
# The ui/ micro-frontend. Requires node; nothing in `make gate` does.
# --------------------------------------------------------------------------------------- #

ui-install:
	npm ci --prefix ui

# What the ui-gate workflow runs, so a failure is reproducible locally in one command.
ui-check:
	npm ci --prefix ui
	npm --prefix ui run lint
	npm --prefix ui test
	NEXT_TELEMETRY_DISABLED=1 npm --prefix ui run build
	npm --prefix ui run assert-hydratable
	npm audit --audit-level=high --prefix ui

ui-dev:
	npm --prefix ui run dev

# Remove the UI in the ONE step that keeps the repo consistent. Deleting ui/ by hand leaves the
# npm dependabot ecosystem pointing at a directory that no longer exists (dependabot errors on
# that) and a CI job with nothing to do; tests/unit/test_ui_surface.py fails the gate until both
# halves agree, in either direction.
drop-ui:
	$(PYRUN) scripts/drop_ui.py
