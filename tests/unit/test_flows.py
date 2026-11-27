"""The flows of the domain through the real tools, without a model.

A scripted model calls the tools as a model would; the ADK runner, the sessions and the
toolkit are real. A flow is checked on what was written to the store.
"""

from dataclasses import replace
from typing import Any

from domain_agent.agent import root_agent
from domain_agent.domain.store import InMemoryOrderStore
from tests.support.scripted import Conversation

PREPARE_101 = ("prepare_order_cancellation", {"order_id": "101", "reason": "duplicate"})
PREPARE_102 = ("prepare_order_cancellation", {"order_id": "102", "reason": "duplicate"})
SUBMIT = ("submit_order_cancellation", {})


def talk() -> Conversation:
    return Conversation(root_agent.tools)


def code(answer: dict[str, Any]) -> str:
    return str(answer.get("error_code") or answer["status"])


async def test_a_small_order_is_cancelled_after_the_user_confirms(
    fresh_store: InMemoryOrderStore,
) -> None:
    conversation = talk()
    [shown] = await conversation.turn("ana", "cancel order 101, it is a duplicate", PREPARE_101)
    assert shown["result"] == {
        "order_id": "000101",
        "customer": "ACME SUPPLIES",
        "amount": "450.00",
        "status": "OPEN",
        "reason": "duplicate",
        "needs_approval": False,
    }
    untouched = fresh_store.get_order("000101")
    assert untouched is not None and untouched.status == "OPEN"  # prepare writes nothing
    [done] = await conversation.turn("ana", "yes", SUBMIT)
    assert (done["acting_user"], done["result"]["applied"]) == ("ana", True)
    assert done["result"]["order"]["status"] == "CANCELLED"
    assert [(w.operation, w.target, w.user) for w in fresh_store.writes()] == [
        ("cancel_order", "000101", "ANA")
    ]


async def test_nothing_is_written_when_the_order_changed_before_the_confirmation(
    fresh_store: InMemoryOrderStore,
) -> None:
    conversation = talk()
    await conversation.turn("ana", "cancel order 101, it is a duplicate", PREPARE_101)
    order = fresh_store.get_order("000101")
    assert order is not None
    fresh_store.save_order(replace(order, amount_cents=999_900))  # someone else, meanwhile
    [refused] = await conversation.turn("ana", "yes", SUBMIT)
    assert code(refused) == "CHANGED_SINCE_SHOWN"
    assert fresh_store.get_order("000101") == replace(order, amount_cents=999_900)
    assert fresh_store.writes() == []


async def test_a_large_order_waits_for_a_second_person(fresh_store: InMemoryOrderStore) -> None:
    conversation = talk()
    await conversation.turn("ana", "cancel order 102, it is a duplicate", PREPARE_102)
    [created] = await conversation.turn("ana", "yes", SUBMIT)
    request_id = created["result"]["request_id"]
    assert created["result"]["applied"] is False

    # the requester cannot decide her own request
    review = ("review_cancellation_request", {"request_id": request_id})
    approve = ("approve_cancellation_request", {"request_id": request_id})
    [seen] = await conversation.turn("ana", "show me that request", review)
    assert seen["result"]["you_can_decide"] is False
    [refused] = await conversation.turn("ana", "approve it", approve)
    assert (code(refused), refused["rule_id"]) == ("FOUR_EYES", "BR-004")
    order = fresh_store.get_order("000102")
    assert order is not None and order.status == "OPEN"

    # a second person lists, reviews and, in the next turn, approves
    [listed] = await conversation.turn(
        "bruno", "anything for me?", ("list_cancellation_requests", {"status": "PENDING"})
    )
    assert request_id in [r["request_id"] for r in listed["result"]["requests"]]
    await conversation.turn("bruno", f"show me request {request_id}", review)
    [decided] = await conversation.turn("bruno", "it is correct, approve it", approve)
    assert (decided["result"]["status"], decided["result"]["decided_by"]) == ("APPROVED", "BRUNO")
    cancelled = fresh_store.get_order("000102")
    assert cancelled is not None and cancelled.status == "CANCELLED"
    assert [(w.operation, w.user) for w in fresh_store.writes()] == [
        ("cancel_order", "ANA"),
        ("approve_cancellation", "BRUNO"),
    ]


async def test_a_request_is_rejected_with_the_reason_of_the_user(
    fresh_store: InMemoryOrderStore,
) -> None:
    conversation = talk()
    await conversation.turn(
        "bruno", "show request 2", ("review_cancellation_request", {"request_id": 2})
    )
    [decided] = await conversation.turn(
        "bruno",
        "reject it: the order is already in production",
        ("reject_cancellation_request", {"request_id": 2, "reason": "already in production"}),
    )
    assert (decided["result"]["status"], decided["result"]["reject_reason"]) == (
        "REJECTED",
        "already in production",
    )
    order = fresh_store.get_order("000106")
    assert order is not None and order.status == "OPEN"


async def test_a_refusal_of_a_rule_reaches_the_user_with_its_rule() -> None:
    [refused] = await talk().turn(
        "ana",
        "cancel order 103",
        ("prepare_order_cancellation", {"order_id": "103", "reason": "duplicate"}),
    )
    assert (code(refused), refused["rule_id"]) == ("NOT_CANCELLABLE", "BR-001")
