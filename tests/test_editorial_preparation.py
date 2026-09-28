"""Cold preparation, exact producer reuse and incomplete-provider behavior without models."""

from __future__ import annotations

import io
import logging
import os
import stat
import time
from dataclasses import replace
from datetime import UTC, datetime

import numpy as np
import pytest
import sqlalchemy as sa
from PIL import Image

from immich_memories.analysis.editorial_description_contract import (
    DESCRIPTION_MODEL,
    DESCRIPTION_SOURCE,
    validate_envelope,
)
from immich_memories.analysis.editorial_preparation import (
    PreparationPorts,
    prepare_editorial_annotations,
)
from immich_memories.analysis.editorial_preparation_captions import _remember_captions
from immich_memories.analysis.editorial_preparation_detectors import (
    DETECTOR_VERSIONS,
    decide,
    docling_pixels,
)
from immich_memories.analysis.editorial_preparation_pixels import pixel_facts
from immich_memories.analysis.subject_framing import FaceBox
from immich_memories.api.models import Asset, Person
from immich_memories.cache.thumbnail_cache import ThumbnailCache
from immich_memories.config_models_editorial import EditorialConfig
from immich_memories.config_models_editorial_preparation import EditorialPreparationConfig
from immich_memories.config_models_triage import TriageConfig
from immich_memories.db.tables import face_boxes, head_facts
from immich_memories.operations.cancellation import PipelineCancelled, cancellation_scope
from immich_memories.store.editorial_preparation import remember_assets, remember_head_rows
from tests.annotation_rows import add_rows, annotation_store, count_rows, read_rows


def asset(asset_id):
    timestamp = datetime(2024, 1, 2, tzinfo=UTC)
    return Asset(
        id=asset_id,
        type="IMAGE",
        file_created_at=timestamp,
        file_modified_at=timestamp,
        updated_at=timestamp,
        original_file_name="photo.jpg",
        width=640,
        height=480,
        people=[Person(id="person", name="A Person")],
    )


def preview():
    buffer = io.BytesIO()
    Image.new("RGB", (80, 60), (123, 83, 66)).save(buffer, "JPEG")
    return buffer.getvalue()


def successful_ports(calls):
    def heads(**kwargs):
        calls.append(("heads", tuple(kwargs["asset_ids"])))
        remember_head_rows(
            kwargs["store"],
            [
                {
                    "asset_id": asset_id,
                    "head": head,
                    "version": version,
                    "label": "other",
                    "confidence": 0.9,
                    "encoder_key": "test",
                }
                for asset_id in kwargs["asset_ids"]
                for head, version in kwargs["head_versions"].items()
            ],
        )

    def detectors(**kwargs):
        calls.append(("detectors", tuple(kwargs["pending"])))
        remember_head_rows(
            kwargs["store"],
            [
                {
                    "asset_id": asset_id,
                    "head": head,
                    "version": DETECTOR_VERSIONS[head],
                    "label": "no",
                    "confidence": 0.1,
                    "encoder_key": "test",
                }
                for head, ids in kwargs["pending"].items()
                for asset_id in ids
            ],
        )
        return {}

    def captions(**kwargs):
        calls.append(("captions", tuple(kwargs["asset_ids"])))
        for asset_id in kwargs["asset_ids"]:
            _remember_captions(
                kwargs["store"],
                {
                    asset_id: validate_envelope(
                        {"description": "People sit together.", "setting": "a room"}
                    )
                },
            )
        return {}

    return PreparationPorts(captions=captions, heads=heads, detectors=detectors)


def run(tmp_path, **kwargs):
    return prepare_editorial_annotations(
        assets=kwargs.pop("assets", [asset("aa1"), asset("bb2")]),
        store=annotation_store(),
        thumbnail_cache=kwargs.pop("thumbnail_cache", tmp_path / "previews"),
        preparation_config=kwargs.pop("preparation_config", EditorialPreparationConfig()),
        triage_config=TriageConfig(),
        head_versions=kwargs.pop("head_versions", EditorialConfig().head_versions),
        **kwargs,
    )


def _refuse(producer):
    def refuse(**_):
        pytest.fail(f"{producer} ran under a tier that excludes it")

    return refuse


