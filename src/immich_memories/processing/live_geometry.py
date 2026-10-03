"""Resolve a shared display canvas before stitching Live Photo companions."""

from pathlib import Path

from immich_memories.processing.probe_cache import ProbeCache, ProbeError


def burst_geometry_filter(paths: list[Path], *, nas: bool = False) -> str:
    """Fit companions to one canvas, bounded to 1080p for the Basic tier."""
    if len(paths) < 2 and not nas:
        return ""
    probes = ProbeCache()
    sizes = []
    for path in paths:
        try:
            size = probes.get(path).resolution
        except (ProbeError, OSError, ValueError):
            continue  # The legacy path still lets FFmpeg report an unreadable input.
        if size is not None:
            sizes.append(size)
    if not sizes:
        return ""
    width, height = max(sizes, key=lambda size: size[0] * size[1])
    if nas:
        scale = min(1.0, 1920 / max(width, height), 1080 / min(width, height))
        width, height = max(2, int(width * scale) // 2 * 2), max(2, int(height * scale) // 2 * 2)
    width += width % 2
    height += height % 2
    # Companions can mix original and reduced resolutions; concat needs one canvas.
    return (
        f",scale={width}:{height}:force_original_aspect_ratio=decrease:"
        f"force_divisible_by=2:flags=lanczos,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1"
    )
