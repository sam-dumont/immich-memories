"""Coordinate validation shared by place matching and home detection."""

from __future__ import annotations


def valid_coordinates(latitude: float | None, longitude: float | None) -> bool:
    """Null Island and non-finite/out-of-range EXIF cannot identify a home."""
    return (
        latitude is not None
        and longitude is not None
        and -90 <= latitude <= 90
        and -180 <= longitude <= 180
        and (latitude != 0 or longitude != 0)
    )
