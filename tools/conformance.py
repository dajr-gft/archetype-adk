"""Conformance gate of the archetype: the rules of archetype.md that a machine can check.

    python tools/conformance.py                    # exit code 1 and one line per finding
    python tools/conformance.py --write-owned      # (archetype only) refresh the manifest

It reads the source (no import of the agent, no model call), so it also runs on code that
does not import yet. Each check has an id (C01...) that archetype.md cites. Two profiles:
a conversational agent (the package has ``tools.py``) and a pipeline (``root_agent`` is a
``Workflow``).
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOT_PACKAGES = {"tests", "tools", "examples", "deployment", "docs"}
OWNED_MANIFEST = "ARCHETYPE_OWNED.sha256"
OWNED = (
    "{package}/__init__.py",
    "{package}/toolkit.py",
    "{package}/plugins.py",
    "{package}/domain/base.py",
    "tools/conformance.py",
    "tools/check_deploy.py",
    "tools/check_model.py",
    "conftest.py",
    "tests/conftest.py",
    "tests/support/scripted.py",
    "tests/support/backend.py",
    "tests/unit/test_toolkit.py",
    "tests/unit/test_base.py",
    "tests/unit/test_replay.py",
    "tests/unit/test_conformance.py",
    "tests/eval/test_eval.py",
    "tests/eval/test_config.json",
)

FORBIDDEN_CALLS = {"print", "exit", "quit", "input", "breakpoint"}
FORBIDDEN_ATTRIBUTES = {("sys", "exit"), ("os", "_exit"), ("os", "system"), ("os", "abort")}
FORBIDDEN_MODULES = {"subprocess", "multiprocessing"}
MODEL_SDKS = {"google", "vertexai", "litellm", "openai", "anthropic"}
UNSTABLE_MODEL = re.compile(r"preview|latest|exp\b|experimental", re.IGNORECASE)
SOURCE_CODE = re.compile(r"^[A-Za-z0-9_.\-/$#@]+:\d+(-\d+)?(,\d+(-\d+)?)*$")
SOURCE_DOCUMENT = re.compile(r"^DOC:[A-Za-z0-9_.\-/ ]+#[A-Za-z0-9_.\-]+$")
SOURCE_ASSUMED = re.compile(r"^ASSUMED:(OP-\d+)$")
PARAMETER_TYPES = {"str", "int", "bool", "list[str]", "list[int]"}
STORE_WRITES = ("save_", "add_", "delete_", "remove_", "update_", "put_", "insert_")
TOOLKIT_READS = {"read", "prepare", "review"}
TOOLKIT_WRITES = {"submit", "decide"}
PAIRS = {"submit": "prepare", "decide": "review"}

Function = ast.FunctionDef | ast.AsyncFunctionDef


class Project:
    """The files of the project being checked."""

    def __init__(self, root: Path, package: str | None = None, tests: str = "tests/unit") -> None:
        self.root = root
        self.package = root / (package or self._find_package(root))
        self.tests = root / tests
        self.findings: list[str] = []

    @staticmethod
    def _find_package(root: Path) -> str:
        found = sorted(
            path.parent.name
            for path in root.glob("*/agent.py")
            if path.parent.name not in NOT_PACKAGES and (path.parent / "__init__.py").is_file()
        )
        return found[0] if len(found) == 1 else "domain_agent"

    def add(self, check: str, message: str) -> None:
        self.findings.append(f"{check} {message}")

    def name(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def tree(self, relative: str) -> ast.Module | None:
        """The parsed module, or None (with a finding) when it is missing or does not parse."""
        path = self.package / relative
        if not path.is_file():
            self.add("C00", f"{self.name(path)} does not exist")
            return None
        try:
            return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as error:
            self.add("C00", f"{self.name(path)} does not parse: line {error.lineno}")
            return None

    def modules(self) -> Iterator[tuple[Path, ast.Module]]:
        for path in sorted(self.package.rglob("*.py")):
            try:
                yield path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except SyntaxError as error:
                self.add("C00", f"{self.name(path)} does not parse: line {error.lineno}")


def _functions(tree: ast.Module, public: bool = True) -> list[Function]:
    return [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and (not public or not node.name.startswith("_"))
    ]


def _parameters(function: Function | ast.Lambda) -> list[ast.arg]:
    arguments = function.args
    return [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]


def _string_constants(tree: ast.Module) -> dict[str, str]:
    found: dict[str, str] = {}
    for node in tree.body:
        value = node.value if isinstance(node, ast.Assign | ast.AnnAssign) else None
        targets = (
            node.targets
            if isinstance(node, ast.Assign)
            else [node.target]
            if isinstance(node, ast.AnnAssign)
            else []
        )
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            for target in targets:
                if isinstance(target, ast.Name):
                    found[target.id] = value.value
    return found


def _calls(tree: ast.AST, name: str) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and ast.unparse(node.func).split(".")[-1] == name
    ]


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    return next((keyword.value for keyword in call.keywords if keyword.arg == name), None)


# ── C01: the tools of the agent ───────────────────────────────────────────────────────


def check_tools_contract(project: Project, tools: ast.Module, agent: ast.Module) -> set[str]:
    """C01: agent.py imports and registers exactly the public functions of tools.py."""
    defined = {function.name for function in _functions(tools)}
    imported: set[str] = set()
    registered: set[str] = set()
    for node in ast.walk(agent):
        if isinstance(node, ast.ImportFrom) and node.module == "tools" and node.level == 1:
            imported |= {alias.name for alias in node.names}
        if (
            isinstance(node, ast.keyword)
            and node.arg == "tools"
            and isinstance(node.value, ast.List)
        ):
            for element in node.value.elts:
                target: ast.expr = element
                if isinstance(element, ast.Call) and element.args:
                    if ast.unparse(element.func) == "FunctionTool":
                        target = element.args[0]
                if isinstance(target, ast.Name):
                    registered.add(target.id)
                else:
                    project.add(
                        "C01", f"tools=[...] holds {ast.unparse(element)}, not a tool of tools.py"
                    )
    for label, names in (("imported in agent.py", imported), ("in tools=[...]", registered)):
        for name in sorted(defined - names):
            project.add("C01", f"tool {name} is defined in tools.py but not {label}")
        for name in sorted(names - defined):
            project.add("C01", f"{name} is {label} but tools.py does not define it")
    return defined


# ── C02: no process calls ─────────────────────────────────────────────────────────────


def check_no_process_calls(project: Project) -> None:
    """C02: no print, exit, input or process call anywhere in the package."""
    for path, tree in project.modules():
        for node in ast.walk(tree):
            where = f"{project.name(path)}:{getattr(node, 'lineno', 0)}"
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in FORBIDDEN_CALLS:
                    project.add("C02", f"{where} calls {node.func.id}()")
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                if (node.value.id, node.attr) in FORBIDDEN_ATTRIBUTES:
                    project.add("C02", f"{where} uses {node.value.id}.{node.attr}")
            if isinstance(node, ast.Raise) and node.exc is not None:
                if "SystemExit" in ast.unparse(node.exc):
                    project.add("C02", f"{where} raises SystemExit")
            imported = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            for module in imported:
                if module.split(".")[0] in FORBIDDEN_MODULES:
                    project.add("C02", f"{where} imports {module}")


# ── C03: the signature of a tool ──────────────────────────────────────────────────────


def check_tool_signatures(project: Project, tools: ast.Module) -> None:
    """C03: a coroutine with typed scalar parameters, no defaults, a docstring for the model."""
    for function in _functions(tools):
        name = function.name
        arguments = function.args
        docstring = ast.get_docstring(function) or ""
        parameters = _parameters(function)
        model_parameters = [p for p in parameters if p.arg != "tool_context"]
        if not isinstance(function, ast.AsyncFunctionDef):
            project.add("C03", f"tool {name} is not a coroutine (async def)")
        if arguments.defaults or any(default is not None for default in arguments.kw_defaults):
            project.add("C03", f"tool {name} has a parameter with a default value")
        if arguments.vararg or arguments.kwarg:
            project.add("C03", f"tool {name} takes *args or **kwargs")
        if not parameters or parameters[-1].arg != "tool_context":
            project.add("C03", f"tool {name}: the last parameter is not tool_context")
        elif ast.unparse(parameters[-1].annotation or ast.Constant("")) != "ToolContext":
            project.add("C03", f"tool {name}: tool_context is not annotated ToolContext")
        if not docstring:
            project.add("C03", f"tool {name} has no docstring")
        if "tool_context" in docstring:
            project.add("C03", f"the docstring of tool {name} mentions tool_context")
        if model_parameters and "Args:" not in docstring:
            project.add("C03", f"the docstring of tool {name} has no Args: section")
        returns = ast.unparse(function.returns) if function.returns else ""
        if not returns.startswith("dict"):
            project.add("C03", f"tool {name} does not declare a dict return type")
        for parameter in model_parameters:
            annotation = ast.unparse(parameter.annotation) if parameter.annotation else ""
            if annotation.replace(" ", "") not in PARAMETER_TYPES:
                project.add(
                    "C03",
                    f"tool {name}: parameter {parameter.arg} is {annotation or 'untyped'}; a tool "
                    "takes str, int, bool or a list of str or int (amounts and dates as text)",
                )
            if "Args:" in docstring and f"{parameter.arg}:" not in docstring.split("Args:")[1]:
                project.add("C03", f"tool {name}: parameter {parameter.arg} is not documented")


# ── C04: the domain is plain Python ───────────────────────────────────────────────────


def check_domain_purity(project: Project) -> None:
    """C04: the domain imports neither ADK, nor a model SDK, nor the agent layer."""
    domain = project.package / "domain"
    for path, tree in project.modules():
        if domain not in path.parents:
            continue
        for node in ast.walk(tree):
            where = f"{project.name(path)}:{getattr(node, 'lineno', 0)}"
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                modules = [node.module or ""]
            elif isinstance(node, ast.ImportFrom) and node.level >= 2:
                project.add("C04", f"{where} imports from outside the domain package")
                continue
            else:
                continue
            for module in modules:
                if module.split(".")[0] in MODEL_SDKS:
                    project.add("C04", f"{where} imports {module}")


# ── C05, C06: the agents ──────────────────────────────────────────────────────────────


def check_agents(project: Project, agent: ast.Module) -> None:
    """C05: no templated instruction. C06: model, temperature and app from the archetype."""
    source = ast.unparse(agent)
    constants = _string_constants(agent)
    default = constants.get("DEFAULT_MODEL")
    if not default:
        project.add("C06", "agent.py does not define DEFAULT_MODEL as a string literal")
    elif UNSTABLE_MODEL.search(default) or len(default) < 8:
        project.add("C06", f"DEFAULT_MODEL {default!r} is an alias, a preview or truncated")
    if "os.environ.get('AGENT_MODEL', DEFAULT_MODEL)" not in source:
        project.add(
            "C06", "agent.py does not set MODEL = os.environ.get('AGENT_MODEL', DEFAULT_MODEL)"
        )
    if not re.search(
        r"TEMPERATURE = float\(os\.environ\.get\('AGENT_TEMPERATURE', '0(\.0)?'\)\)", source
    ):
        project.add(
            "C06", "agent.py does not set TEMPERATURE from AGENT_TEMPERATURE with the default 0.0"
        )
    generation = [call for call in _calls(agent, "GenerateContentConfig")]
    if not any(ast.unparse(_keyword(call, "temperature") or ast.Constant(None)) == "TEMPERATURE"
               for call in generation):  # fmt: skip
        project.add("C06", "GENERATION does not use temperature=TEMPERATURE")

    providers = {function.name for function in _functions(agent, public=False)}
    prompt = project.package / "prompt.py"
    if prompt.is_file():
        providers |= {
            f.name for f in _functions(ast.parse(prompt.read_text(encoding="utf-8")), False)
        }
    agents = _calls(agent, "Agent") + _calls(agent, "LlmAgent")
    if not agents and not _calls(agent, "Workflow"):
        project.add("C06", "agent.py defines no agent")
    for call in agents:
        label = ast.unparse(_keyword(call, "name") or ast.Constant("?"))
        if ast.unparse(_keyword(call, "model") or ast.Constant(None)) != "MODEL":
            project.add("C06", f"agent {label} does not use model=MODEL")
        if (
            ast.unparse(_keyword(call, "generate_content_config") or ast.Constant(None))
            != "GENERATION"
        ):
            project.add("C06", f"agent {label} does not use generate_content_config=GENERATION")
        instruction = _keyword(call, "instruction")
        if instruction is not None and not (
            isinstance(instruction, ast.Name) and instruction.id in providers
        ):
            project.add(
                "C05",
                f"agent {label} passes a text as instruction=: ADK substitutes braces in it and "
                "stops on a name that is not session state. Use static_instruction=, or a "
                "function of prompt.py that returns the text",
            )
        if _keyword(call, "global_instruction") is not None:
            project.add("C06", f"agent {label} uses the deprecated global_instruction")
        if ast.unparse(_keyword(call, "mode") or ast.Constant("chat")) not in ("'chat'", "chat"):
            project.add(
                "C06",
                f"agent {label} sets mode=: task agents share an invocation with their caller",
            )
    if _calls(agent, "AgentTool"):
        project.add(
            "C06",
            "agent.py wraps an agent in AgentTool: each call is a session of its own, so no "
            "write can be confirmed through it. Use sub_agents",
        )

    apps = _calls(agent, "App")
    names = [ast.unparse(_keyword(call, "name") or ast.Constant(None)) for call in apps]
    if names != [repr(project.package.name)]:
        project.add("C06", f"agent.py must define one App(name={project.package.name!r}, ...)")
    if apps and "AuditPlugin()" not in ast.unparse(
        _keyword(apps[0], "plugins") or ast.Constant(None)
    ):
        project.add("C06", "App(...) does not register AuditPlugin() in plugins=[...]")
    assigned = {
        target.id
        for node in agent.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    if "root_agent" not in assigned:
        project.add("C06", "agent.py does not assign root_agent")


# ── C07: the rule catalogue ───────────────────────────────────────────────────────────


def _tested_ids(project: Project) -> str:
    """Names and docstrings of the test functions: where a rule id counts as tested."""
    text: list[str] = []
    for path in sorted(project.tests.glob("test_*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith(
                "test"
            ):
                text.append(node.name.upper().replace("_", "-"))
                text.append(ast.get_docstring(node) or "")
    return "\n".join(text)


def check_rule_catalogue(project: Project, rules: ast.Module) -> None:
    """C07: every rule says where it comes from and is named by a unit test.

    A source is legacy code (``<member>:<line>[-<line>][,...]``), a document of the legacy
    system (``DOC:<document>#<anchor>``) or a declared assumption (``ASSUMED:OP-<n>``,
    with OP-<n> described in OPEN_POINTS.md).
    """
    catalogue: dict[str, str] = {}
    for call in _calls(rules, "Rule"):
        values = [*call.args, *(keyword.value for keyword in call.keywords)]
        if len(values) != 3 or not all(
            isinstance(value, ast.Constant) and isinstance(value.value, str) for value in values
        ):
            project.add(
                "C07",
                f"rules.py:{call.lineno} Rule(...) takes three string literals: id, statement, source",
            )
            continue
        catalogue[str(values[0].value)] = str(values[2].value)  # type: ignore[attr-defined]
    if not catalogue:
        project.add("C07", "domain/rules.py declares no Rule in RULES")
    points = project.root / "OPEN_POINTS.md"
    open_points = points.read_text(encoding="utf-8") if points.is_file() else ""
    tested = _tested_ids(project)
    for rule_id, source in sorted(catalogue.items()):
        assumed = SOURCE_ASSUMED.match(source)
        if assumed and not re.search(rf"\b{assumed.group(1)}\b", open_points):
            project.add(
                "C07",
                f"rule {rule_id} is assumed, but {assumed.group(1)} is not described in OPEN_POINTS.md",
            )
        if not (assumed or SOURCE_DOCUMENT.match(source) or SOURCE_CODE.match(source)):
            project.add(
                "C07",
                f"rule {rule_id}: source {source!r} is not '<member>:<line>[-<line>]', "
                "'DOC:<document>#<anchor>' or 'ASSUMED:OP-<n>'",
            )
        if not re.search(rf"(?<![A-Z0-9-]){re.escape(rule_id)}(?![0-9])", tested):
            project.add(
                "C07",
                f"rule {rule_id} is not named in the name or the docstring of a test in "
                f"{project.name(project.tests)}",
            )


# ── C08: business values live in the domain ───────────────────────────────────────────


def check_business_values(project: Project) -> None:
    """C08: no number in the tools or the instruction; no float in the domain."""
    for relative in ("tools.py", "prompt.py"):
        path = project.package / relative
        if not path.is_file():
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            value = node.value if isinstance(node, ast.Constant) else None
            if (
                isinstance(value, int | float)
                and not isinstance(value, bool)
                and value not in (0, 1)
            ):
                project.add(
                    "C08",
                    f"{project.name(path)}:{node.lineno} holds the number {value}; limits and "  # type: ignore[attr-defined]
                    "thresholds are constants of domain/rules.py",
                )
    domain = project.package / "domain"
    for path, tree in project.modules():
        if domain not in path.parents:
            continue
        for node in ast.walk(tree):
            annotation = getattr(node, "annotation", None)
            if isinstance(node, ast.arg | ast.AnnAssign) and annotation is not None:
                if re.search(r"\bfloat\b", ast.unparse(annotation)):
                    project.add(
                        "C08",
                        f"{project.name(path)}:{node.lineno} declares a float; an amount is an "
                        "integer of minor units or a Decimal",
                    )
            if isinstance(node, ast.FunctionDef) and node.returns is not None:
                if re.search(r"\bfloat\b", ast.unparse(node.returns)):
                    project.add("C08", f"{project.name(path)}:{node.lineno} returns a float")


# ── C09: the evaluation set ───────────────────────────────────────────────────────────


def check_evaluation_set(project: Project, tools: set[str], writes: bool) -> None:
    """C09: EvalSet schema, real tools only, and the conversations every agent has to pass."""
    files = sorted((project.root / "tests" / "eval").glob("*.test.json"))
    if not files:
        project.add("C09", "tests/eval has no *.test.json evaluation set")
        return
    used: set[str] = set()
    confirmed = declined = unavailable = False
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            project.add("C09", f"{path.name} is not JSON: line {error.lineno}")
            continue
        cases = data.get("eval_cases") if isinstance(data, dict) else None
        if not cases:
            project.add("C09", f"{path.name} is not an EvalSet (eval_cases[])")
            continue
        for case in cases:
            label = f"{path.name} {case.get('eval_id')}"
            turns: list[list[str]] = []
            for turn in case.get("conversation") or []:
                if "user_content" not in turn:
                    project.add("C09", f"{label}: turn without user_content")
                names = [
                    str(use.get("name"))
                    for use in (turn.get("intermediate_data") or {}).get("tool_uses") or []
                ]
                for name in names:
                    if name not in tools:
                        project.add("C09", f"{label}: unknown tool {name}")
                turns.append(names)
            if not turns:
                project.add("C09", f"{label}: no conversation[]")
            used |= {name for names in turns for name in names}
            unavailable = unavailable or all(not names for names in turns)
            for before, after in zip(turns, turns[1:], strict=False):
                prepared = [name for name in before if name.startswith("prepare_")]
                if prepared and any(
                    name == "submit_" + p.removeprefix("prepare_")
                    for p in prepared
                    for name in after
                ):
                    confirmed = True
                if prepared and not after:
                    declined = True
    for name in sorted(tools - used):
        project.add("C09", f"no evaluation case calls the tool {name}")
    if not unavailable:
        project.add(
            "C09", "no evaluation case asks for something no tool does (a case with no tool call)"
        )
    if writes and not confirmed:
        project.add(
            "C09",
            "no evaluation case confirms a write (prepare_x in one turn, submit_x in the next)",
        )
    if writes and not declined:
        project.add(
            "C09", "no evaluation case declines a write (prepare_x, then a turn with no tool call)"
        )


# ── C10, C11: a tool only delegates; a write is confirmed; identity comes from the session ──


def _service_functions(service: ast.Module) -> dict[str, Function]:
    return {function.name: function for function in _functions(service, public=False)}


def _writes_to_store(function: Function, functions: dict[str, Function], seen: set[str]) -> bool:
    """Whether the function, or a function of the module it calls, changes the store."""
    seen.add(function.name)
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Attribute) and node.func.attr.startswith(STORE_WRITES):
            if node.func.attr != "add_write":
                return True
        if isinstance(node.func, ast.Name):
            if node.func.id == "record":
                return True
            called = functions.get(node.func.id)
            if called and called.name not in seen and _writes_to_store(called, functions, seen):
                return True
    return False


def check_write_use_cases(project: Project, service: ast.Module) -> set[str]:
    """C11: a use case that writes takes user and confirmation, authorizes and records."""
    functions = _service_functions(service)
    writers: set[str] = set()
    for name, function in functions.items():
        parameters = [parameter.arg for parameter in _parameters(function)]
        if "confirmation" in parameters:
            writers.add(name)
        if name.startswith("_"):
            continue
        writes = _writes_to_store(function, functions, set())
        if writes and "confirmation" not in parameters:
            project.add(
                "C11",
                f"use case {name} changes the store without a confirmation parameter: a write "
                "takes (…, user, confirmation)",
            )
        if "confirmation" in parameters:
            body = ast.unparse(function)
            if "user" not in parameters:
                project.add("C11", f"use case {name} writes without a user parameter")
            if not re.search(r"\bauthorize\(", body):
                project.add("C11", f"use case {name} does not call authorize(...) before it writes")
            if not re.search(r"\brecord\(", body):
                project.add("C11", f"use case {name} does not call record(...) after it wrote")
    return writers


def _callables(call: ast.Call, function: Function) -> list[ast.Lambda | Function]:
    """The use-case callables passed to a toolkit call: lambdas, or functions of the tool."""
    local = {
        node.name: node
        for node in ast.walk(function)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node is not function
    }
    found: list[ast.Lambda | Function] = []
    for value in [*call.args, *(keyword.value for keyword in call.keywords)]:
        if isinstance(value, ast.Lambda):
            found.append(value)
        elif isinstance(value, ast.Name) and value.id in local:
            found.append(local[value.id])
    return found


def check_tools_delegate(
    project: Project, tools: ast.Module, service: ast.Module, writers: set[str]
) -> bool:
    """C10: a tool only hands a use case to the toolkit. C11: writes go through submit/decide.

    Returns whether the agent writes at all.
    """
    signatures = {
        name: [parameter.arg for parameter in _parameters(function)]
        for name, function in _service_functions(service).items()
    }
    opened: dict[str, set[str]] = {kind: set() for kind in (*TOOLKIT_READS, *TOOLKIT_WRITES)}
    writes = False
    for function in _functions(tools):
        name = function.name
        toolkit_calls = [
            call
            for call in ast.walk(function)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and ast.unparse(call.func.value) == "toolkit"
        ]
        if not toolkit_calls:
            project.add("C10", f"tool {name} does not go through the toolkit")
        direct = {id(arg) for call in toolkit_calls for arg in call.args[:1]}
        for node in ast.walk(function):
            if isinstance(node, ast.Name) and node.id == "tool_context" and id(node) not in direct:
                if isinstance(node.ctx, ast.Load):
                    project.add(
                        "C10",
                        f"tool {name} reads tool_context at line {node.lineno}: a tool only passes "
                        "it to the toolkit (the user, the state and the session are the toolkit's)",
                    )
        inside: dict[int, str] = {}
        for call in toolkit_calls:
            kind = call.func.attr  # type: ignore[attr-defined]
            if kind not in opened:
                project.add(
                    "C10", f"tool {name} calls toolkit.{kind}, which is not a tool entry point"
                )
                continue
            if len(call.args) < 2 or ast.unparse(call.args[0]) != "tool_context":
                project.add(
                    "C10", f"tool {name}: toolkit.{kind}(tool_context, ...) is called otherwise"
                )
                continue
            label = call.args[1]
            if isinstance(label, ast.Constant) and isinstance(label.value, str):
                opened[kind].add(label.value)
            elif kind != "read":
                project.add(
                    "C10", f"tool {name}: toolkit.{kind} needs its name as a string literal"
                )
            if kind in TOOLKIT_WRITES:
                writes = True
            if kind == "submit" and [p.arg for p in _parameters(function)] != ["tool_context"]:
                project.add(
                    "C11",
                    f"tool {name} submits a write and takes parameters from the model: what is "
                    "written comes from what prepare showed",
                )
            for use_case in _callables(call, function):
                parameters = [parameter.arg for parameter in _parameters(use_case)]
                if not parameters or parameters[0] != "user":
                    project.add(
                        "C10", f"tool {name}: the first parameter of a use-case callable is user"
                    )
                for node in ast.walk(use_case):
                    inside[id(node)] = kind
                for inner in ast.walk(use_case):
                    if not (
                        isinstance(inner, ast.Call)
                        and ast.unparse(inner.func).startswith("service.")
                    ):
                        continue
                    called = ast.unparse(inner.func).removeprefix("service.")
                    expected = signatures.get(called)
                    if expected is None:
                        project.add(
                            "C10",
                            f"tool {name} calls service.{called}, which service.py does not define",
                        )
                        continue
                    passed = {
                        expected[index]: ast.unparse(value)
                        for index, value in enumerate(inner.args)
                        if index < len(expected)
                    } | {
                        keyword.arg: ast.unparse(keyword.value)
                        for keyword in inner.keywords
                        if keyword.arg
                    }
                    if "user" in expected and passed.get("user") != "user":
                        project.add(
                            "C11",
                            f"tool {name} passes {passed.get('user')!r} as the user of service.{called}: "
                            "the acting user is the one the toolkit gives",
                        )
                    if (called in writers) != (kind in TOOLKIT_WRITES):
                        project.add(
                            "C11",
                            f"tool {name} calls service.{called} from toolkit.{kind}: a use case that "
                            "writes runs in submit or decide, and only there",
                        )
        for node in ast.walk(function):
            if isinstance(node, ast.Attribute) and ast.unparse(node.value) == "service":
                if id(node) not in inside:
                    project.add(
                        "C10",
                        f"tool {name} uses service.{node.attr} outside a callable given to the toolkit",
                    )
    for kind, opener in PAIRS.items():
        for unopened in sorted(opened[kind] - opened[opener]):
            project.add(
                "C11",
                f"toolkit.{kind}(…, {unopened!r}) has no tool that calls toolkit.{opener}(…, {unopened!r})",
            )
    return writes


# ── C12: what belongs to the archetype ────────────────────────────────────────────────


def _digest(path: Path, package: str = "domain_agent") -> str:
    """The digest of a file, whatever its line ends and the name the package was given."""
    content = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(content.replace(package.encode(), b"domain_agent")).hexdigest()


def owned_files(project: Project) -> list[str]:
    return [entry.format(package=project.package.name) for entry in OWNED]


def write_owned_manifest(project: Project) -> None:
    lines = [
        f"{_digest(project.root / name, project.package.name)}  {name}"
        for name in owned_files(project)
    ]
    (project.root / OWNED_MANIFEST).write_text(
        "\n".join(lines) + "\n", encoding="utf-8", newline="\n"
    )


def check_owned_files(project: Project) -> None:
    """C12: the files of the archetype are the ones the archetype shipped."""
    manifest = project.root / OWNED_MANIFEST
    if not manifest.is_file():
        project.add("C12", f"{OWNED_MANIFEST} is missing")
        return
    expected: dict[str, str] = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        digest, _, owned = line.partition("  ")
        if owned:
            expected[owned] = digest
    for name in owned_files(project):
        path = project.root / name
        template = name.replace(project.package.name + "/", "domain_agent/", 1)
        wanted = expected.get(name) or expected.get(template)
        if not path.is_file():
            project.add("C12", f"{name} belongs to the archetype and is missing")
        elif wanted is None:
            project.add("C12", f"{name} is not in {OWNED_MANIFEST}")
        elif _digest(path, project.package.name) != wanted:
            project.add("C12", f"{name} belongs to the archetype and was changed")


# ── C13: a pipeline ───────────────────────────────────────────────────────────────────


def check_pipeline(project: Project, agent: ast.Module) -> None:
    """C13: the steps of a pipeline are code, and a test asserts what they produced."""
    functions = {function.name for function in _functions(agent, public=False)}
    in_edges: set[str] = set()
    for call in _calls(agent, "Workflow"):
        edges = _keyword(call, "edges")
        if edges is not None:
            in_edges |= {node.id for node in ast.walk(edges) if isinstance(node, ast.Name)}
    if not in_edges & functions:
        project.add(
            "C13",
            "the workflow has no function node: the steps of the legacy program are functions "
            "of agent.py, not model agents",
        )
    if not sorted((project.root / "tests").rglob("test_pipeline*model*.py")):
        project.add(
            "C13",
            "no tests/**/test_pipeline*model*.py: a pipeline is checked on the state its code "
            "wrote, with the real model",
        )


def check(root: Path = ROOT, package: str | None = None, tests: str = "tests/unit") -> list[str]:
    project = Project(root, package, tests)
    agent = project.tree("agent.py")
    rules = project.tree("domain/rules.py")
    check_no_process_calls(project)
    check_domain_purity(project)
    check_business_values(project)
    if rules is not None:
        check_rule_catalogue(project, rules)
    if agent is not None:
        check_agents(project, agent)
    conversational = (project.package / "tools.py").is_file()
    if conversational:
        tools = project.tree("tools.py")
        service = project.tree("domain/service.py")
        store = project.package / "domain" / "store.py"
        if store.is_file() and "def in_memory_store(" not in store.read_text(encoding="utf-8"):
            project.add(
                "C00",
                "domain/store.py does not define in_memory_store(): wiring.py and the tests "
                "take their store from it",
            )
        if tools is not None and agent is not None:
            names = check_tools_contract(project, tools, agent)
            check_tool_signatures(project, tools)
            writes = False
            if service is not None:
                writers = check_write_use_cases(project, service)
                writes = check_tools_delegate(project, tools, service, writers)
            check_evaluation_set(project, names, writes)
    elif agent is not None and _calls(agent, "Workflow"):
        check_pipeline(project, agent)
    elif agent is not None:
        project.add("C00", "the package has no tools.py and its root_agent is not a Workflow")
    if root == ROOT or (root / OWNED_MANIFEST).is_file():
        if conversational or package is None:
            check_owned_files(project)
    return project.findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--package", help="the agent package (default: the one that has agent.py)")
    parser.add_argument("--tests", default="tests/unit", help="where the tests of the rules are")
    parser.add_argument("--write-owned", action="store_true", help="refresh ARCHETYPE_OWNED.sha256")
    arguments = parser.parse_args()
    if arguments.write_owned:
        write_owned_manifest(Project(ROOT, arguments.package, arguments.tests))
        print(f"wrote {OWNED_MANIFEST}")
        return 0
    findings = check(ROOT, arguments.package, arguments.tests)
    for finding in findings:
        print(finding)
    print(f"conformance: {len(findings)} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
