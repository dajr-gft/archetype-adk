"""Self-test of the archetype: the conformance gate catches each defect it exists for.

Every test breaks a copy of the illustrative ``orders`` domain in one way and expects the
gate to name that check. Most of these defects were produced by code generation, or passed
an earlier version of the gate. The tests are skipped in a project where the generator
replaced the illustrative domain (they belong to the archetype, not to the agent).
"""

import json
import shutil
from pathlib import Path

import pytest

from tools import conformance

pytestmark = pytest.mark.skipif(
    "async def find_order("
    not in (conformance.ROOT / "domain_agent" / "tools.py").read_text("utf-8")
    if (conformance.ROOT / "domain_agent" / "tools.py").is_file()
    else True,
    reason="The illustrative orders domain was replaced: archetype self-tests do not apply.",
)

AGENT, TOOLS, PROMPT = "domain_agent/agent.py", "domain_agent/tools.py", "domain_agent/prompt.py"
RULES, SERVICE, STORE = (f"domain_agent/domain/{name}.py" for name in ("rules", "service", "store"))
EVAL = "tests/eval/orders.test.json"


@pytest.fixture
def copy(tmp_path: Path) -> Path:
    """A copy of the archetype that a test may break."""
    root = tmp_path / "copy"
    for name in ("domain_agent", "tests", "tools"):
        shutil.copytree(
            conformance.ROOT / name, root / name, ignore=shutil.ignore_patterns("__pycache__")
        )
    for name in ("conftest.py", "OPEN_POINTS.md", conformance.OWNED_MANIFEST):
        shutil.copy(conformance.ROOT / name, root / name)
    return root


def edit(root: Path, name: str, old: str, new: str) -> None:
    path = root / name
    text = path.read_text(encoding="utf-8")
    assert old in text, old
    path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")


def append(root: Path, name: str, text: str) -> None:
    path = root / name
    path.write_text(path.read_text(encoding="utf-8") + text, encoding="utf-8", newline="\n")


def ids(root: Path) -> set[str]:
    return {finding.split()[0] for finding in conformance.check(root)}


def findings(root: Path) -> str:
    return "\n".join(conformance.check(root))


def test_the_copy_is_conformant_before_it_is_broken(copy: Path) -> None:
    assert conformance.check(copy) == []


# ── C01 ───────────────────────────────────────────────────────────────────────────────


def test_c01_a_tool_that_is_not_registered(copy: Path) -> None:
    edit(copy, AGENT, "        find_order,\n", "")
    assert ids(copy) == {"C01"}


def test_c01_a_tool_that_does_not_exist(copy: Path) -> None:
    edit(copy, TOOLS, "async def find_order(", "async def search_order(")
    assert ids(copy) == {"C01", "C09"}  # the evaluation set names it too


def test_c01_a_tool_wrapped_for_confirmation_is_registered(copy: Path) -> None:
    edit(copy, AGENT, "        find_order,\n", "        FunctionTool(find_order),\n")
    assert conformance.check(copy) == []


# ── C02 ───────────────────────────────────────────────────────────────────────────────


def test_c02_print_exit_and_processes(copy: Path) -> None:
    edit(
        copy,
        SERVICE,
        "    reader = normalize_user(user)\n",
        "    print(user)\n    reader = normalize_user(user)\n",
    )
    append(
        copy,
        SERVICE,
        "\n\nimport subprocess\nimport sys\n\n\ndef _leave() -> None:\n    sys.exit(1)\n",
    )
    assert ids(copy) == {"C02"} and len(conformance.check(copy)) == 3


# ── C03 ───────────────────────────────────────────────────────────────────────────────


def test_c03_a_synchronous_tool(copy: Path) -> None:
    edit(copy, TOOLS, "async def find_order(", "def find_order(")
    edit(copy, TOOLS, "    return await toolkit.read(tool_context, lambda user: service.find_orders(query))",
         "    return toolkit.read(tool_context, lambda user: service.find_orders(query))")  # fmt: skip
    assert "tool find_order is not a coroutine" in findings(copy)


