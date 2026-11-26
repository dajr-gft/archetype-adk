"""Rules of the illustrative pipeline (a discount decision): plain Python, no ADK.

Invented domain. The legacy program ran these steps in a fixed order on one request and
stopped at the first refusal; ``agent.py`` keeps that order as the edges of a graph.

What the user gave arrives as text and is parsed here: an amount becomes an integer of
cents and a percentage an exact decimal. Nothing is computed with binary floats.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from domain_agent.domain.base import Rule

MAX_DISCOUNT_PERCENT: Decimal = Decimal("30")
AUTO_APPROVE_PERCENT: Decimal = Decimal("10")
LOYALTY_BONUS_PERCENT: Decimal = Decimal("5")
LOYALTY_YEARS: int = 5
MIN_ORDER_CENTS: int = 5_000
SEGMENTS: frozenset[str] = frozenset({"RETAIL", "WHOLESALE"})
REQUIRED_FIELDS: tuple[str, ...] = (
    "segment",
    "order_amount",
    "requested_percent",
    "years_as_customer",
)

RULES: dict[str, Rule] = {
    rule.rule_id: rule
    for rule in (
        Rule("VAL-001", "The segment is one of SEGMENTS.", "DSCPRG01:40-52"),
        Rule("VAL-002", "The order amount is at least MIN_ORDER_CENTS.", "DSCPRG01:53-60"),
        Rule("VAL-003", "The requested percentage is above 0 and at most 100.", "DSCPRG01:61-70"),
        Rule(
            "VAL-004",
            "A request is decided only when every one of REQUIRED_FIELDS was given.",
            "DSCPRG01:30-38",
        ),
        Rule(
            "CALC-001",
            "The percentage approved without a second person is AUTO_APPROVE_PERCENT, plus "
            "LOYALTY_BONUS_PERCENT from LOYALTY_YEARS years as a customer.",
            "DSCPRG01:88-97",
        ),
        Rule("BR-001", "A request above MAX_DISCOUNT_PERCENT is denied.", "DSCPRG01:101-108"),
        Rule(
            "BR-002",
            "A request above the percentage of CALC-001 is referred to a second person.",
            "DSCPRG01:109-118",
        ),
        Rule("BR-003", "Any other request is approved as requested.", "DSCPRG01:119-124"),
    )
}

_AMOUNT = re.compile(r"^\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,2})?$|^\d+(?:[.,]\d{1,2})?$")


@dataclass(frozen=True)
class Request:
    segment: str
    order_cents: int
    requested_percent: Decimal
    years_as_customer: int


@dataclass(frozen=True)
class Decision:
    """The outcome of a request: what the session keeps and the user is told."""

    outcome: str  # APPROVED | REFERRED | DENIED | INVALID | INCOMPLETE
    rule_id: str
    reason: str
    granted_percent: str = "0"
    missing: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "missing": list(self.missing)}


def missing_fields(given: Mapping[str, object]) -> list[str]:
    """VAL-004: the required fields the user has not given yet."""
    return [name for name in REQUIRED_FIELDS if given.get(name) in (None, "")]


def parse_amount(text: str) -> int | None:
    """An amount as written ("2,000.00", "2.000,00", "300") in cents, or None."""
    compact = text.strip().replace(" ", "")
    if not _AMOUNT.match(compact):
        return None
    decimals = re.search(r"[.,](\d{1,2})$", compact)
    whole = compact[: decimals.start()] if decimals else compact
    cents = (decimals.group(1) if decimals else "").ljust(2, "0")
    return int(re.sub(r"[.,]", "", whole)) * 100 + int(cents)


def parse_percent(text: str) -> Decimal | None:
    """A percentage as written ("12", "12%", "12,5") as an exact decimal, or None."""
    try:
        return Decimal(text.strip().rstrip("%").strip().replace(",", "."))
    except InvalidOperation:
        return None


def check(given: Mapping[str, object]) -> Request | Decision:
    """VAL-001, VAL-002, VAL-003 in the order of the legacy program: the request, or the refusal."""
    segment = str(given["segment"]).strip().upper()
    if segment not in SEGMENTS:
        return Decision("INVALID", "VAL-001", "SEGMENT_UNKNOWN")
    order_cents = parse_amount(str(given["order_amount"]))
    if order_cents is None or order_cents < MIN_ORDER_CENTS:
        return Decision("INVALID", "VAL-002", "ORDER_TOO_SMALL")
    percent = parse_percent(str(given["requested_percent"]))
    if percent is None or not Decimal(0) < percent <= Decimal(100):
        return Decision("INVALID", "VAL-003", "PERCENT_INVALID")
    years = given["years_as_customer"]
    return Request(segment, order_cents, percent, years if isinstance(years, int) else 0)


def allowed_percent(request: Request) -> Decimal:
    """CALC-001."""
    loyal = request.years_as_customer >= LOYALTY_YEARS
    return AUTO_APPROVE_PERCENT + (LOYALTY_BONUS_PERCENT if loyal else Decimal(0))


def decide(request: Request) -> Decision:
    """BR-001, BR-002, BR-003, in the order of the legacy program (the first refusal wins)."""
    if request.requested_percent > MAX_DISCOUNT_PERCENT:
        return Decision("DENIED", "BR-001", "ABOVE_MAXIMUM")
    if request.requested_percent > allowed_percent(request):
        return Decision("REFERRED", "BR-002", "NEEDS_APPROVAL")
    return Decision("APPROVED", "BR-003", "WITHIN_LIMIT", str(request.requested_percent))
