"""The rules and use cases, without a model.

Each test names the rule it proves in its docstring (gate C07 looks for the id there or in
the test name). For each rule: what is accepted, what is refused with its code and rule
id, and the boundary. For each write: that a refusal wrote nothing.
"""

from collections.abc import Callable
from dataclasses import replace
from typing import Any

import pytest

from domain_agent.domain import rules, service
from domain_agent.domain.base import Confirmation, DomainError
from domain_agent.domain.rules import RULES
from domain_agent.domain.store import InMemoryOrderStore, Order, get_store, set_store


def refusal(call: Callable[[], Any]) -> DomainError:
    with pytest.raises(DomainError) as caught:
        call()
    return caught.value


def cancel(order_id: str, reason: str, user: str) -> dict[str, Any]:
    """Preview, then the write the user confirmed."""
    shown = service.preview_cancellation(order_id, reason)
    return service.cancel_order(order_id, reason, user, Confirmation.of(shown))


def decide(request_id: int, user: str, approve: bool, reason: str = "") -> dict[str, Any]:
    """Review, then the decision of the user."""
    confirmation = Confirmation.of(service.review_request(request_id, user))
    if approve:
        return service.approve_request(request_id, user, confirmation)
    return service.reject_request(request_id, reason, user, confirmation)


def order(order_id: str) -> Order:
    found = get_store().get_order(order_id)
    assert found is not None
    return found


# ── validations ───────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("raw", "stored"), [("101", "000101"), (" 000101 ", "000101")])
def test_an_order_id_is_zero_filled(raw: str, stored: str) -> None:
    """VAL-001"""
    assert rules.normalize_order_id(raw) == stored


@pytest.mark.parametrize("raw", ["", "0", "000000", "1234567", "A101", "10 1", "²", "١٠١"])
def test_other_order_ids_are_refused(raw: str) -> None:
    """VAL-001: also digits that are not the ten of the legacy character set."""
    error = refusal(lambda: rules.normalize_order_id(raw))
    assert (error.code, error.rule_id) == ("ORDER_ID_INVALID", "VAL-001")


def test_a_value_that_is_not_text_is_refused_not_a_crash() -> None:
    """A model may send a number where text is expected."""
    assert refusal(lambda: rules.normalize_order_id(101)).code == "INPUT_INVALID"
    assert refusal(lambda: service.preview_cancellation("101", None)).code == "INPUT_INVALID"


def test_a_reason_is_one_to_sixty_characters_of_the_legacy_set() -> None:
    """VAL-002: at the limit, one past it, empty, and outside the character set."""
    assert rules.normalize_reason("  ordered   twice ") == "ordered twice"
    assert rules.normalize_reason("x" * rules.REASON_MAX_LENGTH) == "x" * rules.REASON_MAX_LENGTH
    for raw in ("", "   ", "x" * (rules.REASON_MAX_LENGTH + 1), "razão", "a\x00b"):
        error = refusal(lambda raw=raw: rules.normalize_reason(raw))
        assert (error.code, error.rule_id) == ("REASON_INVALID", "VAL-002")


def test_a_user_id_is_kept_in_upper_case_and_compared_in_that_form() -> None:
    """VAL-003: also against a stored id padded as the legacy record keeps it."""
    assert rules.normalize_user(" ana@example.com ") == "ANA@EXAMPLE.COM"
    assert rules.same_user("ANA     ", "ana") and not rules.same_user("ANA", "bruno")
    for raw in ("", "  ", "a b", "anã"):
        assert refusal(lambda raw=raw: rules.normalize_user(raw)).code == "USER_UNKNOWN"


def test_an_amount_is_formatted_by_code() -> None:
    assert [rules.format_amount(cents) for cents in (45_000, 5, 100_001)] == [
        "450.00",
        "0.05",
        "1000.01",
    ]


# ── search and lists ──────────────────────────────────────────────────────────────────


def test_a_query_of_digits_is_an_order_id_any_other_a_customer_name() -> None:
    """BR-007"""
    assert [o["order_id"] for o in service.find_orders("101")["orders"]] == ["000101"]
    found = service.find_orders("northwind")
    assert [o["order_id"] for o in found["orders"]] == ["000103", "000104"]
    assert (found["total_matches"], found["more"]) == (2, False)
    assert service.find_orders("999")["orders"] == []
    assert refusal(lambda: service.find_orders(" ")).code == "QUERY_MISSING"


def test_a_search_lists_the_limit_and_says_that_there_are_more() -> None:
    """BR-007: at the limit nothing is left out; one more and the result says so."""
    many = tuple(
        Order(f"{n:06d}", "FABRIKAM", 1_000, "OPEN") for n in range(1, rules.SEARCH_LIMIT + 1)
    )
    set_store(InMemoryOrderStore(many, ()))
    assert service.find_orders("fabrikam")["more"] is False
    set_store(InMemoryOrderStore((*many, Order("000999", "FABRIKAM", 1_000, "OPEN")), ()))
    found = service.find_orders("fabrikam")
    assert (len(found["orders"]), found["total_matches"], found["more"]) == (
        rules.SEARCH_LIMIT,
        rules.SEARCH_LIMIT + 1,
        True,
    )


def test_requests_are_listed_by_status_or_all_newest_first() -> None:
    """BR-008"""
    assert [r["request_id"] for r in service.list_requests("pending", "bruno")["requests"]] == [
        2,
        1,
    ]
    decide(1, "bruno", approve=True)
    assert [r["request_id"] for r in service.list_requests("APPROVED", "bruno")["requests"]] == [1]
    assert [r["request_id"] for r in service.list_requests("ALL", "bruno")["requests"]] == [2, 1]
    error = refusal(lambda: service.list_requests("OPEN", "bruno"))
    assert (error.code, error.rule_id) == ("STATUS_INVALID", "BR-008")


