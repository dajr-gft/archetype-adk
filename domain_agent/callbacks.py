"""Cross-cutting callbacks for the domain agent.

These are framework-level guards that apply to *every* tool call, independent of
the domain. Use them for cross-cutting concerns — here, an audit trail — and keep
business validation and numeric coercion inside the tools themselves (the tool is
where the rule, the types, and the verbatim string codes are known; centralizing
coercion here would risk corrupting domain string codes such as CNAE ``"24"``).

Wired in ``agent.py`` via ``after_tool_callback=audit_tool_call``.
"""

from __future__ import annotations

import logging
from typing import Any

from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext

logger = logging.getLogger("domain_agent.audit")


def audit_tool_call(
    tool: BaseTool,
    args: dict[str, Any],
    tool_context: ToolContext,
    tool_response: dict[str, Any],
) -> dict[str, Any] | None:
    """Emit a structured audit record for each tool invocation.

    For an auditable domain (credit decisioning, approvals) the sequence of tool
    calls and their outcomes *is* the decision trail. We log the argument **keys**
    and the response ``status`` only — never the full payload — so the audit log
    never becomes a sink for sensitive values.

    Returns ``None`` so ADK uses the tool's original response unchanged.
    """
    status = tool_response.get("status") if isinstance(tool_response, dict) else "unknown"
    logger.info(
        "tool_call agent=%s invocation=%s tool=%s arg_keys=%s status=%s",
        getattr(tool_context, "agent_name", "?"),
        getattr(tool_context, "invocation_id", "?"),
        tool.name,
        sorted(args.keys()),
        status,
    )
    return None
