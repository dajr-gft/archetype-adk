"""The rules, without a model. Each test names the rule it proves (gate C07)."""

import pytest

from domain_agent.domain import service
from domain_agent.domain.rules import RULES, DomainError, normalize_order_id, normalize_reason
from domain_agent.domain.store import get_store


def refusal(call) -> DomainError:
    with pytest.raises(DomainError) as caught:
        call()
    return caught.value


@pytest.mark.parametrize(("raw", "stored"), [("101", "000101"), (" 000101 ", "000101")])
def test_val_001_order_id_is_six_digits_zero_filled(raw: str, stored: str) -> None:
    """VAL-001"""
    assert normalize_order_id(raw) == stored


@pytest.mark.parametrize("raw", ["", "0", "1234567", "A101", "10 1"])
def test_val_001_other_ids_are_refused(raw: str) -> None:
    """VAL-001"""
    assert refusal(lambda: normalize_order_id(raw)).rule_id == "VAL-001"


def test_val_002_reason_is_one_to_sixty_printable_characters() -> None:
    """VAL-002"""
    assert normalize_reason("  ordered   twice ") == "ordered twice"
    assert normalize_reason("x" * 60) == "x" * 60
    for raw in ("", "   ", "x" * 61, "line\x00break"):
        assert refusal(lambda raw=raw: normalize_reason(raw)).rule_id == "VAL-002"


def test_br_001_only_open_or_on_hold_is_cancellable() -> None:
    """BR-001"""
    assert service.preview_cancellation("104", "duplicate")["status_before"] == "ON_HOLD"
    error = refusal(lambda: service.preview_cancellation("103", "duplicate"))
    assert (error.code, error.rule_id) == ("NOT_CANCELLABLE", "BR-001")


def test_br_002_one_pending_request_per_order() -> None:
    """BR-002"""
    service.cancel_order("102", "duplicate", "ana")
    error = refusal(lambda: service.cancel_order("102", "again", "bruno"))
    assert (error.code, error.rule_id) == ("ALREADY_PENDING", "BR-002")


def test_br_003_at_the_threshold_the_cancellation_is_applied() -> None:
    """BR-003: 1,000.00 is not above the threshold."""
    get_store().save_order(
        get_store().get_order("000101").__class__("000105", "X", 100_000, "OPEN")
    )
    assert service.cancel_order("105", "duplicate", "ana")["applied"] is True
    assert get_store().get_order("000105").status == "CANCELLED"


def test_br_003_above_the_threshold_a_request_waits_for_approval() -> None:
    """BR-003"""
    result = service.cancel_order("102", "duplicate", "ana")
    assert result["applied"] is False
    assert result["request"]["request_status"] == "PENDING"
    assert get_store().get_order("000102").status == "OPEN"


def test_br_004_the_requester_cannot_decide() -> None:
    """BR-004, for approval and for rejection, whatever the case of the user id."""
    request_id = service.cancel_order("102", "duplicate", "ana")["request"]["request_id"]
    for decide in (
        lambda: service.approve_request(request_id, "ANA"),
        lambda: service.reject_request(request_id, "no", "Ana"),
    ):
        error = refusal(decide)
        assert (error.code, error.rule_id) == ("FOUR_EYES", "BR-004")
    assert get_store().get_order("000102").status == "OPEN"


def test_br_004_a_second_person_approves_and_the_order_is_cancelled() -> None:
    """BR-004"""
    request_id = service.cancel_order("102", "duplicate", "ana")["request"]["request_id"]
    decided = service.approve_request(request_id, "bruno")
    assert (decided["request_status"], decided["decided_by"]) == ("APPROVED", "BRUNO")
    assert get_store().get_order("000102").status == "CANCELLED"
    assert refusal(lambda: service.approve_request(request_id, "carla")).code == "NOT_PENDING"


def test_br_005_a_rejection_needs_a_reason_and_changes_no_order() -> None:
    """BR-005"""
    request_id = service.cancel_order("102", "duplicate", "ana")["request"]["request_id"]
    error = refusal(lambda: service.reject_request(request_id, "  ", "bruno"))
    assert (error.code, error.rule_id) == ("REASON_MISSING", "BR-005")
    decided = service.reject_request(request_id, "customer wants it", "bruno")
    assert (decided["request_status"], decided["reject_reason"]) == (
        "REJECTED",
        "customer wants it",
    )
    assert get_store().get_order("000102").status == "OPEN"


def test_br_006_an_order_changed_since_the_request_is_not_cancelled() -> None:
    """BR-006: nothing is written, the request stays pending."""
    request_id = service.cancel_order("102", "duplicate", "ana")["request"]["request_id"]
    order = get_store().get_order("000102")
    get_store().save_order(
        order.__class__(order.order_id, order.customer, order.amount_cents, "SHIPPED")
    )
    error = refusal(lambda: service.approve_request(request_id, "bruno"))
    assert (error.code, error.rule_id) == ("CHANGED_SINCE", "BR-006")
    assert get_store().get_order("000102").status == "SHIPPED"
    assert service.get_request(request_id, "bruno")["request_status"] == "PENDING"


def test_every_rule_of_the_catalogue_cites_its_source() -> None:
    assert RULES and all(":" in rule.source for rule in RULES.values())


def test_search_by_id_and_by_customer() -> None:
    assert [o["order_id"] for o in service.find_orders("101")["orders"]] == ["000101"]
    assert [o["order_id"] for o in service.find_orders("northwind")["orders"]] == [
        "000103",
        "000104",
    ]
    assert service.find_orders("999")["orders"] == []
    assert refusal(lambda: service.find_orders(" ")).code == "QUERY_MISSING"