# ── cancellation ──────────────────────────────────────────────────────────────────────


def test_only_an_open_or_on_hold_order_is_cancellable() -> None:
    """BR-001"""
    assert service.preview_cancellation("104", "duplicate")["status"] == "ON_HOLD"
    error = refusal(lambda: service.preview_cancellation("103", "duplicate"))
    assert (error.code, error.rule_id) == ("NOT_CANCELLABLE", "BR-001")


def test_an_order_has_one_pending_request() -> None:
    """BR-002"""
    assert cancel("102", "duplicate", "ana")["applied"] is False
    error = refusal(lambda: cancel("102", "again", "bruno"))
    assert (error.code, error.rule_id) == ("ALREADY_PENDING", "BR-002")


def test_at_the_threshold_a_cancellation_is_applied_above_it_a_request_waits() -> None:
    """BR-003: the threshold itself, and one cent above it."""
    limit = rules.APPROVAL_THRESHOLD_CENTS
    set_store(
        InMemoryOrderStore(
            (Order("000001", "X", limit, "OPEN"), Order("000002", "X", limit + 1, "OPEN")), ()
        )
    )
    at = cancel("1", "duplicate", "ana")
    assert (at["applied"], order("000001").status) == (True, "CANCELLED")
    above = cancel("2", "duplicate", "ana")
    assert (above["applied"], order("000002").status) == (False, "OPEN")
    [pending] = service.list_requests("PENDING", "ana")["requests"]
    assert (pending["request_id"], pending["requested_by"]) == (above["request_id"], "ANA")


def test_a_write_leaves_a_record_of_who_did_what() -> None:
    cancel("101", "duplicate", "ana")
    store = get_store()
    assert isinstance(store, InMemoryOrderStore)
    [written] = store.writes()
    assert (written.operation, written.target, written.user) == ("cancel_order", "000101", "ANA")


def test_what_changed_after_it_was_shown_is_not_written() -> None:
    """The user saw 450.00 and "no approval"; the order is another one when confirmed."""
    shown = service.preview_cancellation("101", "duplicate")
    get_store().save_order(replace(order("000101"), amount_cents=250_000))
    error = refusal(lambda: service.cancel_order("101", "duplicate", "ana", Confirmation.of(shown)))
    assert error.code == "CHANGED_SINCE_SHOWN"
    assert order("000101").status == "OPEN"
    assert service.list_requests("ALL", "ana")["requests"][0]["request_id"] == 2  # none added


# ── decision of a request ─────────────────────────────────────────────────────────────


def test_the_requester_cannot_decide() -> None:
    """BR-004: for approval and for rejection, whatever the case of the user id."""
    request_id = cancel("102", "duplicate", "ana")["request_id"]
    assert service.review_request(request_id, "ANA")["you_can_decide"] is False
    for attempt in (
        lambda: decide(request_id, "Ana", approve=True),
        lambda: decide(request_id, "ANA", approve=False, reason="no"),
    ):
        error = refusal(attempt)
        assert (error.code, error.rule_id) == ("FOUR_EYES", "BR-004")
    assert order("000102").status == "OPEN"


def test_a_second_person_approves_and_the_order_is_cancelled() -> None:
    """BR-004"""
    request_id = cancel("102", "duplicate", "ana")["request_id"]
    decided = decide(request_id, "bruno", approve=True)
    assert (decided["status"], decided["decided_by"], decided["order_status"]) == (
        "APPROVED",
        "BRUNO",
        "CANCELLED",
    )
    assert refusal(lambda: decide(request_id, "carla", approve=True)).code == "NOT_PENDING"


def test_a_rejection_needs_a_reason_and_changes_no_order() -> None:
    """BR-005"""
    error = refusal(lambda: decide(1, "bruno", approve=False, reason="  "))
    assert (error.code, error.rule_id) == ("REASON_MISSING", "BR-005")
    decided = decide(1, "bruno", approve=False, reason="customer wants it")
    assert (decided["status"], decided["reject_reason"]) == ("REJECTED", "customer wants it")
    assert order("000105").status == "OPEN"


def test_an_order_changed_since_the_request_is_not_cancelled() -> None:
    """BR-006: nothing is written and the request stays pending."""
    get_store().save_order(replace(order("000105"), status="SHIPPED"))
    error = refusal(lambda: decide(1, "bruno", approve=True))
    assert (error.code, error.rule_id) == ("CHANGED_SINCE_REQUESTED", "BR-006")
    assert order("000105").status == "SHIPPED"
    assert service.review_request(1, "bruno")["status"] == "PENDING"


def test_a_request_that_changed_after_the_review_is_not_decided() -> None:
    """The approver saw 3000.00; the order is another amount when the decision arrives."""
    confirmation = Confirmation.of(service.review_request(1, "bruno"))
    get_store().save_order(replace(order("000105"), amount_cents=9_900_000))
    error = refusal(lambda: service.approve_request(1, "bruno", confirmation))
    assert error.code == "CHANGED_SINCE_SHOWN"
    assert order("000105").status == "OPEN"


def test_every_rule_of_the_catalogue_says_where_it_comes_from() -> None:
    assert RULES and all(rule.source and rule.statement for rule in RULES.values())
