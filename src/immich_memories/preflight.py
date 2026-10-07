"""Preflight checks for validating provider connections."""

from __future__ import annotations

import importlib.util
import logging
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import httpx
from pydantic import BaseModel

from immich_memories.config import Config
from immich_memories.db import resolve_location
from immich_memories.db.store import unmigrated_store
from immich_memories.security import sanitize_error_message

logger = logging.getLogger(__name__)


class CheckStatus(Enum):
    """Status of a preflight check."""

    OK = "ok"
    WARNING = "warning"
    ERROR = "error"
    SKIPPED = "skipped"


@dataclass
class CheckResult:
    """Result of a single preflight check."""

    name: str
    status: CheckStatus
    message: str
    details: str | None = None


def _encoder_summary(caps, inference_gpu: bool) -> str:
    """What encodes the film; on the GPU tier also where picture preparation runs."""
    from immich_memories.processing.hardware import HWAccelBackend

    device = caps.device_name or "Unknown"
    if inference_gpu and caps.backend == HWAccelBackend.NVIDIA:
        return f"Encoding on NVENC ({device}); picture preparation on the GPU"
    return f"{caps.backend.value.upper()} ({device})"


def check_hardware(inference_gpu: bool = False) -> CheckResult:
    """Check hardware acceleration availability.

    Returns:
        CheckResult with status and details.
    """
    try:
        from immich_memories.processing.hardware import (
            HWAccelBackend,
            detect_hardware_acceleration,
            nvenc_capability_hint,
        )

        caps = detect_hardware_acceleration()

        if caps.backend == HWAccelBackend.NONE:
            # The capability line leads when there is a card, because `preflight`
            # prints details only under -v and a GPU node encoding in software is
            # a misconfiguration rather than the expected answer (#936).
            hint = nvenc_capability_hint()
            if inference_gpu and not hint:
                return CheckResult(
                    name="Hardware",
                    status=CheckStatus.OK,
                    message="Picture preparation on the GPU; encoding on the CPU (libx264)",
                    details="This pod has no GPU of its own; the inference service has one.",
                )
            return CheckResult(
                name="Hardware",
                status=CheckStatus.WARNING,
                message=hint or "No GPU acceleration",
                details="Video encoding will use CPU (slower)",
            )

        features = []
        if caps.supports_h264_encode:
            features.append("H.264 encode")
        if caps.supports_h265_encode:
            features.append("H.265 encode")
        if caps.opencv_cuda:
            features.append("OpenCV CUDA")

        return CheckResult(
            name="Hardware",
            status=CheckStatus.OK,
            message=_encoder_summary(caps, inference_gpu),
            details=", ".join(features) if features else "Basic acceleration",
        )

    except (ImportError, RuntimeError, OSError) as e:
        return CheckResult(
            name="Hardware",
            status=CheckStatus.WARNING,
            message="Detection failed",
            details=str(e),
        )


def check_title_rendering(config: Config, inference_gpu: bool = False) -> CheckResult:
    """Report whether title screens get the GPU renderer or the PIL fallback."""
    if not config.title_screens.enabled:
        return CheckResult(
            name="Title rendering",
            status=CheckStatus.SKIPPED,
            message="Title screens disabled",
        )
    return _kernel_library_check(inference_gpu)


# The tier's design, not a fault: the GPU lives in the inference service, the app pod has none.
TITLES_ON_CPU_ON_GPU_TIER = "Titles render on the CPU; the GPU is for picture preparation"

_PIL_RENDERER_MESSAGE = "PIL + FFmpeg: animated raster text, still backgrounds (no SDF effects)"


