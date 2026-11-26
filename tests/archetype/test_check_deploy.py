"""The deployment preflight catches each fault it exists for (see tools/check_deploy.py)."""

from pathlib import Path

import pytest

from tools import check_deploy

MANIFEST = 'agent_directory: "domain_agent"\ncreate_params:\n  deployment_target: "agent_runtime"\n'
PYPROJECT = """[project]
name = "x"
dependencies = [
    "google-adk[gcp,otel-gcp]>=2.15.0,<3.0.0",
    "google-cloud-aiplatform[agent-engines]>=1.156.0",
]
"""
SERVER = "app = get_fast_api_app()\nattach_reasoning_engine_routes(app)\n"
AGENT = 'app = App(name="domain_agent", root_agent=root_agent)\n'
STORE_SETUP = "set_store(SystemOfRecordStore())\n"


@pytest.fixture
def deployed(tmp_path: Path) -> Path:
    """A project as it has to be before `agents-cli deploy`."""
    package = tmp_path / "domain_agent"
    (package / "domain").mkdir(parents=True)
    (tmp_path / "agents-cli-manifest.yaml").write_text(MANIFEST, encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    (package / "fast_api_app.py").write_text(SERVER, encoding="utf-8")
    (package / "agent.py").write_text(AGENT, encoding="utf-8")
    (package / "domain" / "store.py").write_text("def set_store(store): ...\n", encoding="utf-8")
    (package / "runtime.py").write_text(STORE_SETUP, encoding="utf-8")
    return tmp_path


def ids(findings: list[str]) -> list[str]:
    return [finding.split()[0] for finding in findings]


def rewrite(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text, old
    path.write_text(text.replace(old, new), encoding="utf-8")


def test_a_project_ready_to_deploy_has_no_finding(deployed: Path) -> None:
    assert check_deploy.check(deployed) == []


def test_d01_no_manifest_or_no_target(deployed: Path) -> None:
    rewrite(deployed / "agents-cli-manifest.yaml", '"agent_runtime"', '"none"')
    assert ids(check_deploy.check(deployed)) == ["D01"]
    (deployed / "agents-cli-manifest.yaml").unlink()
    assert ids(check_deploy.check(deployed)) == ["D01"]


def test_d02_the_adk_version_was_lowered(deployed: Path) -> None:
    rewrite(deployed / "pyproject.toml", ">=2.15.0", ">=2.2.0")
    assert ids(check_deploy.check(deployed)) == ["D02"]


def test_d03_the_server_dependency_is_missing(deployed: Path) -> None:
    rewrite(
        deployed / "pyproject.toml", '    "google-cloud-aiplatform[agent-engines]>=1.156.0",\n', ""
    )
    assert ids(check_deploy.check(deployed)) == ["D03"]


def test_d04_the_reasoning_engine_routes_are_not_attached(deployed: Path) -> None:
    rewrite(deployed / "domain_agent/fast_api_app.py", "attach_reasoning_engine_routes(app)\n", "")
    assert ids(check_deploy.check(deployed)) == ["D04"]


def test_d05_the_app_is_not_named_after_the_package(deployed: Path) -> None:
    rewrite(deployed / "domain_agent/agent.py", '"domain_agent"', '"orders"')
    assert ids(check_deploy.check(deployed)) == ["D05"]


def test_d06_the_data_would_stay_in_the_container(deployed: Path) -> None:
    (deployed / "domain_agent/runtime.py").unlink()
    assert ids(check_deploy.check(deployed)) == ["D06"]
