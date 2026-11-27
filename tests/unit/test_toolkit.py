"""Archetype-owned. The guards of the toolkit, through the real ADK runner, without a model.

The tools below are stand-ins with no domain: they only say what the toolkit let through.
They prove what ``archetype.md`` promises of every generated agent, whatever its domain:
who acts, what a tool answers, and when a write or a decision is allowed to run.
"""

import logging
import time
from decimal import Decimal
from typing import Any

import pytest
from google.adk.agents import Agent
from google.adk.agents.base_agent import BaseAgent
from google.adk.tools.agent_tool import AgentTool
from google.adk.tools.tool_context import ToolContext

from domain_agent import toolkit
from domain_agent.domain.base import Confirmation, DomainError, fingerprint
from tests.support.scripted import Conversation

WRITES: list[tuple[str, dict[str, Any], Confirmation]] = []
DECISIONS: list[tuple[str, str, Confirmation]] = []
SHOWN = {"thing": "A-1", "amount": "450.00", "needs_approval": False}


@pytest.fixture(autouse=True)
def clean() -> None:
    WRITES.clear()
    DECISIONS.clear()


async def look(tool_context: ToolContext) -> dict[str, Any]:
    """Reads something."""
    return await toolkit.read(tool_context, lambda user: {"seen_by": user})


async def prepare_thing(thing: str, tool_context: ToolContext) -> dict[str, Any]:
    """Prepares a write.

    Args:
        thing: The key.
    """
    return await toolkit.prepare(
        tool_context, "write_thing", lambda user: {**SHOWN, "thing": thing}
    )


async def submit_thing(tool_context: ToolContext) -> dict[str, Any]:
    """Submits the prepared write."""

    def write(user: str, shown: dict[str, Any], confirmation: Confirmation) -> dict[str, Any]:
        WRITES.append((user, shown, confirmation))
        return {"written": shown["thing"]}

    return await toolkit.submit(tool_context, "write_thing", write)


async def submit_other(tool_context: ToolContext) -> dict[str, Any]:
    """Submits another operation."""
    return await toolkit.submit(tool_context, "write_other", lambda user, shown, c: {"written": 1})


async def review_item(item_id: int, tool_context: ToolContext) -> dict[str, Any]:
    """Shows an item.

    Args:
        item_id: The item.
    """
    return await toolkit.review(tool_context, "item", item_id, lambda user: {"item": item_id})


async def decide_item(item_id: int, tool_context: ToolContext) -> dict[str, Any]:
    """Decides an item.

    Args:
        item_id: The item.
    """

    def decision(user: str, confirmation: Confirmation) -> dict[str, Any]:
        DECISIONS.append((user, str(item_id), confirmation))
        return {"decided": item_id}

    return await toolkit.decide(tool_context, "item", item_id, decision)


async def refuse(tool_context: ToolContext) -> dict[str, Any]:
    """Is refused by a rule."""

    def use_case(user: str) -> dict[str, Any]:
        raise DomainError("NOT_ALLOWED", "Not allowed.", "BR-999")

    return await toolkit.read(tool_context, use_case)


async def broken(tool_context: ToolContext) -> dict[str, Any]:
    """Raises."""

    def use_case(user: str) -> dict[str, Any]:
        raise RuntimeError("storage is down")

    return await toolkit.read(tool_context, use_case)


async def not_json(tool_context: ToolContext) -> dict[str, Any]:
    """Returns a value JSON cannot carry."""
    return await toolkit.read(tool_context, lambda user: {"amount": Decimal("1.10")})


async def slow(tool_context: ToolContext) -> dict[str, Any]:
    """Takes too long."""

    def use_case(user: str) -> dict[str, Any]:
        time.sleep(0.5)
        return {}

    return await toolkit.read(tool_context, use_case)


TOOLS = [
    look, prepare_thing, submit_thing, submit_other, review_item, decide_item,
    refuse, broken, not_json, slow,
]  # fmt: skip
PREPARE = ("prepare_thing", {"thing": "A-1"})
SUBMIT = ("submit_thing", {})


def codes(answers: list[dict[str, Any]]) -> list[str]:
    return [answer.get("error_code") or answer["status"] for answer in answers]


# ── the envelope and the acting user ──────────────────────────────────────────────────


async def test_a_result_is_wrapped_and_names_the_session_user() -> None:
    talk = Conversation(TOOLS)
    assert await talk.turn("ana@example.com", "look", ("look", {})) == [
        {
            "status": "success",
            "acting_user": "ana@example.com",
            "result": {"seen_by": "ana@example.com"},
        }
    ]


