"""The agent of the domain and the app that hosts it (Google ADK 2.x).

``root_agent`` is what ``adk run`` / ``adk web`` discover; ``app`` is what a runner and a
deployment use (plugins, resumability, context settings). ``App.name`` is the name of
this package: ADK resolves sessions by it.

See ``archetype.md`` for the patterns (conversational agent, graph workflow for a fixed
pipeline) and for what a generated agent may and may not change in this file.
"""

from __future__ import annotations

import os

from google.adk.agents import Agent
from google.adk.apps import App
from google.genai import types

from .plugins import AuditPlugin
from .prompt import DOMAIN_INSTRUCTION
from .tools import (
    approve_cancellation_request,
    find_order,
    list_cancellation_requests,
    prepare_order_cancellation,
    reject_cancellation_request,
    review_cancellation_request,
    submit_order_cancellation,
)

# The model is configuration, not code: which Gemini versions a project can call depends
# on the project and on the region. AGENT_MODEL overrides the default; `python
# tools/check_model.py` verifies that the chosen model answers before anything is deployed.
DEFAULT_MODEL = "gemini-3.8-flash"
MODEL = os.environ.get("AGENT_MODEL", DEFAULT_MODEL)

# temperature 0: the agent must not re-roll what it does with the same request. It is not
# a guarantee of identical text; the evaluation gate is what holds behaviour.
GENERATION = types.GenerateContentConfig(
    temperature=0.0,
    http_options=types.HttpOptions(
        retry_options=types.HttpRetryOptions(initial_delay=1, attempts=3),
    ),
)

root_agent = Agent(
    name="orders_agent",
    model=MODEL,
    description="Looks up orders and cancels them, with approval by a second person.",
    instruction=DOMAIN_INSTRUCTION,
    tools=[
        find_order,
        prepare_order_cancellation,
        submit_order_cancellation,
        list_cancellation_requests,
        review_cancellation_request,
        approve_cancellation_request,
        reject_cancellation_request,
    ],
    generate_content_config=GENERATION,
)

app = App(name="domain_agent", root_agent=root_agent, plugins=[AuditPlugin()])