def _kernel_library_check(inference_gpu: bool = False) -> CheckResult:
    """Name the title renderer this machine will use, and why.

    Two ways to lose the kernels, and a self-hoster should meet both here rather
    than after a long run: no wheel for the platform, answered by `find_spec`,
    and a wheel that cannot run here, answered by the child dispatch probe. The
    second is the expensive one, and it is why an installed package is not the
    answer on its own: a CPU without AVX dies on the first kernel (#910).
    """
    # WHY the probe module and not the seam behind it: importing the seam is
    # importing the library, and on a processor without AVX that is the crash
    # this check exists to report (#910).
    from immich_memories.titles.kernel_backend_probe import KERNEL_LIBRARY, python_version_reason

    if importlib.util.find_spec(KERNEL_LIBRARY) is None:
        # The reason leads: details print only under -v, and the interpreter is what a
        # native install on Homebrew's default 3.14 needs to read first (#1987). On any
        # other platform with no wheel, say that instead — reinstalling changes nothing.
        no_wheel_reason = python_version_reason() or (
            f"GPU title kernels unavailable: no {KERNEL_LIBRARY} wheel for {_platform_tag()}"
        )
        message = f"{no_wheel_reason}; titles use PIL + FFmpeg (no SDF effects)"
        return CheckResult(
            name="Title rendering",
            status=CheckStatus.WARNING,
            message=message,
            details=(
                f"{KERNEL_LIBRARY} publishes no wheel for {_platform_tag()}. "
                "Wheels exist for Linux x86_64, Linux aarch64, macOS arm64 and Windows AMD64 "
                "on Python 3.10-3.13; everywhere else title screens are PIL-rendered, "
                "which the log says once at startup."
            ),
        )

    from immich_memories.titles.kernel_backend_probe import kernel_dispatch_failure

    if reason := kernel_dispatch_failure():
        # The reason leads, because `preflight` prints details only under -v and this
        # is the line that tells a self-hoster their processor is the problem.
        return CheckResult(
            name="Title rendering",
            status=CheckStatus.WARNING,
            message=reason,
            details=_PIL_RENDERER_MESSAGE,
        )
    return _kernel_backend_check(inference_gpu)


def _kernel_backend_check(inference_gpu: bool = False) -> CheckResult:
    """Name the backend working kernels land on: a GPU, or the processor (#1202)."""
    import platform

    from immich_memories.titles.kernel_backend_probe import KERNEL_LIBRARY, gpu_backend

    gpu, failures = gpu_backend(platform.system())
    if gpu is None and inference_gpu:
        return CheckResult(
            name="Title rendering",
            status=CheckStatus.OK,
            message=TITLES_ON_CPU_ON_GPU_TIER,
            details="; ".join(failures),
        )
    if gpu is None:
        return CheckResult(
            name="Title rendering",
            status=CheckStatus.WARNING,
            message=f"Kernels on the CPU ({KERNEL_LIBRARY}): no GPU backend started",
            details="; ".join((*failures, "titles render markedly slower than on a GPU")),
        )
    return CheckResult(
        name="Title rendering",
        status=CheckStatus.OK,
        message=f"GPU kernels on {gpu} ({KERNEL_LIBRARY}): animated title screens",
    )


def _platform_tag() -> str:
    """This interpreter as the two things a wheel is chosen by."""
    import platform

    return (
        f"{sys.platform}/{platform.machine()} on Python "
        f"{sys.version_info.major}.{sys.version_info.minor}"
    )


# A failing caption service needs a link to both standalone and worker setup recipes.
# A path, not a URL: the docs travel with the checkout and with the image.
CAPTION_SETUP_PAGE = "docs/better/captions.md"


def _caption_endpoint_unreachable(base_url: str, error: Exception) -> CheckResult:
    return CheckResult(
        name="Captions",
        status=CheckStatus.ERROR,
        message="Caption endpoint unreachable",
        details=(
            f"{base_url}: {sanitize_error_message(str(error))}; "
            f"set one up with {CAPTION_SETUP_PAGE}"
        ),
    )