def refusing_ports(*absent):
    """Producers a tier must not reach fail the test the moment they are called."""
    calls = []
    real = successful_ports(calls)
    seams = {
        name: _refuse(name) if name in absent else getattr(real, name)
        for name in ("captions", "heads", "detectors")
    }
    return PreparationPorts(**seams), calls


def test_cold_full_source_then_warm_has_zero_provider_calls(tmp_path):
    calls = []
    first = run(tmp_path, ports=successful_ports(calls), fetch_preview=lambda _: preview())
    assert first.complete and first.requested == 2
    assert ("captions", ("aa1", "bb2")) in calls
    calls.clear()
    second = run(tmp_path, ports=successful_ports(calls))
    assert second.complete
    assert calls == []
    db_path = annotation_store().location.sqlite_path
    assert db_path is not None
    assert stat.S_IMODE(db_path.stat().st_mode) == 0o600


def test_changing_caption_server_preserves_rows_and_marks_legacy_origins_unknown(tmp_path):
    calls = []
    assert run(tmp_path, ports=successful_ports(calls), fetch_preview=lambda _: preview()).complete
    calls.clear()
    result = run(
        tmp_path,
        ports=successful_ports(calls),
        preparation_config=EditorialPreparationConfig(
            caption_base_url="http://replacement.invalid/v1",
            caption_artifact_id="new-build",
        ),
    )
    assert result.complete
    assert calls == []
    assert result.caption_provenance == {
        "origins": [{"status": "unknown", "assets": 2}],
        "by_asset": {},
    }


def test_warm_preparation_keeps_the_original_server_and_build(tmp_path):
    from dataclasses import replace

    from immich_memories.analysis.editorial_preparation_captions import prepare_captions
    from tests.test_editorial_preparation_captions import _CaptionServer

    server = _CaptionServer(None)
    first_url = server.base_url
    ports = replace(successful_ports([]), captions=prepare_captions)
    try:
        first = run(
            tmp_path,
            ports=ports,
            fetch_preview=lambda _: preview(),
            preparation_config=EditorialPreparationConfig(
                caption_base_url=first_url, caption_artifact_id="original-build"
            ),
        )
        assert first.complete
    finally:
        server.close()
    # The original server is stopped. A warm run must neither probe it nor invent a new origin.
    second = run(
        tmp_path,
        ports=ports,
        preparation_config=EditorialPreparationConfig(
            caption_base_url="http://replacement.invalid/v1",
            caption_artifact_id="replacement-build",
        ),
    )
    assert second.complete
    assert second.caption_provenance == first.caption_provenance
    (origin,) = second.caption_provenance["origins"]
    assert origin["artifact_id"] == "original-build"
    assert origin["served"] == {"owned_by": "served-revision"}
    assert origin["endpoint"] == first_url


def test_old_docling_facts_are_replaced_without_repeating_other_producers(tmp_path):
    calls = []
    assert run(tmp_path, ports=successful_ports(calls), fetch_preview=lambda _: preview()).complete
    store = annotation_store()
    with store.begin() as connection:
        connection.execute(
            sa.update(head_facts)
            .where(head_facts.c.head == "doc_docling")
            .values(version="det-v1", label="table", confidence=0.05295)
        )
    calls.clear()

    result = run(tmp_path, ports=successful_ports(calls))

    assert result.complete
    assert calls == [("detectors", ("doc_docling",))]
    assert result.produced == {"head:doc_docling@det-v2": 2}
    assert run(tmp_path, ports=refusing_ports("heads", "detectors", "captions")[0]).complete


def test_the_pass_names_each_picture_it_finishes_so_a_watcher_can_show_them(tmp_path):
    """A count cannot carry a picture: a surface watching a long stage needs the ids."""
    seen: list[str] = []

    result = run(
        tmp_path,
        ports=successful_ports([]),
        fetch_preview=lambda _: preview(),
        on_asset=seen.append,
    )

    assert result.complete
    # Previews first, in source order, then the pixel read of the same two.
    assert seen[:2] == ["aa1", "bb2"]
    assert set(seen) == {"aa1", "bb2"}


def test_a_picture_whose_preview_never_arrives_is_not_offered_to_the_watcher(tmp_path):
    seen: list[str] = []

    run(tmp_path, ports=successful_ports([]), fetch_preview=lambda _: None, on_asset=seen.append)

    assert seen == []


