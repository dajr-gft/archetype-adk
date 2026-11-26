"""Deployment preflight: the faults that make a deployed agent fail on its first call.

    python tools/check_deploy.py            # after `agents-cli scaffold enhance`, before deploy

Each check is a fault that passes every local test and shows only when the platform calls
the deployed agent, or when a second instance or a restart happens.

D01  agents-cli-manifest.yaml names a deployment target (not "none").
D02  The ADK version is the one the archetype was tested with: in pyproject.toml, and in
     uv.lock when there is one (the container installs the lock, not the range).
D03  google-cloud-aiplatform[agent-engines] is a dependency the container installs (the
     server imports vertexai; without it the container does not start).
D04  On Agent Runtime the server attaches the reasoning-engine routes (Gemini Enterprise
     and the console call /api/stream_reasoning_engine; without them: 404 Not Found).
D05  App.name is the name of the agent package (sessions are resolved by it).
D06  wiring.py connects the system of record, not an in-memory store.
D07  Sessions are kept outside the container on Cloud Run and GKE (what waits for the
     user's confirmation is in the session: another instance would not find it).
D08  On Cloud Run and GKE the server does not serve the developer UI (web=True also serves
     endpoints that create sessions with any user id and any state).
"""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from pathlib import Path

MINIMUM_ADK = (2, 15)
PUBLIC_TARGETS = {"cloud_run", "gke"}


def _manifest(root: Path) -> dict[str, str]:
    """The scalar values of agents-cli-manifest.yaml, whatever their nesting."""
    path = root / "agents-cli-manifest.yaml"
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore[import-untyped]

        values: dict[str, str] = {}

        def flatten(node: object) -> None:
            if isinstance(node, dict):
                for key, value in node.items():
                    if isinstance(value, dict):
                        flatten(value)
                    elif value is not None:
                        values[str(key)] = str(value)

        flatten(yaml.safe_load(text))
        return values or {"_": ""}
    except ImportError:
        pairs = re.findall(r"^\s*([A-Za-z_]+):\s*[\"']?([^\"'\n#]*?)[\"']?\s*(?:#.*)?$", text, re.M)
        return {key: value for key, value in pairs if value} or {"_": ""}


def _version(text: str) -> tuple[int, int] | None:
    match = re.search(r"(\d+)\.(\d+)", text)
    return (int(match.group(1)), int(match.group(2))) if match else None


def _check_dependencies(root: Path, findings: list[str]) -> None:
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8")).get(
        "project", {}
    )
    dependencies = [str(item) for item in project.get("dependencies", [])]
    adk = next((d for d in dependencies if re.match(r"google-adk(\[|[<>=~! ]|$)", d)), "")
    floor = re.search(r"(?:>=|==|~=)\s*([\d.]+)", adk)
    declared = _version(floor.group(1)) if floor else None
    if declared is None or declared < MINIMUM_ADK:
        findings.append(
            f"D02 pyproject.toml asks for {adk or 'no google-adk'}: keep the version of the "
            f"archetype (at least {MINIMUM_ADK[0]}.{MINIMUM_ADK[1]}; enhance lowers it)"
        )
    lock = root / "uv.lock"
    if lock.is_file():
        packages = tomllib.loads(lock.read_text(encoding="utf-8")).get("package", [])
        locked = next((p.get("version", "") for p in packages if p.get("name") == "google-adk"), "")
        if (_version(locked) or (0, 0)) < MINIMUM_ADK:
            findings.append(
                f"D02 uv.lock installs google-adk {locked or '(none)'}: the container runs the "
                "lock. Run `uv lock` after fixing pyproject.toml"
            )
    if not any(re.match(r"google-cloud-aiplatform\[[^\]]*agent-engines", d) for d in dependencies):
        findings.append(
            "D03 pyproject.toml lacks google-cloud-aiplatform[agent-engines] in "
            "[project].dependencies: the server imports vertexai and will not start"
        )


def _check_wiring(package: Path, findings: list[str]) -> None:
    path = package / "wiring.py"
    connected: list[str] = []
    if path.is_file():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        configure = next(
            (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "configure"), None
        )
        for node in ast.walk(configure) if configure else []:
            if isinstance(node, ast.Call) and ast.unparse(node.func) == "set_store" and node.args:
                connected.append(ast.unparse(node.args[0]))
    if not connected:
        findings.append("D06 wiring.py has no configure() that calls set_store(...)")
    elif any(
        re.match(r"InMemory", store.split(".")[-1].lstrip("(")) or "InMemory" in store
        for store in connected
    ):
        findings.append(
            f"D06 wiring.py connects {connected[0]}: a deployed agent keeps its data in the "
            "system of record, not in the memory of one container"
        )


def check(root: Path) -> list[str]:
    findings: list[str] = []
    manifest = _manifest(root)
    if not manifest:
        return ["D01 no agents-cli-manifest.yaml: run `agents-cli scaffold enhance` first"]
    package = root / manifest.get("agent_directory", "domain_agent")
    target = manifest.get("deployment_target", "none")
    if target in ("", "none"):
        findings.append(
            'D01 agents-cli-manifest.yaml has deployment_target "none": set the target '
            "(agent_runtime, cloud_run or gke)"
        )
    _check_dependencies(root, findings)

    server = package / "fast_api_app.py"
    source = server.read_text(encoding="utf-8") if server.is_file() else ""
    if not source:
        findings.append(f"D04 {server.relative_to(root).as_posix()} does not exist")
    elif target == "agent_runtime" and not re.search(
        r"^[^#\n]*attach_reasoning_engine_routes\(\s*app", source, re.M
    ):
        findings.append(
            "D04 fast_api_app.py does not call attach_reasoning_engine_routes(app): "
            "Gemini Enterprise gets 404 Not Found"
        )

    agent = package / "agent.py"
    names = (
        re.findall(r"App\(\s*name\s*=\s*[\"']([^\"']+)[\"']", agent.read_text(encoding="utf-8"))
        if agent.is_file()
        else []
    )
    if names != [package.name]:
        findings.append(f"D05 agent.py must define App(name={package.name!r}); found {names}")
    _check_wiring(package, findings)

    if target in PUBLIC_TARGETS:
        if manifest.get("session_type", "in_memory") in ("in_memory", "none", ""):
            findings.append(
                f"D07 sessions are in memory on {target}: what waits for the user's confirmation "
                "is in the session. Use a session service outside the container"
            )
        if re.search(r"\bweb\s*=\s*True", source):
            findings.append(
                f"D08 fast_api_app.py serves the developer UI (web=True) on {target}: its "
                "endpoints accept any user id and session state. Set web=False and put the "
                "service behind authentication that fixes the user"
            )
    return findings


def main() -> int:
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
    findings = check(root)
    for finding in findings:
        print(finding)
    print(f"deployment preflight: {len(findings)} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
