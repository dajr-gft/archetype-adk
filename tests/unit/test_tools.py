"""The guards of the tools, without a model: what the model cannot talk its way around."""

from domain_agent import tools
from domain_agent.domain.store import get_store

from .conftest import next_turn, session


async def test_nothing_is_written_without_a_prepared_draft() -> None:
    result = await tools.submit_order_cancellation(session("ana"))
    assert (result["status"], result["error_code"]) == ("error", "NO_DRAFT")
    assert get_store().get_order("000101").status == "OPEN"


async def test_nothing_is_written_in_the_turn_that_prepared_it() -> None:
    """The model cannot prepare and submit in one turn: the user answers in between."""
    context = session("ana")
    await tools.prepare_order_cancellation("101", "duplicate", context)
    refused = await tools.submit_order_cancellation(context)
    assert (refused["status"], refused["error_code"]) == ("error", "NOT_CONFIRMED")
    assert get_store().get_order("000101").status == "OPEN"
    done = await tools.submit_order_cancellation(next_turn(context))  # the draft was kept
    assert done["applied"] is True


async def test_the_write_uses_the_draft_the_user_saw() -> None:
    context = session("ana")
    draft = await tools.prepare_order_cancellation("101", "ordered  twice", context)
    assert (draft["status"], draft["needs_approval"]) == ("success", False)
    assert get_store().get_order("000101").status == "OPEN"  # prepare writes nothing
    done = await tools.submit_order_cancellation(next_turn(context))
    assert (done["status"], done["applied"], done["acting_user"]) == ("success", True, "ANA")
    assert get_store().get_order("000101").status == "CANCELLED"
    again = await tools.submit_order_cancellation(next_turn(context))
    assert again["error_code"] == "NO_DRAFT"  # a draft is used once


async def test_a_refused_draft_cancels_the_previous_one() -> None:
    context = session("ana")
    await tools.prepare_order_cancellation("101", "duplicate", context)
    refused = await tools.prepare_order_cancellation("103", "duplicate", next_turn(context))
    assert (refused["error_code"], refused["rule_id"]) == ("NOT_CANCELLABLE", "BR-001")
    assert (await tools.submit_order_cancellation(next_turn(context)))["error_code"] == "NO_DRAFT"


async def pending_request() -> int:
    maker = session("ana")
    await tools.prepare_order_cancellation("102", "duplicate", maker)
    created = await tools.submit_order_cancellation(next_turn(maker))
    assert created["applied"] is False
    return int(created["request"]["request_id"])


async def test_a_request_is_decided_only_after_it_was_reviewed() -> None:
    request_id = await pending_request()
    checker = session("bruno")
    approve = await tools.approve_cancellation_request(request_id, checker)
    reject = await tools.reject_cancellation_request(request_id, "no", checker)
    assert (approve["error_code"], reject["error_code"]) == ("NOT_REVIEWED", "NOT_REVIEWED")
    reviewed = await tools.review_cancellation_request(request_id, checker)
    assert reviewed["you_can_decide"] is True
    same_turn = await tools.approve_cancellation_request(request_id, checker)
    assert same_turn["error_code"] == "NOT_CONFIRMED"  # shown, but the user has not answered
    assert get_store().get_order("000102").status == "OPEN"
    decided = await tools.approve_cancellation_request(request_id, next_turn(checker))
    assert decided["request_status"] == "APPROVED"
    assert get_store().get_order("000102").status == "CANCELLED"


async def test_reviewing_one_request_does_not_allow_deciding_another() -> None:
    request_id = await pending_request()
    checker = session("bruno")
    await tools.review_cancellation_request(request_id, checker)
    other = await tools.approve_cancellation_request(request_id + 1, next_turn(checker))
    assert other["error_code"] == "NOT_REVIEWED"


async def test_the_acting_user_is_the_session_user() -> None:
    request_id = await pending_request()
    maker = session("ana")
    reviewed = await tools.review_cancellation_request(request_id, maker)
    assert reviewed["you_can_decide"] is False
    refused = await tools.approve_cancellation_request(request_id, next_turn(maker))
    assert (refused["error_code"], refused["rule_id"]) == ("FOUR_EYES", "BR-004")
    listed = await tools.list_cancellation_requests("PENDING", session("bruno"))
    assert [r["you_can_decide"] for r in listed["requests"]] == [True]
