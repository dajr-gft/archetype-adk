"""Deployment preflight: the faults that make a deployed agent fail on its first call.

    python tools/check_deploy.py            # after `agents-cli scaffold enhance`, before deploy

Each check is a fault that was met deploying an agent built from this archetype to Agent
Runtime and registering it in Gemini Enterprise. None of them shows locally: the agent
runs in the playground and fails only when the platform calls it.

D01  agents-cli-manifest.yaml names a deployment target (not "none").
D02  pyproject.toml keeps the ADK version the archetype was tested with.
D03  pyproject.toml has google-cloud-aiplatform[agent-engines] in the dependencies the
     container installs (the server imports vertexai; without it the container does not
     start).
D04  The server attaches the reasoning-engine routes (Gemini Enterprise and the console
     call /api/stream_reasoning_engine; without them the call ends in 404 Not Found).
D05  App.name is the name of the agent package (sessions are resolved by it).
D06  The agent does not keep its data in the container (the in-memory store is replaced).
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

MINIMUM_ADK = (2, 15)


def _dependencies(root: Path) -> list[str]:
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    return [str(item) for item in data.get("project", {}).get("dependencies", [])]


def _manifest(root: Path) -> dict[str, str]:
    path = root / "agents-cli-manifest.yaml"
    if not path.is_file():
        return {}
    pairs = re.findall(
        r'^\s*([a-z_]+):\s*"?([^"\n]*)"?\s*$', path.read_text(encoding="utf-8"), re.M
    )
    return dict(pairs)


def check(root: Path) -> list[str]:
    findings: list[str] = []
    manifest = _manifest(root)
    if not manifest:
        return ["D01 no agents-cli-manifest.yaml: run `agents-cli scaffold enhance` first"]
    package = root / manifest.get("agent_directory", "domain_agent")

    if manifest.get("deployment_target", "none") in ("", "none"):
        findings.append(
            'D01 agents-cli-manifest.yaml has deployment_target "none": set the target '
            "(agent_runtime, cloud_run or gke)"
        )

    dependencies = _dependencies(root)
    adk = next((d for d in dependencies if re.match(r"google-adk(\[|[<>=~! ]|$)", d)), "")
    floor = re.search(r">=\s*(\d+)\.(\d+)", adk)
    if not floor or (int(floor.group(1)), int(floor.group(2))) < MINIMUM_ADK:
        findings.append(
            f"D02 pyproject.toml asks for {adk or 'no google-adk'}: keep "
            f">={MINIMUM_ADK[0]}.{MINIMUM_ADK[1]}.0 (enhance lowers it)"
        )
    if not any(re.match(r"google-cloud-aiplatform\[[^\]]*agent-engines", d) for d in dependencies):
        findings.append(
            "D03 pyproject.toml lacks google-cloud-aiplatform[agent-engines] in "
            "[project].dependencies: the server imports vertexai and will not start"
        )

    server = package / "fast_api_app.py"
    if not server.is_file():
        findings.append(f"D04 {server.relative_to(root).as_posix()} does not exist")
    else:
        source = server.read_text(encoding="utf-8")
        if not re.search(r"^attach_reasoning_engine_routes\(", source, re.M):
            findings.append(
                "D04 fast_api_app.py does not call attach_reasoning_engine_routes(app): "
                "Gemini Enterprise gets 404 Not Found"
            )

    agent = (package / "agent.py").read_text(encoding="utf-8")
    names = re.findall(r"App\(\s*name\s*=\s*[\"']([^\"']+)[\"']", agent)
    if names != [package.name]:
        findings.append(f"D05 agent.py must define App(name={package.name!r}); found {names}")

    replaced = any(
        "set_store(" in path.read_text(encoding="utf-8")
        for path in package.rglob("*.py")
        if path.name != "store.py"
    )
    if not replaced:
        findings.append(
            "D06 nothing calls set_store(): the deployed agent would keep its data in the "
            "memory of one container (lost on restart, not shared between instances)"
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
