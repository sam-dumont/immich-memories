"""Tests for privacy/demo mode: the flag, GPS and name anonymization."""

from __future__ import annotations

from pathlib import Path

import pytest

from immich_memories.processing.assembly_config import (
    AssemblyClip,
    AssemblySettings,
    standalone_assembly_encoding_plan,
)


class TestPrivacyModeConfig:
    """AssemblySettings has privacy_mode flag."""

    def test_default_is_false(self):
        settings = AssemblySettings(encoding_plan=standalone_assembly_encoding_plan())
        assert not settings.privacy_mode

    def test_can_be_enabled(self):
        settings = AssemblySettings(
            encoding_plan=standalone_assembly_encoding_plan(), privacy_mode=True
        )
        assert settings.privacy_mode


class TestPrivacyGpsAnonymization:
    """The destination moves too: no real coordinate reaches the output."""

    # Nowhere near any of the fake cities, so "did it move" is unambiguous.
    AWAY_LAT = 10.0
    AWAY_LON = 20.0

    def _located(self, lat, lon, name=None):
        return AssemblyClip(
            path=Path("/tmp/a.mp4"),
            duration=3.0,
            latitude=lat,
            longitude=lon,
            location_name=name,
        )

    def test_clip_gps_is_relocated_near_the_fake_city(self):
        from immich_memories.generate_privacy import (
            anonymize_clips_for_privacy,
            pick_fake_city,
        )

        _, city_lat, city_lon = pick_fake_city()
        result = anonymize_clips_for_privacy([self._located(self.AWAY_LAT, self.AWAY_LON)])

        assert (result[0].latitude, result[0].longitude) != (self.AWAY_LAT, self.AWAY_LON)
        assert result[0].latitude == pytest.approx(city_lat)
        assert result[0].longitude == pytest.approx(city_lon)

    def test_the_shape_of_the_memory_survives_the_move(self):
        """Pins keep their spacing, so the map still shows a coherent trip."""
        from immich_memories.generate_privacy import anonymize_clips_for_privacy

        clips = [
            self._located(self.AWAY_LAT, self.AWAY_LON),
            self._located(self.AWAY_LAT + 0.2, self.AWAY_LON + 0.1),
        ]
        result = anonymize_clips_for_privacy(clips)

        assert result[1].latitude - result[0].latitude == pytest.approx(0.2)
        assert result[1].longitude - result[0].longitude == pytest.approx(0.1)

    def test_a_continent_wide_memory_still_lands_by_the_city(self):
        """Rigid translation would put a wide spread in the sea; it is scaled."""
        from immich_memories.generate_privacy import (
            anonymize_clips_for_privacy,
            pick_fake_city,
        )

        _, city_lat, city_lon = pick_fake_city()
        clips = [
            self._located(self.AWAY_LAT - 20.0, self.AWAY_LON - 30.0),
            self._located(self.AWAY_LAT + 20.0, self.AWAY_LON + 30.0),
        ]
        result = anonymize_clips_for_privacy(clips)

        for clip in result:
            assert abs(clip.latitude - city_lat) <= 1.0
            assert abs(clip.longitude - city_lon) <= 1.0

    def test_the_same_memory_relocates_the_same_way_every_run(self):
        """A per-run offset would let repeated renders be averaged back."""
        from immich_memories.generate_privacy import anonymize_clips_for_privacy

        clips = [self._located(self.AWAY_LAT, self.AWAY_LON)]

        first = anonymize_clips_for_privacy(clips)
        second = anonymize_clips_for_privacy(clips)

        assert (first[0].latitude, first[0].longitude) == (
            second[0].latitude,
            second[0].longitude,
        )

    def test_the_place_name_goes_with_the_coordinates(self):
        """The name identifies the place harder than the coordinate does."""
        from immich_memories.generate_privacy import (
            anonymize_clips_for_privacy,
            pick_fake_city,
        )

        fake_name, _, _ = pick_fake_city()
        result = anonymize_clips_for_privacy(
            [self._located(self.AWAY_LAT, self.AWAY_LON, "Real Village, Realland")]
        )

        assert result[0].location_name == fake_name

    def test_a_clip_with_no_place_name_gains_none(self):
        """Inventing a caption where the memory had none changes the render."""
        from immich_memories.generate_privacy import anonymize_clips_for_privacy

        result = anonymize_clips_for_privacy([self._located(self.AWAY_LAT, self.AWAY_LON)])

        assert result[0].location_name is None

    def test_home_and_destination_are_both_faked_in_the_preset(self):
        from immich_memories.generate_privacy import anonymize_preset_params, pick_fake_city

        fake_name, _, _ = pick_fake_city()
        preset = {"home_lat": 48.85, "home_lon": 2.35, "location_name": "Real Village"}

        result = anonymize_preset_params(preset)

        assert result["home_lat"] != 48.85
        assert result["home_lon"] != 2.35
        assert result["location_name"] == fake_name

    def test_clip_without_gps_keeps_none(self):
        from immich_memories.generate_privacy import anonymize_clips_for_privacy

        clips = [
            AssemblyClip(path=Path("/tmp/a.mp4"), duration=3.0),
        ]
        result = anonymize_clips_for_privacy(clips)
        assert result[0].latitude is None
        assert result[0].longitude is None

    def test_anonymize_preserves_all_fields(self):
        """Anonymization must preserve llm_emotion and is_photo."""
        from immich_memories.generate_privacy import anonymize_clips_for_privacy

        clips = [
            AssemblyClip(
                path=Path("/tmp/a.mp4"),
                duration=3.0,
                latitude=48.8566,
                longitude=2.3522,
                location_name="Paris, France",
                llm_emotion="joyful",
                is_photo=True,
                outgoing_transition="fade",
            ),
        ]
        result = anonymize_clips_for_privacy(clips)
        assert result[0].llm_emotion == "joyful"
        assert result[0].is_photo is True
        assert result[0].outgoing_transition == "fade"


