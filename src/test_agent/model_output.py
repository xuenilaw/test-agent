"""Deterministic cleanup of model replies before strict schema validation."""
import re

_FENCE = re.compile(r"\A\s*```(?:json)?[ \t]*\n((?:(?!```).)*)\n[ \t]*```\s*\Z", re.DOTALL | re.IGNORECASE)


def unwrap_json_fence(text: str) -> str:
    """Remove one outer Markdown code fence; anything else is returned unchanged."""
    match = _FENCE.match(text)
    return match.group(1) if match else text
