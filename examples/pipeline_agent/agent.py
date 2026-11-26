"""Pipeline pattern: a fixed sequence of legacy steps as an ADK graph workflow.

    START -> intake (model) -> validate (code) -> decide (code) -> present (model)
                                    `-- invalid --------------------^

The model is used at the two ends only: to read the request out of the user's words and
to word the answer. Validation and decision are function nodes, so the order of the
steps, the stop at the first refusal and the result are code: no model call can skip,
reorder or re-decide them.

Run:  adk run examples/pipeline_agent
"""

from __future__ import annotations

import os

from google.adk.agents import LlmAgent
from google.adk.apps import App
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.adk.workflow import Workflow
from google.genai import types

from .rules import DiscountRequest, decide, validate

MODEL = os.environ.get("AGENT_MODEL", "gemini-3.8-flash")
GENERATION = types.GenerateContentConfig(temperature=0.0)

intake = LlmAgent(
    name="intake",
    model=MODEL,
    instruction=(
        "Extract the discount request from the user's message. Copy the values the user "
        "gave; do not compute, round or correct them. Amounts are returned in cents."
    ),
    output_schema=DiscountRequest,
    generate_content_config=GENERATION,
)


def validate_request(node_input: DiscountRequest) -> Event:
    """Stops the pipeline at an invalid request (route "invalid")."""
    refusal = validate(node_input)
    if refusal is not None:
        return Event(
            actions=EventActions(route="invalid", state_delta={"decision": refusal.model_dump()})
        )
    return Event(output=node_input.model_dump(), actions=EventActions(route="valid"))


def decide_request(node_input: DiscountRequest) -> Event:
    """Applies the business rules; the decision goes to the session state."""
    decision = decide(node_input).model_dump()
    return Event(output=decision, actions=EventActions(state_delta={"decision": decision}))


present = LlmAgent(
    name="present",
    model=MODEL,
    instruction=(
        "Tell the user the result of the discount request, in the user's language, in one "
        "or two sentences. The decision is: {decision}. State its outcome and reason as "
        "given; do not change, soften or add to them."
    ),
    include_contents="none",
    generate_content_config=GENERATION,
)

root_agent = Workflow(
    name="discount_pipeline",
    description="Decides a discount request by the rules of the legacy program.",
    # An edge item is a chain: (a, b, c) is a -> b -> c. A dict is a routing map: the node
    # before it continues on the edge whose key is the route of the Event it returned.
    edges=[
        ("START", intake, validate_request, {"valid": decide_request, "invalid": present}),
        (decide_request, present),
    ],
)

app = App(name="pipeline_agent", root_agent=root_agent)