def test_cancellation_retains_committed_pixel_facts(tmp_path):
    """A cancellation raised mid-run must not undo facts an earlier stage already committed.

    The store commits pixel facts in their own transaction before heads ever run, so a
    cancellation raised from the heads port must leave those two pixel rows in place.
    """

    def cancel(**_):
        raise PipelineCancelled()

    ports = PreparationPorts(
        captions=lambda **_: pytest.fail("no later caption call"),
        heads=cancel,
        detectors=lambda **_: pytest.fail("no later detector call"),
    )
    with pytest.raises(PipelineCancelled):
        run(tmp_path, ports=ports, fetch_preview=lambda _: preview())
    assert count_rows(annotation_store(), "pixel_facts") == 2


def test_database_and_existing_sidecars_are_private(tmp_path):
    from immich_memories.db.sqlite_files import private_database_path

    path = tmp_path / "store.sqlite"
    paths = [path, *(tmp_path / f"store.sqlite{suffix}" for suffix in ("-wal", "-shm", "-journal"))]
    for entry in paths:
        entry.write_bytes(b"existing")
        entry.chmod(0o644)
    assert private_database_path(path) == path
    assert all(stat.S_IMODE(entry.stat().st_mode) == 0o600 for entry in paths)
    assert all(entry.read_bytes() == b"existing" for entry in paths)


def test_fresh_prepared_store_is_readable_by_the_real_annotation_reader(tmp_path):
    from immich_memories.analysis.annotation_lines import StoredAnnotationLineReader
    from immich_memories.analysis.editorial_contracts import EditorialCandidate
    from immich_memories.store.asset_annotations import AssetAnnotationFactRepository

    calls = []
    source = [asset("aa1"), asset("bb2")]
    assert run(
        tmp_path, assets=source, ports=successful_ports(calls), fetch_preview=lambda _: preview()
    ).complete
    versions = EditorialConfig().head_versions
    store = annotation_store()
    repository = AssetAnnotationFactRepository(
        store,
        description_model=DESCRIPTION_MODEL,
        head_versions=versions,
        pixel_producer_key="pixel-facts-v1",  # gitleaks:allow
    )
    facts = repository.facts_for(("aa1", "bb2"))
    assert not facts.unavailable_asset_ids and not facts.warnings
    assert len(facts.facts) == 2 and all(fact.pixel is not None for fact in facts.facts)
    candidates = tuple(
        EditorialCandidate(
            asset_id=a.id,
            taken_at=a.file_created_at,
            media_kind="photo",
            live_photo_stitch_member_ids=(),
            rendering_family_id=None,
            favourite=False,
            source=a,
            shippable_duration=4,
            grounded_annotations=(),
        )
        for a in source
    )
    result = StoredAnnotationLineReader(
        store=store,
        candidates=candidates,
        description_model=DESCRIPTION_MODEL,
        head_versions=versions,
        pixel_producer_key="pixel-facts-v1",  # gitleaks:allow
    ).lines_for(("aa1", "bb2"))
    assert not result.missing_asset_ids and not result.warnings
    assert all("People sit together." in line.text for line in result.lines)


def test_corrupt_preview_is_refetched_once_with_atomic_private_write(tmp_path):
    path = tmp_path / "previews" / "aa" / "aa1_preview.jpg"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"truncated")
    fetched = []

    def fetch(asset_id):
        fetched.append(asset_id)
        return preview()

    result = run(tmp_path, assets=[asset("aa1")], ports=successful_ports([]), fetch_preview=fetch)
    assert result.complete and fetched == ["aa1"]
    assert path.read_bytes() == preview()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert list(path.parent.glob("*.tmp")) == []


def test_missing_previews_report_every_producer_and_do_not_call_providers(tmp_path):
    calls = []
    result = run(tmp_path, ports=successful_ports(calls))
    assert not result.complete
    assert len(result.missing_by_producer) == 13  # 10 heads, caption, pixel, preview
    assert all(ids == ("aa1", "bb2") for ids in result.missing_by_producer.values())
    assert calls == []


