"""The demo surface, asserted from inside the offline gate.

A demo that is only ever run by hand before a meeting is a demo that breaks in the meeting. The
``demo-gate`` workflow runs the real walkthrough headless on every push; this module is the
cheaper half that runs in ``make gate``, so a broken demo fails the same command a developer
already runs before committing.

What is asserted here is not "the files exist". It is that the demo's ARC and its ASSERTIONS
cannot drift apart, and that the arc actually holds when the real services are driven through
it. The scripts are importable from the suite (``pythonpath = ["scripts"]`` in
``pyproject.toml``), so this drives the same code the presenter drives.
"""

from __future__ import annotations

import os
import subprocess
import sys

import demo
import pytest
import render_ui
import walkthrough

from tests import REPO_ROOT

SCRIPTS = REPO_ROOT / "scripts"


def test_every_script_is_documented_and_every_documented_script_exists() -> None:
    """The README is the demo surface's index, so it cannot silently fall behind the directory."""
    listed = (SCRIPTS / "README.md").read_text(encoding="utf-8")
    on_disk = {path.name for path in SCRIPTS.glob("*.py")}
    assert on_disk, "the demo surface is missing entirely"
    for name in sorted(on_disk):
        assert "`" + name + "`" in listed, name + " is not described in scripts/README.md"


def test_the_arc_and_its_assertions_cannot_drift() -> None:
    """A step with no expectation would narrate a claim nobody checks."""
    assert set(demo.STEP_KEYS) == set(walkthrough.CHECKS), (
        "demo.STEPS and walkthrough.CHECKS disagree: "
        + str(set(demo.STEP_KEYS).symmetric_difference(walkthrough.CHECKS))
    )
    assert len(demo.STEP_KEYS) == len(set(demo.STEP_KEYS)), "a step key is repeated"


def test_the_whole_arc_holds_when_the_real_services_are_driven_through_it() -> None:
    """Run every step against the real adapters and apply the walkthrough's own expectations."""
    run = demo.DemoRun()
    seen: list[str] = []
    while True:
        state = run.state()
        key = str(state["step"])
        problems = walkthrough.CHECKS[key](state)
        assert not problems, key + ": " + "; ".join(problems)
        seen.append(key)
        if run.done:
            break
        run.advance()
    assert seen == list(demo.STEP_KEYS)


def test_the_demo_shows_bad_news_as_well_as_good() -> None:
    """A demo with no failing panel is a sales deck. The tamper step must actually go red."""
    run = demo.DemoRun()
    run.run_to_end()
    state = run.state()
    tones = {panel["tone"] for step in state["steps"] for panel in step["panels"] if panel["tone"]}
    assert "ok" in tones
    tamper = next(step for step in state["steps"] if step["key"] == "tamper")
    assert tamper["facts"]["detected"] is True
    assert state["totals"]["chain_ok"] is False, "the tamper step left the chain looking fine"


def test_the_demo_data_is_obviously_fictional() -> None:
    cases = (demo.ROUTINE_CASE, demo.ESCALATING_CASE, demo.PII_CASE)
    for case in cases:
        assert "FICTIONAL" in case.subject, case.subject + " does not announce itself as fake"
    blob = " ".join(case.text for case in cases) + demo.ACTOR
    for real_looking in ("@gmail.", "@outlook.", "@yahoo."):
        assert real_looking not in blob
    assert ".example" in blob, "the fixtures should use .example domains"
    # RFC 5737 / RFC 3849 documentation literals, never a routable address.
    assert "192.0.2." in blob and "2001:db8:" in blob


def test_the_demo_imports_no_cloud_sdk() -> None:
    """Importing the demo surface must not pull a managed SDK in through a side door.

    In a FRESH interpreter, deliberately. Inspecting ``sys.modules`` of the running
    pytest process makes the verdict depend on test ordering: any other module in the
    suite that legitimately imports google (the IAP negative matrix does, where google-auth is
    installed) turns this green tick red, and the check says nothing about the demo either way.
    A subprocess asks the question the claim is actually about, and it is the same technique
    ``tests/contract/_sdk_free_probe.py`` uses for the adapters, for the same reason.
    """
    probe = (
        "import sys, demo, walkthrough, render_ui\n"
        "demo.DemoRun().run_to_end()\n"
        "print(','.join(demo.loaded_cloud_sdks()))\n"
    )
    env = dict(os.environ, PYTHONPATH=str(SCRIPTS) + os.pathsep + str(REPO_ROOT / "src"))
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=env,
        check=False,
    )
    assert result.returncode == 0, "the demo surface did not run in a fresh interpreter:\n" + (
        result.stderr
    )
    loaded = [name for name in result.stdout.strip().split(",") if name]
    assert not loaded, "the demo surface imported a cloud SDK: " + str(loaded)


def test_the_static_renderer_produces_a_self_contained_page() -> None:
    run = demo.DemoRun()
    run.run_to_end()
    page = render_ui.render_page(run.state())
    assert page.startswith("<!doctype html>")
    for needle in ("<style>", "Audit trail", "Findings", demo.SERVICE_NAME):
        assert needle in page, "the rendered page is missing " + needle
    # No external reference of any kind: the page has to open from a file:// URL on a locked-down
    # laptop, which is exactly where a demo gets asked for.
    for external in ("http://", "https://", "<script"):
        assert external not in page, "the rendered page reaches outside itself: " + external


def test_the_renderer_escapes_content_rather_than_interpolating_it() -> None:
    state = {
        "service": "<img src=x onerror=alert(1)>",
        "catalog_id": "X1",
        "repository": "r",
        "profile": "local",
        "region": "r",
        "step_count": 1,
        "totals": {"cases": 0, "escalated": 0, "routed": 0, "chain_ok": True},
        "steps": [
            {
                "key": "k",
                "label": "l",
                "narration": "n",
                "facts": {},
                "panels": [
                    {
                        "title": "t",
                        "note": "",
                        "tone": "",
                        "rows": [{"label": "a", "value": "<b>", "tone": ""}],
                    }
                ],
            }
        ],
    }
    page = render_ui.render_page(state)
    assert "<img src=x" not in page
    assert "&lt;img" in page and "&lt;b&gt;" in page


@pytest.mark.parametrize(
    "target",
    ["demo:", "demo-selftest:", "demo-static:", "demo-server:", "portability:", "docs-check:"],
)
def test_the_makefile_exposes_the_demo_surface(target: str) -> None:
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    assert "\n" + target in makefile, "no `make " + target.rstrip(":") + "` target"


def test_the_demo_is_not_part_of_the_hard_gate() -> None:
    """The gate proves the service. Bolting the demo onto it makes the gate slow and flaky."""
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    gate_line = next(line for line in makefile.splitlines() if line.startswith("gate:"))
    for demo_target in ("demo", "demo-selftest", "demo-static", "portability"):
        assert demo_target not in gate_line.split(":", 1)[1].split()


def test_the_demo_self_test_runs_in_ci() -> None:
    """Outside the gate is not the same as unenforced: the demo has its own required check."""
    workflow = REPO_ROOT / ".github" / "workflows" / "demo-gate.yaml"
    body = workflow.read_text(encoding="utf-8")
    for command in ("make demo-selftest", "make portability", "make docs-check"):
        assert command in body, "demo-gate.yaml does not run " + command
