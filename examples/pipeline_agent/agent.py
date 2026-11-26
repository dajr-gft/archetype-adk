"""Pipeline pattern: a fixed sequence of legacy steps as an ADK graph workflow.

    START -> intake (model) -> collect (code) -> validate (code) -> decide (code) -> present (model)
                                   |                  `-- invalid ---------------------^
                                   `-- incomplete -------------------------------------^

The model is used at the two ends only: to read the request out of the user's words and
to word the answer. The steps between them are function nodes, so their order, the stop
at the first refusal and the result are code: no model call can skip, reorder or re-decide
them. A request that lacks a field is not decided on a guess: the pipeline keeps what it
has in the session and asks for the rest.

Run:  adk run examples/pipeline_agent
"""

from __future__ import annotations

import os
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.agents.context import Context
from google.adk.apps import App
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.adk.workflow import Workflow
from google.genai import types
from pydantic import BaseModel, Field

from domain_agent.plugins import AuditPlugin

from .domain.rules import SEGMENTS, Decision, check, decide, missing_fields
from .prompt import intake_instruction, present_instruction

DEFAULT_MODEL = "gemini-3.8-flash"
MODEL = os.environ.get("AGENT_MODEL", DEFAULT_MODEL)
TEMPERATURE = float(os.environ.get("AGENT_TEMPERATURE", "0.0"))
GENERATION = types.GenerateContentConfig(
    temperature=TEMPERATURE,
    http_options=types.HttpOptions(
        retry_options=types.HttpRetryOptions(initial_delay=1, attempts=3),
    ),
)


class Extracted(BaseModel):
    """What the intake reads out of the user's message: text as written, null when absent."""

    # Every field has a default: a null of the model may arrive as an absent key.

    segment: str | None = Field(
        default=None,
        description=f"Customer segment: the code of {sorted(SEGMENTS)} that means what the "
        "user wrote, or null.",
    )
    order_amount: str | None = Field(
        default=None,
        description="Order amount exactly as the user wrote it, for example '2,000.00', or null.",
    )
    requested_percent: str | None = Field(
        default=None,
        description="Discount asked for, as the user wrote it, for example '12', or null.",
    )
    years_as_customer: int | None = Field(
        default=None, description="Whole years as a customer, or null when the user did not say."
    )


intake = LlmAgent(
    name="intake",
    model=MODEL,
    instruction=intake_instruction,
    output_schema=Extracted,
    generate_content_config=GENERATION,
)


def _decided(decision: Decision, route: str, **state: Any) -> Event:
    kept = {"decision": decision.as_dict(), **state}
    return Event(output=kept["decision"], actions=EventActions(route=route, state_delta=kept))


def collect_request(ctx: Context, node_input: Extracted) -> Event:
    """VAL-004: keeps what the user gave so far; nothing is decided on a missing field."""
    given = {key: value for key, value in node_input.model_dump().items() if value is not None}
    known = {**(ctx.state.get("request") or {}), **given}
    missing = missing_fields(known)
    if missing:
        decision = Decision("INCOMPLETE", "VAL-004", "FIELDS_MISSING", missing=tuple(missing))
        return _decided(decision, "incomplete", request=known)
    return Event(
        output=known, actions=EventActions(route="complete", state_delta={"request": known})
    )


def validate_request(node_input: dict[str, Any]) -> Event:
    """Stops the pipeline at an invalid request (route "invalid")."""
    checked = check(node_input)
    if isinstance(checked, Decision):
        return _decided(checked, "invalid")
    return Event(output=node_input, actions=EventActions(route="valid"))


def decide_request(node_input: dict[str, Any]) -> Event:
    """Applies the business rules; the decision goes to the session state."""
    request = check(node_input)
    if isinstance(request, Decision):  # not on the edge "valid"; kept for the type checker
        return _decided(request, "decided")
    return _decided(decide(request), "decided")


present = LlmAgent(
    name="present",
    model=MODEL,
    instruction=present_instruction,
    include_contents="none",
    generate_content_config=GENERATION,
)

root_agent = Workflow(
    name="discount_pipeline",
    description="Decides a discount request by the rules of the legacy program.",
    # An edge item is a chain: (a, b, c) is a -> b -> c. A dict is a routing map: the node
    # before it continues on the entry whose key is the route of the Event it returned.
    edges=[
        ("START", intake, collect_request, {"complete": validate_request, "incomplete": present}),
        (validate_request, {"valid": decide_request, "invalid": present}),
        (decide_request, present),
    ],
)

app = App(name="pipeline_agent", root_agent=root_agent, plugins=[AuditPlugin()])