def test_provider_omission_cannot_be_mistaken_for_success(tmp_path):
    calls = []
    good = successful_ports(calls)
    ports = PreparationPorts(
        captions=good.captions,
        heads=lambda **_: None,
        detectors=lambda **_: {"setup": "missing detector weights"},
    )
    result = run(tmp_path, ports=ports, fetch_preview=lambda _: preview())
    assert not result.complete
    assert len(result.missing_by_producer) == 10
    assert result.failures["detector:setup"] == "missing detector weights"
    assert ("captions", ("aa1", "bb2")) in calls


def test_wrong_head_version_is_explicit_and_never_written_as_requested_version(tmp_path):
    calls = []
    result = run(
        tmp_path,
        ports=successful_ports(calls),
        fetch_preview=lambda _: preview(),
        head_versions={"unknown": "next-generation"},
    )
    assert result.missing_by_producer == {"head:unknown@next-generation": ("aa1", "bb2")}
    assert "no packaged producer" in result.failures["head_provider:unknown"]


def test_partial_description_rows_do_not_trigger_paid_retries(tmp_path):
    store = annotation_store()
    add_rows(
        store,
        "descriptions",
        {
            "asset_id": "aa1",
            "model": DESCRIPTION_MODEL,
            "text": "People sit together.",
            "source": DESCRIPTION_SOURCE,
        },
    )
    calls = []
    result = run(tmp_path, ports=successful_ports(calls), fetch_preview=lambda _: preview())
    assert ("captions", ("bb2",)) in calls
    assert not result.complete
    assert "repair" in result.failures["caption:aa1"]


def test_metadata_migration_uses_live_source_and_preserves_owner_flags(tmp_path):
    store = annotation_store()
    add_rows(
        store,
        "asset_flags",
        {"asset_id": "aa1", "flag": "owner_keep", "source": "owner", "evidence": "reason"},
    )
    remember_assets(store, [asset("aa1")])
    (row,) = read_rows(store, "annotation_assets")
    assert (row["width"], row["height"], row["original_file"]) == (640, 480, "photo.jpg")
    (person,) = read_rows(store, "asset_people")
    assert (person["person_id"], person["person_name"]) == ("person", "A Person")
    (flag,) = read_rows(store, "asset_flags")
    assert flag["flag"] == "owner_keep"


def test_default_cancellation_scope_stops_before_any_acquisition(tmp_path):
    def cancel():
        raise PipelineCancelled()

    with pytest.raises(PipelineCancelled), cancellation_scope(cancel):
        run(tmp_path, fetch_preview=lambda _: pytest.fail("must not fetch"))
    assert count_rows(annotation_store(), "annotation_assets") == 0


def test_pixel_recipe_retains_accepted_q85_golden():
    pixels = np.random.default_rng(7).integers(0, 256, (480, 640, 3), dtype=np.uint8)
    buffer = io.BytesIO()
    Image.fromarray(pixels).save(buffer, "PNG")
    facts = pixel_facts(buffer.getvalue())
    # Golden from the accepted standalone pixel-facts-v1 routine, before porting.
    assert facts == {
        "sharpness": 13345.785,
        "brightness": 127.532,
        "contrast": 28.088,
        "dark_fraction": 0.00005,
        "bright_fraction": 0.00007,
        "width": 640,
        "height": 480,
        "orientation": "landscape",
        "needs_rotation": 0,
    }


def test_det_v1_rules_and_docling_preprocessing_are_preserved():
    assert decide("nsfw_marqo", {"NSFW": 0.499999, "SFW": 0.500001}) == ("no", 0.5)
    assert decide("nsfw_marqo", {"NSFW": 0.5, "SFW": 0.5}) == ("yes", 0.5)
    assert decide("doc_docling", {"photograph": 0.1, "signature": 0.9}) == ("signature", 0.9)
    pixels = docling_pixels([Image.new("RGB", (10, 20), "white")])
    assert pixels.shape == (1, 3, 224, 224)
    np.testing.assert_allclose(
        pixels[0, :, 0, 0],
        np.array([0.515, 0.544, 0.594]) / np.array([0.47853944, 0.4732864, 0.47434163]),
        rtol=1e-6,
    )


