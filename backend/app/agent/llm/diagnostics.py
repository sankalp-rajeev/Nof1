"""Bounded provider diagnostics with request-data and credential redaction."""

import json
import re
from collections.abc import Sequence

from pydantic import JsonValue

from app.agent.llm.base import LLMMessage, ProviderError

ERROR_LIMIT = 300


def safe_error(
    error: Exception, messages: Sequence[LLMMessage], secrets: Sequence[str] = ()
) -> str:
    if not isinstance(error, ProviderError):
        return f"{type(error).__name__} | HTTP unknown | Google unknown | client_error"[
            :ERROR_LIMIT
        ]
    taints = {secret for secret in secrets if secret}

    def strings(value: JsonValue) -> None:
        if isinstance(value, str):
            taints.add(value)
        elif isinstance(value, list):
            for item in value:
                strings(item)
        elif isinstance(value, dict):
            for item in value.values():
                strings(item)

    for message in messages:
        if message.role != "system":
            taints.add(message.content)
            try:
                strings(json.loads(message.content))
            except (ValueError, TypeError):
                pass
    # Errors may echo only a fragment of a structured user field.
    taints.update(word for value in tuple(taints) for word in re.findall(r"\w+", value))
    detail = error.provider_message or error.code
    for secret in secrets:
        if secret:
            detail = detail.replace(secret, "[REDACTED]")
    for value in sorted(taints, key=len, reverse=True):
        if value:
            detail = re.sub(
                r"(?<!\w)" + re.escape(value) + r"(?!\w)", "[REDACTED]", detail, flags=re.I
            )
    prefix = (
        f"{error.exception_class} | HTTP {error.status_code or 'unknown'} | "
        f"Google {error.google_status or 'unknown'} | "
    )
    return (prefix + detail)[:ERROR_LIMIT]
