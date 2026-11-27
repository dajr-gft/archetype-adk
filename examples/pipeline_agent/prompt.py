"""The instructions of the two model nodes of the pipeline.

Each instruction is a function: ADK sends what it returns as it is (no substitution of
braces), and the function reads what it needs from the session state itself.
"""

from __future__ import annotations

import json

from google.adk.agents.readonly_context import ReadonlyContext

INTAKE = """\
Extract the discount request from the user's message.
- Amounts, percentages and numbers: copy them as the user wrote them. Do not compute,
  convert, round or correct them.
- A field that has a list of codes: return the code that means what the user wrote, in
  whatever language the user wrote it.
- Do not guess: a field the user did not give is null.
"""

PRESENT = """\
Tell the user the outcome of the discount request, in the language of the user's message,
in one or two sentences. State the outcome and the reason exactly as given: do not change,
soften or add to them. If the outcome is INCOMPLETE, ask for the missing fields and say
nothing else.
"""


def intake_instruction(context: ReadonlyContext) -> str:
    """What to extract, and what earlier messages of the user already gave."""
    known = context.state.get("request") or {}
    if not known:
        return INTAKE
    return (
        f"{INTAKE}\nEarlier messages already gave: {json.dumps(known)}. Keep each of these "
        "values unless this message changes it."
    )


def present_instruction(context: ReadonlyContext) -> str:
    """The decision that the code made, and the message whose language the answer uses."""
    parts = (context.user_content.parts if context.user_content else None) or []
    message = " ".join(part.text for part in parts if part.text)
    decision = context.state.get("decision") or {}
    return (
        f"{PRESENT}\nThe user's message: {json.dumps(message, ensure_ascii=False)}\n"
        f"The decision: {json.dumps(decision)}"
    )
