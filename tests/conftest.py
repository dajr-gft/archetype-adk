"""Archetype-owned. A fresh in-memory store for each test, whatever the domain."""

from typing import Any

import pytest

from domain_agent.domain import store


@pytest.fixture(autouse=True)
def fresh_store() -> Any:
    """The store of this test: ``in_memory_store()`` of the domain, with its seed data."""
    fresh = store.in_memory_store()
    store.set_store(fresh)
    return fresh
