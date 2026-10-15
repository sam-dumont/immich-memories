"""Handing a finished artifact to Immich, and writing down what happened.

Delivery is the one phase that runs after the artifact is already durable, so
every failure here has to stay retryable: the run row records a pending or
delivered state, and nothing in this module is allowed to invalidate a video
that has already been rendered.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, NoReturn

from immich_memories.delivery_timestamp import film_capture_instant
from immich_memories.generate_progress import report_progress
from immich_memories.generate_settings import upload_to_immich
from immich_memories.operations.film_labelling import label_for_params
from immich_memories.operations.local_output_cleanup import remove_after_confirmed_upload
from immich_memories.operations.phases import OperationalPhase
from immich_memories.processing.output_contract import InvalidOutputArtifact
from immich_memories.security import configured_secret_values, sanitize_error_message

if TYPE_CHECKING:
    from pathlib import Path

    from immich_memories.config.loader import Config
    from immich_memories.generate import DeliveryError, GenerationParams
    from immich_memories.generate_progress import OperationalProgress
    from immich_memories.tracking import RunTracker

logger = logging.getLogger(__name__)


def _delivery_error(message: str) -> DeliveryError:
    # WHY: generate.py owns the public exception surface and imports this module,
    # so importing the class back at module scope would close the cycle.
    from immich_memories.generate import DeliveryError

    return DeliveryError(message)


def safe_delivery_message(exc: Exception | str, config: Config) -> str:
    """Sanitize one delivery error, including unlabelled configured secrets."""
    safe_message = sanitize_error_message(str(exc))
    for secret in configured_secret_values(config):
        safe_message = safe_message.replace(secret, "***")
    return safe_message


def _pending_delivery_error(
    run_tracker: RunTracker,
    message: str,
    *,
    attempted: bool,
) -> DeliveryError:
    """Persist retry state and build a safe error outside any raw exception chain."""
    try:
        run_tracker.mark_delivery_pending(message, attempted=attempted)
    except Exception:  # WHY: secondary details may contain secrets; keep the artifact primary
        logger.error("Could not persist pending delivery state")
    return _delivery_error(f"Immich delivery failed: {message}")


def _raise_delivery_error(
    run_tracker: RunTracker,
    message: str,
    *,
    attempted: bool,
) -> NoReturn:
    """Persist retry state and raise without invalidating the completed artifact."""
    error = _pending_delivery_error(run_tracker, message, attempted=attempted)
    raise error from None


def deliver_completed_artifact(
    params: GenerationParams,
    result_path: Path,
    run_tracker: RunTracker,
    recheck: Callable[[], object] | None = None,
) -> dict | None:
    """Deliver a completed artifact and persist exactly one API attempt.

    ``recheck`` runs first; a film it refuses is not uploaded and the delivery
    stays pending with the reason.
    """
    if not params.upload_enabled:
        return None
    if params.client is None:
        _raise_delivery_error(
            run_tracker,
            "no Immich client is configured",
            attempted=False,
        )
    if recheck is not None:
        try:
            recheck()
        except InvalidOutputArtifact as exc:
            _raise_delivery_error(
                run_tracker, safe_delivery_message(exc, params.config), attempted=False
            )

    report_progress(params, "upload", 0.95, "Uploading to Immich...")
    delivery_error: DeliveryError | None = None
    asset_id: str | None = None
    try:
        result = upload_to_immich(
            params.client,
            result_path,
            params.upload_album,
            film_capture_instant(clip.asset for clip in params.clips),
            label_for_params(params),
        )
        asset_id = result.get("asset_id")
        if result.get("delivery_complete") is False:
            warnings = [safe_delivery_message(w, params.config) for w in result.get("warnings", [])]
            reason = "; ".join(warnings) or "Immich delivery incomplete; local film kept"
            _record_incomplete_delivery(run_tracker, result, reason, warnings)
            logger.warning("%s; local film kept at %s", reason, result_path)
            report_progress(params, "upload", 1.0, f"{reason}; local film kept")
            return result
        if not isinstance(asset_id, str) or not asset_id.strip():
            raise ValueError("Immich upload returned no asset ID")
    except Exception as exc:
        safe_message = safe_delivery_message(exc, params.config)
        logger.warning("Immich delivery failed: %s", safe_message)
        delivery_error = _pending_delivery_error(
            run_tracker,
            safe_message,
            attempted=True,
        )
    if delivery_error is not None:
        raise delivery_error from None

    assert asset_id is not None  # validated in the API-call boundary above
    _record_delivered_asset(params, run_tracker, result, asset_id)
    return result


def _record_incomplete_delivery(
    run_tracker: RunTracker, result: dict, reason: str, warnings: list[str]
) -> None:
    if result.get("missing_permissions"):
        run_tracker.mark_delivery_abandoned(
            reason, asset_id=result.get("asset_id"), warnings=warnings
        )
    else:
        run_tracker.mark_delivery_pending(
            reason, asset_id=result.get("asset_id"), warnings=warnings
        )


def _record_delivered_asset(
    params: GenerationParams,
    run_tracker: RunTracker,
    result: dict,
    asset_id: str,
) -> None:
    """Persist delivery once and reclaim local output only after durable confirmation."""
    delivery_error: DeliveryError | None = None
    normalized_asset_id = asset_id.strip()
    try:
        warnings = [safe_delivery_message(w, params.config) for w in result.get("warnings", [])]
        delivered_run = (
            run_tracker.mark_delivered(asset_id, warnings=warnings)
            if warnings
            else run_tracker.mark_delivered(asset_id)
        )
    except Exception as exc:
        persisted = None
        try:
            persisted = run_tracker.db.get_run(run_tracker.run_id)
        except Exception:  # WHY: an ambiguous transition must not trigger a second upload
            logger.error("Could not inspect successful Immich delivery state")
        if (
            persisted is not None
            and persisted.delivery_status.value == "delivered"
            and persisted.immich_asset_id == normalized_asset_id
        ):
            remove_after_confirmed_upload(persisted)
            return
        safe_message = safe_delivery_message(exc, params.config)
        logger.error("Could not persist successful Immich delivery: %s", safe_message)
        delivery_error = _delivery_error(f"Immich delivery state update failed: {safe_message}")
    else:
        remove_after_confirmed_upload(delivered_run)
    if delivery_error is not None:
        raise delivery_error from None


def _deliver_completed_artifact(
    params: GenerationParams,
    result_path: Path,
    run_tracker: RunTracker,
    recheck: Callable[[], object] | None = None,
) -> dict | None:
    """Compatibility wrapper for the original internal delivery boundary."""
    return deliver_completed_artifact(params, result_path, run_tracker, recheck)


def deliver_with_operational_progress(
    params: GenerationParams,
    result_path: Path,
    run_tracker: RunTracker,
    operational: OperationalProgress,
    recheck: Callable[[], object] | None = None,
) -> None:
    """Expose optional delivery while preserving its existing error boundary."""
    operational.emit(
        OperationalPhase.DELIVERY,
        0,
        1 if params.upload_enabled else 0,
        "Uploading to Immich" if params.upload_enabled else "Delivery not requested",
    )
    result = _deliver_completed_artifact(params, result_path, run_tracker, recheck)
    if params.upload_enabled:
        message = (
            "Local film kept; Immich delivery incomplete"
            if result and result.get("delivery_complete") is False
            else "Delivered to Immich"
        )
        operational.emit(OperationalPhase.DELIVERY, 1, 1, message)
