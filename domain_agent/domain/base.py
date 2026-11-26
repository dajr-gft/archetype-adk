"""Archetype-owned. The types every domain shares, and what makes a write safe.

A write reaches the system of record through a use case that takes a ``Confirmation``:
the key of one confirmation given by the user, and the fingerprint of what the user was
shown. Inside its transaction the use case calls ``authorize`` with what it would show
now, and ``record`` once it has written. So a write

- is the one the user was shown (``CHANGED_SINCE_SHOWN`` otherwise), and
- happens at most once per confirmation (``ALREADY_SUBMITTED`` otherwise), and
- leaves a record of who did what, in the same transaction as the data.

Do not change this file in a generated agent.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class Rule:
    """One business rule and where it comes from (see ``rules.py``)."""

    rule_id: str
    statement: str
    source: str


class DomainError(Exception):
    """A refusal the user has to be told about: a stable code and a message.

    ``rule_id`` names the business rule that refused. A refusal that enforces no business
    rule (missing input, an unknown key, nothing found) has none.
    """

    def __init__(self, code: str, message: str, rule_id: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.rule_id = rule_id


def utc_now() -> str:
    """The time of a record, in UTC, as text."""
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def fingerprint(shown: Mapping[str, Any]) -> str:
    """A stable digest of what a preview returned.

    Raises ``TypeError`` for a value that JSON cannot carry (a ``Decimal``, a date): what
    is shown crosses to the model and to the session as JSON, so a preview returns text,
    integers, booleans, lists and dictionaries of them only.
    """
    text = json.dumps(shown, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(text.encode("ascii")).hexdigest()


@dataclass(frozen=True)
class Confirmation:
    """One confirmation of the user: its key and the fingerprint of what was shown."""

    key: str
    shown: str

    @classmethod
    def of(cls, shown: Mapping[str, Any]) -> Confirmation:
        """A new confirmation of what a preview returned (tests, callers without an agent)."""
        return cls(uuid.uuid4().hex, fingerprint(shown))


@dataclass(frozen=True)
class WriteRecord:
    """What a confirmed write did: kept by the store, in the transaction of the write."""

    key: str  # the confirmation that authorised it
    operation: str
    target: str  # the business key that was written
    user: str
    at: str


class WriteJournal(Protocol):
    """The part of every storage port that makes a write happen once."""

    def find_write(self, key: str) -> WriteRecord | None: ...

    def add_write(self, record: WriteRecord) -> None:
        """Stores the record; raises if the key exists (a unique key in a database)."""
        ...


def authorize(
    journal: WriteJournal, confirmation: Confirmation, shown_now: Mapping[str, Any]
) -> None:
    """Refuses a write that was already made, or whose preview no longer holds.

    Call it inside the transaction of the write, after the validations and before the
    first change, with what the preview would return now.
    """
    if journal.find_write(confirmation.key) is not None:
        raise DomainError(
            "ALREADY_SUBMITTED",
            "This was already submitted. Look at the current state before trying again.",
        )
    if fingerprint(shown_now) != confirmation.shown:
        raise DomainError(
            "CHANGED_SINCE_SHOWN",
            "What you were shown has changed since. Look at it again before confirming.",
        )


def record(
    journal: WriteJournal, confirmation: Confirmation, *, operation: str, target: str, user: str
) -> None:
    """Records a write that was made. Call it last inside the transaction of the write."""
    journal.add_write(WriteRecord(confirmation.key, operation, target, user, utc_now()))


def as_text(raw: object, what: str) -> str:
    """The text a caller gave, or a refusal: a model may send a number for a text value."""
    if not isinstance(raw, str):
        raise DomainError("INPUT_INVALID", f"Give {what} as text.")
    return raw
