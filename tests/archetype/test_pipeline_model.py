"""The pipeline example with a real model: the decision that the code wrote to the state.

A workflow is checked on what its function nodes produced, never on the wording of the
answer: the model reads the request (intake) and words the result (present); everything
between them is code, so its result is exact and can be asserted exactly.
"""

import os

import pytest
from google.adk.runners import InMemoryRunner
from google.genai import types

from examples.pipeline_agent.agent import app

_has_backend = bool(
    os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_CLOUD_PROJECT")
)

CASES = [
    ("Wholesale customer for 7 years, order of 2,000.00, asks 12% discount.", "APPROVED", "BR-003"),
    ("Retail customer for 1 year, order of 300.00, wants 20% off.", "REFERRED", "BR-002"),
    ("Retail customer for 2 years, order of 20.00, asks 5% discount.", "INVALID", "VAL-002"),
    ("Wholesale, 3 years, order 900.00, asks 45%.", "DENIED", "BR-001"),
]


@pytest.mark.model
@pytest.mark.skipif(not _has_backend, reason="No Gemini backend configured (see .env.example).")
@pytest.mark.parametrize(("message", "outcome", "rule_id"), CASES)
async def test_the_decision_is_the_one_of_the_rules(
    message: str, outcome: str, rule_id: str
) -> None:
    runner = InMemoryRunner(app=app)
    session = await runner.session_service.create_session(app_name=app.name, user_id="user")
    answered = False
    content = types.Content(role="user", parts=[types.Part.from_text(text=message)])
    async for event in runner.run_async(user_id="user", session_id=session.id, new_message=content):
        answered = answered or (event.author == "present" and bool(event.content))
    stored = await runner.session_service.get_session(
        app_name=app.name, user_id="user", session_id=session.id
    )
    assert stored is not None
    decision = stored.state["decision"]
    assert (decision["outcome"], decision["rule_id"]) == (outcome, rule_id)
    assert answered
