"""Archetype-owned. The real tools and plugins of an agent, driven by a script, not a model.

A test says what the "model" does in each turn (which tools it calls, with which
arguments) and reads what the tools answered. Everything else is real: the ADK runner,
the session and its events, the tool declarations, the plugins. So a test of the guards
does not depend on what a model happens to do, costs nothing and needs no credentials.

    talk = Conversation(tools=[...])
    answers = await talk.turn("ana", "cancel order 101", ("prepare_order_cancellation",
                              {"order_id": "101", "reason": "duplicate"}))
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Callable, Sequence
from typing import Any

from google.adk.agents import Agent
from google.adk.agents.base_agent import BaseAgent
from google.adk.apps import App
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import InMemoryRunner
from google.genai import types

from domain_agent.plugins import AuditPlugin

Call = tuple[str, dict[str, Any]]
Step = Sequence[Call] | str  # the tool calls of one model step, or the text it answers


class ScriptedModel(BaseLlm):
    """Answers each request with the next step of its script."""

    model: str = "scripted"
    steps: list[list[types.Part]] = []
    requests: list[LlmRequest] = []

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        self.requests.append(llm_request)
        parts = self.steps.pop(0) if self.steps else [types.Part(text="(nothing scripted)")]
        yield LlmResponse(content=types.Content(role="model", parts=parts))


class Conversation:
    """Sessions of several users on one app whose model is scripted."""

    def __init__(
        self,
        tools: Sequence[Callable[..., Any] | Any],
        app_name: str = "domain_agent",
        root: Callable[[Agent], BaseAgent] | None = None,
    ) -> None:
        self.model = ScriptedModel(steps=[], requests=[])
        agent = Agent(
            name="scripted_agent",
            model=self.model,
            description="The agent under test.",
            static_instruction="scripted",
            tools=list(tools),
        )
        self.app = App(
            name=app_name, root_agent=root(agent) if root else agent, plugins=[AuditPlugin()]
        )
        self.runner = InMemoryRunner(app=self.app)
        self.sessions: dict[str, str] = {}

    async def open(self, user: str, state: dict[str, Any] | None = None) -> str:
        """Opens the session of a user (``turn`` opens it when needed)."""
        session = await self.runner.session_service.create_session(
            app_name=self.app.name, user_id=user, state=state
        )
        self.sessions[user] = session.id
        return session.id

    async def run(
        self,
        user: str,
        message: str,
        steps: Sequence[Step],
        state_delta: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """One message of the user, answered by the given model steps.

        Returns what each tool answered, in order.
        """
        if user not in self.sessions:
            await self.open(user)
        self.model.steps = [
            [types.Part(text=step)]
            if isinstance(step, str)
            else [
                types.Part(function_call=types.FunctionCall(name=name, args=arguments))
                for name, arguments in step
            ]
            for step in steps
        ]
        answers: list[dict[str, Any]] = []
        content = types.Content(role="user", parts=[types.Part.from_text(text=message)])
        async for event in self.runner.run_async(
            user_id=user,
            session_id=self.sessions[user],
            new_message=content,
            state_delta=state_delta,
        ):
            for part in (event.content.parts if event.content else None) or []:
                if part.function_response is not None:
                    answers.append(dict(part.function_response.response or {}))
        return answers

    async def turn(
        self,
        user: str,
        message: str,
        *calls: Call,
        together: bool = False,
        state_delta: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """One message of the user; the model calls the tools, then answers "done".

        ``together`` sends all the calls in one model step (parallel tool calls) instead
        of one step per call.
        """
        steps: list[Step] = [list(calls)] if together and calls else [[call] for call in calls]
        return await self.run(user, message, [*steps, "done"], state_delta)

    async def state(self, user: str) -> dict[str, Any]:
        """The session state of a user, as the session service keeps it."""
        session = await self.runner.session_service.get_session(
            app_name=self.app.name, user_id=user, session_id=self.sessions[user]
        )
        assert session is not None
        return dict(session.state)
