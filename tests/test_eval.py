"""ADK evaluation regression gate.

Runs the agent against the golden trajectories in ``orders.test.json`` and scores
them with the criteria in ``test_config.json`` (auto-discovered from this folder):

- ``tool_trajectory_avg_score`` = 1.0 -> the tool call sequence must match exactly
  (the auditability lever: a wrong/reordered/dropped tool call fails the build).

``response_match_score`` is intentionally left out: ROUGE on free-form prose is noisy
and, under the ``-latest`` model alias, the prose can drift. Add it only once you pin
a GA model and have stable reference responses.

Run:  ``pytest tests/``  (auto-discovers test_config.json), or the CLI form
``adk eval domain_agent tests/orders.test.json --config_file_path tests/test_config.json``

Note: this test invokes the model, so it needs Vertex AI / AI Studio credentials
(see .env.example). Skipped automatically when no backend is configured.
"""

import os
import pathlib

import pytest
from google.adk.evaluation.agent_evaluator import AgentEvaluator

EVAL_FILE = pathlib.Path(__file__).parent / "orders.test.json"

_has_backend = bool(
    os.getenv("GOOGLE_API_KEY")
    or os.getenv("GOOGLE_GENAI_API_KEY")
    or os.getenv("GOOGLE_CLOUD_PROJECT")
)


@pytest.mark.skipif(not _has_backend, reason="No Gemini backend configured (see .env.example).")
@pytest.mark.asyncio
async def test_orders_golden_trajectory():
    """The orders agent must follow the golden tool-call trajectory."""
    await AgentEvaluator.evaluate(
        agent_module="domain_agent",
        eval_dataset_file_path_or_dir=str(EVAL_FILE),
    )
