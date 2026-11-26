"""Archetype-owned. What makes a write safe, and what the store has to give for it.

These tests use only the part of the storage port that every domain has (``transaction``,
``find_write``, ``add_write``), so they hold for the store of any generated agent: run
them against the adapter of the system of record too (``fresh_store`` in ``conftest.py``).
"""

import threading
import time
from decimal import Decimal
from typing import Any

import pytest

from domain_agent.domain.base import (
    Confirmation,
    DomainError,
    WriteRecord,
    authorize,
    fingerprint,
    record,
)

SHOWN = {"order_id": "000101", "amount": "450.00", "needs_approval": False, "lines": [1, 2]}


def test_a_fingerprint_is_of_the_content_not_of_its_order() -> None:
    reordered = {"lines": [1, 2], "needs_approval": False, "amount": "450.00", "order_id": "000101"}
    assert fingerprint(SHOWN) == fingerprint(reordered)
    assert fingerprint(SHOWN) != fingerprint({**SHOWN, "amount": "450.01"})
    assert fingerprint(SHOWN) != fingerprint({**SHOWN, "lines": [2, 1]})


def test_a_fingerprint_survives_the_session_and_refuses_what_json_cannot_carry() -> None:
    """A session service keeps what was shown as JSON: a tuple comes back as a list."""
    assert fingerprint({"lines": (1, 2)}) == fingerprint({"lines": [1, 2]})
    with pytest.raises(TypeError):
        fingerprint({"amount": Decimal("450.00")})


def test_a_write_is_authorized_once_and_only_for_what_was_shown(fresh_store: Any) -> None:
    confirmation = Confirmation.of(SHOWN)
    with fresh_store.transaction():
        authorize(fresh_store, confirmation, SHOWN)
        with pytest.raises(DomainError) as changed:
            authorize(fresh_store, confirmation, {**SHOWN, "amount": "2500.00"})
        record(fresh_store, confirmation, operation="cancel_order", target="000101", user="ANA")
    assert changed.value.code == "CHANGED_SINCE_SHOWN"
    written = fresh_store.find_write(confirmation.key)
    assert (written.operation, written.target, written.user) == ("cancel_order", "000101", "ANA")
    with fresh_store.transaction(), pytest.raises(DomainError) as again:
        authorize(fresh_store, confirmation, SHOWN)
    assert again.value.code == "ALREADY_SUBMITTED"


def test_a_transaction_that_fails_leaves_nothing(fresh_store: Any) -> None:
    entry = WriteRecord("k-1", "operation", "target", "ANA", "now")
    with pytest.raises(RuntimeError), fresh_store.transaction():
        fresh_store.add_write(entry)
        raise RuntimeError("the use case failed after it wrote")
    assert fresh_store.find_write("k-1") is None


def test_the_store_refuses_a_second_record_of_one_confirmation(fresh_store: Any) -> None:
    entry = WriteRecord("k-1", "operation", "target", "ANA", "now")
    with fresh_store.transaction():
        fresh_store.add_write(entry)
    with pytest.raises(Exception), fresh_store.transaction():  # noqa: B017 - any refusal of the store
        fresh_store.add_write(entry)


def test_two_use_cases_at_once_do_not_both_pass_the_same_check(fresh_store: Any) -> None:
    """Check, then write: the transaction has to keep the check true until the write."""
    outcomes: list[str] = []

    def use_case() -> None:
        try:
            with fresh_store.transaction():
                if fresh_store.find_write("k-1") is None:
                    time.sleep(0.05)  # the other one checks meanwhile
                    fresh_store.add_write(WriteRecord("k-1", "operation", "target", "ANA", "now"))
                    outcomes.append("wrote")
                else:
                    outcomes.append("refused")
        except Exception:  # noqa: BLE001 - a store may refuse by raising
            outcomes.append("refused")

    threads = [threading.Thread(target=use_case) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["refused", "wrote"]
