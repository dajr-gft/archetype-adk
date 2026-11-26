"""Archetype-owned. Loads ``.env`` so that every gate uses the configured backend."""

from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # python-dotenv is installed with google-adk
    pass
else:
    load_dotenv(Path(__file__).parent / ".env")
