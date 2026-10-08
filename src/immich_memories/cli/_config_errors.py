"""User-friendly formatting for configuration errors."""

from __future__ import annotations

import yaml
from pydantic import ValidationError


def format_validation_error(error: ValidationError) -> str:
    """Name each bad key and what is wrong with it, never the value it holds.

    The value is left out on purpose: it can be an API key or a password, and for a
    check across the whole config pydantic's input is the entire file.
    """
    lines = ["Configuration error:"]
    for err in error.errors(include_input=False):
        field_path = " -> ".join(str(loc) for loc in err["loc"]) or "config"
        lines.append(f"  {field_path}: {err['msg']}")
    return "\n".join(lines)


def format_yaml_error(error: yaml.YAMLError) -> str:
    """Format a YAML parsing error into a user-friendly message.

    Args:
        error: The YAML error.

    Returns:
        Human-readable error description with line/column if available.
    """
    if hasattr(error, "problem_mark") and error.problem_mark is not None:
        mark = error.problem_mark
        problem = getattr(error, "problem", "unknown error")
        return (
            f"YAML syntax error at line {mark.line + 1}, column {mark.column + 1}:\n"
            f"  {problem}\n"
            f"  Check your config file for correct YAML formatting."
        )

    # WHY: str(error) can quote source context lines, which may sit next to a secret
    # in config.yaml; the message says what to do without echoing any of it.
    return "YAML syntax error.\n  Check your config file for correct YAML formatting."
