import re
from collections.abc import Mapping
from typing import Any


class Redactor:
    """Scrub configured patterns recursively without modifying the input."""

    def __init__(self, patterns: list[str]):
        self.patterns = [re.compile(pattern, re.IGNORECASE | re.MULTILINE) for pattern in patterns]

    def redact(self, value: Any) -> Any:
        if isinstance(value, str):
            # Keep replacement markers opaque even when a configured pattern matches them.
            for pattern in self.patterns:
                value = "[REDACTED]".join(
                    pattern.sub("[REDACTED]", part) for part in value.split("[REDACTED]")
                )
            return value
        if isinstance(value, Mapping):
            return {self.redact(k): self.redact(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.redact(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self.redact(item) for item in value)
        return value
