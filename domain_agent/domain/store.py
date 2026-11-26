"""Storage port of the domain and its in-memory implementation.

The use cases depend on ``OrderStore`` only. The in-memory store serves local runs, unit
tests and the evaluation; a deployed agent replaces it with an implementation on the
system of record (``set_store``), because a container keeps nothing between restarts and
instances share nothing.

``transaction()`` makes a use case atomic: everything it reads and writes happens under
one lock (in a database implementation: one transaction).
"""

from __future__ import annotations

import copy
import threading
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, replace
from typing import Protocol


@dataclass(frozen=True)
class Order:
    order_id: str
    customer: str
    amount_cents: int
    status: str


@dataclass(frozen=True)
class CancellationRequest:
    request_id: int
    order_id: str
    status_before: str
    reason: str
    status: str  # PENDING | APPROVED | REJECTED
    requested_by: str
    requested_at: str
    decided_by: str | None = None
    decided_at: str | None = None
    reject_reason: str | None = None


class OrderStore(Protocol):
    """What the use cases need from storage."""

    def transaction(self) -> AbstractContextManager[None]: ...

    def get_order(self, order_id: str) -> Order | None: ...

    def find_orders(self, customer_part: str, limit: int) -> list[Order]: ...

    def save_order(self, order: Order) -> None: ...

    def add_request(self, request: CancellationRequest) -> CancellationRequest: ...

    def get_request(self, request_id: int) -> CancellationRequest | None: ...

    def list_requests(self, status: str | None) -> list[CancellationRequest]: ...

    def save_request(self, request: CancellationRequest) -> None: ...


# Invented data of the illustrative domain.
SEED_ORDERS: tuple[Order, ...] = (
    Order("000101", "ACME SUPPLIES", 45_000, "OPEN"),
    Order("000102", "ACME SUPPLIES", 250_000, "OPEN"),
    Order("000103", "NORTHWIND TRADING", 80_000, "SHIPPED"),
    Order("000104", "NORTHWIND TRADING", 120_000, "ON_HOLD"),
)


class InMemoryOrderStore:
    """Process-local store; restoring the state on an error keeps a use case atomic."""

    def __init__(self, orders: tuple[Order, ...] = SEED_ORDERS) -> None:
        self._lock = threading.RLock()
        self._orders = {order.order_id: order for order in orders}
        self._requests: dict[int, CancellationRequest] = {}

    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self._lock:
            snapshot = (copy.copy(self._orders), copy.copy(self._requests))
            try:
                yield
            except BaseException:
                self._orders, self._requests = snapshot
                raise

    def get_order(self, order_id: str) -> Order | None:
        return self._orders.get(order_id)

    def find_orders(self, customer_part: str, limit: int) -> list[Order]:
        wanted = customer_part.upper()
        found = [order for order in self._orders.values() if wanted in order.customer]
        return sorted(found, key=lambda order: order.order_id)[:limit]

    def save_order(self, order: Order) -> None:
        self._orders[order.order_id] = order

    def add_request(self, request: CancellationRequest) -> CancellationRequest:
        stored = replace(request, request_id=len(self._requests) + 1)
        self._requests[stored.request_id] = stored
        return stored

    def get_request(self, request_id: int) -> CancellationRequest | None:
        return self._requests.get(request_id)

    def list_requests(self, status: str | None) -> list[CancellationRequest]:
        requests = sorted(self._requests.values(), key=lambda r: r.request_id, reverse=True)
        return [r for r in requests if status is None or r.status == status]

    def save_request(self, request: CancellationRequest) -> None:
        self._requests[request.request_id] = request


_store: OrderStore = InMemoryOrderStore()


def get_store() -> OrderStore:
    return _store


def set_store(store: OrderStore) -> None:
    """Replaces the store (a deployed agent: the system of record; a test: a fresh one)."""
    global _store
    _store = store
