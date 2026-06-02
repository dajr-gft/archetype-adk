"""Make the top-level `domain_agent` package importable when running `pytest` from
a bare checkout (pytest puts `tests/` on sys.path, not the repo root). With this,
`AgentEvaluator.evaluate(agent_module="domain_agent", ...)` resolves the package
without requiring an editable install."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
