# scripts: the demo surface

Everything here is **offline, SDK-free and stdlib-only**. No cloud project, no credentials, no
API key, no browser engine, no bundler. That is not a limitation of the demo, it is the claim the
demo makes: the service works with none of those, so anybody can run it from a checkout.

None of these scripts is part of `make gate`. The gate proves the service; these prove the story
the service is presented with, which is a different job and a different failure mode. They are
still enforced, though: the hosted GitHub Actions check runs `make demo-selftest` and
`make portability` on every pull request and every push to main, and
`tests/unit/test_demo_surface.py` fails the offline gate if a script is deleted, stops importing,
or stops being listed here.

Run them from the repository root. After `make install` the package is importable and the plain
commands work; without an install, prefix with `PYTHONPATH=src`.

| Script | What it does |
|---|---|
| `demo.py` | The scripted arc, driving the REAL services over the `local` profile: bind the stack, triage a routine case, triage a consequential one and route it (rule R8), plant a national id and prove it is masked before the audit write, show the reviewer's queue, verify and export the audit trail, rewrite a record and detect it, then swap to the exit profile and watch every seam refuse. Writes the audit-view JSON. |
| `render_ui.py` | Renders that JSON to dependency-free static HTML: one page per step plus a full-run index, in the audit-first layout (result, evidence, figures, findings, next actions). Good for screenshots. |
| `demo_server.py` | The same run, live: a loopback stdlib HTTP server that advances the ACTUAL service one step per click and re-renders the same output view. Nothing is pre-recorded. |
| `walkthrough.py` | The presenter-paced walkthrough. It starts the server, narrates each step on the terminal (never on the page), waits for you, performs the step, then ASSERTS the service really reached the state the narration claimed. `--auto --headless` turns it into the unattended self-test. |
| `portability_demo.py` | The executable portability claim: named checks with a pass or fail each, covering the port map, adapter conformance, the offline family answering, the exit family refusing, tamper evidence, anchored truncation detection and the open-format round trip. Exits non-zero if any check fails, and prints what it does NOT prove. |
| `check_docs_links.py` | Offline documentation checks: every relative markdown link resolves, every code fence closes, and no em-dash or en-dash reaches shipped prose. |
| `drop_ui.py` | Removes `ui/` together with its npm dependabot ecosystem, in one consistent step (`make drop-ui`). It used to remove a `ui-gate` workflow too; that workflow was retired with the rest, so there is no CI job left to delete. Most catalog repos have no user-facing surface; removing the UI must be cheaper than hand-building one. |
| `lock.py` | Compiles both lockfiles and puts the header back, because `uv pip compile` REPLACES the output file: it writes its own two-line provenance comment and destroys the `tag = commit` map the pin tests check against. `make lock` runs this rather than uv directly. |
| `rename_fork.py` | The one-pass rebrand for a fork: the package name (which is also the console script), the `CONTRACT_` env prefix including the bare token `infra/terraform/render.tf.json` carries, the Terraform `name_prefix` resource stem and the distribution id. Prints a plan and writes nothing without `--yes`; skips itself, so the renamer is not left half-rewritten. See `docs/ADOPTING.md`. |

## The three ways to run the demo

```bash
make demo              # presenter-paced: starts the server, opens the page, waits for you
make demo-selftest     # unattended and headless, asserts every step, non-zero on failure
make demo-static       # writes demo.json plus out/index.html and out/step-*.html
```

At a prompt in `make demo`: **Enter** runs the step, a **number** jumps to that step, **r**
restarts the run, **q** quits. The narration lives on your terminal so the audience sees only the
clean output view.

You can also run the server alone and drive it in any browser:

```bash
PYTHONPATH=src python scripts/demo_server.py --port 8099   # then open http://127.0.0.1:8099
```

It binds loopback only and is not configurable. The demo runs the unauthenticated `local`
profile, so a non-loopback bind would put a no-auth surface on the network; the service's own API
refuses that posture at startup, and the demo server must not be the soft way around it.

## Why there is no browser automation here

A walkthrough that needed Playwright or a headless Chromium could not be installed offline, could
not run in a no-egress CI job, and would break the first time the engine moved. This one drives
the demo server over plain HTTP with the standard library, which is why the same script is both
the presenter tool and the self-test. If a repo later grows a `ui/` walkthrough that genuinely
needs a browser, add it as a SEPARATE script with its own optional dependency, and leave this one
able to run everywhere.

## The rules these scripts follow

- **Synthetic, obviously fictional data only.** Fictional parties, `.example` domains, RFC 5737
  and RFC 3849 literals. The one national id in the fixtures exists solely so a redaction check
  has an independent literal to look for.
- **Nothing is faked.** No stub of the engine and no pre-baked output. If the demo shows a
  decision, the shipped code produced it in that process. The one stub is the offline model
  adapter, which decides nothing and carries the word stub in its own model id.
- **Every claim is bounded.** Each script says what it does not prove. An unbounded claim is the
  one an auditor disproves for you.
- **Bad news is shown.** The tamper step exists to display a failure, and the walkthrough exits
  non-zero when a step stops being true rather than narrating past it.
