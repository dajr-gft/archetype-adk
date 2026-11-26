"""The tools the agent may call: thin adapters between the model and the domain.

A tool decides nothing. It takes what the user said from the model, takes who the user is
from the session, calls one use case of ``domain.service`` and returns its result in the
envelope below. The rules live in ``domain``.

Envelope (every tool):
    {"status": "success", "acting_user": ..., <result fields>}
    {"status": "error", "error_code": ..., "error_message": ..., "rule_id": ...}

Guards that the model cannot talk its way around:
- The acting user is ``tool_context.user_id``. No tool has a parameter for it.
- A write is submitted from the draft kept in the session, never from arguments of the
  model, and not in the turn that prepared it: the user answers in between.
- A request is decided only after its detail was shown in an earlier turn of the session.

Tools are coroutines and run the use case in a worker thread: a use case may wait for the
system of record, and a synchronous tool would hold the event loop that serves every
other conversation of the process.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from google.adk.tools.tool_context import ToolContext

from .domain import service
from .domain.rules import DomainError

# Session state written by the tools. Declared here so the conformance gate knows them.
DRAFT = "cancellation_draft"
REVIEWED = "reviewed_request"


def _error(code: str, message: str, rule_id: str | None = None) -> dict[str, Any]:
    return {"status": "error", "error_code": code, "error_message": message, "rule_id": rule_id}


async def _run(tool_context: ToolContext, use_case: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        result = await asyncio.to_thread(use_case)
    except DomainError as error:
        return _error(error.code, error.message, error.rule_id)
    return {"status": "success", "acting_user": tool_context.user_id.upper(), **result}


def _shown_in_an_earlier_turn(
    kept: dict[str, Any] | None, tool_context: ToolContext
) -> dict[str, Any] | None:
    """The refusal when the user has not answered yet to what the session keeps."""
    if kept and kept["invocation_id"] == tool_context.invocation_id:
        return _error(
            "NOT_CONFIRMED",
            "The user has not answered yet. Show what was prepared and wait for the answer.",
        )
    return None


async def find_order(query: str, tool_context: ToolContext) -> dict[str, Any]:
    """Finds orders by order id or by a part of the customer name.

    Args:
        query: An order id (for example "101") or a part of the customer name.

    Returns:
        The matching orders: order_id, customer, amount_cents, status and
        has_pending_request.
    """
    return await _run(tool_context, lambda: service.find_orders(query))


async def prepare_order_cancellation(
    order_id: str, reason: str, tool_context: ToolContext
) -> dict[str, Any]:
    """Checks a cancellation and keeps it as a draft. Writes nothing.

    Call it when the user asks to cancel an order, then show the user the order, the
    reason and whether a second person will have to approve, and ask for confirmation.

    Args:
        order_id: The id of the order to cancel.
        reason: Why the order is cancelled, in the user's words.

    Returns:
        The draft: order_id, customer, amount_cents, status_before, reason and
        needs_approval.
    """
    tool_context.state[DRAFT] = None
    result = await _run(tool_context, lambda: service.preview_cancellation(order_id, reason))
    if result["status"] == "success":
        tool_context.state[DRAFT] = {
            "order_id": result["order_id"],
            "reason": result["reason"],
            "invocation_id": tool_context.invocation_id,
        }
    return result


async def submit_order_cancellation(tool_context: ToolContext) -> dict[str, Any]:
    """Submits the cancellation that was prepared and that the user confirmed.

    Call it only after the user confirmed the draft shown by prepare_order_cancellation,
    in a later message of the user.

    Returns:
        applied true and the cancelled order, or applied false and the request that a
        second person has to approve.
    """
    draft = tool_context.state.get(DRAFT)
    if not draft:
        return _error("NO_DRAFT", "There is no cancellation prepared. Prepare it first.")
    refused = _shown_in_an_earlier_turn(draft, tool_context)
    if refused:
        return refused
    result = await _run(
        tool_context,
        lambda: service.cancel_order(draft["order_id"], draft["reason"], tool_context.user_id),
    )
    if result["status"] == "success":
        tool_context.state[DRAFT] = None
    return result


async def list_cancellation_requests(status: str, tool_context: ToolContext) -> dict[str, Any]:
    """Lists cancellation requests, newest first.

    Args:
        status: PENDING, APPROVED, REJECTED or ALL.

    Returns:
        The requests. you_can_decide is true for a pending request the acting user did
        not create.
    """
    return await _run(tool_context, lambda: service.list_requests(status, tool_context.user_id))


async def review_cancellation_request(request_id: int, tool_context: ToolContext) -> dict[str, Any]:
    """Shows one cancellation request in full. Required before approving or rejecting it.

    Args:
        request_id: The number of the request.

    Returns:
        The request: order, reason, who requested it and when, its status and
        you_can_decide.
    """
    tool_context.state[REVIEWED] = None
    result = await _run(tool_context, lambda: service.get_request(request_id, tool_context.user_id))
    if result["status"] == "success":
        tool_context.state[REVIEWED] = {
            "request_id": result["request_id"],
            "invocation_id": tool_context.invocation_id,
        }
    return result


def _decidable(request_id: int, tool_context: ToolContext) -> dict[str, Any] | None:
    """The refusal when the request was not shown to the user in an earlier turn."""
    reviewed = tool_context.state.get(REVIEWED)
    if not reviewed or reviewed["request_id"] != request_id:
        return _error(
            "NOT_REVIEWED",
            "Show the request to the user with review_cancellation_request and get the "
            "decision before deciding it.",
        )
    return _shown_in_an_earlier_turn(reviewed, tool_context)


async def approve_cancellation_request(
    request_id: int, tool_context: ToolContext
) -> dict[str, Any]:
    """Approves a pending cancellation request: the order is cancelled.

    Call it only after the user saw the request and, in a later message, said to
    approve it.

    Args:
        request_id: The number of the request that was reviewed.

    Returns:
        The approved request.
    """
    refused = _decidable(request_id, tool_context)
    if refused:
        return refused
    result = await _run(
        tool_context, lambda: service.approve_request(request_id, tool_context.user_id)
    )
    tool_context.state[REVIEWED] = None
    return result


async def reject_cancellation_request(
    request_id: int, reason: str, tool_context: ToolContext
) -> dict[str, Any]:
    """Rejects a pending cancellation request: the order is not changed.

    Call it only after the user saw the request and, in a later message, said to reject
    it, with the reason.

    Args:
        request_id: The number of the request that was reviewed.
        reason: Why the request is rejected, in the user's words.

    Returns:
        The rejected request.
    """
    refused = _decidable(request_id, tool_context)
    if refused:
        return refused
    result = await _run(
        tool_context, lambda: service.reject_request(request_id, reason, tool_context.user_id)
    )
    if result["status"] == "success":
        tool_context.state[REVIEWED] = None
    return result
