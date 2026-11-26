"""The tools the agent may call: one per thing the user can ask for.

A tool decides nothing and guards nothing. It names the use case that answers it and
hands it to the toolkit, which supplies the acting user, the envelope of the result and
the confirmation of writes (see ``toolkit.py``). So a tool:

- never reads ``tool_context`` (it only passes it on) and has no parameter for the user;
- reads with ``toolkit.read``;
- writes in two tools: ``prepare_<operation>`` (``toolkit.prepare`` with the preview use
  case) and ``submit_<operation>`` (``toolkit.submit``, no parameter but the context);
- decides on something another person asked for in two tools as well: a review tool
  (``toolkit.review``) and the decision tools (``toolkit.decide``).

The docstring is what the model reads: what the tool does, when to call it, each argument.
"""

from __future__ import annotations

from typing import Any

from google.adk.tools.tool_context import ToolContext

from . import toolkit
from .domain import service


async def find_order(query: str, tool_context: ToolContext) -> dict[str, Any]:
    """Finds orders by order id or by a part of the customer name.

    Args:
        query: An order id (for example "101") or a part of the customer name.

    Returns:
        orders (order_id, customer, amount, status, has_pending_request), total_matches,
        and more: true when there are more orders than the ones listed.
    """
    return await toolkit.read(tool_context, lambda user: service.find_orders(query))


async def prepare_order_cancellation(
    order_id: str, reason: str, tool_context: ToolContext
) -> dict[str, Any]:
    """Checks a cancellation and keeps it for confirmation. Writes nothing.

    Call it when the user asks to cancel an order. Then show the user the order, the
    reason and whether a second person will have to approve, and ask for confirmation.

    Args:
        order_id: The id of the order to cancel.
        reason: Why the order is cancelled, in the user's words.

    Returns:
        What will be done: order_id, customer, amount, status, reason and needs_approval.
    """
    return await toolkit.prepare(
        tool_context,
        "cancel_order",
        lambda user: service.preview_cancellation(order_id, reason),
    )


async def submit_order_cancellation(tool_context: ToolContext) -> dict[str, Any]:
    """Submits the cancellation that was prepared, after the user confirmed it.

    Call it only when the user's last message confirms what prepare_order_cancellation
    showed. Call no other tool before it in that turn.

    Returns:
        applied true and the cancelled order, or applied false and the request_id of the
        request that a second person has to approve.
    """
    return await toolkit.submit(
        tool_context,
        "cancel_order",
        lambda user, shown, confirmation: service.cancel_order(
            shown["order_id"], shown["reason"], user, confirmation
        ),
    )


async def list_cancellation_requests(status: str, tool_context: ToolContext) -> dict[str, Any]:
    """Lists cancellation requests, newest first.

    Args:
        status: PENDING, APPROVED, REJECTED or ALL.

    Returns:
        requests. you_can_decide is true for a pending request the acting user did not
        create.
    """
    return await toolkit.read(tool_context, lambda user: service.list_requests(status, user))


async def review_cancellation_request(request_id: int, tool_context: ToolContext) -> dict[str, Any]:
    """Shows one cancellation request in full. Required before approving or rejecting it.

    Call it when the user wants to decide a request, then show its detail and ask for
    the decision.

    Args:
        request_id: The number of the request.

    Returns:
        The request with the order as it is now, who requested it and when, its status
        and you_can_decide.
    """
    return await toolkit.review(
        tool_context,
        "cancellation_request",
        request_id,
        lambda user: service.review_request(request_id, user),
    )


async def approve_cancellation_request(
    request_id: int, tool_context: ToolContext
) -> dict[str, Any]:
    """Approves a pending cancellation request: the order is cancelled.

    Call it only when the user's last message says to approve the request that
    review_cancellation_request showed. Call no other tool before it in that turn.

    Args:
        request_id: The number of the request that was reviewed.

    Returns:
        The approved request.
    """
    return await toolkit.decide(
        tool_context,
        "cancellation_request",
        request_id,
        lambda user, confirmation: service.approve_request(request_id, user, confirmation),
    )


async def reject_cancellation_request(
    request_id: int, reason: str, tool_context: ToolContext
) -> dict[str, Any]:
    """Rejects a pending cancellation request: the order is not changed.

    Call it only when the user's last message says to reject the request that
    review_cancellation_request showed, and gives the reason. Call no other tool before
    it in that turn.

    Args:
        request_id: The number of the request that was reviewed.
        reason: Why the request is rejected, in the user's words.

    Returns:
        The rejected request.
    """
    return await toolkit.decide(
        tool_context,
        "cancellation_request",
        request_id,
        lambda user, confirmation: service.reject_request(request_id, reason, user, confirmation),
    )
