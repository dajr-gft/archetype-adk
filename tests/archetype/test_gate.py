"""Self-test of the archetype: the conformance gate catches each defect it exists for.

Every test breaks a copy of the illustrative ``orders`` domain in one way and expects the
gate to name exactly that check. The tests are skipped in a project where the generator
replaced the illustrative domain (they belong to the archetype, not to the agent).
"""

import shutil
from pathlib import Path

import pytest

from tools import conformance

pytestmark = pytest.mark.skipif(
    "def find_order(" not in (conformance.PACKAGE / "tools.py").read_text(encoding="utf-8"),
    reason="The illustrative orders domain was replaced: archetype self-tests do not apply.",
)


@pytest.fixture
def copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A copy of the archetype that a test may break."""
    root = tmp_path / "copy"
    for name in ("domain_agent", "tests"):
        shutil.copytree(
            conformance.ROOT / name, root / name, ignore=shutil.ignore_patterns("__pycache__")
        )
    shutil.copy(conformance.ROOT / "OPEN_POINTS.md", root / "OPEN_POINTS.md")
    monkeypatch.setattr(conformance, "ROOT", root)
    monkeypatch.setattr(conformance, "PACKAGE", root / "domain_agent")
    return root


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text, old
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def ids(findings: list[str]) -> set[str]:
    return {finding.split()[0] for finding in findings}


def test_the_copy_is_conformant_before_it_is_broken(copy: Path) -> None:
    assert conformance.check() == []


def test_c01_a_tool_that_is_not_registered(copy: Path) -> None:
    edit(copy / "domain_agent/agent.py", "        find_order,\n        prepare", "        prepare")
    assert ids(conformance.check()) == {"C01"}


def test_c01_a_tool_that_does_not_exist(copy: Path) -> None:
    edit(copy / "domain_agent/tools.py", "def find_order(", "def search_order(")
    assert ids(conformance.check()) == {"C01", "C09"}  # the evaluation set names it too


def test_c02_print_and_exit(copy: Path) -> None:
    edit(
        copy / "domain_agent/tools.py",
        "    draft = tool_context.state.get(DRAFT)",
        "    print('x')\n    draft = tool_context.state.get(DRAFT)",
    )
    edit(
        copy / "domain_agent/domain/service.py",
        '    text = (query or "").strip()',
        '    import sys\n    sys.exit(1)\n    text = (query or "").strip()',
    )
    findings = conformance.check()
    assert ids(findings) == {"C02"} and len(findings) == 2


def test_c03_the_model_must_not_say_who_the_user_is(copy: Path) -> None:
    edit(
        copy / "domain_agent/tools.py",
        "def find_order(query: str, tool_context",
        "def find_order(query: str, approver: str, tool_context",
    )
    findings = conformance.check()
    assert ids(findings) == {"C03"}
    assert any("who the user is" in finding for finding in findings)


def test_c03_a_tool_that_takes_records_or_a_default(copy: Path) -> None:
    edit(
        copy / "domain_agent/tools.py",
        "def find_order(query: str, tool_context",
        "def find_order(query: str, orders: list[dict[str, Any]], tool_context",
    )
    edit(
        copy / "domain_agent/tools.py",
        "def list_cancellation_requests(status: str, tool_context: ToolContext)",
        'def list_cancellation_requests(tool_context: ToolContext, status: str = "PENDING")',
    )
    findings = "\n".join(conformance.check())
    assert "takes scalars and keys" in findings and "default value" in findings


def test_c04_the_domain_does_not_import_adk(copy: Path) -> None:
    edit(
        copy / "domain_agent/domain/service.py",
        "from dataclasses",
        "from google.adk.tools import ToolContext\nfrom dataclasses",
    )
    assert ids(conformance.check()) == {"C04"}


def test_c05_an_unescaped_brace_in_the_instruction(copy: Path) -> None:
    edit(copy / "domain_agent/prompt.py", "How you talk", "Example: {orderId}\nHow you talk")
    assert ids(conformance.check()) == {"C05"}


def test_c05_an_escaped_brace_and_a_declared_state_key_are_fine(copy: Path) -> None:
    edit(copy / "domain_agent/prompt.py", "How you talk", 'Example: {{"orderId": 1}}\nHow you talk')
    edit(copy / "domain_agent/prompt.py", "How you act", "Branch: {branch}\nHow you act")
    edit(copy / "domain_agent/prompt.py", "frozenset()", 'frozenset({"branch"})')
    assert conformance.check() == []


def test_c06_a_model_alias_or_preview(copy: Path) -> None:
    edit(
        copy / "domain_agent/agent.py",
        'DEFAULT_MODEL = "gemini-3.8-flash"',
        'DEFAULT_MODEL = "gemini-flash-latest"',
    )
    assert ids(conformance.check()) == {"C06"}


def test_c06_the_app_is_named_after_the_package(copy: Path) -> None:
    edit(copy / "domain_agent/agent.py", 'App(name="domain_agent"', 'App(name="orders"')
    assert ids(conformance.check()) == {"C06"}


def test_c07_a_rule_without_a_source_or_without_a_test(copy: Path) -> None:
    edit(copy / "domain_agent/domain/rules.py", '"ORDAPR01:77-90"', '"see the legacy code"')
    untested = "BR-" + "9" * 3  # built here so that this file does not name it
    edit(copy / "domain_agent/domain/rules.py", 'Rule("BR-005"', f'Rule("{untested}"')
    findings = conformance.check()
    assert ids(findings) == {"C07"} and len(findings) == 2


def test_c07_an_assumption_has_to_be_an_open_point(copy: Path) -> None:
    edit(copy / "OPEN_POINTS.md", "| OP-001 |", "| OP-002 |")
    findings = conformance.check()
    assert ids(findings) == {"C07"} and "OPEN_POINTS.md" in findings[0]


def test_c08_a_business_value_outside_the_domain(copy: Path) -> None:
    edit(
        copy / "domain_agent/tools.py",
        'DRAFT = "cancellation_draft"',
        'DRAFT = "cancellation_draft"\nLIMIT = 100000',
    )
    assert ids(conformance.check()) == {"C08"}


def test_c09_an_evaluation_case_that_names_an_unknown_tool(copy: Path) -> None:
    path = next((copy / "tests/eval").glob("*.test.json"))
    edit(path, '"name": "find_order"', '"name": "search_order"')
    assert ids(conformance.check()) == {"C09"}


def test_c09_the_legacy_evaluation_format(copy: Path) -> None:
    path = next((copy / "tests/eval").glob("*.test.json"))
    path.write_text('[{"query": "hi", "expected_tool_use": []}]', encoding="utf-8")
    assert ids(conformance.check()) == {"C09"}
