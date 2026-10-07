"""What each setting accepts, for the Settings page's editor (#2234).

Reads the schema the save path validates against (`settings_edit.field_type`), so the
editor and the save can't disagree about a list of values or a bound. The labels are
English only and live here, outside the translation catalogue: the other languages show
the same text until someone translates them.
"""

from __future__ import annotations

import enum
import types
from typing import Annotated, Any, Literal, Union, get_args, get_origin

from immich_memories.settings_edit import field_type
from immich_memories.web.schemas import SettingChoice, SettingInput

_LOCALES = {
    "auto": "Automatic (follow the library)",
    "en": "English",
    "fr": "French",
    "nl": "Dutch",
    "de": "German",
    "es": "Spanish",
    "it": "Italian",
    "pt-BR": "Portuguese (Brazil)",
    "pt-PT": "Portuguese (Portugal)",
    "pl": "Polish",
    "sv": "Swedish",
    "ru": "Russian",
    "ja": "Japanese",
    "zh-Hans": "Chinese (Simplified)",
    "ko": "Korean",
}

_LABELS: dict[str, dict[str, str]] = {
    "tier": {
        "auto": "Automatic (from what the server can do)",
        "basic": "Basic (no model, runs anywhere)",
        "gpu": "GPU (pictures read on a GPU)",
        "full": "Full (GPU and a language model)",
    },
    "preset": {"fast": "Fast (CPU only, NAS)"},
    "output.format": {"mp4": "MP4", "mov": "MOV"},
    "output.resolution": {
        "720p": "720p (1280x720)",
        "1080p": "1080p (1920x1080)",
        "4k": "4K (3840x2160)",
    },
    "output.codec": {
        "h264": "H.264, software (libx264)",
        "h265": "H.265, software (libx265)",
        "prores": "ProRes (large files)",
    },
    "output.codec_policy": {
        "prefer_hardware": "Prefer hardware, fall back to software",
        "strict": "Hardware only, fail if it is missing",
    },
    "output.hdr_mode": {
        "auto": "Automatic (HDR if the clips are)",
        "sdr": "SDR only",
        "hdr": "HDR",
    },
    "output.quality": {"high": "High", "balanced": "Balanced", "fast": "Fast"},
    "defaults.scale_mode": {"fit": "Fit (black bars)", "blur": "Fill with a blurred copy"},
    "defaults.transition": {
        "cut": "Cut",
        "crossfade": "Crossfade",
        "smart": "Smart (mixed per clip)",
        "none": "None",
    },
    "defaults.sharing": {
        "just-us": "Just us",
        "family": "Family",
        "shareable": "Shareable",
    },
    "hardware.backend": {
        "auto": "Automatic",
        "none": "None (software)",
        "nvidia": "NVIDIA (NVENC)",
        "apple": "Apple (VideoToolbox)",
        "vaapi": "VAAPI (Intel and AMD on Linux)",
        "qsv": "Intel Quick Sync",
    },
    "hardware.encoder_preset": {"fast": "Fast", "balanced": "Balanced", "quality": "Quality"},
    "immich.api_version": {
        "auto": "Automatic (ask the server)",
        "v2": "Immich v2",
        "v3": "Immich v3",
    },
    "llm.provider": {
        "ollama": "Ollama",
        "openai-compatible": "OpenAI-compatible server",
        "openai": "OpenAI",
        "zai": "z.ai",
        "anthropic": "Anthropic",
    },
    "llm.thinking": {
        "disabled": "Off",
        "low": "Low",
        "high": "High",
        "max": "Max",
        "auto": "Automatic",
    },
    "llm.batch": {"off": "Off", "auto": "Automatic"},
    "ace_step.mode": {"lib": "Library (runs here)", "api": "API (a server)"},
    "title_screens.locale": _LOCALES,
    "title_screens.fade_color": {"white": "White", "black": "Black"},
    "title_screens.style_mode": {
        "auto": "Automatic",
        "random": "Random",
        "modern_warm": "Modern warm",
        "elegant_minimal": "Elegant minimal",
        "vintage_charm": "Vintage charm",
        "playful_bright": "Playful bright",
        "soft_romantic": "Soft romantic",
    },
    "auth.provider": {
        "basic": "Username and password",
        "oidc": "OpenID Connect",
        "header": "Trusted header",
    },
    "triage.provider": {"auto": "Automatic", "cpu": "CPU", "cuda": "CUDA", "coreml": "Core ML"},
    "editorial.preparation.tier": {
        "full": "Full (descriptions for every picture)",
        "no_captions": "No descriptions",
        "metadata_only": "Metadata only",
    },
    "editorial.preparation.caption_provider": {
        "smolvlm": "SmolVLM (local)",
        "llm": "The language model",
    },
    "editorial.reader": {
        "auto": "Automatic",
        "model": "Language model",
        "rules": "Rules, no model",
    },
}