async def test_a_refusal_carries_its_code_and_rule() -> None:
    talk = Conversation(TOOLS)
    assert await talk.turn("ana", "try", ("refuse", {})) == [
        {
            "status": "error",
            "error_code": "NOT_ALLOWED",
            "error_message": "Not allowed.",
            "rule_id": "BR-999",
        }
    ]


async def test_a_tool_that_breaks_answers_that_the_outcome_is_unknown() -> None:
    talk = Conversation(TOOLS)
    assert codes(await talk.turn("ana", "try", ("broken", {}))) == ["OUTCOME_UNKNOWN"]


async def test_a_result_that_json_cannot_carry_is_a_defect_not_a_result() -> None:
    talk = Conversation(TOOLS)
    assert codes(await talk.turn("ana", "try", ("not_json", {}))) == ["OUTCOME_UNKNOWN"]


async def test_a_use_case_that_does_not_answer_in_time(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(toolkit, "USE_CASE_TIMEOUT_SECONDS", 0.05)
    talk = Conversation(TOOLS)
    assert codes(await talk.turn("ana", "try", ("slow", {}))) == ["OUTCOME_UNKNOWN"]


# ── a write is confirmed ──────────────────────────────────────────────────────────────


async def test_a_write_runs_in_the_turn_after_its_preview_with_what_was_shown() -> None:
    talk = Conversation(TOOLS)
    assert codes(await talk.turn("ana", "write A-1", PREPARE)) == ["success"]
    assert WRITES == []
    assert await talk.turn("ana", "yes", SUBMIT) == [
        {"status": "success", "acting_user": "ana", "result": {"written": "A-1"}}
    ]
    [(user, shown, confirmation)] = WRITES
    assert (user, shown) == ("ana", SHOWN)
    assert confirmation.shown == fingerprint(SHOWN) and confirmation.key


async def test_nothing_is_written_in_the_turn_of_the_preview() -> None:
    """One step after the other, and both calls in one model step."""
    talk = Conversation(TOOLS)
    assert codes(await talk.turn("ana", "write A-1", PREPARE, SUBMIT)) == [
        "success",
        "NOT_CONFIRMED",
    ]
    # In one model step the two calls run concurrently, in either order: still no write.
    together = await talk.turn("bia", "write A-1", PREPARE, SUBMIT, together=True)
    assert sorted(codes(together))[0] in ("NOTHING_PREPARED", "NOT_CONFIRMED")
    assert WRITES == []
    assert codes(await talk.turn("ana", "yes", SUBMIT)) == ["success"]  # it was kept for the answer


async def test_nothing_is_written_without_a_preview() -> None:
    talk = Conversation(TOOLS)
    assert codes(await talk.turn("ana", "yes", SUBMIT)) == ["NOTHING_PREPARED"]
    assert WRITES == []


async def test_a_confirmation_is_used_once() -> None:
    talk = Conversation(TOOLS)
    await talk.turn("ana", "write A-1", PREPARE)
    assert codes(await talk.turn("ana", "yes", SUBMIT, SUBMIT)) == ["success", "NOTHING_PREPARED"]
    assert len(WRITES) == 1


async def test_a_confirmation_expires_when_the_user_moves_on() -> None:
    talk = Conversation(TOOLS)
    await talk.turn("ana", "write A-1", PREPARE)
    await talk.turn("ana", "by the way, good morning")  # a message, no tool
    assert codes(await talk.turn("ana", "yes", SUBMIT)) == ["CONFIRMATION_EXPIRED"]
    assert codes(await talk.turn("ana", "yes", SUBMIT)) == ["NOTHING_PREPARED"]
    assert WRITES == []


async def test_another_tool_call_drops_what_waited() -> None:
    talk = Conversation(TOOLS)
    await talk.turn("ana", "write A-1", PREPARE)
    assert codes(await talk.turn("ana", "wait, look first", ("look", {}), SUBMIT)) == [
        "success",
        "NOTHING_PREPARED",
    ]
    assert WRITES == []


async def test_a_confirmation_belongs_to_its_operation_and_its_session() -> None:
    talk = Conversation(TOOLS)
    await talk.turn("ana", "write A-1", PREPARE)
    assert codes(await talk.turn("ana", "yes", ("submit_other", {}))) == ["NOTHING_PREPARED"]
    await talk.turn("ana", "write A-1", PREPARE)
    assert codes(await talk.turn("bia", "yes", SUBMIT)) == ["NOTHING_PREPARED"]
    assert WRITES == []


async def test_a_newer_preview_replaces_the_older_one() -> None:
    talk = Conversation(TOOLS)
    await talk.turn("ana", "write A-1", PREPARE)
    await talk.turn("ana", "no, A-2", ("prepare_thing", {"thing": "A-2"}))
    await talk.turn("ana", "yes", SUBMIT)
    assert [shown["thing"] for _, shown, _ in WRITES] == ["A-2"]


# ── a decision is reviewed ────────────────────────────────────────────────────────────


async def test_a_decision_runs_in_the_turn_after_the_review_of_that_item() -> None:
    talk = Conversation(TOOLS)
    assert codes(await talk.turn("ana", "decide 7", ("decide_item", {"item_id": 7}))) == [
        "NOT_REVIEWED"
    ]
    assert codes(
        await talk.turn(
            "ana", "show 7", ("review_item", {"item_id": 7}), ("decide_item", {"item_id": 7})
        )
    ) == ["success", "NOT_CONFIRMED"]
    assert codes(await talk.turn("ana", "approve 8", ("decide_item", {"item_id": 8}))) == [
        "NOT_REVIEWED"
    ]
    assert DECISIONS == []
    await talk.turn("ana", "show 7", ("review_item", {"item_id": 7}))
    assert codes(await talk.turn("ana", "approve", ("decide_item", {"item_id": "7"}))) == [
        "success"
    ]
    [(user, item, confirmation)] = DECISIONS
    assert (user, item) == ("ana", "7") and confirmation.shown == fingerprint({"item": 7})


async def test_a_review_does_not_confirm_a_write() -> None:
    talk = Conversation(TOOLS)
    await talk.turn("ana", "show 7", ("review_item", {"item_id": 7}))
    assert codes(await talk.turn("ana", "yes", SUBMIT)) == ["NOTHING_PREPARED"]
    assert WRITES == []


# ── what a caller of the service could try ────────────────────────────────────────────


def planted(talk_user: str) -> dict[str, Any]:
    return {
        toolkit.PENDING: {
            "kind": "write", "name": "write_thing", "item": "", "shown": SHOWN,
            "key": "k", "user": talk_user, "answered_after": "",
        }
    }  # fmt: skip


async def test_state_planted_when_the_session_is_created_confirms_nothing() -> None:
    talk = Conversation(TOOLS)
    await talk.open("ana", state=planted("ana"))
    assert codes(await talk.turn("ana", "yes", SUBMIT)) == ["CONFIRMATION_EXPIRED"]
    assert WRITES == []


async def test_state_planted_with_a_message_confirms_nothing() -> None:
    talk = Conversation(TOOLS)
    await talk.turn("ana", "hello")
    assert codes(await talk.turn("ana", "yes", SUBMIT, state_delta=planted("ana"))) == [
        "CONFIRMATION_EXPIRED"
    ]
    assert WRITES == []


async def test_through_an_agent_tool_nothing_is_written() -> None:
    """Each call of an AgentTool is a session of its own: no user message is in between."""

    def coordinator(agent: Agent) -> BaseAgent:
        return Agent(name="coordinator", model=agent.model, tools=[AgentTool(agent)])

    talk = Conversation(TOOLS, root=coordinator)
    worker = ("scripted_agent", {"request": "do it"})
    # In ONE user turn the coordinator calls the worker twice: it prepares, then submits.
    await talk.run(
        "ana",
        "write A-1 now",
        [[worker], [PREPARE], "prepared", [worker], [SUBMIT], "submitted", "done"],
    )
    assert WRITES == []


# ── the audit trail ───────────────────────────────────────────────────────────────────


async def test_every_tool_call_leaves_an_audit_record() -> None:
    audit = logging.getLogger("domain_agent.audit")
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[method-assign]
    audit.addHandler(handler)
    try:
        talk = Conversation(TOOLS)
        await talk.turn(
            "ana", "go", ("prepare_thing", {"thing": "A-1"}), ("refuse", {}), ("broken", {})
        )
    finally:
        audit.removeHandler(handler)
    entries = [(r.getMessage(), r.audit) for r in records]  # type: ignore[attr-defined]
    assert [message for message, _ in entries] == [
        "tool_call",
        "tool_call",
        "tool_failed",
        "tool_call",
    ]
    prepared, refused, failed, answered = (fields for _, fields in entries)
    assert (prepared["user"], prepared["tool"], prepared["arguments"], prepared["status"]) == (
        "ana", "prepare_thing", ["thing"], "success",
    )  # fmt: skip
    assert (refused["error_code"], refused["rule_id"]) == ("NOT_ALLOWED", "BR-999")
    assert failed["error"] == "RuntimeError" and answered["error_code"] == "OUTCOME_UNKNOWN"
    assert "A-1" not in str(entries)  # argument values are not logged


def test_the_audit_log_has_an_output_of_its_own() -> None:
    """Python drops INFO records by default; the audit trail does not depend on that."""
    Conversation(TOOLS)
    audit = logging.getLogger("domain_agent.audit")
    assert audit.handlers and audit.level == logging.INFO and audit.propagate is False
