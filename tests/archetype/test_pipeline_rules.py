"""The rules of the pipeline example, without a model, and the shape of its graph."""

import pytest

from examples.pipeline_agent import rules
from examples.pipeline_agent.agent import root_agent
from examples.pipeline_agent.rules import DiscountRequest


def request(segment: str = "RETAIL", cents: int = 30_000, pct: float = 5, years: int = 1):
    return DiscountRequest(
        segment=segment, order_cents=cents, requested_pct=pct, years_as_customer=years
    )


@pytest.mark.parametrize(
    ("invalid", "rule_id"),
    [
        (request(segment="PUBLIC"), "VAL-001"),
        (request(cents=4_999), "VAL-002"),
        (request(pct=0), "VAL-003"),
        (request(pct=100.5), "VAL-003"),
    ],
)
def test_an_invalid_request_stops_before_the_rules(invalid: DiscountRequest, rule_id: str) -> None:
    refusal = rules.validate(invalid)
    assert refusal is not None
    assert (refusal.outcome, refusal.rule_id) == ("INVALID", rule_id)


def test_a_valid_request_at_the_limits_passes_validation() -> None:
    assert rules.validate(request(segment="wholesale", cents=5_000, pct=100)) is None


@pytest.mark.parametrize(
    ("pct", "years", "outcome", "rule_id"),
    [
        (10, 1, "APPROVED", "BR-003"),  # at the limit without loyalty
        (10.5, 1, "REFERRED", "BR-002"),
        (15, 5, "APPROVED", "BR-003"),  # loyalty bonus from the fifth year
        (15, 4, "REFERRED", "BR-002"),
        (30, 9, "REFERRED", "BR-002"),  # the maximum itself is not denied
        (30.5, 9, "DENIED", "BR-001"),
    ],
)
def test_the_decision_follows_the_order_of_the_legacy_program(
    pct: float, years: int, outcome: str, rule_id: str
) -> None:
    decision = rules.decide(request(pct=pct, years=years))
    assert (decision.outcome, decision.rule_id) == (outcome, rule_id)
    assert decision.granted_pct == (pct if outcome == "APPROVED" else 0)


def test_the_order_of_the_steps_is_the_graph() -> None:
    """The steps and their order are edges, not something a model decides."""
    edges = {
        (edge.from_node.name, edge.to_node.name, edge.route) for edge in root_agent.graph.edges
    }
    assert edges == {
        ("__START__", "intake", None),
        ("intake", "validate_request", None),
        ("validate_request", "decide_request", "valid"),
        ("validate_request", "present", "invalid"),
        ("decide_request", "present", None),
    }