def check_caption_endpoint(config: Config) -> CheckResult:
    """Report whether the configured caption server advertises the accepted alias."""
    if not config.editorial.preparation.demands_captions:
        return CheckResult(
            name="Captions",
            status=CheckStatus.SKIPPED,
            message=f"Not required by {config.editorial.preparation.tier}",
        )
    if config.editorial.preparation.caption_provider == "llm":
        from immich_memories.config_models_editorial_preparation import LLM_CAPTION_WARNING

        return CheckResult(
            name="Captions",
            status=CheckStatus.WARNING,
            message=f"Explicit LLM captioning: {config.llm.model}",
            details=LLM_CAPTION_WARNING
            + " Image schema controls run before missing captions are acquired.",
        )
    from immich_memories.analysis.editorial_description_contract import API_MODEL
    from immich_memories.analysis.editorial_preparation_captions import (
        CAPTION_KEY_HINT,
        REFUSED_CODES,
        bearer_headers,
    )

    preparation = config.editorial.preparation
    base_url = preparation.caption_base_url
    try:
        response = httpx.get(
            f"{base_url}/models",
            timeout=httpx.Timeout(preparation.caption_timeout_seconds, connect=5.0),
            headers=bearer_headers(preparation.caption_api_key),
        )
        response.raise_for_status()
        rows = response.json().get("data", [])
    except httpx.HTTPStatusError as e:
        if e.response.status_code not in REFUSED_CODES:
            return _caption_endpoint_unreachable(base_url, e)
        return CheckResult(
            name="Captions",
            status=CheckStatus.ERROR,
            message="Caption endpoint refused the request",
            details=f"{base_url} answered HTTP {e.response.status_code}; {CAPTION_KEY_HINT}",
        )
    except httpx.ReadTimeout:
        return CheckResult(
            name="Captions",
            status=CheckStatus.ERROR,
            message="Caption server is slow to answer",
            details=(
                f"{base_url} exceeded editorial.preparation.caption_timeout_seconds "
                f"({preparation.caption_timeout_seconds:g}s). A cold worker may still be loading; "
                "check its logs or increase that timeout, then rerun preflight."
            ),
        )
    except (httpx.HTTPError, ValueError) as e:
        return _caption_endpoint_unreachable(base_url, e)
    served = {row.get("id") for row in rows if isinstance(row, dict)}
    if API_MODEL not in served:
        return CheckResult(
            name="Captions",
            status=CheckStatus.ERROR,
            message="Caption endpoint serves another model",
            details=(
                f"{base_url} advertises {sorted(map(str, served))}, not {API_MODEL}; "
                f"serve it under that alias as in {CAPTION_SETUP_PAGE}"
            ),
        )
    return CheckResult(
        name="Captions",
        status=CheckStatus.OK,
        message=f"Serving {API_MODEL}",
        details=base_url,
    )


# Every path-valued setting that describes the host rather than the library.
# A config is portable until one of these is in it: copied to a second machine
# it still names an interpreter under /Users, or a models directory on a volume
# the new box does not mount, and the failure lands hours later inside a worker.
# The encoder and the sensitive-content export are deliberately absent: they get
# their own rows (preflight_run), with the digest and the command that fixes them.
HOST_PATH_KEYS = (
    "output.directory",
    "audio.local_music_dir",
    "cache.directory",
    "cache.database",
    "editorial.annotation_database",
    "editorial.preparation.head_bundle",
    "editorial.preparation.detector_python",
    "editorial.preparation.detector_cache_dir",
)


def _host_paths_set_by_hand(config: Config) -> Iterator[tuple[str, Path]]:
    """Yield (key, path) for every host path someone wrote down, defaults skipped."""
    for key in HOST_PATH_KEYS:
        *sections, field = key.split(".")
        owner: BaseModel = config
        for part in sections:
            owner = getattr(owner, part)
        value = str(getattr(owner, field)).strip()
        if value and value != type(owner).model_fields[field].default:
            yield key, Path(value).expanduser()


def check_host_paths(config: Config) -> CheckResult:
    """Report configured paths that are not on this host, all in one row.

    A path the app writes is created inside a directory that already exists, so
    the test is the parent: present means the app can make the rest, absent means
    the path came from somewhere else. WARNING and not ERROR, because a NAS whose
    music share is unmounted this morning should still be able to cut a memory.
    """
    missing = [
        f"{key}={path}"
        for key, path in _host_paths_set_by_hand(config)
        if not path.exists() and not path.parent.is_dir()
    ]
    if not missing:
        return CheckResult(
            name="Config paths",
            status=CheckStatus.OK,
            message="Every configured path is on this host",
        )
    noun = "path is" if len(missing) == 1 else "paths are"
    return CheckResult(
        name="Config paths",
        status=CheckStatus.WARNING,
        message=f"{len(missing)} configured {noun} not on this host",
        details=f"{'; '.join(missing)} (a config copied between hosts keeps the first host's paths)",
    )


