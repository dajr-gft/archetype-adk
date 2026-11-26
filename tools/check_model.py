"""Preflight: does the configured model answer in the configured project and region?

    python tools/check_model.py                 # the model the agent will use
    python tools/check_model.py gemini-3.5-flash gemini-3.8-flash

Model availability depends on the project and on the region (a version served on the
``global`` endpoint may not be served in a regional one). A model that is not available
fails at the first user turn with 404 NOT_FOUND, so check before deploying.
"""

from __future__ import annotations

import os
import sys

from google import genai


def answers(client: genai.Client, model: str) -> tuple[bool, str]:
    try:
        response = client.models.generate_content(model=model, contents="Reply with: OK")
    except Exception as error:  # the SDK raises several types; the message is what matters
        return False, str(error).splitlines()[0][:120]
    return True, response.model_version or model


def main() -> int:
    default = os.environ.get("AGENT_MODEL", "")
    if not default:
        from domain_agent.agent import DEFAULT_MODEL

        default = DEFAULT_MODEL
    models = sys.argv[1:] or [default]
    client = genai.Client()
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "(API key backend)")
    failed = 0
    for model in models:
        ok, detail = answers(client, model)
        failed += not ok
        print(f"{'OK  ' if ok else 'FAIL'} {model} @ {location}: {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sys.exit(main())
