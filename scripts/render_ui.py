"""Render the demo's audit-view JSON into dependency-free static HTML (the output view).

Server-side rendering with the stdlib only: no framework, no bundler, no network. That is
deliberate. A demo surface that needs a JavaScript toolchain to show a decision cannot be run
from a checkout on a locked-down laptop, and screenshots for a deck should not require one
either.

The layout is AUDIT-FIRST, which is the catalog's house style for showing an agent's work:

1. the RESULT, with the decision and its severity band;
2. the EVIDENCE behind it, cited;
3. the FIGURES that were computed, never a prose paraphrase of them;
4. the FINDINGS, including the ones that are bad news;
5. the NEXT ACTIONS, addressed to a named role.

``demo.py`` produces those panels; this module only paints them, so the demo cannot show one
thing while the service does another.

    make demo-static      # -> demo.json plus out/index.html and out/step-<key>.html
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path
from typing import Any

#: Palette and layout. Kept in one plain string (never an f-string) so a CSS brace can never be
#: confused with a template brace by the generator that renders this repo.
CSS = """
:root {
  --ink-50: #f5f7fa;
  --ink-100: #e9eef5;
  --ink-200: #cdd7e4;
  --ink-500: #546b8b;
  --ink-700: #33445b;
  --ink-900: #1b2536;
  --accent: #2945d6;
  --ok: #0f766e;
  --ok-bg: #ecfdf5;
  --warn: #b45309;
  --warn-bg: #fffbeb;
  --bad: #b91c1c;
  --bad-bg: #fef2f2;
  --shadow: 0 1px 2px rgba(11, 16, 26, .06), 0 8px 24px rgba(11, 16, 26, .06);
}
* { box-sizing: border-box; }
body {
  margin: 0;
  padding: 28px 18px;
  background: var(--ink-50);
  color: var(--ink-900);
  font: 14px/1.55 ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif;
}
.wrap { max-width: 900px; margin: 0 auto; }
header.top { margin-bottom: 18px; }
h1 { font-size: 19px; margin: 0 0 4px; }
.sub { color: var(--ink-500); font-size: 13px; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12.5px; }
.rail { display: flex; flex-wrap: wrap; gap: 6px; margin: 14px 0 20px; }
.rail a, .rail span {
  display: inline-block;
  padding: 4px 10px;
  border-radius: 999px;
  background: var(--ink-100);
  color: var(--ink-700);
  text-decoration: none;
  font-size: 12px;
  border: 1px solid var(--ink-200);
}
.rail .now { background: var(--accent); border-color: var(--accent); color: #fff; }
.rail .todo { opacity: .45; }
section.step { margin-bottom: 26px; }
.step h2 { font-size: 15px; margin: 0 0 6px; }
.narr {
  color: var(--ink-700);
  background: #fff;
  border-left: 3px solid var(--accent);
  padding: 10px 12px;
  border-radius: 0 8px 8px 0;
  margin-bottom: 12px;
}
.panel {
  background: #fff;
  border: 1px solid var(--ink-200);
  border-radius: 10px;
  box-shadow: var(--shadow);
  padding: 12px 14px;
  margin-bottom: 10px;
}
.panel.ok { border-left: 4px solid var(--ok); }
.panel.warn { border-left: 4px solid var(--warn); }
.panel.bad { border-left: 4px solid var(--bad); }
.panel h3 { font-size: 13px; margin: 0 0 8px; text-transform: uppercase; letter-spacing: .04em; }
table { width: 100%; border-collapse: collapse; }
td { padding: 5px 0; vertical-align: top; border-top: 1px solid var(--ink-100); }
tr:first-child td { border-top: 0; }
td.k { color: var(--ink-500); width: 40%; padding-right: 12px; }
td.v { font-weight: 500; word-break: break-word; }
.tag { display: inline-block; padding: 1px 8px; border-radius: 999px; font-size: 12px; }
.tag.ok { background: var(--ok-bg); color: var(--ok); }
.tag.warn { background: var(--warn-bg); color: var(--warn); }
.tag.bad { background: var(--bad-bg); color: var(--bad); }
.note { color: var(--ink-500); font-size: 12.5px; margin: 8px 0 0; }
.controls { display: flex; gap: 10px; align-items: center; margin: 16px 0 22px; }
button {
  font: inherit;
  padding: 8px 16px;
  border-radius: 8px;
  border: 1px solid var(--accent);
  background: var(--accent);
  color: #fff;
  cursor: pointer;
}
button.ghost { background: #fff; color: var(--accent); }
button[disabled] { opacity: .4; cursor: default; }
footer.foot { color: var(--ink-500); font-size: 12px; margin-top: 26px; }
"""


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _tag(text: str, tone: str) -> str:
    if tone in ("ok", "warn", "bad"):
        return '<span class="tag ' + tone + '">' + _esc(text) + "</span>"
    return _esc(text)


def _panel_html(panel: dict[str, Any]) -> str:
    rows = "".join(
        '<tr><td class="k">'
        + _esc(row["label"])
        + '</td><td class="v">'
        + _tag(row["value"], row.get("tone", ""))
        + "</td></tr>"
        for row in panel["rows"]
    )
    tone = panel.get("tone", "")
    note = '<p class="note">' + _esc(panel["note"]) + "</p>" if panel.get("note") else ""
    return (
        '<div class="panel '
        + tone
        + '">'
        + "<h3>"
        + _esc(panel["title"])
        + "</h3><table>"
        + rows
        + "</table>"
        + note
        + "</div>"
    )


def _step_html(step: dict[str, Any], number: int) -> str:
    panels = "".join(_panel_html(panel) for panel in step["panels"])
    return (
        '<section class="step" id="'
        + _esc(step["key"])
        + '">'
        + "<h2>"
        + str(number)
        + ". "
        + _esc(step["label"])
        + "</h2>"
        + '<p class="narr">'
        + _esc(step["narration"])
        + "</p>"
        + panels
        + "</section>"
    )


def _rail_html(state: dict[str, Any], upto: int, *, linked: bool) -> str:
    cells: list[str] = []
    for index, step in enumerate(state["steps"]):
        if index > upto:
            break
        klass = "now" if index == upto else ""
        label = str(index + 1) + ". " + str(step["key"])
        if linked and index != upto:
            cells.append('<a class="" href="#' + _esc(step["key"]) + '">' + _esc(label) + "</a>")
        else:
            cells.append('<span class="' + klass + '">' + _esc(label) + "</span>")
    remaining = int(state["step_count"]) - (upto + 1)
    if remaining > 0:
        cells.append('<span class="todo">+' + str(remaining) + " to come</span>")
    return '<div class="rail">' + "".join(cells) + "</div>"


def render_page(
    state: dict[str, Any],
    *,
    upto: int | None = None,
    controls: str = "",
    linked: bool = True,
) -> str:
    """Render the run (up to and including step ``upto``) as one self-contained HTML document.

    ``controls`` is raw HTML injected under the header; the live server passes its Next and
    Restart forms there, and the static renderer passes nothing. Keeping the difference to one
    argument is what stops the served page and the screenshotted page from drifting apart.
    """
    last = len(state["steps"]) - 1 if upto is None else min(upto, len(state["steps"]) - 1)
    steps = "".join(
        _step_html(step, index + 1) for index, step in enumerate(state["steps"][: last + 1])
    )
    totals = state["totals"]
    summary = (
        "profile "
        + str(state["profile"])
        + " / region "
        + str(state["region"])
        + " / cases "
        + str(totals["cases"])
        + " / escalated "
        + str(totals["escalated"])
        + " / routed "
        + str(totals["routed"])
        + " / audit chain "
        + ("intact" if totals["chain_ok"] else "BROKEN (see the tamper step)")
    )
    title = str(state["service"]) + " (" + str(state["repository"]) + ") demo"
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        + '<meta name="viewport" content="width=device-width, initial-scale=1">'
        + "<title>"
        + _esc(title)
        + "</title><style>"
        + CSS
        + '</style></head><body><div class="wrap">'
        + '<header class="top"><h1>'
        + _esc(state["service"])
        + ' <span class="sub">'
        + _esc(state["repository"])
        + "</span></h1>"
        + '<div class="sub mono">'
        + _esc(summary)
        + "</div></header>"
        + controls
        + _rail_html(state, last, linked=linked)
        + steps
        + '<footer class="foot">Synthetic, obviously fictional data only. Rendered offline by '
        + "scripts/render_ui.py with no framework, no bundler and no network."
        + "</footer></div></body></html>"
    )


def render_all(state: dict[str, Any], out_dir: Path) -> list[Path]:
    """Write one page per step plus a full-run index. Returns the files written."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for index, step in enumerate(state["steps"]):
        path = out_dir / ("step-" + str(index + 1) + "-" + str(step["key"]) + ".html")
        path.write_text(render_page(state, upto=index, linked=False), encoding="utf-8")
        written.append(path)
    index_path = out_dir / "index.html"
    index_path.write_text(render_page(state), encoding="utf-8")
    written.append(index_path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render the demo JSON to static HTML pages.")
    parser.add_argument("state", nargs="?", default="demo.json", help="the demo JSON to render")
    parser.add_argument("out", nargs="?", default="out", help="output directory for the pages")
    args = parser.parse_args(argv)

    state = json.loads(Path(args.state).read_text(encoding="utf-8"))
    for path in render_all(state, Path(args.out)):
        print("wrote " + str(path))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