class TestTheThumbnailBudgetMeetsThePreparedScope:
    """Preparation annotates every candidate in scope, so the thumbnail cache is
    sized by the library, not by the cut. Measured on a real library: 12,159
    previews averaging 315 KB = 3.92 GB, against a 500 MB default, and one run
    logged `Evicted 17436.0 MB from thumbnails (budget 500.0 MB)` mid-analysis.

    Preparation writes previews straight into the cache layout rather than
    through `put`, so neither the budget nor its periodic check ever saw them.
    """

    @staticmethod
    def _earlier_run(tmp_path):
        """Prepare a scope that does not fit, then age it into a previous run."""
        cache = ThumbnailCache(cache_dir=tmp_path / "previews", max_size_mb=0.001)
        cache.begin_run()
        assert run(
            tmp_path,
            ports=successful_ports([]),
            fetch_preview=lambda _: preview(),
            thumbnail_cache=cache,
        ).complete
        previews = sorted(cache.cache_dir.rglob("*_preview.jpg"))
        aged = time.time() - 3600
        for path in previews:
            os.utime(path, (aged, aged))
        return cache, previews

    def test_a_preview_this_run_reuses_survives_a_budget_it_does_not_fit(self, tmp_path):
        """An earlier run downloaded it; this run reads it back for pixels, heads,
        contact sheets and the caption. Reuse is use -- dropped between those
        stages it becomes a missing fact, not a refetch.
        """
        cache, previews = self._earlier_run(tmp_path)

        cache.begin_run()
        second = run(tmp_path, ports=successful_ports([]), thumbnail_cache=cache)

        assert second.complete
        assert all(path.exists() for path in previews)

    def test_each_overflowing_run_says_so_once_and_names_the_setting(self, tmp_path, caplog):
        """Once per run, not once per eviction pass: the thing the user has to
        change is a line in their config file, and repeating it per pass buries
        it in the run log it is trying to explain.
        """
        caplog.set_level(logging.WARNING)
        cache, _ = self._earlier_run(tmp_path)
        assert len(caplog.records) == 1
        caplog.clear()

        cache.begin_run()
        run(tmp_path, ports=successful_ports([]), thumbnail_cache=cache)

        assert len(caplog.records) == 1
        assert "thumbnail_cache_max_size_mb" in caplog.records[0].getMessage()


def test_the_no_captions_tier_finishes_without_a_caption_server(tmp_path):
    """The NAS tier: every producer the audience gate reads, and no caption request."""
    ports, calls = refusing_ports("captions")

    result = run(
        tmp_path,
        ports=ports,
        fetch_preview=lambda _: preview(),
        preparation_config=EditorialPreparationConfig(tier="no_captions"),
    )

    assert result.complete
    assert result.tier == "no_captions"
    assert [stage for stage, _ in calls] == ["heads", "detectors"]
    assert not [key for key in result.missing_by_producer if key.startswith("description:")]


def test_the_metadata_only_tier_finishes_with_no_onnx_and_no_captions(tmp_path):
    ports, calls = refusing_ports("captions", "heads", "detectors")

    result = run(
        tmp_path,
        ports=ports,
        fetch_preview=lambda _: preview(),
        preparation_config=EditorialPreparationConfig(tier="metadata_only"),
    )

    assert result.complete
    assert calls == []
    assert not result.missing_by_producer and not result.failures


def test_an_undemanded_producer_is_never_reported_missing(tmp_path):
    """A tier that does not ask for captions cannot be blocked by their absence."""
    full = run(
        tmp_path / "full",
        assets=[asset("full1"), asset("full2")],
        ports=PreparationPorts(
            captions=lambda **_: {},
            heads=lambda **_: None,
            detectors=lambda **_: {},
        ),
        fetch_preview=lambda _: preview(),
    )
    reduced = run(
        tmp_path / "reduced",
        assets=[asset("reduced1"), asset("reduced2")],
        ports=PreparationPorts(
            captions=lambda **_: {}, heads=lambda **_: None, detectors=lambda **_: {}
        ),
        fetch_preview=lambda _: preview(),
        preparation_config=EditorialPreparationConfig(tier="metadata_only"),
    )

    assert not full.complete
    assert set(full.missing_by_producer) > set(reduced.missing_by_producer)
    assert reduced.complete


def test_a_run_reports_what_each_stage_cost_and_how_many_pictures_it_saw(tmp_path):
    """A wall-clock total cannot size a tier; seconds per producer per picture can."""
    result = run(
        tmp_path,
        ports=successful_ports([]),
        fetch_preview=lambda _: preview(),
        preparation_config=EditorialPreparationConfig(tier="no_captions"),
    )

    rates = result.stage_rates()
    assert result.pictures_by_stage["previews"] == 2
    assert set(rates) == {"previews", "pixels", "public_heads", "detectors"}
    assert all(seconds >= 0 for seconds in rates.values())