class TestPrivacyNameAnonymization:
    """Person names must be replaced with fake names in privacy mode."""

    def test_a_name_gets_a_consistent_fake(self):
        from immich_memories.generate_privacy import fake_names

        fake = fake_names(["TestPerson"])["TestPerson"]

        assert fake != "TestPerson"
        assert fake_names(["TestPerson"]) == {"TestPerson": fake}

    def test_a_name_on_the_fake_list_never_gets_itself_back(self):
        from immich_memories.generate_privacy import _PRIVACY_FAKE_NAMES, fake_names

        for name in _PRIVACY_FAKE_NAMES:
            assert fake_names([name])[name] != name
            assert fake_names([f"{name} Example"])[f"{name} Example"] != name

    def test_two_people_never_share_a_fake_nor_take_each_others_name(self):
        from immich_memories.generate_privacy import _PRIVACY_FAKE_NAMES, fake_names

        names = list(_PRIVACY_FAKE_NAMES[:6])
        fakes = fake_names(names)

        assert len(set(fakes.values())) == len(names)
        assert not set(fakes.values()) & set(names)

    def test_no_name_stays_no_name(self):
        from immich_memories.generate_privacy import fake_names

        assert fake_names([None, ""]) == {}

    def test_the_names_a_person_film_asks_for_are_swapped_in_its_preset(self):
        from immich_memories.api.person_expression import PersonExpression
        from immich_memories.generate_privacy import anonymize_preset_params

        expression = PersonExpression.parse('"Kit" AND "Pat"')
        preset = {"person_names": ["Kit", "Pat"], "person_expression": expression.to_dict()}

        result = anonymize_preset_params(preset)

        shown = set(result["person_names"])
        leaves = set(PersonExpression.from_dict(result["person_expression"]).leaf_values)
        assert not shown & {"Kit", "Pat"}
        assert leaves == shown and len(shown) == 2
        assert preset["person_names"] == ["Kit", "Pat"]


class TestPrivacyTitleNames:
    """A title settled before the render carries the names; privacy mode swaps them there."""

    def test_full_and_first_names_in_a_title_become_their_fakes(self):
        from immich_memories.generate_privacy import fake_names, swap_names

        fakes = fake_names(["Kit Example", "Pat"])

        swapped = swap_names("Kit & Pat · July 2025, Kit Example's summer", fakes)

        assert swapped == (
            f"{fakes['Kit Example']} & {fakes['Pat']} · July 2025, {fakes['Kit Example']}'s summer"
        )

    def test_a_name_inside_a_longer_word_is_left_alone(self):
        from immich_memories.generate_privacy import swap_names

        assert swap_names("Kitchen days", {"Kit": "Ada"}) == "Kitchen days"
        assert swap_names(None, {"Kit": "Ada"}) is None
