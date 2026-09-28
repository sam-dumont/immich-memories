"""What a pasted report may never carry, one leak shape at a time."""

import pytest

from immich_memories.tracking.report_privacy import ReportPrivacy


@pytest.mark.parametrize(
    ("line", "leak"),
    [
        ("Tile fetch failed z=12 (50.85,4.35): timeout", "50.85"),
        ("Reverse geocoding failed for (50.850346, 4.351721)", "4.351721"),
        ("asset at lat=-33.8688 lon=151.2093", "151.2093"),
        ("could not reach nas.local:2283", "nas.local"),
        ("could not reach immich:2283", "immich:2283"),
        ("connect to 192.168.1.20:5432 refused", "192.168.1.20"),
        ("bound to 10.0.0.7", "10.0.0.7"),
        ("listening on [fe80::1ff:fe23:4567:890a]:8080", "fe80::1ff"),
        ("dialing 2001:db8:85a3:0:0:8a2e:370:7334", "2001:db8"),
        ("store postgresql://memories:hunter2@db.lan:5432/memories failed", "hunter2"),
        ("queue redis://cache.lan:6379/0 down", "cache.lan"),
        ("wrote /volume1/photos/2024/IMG_0001.HEIC", "/volume1"),
        ("read /photos/library/upload", "/photos"),
        ("moved to /srv/immich/library", "/srv"),
        ("model in /opt/models/gemma", "/opt/models"),
        (r"saved C:\Users\someone\Videos\film.mp4", "someone"),
        ("saved D:/Films/film.mp4", "D:/Films"),
    ],
)
def test_addresses_places_and_paths_never_survive(line, leak):
    assert leak not in ReportPrivacy().text(line)


def test_timestamps_rates_and_stack_frames_stay_readable():
    privacy = ReportPrivacy()
    for line in (
        "12:30:45 INFO done",
        "0.5000 s/item (4)",
        "analysis/editorial_story_reading.py:437:read_page",
        "editorial_story_reading.py:437",
    ):
        assert privacy.text(line) == line


def test_a_term_whose_case_folding_changes_length_is_still_redacted():
    assert ReportPrivacy(terms=["İzmir"]).text("trip to izmir") == "trip to [private]"


def test_terms_match_whole_words_in_values_never_keys():
    privacy = ReportPrivacy(terms=["Spa", "Family picnic"])
    cleaned = privacy.clean({"spans": "Spa spans; family picnic at noon"})
    assert cleaned == {"spans": "[private] spans; [private] at noon"}


def test_trivial_terms_and_a_root_home_are_ignored(monkeypatch):
    # WHY: a container user whose home is "/" must not turn every slash into a redaction.
    with monkeypatch.context() as patched:
        patched.setenv("HOME", "/")
        privacy = ReportPrivacy(terms=["/", "Al", ""])
    assert privacy.text("Alarm at 1/2 speed, s/item") == "Alarm at 1/2 speed, s/item"


def test_geocoder_and_tile_failures_log_no_coordinates(monkeypatch, caplog):
    from immich_memories.analysis import trip_detection
    from immich_memories.titles import map_animation

    def refuse(*_args, **_kwargs):
        raise ValueError("service declined")

    # WHY: the geocoder and the tile server are the external boundaries that fail here.
    monkeypatch.setattr(trip_detection.Nominatim, "reverse", refuse)
    monkeypatch.setattr(map_animation._CachedStaticMap, "render", refuse)
    with caplog.at_level("DEBUG"):
        assert trip_detection.reverse_geocode(50.850346, 4.351721) is None
        map_animation._render_satellite(50.850346, 4.351721, 9.0, 16, 12)
    assert "service declined" in caplog.text
    assert "50.85" not in caplog.text
    assert "4.35" not in caplog.text
