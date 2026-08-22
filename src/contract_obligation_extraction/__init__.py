"""Contract Obligation Extraction (Rgc12).

Structured register of obligations, key clauses, dates and risk flags extracted from contracts.

A hexagonal ports-and-adapters build scaffolded from the catalog commons: a pure-stdlib domain
core, typed ports, swappable adapter profiles (local / gcp / onprem), a DI container driven by
one env var, and a green SDK-free offline gate. Identity, S2S, fail-closed defaults and the WORM
audit log come from ``hex-service-kit``; the eval scaffold from ``agent-eval-kit``; the PII pattern
pack from ``pii-kit``.
"""

from __future__ import annotations

__version__ = "0.0.1"
