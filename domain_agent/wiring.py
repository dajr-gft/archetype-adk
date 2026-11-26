"""Composition root: what the agent is connected to. ``agent.py`` calls ``configure()``.

The archetype connects the in-memory store: it serves local runs, the unit tests and the
evaluation. A deployed agent connects the adapter of the system of record here, and only
here. Adapters live in ``domain_agent/adapters/``; they may use any client library, which
the domain may not:

    from .adapters.orders_database import DatabaseOrderStore

    def configure() -> None:
        set_store(DatabaseOrderStore.from_environment())

The deployment preflight (``tools/check_deploy.py``, D06) fails while this file still
connects an in-memory store.
"""

from __future__ import annotations

from .domain.store import InMemoryOrderStore, set_store


def configure() -> None:
    set_store(InMemoryOrderStore())
