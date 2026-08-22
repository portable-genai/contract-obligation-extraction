"""The agent surface: A2A discovery card plus the tool functions an agent runtime calls.

Scaffolded, optional and import-safe. Many catalog rows promise an agent, and a repo that
starts without the surface grows one by hand later in whatever shape that day suggested. So the
shape ships here: two plain Python callables that delegate to the domain services, and a card
that advertises exactly those callables.

Optional means the runtime is optional, not the code path. Nothing here needs ADK, an A2A
server or a cloud SDK to import, construct or test; ``build_function_tools`` is the only place
that touches a runtime and it imports it lazily. Delete this package if the vertical genuinely
has no agent, rather than leaving a half-wired one.
"""

from __future__ import annotations

from .agent_card import SKILLS, AgentCard, AgentSkill, agent_card_document, build_agent_card
from .tools import TOOL_FUNCTIONS, build_function_tools, triage_case, verify_audit_trail

__all__ = [
    "SKILLS",
    "TOOL_FUNCTIONS",
    "AgentCard",
    "AgentSkill",
    "agent_card_document",
    "build_agent_card",
    "build_function_tools",
    "triage_case",
    "verify_audit_trail",
]