def run_preflight_checks(config: Config) -> list[CheckResult]:
    """Run all preflight checks.

    Args:
        config: Configuration to use.

    Returns:
        List of check results.
    """
    from immich_memories.preflight_accounts import check_extra_accounts
    from immich_memories.preflight_compute import check_inference_compute, inference_gpu_available
    from immich_memories.preflight_config_keys import check_unknown_config_keys
    from immich_memories.preflight_homebase import check_homebase
    from immich_memories.preflight_immich import check_immich
    from immich_memories.preflight_laya import check_laya
    from immich_memories.preflight_llm import check_llm
    from immich_memories.preflight_music import check_music
    from immich_memories.preflight_network import outside_call_checks
    from immich_memories.preflight_output import output_directory_rows
    from immich_memories.preflight_render import check_render_worker
    from immich_memories.preflight_run import (
        check_detector_export,
        check_detector_interpreter,
        check_encoder,
        check_memory,
    )
    from immich_memories.preflight_settings import check_stored_settings
    from immich_memories.preflight_sign_in import check_sign_in
    from immich_memories.preflight_store import check_store_location

    inference_gpu = inference_gpu_available(config)
    return [
        *check_unknown_config_keys(config),
        check_immich(config),
        check_stored_settings(config),
        *check_extra_accounts(config),
        check_homebase(config),
        check_sign_in(config),
        check_llm(config),
        check_title_rendering(config, inference_gpu),
        check_encoder(config),
        check_detector_export(config),
        check_detector_interpreter(config),
        check_caption_endpoint(config),
        check_laya(config),
        check_host_paths(config),
        check_store_location(config),
        *output_directory_rows(config),
        check_notifications(config),
        check_render_worker(config),
        check_music(config),
        check_hardware(inference_gpu),
        check_inference_compute(config),
        check_memory(config),
        *outside_call_checks(config),
    ]


def check_notifications(config: Config) -> CheckResult:
    """Report optional durable notification health without probing provider URLs."""
    if not config.notifications.enabled:
        return CheckResult(
            name="Notifications",
            status=CheckStatus.SKIPPED,
            message="Notifications disabled",
        )
    if not config.notifications.urls:
        return CheckResult(
            name="Notifications",
            status=CheckStatus.WARNING,
            message="No notification URLs configured",
        )

    from immich_memories.automation.notification_state import NotificationStateStore

    try:
        location = resolve_location(config)
        path = location.sqlite_path
        if path is not None and not path.exists():
            health = None
        else:
            store = unmigrated_store(location)
            try:
                health = NotificationStateStore(store).get()
            finally:
                store.engine.dispose()
    except Exception:  # WHY: optional health telemetry cannot fail provider preflight
        return CheckResult(
            name="Notifications",
            status=CheckStatus.WARNING,
            message="Notification health unavailable",
        )
    if health is None:
        return CheckResult(
            name="Notifications",
            status=CheckStatus.OK,
            message="Configured; no delivery attempted yet",
        )
    if health.is_cooling_down(config.notifications.cooldown_hours):
        category = health.failure_category.value if health.failure_category else "delivery"
        return CheckResult(
            name="Notifications",
            status=CheckStatus.WARNING,
            message=f"Delivery paused after {category} failure",
            details=f"Normal attempts resume after the {config.notifications.cooldown_hours}h cooldown",
        )
    if health.last_success_at is not None and (
        health.last_failure_at is None or health.last_success_at >= health.last_failure_at
    ):
        return CheckResult(
            name="Notifications",
            status=CheckStatus.OK,
            message="Last notification delivered successfully",
            details=f"Last success: {health.last_success_at.isoformat()}",
        )
    return CheckResult(
        name="Notifications",
        status=CheckStatus.WARNING,
        message="Previous notification delivery failed",
        details="Cooldown expired; run auto test-notification to verify recovery",
    )
