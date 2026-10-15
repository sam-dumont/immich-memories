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
        "analysis/stories/period_account.py:437:read_page",
        "editorial_story_reading.py:437",
    ):
        assert privacy.text(line) == line


def test_a_term_whose_case_folding_changes_length_is_still_redacted():
    assert ReportPrivacy(terms=["İzmir"]).text("trip to izmir") == "trip to [private]"


def test_terms_match_whole_words_in_keys_and_values():
    privacy = ReportPrivacy(terms=["Spa", "Family picnic"])
    cleaned = privacy.clean(
        {"spans": "Spa spans; family picnic at noon", "Family picnic render": 12.5}
    )
    assert cleaned == {"spans": "[private] spans; [private] at noon", "[private] render": 12.5}


def test_a_two_letter_name_is_redacted_as_a_whole_word():
    privacy = ReportPrivacy(terms=["Al"])
    assert privacy.text("Al at the beach, Alarm set") == "[private] at the beach, Alarm set"


def test_trivial_terms_and_a_root_home_are_ignored(monkeypatch):
    # WHY: a container user whose home is "/" must not turn every slash into a redaction.
    with monkeypatch.context() as patched:
        patched.setenv("HOME", "/")
        privacy = ReportPrivacy(terms=["/", "A", ""])
    assert privacy.text("A trip at 1/2 speed, s/item") == "A trip at 1/2 speed, s/item"


def test_geocoder_and_tile_failures_log_no_coordinates(monkeypatch, caplog):
    from immich_memories.analysis.places.geocoder import PlaceGeocoder
    from immich_memories.db import open_store
    from immich_memories.titles import map_animation

    def refuse(*_args, **_kwargs):
        raise ValueError("service declined")

    # WHY: the geocoder and the tile server are the external boundaries that fail here.
    monkeypatch.setattr(map_animation.CachedStaticMap, "render", refuse)
    with caplog.at_level("DEBUG"):
        assert PlaceGeocoder(open_store(), "en", refuse).address(50.850346, 4.351721) == {}
        map_animation._render_satellite(50.850346, 4.351721, 9.0, 16, 12)
    assert "service declined" in caplog.text
    assert "50.85" not in caplog.text
    assert "4.35" not in caplog.text


# ── an id, a name or an address glued to a file name (#2397) ─────────────────

_UUID = "3fa85f64-5717-4562-b3fc-2c963f66afa6"


@pytest.mark.parametrize(
    "line",
    [
        f"{_UUID}_photo.mp4",
        f"clip_{_UUID}_0.0_4.0.mp4",
        f"cache/{_UUID}.jpg",
        f"'{_UUID}'",
        f'"{_UUID}"',
        f"asset-{_UUID}",
        _UUID,
        f"{_UUID.upper()}_photo.mp4",
    ],
)
def test_an_immich_id_is_hashed_whatever_surrounds_it(line):
    privacy = ReportPrivacy()

    cleaned = privacy.text(line)

    assert _UUID not in cleaned.lower()
    assert privacy.hash_id(_UUID) in cleaned


@pytest.mark.parametrize(
    "template",
    ["{}_photo.mp4", "clip_{}.mp4", "runs/{}/story", "'{}'", "{}.", "x {}", "{}", "({})"],
)
def test_a_private_id_is_hashed_whatever_surrounds_it(template):
    privacy = ReportPrivacy(ids=["garden-cake-01"])

    cleaned = privacy.text(template.format("garden-cake-01"))

    assert cleaned == template.format(privacy.hash_id("garden-cake-01"))


def test_adjacent_and_overlapping_ids_each_hash_whole():
    privacy = ReportPrivacy(ids=["garden-cake", "garden-cake-01", "20261011_125635_c92a"])

    cleaned = privacy.text("garden-cake-01_garden-cake run_20261011_125635_c92a")

    assert cleaned == (
        f"{privacy.hash_id('garden-cake-01')}_{privacy.hash_id('garden-cake')} "
        f"run_{privacy.hash_id('20261011_125635_c92a')}"
    )


def test_an_id_is_not_hashed_inside_a_longer_id_or_word():
    privacy = ReportPrivacy(ids=["garden-cake"])

    assert privacy.text("garden-cakes garden-cake-02 xgarden-cake") == (
        "garden-cakes garden-cake-02 xgarden-cake"
    )


def test_a_name_glued_to_an_underscore_is_redacted_but_a_longer_word_is_not():
    privacy = ReportPrivacy(terms=["Kit"])

    assert privacy.text("Kit_photo.mp4 spotlight_kit Kitchen toolkit") == (
        "[private]_photo.mp4 spotlight_[private] Kitchen toolkit"
    )


@pytest.mark.parametrize(
    ("line", "leak"),
    [
        ("tile_50.85,4.35.png", "50.85"),
        ("map_lat=50.8417 map_lon=4.3624", "50.8417"),
        ("peer_10.0.0.7 refused", "10.0.0.7"),
        ("upstream_nas.lan:2283 down", "nas.lan"),
        ("fetch_https://immich.lan/api failed", "immich.lan"),
        ("cache_/volume1/photos/x.jpg", "/volume1"),
        ("stopped at 50.85,4.35.", "4.35"),
        ("refused by 10.0.0.7.", "10.0.0.7"),
    ],
)
def test_addresses_and_coordinates_glued_to_an_underscore_never_survive(line, leak):
    assert leak not in ReportPrivacy().text(line)


def test_ordinary_words_and_numbers_stay_readable_next_to_underscores():
    line = "clip_extraction 0.734 s, render_assembly 4/4, v1.2_beta, flat=3"

    assert ReportPrivacy(ids=["c92a"], terms=["Robin"]).text(line) == line
