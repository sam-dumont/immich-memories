"""What a text stage asks the model, and what one answered call records."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from immich_memories.analysis.llm.providers import resolved_llm_config
from immich_memories.analysis.llm.text_identity import COMPLETE_RETRY_POLICY, text_judgment_key

if TYPE_CHECKING:
    from immich_memories.db import Store


@dataclass(frozen=True)
class TextCall:
    prompt: str
    raw: str
    wall_seconds: float
    cache_hit: bool
    thinking: bool
    warning: str | None = None


@dataclass(frozen=True)
class TextRequest:
    prompt: str
    llm_config: Any
    judgments: Store
    max_tokens: int
    timeout_seconds: int
    thinking: bool = False
    json_object: bool = False
    refresh: bool = False
    json_fields: tuple[str, ...] = ()
    json_empty_array_pairs: tuple[tuple[str, str], ...] = ()
    json_optional_fields: tuple[str, ...] = ()
    response_format: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        from immich_memories.analysis.judgments.json_completion import (
            validate_empty_array_pairs,
            validate_optional_fields,
        )

        if self.json_fields and not self.json_object:
            raise ValueError("JSON fields require the JSON response contract")
        validate_empty_array_pairs(self.json_fields, self.json_empty_array_pairs)
        validate_optional_fields(self.json_fields, self.json_optional_fields)

    @property
    def judgment_key(self) -> str:
        from immich_memories.analysis.judgments.json_completion import (
            JSON_EMPTY_ARRAY_POLICY,
            JSON_FIELDS_POLICY,
            JSON_OPTIONAL_FIELDS_POLICY,
            JSON_RECOVERY_POLICY,
        )

        return text_judgment_key(
            resolved_llm_config(self.llm_config),
            self.prompt,
            thinking=self.thinking,
            max_tokens=self.max_tokens,
            temperature=0.0,
            require_complete=True,
            response_format=self.response_format,
            policy=COMPLETE_RETRY_POLICY
            + (f"/{JSON_RECOVERY_POLICY}" if self.json_object else "")
            + (
                f"/{JSON_FIELDS_POLICY}:" + json.dumps(sorted(set(self.json_fields)))
                if self.json_fields
                else ""
            )
            + (
                f"/{JSON_EMPTY_ARRAY_POLICY}:" + json.dumps(sorted(self.json_empty_array_pairs))
                if self.json_empty_array_pairs
                else ""
            )
            + (
                f"/{JSON_OPTIONAL_FIELDS_POLICY}:"
                + json.dumps(sorted(set(self.json_optional_fields)))
                if self.json_optional_fields
                else ""
            ),
        )