@pytest.mark.parametrize(
    "annotation",
    [
        "Decimal",
        "float",
        "date",
        "list[dict[str, Any]]",
        "dict[str, str]",
        "str | None",
        "tuple[str, ...]",
    ],
)
def test_c03_a_parameter_that_does_not_cross_the_tool_boundary(copy: Path, annotation: str) -> None:
    edit(
        copy,
        TOOLS,
        "async def find_order(query: str,",
        f"async def find_order(query: {annotation},",
    )
    assert ids(copy) == {"C03"}


def test_c03_keys_as_a_list_are_fine(copy: Path) -> None:
    edit(copy, TOOLS, "async def find_order(query: str,", "async def find_order(query: list[str],")
    assert conformance.check(copy) == []


def test_c03_a_default_value_and_a_missing_docstring(copy: Path) -> None:
    edit(
        copy,
        TOOLS,
        "async def list_cancellation_requests(status: str, tool_context: ToolContext)",
        'async def list_cancellation_requests(tool_context: ToolContext, status: str = "PENDING")',
    )
    text = findings(copy)
    assert "default value" in text and "last parameter is not tool_context" in text


# ── C04 ───────────────────────────────────────────────────────────────────────────────


def test_c04_the_domain_imports_neither_adk_nor_the_agent_layer(copy: Path) -> None:
    append(copy, SERVICE, "\n\nfrom google.adk.tools.tool_context import ToolContext  # noqa\n")
    append(copy, RULES, "\n\nfrom .. import tools  # noqa\n")
    assert ids(copy) == {"C04"} and len(conformance.check(copy)) == 2


# ── C05 ───────────────────────────────────────────────────────────────────────────────


def test_c05_a_text_passed_as_instruction(copy: Path) -> None:
    """ADK substitutes braces there: {orderId} or {{orderId}} stops the agent on turn one."""
    edit(copy, AGENT, "static_instruction=DOMAIN_INSTRUCTION", "instruction=DOMAIN_INSTRUCTION")
    assert ids(copy) == {"C05"}


def test_c05_a_function_as_instruction_is_fine(copy: Path) -> None:
    append(
        copy,
        PROMPT,
        "\n\ndef instruction(context: object) -> str:\n    return DOMAIN_INSTRUCTION\n",
    )
    edit(copy, AGENT, "from .prompt import DOMAIN_INSTRUCTION", "from .prompt import instruction")
    edit(copy, AGENT, "static_instruction=DOMAIN_INSTRUCTION", "instruction=instruction")
    assert conformance.check(copy) == []


# ── C06 ───────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ('DEFAULT_MODEL = "gemini-3.8-flash"', 'DEFAULT_MODEL = "gemini-flash-latest"'),
        ("    model=MODEL,", '    model="gemini-3.8-flash",'),
        ("    temperature=TEMPERATURE,", "    temperature=0.7,"),
        (
            'os.environ.get("AGENT_TEMPERATURE", "0.0")',
            'os.environ.get("AGENT_TEMPERATURE", "0.7")',
        ),
        ("    generate_content_config=GENERATION,\n", ""),
        ("plugins=[AuditPlugin()]", "plugins=[]"),
        ('App(name="domain_agent"', 'App(name="orders"'),
        ("root_agent = Agent(", "agent = Agent("),
        (
            "    static_instruction=DOMAIN_INSTRUCTION,",
            '    static_instruction=DOMAIN_INSTRUCTION,\n    global_instruction="x",',
        ),
        (
            "    static_instruction=DOMAIN_INSTRUCTION,",
            '    static_instruction=DOMAIN_INSTRUCTION,\n    mode="task",',
        ),
    ],
)
def test_c06_the_configuration_of_the_agent(copy: Path, old: str, new: str) -> None:
    edit(copy, AGENT, old, new)
    if "agent = Agent(" in new:
        edit(copy, AGENT, "root_agent=root_agent", "root_agent=agent")
    assert ids(copy) == {"C06"}


