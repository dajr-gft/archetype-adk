"""The pipeline example without a model: its rules, its graph, and a run of the graph.

In the run, a scripted model stands in for the two model nodes (it returns what the
intake would extract, then any answer). The function nodes, the routes and the session
state are real, so the order of the steps and their results are proven without a model.
"""

import json
from decimal import Decimal
from typing import Any

import pytest
from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.genai import types

from examples.pipeline_agent import agent as pipeline
from examples.pipeline_agent.domain import rules
from examples.pipeline_agent.domain.rules import Decision, Request
from tests.support.scripted import ScriptedModel

GIVEN = {
    "segment": "retail",
    "order_amount": "300.00",
    "requested_percent": "5",
    "years_as_customer": 1,
}


def request(percent: str = "5", years: int = 1) -> Request:
    return Request("RETAIL", 30_000, Decimal(percent), years)


@pytest.mark.parametrize(
    ("text", "cents"),
    [
        ("300", 30_000),
        ("300.5", 30_050),
        ("2,000.00", 200_000),
        ("2.000,00", 200_000),
        ("1.234.567,89", 123_456_789),
    ],
)
def test_an_amount_is_parsed_as_written_into_cents(text: str, cents: int) -> None:
    assert rules.parse_amount(text) == cents


def test_what_is_not_an_amount_or_a_percentage_is_not_guessed() -> None:
    assert [rules.parse_amount(text) for text in ("", "abc", "1.2.3", "-5")] == [None] * 4
    assert rules.parse_percent("12,5%") == Decimal("12.5") and rules.parse_percent("many") is None


@pytest.mark.parametrize(
    ("change", "rule_id"),
    [
        ({"segment": "PUBLIC"}, "VAL-001"),
        ({"order_amount": "49.99"}, "VAL-002"),
        ({"order_amount": "a lot"}, "VAL-002"),
        ({"requested_percent": "0"}, "VAL-003"),
        ({"requested_percent": "100.5"}, "VAL-003"),
    ],
)
def test_an_invalid_request_is_refused_before_the_rules(
    change: dict[str, Any], rule_id: str
) -> None:
    """VAL-001, VAL-002, VAL-003"""
    refused = rules.check({**GIVEN, **change})
    assert isinstance(refused, Decision)
    assert (refused.outcome, refused.rule_id) == ("INVALID", rule_id)


def test_a_valid_request_at_the_limits_is_accepted() -> None:
    """VAL-002 and VAL-003 at their boundaries."""
    accepted = rules.check({**GIVEN, "order_amount": "50.00", "requested_percent": "100"})
    assert accepted == Request("RETAIL", 5_000, Decimal("100"), 1)


def test_a_field_that_was_not_given_is_missing_not_zero() -> None:
    """VAL-004"""
    assert rules.missing_fields({**GIVEN, "years_as_customer": None}) == ["years_as_customer"]
    assert rules.missing_fields({**GIVEN, "years_as_customer": 0}) == []


def test_the_loyalty_bonus_starts_in_the_fifth_year() -> None:
    """CALC-001"""
    assert rules.allowed_percent(request(years=4)) == Decimal("10")
    assert rules.allowed_percent(request(years=5)) == Decimal("15")


@pytest.mark.parametrize(
    ("percent", "years", "outcome", "rule_id"),
    [
        ("10", 1, "APPROVED", "BR-003"),  # at the limit without loyalty
        ("10.01", 1, "REFERRED", "BR-002"),
        ("15", 5, "APPROVED", "BR-003"),
        ("15", 4, "REFERRED", "BR-002"),
        ("30", 9, "REFERRED", "BR-002"),  # the maximum itself is not denied
        ("30.01", 9, "DENIED", "BR-001"),
    ],
)
def test_the_decision_follows_the_order_of_the_legacy_program(
    percent: str, years: int, outcome: str, rule_id: str
) -> None:
    """BR-001, BR-002, BR-003"""
    decision = rules.decide(request(percent, years))
    assert (decision.outcome, decision.rule_id) == (outcome, rule_id)
    assert decision.granted_percent == (percent if outcome == "APPROVED" else "0")


def test_the_order_of_the_steps_is_the_graph() -> None:
    """The steps and their order are edges, not something a model decides."""
    edges = {
        (edge.from_node.name, edge.to_node.name, edge.route)
        for edge in pipeline.root_agent.graph.edges
    }
    assert edges == {
        ("__START__", "intake", None),
        ("intake", "collect_request", None),
        ("collect_request", "validate_request", "complete"),
        ("collect_request", "present", "incomplete"),
        ("validate_request", "decide_request", "valid"),
        ("validate_request", "present", "invalid"),
        ("decide_request", "present", None),
    }


class Run:
    """The pipeline with a scripted model in its two model nodes."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.model = ScriptedModel(steps=[], requests=[])
        for node in pipeline.root_agent.graph.nodes:  # the graph holds copies of the agents
            if isinstance(node, LlmAgent):
                monkeypatch.setattr(node, "model", self.model)
        self.runner = InMemoryRunner(app=pipeline.app)
        self.session_id = ""

    async def say(self, extracted: dict[str, Any]) -> dict[str, Any]:
        """One message of the user, of which the intake extracts ``extracted``."""
        if not self.session_id:
            session = await self.runner.session_service.create_session(
                app_name=pipeline.app.name, user_id="user"
            )
            self.session_id = session.id
        self.model.steps = [[types.Part(text=json.dumps(extracted))], [types.Part(text="answer")]]
        message = types.Content(role="user", parts=[types.Part.from_text(text="a request")])
        async for _ in self.runner.run_async(
            user_id="user", session_id=self.session_id, new_message=message
        ):
            pass
        session = await self.runner.session_service.get_session(
            app_name=pipeline.app.name, user_id="user", session_id=self.session_id
        )
        assert session is not None
        return dict(session.state)


async def test_the_graph_decides_a_complete_request(monkeypatch: pytest.MonkeyPatch) -> None:
    state = await Run(monkeypatch).say({**GIVEN, "requested_percent": "20"})
    assert (state["decision"]["outcome"], state["decision"]["rule_id"]) == ("REFERRED", "BR-002")


async def test_the_graph_stops_at_an_invalid_request(monkeypatch: pytest.MonkeyPatch) -> None:
    state = await Run(monkeypatch).say({**GIVEN, "order_amount": "20,00"})
    assert (state["decision"]["outcome"], state["decision"]["rule_id"]) == ("INVALID", "VAL-002")


async def test_the_graph_asks_for_what_is_missing_and_decides_when_it_arrives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """VAL-004: nothing is decided on a value the user did not give."""
    run = Run(monkeypatch)
    first = await run.say({**GIVEN, "requested_percent": "12", "years_as_customer": None})
    assert first["decision"]["outcome"] == "INCOMPLETE"
    assert first["decision"]["missing"] == ["years_as_customer"]
    second = await run.say(
        {"segment": None, "order_amount": None, "requested_percent": None, "years_as_customer": 6}
    )
    assert (second["decision"]["outcome"], second["decision"]["granted_percent"]) == (
        "APPROVED",
        "12",
    )
