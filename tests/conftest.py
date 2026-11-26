"""A fresh store for each test (adapt the store class to the domain)."""

import pytest

from domain_agent.domain import store


@pytest.fixture(autouse=True)
def fresh_store() -> store.InMemoryOrderStore:
    fresh = store.InMemoryOrderStore()
    store.set_store(fresh)
    return fresh