def test_c06_an_agent_reached_through_agent_tool(copy: Path) -> None:
    append(
        copy,
        AGENT,
        "\ncoordinator = Agent(name='c', model=MODEL, generate_content_config=GENERATION, tools=[AgentTool(root_agent)])\n",
    )
    assert "AgentTool" in findings(copy)


# ── C07 ───────────────────────────────────────────────────────────────────────────────


def test_c07_a_rule_without_a_source_or_without_a_test(copy: Path) -> None:
    edit(copy, RULES, '"ORDAPR01:77-90"', '"see the legacy code"')
    untested = "BR-" + "9" * 3  # built here so that this file does not name it
    edit(copy, RULES, 'Rule("BR-005"', f'Rule("{untested}"')
    append(copy, "tests/unit/test_rules.py", f"\n# {untested} is only named in a comment\n")
    assert ids(copy) == {"C07"} and len(conformance.check(copy)) == 2


@pytest.mark.parametrize(
    "source",
    [
        "src/main/java/com/acme/OrderApprovalService.java:77-90",
        "ordapr01.cbl:77-90,120-131",
        "ORDAPR01:77",
    ],
)
def test_c07_sources_of_any_legacy_technology_are_accepted(copy: Path, source: str) -> None:
    edit(copy, RULES, '"ORDAPR01:77-90"', f'"{source}"')
    assert conformance.check(copy) == []


def test_c07_a_rule_whose_source_is_not_a_literal(copy: Path) -> None:
    edit(copy, RULES, '"ORDAPR01:77-90"', "SOURCE")
    assert ids(copy) == {"C07"}


def test_c07_an_assumption_has_to_be_an_open_point(copy: Path) -> None:
    edit(copy, "OPEN_POINTS.md", "| OP-001 |", "| OP-002 |")
    assert ids(copy) == {"C07"} and "OPEN_POINTS.md" in findings(copy)


# ── C08 ───────────────────────────────────────────────────────────────────────────────


def test_c08_a_number_in_a_tool_and_a_float_in_a_record(copy: Path) -> None:
    edit(copy, TOOLS, "    return await toolkit.read(tool_context, lambda user: service.find_orders(query))",
         "    limit = 100000\n    return await toolkit.read(tool_context, lambda user: service.find_orders(query))")  # fmt: skip
    edit(copy, STORE, "    amount_cents: int\n", "    amount_cents: float\n")
    assert ids(copy) == {"C08"} and len(conformance.check(copy)) == 2


# ── C09 ───────────────────────────────────────────────────────────────────────────────


def cases(root: Path, keep: set[str]) -> None:
    path = root / EVAL
    data = json.loads(path.read_text(encoding="utf-8"))
    data["eval_cases"] = [case for case in data["eval_cases"] if case["eval_id"] in keep]
    path.write_text(json.dumps(data), encoding="utf-8")


ALL_CASES = {
    "lookup_by_id", "cancel_after_confirmation", "nothing_is_written_when_the_user_declines",
    "a_second_person_approves", "a_second_person_rejects_with_a_reason", "not_available_here",
}  # fmt: skip


@pytest.mark.parametrize(
    ("dropped", "missing"),
    [
        ("lookup_by_id", "no evaluation case calls the tool find_order"),
        ("cancel_after_confirmation", "confirms a write"),
        ("nothing_is_written_when_the_user_declines", "declines a write"),
        ("not_available_here", "something no tool does"),
    ],
)
def test_c09_the_conversations_every_agent_has_to_pass(
    copy: Path, dropped: str, missing: str
) -> None:
    cases(copy, ALL_CASES - {dropped})
    assert ids(copy) == {"C09"} and missing in findings(copy)


def test_c09_an_unknown_tool_the_legacy_format_and_broken_json(copy: Path) -> None:
    edit(copy, EVAL, '"name": "find_order"', '"name": "search_order"')
    assert "unknown tool search_order" in findings(copy)
    (copy / EVAL).write_text('[{"query": "hi", "expected_tool_use": []}]', encoding="utf-8")
    assert "is not an EvalSet" in findings(copy)
    (copy / EVAL).write_text("{not json", encoding="utf-8")
    assert "is not JSON" in findings(copy)


