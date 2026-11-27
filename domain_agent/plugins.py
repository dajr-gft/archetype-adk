"""Archetype-owned. Cross-cutting behaviour of the app, as ADK plugins (registered on ``App``).

A plugin sees every tool call of every agent of the app, so an agent added later cannot
forget the audit trail. Business validation stays in the domain: a plugin never changes
what a tool decided.

Two records exist of what the agent did. This log says that a tool was called and how it
ended; it is written as one JSON object per line on the standard error stream, where the
platform collects it. The durable record of every write (who, what, which key) is kept by
the store, in the transaction of the write (``domain/base.py``).

Do not change this file in a generated agent.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from google.adk.plugins.base_plugin import BasePlugin
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext

logger = logging.getLogger(__name__.rsplit(".", 1)[0] + ".audit")


class _JsonLines(logging.Formatter):
    """One JSON object per record: ``severity``, ``message`` and the audit fields."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {"severity": record.levelname, "message": record.getMessage()}
        entry.update(getattr(record, "audit", {}))
        return json.dumps(entry, ensure_ascii=True, default=str)


def _configure_logger() -> None:
    """Gives the audit log an output of its own.

    Python drops INFO records unless logging was configured, and a server does not always
    configure it. The audit trail must not depend on that.
    """
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(_JsonLines())
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


class AuditPlugin(BasePlugin):
    """One audit record per tool call, and an answer when a tool breaks.

    The record carries who acted, the tool, the argument NAMES and the outcome (status,
    error code, rule id). Argument values and results are not logged: the audit trail
    must not become a copy of the business data.
    """

    def __init__(self) -> None:
        super().__init__(name="audit")
        _configure_logger()

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
            "tool_call",
            extra={
                "audit": {
                    "user": tool_context.user_id,
                    "session": tool_context.session.id,
                    "invocation": tool_context.invocation_id,
                    "agent": tool_context.agent_name,
                    "tool": tool.name,
                    "arguments": sorted(tool_args),
                    "status": outcome.get("status", "unknown"),
                    "error_code": outcome.get("error_code"),
                    "rule_id": outcome.get("rule_id"),
                }
            },
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
        """A tool that raised (a defect, storage that is down) answers like a tool.

        The tool may have written before it failed, so the answer does not say that
        nothing changed: the outcome is unknown.
        """
        logger.error(
            "tool_failed",
            extra={
                "audit": {
                    "user": tool_context.user_id,
                    "session": tool_context.session.id,
                    "invocation": tool_context.invocation_id,
                    "tool": tool.name,
                    "error": type(error).__name__,
                }
            },
        )
        return {
            "status": "error",
            "error_code": "OUTCOME_UNKNOWN",
            "error_message": "The operation failed unexpectedly, so its outcome is unknown. "
            "Look at the current state before trying again.",
            "rule_id": None,
        }
