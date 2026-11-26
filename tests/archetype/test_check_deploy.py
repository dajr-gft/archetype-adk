"""The deployment preflight catches each fault it exists for (see tools/check_deploy.py)."""

from pathlib import Path

import pytest

from tools import check_deploy

MANIFEST = """name: "x"
agent_directory: "domain_agent"
create_params:
  deployment_target: "agent_runtime"
  session_type: "in_memory"
"""
PYPROJECT = """[project]
name = "x"
dependencies = [
    "google-adk[gcp,otel-gcp]~=2.15.1",
    "google-cloud-aiplatform[agent-engines]>=1.156.0",
]
"""
LOCK = '[[package]]\nname = "google-adk"\nversion = "2.15.1"\n'
SERVER = "app = get_fast_api_app(web=True)\nattach_reasoning_engine_routes(app)\n"
AGENT = 'app = App(name="domain_agent", root_agent=root_agent)\n'
WIRING = "def configure() -> None:\n    set_store(DatabaseOrderStore.from_environment())\n"


@pytest.fixture
def deployed(tmp_path: Path) -> Path:
    """A project as it has to be before `agents-cli deploy`."""
    package = tmp_path / "domain_agent"
    package.mkdir()
    (tmp_path / "agents-cli-manifest.yaml").write_text(MANIFEST, encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    (tmp_path / "uv.lock").write_text(LOCK, encoding="utf-8")
    (package / "fast_api_app.py").write_text(SERVER, encoding="utf-8")
    (package / "agent.py").write_text(AGENT, encoding="utf-8")
    (package / "wiring.py").write_text(WIRING, encoding="utf-8")
    return tmp_path


def ids(root: Path) -> list[str]:
    return [finding.split()[0] for finding in check_deploy.check(root)]


def rewrite(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text, old
    path.write_text(text.replace(old, new), encoding="utf-8")


def test_a_project_ready_to_deploy_has_no_finding(deployed: Path) -> None:
    assert check_deploy.check(deployed) == []


def test_d01_no_manifest_or_no_target(deployed: Path) -> None:
    rewrite(deployed / "agents-cli-manifest.yaml", '"agent_runtime"', '"none"')
    assert ids(deployed) == ["D01"]
    (deployed / "agents-cli-manifest.yaml").unlink()
    assert ids(deployed) == ["D01"]


def test_d01_a_manifest_written_without_quotes(deployed: Path) -> None:
    rewrite(deployed / "agents-cli-manifest.yaml", '"agent_runtime"', "agent_runtime  # managed")
    assert check_deploy.check(deployed) == []


@pytest.mark.parametrize("pin", ["==2.15.1", "~=2.15.1", ">=2.15.0,<3.0.0", ">=2.16"])
def test_d02_the_version_of_the_archetype_is_accepted_however_it_is_pinned(
    deployed: Path, pin: str
) -> None:
    rewrite(deployed / "pyproject.toml", "~=2.15.1", pin)
    assert check_deploy.check(deployed) == []


def test_d02_the_adk_version_was_lowered_in_the_project_or_in_the_lock(deployed: Path) -> None:
    rewrite(deployed / "pyproject.toml", "~=2.15.1", ">=2.2.0,<3.0.0")
    assert ids(deployed) == ["D02"]
    rewrite(deployed / "pyproject.toml", ">=2.2.0,<3.0.0", "~=2.15.1")
    rewrite(deployed / "uv.lock", '"2.15.1"', '"2.5.0"')
    assert (
        ids(deployed) == ["D02"]
        and "uv.lock installs google-adk 2.5.0" in check_deploy.check(deployed)[0]
    )


def test_d03_the_server_dependency_is_missing(deployed: Path) -> None:
    rewrite(
        deployed / "pyproject.toml", '    "google-cloud-aiplatform[agent-engines]>=1.156.0",\n', ""
    )
    assert ids(deployed) == ["D03"]


def test_d04_the_reasoning_engine_routes_are_not_attached(deployed: Path) -> None:
    server = deployed / "domain_agent/fast_api_app.py"
    rewrite(
        server, "attach_reasoning_engine_routes(app)\n", "# attach_reasoning_engine_routes(app)\n"
    )
    assert ids(deployed) == ["D04"]
    server.write_text(
        "def build():\n    app = get_fast_api_app(web=True)\n    attach_reasoning_engine_routes(app)\n",
        encoding="utf-8",
    )
    assert check_deploy.check(deployed) == []  # inside a function is fine


def test_d05_the_app_is_not_named_after_the_package(deployed: Path) -> None:
    rewrite(deployed / "domain_agent/agent.py", '"domain_agent"', '"orders"')
    assert ids(deployed) == ["D05"]


@pytest.mark.parametrize(
    "wiring",
    [
        "def configure() -> None:\n    set_store(InMemoryOrderStore())\n",
        "def configure() -> None:\n    pass  # TODO: call set_store(DatabaseOrderStore())\n",
        "def other() -> None:\n    set_store(DatabaseOrderStore())\n",
        "def configure() -> None:\n    set_store(store.InMemoryOrderStore(SEED))\n",
    ],
)
def test_d06_the_data_would_stay_in_the_container(deployed: Path, wiring: str) -> None:
    (deployed / "domain_agent/wiring.py").write_text(wiring, encoding="utf-8")
    assert ids(deployed) == ["D06"]


def test_d07_d08_a_public_target_with_sessions_in_memory_and_the_developer_ui(
    deployed: Path,
) -> None:
    rewrite(deployed / "agents-cli-manifest.yaml", '"agent_runtime"', '"cloud_run"')
    assert ids(deployed) == ["D07", "D08"]
    rewrite(deployed / "agents-cli-manifest.yaml", '"in_memory"', '"cloud_sql"')
    rewrite(deployed / "domain_agent/fast_api_app.py", "web=True", "web=False")
    assert check_deploy.check(deployed) == []
