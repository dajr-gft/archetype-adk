"""Archetype-owned. The golden conversations of ``tests/eval`` replayed without a model.

The evaluation gate needs a model. This replay does not: a scripted model makes exactly
the tool calls each golden turn expects, through the real runner and the real tools. It
proves, on every run and without credentials, that the evaluation set is consistent with
the code: every tool it names exists and accepts its arguments, no call breaks, and a
write the set expects is one the toolkit lets through.
"""

import json
import pathlib
from typing import Any

import pytest

from domain_agent.agent import root_agent
from tests.support.scripted import Conversation

EVAL_SETS = sorted((pathlib.Path(__file__).parents[1] / "eval").glob("*.test.json"))
CASES = [
    pytest.param(case, id=f"{path.stem}:{case.get('eval_id')}")
    for path in EVAL_SETS
    for case in json.loads(path.read_text(encoding="utf-8")).get("eval_cases", [])
]


def text_of(content: dict[str, Any]) -> str:
    return " ".join(part.get("text", "") for part in content.get("parts", []))


@pytest.mark.parametrize("case", CASES)
async def test_a_golden_conversation_runs_through_the_real_tools(case: dict[str, Any]) -> None:
    talk = Conversation(root_agent.tools)
    user = case.get("session_input", {}).get("user_id", "user")
    for turn in case["conversation"]:
        expected = (turn.get("intermediate_data") or {}).get("tool_uses") or []
        calls = [(use["name"], use.get("args") or {}) for use in expected]
        answers = await talk.turn(user, text_of(turn["user_content"]), *calls)
        assert len(answers) == len(calls)
        for (name, _), answer in zip(calls, answers, strict=True):
            assert answer.get("status") in ("success", "error"), (name, answer)
            assert answer.get("error_code") != "OUTCOME_UNKNOWN", (name, answer)
            if name.startswith(("submit_", "approve_", "reject_")):
                assert answer["status"] == "success", (name, answer)