_TRI_STATE = {"true": "Yes", "false": "No"}


def _readable(value: str) -> str:
    return value.replace("_", " ").replace("-", " ").capitalize()


def _strip(annotation: Any) -> tuple[Any, list[Any]]:
    """The type under any `Annotated` wrapping, and the constraints it carried."""
    metadata: list[Any] = []
    while get_origin(annotation) is Annotated:
        annotation, *extra = get_args(annotation)
        metadata.extend(extra)
    return annotation, metadata


def _members(annotation: Any) -> tuple[list[Any], bool, list[Any]]:
    """The non-None members of a (possibly optional) type, whether None is allowed, and bounds."""
    base, bounds = _strip(annotation)
    if get_origin(base) not in (Union, types.UnionType):
        return [base], False, bounds
    members: list[Any] = []
    for arg in get_args(base):
        inner, more = _strip(arg)
        bounds += more
        members.append(inner if inner is not type(None) else None)
    return [m for m in members if m is not None], None in members, bounds


def _choice(key: str, values: list[str], nullable: bool) -> SettingInput:
    labels = _LABELS.get(key, {})
    choices = [SettingChoice(value=v, label=labels.get(v, _readable(v))) for v in values]
    if nullable:
        choices.insert(0, SettingChoice(value="", label="Not set"))
    return SettingInput(kind="choice", choices=choices, nullable=nullable)


def _bound(bounds: list[Any], name: str) -> float | None:
    return next((getattr(b, name) for b in bounds if hasattr(b, name)), None)


def _number(member: Any, bounds: list[Any], nullable: bool) -> SettingInput:
    low = _bound(bounds, "ge")
    if low is None:
        low = _bound(bounds, "gt")
    high = _bound(bounds, "le")
    if high is None:
        high = _bound(bounds, "lt")
    return SettingInput(
        kind="number",
        min=low,
        max=high,
        step=1 if member is int else None,
        nullable=nullable,
    )


def _union_hint(members: list[Any]) -> str:
    parts: list[str] = []
    for member in members:
        inner, bounds = _strip(member)
        if get_origin(inner) is Literal:
            parts.extend(str(v) for v in get_args(inner))
        elif inner in (int, float):
            low, high = _bound(bounds, "ge"), _bound(bounds, "le")
            span = f" from {low:g} to {high:g}" if low is not None and high is not None else ""
            parts.append(f"a number{span}")
        else:
            parts.append(getattr(inner, "__name__", str(inner)))
    return "Either " + " or ".join(parts)


def describe_input(key: str, *, secret: bool = False) -> SettingInput:
    """How the editor should ask for this setting: a choice, a number, a switch, a secret or text."""
    members, nullable, bounds = _members(field_type(key))
    if len(members) > 1:
        return SettingInput(kind="text", hint=_union_hint(members), nullable=nullable)
    member = members[0]
    if get_origin(member) is Literal:
        return _choice(key, [str(v) for v in get_args(member)], nullable)
    if isinstance(member, type) and issubclass(member, enum.Enum):
        return _choice(key, [str(m.value) for m in member], nullable)
    if member is bool:
        if nullable:
            yes_no = [SettingChoice(value=v, label=label) for v, label in _TRI_STATE.items()]
            not_set = SettingChoice(value="", label="Not set (automatic)")
            return SettingInput(kind="choice", choices=[not_set, *yes_no], nullable=True)
        return SettingInput(kind="bool")
    if member in (int, float):
        return _number(member, bounds, nullable)
    return SettingInput(kind="secret" if secret else "text", nullable=nullable)
