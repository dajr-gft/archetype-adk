"""Use cases of the domain: one function per operation of the legacy system.

Each use case is one transaction, takes the acting user as an argument (the caller gets it
from the session, never from the conversation) and either returns plain data or raises
``DomainError``. Nothing here knows about ADK or a model.

A use case that writes takes a ``Confirmation`` and follows one shape:

    with store.transaction():
        <validations and business rules, in the order of the legacy source>
        authorize(store, confirmation, <what the preview would show now>)
        <the changes>
        record(store, confirmation, operation=..., target=..., user=...)

What a use case returns is what the user is shown: text, integers, booleans, lists and
dictionaries of them. Amounts are formatted here, by code.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .base import Confirmation, DomainError, authorize, record, utc_now
from .rules import (
    CANCELLABLE_STATUSES,
    SEARCH_LIMIT,
    format_amount,
    needs_approval,
    normalize_order_id,
    normalize_reason,
    normalize_request_id,
    normalize_request_status,
    normalize_user,
    same_user,
)
from .store import CancellationRequest, Order, OrderStore, get_store


def _order_view(store: OrderStore, order: Order) -> dict[str, Any]:
    return {
        "order_id": order.order_id,
        "customer": order.customer,
        "amount": format_amount(order.amount_cents),
        "status": order.status,
        "has_pending_request": _has_pending(store, order.order_id),
    }


def _has_pending(store: OrderStore, order_id: str) -> bool:
    return any(request.order_id == order_id for request in store.list_requests("PENDING"))


def find_orders(query: object) -> dict[str, Any]:
    """BR-007: an order by its id, or the orders of the customers whose name contains the text."""
    text = query.strip() if isinstance(query, str) else ""
    if not text:
        raise DomainError("QUERY_MISSING", "Give an order id or a part of the customer name.")
    store = get_store()
    with store.transaction():
        if text.isascii() and text.isdigit():
            order = store.get_order(normalize_order_id(text))
            found = [order] if order else []
        else:
            found = store.find_orders(text)
        return {
            "orders": [_order_view(store, order) for order in found[:SEARCH_LIMIT]],
            "total_matches": len(found),
            "more": len(found) > SEARCH_LIMIT,
        }


def _cancellation(
    store: OrderStore, order_id: object, reason: object
) -> tuple[Order, dict[str, Any]]:
    """The order and what a cancellation of it shows, or the refusal.

    Validations and rules in the order of the legacy source: VAL-001, VAL-002, BR-001,
    BR-002.
    """
    stored_id = normalize_order_id(order_id)
    order = store.get_order(stored_id)
    if order is None:
        raise DomainError("ORDER_NOT_FOUND", f"There is no order {stored_id}.")
    text = normalize_reason(reason)
    if order.status not in CANCELLABLE_STATUSES:
        raise DomainError(
            "NOT_CANCELLABLE",
            f"Order {order.order_id} is {order.status}: it cannot be cancelled.",
            "BR-001",
        )
    if _has_pending(store, order.order_id):
        raise DomainError(
            "ALREADY_PENDING",
            f"Order {order.order_id} already has a cancellation waiting for approval.",
            "BR-002",
        )
    return order, {
        "order_id": order.order_id,
        "customer": order.customer,
        "amount": format_amount(order.amount_cents),
        "status": order.status,
        "reason": text,
        "needs_approval": needs_approval(order.amount_cents),
    }


def preview_cancellation(order_id: object, reason: object) -> dict[str, Any]:
    """What a cancellation would do, without doing it."""
    store = get_store()
    with store.transaction():
        return _cancellation(store, order_id, reason)[1]


def cancel_order(
    order_id: object, reason: object, user: object, confirmation: Confirmation
) -> dict[str, Any]:
    """Cancels the order, or creates the request that a second person decides (BR-003)."""
    requester = normalize_user(user)
    store = get_store()
    with store.transaction():
        order, shown = _cancellation(store, order_id, reason)
        authorize(store, confirmation, shown)
        if shown["needs_approval"]:
            request = store.add_request(
                CancellationRequest(
                    0,
                    order.order_id,
                    order.status,
                    shown["reason"],
                    "PENDING",
                    requester,
                    utc_now(),
                )
            )
            outcome: dict[str, Any] = {"applied": False, "request_id": request.request_id}
        else:
            store.save_order(replace(order, status="CANCELLED"))
            outcome = {"applied": True}
        record(store, confirmation, operation="cancel_order", target=order.order_id, user=requester)
        return {**outcome, "order": _order_view(store, _order(store, order.order_id))}


def _order(store: OrderStore, order_id: str) -> Order:
    order = store.get_order(order_id)
    if order is None:
        raise DomainError("ORDER_NOT_FOUND", f"There is no order {order_id}.")
    return order


def _request_view(store: OrderStore, request: CancellationRequest, reader: str) -> dict[str, Any]:
    """A request with the order as it is now: what a person who decides is shown."""
    order = _order(store, request.order_id)
    pending = request.status == "PENDING"
    return {
        "request_id": request.request_id,
        "order_id": order.order_id,
        "customer": order.customer,
        "amount": format_amount(order.amount_cents),
        "order_status": order.status,
        "order_status_when_requested": request.status_before,
        "reason": request.reason,
        "status": request.status,
        "requested_by": request.requested_by,
        "requested_at": request.requested_at,
        "decided_by": request.decided_by,
        "decided_at": request.decided_at,
        "reject_reason": request.reject_reason,
        "you_can_decide": pending and not same_user(request.requested_by, reader),
    }


def list_requests(status: object, user: object) -> dict[str, Any]:
    """BR-008: cancellation requests of one status or of all, newest first."""
    reader = normalize_user(user)
    wanted = normalize_request_status(status)
    store = get_store()
    with store.transaction():
        requests = store.list_requests(wanted)
        return {"requests": [_request_view(store, request, reader) for request in requests]}


def _request(store: OrderStore, request_id: object) -> CancellationRequest:
    number = normalize_request_id(request_id)
    request = store.get_request(number)
    if request is None:
        raise DomainError("REQUEST_NOT_FOUND", f"There is no request {number}.")
    return request


def review_request(request_id: object, user: object) -> dict[str, Any]:
    """One request in full, as the person who may decide it is shown it."""
    reader = normalize_user(user)
    store = get_store()
    with store.transaction():
        return _request_view(store, _request(store, request_id), reader)


def _decidable(store: OrderStore, request_id: object, decider: str) -> CancellationRequest:
    request = _request(store, request_id)
    if request.status != "PENDING":
        raise DomainError(
            "NOT_PENDING", f"Request {request.request_id} was already {request.status.lower()}."
        )
    if same_user(request.requested_by, decider):
        raise DomainError(
            "FOUR_EYES",
            "A request is decided by a second person: you created this one.",
            "BR-004",
        )
    return request


def approve_request(request_id: object, user: object, confirmation: Confirmation) -> dict[str, Any]:
    """Applies a pending cancellation (BR-004, BR-006): order and request in one transaction."""
    approver = normalize_user(user)
    store = get_store()
    with store.transaction():
        request = _decidable(store, request_id, approver)
        order = _order(store, request.order_id)
        if order.status != request.status_before:
            raise DomainError(
                "CHANGED_SINCE_REQUESTED",
                f"Order {order.order_id} is now {order.status}, not {request.status_before} as "
                "when the cancellation was requested. It can only be rejected.",
                "BR-006",
            )
        authorize(store, confirmation, _request_view(store, request, approver))
        store.save_order(replace(order, status="CANCELLED"))
        decided = replace(request, status="APPROVED", decided_by=approver, decided_at=utc_now())
        store.save_request(decided)
        record(
            store,
            confirmation,
            operation="approve_cancellation",
            target=str(request.request_id),
            user=approver,
        )
        return _request_view(store, decided, approver)


def reject_request(
    request_id: object, reason: object, user: object, confirmation: Confirmation
) -> dict[str, Any]:
    """Rejects a pending cancellation (BR-004, BR-005); the order is not changed."""
    approver = normalize_user(user)
    store = get_store()
    with store.transaction():
        request = _decidable(store, request_id, approver)
        try:
            text = normalize_reason(reason)
        except DomainError as error:
            raise DomainError("REASON_MISSING", "A rejection needs a reason.", "BR-005") from error
        authorize(store, confirmation, _request_view(store, request, approver))
        decided = replace(
            request,
            status="REJECTED",
            decided_by=approver,
            decided_at=utc_now(),
            reject_reason=text,
        )
        store.save_request(decided)
        record(
            store,
            confirmation,
            operation="reject_cancellation",
            target=str(request.request_id),
            user=approver,
        )
        return _request_view(store, decided, approver)
