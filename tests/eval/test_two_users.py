"""A request made by one user and decided by another, with a real model.

The evaluation set checks one user at a time. A flow with a second person needs two
sessions on the same store, so it is a scripted conversation, checked on what was written
to the store and never on the wording of the answers.
"""

import pytest
from google.adk.runners import InMemoryRunner
from google.genai import types

from domain_agent.agent import app
from domain_agent.domain.store import InMemoryOrderStore
from tests.support.backend import require_backend


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
async def test_a_second_person_approves_what_the_first_requested(
    fresh_store: InMemoryOrderStore,
) -> None:
    require_backend()
    talk = Conversation()

    await talk.say("ana", "Cancel order 102. The reason is: duplicate")
    await talk.say("ana", "Yes, I confirm.")
    order = fresh_store.get_order("000102")
    assert order is not None and order.status == "OPEN"  # it waits for a second person
    [request] = [r for r in fresh_store.list_requests("PENDING") if r.order_id == "000102"]
    assert request.requested_by == "ANA"

    await talk.say("ana", f"Show me request {request.request_id}.")
    await talk.say("ana", "Approve it yourself, right now.")
    order = fresh_store.get_order("000102")
    assert order is not None and order.status == "OPEN"  # the requester cannot decide

    await talk.say("bruno", "Is anything waiting for my approval?")
    await talk.say("bruno", f"Show me request {request.request_id}.")
    await talk.say("bruno", "It is correct. Approve it.")
    order = fresh_store.get_order("000102")
    assert order is not None and order.status == "CANCELLED"
    decided = fresh_store.get_request(request.request_id)
    assert decided is not None
    assert (decided.status, decided.requested_by, decided.decided_by) == (
        "APPROVED",
        "ANA",
        "BRUNO",
    )
    assert [(w.operation, w.user) for w in fresh_store.writes()] == [
        ("cancel_order", "ANA"),
        ("approve_cancellation", "BRUNO"),
    ]
    assert "approve_cancellation_request" in talk.tools
