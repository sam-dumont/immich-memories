"""FFmpeg animation over one rasterized text layer, without a native kernel runtime."""

from __future__ import annotations

from .animations import AnimationProperty, get_animation_preset


def _value(prop: AnimationProperty | None, eased: str, default: float) -> str:
    if prop is None:
        return str(default)
    return f"({prop.from_value}+({prop.to_value - prop.from_value})*({eased}))"


def text_animation(preset_name: str, duration: float) -> tuple[str, str, str]:
    """Scale and position expressions using the existing title preset's entry timing."""
    preset = get_animation_preset(preset_name)
    enter = min(preset.duration_ms / 1000, duration / 3)
    progress = f"min(max(t/{enter},0),1)"
    easing = {
        "ease_out_quad": f"1-pow(1-({progress}),2)",
        "ease_in_out_sine": f"(1-cos(PI*({progress})))/2",
        "ease_out_back": f"1+2.70158*pow(({progress})-1,3)+1.70158*pow(({progress})-1,2)",
    }.get(preset.easing, f"1-pow(1-({progress}),3)")
    return (
        _value(preset.scale, easing, 1),
        _value(preset.x_offset, easing, 0),
        _value(preset.y_offset, easing, 0),
    )
