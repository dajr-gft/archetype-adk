"""Rules of the illustrative pipeline (a discount decision): plain Python, no ADK.

Invented domain. The legacy program ran these steps in a fixed order and stopped at the
first refusal; the workflow of ``agent.py`` keeps that order as graph edges.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

MAX_DISCOUNT_PCT: float = 30.0
AUTO_APPROVE_PCT: float = 10.0
MIN_ORDER_CENTS: int = 5_000
LOYALTY_YEARS: int = 5
LOYALTY_BONUS_PCT: float = 5.0
SEGMENTS: frozenset[str] = frozenset({"RETAIL", "WHOLESALE"})


class DiscountRequest(BaseModel):
    """What the intake step extracts from the user's message."""

    segment: str = Field(description="Customer segment: RETAIL or WHOLESALE.")
    order_cents: int = Field(description="Order amount in cents.")
    requested_pct: float = Field(description="Discount requested, in percent.")
    years_as_customer: int = Field(description="Whole years as a customer.")


class Decision(BaseModel):
    outcome: str  # APPROVED | REFERRED | DENIED | INVALID
    rule_id: str
    granted_pct: float
    reason: str


def validate(request: DiscountRequest) -> Decision | None:
    """VAL-001..003: the refusal, or None when the request is valid."""
    if request.segment.upper() not in SEGMENTS:
        return Decision(
            outcome="INVALID", rule_id="VAL-001", granted_pct=0, reason="SEGMENT_UNKNOWN"
        )
    if request.order_cents < MIN_ORDER_CENTS:
        return Decision(
            outcome="INVALID", rule_id="VAL-002", granted_pct=0, reason="ORDER_TOO_SMALL"
        )
    if not 0 < request.requested_pct <= 100:
        return Decision(
            outcome="INVALID", rule_id="VAL-003", granted_pct=0, reason="PERCENT_INVALID"
        )
    return None


def allowed_pct(request: DiscountRequest) -> float:
    """CALC-001: what may be approved without a second person."""
    bonus = LOYALTY_BONUS_PCT if request.years_as_customer >= LOYALTY_YEARS else 0.0
    return AUTO_APPROVE_PCT + bonus


def decide(request: DiscountRequest) -> Decision:
    """BR-001..003, in the order of the legacy program (first refusal wins)."""
    if request.requested_pct > MAX_DISCOUNT_PCT:
        return Decision(outcome="DENIED", rule_id="BR-001", granted_pct=0, reason="ABOVE_MAXIMUM")
    if request.requested_pct > allowed_pct(request):
        return Decision(
            outcome="REFERRED", rule_id="BR-002", granted_pct=0, reason="NEEDS_APPROVAL"
        )
    return Decision(
        outcome="APPROVED",
        rule_id="BR-003",
        granted_pct=request.requested_pct,
        reason="WITHIN_LIMIT",
    )