# ── C10, C11 ──────────────────────────────────────────────────────────────────────────


def test_c10_a_tool_that_reads_the_context_itself(copy: Path) -> None:
    edit(copy, TOOLS, "    return await toolkit.read(tool_context, lambda user: service.find_orders(query))",
         "    who = tool_context.user_id\n    tool_context.state['x'] = who\n"
         "    return await toolkit.read(tool_context, lambda user: service.find_orders(query))")  # fmt: skip
    assert ids(copy) == {"C10"} and len(conformance.check(copy)) == 2


def test_c10_a_tool_that_calls_the_domain_without_the_toolkit(copy: Path) -> None:
    edit(copy, TOOLS, "    return await toolkit.read(tool_context, lambda user: service.find_orders(query))",
         "    return {'status': 'success', 'result': service.find_orders(query)}")  # fmt: skip
    assert ids(copy) == {"C10"}


DIRECT_WRITE = '''

async def cancel_order_now(order_id: str, reason: str, tool_context: ToolContext) -> dict[str, Any]:
    """Cancels an order at once.

    Args:
        order_id: The order.
        reason: The reason.
    """
    return await toolkit.read(
        tool_context, lambda user: service.cancel_order(order_id, reason, user, None)
    )
'''


def test_c11_a_tool_that_writes_without_a_confirmation(copy: Path) -> None:
    append(copy, TOOLS, DIRECT_WRITE)
    assert "service.cancel_order from toolkit.read" in findings(copy)


def test_c11_a_submit_that_takes_what_it_writes_from_the_model(copy: Path) -> None:
    edit(copy, TOOLS, "async def submit_order_cancellation(tool_context: ToolContext)",
         "async def submit_order_cancellation(order_id: str, tool_context: ToolContext)")  # fmt: skip
    assert "takes parameters from the model" in findings(copy)


@pytest.mark.parametrize("argument", ['"boss"', "aprovador", "str(request_id)"])
def test_c11_the_user_is_the_one_the_toolkit_gives(copy: Path, argument: str) -> None:
    edit(copy, TOOLS, "service.approve_request(request_id, user, confirmation)",
         f"service.approve_request(request_id, {argument}, confirmation)")  # fmt: skip
    assert "as the user of service.approve_request" in findings(copy)


def test_c11_a_use_case_that_writes_without_confirmation_or_without_recording(copy: Path) -> None:
    append(copy, SERVICE, "\n\ndef force_cancel(order_id: str) -> None:\n"
           "    store = get_store()\n    store.save_order(replace(_order(store, order_id), status='CANCELLED'))\n")  # fmt: skip
    edit(copy, SERVICE, "        authorize(store, confirmation, shown)\n", "")
    text = findings(copy)
    assert "force_cancel changes the store without a confirmation" in text
    assert "cancel_order does not call authorize" in text


def test_c11_a_submit_without_its_prepare(copy: Path) -> None:
    edit(copy, TOOLS, '        tool_context,\n        "cancel_order",\n        lambda user, shown, confirmation',
         '        tool_context,\n        "cancel_order_now",\n        lambda user, shown, confirmation')  # fmt: skip
    assert "has no tool that calls toolkit.prepare" in findings(copy)


# ── C12 ───────────────────────────────────────────────────────────────────────────────


def test_c12_a_file_of_the_archetype_was_changed(copy: Path) -> None:
    append(copy, "domain_agent/toolkit.py", "\nUSE_CASE_TIMEOUT_SECONDS = 3600.0\n")
    edit(copy, "tests/eval/test_config.json", "1.0", "0.5")
    assert ids(copy) == {"C12"} and len(conformance.check(copy)) == 2


def test_c12_line_ends_do_not_count(copy: Path) -> None:
    path = copy / "domain_agent/toolkit.py"
    path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    assert conformance.check(copy) == []


# ── the pipeline profile ──────────────────────────────────────────────────────────────


def test_the_pipeline_example_passes_its_profile() -> None:
    assert conformance.check(conformance.ROOT, "examples/pipeline_agent", "tests/archetype") == []
