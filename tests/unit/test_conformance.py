"""The project passes the conformance gate of the archetype (see archetype.md, Gates)."""

from tools import conformance


def test_the_project_is_conformant() -> None:
    assert conformance.check() == []
