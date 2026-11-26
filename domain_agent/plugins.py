"""Cross-cutting behaviour of the app, as ADK plugins (registered once on ``App``).

A plugin sees every tool call of every agent of the app, so an agent added later cannot
forget the audit trail. Business validation stays in the domain: a plugin never changes
what a tool decided.
"""

from __future__ import annotations

import logging
from typing import Any

from google.adk.plugins.base_plugin import BasePlugin
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext

logger = logging.getLogger("domain_agent.audit")


class AuditPlugin(BasePlugin):
    """One audit record per tool call, and a structured answer when a tool breaks.

    The record carries who acted, the tool, the argument NAMES and the outcome (status,
    error code, rule id). Argument values and results are not logged: the audit trail
    must not become a copy of the business data.
    """

    def __init__(self) -> None:
        super().__init__(name="audit")

    async def after_tool_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
        result: dict[str, Any],
    ) -> dict[str, Any] | None:
        outcome = result if isinstance(result, dict) else {}
        logger.info(
            "tool_call user=%s session=%s invocation=%s agent=%s tool=%s args=%s "
            "status=%s error_code=%s rule_id=%s",
            tool_context.user_id,
            tool_context.session.id,
            tool_context.invocation_id,
            tool_context.agent_name,
            tool.name,
            sorted(tool_args),
            outcome.get("status", "unknown"),
            outcome.get("error_code"),
            outcome.get("rule_id"),
        )
        return None  # the tool's own result is used unchanged

    async def on_tool_error_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
        error: Exception,
    ) -> dict[str, Any] | None:
        """A tool that raised (a defect, or storage that is down) answers like a tool."""
        logger.error(
            "tool_failed user=%s invocation=%s tool=%s error=%s",
            tool_context.user_id,
            tool_context.invocation_id,
            tool.name,
            type(error).__name__,
        )
        return {
            "status": "error",
            "error_code": "UNAVAILABLE",
            "error_message": "The operation could not be completed. Nothing was changed.",
            "rule_id": None,
        }
