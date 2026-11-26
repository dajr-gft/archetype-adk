"""A fresh store for each test, and the part of an ADK ToolContext the tools use."""

from itertools import count
from types import SimpleNamespace

import pytest

from domain_agent.domain import store

_turns = count(1)


@pytest.fixture(autouse=True)
def fresh_store() -> store.InMemoryOrderStore:
    fresh = store.InMemoryOrderStore()
    store.set_store(fresh)
    return fresh


def session(user: str) -> SimpleNamespace:
    """A signed-in user, an empty session state and the first turn of a conversation."""
    return SimpleNamespace(user_id=user, state={}, invocation_id=f"turn-{next(_turns)}")


def next_turn(context: SimpleNamespace) -> SimpleNamespace:
    """The user answered: the same session, a new invocation."""
    context.invocation_id = f"turn-{next(_turns)}"
    return context
