"""What a deployment (Compose, Kubernetes, Terraform) tells the app about itself.

`IMMICH_MEMORIES_DEPLOYMENT_TIER` (the Compose `.env` `TIER`) is the deployment's one tier:
it sets the config `tier` like an environment variable does, so the `.env` and a config
file can't disagree. The service endpoints it implies are editable defaults, below saved
operator settings.
"""

from collections.abc import Mapping
from contextlib import suppress
from ipaddress import AddressValueError, IPv6Address
from typing import Any
from urllib.parse import urlsplit

DEPLOYMENT_TIER = "IMMICH_MEMORIES_DEPLOYMENT_TIER"


def _validated_preset(environ: Mapping[str, str]) -> str:
    preset = environ.get(DEPLOYMENT_TIER, "basic") or "basic"
    if preset == "nas":
        raise ValueError("tier 'nas' is now called 'basic': set tier: basic")
    if preset not in {"auto", "basic", "gpu", "full"}:
        raise ValueError(f"{DEPLOYMENT_TIER} must be auto, basic, gpu or full")
    return preset


def deployment_tier(environ: Mapping[str, str]) -> dict[str, Any]:
    """The config `tier` the deployment sets, ranked with the environment; empty when unset."""
    if not environ.get(DEPLOYMENT_TIER):
        return {}
    return {"tier": _validated_preset(environ)}


def deployment_defaults(environ: Mapping[str, str]) -> dict[str, Any]:
    """Wire Compose model services without overriding YAML, env or saved Settings."""
    preset = _validated_preset(environ)
    defaults: dict[str, Any] = {}
    gpu_box = environ.get("IMMICH_MEMORIES_DEPLOYMENT_GPU_BOX", "").strip()
    if preset in {"gpu", "full"}:
        inference = _gpu_worker_url(gpu_box) if gpu_box else "http://immich-memories-inference:8092"
        caption = f"{inference}/v1" if gpu_box else "http://immich-memories-captioner:8092/v1"
        defaults.update(
            {
                "inference": {"facts_base_url": inference},
                "editorial": {"preparation": {"caption_base_url": caption}},
            }
        )
    for key, section, field in (
        ("INFERENCE_URL", "inference", "facts_base_url"),
        ("CAPTION_URL", "editorial", "caption_base_url"),
    ):
        variable = f"IMMICH_MEMORIES_DEPLOYMENT_{key}"
        if variable in environ:
            target = defaults.setdefault(section, {})
            if section == "editorial":
                target = target.setdefault("preparation", {})
            target[field] = environ[variable]
    reader = _reader_defaults(environ)
    if reader:
        defaults["llm"] = reader
    return defaults


def _reader_defaults(environ: Mapping[str, str]) -> dict[str, Any]:
    reader: dict[str, Any] = {}
    for variable, field in (
        ("URL", "base_url"),
        ("MODEL", "model"),
        ("ENABLED", "enabled"),
        ("API_KEY", "api_key"),
    ):
        key = f"IMMICH_MEMORIES_DEPLOYMENT_READER_{variable}"
        if key in environ and (environ[key] or variable == "URL"):
            reader[field] = environ[key]
    if reader:
        reader.setdefault("enabled", False)
    return reader


def _gpu_worker_url(address: str) -> str:
    with suppress(AddressValueError):
        address = f"[{IPv6Address(address)}]"
    try:
        parsed = urlsplit(f"http://{address}")
        port = parsed.port
        if (
            not parsed.hostname
            or parsed.username is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
            or address.endswith(":")
        ):
            raise ValueError("invalid worker address")
    except ValueError as error:
        raise ValueError(
            "GPU_BOX must be a hostname or IP with an optional port, without credentials or path"
        ) from error
    return f"http://{address}" if port is not None else f"http://{address}:8092"
