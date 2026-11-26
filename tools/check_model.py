"""Preflight: does the configured model answer in the configured project and region?

    python tools/check_model.py                 # the model the agent will use
    python tools/check_model.py gemini-3.5-flash gemini-3.8-flash

Model availability depends on the project and on the region (a version served on the
``global`` endpoint may not be served in a regional one). A model that is not available
fails at the first user turn with 404 NOT_FOUND, so check before deploying. The backend is
read from the environment and from ``.env``.
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def default_model() -> str:
    """DEFAULT_MODEL of the agent package, read from its source."""
    for path in sorted(ROOT.glob("*/agent.py")):
        if path.parent.name in {"tests", "tools", "examples"}:
            continue
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.Assign) and ast.unparse(node.targets[0]) == "DEFAULT_MODEL":
                if isinstance(node.value, ast.Constant):
                    return str(node.value.value)
    return ""


def main() -> int:
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    models = sys.argv[1:] or [os.environ.get("AGENT_MODEL") or default_model()]
    where = os.environ.get("GOOGLE_CLOUD_LOCATION") or "the Gemini API"
    try:
        from google import genai

        client = genai.Client()
    except Exception as error:  # the SDK raises several types when no backend is configured
        print(f"No backend is configured (see .env.example): {str(error).splitlines()[0][:160]}")
        return 2
    failed = 0
    for model in models:
        try:
            response = client.models.generate_content(model=model, contents="Reply with: OK")
            print(f"OK   {model} @ {where}: served by {response.model_version or model}")
        except Exception as error:  # the message is what matters
            failed += 1
            print(f"FAIL {model} @ {where}: {str(error).splitlines()[0][:160]}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
