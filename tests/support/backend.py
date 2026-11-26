"""Archetype-owned. A gate that needs a model does not pass by not running."""

import os

import pytest


def require_backend() -> None:
    """Fails without a Gemini backend, unless the gate was switched off on purpose."""
    if (
        os.getenv("GOOGLE_API_KEY")
        or os.getenv("GEMINI_API_KEY")
        or os.getenv("GOOGLE_CLOUD_PROJECT")
    ):
        return
    if os.getenv("EVAL_GATE", "").lower() == "off":
        pytest.skip("EVAL_GATE=off")
    pytest.fail(
        "This gate calls the model and no backend is configured (see .env.example). "
        "The model-free gates: pytest -m 'not model'. To skip on purpose: EVAL_GATE=off.",
        pytrace=False,
    )
