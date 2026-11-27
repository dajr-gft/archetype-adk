"""Archetype-owned. Evaluation gate: with a real model, the golden tool trajectories.

    pytest tests/eval            # needs a Gemini backend (see .env.example)

``test_config.json`` (same folder, discovered by ADK) asks for an exact tool trajectory:
the right tools, with the right arguments, in the right order. The unit tests prove the
rules and the guards; this proves that the model reaches them. It does not judge the
wording of the answers.

Each set runs once, one case at a time, on a fresh store (``tests/conftest.py``): cases
write, so two of them at the same time, or a second run, would start from another state.
"""

import pathlib

import pytest
from google.adk.evaluation.agent_evaluator import AgentEvaluator

from tests.support.backend import require_backend
from tools.conformance import ROOT, Project

EVAL_SETS = sorted(pathlib.Path(__file__).parent.glob("*.test.json"))


@pytest.mark.model
def test_there_is_an_evaluation_set() -> None:
    assert EVAL_SETS, "tests/eval has no *.test.json"


@pytest.mark.model
@pytest.mark.parametrize("eval_set", EVAL_SETS, ids=lambda path: path.name)
async def test_golden_trajectories(eval_set: pathlib.Path) -> None:
    require_backend()
    await AgentEvaluator.evaluate(
        agent_module=Project(ROOT).package.name,
        eval_dataset_file_path_or_dir=str(eval_set),
        num_runs=1,
        parallelism=1,
    )
