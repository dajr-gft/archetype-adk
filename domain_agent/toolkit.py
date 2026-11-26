"""Archetype-owned. How a tool reaches a use case.

A tool of ``tools.py`` only says which use case answers it. Everything that has to hold
whatever the model does is here, written and tested once:

- **The acting user** is the user of the session. The toolkit passes it to the use case;
  a tool never reads it and never takes it as a parameter.
- **The envelope** of every tool result:
      {"status": "success", "acting_user": ..., "result": {...}}
      {"status": "error", "error_code": ..., "error_message": ..., "rule_id": ...}
- **A write is confirmed.** ``prepare`` runs the preview of a write and keeps what was
  shown. ``submit`` runs the write only when the user sent exactly one message since:
  not in the turn of the preview (nobody answered yet), and not after the user moved on.
  Any other tool call drops what was kept. The write receives a ``Confirmation``, so the
  use case refuses when what was shown has changed, and applies it once.
- **A decision is reviewed.** ``review`` shows an item and keeps which one; ``decide``
  follows the same rule as ``submit``.
- **The event loop is not held.** A use case may wait for the system of record: it runs
  in a worker thread, with a time limit.

What the code cannot know is whether the user's message meant yes. The model reads that.
The toolkit makes sure there was a message, right after the user was shown exactly what
is about to be written.

Do not change this file in a generated agent.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import Callable
from typing import Any

from google.adk.tools.tool_context import ToolContext

from .domain.base import Confirmation, DomainError, fingerprint

Result = dict[str, Any]

# The one session state key of the toolkit: what waits for the user's answer.
PENDING = "pending_confirmation"

# How long a use case may take before the tool answers that the outcome is unknown.
USE_CASE_TIMEOUT_SECONDS = float(os.environ.get("USE_CASE_TIMEOUT_SECONDS", "30"))


def _refusal(code: str, message: str, rule_id: str | None = None) -> Result:
    return {"status": "error", "error_code": code, "error_message": message, "rule_id": rule_id}


def _user_messages(tool_context: ToolContext) -> list[str]:
    """The ids of the messages the user wrote in this session, oldest first."""
    ids: list[str] = []
    for event in tool_context.session.events:
        parts = (event.content.parts if event.content else None) or []
        if event.author == "user" and any(part.text for part in parts):
            ids.append(event.id)
    return ids


async def _call(tool_context: ToolContext, use_case: Callable[[str], Result]) -> Result:
    user = tool_context.user_id
    try:
        result = await asyncio.wait_for(asyncio.to_thread(use_case, user), USE_CASE_TIMEOUT_SECONDS)
    except DomainError as error:
        return _refusal(error.code, error.message, error.rule_id)
    except TimeoutError:
        return _refusal(
            "OUTCOME_UNKNOWN",
            "There was no answer in time, so the outcome is unknown. Look at the current "
            "state before trying again.",
        )
    json.dumps(result)  # TypeError: the use case returned a value JSON cannot carry
    return {"status": "success", "acting_user": user, "result": result}


def _keep(tool_context: ToolContext, kind: str, name: str, item: str, shown: Result) -> None:
    messages = _user_messages(tool_context)
    fingerprint(shown)  # TypeError here, not at the confirmation, for a value JSON cannot carry
    tool_context.state[PENDING] = {
        "kind": kind,
        "name": name,
        "item": item,
        "shown": shown,
        "key": uuid.uuid4().hex,
        "user": tool_context.user_id,
        "answered_after": messages[-1] if messages else "",
    }


def _take(tool_context: ToolContext, kind: str, name: str, item: str) -> dict[str, Any]:
    """What waits for this confirmation, if the user answered it; the refusal otherwise."""
    pending = tool_context.state.get(PENDING)
    tool_context.state[PENDING] = None
    expected = (kind, name, item, tool_context.user_id)
    if not pending or expected != tuple(
        str(pending.get(k)) for k in ("kind", "name", "item", "user")
    ):
        if kind == "write":
            raise DomainError(
                "NOTHING_PREPARED",
                "Nothing is waiting for this confirmation. Prepare it and show it to the "
                "user first.",
            )
        raise DomainError(
            "NOT_REVIEWED",
            "Show this to the user with its review tool and get the decision before deciding it.",
        )
    messages = _user_messages(tool_context)
    anchor = pending.get("answered_after")
    newer = len(messages) - 1 - messages.index(anchor) if anchor in messages else -1
    if newer == 0:
        tool_context.state[PENDING] = pending  # still waiting: the user answers next
        raise DomainError(
            "NOT_CONFIRMED",
            "The user has not answered yet. Show what was prepared and wait for the answer.",
        )
    if newer != 1:
        raise DomainError(
            "CONFIRMATION_EXPIRED",
            "The user moved on after this was shown. Prepare it again and show it.",
        )
    return dict(pending)


async def read(tool_context: ToolContext, use_case: Callable[[str], Result]) -> Result:
    """Runs a use case that only reads. ``use_case`` receives the acting user."""
    tool_context.state[PENDING] = None  # the user moved on from what was waiting
    return await _call(tool_context, use_case)


async def prepare(
    tool_context: ToolContext, operation: str, preview: Callable[[str], Result]
) -> Result:
    """Runs the preview of a write and keeps what it returned for ``submit``.

    ``preview`` receives the acting user and writes nothing. What it returns is shown to
    the user and is what the write will be checked against.
    """
    tool_context.state[PENDING] = None
    result = await _call(tool_context, preview)
    if result["status"] == "success":
        _keep(tool_context, "write", operation, "", result["result"])
    return result


async def submit(
    tool_context: ToolContext,
    operation: str,
    write: Callable[[str, Result, Confirmation], Result],
) -> Result:
    """Runs the write that ``prepare`` previewed, once the user answered.

    ``write`` receives the acting user, what the preview returned and the confirmation to
    pass to the use case. Nothing the model sends reaches it.
    """
    try:
        pending = _take(tool_context, "write", operation, "")
    except DomainError as error:
        return _refusal(error.code, error.message)
    shown: Result = pending["shown"]
    confirmation = Confirmation(pending["key"], fingerprint(shown))
    return await _call(tool_context, lambda user: write(user, shown, confirmation))


async def review(
    tool_context: ToolContext, subject: str, item: object, show: Callable[[str], Result]
) -> Result:
    """Shows one item the user may decide on, and keeps which one for ``decide``."""
    tool_context.state[PENDING] = None
    result = await _call(tool_context, show)
    if result["status"] == "success":
        _keep(tool_context, "decision", subject, str(item), result["result"])
    return result


async def decide(
    tool_context: ToolContext,
    subject: str,
    item: object,
    decision: Callable[[str, Confirmation], Result],
) -> Result:
    """Runs a decision on the item that ``review`` showed, once the user answered.

    ``decision`` receives the acting user and the confirmation to pass to the use case.
    """
    try:
        pending = _take(tool_context, "decision", subject, str(item))
    except DomainError as error:
        return _refusal(error.code, error.message)
    confirmation = Confirmation(pending["key"], fingerprint(pending["shown"]))
    return await _call(tool_context, lambda user: decision(user, confirmation))
