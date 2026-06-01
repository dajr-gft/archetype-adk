"""ADK 2.1 archetype: a legacy business domain modeled as a Google ADK agent.

Each cohesive domain that Wynxx extracts from the legacy monolith becomes one
``LlmAgent``. The domain's operations are exposed as function tools and its
business rules live in the agent instruction. The module-level ``root_agent`` is
the entry point the ADK CLI (``adk run`` / ``adk web``) discovers.

Generated agents replace the illustrative ``orders`` domain with the domain being
modernized. See ``archetype.md`` for the full pattern catalogue (pipeline vs
dispatcher, generation config, planners, structured output, evaluation).
"""

from google.adk.agents import LlmAgent
from google.genai import types

from .callbacks import audit_tool_call
from .prompt import DOMAIN_INSTRUCTION
from .tools import execute_operation, list_capabilities

# ── Model ─────────────────────────────────────────────────────────────────────
# Gemini on Vertex AI (global endpoint). Default to the latest stable Flash tier
# via the `-latest` selector (requires the `global` endpoint set in .env).
#
# For auditable/compliance domains, PIN a specific GA version instead of `-latest`
# (e.g. a pinned `gemini-*-flash` GA release) so decisions are reproducible and do
# not silently drift when Google rotates the alias. Reserve a `gemini-pro-*` GA
# tier for genuinely reasoning-heavy domains — and prefer adding a `planner`
# (see archetype.md) before escalating the model tier. Never default to a
# `-preview` model: preview models carry availability/quota limitations.
MODEL = "gemini-flash-latest"

# ── Generation config ─────────────────────────────────────────────────────────
# Business-rule agents must not re-roll their evaluation: pin temperature to 0 for
# the most deterministic decoding the model allows. `temperature=0` is strong but
# not a byte-for-byte determinism guarantee — the eval gate (tests/) is what
# actually locks behaviour. `HttpRetryOptions` adds resilience to transient 429s.
GENERATION = types.GenerateContentConfig(
    temperature=0.0,
    http_options=types.HttpOptions(
        retry_options=types.HttpRetryOptions(initial_delay=1, attempts=3),
    ),
)

root_agent = LlmAgent(
    name="orders_domain_agent",
    model=MODEL,
    description=(
        "Modernized 'Orders' business domain (migrated from a legacy Java service). "
        "A coordinator agent routes Orders-related requests here."
    ),
    instruction=DOMAIN_INSTRUCTION,
    tools=[list_capabilities, execute_operation],
    generate_content_config=GENERATION,
    after_tool_callback=audit_tool_call,
)
