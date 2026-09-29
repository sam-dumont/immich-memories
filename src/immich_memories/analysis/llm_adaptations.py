"""Request changes learned from explicit provider capability refusals."""

import json
import logging
import re

from immich_memories.analysis.llm_providers import LOWEST_THINKING_LEVEL

logger = logging.getLogger(__name__)

# z.ai's OpenAI-compatible route refuses "off" outright on the models that
# always reason: HTTP 400 code 1210, "This model always engages in thinking and
# cannot be disabled; please use low, high, or max".
THINKING_REQUIRED_CODE = "1210"
_LOWEST_LEVEL_ADAPTATION = "lowest_thinking_level"
_NO_REASONING_EFFORT = "no_reasoning_effort"


def adaptation_for(error: dict) -> str | None:
    if str(error.get("code", "")) == THINKING_REQUIRED_CODE:
        return _LOWEST_LEVEL_ADAPTATION
    message = str(error.get("message", ""))
    if "chat_template_kwargs" in message:
        return "no_chat_template_kwargs"
    if "max_tokens" in message and "max_completion_tokens" in message:
        return "max_completion_tokens"
    if "temperature" in message and ("not support" in message or "Unsupported" in message):
        return "default_temperature"
    if schema_mode := _schema_adaptation(message):
        return schema_mode
    if "repetition_penalty" in message:
        return NO_REPETITION_PENALTY
    # A rejected value still means the parameter exists. Removing it would
    # silently select the provider's default effort (medium on Luna), and the
    # learned adaptation would then erase even valid values on later calls.
    if error.get("param") == "reasoning_effort" and error.get("code") in {
        "unsupported_parameter",
        "unknown_parameter",
    }:
        return _NO_REASONING_EFFORT
    if re.search(
        r"\b(?:unknown|unsupported|unrecognized) parameter:?\s*['\"]?reasoning_effort\b",
        message,
        re.IGNORECASE,
    ):
        return _NO_REASONING_EFFORT
    return None


def _schema_adaptation(message: str) -> str | None:
    normalized = message.lower().replace("_", " ")
    schema_field = "response format" in normalized or "json schema" in normalized
    unsupported = any(
        term in normalized
        for term in (
            "not support",
            "unsupported",
            "unknown parameter",
            "unrecognized",
            "not capable",
        )
    )
    if schema_field and unsupported:
        return "json_object" if "json object" in normalized else NO_RESPONSE_FORMAT
    return None


NO_RESPONSE_FORMAT = "no_response_format"
NO_REPETITION_PENALTY = "no_repetition_penalty"


def apply_adaptations(payload: dict, adaptations: set[str]) -> None:
    if ({"json_object", NO_RESPONSE_FORMAT} & adaptations) and payload.get(
        "response_format", {}
    ).get("type") == "json_schema":
        schema = payload["response_format"]["json_schema"]["schema"]
        payload["messages"] = [
            *payload["messages"],
            {
                "role": "user",
                "content": "Return a JSON object matching this schema: " + json.dumps(schema),
            },
        ]
        payload["response_format"] = {"type": "json_object"}
    if NO_RESPONSE_FORMAT in adaptations:
        payload.pop("response_format", None)
    if NO_REPETITION_PENALTY in adaptations:
        payload.pop("repetition_penalty", None)
    if "no_chat_template_kwargs" in adaptations:
        payload.pop("chat_template_kwargs", None)
    if "max_completion_tokens" in adaptations and "max_tokens" in payload:
        payload["max_completion_tokens"] = payload.pop("max_tokens")
    if "default_temperature" in adaptations:
        payload.pop("temperature", None)
    if _NO_REASONING_EFFORT in adaptations:
        # A host that refuses the field still reasons; the raised ceiling is
        # what keeps the answer intact, and that is not sent back.
        payload.pop("reasoning_effort", None)
    if _LOWEST_LEVEL_ADAPTATION in adaptations:
        # The refusal is only ever to "off": a level the model will reason at
        # is left exactly as the caller asked for it.
        thinking = payload.get("thinking")
        if isinstance(thinking, dict) and thinking.get("type") == "disabled":
            payload["thinking"] = {"type": LOWEST_THINKING_LEVEL}


def announce_adaptation(adaptation: str, before: object, after: object) -> None:
    if adaptation == _LOWEST_LEVEL_ADAPTATION:
        logger.warning(
            "LLM provider refused thinking %s (code %s); retrying once with %s",
            before,
            THINKING_REQUIRED_CODE,
            after,
        )
    else:
        logger.info("LLM server dialect: adapting request (%s)", adaptation)
