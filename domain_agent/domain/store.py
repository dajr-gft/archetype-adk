"""Storage port of the domain and its in-memory implementation.

The use cases depend on ``OrderStore`` only. The in-memory store serves local runs, unit
tests and the evaluation. A deployed agent replaces it in ``wiring.py`` with an adapter on
the system of record: a container keeps nothing between restarts and its instances share
nothing.

What every implementation has to give (``tests/unit/test_store_contract.py`` checks it):

- ``transaction()`` makes one use case atomic AND isolated: what a use case read cannot
  change under it before it writes. A use case checks and then writes ("no pending
  request" then "add one"), so two of them at the same time must not both pass the check.
  On a database that is a serializable transaction, or a lock on the rows that were read;
  the in-memory store uses one lock.
- ``add_write`` refuses a key that exists (a unique key).
"""

from __future__ import annotations

import copy
import threading
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, replace
from typing import Protocol

from .base import WriteJournal, WriteRecord


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
    status: str  # one of rules.REQUEST_STATUSES
    requested_by: str
    requested_at: str
    decided_by: str | None = None
    decided_at: str | None = None
    reject_reason: str | None = None


class OrderStore(WriteJournal, Protocol):
    """What the use cases need from storage."""

    def transaction(self) -> AbstractContextManager[None]: ...

    def get_order(self, order_id: str) -> Order | None: ...

    def find_orders(self, customer_part: str) -> list[Order]:
        """Orders whose customer name contains the text, by order id."""
        ...

    def save_order(self, order: Order) -> None: ...

    def add_request(self, request: CancellationRequest) -> CancellationRequest: ...

    def get_request(self, request_id: int) -> CancellationRequest | None: ...

    def list_requests(self, status: str | None) -> list[CancellationRequest]:
        """Requests of one status, or all of them, newest first."""
        ...

    def save_request(self, request: CancellationRequest) -> None: ...


# Invented data of the illustrative domain.
SEED_ORDERS: tuple[Order, ...] = (
    Order("000101", "ACME SUPPLIES", 45_000, "OPEN"),
    Order("000102", "ACME SUPPLIES", 250_000, "OPEN"),
    Order("000103", "NORTHWIND TRADING", 80_000, "SHIPPED"),
    Order("000104", "NORTHWIND TRADING", 120_000, "ON_HOLD"),
    Order("000105", "CONTOSO RETAIL", 300_000, "OPEN"),
    Order("000106", "CONTOSO RETAIL", 180_000, "OPEN"),
)
SEED_REQUESTS: tuple[CancellationRequest, ...] = (
    CancellationRequest(
        1, "000105", "OPEN", "customer changed mind", "PENDING", "CARLA", "2026-01-12 09:30:00 UTC"
    ),
    CancellationRequest(
        2, "000106", "OPEN", "wrong quantity", "PENDING", "CARLA", "2026-01-12 09:45:00 UTC"
    ),
)


class InMemoryOrderStore:
    """Process-local store: one lock, and the state restored when a use case fails."""

    def __init__(
        self,
        orders: tuple[Order, ...] = SEED_ORDERS,
        requests: tuple[CancellationRequest, ...] = SEED_REQUESTS,
    ) -> None:
        self._lock = threading.RLock()
        self._orders = {order.order_id: order for order in orders}
        self._requests = {request.request_id: request for request in requests}
        self._writes: dict[str, WriteRecord] = {}

    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self._lock:
            snapshot = (
                copy.copy(self._orders),
                copy.copy(self._requests),
                copy.copy(self._writes),
            )
            try:
                yield
            except BaseException:
                self._orders, self._requests, self._writes = snapshot
                raise

    def get_order(self, order_id: str) -> Order | None:
        return self._orders.get(order_id)

    def find_orders(self, customer_part: str) -> list[Order]:
        wanted = customer_part.upper()
        found = [order for order in self._orders.values() if wanted in order.customer]
        return sorted(found, key=lambda order: order.order_id)

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

    def find_write(self, key: str) -> WriteRecord | None:
        return self._writes.get(key)

    def add_write(self, record: WriteRecord) -> None:
        if record.key in self._writes:
            raise KeyError(f"write {record.key} is already recorded")
        self._writes[record.key] = record

    def writes(self) -> list[WriteRecord]:
        """Every recorded write, oldest first (for tests and for looking at a run)."""
        return list(self._writes.values())


_store: OrderStore = InMemoryOrderStore()


def get_store() -> OrderStore:
    return _store


def set_store(store: OrderStore) -> None:
    """Replaces the store (``wiring.py`` of a deployed agent; a fresh one in a test)."""
    global _store
    _store = store
