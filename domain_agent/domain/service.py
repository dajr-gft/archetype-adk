"""Use cases of the domain: one function per operation of the legacy system.

Each function is one transaction, takes the acting user as an argument (the caller gets
it from the session, never from the conversation) and either returns plain data or
raises ``DomainError``. Nothing here knows about ADK or a model.
"""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, datetime
from typing import Any

from .rules import (
    CANCELLABLE_STATUSES,
    DomainError,
    needs_approval,
    normalize_order_id,
    normalize_reason,
)
from .store import CancellationRequest, Order, get_store

SEARCH_LIMIT = 10
REQUEST_STATUSES = ("PENDING", "APPROVED", "REJECTED")


def _user(raw: str) -> str:
    user = (raw or "").strip().upper()
    if not user:
        raise DomainError("USER_UNKNOWN", "The signed-in user is unknown.")
    return user


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def _order_view(order: Order, pending: bool) -> dict[str, Any]:
    return {**asdict(order), "has_pending_request": pending}


def _request_view(request: CancellationRequest, user: str) -> dict[str, Any]:
    view = asdict(request)
    view["request_status"] = view.pop("status")  # "status" is the key of the tool envelope
    view["you_can_decide"] = request.status == "PENDING" and request.requested_by != user
    return view


def _has_pending(order_id: str) -> bool:
    return any(r.order_id == order_id for r in get_store().list_requests("PENDING"))


def _cancellable(order_id: str, reason: str) -> tuple[Order, str]:
    """The order and the stored reason, or the refusal (VAL-001, VAL-002, BR-001, BR-002)."""
    store = get_store()
    order = store.get_order(normalize_order_id(order_id))
    if order is None:
        raise DomainError("ORDER_NOT_FOUND", f"There is no order {order_id.strip()}.")
    text = normalize_reason(reason)
    if order.status not in CANCELLABLE_STATUSES:
        raise DomainError(
            "NOT_CANCELLABLE",
            f"Order {order.order_id} is {order.status}; only an OPEN or ON_HOLD order "
            "can be cancelled.",
            "BR-001",
        )
    if _has_pending(order.order_id):
        raise DomainError(
            "ALREADY_PENDING",
            f"Order {order.order_id} already has a cancellation waiting for approval.",
            "BR-002",
        )
    return order, text


def find_orders(query: str) -> dict[str, Any]:
    """Orders by id or by a part of the customer name."""
    text = (query or "").strip()
    if not text:
        raise DomainError("QUERY_MISSING", "Give an order id or a part of the customer name.")
    store = get_store()
    with store.transaction():
        if text.isdigit():
            order = store.get_order(normalize_order_id(text))
            orders = [order] if order else []
        else:
            orders = store.find_orders(text, SEARCH_LIMIT)
        return {"orders": [_order_view(o, _has_pending(o.order_id)) for o in orders]}


def preview_cancellation(order_id: str, reason: str) -> dict[str, Any]:
    """What a cancellation would do, without doing it."""
    with get_store().transaction():
        order, text = _cancellable(order_id, reason)
        return {
            "order_id": order.order_id,
            "customer": order.customer,
            "amount_cents": order.amount_cents,
            "status_before": order.status,
            "reason": text,
            "needs_approval": needs_approval(order.amount_cents),
        }


def cancel_order(order_id: str, reason: str, user: str) -> dict[str, Any]:
    """Cancels the order, or creates the request that a second person decides (BR-003)."""
    requester = _user(user)
    store = get_store()
    with store.transaction():
        order, text = _cancellable(order_id, reason)
        if not needs_approval(order.amount_cents):
            store.save_order(replace(order, status="CANCELLED"))
            return {"applied": True, "order": _order_view(get_order(order.order_id), False)}
        request = store.add_request(
            CancellationRequest(0, order.order_id, order.status, text, "PENDING", requester, _now())
        )
        return {"applied": False, "request": _request_view(request, requester)}


def get_order(order_id: str) -> Order:
    order = get_store().get_order(order_id)
    if order is None:  # unreachable for an id that was just read; kept for the type
        raise DomainError("ORDER_NOT_FOUND", f"There is no order {order_id}.")
    return order


def list_requests(status: str, user: str) -> dict[str, Any]:
    """Cancellation requests, newest first. ``status``: PENDING, APPROVED, REJECTED or ALL."""
    reader = _user(user)
    wanted = (status or "PENDING").strip().upper()
    if wanted != "ALL" and wanted not in REQUEST_STATUSES:
        raise DomainError("STATUS_INVALID", "Status is PENDING, APPROVED, REJECTED or ALL.")
    store = get_store()
    with store.transaction():
        requests = store.list_requests(None if wanted == "ALL" else wanted)
        return {"requests": [_request_view(r, reader) for r in requests]}


def get_request(request_id: int, user: str) -> dict[str, Any]:
    reader = _user(user)
    with get_store().transaction():
        return _request_view(_request(request_id), reader)


def _request(request_id: int) -> CancellationRequest:
    request = get_store().get_request(request_id)
    if request is None:
        raise DomainError("REQUEST_NOT_FOUND", f"There is no request {request_id}.")
    return request


def _decidable(request_id: int, decider: str) -> CancellationRequest:
    request = _request(request_id)
    if request.status != "PENDING":
        raise DomainError(
            "NOT_PENDING", f"Request {request_id} was already {request.status.lower()}."
        )
    if request.requested_by == decider:
        raise DomainError(
            "FOUR_EYES",
            "A request is decided by a second person: you created this one.",
            "BR-004",
        )
    return request


def approve_request(request_id: int, user: str) -> dict[str, Any]:
    """Applies a pending cancellation (BR-004, BR-006): order and request in one transaction."""
    approver = _user(user)
    store = get_store()
    with store.transaction():
        request = _decidable(request_id, approver)
        order = get_order(request.order_id)
        if order.status != request.status_before:
            raise DomainError(
                "CHANGED_SINCE",
                f"Order {order.order_id} is now {order.status}, not {request.status_before} "
                "as when the cancellation was requested. Reject this request.",
                "BR-006",
            )
        store.save_order(replace(order, status="CANCELLED"))
        decided = replace(request, status="APPROVED", decided_by=approver, decided_at=_now())
        store.save_request(decided)
        return _request_view(decided, approver)


def reject_request(request_id: int, reason: str, user: str) -> dict[str, Any]:
    """Rejects a pending cancellation (BR-004, BR-005); the order is not changed."""
    approver = _user(user)
    store = get_store()
    with store.transaction():
        request = _decidable(request_id, approver)
        try:
            text = normalize_reason(reason)
        except DomainError as error:
            raise DomainError("REASON_MISSING", "A rejection needs a reason.", "BR-005") from error
        decided = replace(
            request,
            status="REJECTED",
            decided_by=approver,
            decided_at=_now(),
            reject_reason=text,
        )
        store.save_request(decided)
        return _request_view(decided, approver)
