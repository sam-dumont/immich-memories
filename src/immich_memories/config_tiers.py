"""The three product tiers: CPU classifiers, light GPU models, and an added prose LLM.

`tier: auto` resolves inference capability and the configured LLM, then sets one contract
for preparation and selection. Only ``full`` uses an LLM for selection:

* ``basic``: inexpensive CPU heads and rules, no Marqo/Docling, captions or Laya.
* ``gpu``: every light model. The caption server, the heads and detectors, and Laya for the
  sharing question. Selection still uses the rules reader.
* ``full``: the ``gpu`` tier plus an LLM for prose and polish. It refuses to load without the
  LLM enabled with a nonblank ``model``; named providers fill their hosted URL,
  otherwise a blank ``base_url`` runs locally.

Configured text features (titles and music mood) work on every tier. The sharing question
never goes to an LLM on any tier.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, Literal

from immich_memories.analysis.llm_caption_identity import llm_caption_identity
from immich_memories.config_compute import inference_acceleration
from immich_memories.config_models_editorial_preparation import LLM_CAPTION_WARNING

if TYPE_CHECKING:
    from immich_memories.config_loader import Config

logger = logging.getLogger(__name__)

# Help text reads the config (a broken file still fails) but must contact no service.
_SERVICE_PROBES_OFF: ContextVar[bool] = ContextVar("_SERVICE_PROBES_OFF", default=False)


@contextmanager
def service_probes_off() -> Iterator[None]:
    """Resolve an auto tier as basic without asking the inference service."""
    token = _SERVICE_PROBES_OFF.set(True)
    try:
        yield
    finally:
        _SERVICE_PROBES_OFF.reset(token)


ProductTier = Literal["basic", "gpu", "full"]
TierSetting = Literal["auto", ProductTier]

# (section path, field) -> value, per tier. The section path is walked from the Config.
_READER = ("editorial",), "reader"
_PREPARATION = ("editorial", "preparation"), "tier"
_LAYA = ("editorial",), "laya_audience"
_DETECTORS = ("editorial",), "detectors_enabled"

TIERS: dict[str, dict[tuple[tuple[str, ...], str], Any]] = {
    "basic": {_READER: "rules", _PREPARATION: "no_captions", _LAYA: False, _DETECTORS: False},
    "gpu": {_READER: "rules", _PREPARATION: "full", _LAYA: True, _DETECTORS: True},
    "full": {_READER: "model", _PREPARATION: "full", _LAYA: True, _DETECTORS: True},
}


def nas_draft_config(config: Config) -> Config:
    """Keep the film's detector policies while making its first pass without captions or Laya."""
    draft = config.model_copy(deep=True)
    draft.tier = "basic"
    draft.editorial.reader = "rules"
    draft.editorial.laya_audience = False
    draft.editorial.preparation.caption_provider = "smolvlm"
    if draft.editorial.preparation.demands_captions:
        draft.editorial.preparation.tier = "no_captions"
    return draft


def _section(config: Config, path: tuple[str, ...]) -> Any:
    section: Any = config
    for name in path:
        section = getattr(section, name)
    return section


def apply_tier(config: Config) -> dict[str, Any]:
    """Resolve one product tier and apply its preparation and reader contract."""
    applied = _apply_caption_provider(config)
    if config.tier == "auto" and _SERVICE_PROBES_OFF.get():
        config.tier = "basic"
        applied["tier"] = config.tier
    if config.tier == "auto":
        accelerated, reason = inference_acceleration(config.inference)
        config.tier = "basic"
        if accelerated:
            config.tier = "full" if _llm_configured(config) else "gpu"
        applied["tier"] = config.tier
        logger.info(
            "Tier auto resolved to %s on this machine. %s. "
            "A container without the GPU resolves its own; pin the install with tier: gpu or full",
            config.tier,
            reason,
        )
    if config.tier == "full":
        _require_llm_endpoint(config)
    elif config.llm.enabled and config.llm.model.strip():
        logger.warning(
            "The configured LLM can supply titles and music mood; selection stays on %s. "
            "Model refinement requires GPU capability and the full tier's caption and Laya services.",
            config.tier,
        )
    for (path, field), value in TIERS[config.tier].items():
        section = _section(config, path)
        if field in section.model_fields_set and getattr(section, field) != value:
            logger.warning(
                "Ignoring %s: selection tier %s requires %s",
                ".".join((*path, field)),
                config.tier,
                value,
            )
        setattr(section, field, value)
        applied[".".join((*path, field))] = value
    return applied


def _apply_caption_provider(config: Config) -> dict[str, Any]:
    if config.editorial.preparation.caption_provider != "llm":
        return {}
    if not _llm_configured(config):
        raise ValueError("caption_provider: llm needs an enabled LLM and model")
    logger.warning(LLM_CAPTION_WARNING)
    config.editorial.description_model = llm_caption_identity(
        config.llm, config.editorial.preparation.caption_artifact_id
    )
    return {"editorial.description_model": config.editorial.description_model}


def _llm_configured(config: Config) -> bool:
    llm = config.llm
    return bool(llm.enabled and llm.model.strip())


def _require_llm_endpoint(config: Config) -> None:
    if not _llm_configured(config):
        raise ValueError(
            "tier: full needs an enabled LLM: set advanced.llm.enabled: true and choose "
            "a model. A blank base_url runs locally; a URL uses that server. "
            "Choose tier: gpu for every light model and no LLM"
        )
