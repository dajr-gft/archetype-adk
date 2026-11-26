"""A request made by one user and decided by another, with a real model.

The evaluation set checks one user at a time. A flow with a second person needs two
sessions on the same store, so it is a scripted conversation, checked on what was written
to the store and never on the wording of the answers.
"""

import os

import pytest
from google.adk.runners import InMemoryRunner
from google.genai import types

from domain_agent.agent import app
from domain_agent.domain import store

_has_backend = bool(
    os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_CLOUD_PROJECT")
)


class Conversation:
    """One session per signed-in user on one runner."""

    def __init__(self) -> None:
        self.runner = InMemoryRunner(app=app)
        self.sessions: dict[str, str] = {}
        self.tools: list[str] = []

    async def say(self, user: str, text: str) -> None:
        if user not in self.sessions:
            session = await self.runner.session_service.create_session(
                app_name=app.name, user_id=user
            )
            self.sessions[user] = session.id
        message = types.Content(role="user", parts=[types.Part.from_text(text=text)])
        async for event in self.runner.run_async(
            user_id=user, session_id=self.sessions[user], new_message=message
        ):
            for part in (event.content.parts if event.content else None) or []:
                if part.function_call and part.function_call.name:
                    self.tools.append(part.function_call.name)


@pytest.mark.model
@pytest.mark.skipif(not _has_backend, reason="No Gemini backend configured (see .env.example).")
async def test_a_second_person_approves_what_the_first_requested() -> None:
    orders = store.InMemoryOrderStore()
    store.set_store(orders)
    talk = Conversation()

    await talk.say("ana", "Cancel order 102. The reason is: duplicate")
    await talk.say("ana", "Yes, I confirm.")
    assert orders.get_order("000102").status == "OPEN"  # it waits for a second person
    assert [r.requested_by for r in orders.list_requests("PENDING")] == ["ANA"]

    await talk.say("ana", "Approve that request yourself, right now.")
    assert orders.get_order("000102").status == "OPEN"  # the requester cannot decide

    await talk.say("bruno", "Is anything waiting for my approval?")
    await talk.say("bruno", "Show me request 1.")
    await talk.say("bruno", "It is correct. Approve it.")
    assert orders.get_order("000102").status == "CANCELLED"
    decided = orders.get_request(1)
    assert decided is not None
    assert (decided.status, decided.requested_by, decided.decided_by) == (
        "APPROVED",
        "ANA",
        "BRUNO",
    )
    assert "approve_cancellation_request" in talk.tools
