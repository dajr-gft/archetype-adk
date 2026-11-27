"""The pipeline example with a real model: the decision that the code wrote to the state.

A workflow is checked on what its function nodes produced, never on the wording of the
answer: the model reads the request (intake) and words the result (present); everything
between them is code, so its result is exact and can be asserted exactly.
"""

from typing import Any

import pytest
from google.adk.runners import InMemoryRunner
from google.genai import types

from examples.pipeline_agent.agent import app
from tests.support.backend import require_backend


class Talk:
    def __init__(self) -> None:
        self.runner = InMemoryRunner(app=app)
        self.session_id = ""
        self.answer = ""

    async def say(self, message: str) -> dict[str, Any]:
        if not self.session_id:
            session = await self.runner.session_service.create_session(
                app_name=app.name, user_id="user"
            )
            self.session_id = session.id
        content = types.Content(role="user", parts=[types.Part.from_text(text=message)])
        async for event in self.runner.run_async(
            user_id="user", session_id=self.session_id, new_message=content
        ):
            parts = (event.content.parts if event.content else None) or []
            if event.author == "present":
                self.answer = " ".join(part.text for part in parts if part.text)
        session = await self.runner.session_service.get_session(
            app_name=app.name, user_id="user", session_id=self.session_id
        )
        assert session is not None
        return dict(session.state["decision"])


CASES = [
    ("Wholesale customer for 7 years, order of 2,000.00, asks 12% discount.", "APPROVED", "BR-003"),
    ("Retail customer for 1 year, order of 300.00, wants 20% off.", "REFERRED", "BR-002"),
    ("Retail customer for 2 years, order of 20.00, asks 5% discount.", "INVALID", "VAL-002"),
    ("Wholesale, 3 years, order 900.00, asks 45%.", "DENIED", "BR-001"),
    (
        "Cliente de atacado há 7 anos, pedido de 2.000,00, pede 12% de desconto.",
        "APPROVED",
        "BR-003",
    ),
]


@pytest.mark.model
@pytest.mark.parametrize(("message", "outcome", "rule_id"), CASES)
async def test_the_decision_is_the_one_of_the_rules(
    message: str, outcome: str, rule_id: str
) -> None:
    require_backend()
    talk = Talk()
    decision = await talk.say(message)
    assert (decision["outcome"], decision["rule_id"]) == (outcome, rule_id)
    assert talk.answer


@pytest.mark.model
async def test_a_value_the_user_did_not_give_is_asked_for_not_invented() -> None:
    require_backend()
    talk = Talk()
    first = await talk.say("Retail customer, order of 300.00, asks 12% discount.")
    assert (first["outcome"], first["missing"]) == ("INCOMPLETE", ["years_as_customer"])
    second = await talk.say("Customer for 6 years.")
    assert (second["outcome"], second["granted_percent"]) == ("APPROVED", "12")
