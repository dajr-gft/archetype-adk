"""Domain operations exposed as ADK function tools.

ADK builds each tool's schema from the function name, type hints and docstring,
so keep all three accurate. Conventions (per the ADK 2.1 docs):
- Type-hint every parameter; omit defaults for values the model must supply.
- Return a ``dict`` with a ``status`` key ("success" | "error").
- Validate inputs and coerce numeric strings *inside the tool* — never raise; the
  tool is where the types and verbatim string codes are known (see archetype.md).
- In a generated agent, each legacy use-case / public service method becomes one
  typed function here, wired to the modernized domain logic.
"""

from typing import Any


def list_capabilities() -> dict[str, Any]:
    """List the operations this domain agent can perform.

    Returns:
        dict: ``status`` plus the list of capability names.
    """
    return {
        "status": "success",
        "capabilities": ["create_order", "get_order", "cancel_order"],
    }


def execute_operation(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Execute a domain operation.

    Args:
        operation: One of the capabilities returned by ``list_capabilities``.
        payload: Operation inputs, validated against the domain rules.

    Returns:
        dict: ``status`` ("success" | "error") plus the operation result, or an
        ``error_message`` when it fails.
    """
    # Generated code replaces this stub with the modernized domain logic
    # (repositories / downstream services).
    return {"status": "success", "operation": operation, "result": payload}
