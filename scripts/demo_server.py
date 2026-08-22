"""A live, click-through demo server: one real step per click, rendered audit-first (stdlib).

Holds a real :class:`demo.DemoRun` and advances the ACTUAL services one step per press of
``Next``, re-rendering the same output view the static renderer produces. No framework, no
bundler, no cloud, no network egress, and nothing pre-recorded.

    make demo-server         # then open http://127.0.0.1:8099

It binds loopback only, on purpose. The demo runs the unauthenticated local profile, so a
non-loopback bind would put a no-auth surface on the network; the service's own API refuses that
posture at startup and this server holds the same line rather than being the soft way around it.

``walkthrough.py`` drives this server over plain HTTP, which is what makes the walkthrough
headless-capable with no browser engine installed.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import demo
import render_ui

#: Loopback only. Not configurable: see the module docstring.
HOST = "127.0.0.1"
DEFAULT_PORT = 8099

_CONTROLS = (
    '<div class="controls">'
    '<form method="post" action="/next"><button type="submit">Next step</button></form>'
    '<form method="post" action="/restart">'
    '<button class="ghost" type="submit">Restart</button></form>'
    '<span class="sub">Every click runs the real service. Nothing here is pre-recorded.</span>'
    "</div>"
)

_FINISHED = (
    '<div class="controls">'
    '<form method="post" action="/restart">'
    '<button class="ghost" type="submit">Restart</button></form>'
    '<span class="sub">Walkthrough complete.</span>'
    "</div>"
)


class DemoState:
    """The single run the server serves, guarded so two clicks cannot interleave a step."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._run = demo.DemoRun()

    def advance(self) -> None:
        with self._lock:
            self._run.advance()

    def restart(self) -> None:
        with self._lock:
            self._run = demo.DemoRun()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self._run.state()


class Handler(BaseHTTPRequestHandler):
    """Five routes and no more: the page, the two actions, the state, and a health check."""

    server_version = "demo-server/1.0"
    state: DemoState

    def do_GET(self) -> None:  # noqa: N802 - the stdlib names the hook
        path = self.path.split("?", 1)[0]
        if path == "/healthz":
            self._json({"ok": True})
        elif path == "/state":
            self._json(self.state.snapshot())
        elif path == "/":
            snapshot = self.state.snapshot()
            controls = _FINISHED if snapshot["done"] else _CONTROLS
            body = render_ui.render_page(snapshot, controls=controls)
            self._send(HTTPStatus.OK, "text/html; charset=utf-8", body.encode("utf-8"))
        else:
            self._send(HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"not found\n")

    def do_POST(self) -> None:  # noqa: N802 - the stdlib names the hook
        path = self.path.split("?", 1)[0]
        if path == "/next":
            self.state.advance()
        elif path == "/restart":
            self.state.restart()
        else:
            self._send(HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"not found\n")
            return
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", "/")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        """Silence the per-request log: the presenter's terminal is the narration channel."""

    def _json(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self._send(HTTPStatus.OK, "application/json", body)

    def _send(self, status: HTTPStatus, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # The same header baseline the API serves. A demo page is still a served page.
        self.send_header("Content-Security-Policy", "frame-ancestors 'self'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)


def build_server(port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    """Construct the loopback server with a fresh run bound to the handler class."""
    handler = type("BoundHandler", (Handler,), {"state": DemoState()})
    return ThreadingHTTPServer((HOST, port), handler)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serve the click-through demo on loopback.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)

    server = build_server(args.port)
    url = "http://" + HOST + ":" + str(server.server_address[1])
    print(demo.SERVICE_NAME + " demo: " + url)
    print("steps: " + ", ".join(demo.STEP_KEYS))
    try:
        server.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover - interactive exit
        print("")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
