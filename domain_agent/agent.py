"""ADK 2.0 archetype: a legacy business domain modeled as a Google ADK agent.

Each cohesive domain that Wynxx extracts from the legacy monolith becomes one
``LlmAgent``. The domain's operations are exposed as function tools and its
business rules live in the agent instruction. The module-level ``root_agent`` is
the entry point the ADK CLI (``adk run`` / ``adk web``) discovers.

Generated agents replace the illustrative ``orders`` domain with the domain being
modernized.
"""

from google.adk.agents import LlmAgent

from .prompt import DOMAIN_INSTRUCTION
from .tools import execute_operation, list_capabilities

# Gemini on Vertex AI (global endpoint). Flash by default; switch reasoning-heavy
# domains to "gemini-3.1-pro-preview". The backend is selected in .env
# (GOOGLE_GENAI_USE_VERTEXAI=TRUE).
MODEL = "gemini-3.5-flash"

root_agent = LlmAgent(
    name="orders_domain_agent",
    model=MODEL,
    description=(
        "Modernized 'Orders' business domain (migrated from a legacy Java service). "
        "A coordinator agent routes Orders-related requests here."
    ),
    instruction=DOMAIN_INSTRUCTION,
    tools=[list_capabilities, execute_operation],
)