def test_the_configured_caption_key_reaches_the_caption_request(tmp_path):
    ports = successful_ports([])
    real = ports.captions
    sent = []

    def captions(**kwargs):
        sent.append(kwargs.get("api_key"))
        return real(**kwargs)

    run(
        tmp_path,
        ports=replace(ports, captions=captions),
        preparation_config=EditorialPreparationConfig(caption_api_key="caption-token"),
        fetch_preview=lambda _: preview(),
    )

    assert sent == ["caption-token"]


def test_a_caption_endpoint_that_wants_a_token_says_so_and_nothing_else(tmp_path):
    """A refused credential is not a wrong URL, so it must not be reported as one."""

    def refused(**_):
        raise PermissionError("caption endpoint http://vlm.test/v1 answered HTTP 401; set x")

    result = run(
        tmp_path,
        ports=replace(successful_ports([]), captions=refused),
        fetch_preview=lambda _: preview(),
    )

    assert result.failures["captions"] == (
        "caption endpoint http://vlm.test/v1 answered HTTP 401; set x"
    )


def _named_asset(asset_id, *, named=True):
    source = asset(asset_id)
    return source.model_copy(
        update={"people": list(source.people) if named else []},
    )


def _face(client_calls):
    """Stands in for the Immich asset read that carries the face boxes."""

    def fetch(asset_id):
        client_calls.append(asset_id)
        return (
            FaceBox(x1=0.90, y1=0.40, x2=0.95, y2=0.48, named=True, person_id="person-banked"),
            FaceBox(x1=0.20, y1=0.20, x2=0.50, y2=0.60, named=False),
        )

    return fetch


def test_the_faces_of_a_picture_that_names_somebody_are_banked_once(tmp_path):
    calls = []
    assets = [_named_asset("aa1"), _named_asset("bb2", named=False)]

    run(tmp_path, assets=assets, ports=successful_ports([]), fetch_faces=_face(calls))
    run(tmp_path, assets=assets, ports=successful_ports([]), fetch_faces=_face(calls))

    assert calls == ["aa1"]  # never the picture naming nobody, never twice
    assert count_rows(annotation_store(), "face_boxes") == 2


def test_a_picture_whose_faces_were_banked_without_identities_is_read_again(tmp_path):
    """Old boxes say a name was matched, not whose: they are re-read, never guessed."""
    store = annotation_store()
    add_rows(
        store,
        "face_boxes",
        {
            "asset_id": "aa1",
            "ordinal": 0,
            "named": True,
            "x1": 0.1,
            "y1": 0.1,
            "x2": 0.2,
            "y2": 0.2,
        },
    )
    add_rows(
        store,
        "face_reads",
        {"asset_id": "aa1", "producer": "immich-faces-v1", "read_at": "2030-01-01T00:00:00+00:00"},
    )
    calls = []

    run(
        tmp_path, assets=[_named_asset("aa1")], ports=successful_ports([]), fetch_faces=_face(calls)
    )

    assert calls == ["aa1"]
    with store.connect() as connection:
        rows = connection.execute(
            sa.select(face_boxes.c.named, face_boxes.c.person_id).order_by(face_boxes.c.x1)
        ).all()
    assert [tuple(row) for row in rows] == [(False, None), (True, "person-banked")]


def test_a_run_without_a_face_reader_banks_nothing_and_leaves_the_rest_alone(tmp_path):
    run(tmp_path, assets=[_named_asset("aa1")], ports=successful_ports([]))

    store = annotation_store()
    assert count_rows(store, "face_boxes") == 0
    assert count_rows(store, "face_reads") == 0


def test_a_prepared_scope_with_nothing_left_to_do_is_complete_with_no_failures(tmp_path):
    """Completeness is the plain rule again: nothing missing, and nothing failed."""
    run(tmp_path, ports=successful_ports([]), fetch_preview=lambda _: preview())

    result = run(tmp_path, ports=successful_ports([]))

    assert dict(result.failures) == {}
    assert result.complete
