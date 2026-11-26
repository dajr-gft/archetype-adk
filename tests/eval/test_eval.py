"""Evaluation gate: the agent, with a real model, follows the golden tool trajectories.

    pytest tests/eval            # needs a Gemini backend (see .env.example)

``test_config.json`` (same folder, discovered by ADK) asks for an exact tool trajectory.
The unit tests prove the rules; this proves that the model reaches them: the right tool,
the right arguments, in the right order, and no write without the user's confirmation.

One run per case on a fresh store: the cases write, so a second run on the same store
would start from another state.
"""

import os
import pathlib

import pytest
from google.adk.evaluation.agent_evaluator import AgentEvaluator

from domain_agent.domain import store

EVAL_SETS = sorted(pathlib.Path(__file__).parent.glob("*.test.json"))

_has_backend = bool(
    os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_CLOUD_PROJECT")
)


@pytest.mark.model
@pytest.mark.skipif(not _has_backend, reason="No Gemini backend configured (see .env.example).")
@pytest.mark.parametrize("eval_set", EVAL_SETS, ids=lambda path: path.name)
async def test_golden_trajectories(eval_set: pathlib.Path) -> None:
    store.set_store(store.InMemoryOrderStore())
    await AgentEvaluator.evaluate(
        agent_module="domain_agent",
        eval_dataset_file_path_or_dir=str(eval_set),
        num_runs=1,
    )
