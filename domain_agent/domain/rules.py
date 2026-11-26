"""Business rules of the domain: constants, validations and their catalogue.

Illustrative domain: ``orders`` (invented; a generated agent replaces it).

Every rule has an id, a statement and its source. ``RULES`` is the catalogue: the
conformance gate requires a source for every rule and a unit test that names every rule
id. A source is one of:

    <member>:<line>[-<line>]    the legacy code that states the rule
    DOC:<document>#<anchor>     a document of the legacy system (a screen, a manual)
    ASSUMED:OP-<n>              not stated by any source: an assumption, described as
                                open point OP-<n> in OPEN_POINTS.md

A statement names the constant, not its value: the value is written once, below.
"""

from __future__ import annotations

from .base import DomainError, Rule, as_text

# ── Constants (exact values of the legacy source; never tool parameters) ──────────────
ORDER_ID_LENGTH: int = 6
REASON_MAX_LENGTH: int = 60
CANCELLABLE_STATUSES: frozenset[str] = frozenset({"OPEN", "ON_HOLD"})
APPROVAL_THRESHOLD_CENTS: int = 100_000  # a cancellation above it needs a second person
SEARCH_LIMIT: int = 10
REQUEST_STATUSES: tuple[str, ...] = ("PENDING", "APPROVED", "REJECTED")
ALL_STATUSES: str = "ALL"

RULES: dict[str, Rule] = {
    rule.rule_id: rule
    for rule in (
        Rule(
            "VAL-001",
            "An order id is a number of up to ORDER_ID_LENGTH digits, not zero; shorter "
            "input is zero-filled.",
            "ORDMNT01:98-125",
        ),
        Rule(
            "VAL-002",
            "A reason is 1 to REASON_MAX_LENGTH characters of the character set of the "
            "legacy record (blank to tilde).",
            "ORDMNT02:195-208",
        ),
        Rule(
            "VAL-003",
            "A user id is kept in upper case without surrounding blanks, and user ids are "
            "compared in that form.",
            "ORDSEC01:12-20",
        ),
        Rule(
            "BR-001",
            "Only an order in one of CANCELLABLE_STATUSES can be cancelled.",
            "ORDMNT02:143-150",
        ),
        Rule(
            "BR-002",
            "An order has at most one pending cancellation request.",
            "ORDMNT02:129-137",
        ),
        Rule(
            "BR-003",
            "A cancellation above APPROVAL_THRESHOLD_CENTS is not applied: it waits for "
            "an approval.",
            "ORDMNT02:245-257",
        ),
        Rule(
            "BR-004",
            "The person who requested a cancellation cannot decide it.",
            "ORDAPR01:77-90",
        ),
        Rule("BR-005", "A rejection needs a reason.", "DOC:order-approval-screens#APR-02"),
        Rule(
            "BR-006",
            "A request is applied only if the order is still as it was when requested.",
            "ASSUMED:OP-001",
        ),
        Rule(
            "BR-007",
            "A query made of digits looks an order up by its id; any other query lists "
            "the orders whose customer name contains it, by order id, SEARCH_LIMIT at most.",
            "ORDINQ01:40-58",
        ),
        Rule(
            "BR-008",
            "Requests are listed for one of REQUEST_STATUSES or for all of them, newest first.",
            "ORDAPR01:30-52",
        ),
    )
}


def normalize_order_id(raw: object) -> str:
    """VAL-001: the stored form of an order id."""
    text = as_text(raw, "the order id").strip()
    digits = text.isascii() and text.isdigit()
    if not digits or len(text) > ORDER_ID_LENGTH or int(text) == 0:
        raise DomainError(
            "ORDER_ID_INVALID",
            f"An order id is a number of up to {ORDER_ID_LENGTH} digits.",
            "VAL-001",
        )
    return text.zfill(ORDER_ID_LENGTH)


def normalize_reason(raw: object) -> str:
    """VAL-002: the stored form of a reason (single blanks, legacy character set)."""
    text = " ".join(as_text(raw, "the reason").split())
    legacy_characters = all(" " <= character <= "~" for character in text)
    if not text or len(text) > REASON_MAX_LENGTH or not legacy_characters:
        raise DomainError(
            "REASON_INVALID",
            f"Give a reason of 1 to {REASON_MAX_LENGTH} characters, without accents or symbols "
            "outside the basic set.",
            "VAL-002",
        )
    return text


def normalize_user(raw: object) -> str:
    """VAL-003: the stored form of a user id."""
    text = as_text(raw, "the user id").strip()
    if not text or not text.isascii() or not text.isprintable() or " " in text:
        raise DomainError("USER_UNKNOWN", "The signed-in user is unknown.", "VAL-003")
    return text.upper()


def same_user(stored: str, acting: str) -> bool:
    """VAL-003: whether a stored user id and the acting user are the same person."""
    return stored.strip().upper() == normalize_user(acting)


def normalize_request_id(raw: object) -> int:
    """The number of a request, given as a number or as its digits."""
    if isinstance(raw, int) and not isinstance(raw, bool):
        return raw
    text = raw.strip() if isinstance(raw, str) else ""
    if not (text.isascii() and text.isdigit()):
        raise DomainError("REQUEST_ID_INVALID", "A request is identified by its number.")
    return int(text)


def normalize_request_status(raw: object) -> str | None:
    """BR-008: the status to list, or None for all of them."""
    wanted = as_text(raw, "the status").strip().upper()
    if wanted == ALL_STATUSES:
        return None
    if wanted not in REQUEST_STATUSES:
        raise DomainError(
            "STATUS_INVALID",
            f"The status is one of {', '.join(REQUEST_STATUSES)}, or {ALL_STATUSES}.",
            "BR-008",
        )
    return wanted


def needs_approval(amount_cents: int) -> bool:
    """BR-003."""
    return amount_cents > APPROVAL_THRESHOLD_CENTS


def format_amount(amount_cents: int) -> str:
    """An amount as it is shown: code formats it, the model only repeats it."""
    return f"{amount_cents // 100}.{amount_cents % 100:02d}"
