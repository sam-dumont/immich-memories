"""Whether the Laya audience check a tier turns on can run on this host."""

from __future__ import annotations

from immich_memories.config import Config
from immich_memories.preflight import CheckResult, CheckStatus

_NAME = "Laya"
_FALLBACK = "Until then, the heads and rules decide sharing alone."


def check_laya(config: Config) -> CheckResult:
    """Open the configured Laya reader the way a cut does, and say what is missing.

    A missing checkpoint or runtime is a warning, not an error: the cut still runs and the
    heads and rules answer the sharing question alone. A checkpoint that will not open is
    an error, because the cut would fail on it too.
    """
    from immich_memories.analysis.editorial_laya_reader import laya_reader_for

    editorial = config.editorial
    if not editorial.laya_audience:
        return CheckResult(_NAME, CheckStatus.SKIPPED, "Not used by the configured tier")
    try:
        reader = laya_reader_for(editorial)
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        return CheckResult(
            _NAME,
            CheckStatus.ERROR,
            "Laya checkpoint could not be opened",
            f"{editorial.laya_checkpoint_path} ({type(exc).__name__}); "
            "run `immich-memories models fetch --laya --force`",
        )
    if reader is not None:
        return CheckResult(
            _NAME, CheckStatus.OK, "Checkpoint and runtime found; inference not tested"
        )
    if not editorial.laya_checkpoint_path.exists():
        return CheckResult(
            _NAME,
            CheckStatus.WARNING,
            "Laya checkpoint missing",
            f"Run `immich-memories models fetch`. {_FALLBACK}",
        )
    return CheckResult(
        _NAME,
        CheckStatus.WARNING,
        "Laya runtime missing",
        "The MLX checkpoint needs laya-mlx in the app environment; for uv tool: "
        '`uv tool install "immich-memories[all-mac]" --with laya-mlx`. ' + _FALLBACK,
    )
