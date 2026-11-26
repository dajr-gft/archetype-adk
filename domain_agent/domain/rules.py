"""Business rules of the domain: constants, validations and their catalogue.

Illustrative domain: ``orders`` (invented; a generated agent replaces it).

Every rule has an id, a statement and its source. ``RULES`` is the catalogue: the
conformance gate requires a source for every rule and a unit test that names every
rule id. A source is one of:

    <member>:<line>[-<line>]    the legacy code that states the rule
    DOC:<document>#<anchor>     a document of the legacy system (a screen, a manual)
    ASSUMED:OP-<n>              not stated by any source: an assumption, described
                                as open point OP-<n> in OPEN_POINTS.md
"""

from __future__ import annotations

from dataclasses import dataclass

# ── Constants (exact values of the legacy source; never tool parameters) ──────────────
ORDER_ID_LENGTH: int = 6
REASON_MAX_LENGTH: int = 60
CANCELLABLE_STATUSES: frozenset[str] = frozenset({"OPEN", "ON_HOLD"})
APPROVAL_THRESHOLD_CENTS: int = 100_000  # a cancellation above it needs a second person


@dataclass(frozen=True)
class Rule:
    """One business rule and where the legacy source states it."""

    rule_id: str
    statement: str
    source: str  # legacy code, a document, or a declared assumption (see above)


RULES: dict[str, Rule] = {
    rule.rule_id: rule
    for rule in (
        Rule(
            "VAL-001", "An order id is 6 digits; shorter input is zero-filled.", "ORDMNT01:98-125"
        ),
        Rule(
            "VAL-002", "A cancellation reason is 1 to 60 printable characters.", "ORDMNT02:195-208"
        ),
        Rule("BR-001", "Only an OPEN or ON_HOLD order can be cancelled.", "ORDMNT02:143-150"),
        Rule(
            "BR-002", "An order has at most one pending cancellation request.", "ORDMNT02:129-137"
        ),
        Rule(
            "BR-003",
            "A cancellation above 1,000.00 is not applied: it waits for an approval.",
            "ORDMNT02:245-257",
        ),
        Rule(
            "BR-004", "The person who requested a cancellation cannot decide it.", "ORDAPR01:77-90"
        ),
        Rule("BR-005", "A rejection needs a reason.", "DOC:order-approval-screens#APR-02"),
        Rule(
            "BR-006",
            "A request is applied only if the order is still as it was when requested.",
            "ASSUMED:OP-001",
        ),
    )
}


class DomainError(Exception):
    """A refusal the user has to be told about: a stable code and a message."""

    def __init__(self, code: str, message: str, rule_id: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.rule_id = rule_id


def normalize_order_id(raw: str) -> str:
    """VAL-001: the stored form of an order id."""
    text = (raw or "").strip()
    if not text.isdigit() or len(text) > ORDER_ID_LENGTH or int(text) == 0:
        raise DomainError(
            "ORDER_ID_INVALID",
            f"An order id is a number of up to {ORDER_ID_LENGTH} digits.",
            "VAL-001",
        )
    return text.zfill(ORDER_ID_LENGTH)


def normalize_reason(raw: str) -> str:
    """VAL-002: the stored form of a reason (single spaces, printable characters)."""
    text = " ".join((raw or "").split())
    if not text or len(text) > REASON_MAX_LENGTH or not text.isprintable():
        raise DomainError(
            "REASON_INVALID",
            f"Give a reason of 1 to {REASON_MAX_LENGTH} characters.",
            "VAL-002",
        )
    return text


def needs_approval(amount_cents: int) -> bool:
    """BR-003."""
    return amount_cents > APPROVAL_THRESHOLD_CENTS
