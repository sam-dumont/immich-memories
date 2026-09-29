"""Trip map and location card generation service.

Provides methods for generating trip-specific title screens:
- Animated satellite map fly-over (city zoom -> pan -> city zoom)
- Fallback: static satellite map with pins (when no home coords)
- Location interstitial cards between clips
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .generator import GeneratedScreen, TitleScreenConfig
    from .rendering_service import RenderingService

logger = logging.getLogger(__name__)


class TripService:
    """Generates trip map screens and location cards."""

    def __init__(
        self,
        config: TitleScreenConfig,
        rendering: RenderingService,
        output_dir: Path,
    ) -> None:
        self.config = config
        self._rendering = rendering
        self.output_dir = output_dir

    def generate_trip_map_screen(
        self,
        locations: list[tuple[float, float]],
        title_text: str,
        subtitle_text: str | None = None,
        home_lat: float | None = None,
        home_lon: float | None = None,
        location_names: list[str] | None = None,
    ) -> GeneratedScreen:
        """Generate a trip map overview screen.

        When home coordinates are provided, renders an animated satellite
        map fly-over. Falls back to static map otherwise.
        """
        if home_lat is not None and home_lon is not None:
            return self._generate_map_fly(locations, title_text, home_lat, home_lon, location_names)
        return self._generate_static_map(locations, title_text, subtitle_text, location_names)

    def _generate_map_fly(
        self,
        destinations: list[tuple[float, float]],
        title_text: str,
        home_lat: float,
        home_lon: float,
        location_names: list[str] | None = None,
    ) -> GeneratedScreen:
        """Animated satellite map fly-over from home to destinations."""
        from .generator import GeneratedScreen
        from .map_animation import create_map_fly_video

        width, height = self.config.output_resolution
        timing = self.config.map_move
        # A map move's own length, not the title's: the seconds past the title's are
        # added on top of the film's requested length (see processing/map_time_budget).
        duration = timing.intro_seconds((home_lat, home_lon), destinations)

        output_path = self.output_dir / f"trip_map_fly_intro{self.config.output_suffix}"
        create_map_fly_video(
            departure=(home_lat, home_lon),
            destinations=destinations,
            title_text=title_text,
            output_path=output_path,
            width=width,
            height=height,
            duration=duration,
            fps=self.config.fps,
            timing=timing,
            encoding_plan=self.config.encoding_plan,
            destination_names=location_names,
        )

        logger.info(f"Map fly animation generated: {output_path}")
        return GeneratedScreen(
            path=output_path,
            duration=duration,
            screen_type="trip_map",
        )

    def _generate_static_map(
        self,
        locations: list[tuple[float, float]],
        title_text: str,
        subtitle_text: str | None,
        location_names: list[str] | None = None,
    ) -> GeneratedScreen:
        """Static satellite map with pins (fallback when no home coords)."""
        from .generator import GeneratedScreen
        from .map_renderer import render_trip_map_array

        width, height = self.config.output_resolution
        map_array = render_trip_map_array(locations, width, height, location_names=location_names)

        output_path = self.output_dir / f"trip_map_intro{self.config.output_suffix}"
        self._rendering.create_map_video(
            title=title_text,
            subtitle=subtitle_text,
            background_array=map_array,
            output_path=output_path,
            width=width,
            height=height,
            duration=self.config.title_duration,
            fps=self.config.fps,
        )

        renderer_type = "GPU" if self._rendering.use_gpu else "CPU (PIL)"
        logger.info(f"Trip map screen generated [{renderer_type}]: {output_path}")

        return GeneratedScreen(
            path=output_path,
            duration=self.config.title_duration,
            screen_type="trip_map",
        )

    def generate_location_move(
        self,
        location_name: str,
        came_from: tuple[float, float],
        destination: tuple[float, float],
        seconds: float,
    ) -> GeneratedScreen:
        """A location card that flies from the last place to this one and holds on its name."""
        from .generator import GeneratedScreen
        from .map_animation import create_map_move_video

        width, height = self.config.output_resolution
        safe_name = location_name.replace(" ", "_").replace(",", "")[:30]
        # The same place reached from elsewhere is another flight; no coordinate in a file name.
        origin = hashlib.sha256(f"{came_from[0]:.3f},{came_from[1]:.3f}".encode()).hexdigest()[:8]
        output_path = self.output_dir / f"location_{safe_name}_{origin}{self.config.output_suffix}"
        create_map_move_video(
            came_from,
            destination,
            location_name,
            output_path,
            seconds,
            width=width,
            height=height,
            fps=self.config.fps,
            timing=self.config.map_move,
            encoding_plan=self.config.encoding_plan,
        )
        return GeneratedScreen(path=output_path, duration=seconds, screen_type="location_card")
