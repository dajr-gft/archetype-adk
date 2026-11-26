"""Conformance gate of the archetype: the rules of archetype.md that a machine can check.

    python tools/conformance.py            # exit code 1 and one line per finding

It reads the source (no import of the agent, no model call), so it also runs on code that
does not import yet. Each check has an id (C01...) that archetype.md cites.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "domain_agent"

IDENTITY_PARAMETERS = {
    "user", "user_id", "userid", "username", "acting_user", "requester", "requested_by",
    "approver", "approved_by", "operator", "employee_id",
}  # fmt: skip
FORBIDDEN_CALLS = {"print", "exit", "quit", "input", "breakpoint"}
FORBIDDEN_ATTRIBUTES = {("sys", "exit"), ("os", "_exit"), ("os", "system"), ("os", "abort")}
UNSTABLE_MODEL = re.compile(r"preview|latest|exp\b|experimental", re.IGNORECASE)
SOURCE_CODE = re.compile(r"^[A-Z0-9#@$_.\-/]+:\d+(-\d+)?$")
SOURCE_DOCUMENT = re.compile(r"^DOC:[A-Za-z0-9_.\-/ ]+#[A-Za-z0-9_.\-]+$")
SOURCE_ASSUMED = re.compile(r"^ASSUMED:(OP-\d+)$")
TEMPLATE = re.compile(r"(?<!\{)\{([A-Za-z_][A-Za-z0-9_:.?]*)\}(?!\})")


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _public_functions(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and not node.name.startswith("_")
    ]


def _string_constants(tree: ast.Module) -> dict[str, str]:
    found: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            if isinstance(node.value.value, str):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        found[target.id] = node.value.value
    return found


def _name_set(tree: ast.Module, name: str) -> set[str] | None:
    """The string elements of ``name = frozenset({...})`` / ``{...}`` / ``frozenset()``."""
    for node in tree.body:
        value = node.value if isinstance(node, ast.Assign | ast.AnnAssign) else None
        targets = (
            node.targets
            if isinstance(node, ast.Assign)
            else [node.target]
            if isinstance(node, ast.AnnAssign)
            else []
        )
        if value is None or not any(isinstance(t, ast.Name) and t.id == name for t in targets):
            continue
        if isinstance(value, ast.Call) and value.args:
            value = value.args[0]
        elif isinstance(value, ast.Call):
            return set()
        if isinstance(value, ast.Set | ast.List | ast.Tuple):
            return {str(e.value) for e in value.elts if isinstance(e, ast.Constant)}
    return None


def check_tools_contract(findings: list[str]) -> set[str]:
    """C01: agent.py imports and registers exactly the public functions of tools.py."""
    defined = {f.name for f in _public_functions(_tree(PACKAGE / "tools.py"))}
    agent = _tree(PACKAGE / "agent.py")
    imported: set[str] = set()
    registered: set[str] = set()
    for node in ast.walk(agent):
        if isinstance(node, ast.ImportFrom) and node.module == "tools" and node.level == 1:
            imported |= {alias.name for alias in node.names}
        if isinstance(node, ast.keyword) and node.arg == "tools":
            if isinstance(node.value, ast.List):
                registered |= {e.id for e in node.value.elts if isinstance(e, ast.Name)}
    for label, names in (("imported in agent.py", imported), ("in tools=[...]", registered)):
        for name in sorted(defined - names):
            findings.append(f"C01 tool {name} is defined in tools.py but not {label}")
        for name in sorted(names - defined):
            findings.append(f"C01 {name} is {label} but tools.py does not define it")
    return defined


def check_no_process_calls(findings: list[str]) -> None:
    """C02: no print, exit, input or process calls anywhere in the package."""
    for path in sorted(PACKAGE.rglob("*.py")):
        for node in ast.walk(_tree(path)):
            where = f"{path.relative_to(ROOT).as_posix()}:{getattr(node, 'lineno', 0)}"
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in FORBIDDEN_CALLS:
                    findings.append(f"C02 {where} calls {node.func.id}()")
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                if (node.value.id, node.attr) in FORBIDDEN_ATTRIBUTES:
                    findings.append(f"C02 {where} uses {node.value.id}.{node.attr}")
            if isinstance(node, ast.Raise) and node.exc is not None:
                if "SystemExit" in ast.unparse(node.exc):
                    findings.append(f"C02 {where} raises SystemExit")


def check_tool_signatures(findings: list[str]) -> None:
    """C03: typed parameters without defaults, the session as source of identity."""
    for function in _public_functions(_tree(PACKAGE / "tools.py")):
        name = function.name
        arguments = function.args
        docstring = ast.get_docstring(function) or ""
        parameters = arguments.posonlyargs + arguments.args + arguments.kwonlyargs
        model_parameters = [p for p in parameters if p.arg != "tool_context"]
        if arguments.defaults or any(d is not None for d in arguments.kw_defaults):
            findings.append(f"C03 tool {name} has a parameter with a default value")
        if arguments.vararg or arguments.kwarg:
            findings.append(f"C03 tool {name} takes *args or **kwargs")
        if not docstring:
            findings.append(f"C03 tool {name} has no docstring")
        if "tool_context" in docstring:
            findings.append(f"C03 the docstring of tool {name} mentions tool_context")
        if model_parameters and "Args:" not in docstring:
            findings.append(f"C03 the docstring of tool {name} has no Args: section")
        returns = ast.unparse(function.returns) if function.returns else ""
        if not returns.startswith("dict"):
            findings.append(f"C03 tool {name} does not declare a dict return type")
        for parameter in parameters:
            annotation = ast.unparse(parameter.annotation) if parameter.annotation else ""
            if not annotation:
                findings.append(f"C03 tool {name}: parameter {parameter.arg} has no type")
            if parameter.arg.lower() in IDENTITY_PARAMETERS:
                findings.append(
                    f"C03 tool {name}: parameter {parameter.arg} lets the model say who the "
                    "user is; take it from tool_context.user_id"
                )
            if parameter.arg != "tool_context" and re.search(r"\b(list|dict|Any)\b", annotation):
                findings.append(
                    f"C03 tool {name}: parameter {parameter.arg} is {annotation}; a tool "
                    "takes scalars and keys, and reads records itself"
                )
            if (
                parameter.arg not in ("tool_context",)
                and parameter.arg in docstring.split("Args:")[0].split()
            ):
                continue
        for parameter in model_parameters:
            if "Args:" in docstring and f"{parameter.arg}:" not in docstring.split("Args:")[1]:
                findings.append(f"C03 tool {name}: parameter {parameter.arg} is not documented")


def check_domain_purity(findings: list[str]) -> None:
    """C04: the domain imports neither ADK nor a model SDK."""
    for path in sorted((PACKAGE / "domain").rglob("*.py")):
        for node in ast.walk(_tree(path)):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                modules = [node.module]
            for module in modules:
                if module.split(".")[0] in {"google", "vertexai", "litellm", "openai", "anthropic"}:
                    findings.append(
                        f"C04 {path.relative_to(ROOT).as_posix()}:{getattr(node, 'lineno', 0)} "
                        f"imports {module}"
                    )


def check_instruction_templates(findings: list[str]) -> None:
    """C05: a single-brace {name} in an instruction is a declared session state key."""
    tree = _tree(PACKAGE / "prompt.py")
    declared = _name_set(tree, "STATE_KEYS")
    if declared is None:
        findings.append("C05 prompt.py does not declare STATE_KEYS")
        declared = set()
    for constant, text in _string_constants(tree).items():
        for match in TEMPLATE.finditer(text):
            key = match.group(1).rstrip("?").removeprefix("artifact.")
            if key not in declared:
                findings.append(
                    f"C05 prompt.py {constant}: {{{match.group(1)}}} is not in STATE_KEYS; "
                    "double the braces of a literal, or declare the state key"
                )


def check_agent_configuration(findings: list[str]) -> None:
    """C06: model from configuration, temperature 0, App named after the package."""
    tree = _tree(PACKAGE / "agent.py")
    source = (PACKAGE / "agent.py").read_text(encoding="utf-8")
    default = _string_constants(tree).get("DEFAULT_MODEL")
    if not default:
        findings.append("C06 agent.py does not define DEFAULT_MODEL as a string literal")
    elif UNSTABLE_MODEL.search(default) or len(default) < 8:
        findings.append(f"C06 DEFAULT_MODEL {default!r} is an alias, a preview or truncated")
    if "AGENT_MODEL" not in source:
        findings.append("C06 agent.py does not read the model from AGENT_MODEL")
    if not re.search(r"temperature\s*=\s*0(\.0)?\b", source):
        findings.append("C06 agent.py does not set temperature=0.0")
    app_names = [
        keyword.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and ast.unparse(node.func) == "App"
        for keyword in node.keywords
        if keyword.arg == "name" and isinstance(keyword.value, ast.Constant)
    ]
    if app_names != [PACKAGE.name]:
        findings.append(f"C06 agent.py must define one App(name={PACKAGE.name!r}, ...)")
    if not any(isinstance(n, ast.Assign | ast.AnnAssign) and "root_agent" in ast.unparse(n)
               for n in tree.body):  # fmt: skip
        findings.append("C06 agent.py does not define root_agent")


def check_rule_catalogue(findings: list[str]) -> None:
    """C07: every rule says where it comes from and is named by a unit test.

    A source is legacy code (``<member>:<line>[-<line>]``), a document of the legacy
    system (``DOC:<document>#<anchor>``) or a declared assumption
    (``ASSUMED:OP-<n>``, with OP-<n> described in OPEN_POINTS.md).
    """
    tree = _tree(PACKAGE / "domain" / "rules.py")
    rules: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and ast.unparse(node.func) == "Rule":
            values = [a.value for a in node.args if isinstance(a, ast.Constant)]
            values += [k.value.value for k in node.keywords if isinstance(k.value, ast.Constant)]
            if len(values) >= 3:
                rules[str(values[0])] = str(values[-1])
    if not rules:
        findings.append("C07 domain/rules.py declares no Rule in RULES")
    tests = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted((ROOT / "tests" / "unit").glob("*.py"))
    )
    points = ROOT / "OPEN_POINTS.md"
    open_points = points.read_text(encoding="utf-8") if points.is_file() else ""
    for rule_id, source in sorted(rules.items()):
        assumed = SOURCE_ASSUMED.match(source)
        if assumed and not re.search(rf"\b{assumed.group(1)}\b", open_points):
            findings.append(
                f"C07 rule {rule_id} is assumed, but {assumed.group(1)} is not described "
                "in OPEN_POINTS.md"
            )
        if not (assumed or SOURCE_CODE.match(source) or SOURCE_DOCUMENT.match(source)):
            findings.append(
                f"C07 rule {rule_id}: source {source!r} is not '<member>:<line>[-<line>]', "
                "'DOC:<document>#<anchor>' or 'ASSUMED:OP-<n>'"
            )
        if not re.search(rf"(?<![A-Z0-9-]){re.escape(rule_id)}(?![0-9])", tests):
            findings.append(f"C07 rule {rule_id} is not named by any test in tests/unit")


def check_no_business_values_outside_domain(findings: list[str]) -> None:
    """C08: numbers and code sets are constants of domain/rules.py only."""
    for name in ("tools.py", "prompt.py", "agent.py"):
        for node in _tree(PACKAGE / name).body:
            if not isinstance(node, ast.Assign | ast.AnnAssign) or node.value is None:
                continue
            literal = node.value.value if isinstance(node.value, ast.Constant) else None
            if isinstance(literal, int | float) and not isinstance(literal, bool):
                findings.append(
                    f"C08 {name}:{node.lineno} defines a numeric constant; business values "
                    "belong in domain/rules.py"
                )


def check_evaluation_set(findings: list[str], tools: set[str]) -> None:
    """C09: an evaluation set in the ADK EvalSet schema that only names real tools."""
    files = sorted((ROOT / "tests" / "eval").glob("*.test.json"))
    if not files:
        findings.append("C09 tests/eval has no *.test.json evaluation set")
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        cases = data.get("eval_cases") if isinstance(data, dict) else None
        if not cases:
            findings.append(f"C09 {path.name} is not an EvalSet (eval_cases[])")
            continue
        for case in cases:
            for turn in case.get("conversation") or []:
                if "user_content" not in turn:
                    findings.append(
                        f"C09 {path.name} {case.get('eval_id')}: turn without user_content"
                    )
                for use in (turn.get("intermediate_data") or {}).get("tool_uses") or []:
                    if use.get("name") not in tools:
                        findings.append(
                            f"C09 {path.name} {case.get('eval_id')}: unknown tool {use.get('name')}"
                        )
            if not case.get("conversation"):
                findings.append(f"C09 {path.name} {case.get('eval_id')}: no conversation[]")


def check() -> list[str]:
    findings: list[str] = []
    tools = check_tools_contract(findings)
    check_no_process_calls(findings)
    check_tool_signatures(findings)
    check_domain_purity(findings)
    check_instruction_templates(findings)
    check_agent_configuration(findings)
    check_rule_catalogue(findings)
    check_no_business_values_outside_domain(findings)
    check_evaluation_set(findings, tools)
    return findings


def main() -> int:
    findings = check()
    for finding in findings:
        print(finding)
    print(f"conformance: {len(findings)} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
