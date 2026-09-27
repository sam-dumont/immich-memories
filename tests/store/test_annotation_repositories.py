"""The annotation repositories answer the same on SQLite and PostgreSQL."""

from __future__ import annotations

from datetime import UTC, datetime

from immich_memories.analysis.editorial_preparation_pixels import PRODUCER_KEY
from immich_memories.analysis.editorial_rule_banked_facts import open_banked_facts
from immich_memories.analysis.editorial_shareability import load_flags
from immich_memories.api.models import Asset, AssetType, Person
from immich_memories.cache.editorial_verdicts import EditorialVerdicts
from immich_memories.cache.embedding_cache import HeadFactStore
from immich_memories.cache.judgment_cache import JudgmentCache
from immich_memories.store.asset_annotations import AssetAnnotationFactRepository
from immich_memories.store.cut_measurements import (
    PendingMeasurements,
    banked_speech_regions,
    measured_clock_offsets,
)
from immich_memories.store.editorial_preparation import (
    faces_unread,
    missing_facts,
    remember_assets,
    remember_faces,
)
from immich_memories.store.episode_readings import (
    BankedEpisodeReading,
    EpisodeReadingIdentity,
    EpisodeReadingStore,
    EpisodeRepresentative,
)
from immich_memories.store.library_catalogue import CatalogueStore, LibraryAccount
from immich_memories.store.library_overviews import library_period_account
from immich_memories.store.motion_lines import (
    DESCRIBED,
    MotionLine,
    motion_line_row,
    remember_motion_lines,
    settled_motion_lines,
)
from immich_memories.triage.heads import HeadFact
from tests.annotation_rows import add_rows, read_rows

TAKEN = datetime(2025, 6, 1, 10, tzinfo=UTC)
HEADS = {"activity": "public-v1"}
CULL = "cull-v1"


def _asset(asset_id: str, *people: str) -> Asset:
    return Asset(
        id=asset_id,
        type=AssetType.IMAGE,
        fileCreatedAt=TAKEN,
        fileModifiedAt=TAKEN,
        updatedAt=TAKEN,
        originalFileName=f"{asset_id}.jpg",
        people=[Person(id=f"id-{name}", name=name) for name in people],
    )


def test_source_metadata_and_people_replace_what_the_last_read_said(store):
    remember_assets(store, [_asset("a", "Person B", "Person B", "person a")])
    remember_assets(store, [_asset("a", "Person B", "person a")])

    people = sorted(row["person_name"] for row in read_rows(store, "asset_people"))
    assert people == ["Person B", "person a"]
    [asset] = read_rows(store, "annotation_assets")
    assert asset["taken_at"] == datetime(2025, 6, 1, 10)


def test_missing_facts_names_what_each_producer_still_owes(store):
    ids = [f"asset-{n:04d}" for n in range(1200)]
    HeadFactStore(store).remember_facts(
        {ids[0]: [HeadFact(head="activity", label="yes", confidence=0.4, version="public-v1")]},
        encoder_key="enc",
    )

    missing, unavailable = missing_facts(
        store,
        ids,
        description_model="some-model",
        head_versions=HEADS,
        pixel_producer_key=PRODUCER_KEY,
        preview_for=lambda _asset_id: b"",
    )

    assert unavailable == ()
    assert missing["head:activity@public-v1"] == tuple(ids[1:])
    assert len(missing["description:some-model"]) == 1200


def test_the_fact_reader_keeps_the_order_the_file_gave(store):
    remember_assets(store, [_asset("a", "zed", "Amy", "amy")])
    remember_faces(store, {"a": []})
    add_rows(
        store,
        "asset_flags",
        {"asset_id": "a", "flag": "screen", "source": "a-head", "evidence": '{"reason": "screen"}'},
        {"asset_id": "a", "flag": "blurry", "source": "a-head", "evidence": "{}"},
    )

    batch = AssetAnnotationFactRepository(
        store, description_model=None, head_versions=HEADS, pixel_producer_key=PRODUCER_KEY
    ).facts_for(("a",))

    [facts] = batch.facts
    assert [person.name for person in facts.people] == ["Amy", "amy", "zed"]
    assert [flag.flag for flag in facts.flags] == ["blurry", "screen"]
    assert faces_unread(store, ["a", "b"]) == ("b",)


def test_flags_are_read_for_a_lifetime_of_pictures(store):
    add_rows(
        store,
        "asset_flags",
        *({"asset_id": f"p{n}", "flag": "nsfw", "source": "d"} for n in range(1000)),
    )

    assert len(load_flags(store, [f"p{n}" for n in range(1000)])) == 1000


def test_a_reading_is_banked_once_and_found_by_its_identity(store, tmp_path):
    identity = EpisodeReadingIdentity("group", "producer", "evidence")
    reading = BankedEpisodeReading(
        identity=identity,
        full_asset_ids=("a", "b"),
        what_happened="A picnic.",
        representatives=(EpisodeRepresentative("a", "the table"),),
        cull_decisions=(),
    )
    bank = EpisodeReadingStore(store)
    bank.remember([reading, reading])
    bank.remember_refusals([(EpisodeReadingIdentity("other", "producer", "evidence"), "too long")])

    assert bank.readings_for([identity])["group"] == reading
    assert bank.refusals_for([EpisodeReadingIdentity("other", "producer", "evidence")]) == {
        "other": "too long"
    }
    banked = open_banked_facts(
        bank_dir=tmp_path / "structure-banks" / "case",
        attempts_dir=None,
        store=store,
        audience="family",
        episode_cards={"M1": _Card("group", "evidence")},
    )
    assert banked.representatives == {"M1": ("a",)}


def test_cut_measurements_answer_only_for_the_source_they_measured(store):
    with PendingMeasurements(store) as pending:
        pending.speech_regions(asset_id="v", producer="p", source_digest="d1", regions=[(1, 2)])
    with PendingMeasurements(store) as pending:
        pending.speech_regions(asset_id="v", producer="p", source_digest="d2", regions=[])
        pending.clock_offset(pair=("x", "y"), producer="p", source_digest="d", seconds=None)

    assert banked_speech_regions(store, {"v": "d2"}, "p") == {"v": ()}
    assert banked_speech_regions(store, {"v": "d1"}, "p") == {}
    assert measured_clock_offsets(store, "p") == {("x", "y"): ("d", None)}


def test_a_motion_line_is_replaced_by_its_producer(store):
    for text in ("first", "second"):
        remember_motion_lines(
            store,
            [
                motion_line_row(
                    asset_id="v",
                    producer="p",
                    source_digest="d",
                    line=MotionLine(DESCRIBED, text, 3),
                    bytes_read=10,
                )
            ],
        )

    assert settled_motion_lines(store, {"v": "d"}, "p") == {
        "v": MotionLine(DESCRIBED, "second", 3, False)
    }


def test_verdicts_judgments_and_accounts_round_trip(store):
    verdicts = EditorialVerdicts(store)
    verdicts.remember([("a", "blurry"), ("a", "kept")], pass_version=CULL)
    judgments = JudgmentCache(store)
    judgments.remember("key", "answer")
    judgments.remember_completion_failure("failed", {"tokens": 1})
    CatalogueStore(store).remember(
        [LibraryAccount("node", "month", "2025-06", "June.", ("a",))] * 2
    )

    assert verdicts.recall(["a", "b"], pass_version=CULL) == {"a": "kept"}
    assert judgments.answer_for("key") == "answer"
    judgments.flush()
    assert [row["answer"] for row in read_rows(store, "judgments")] == ["answer"]
    judgments.forget("key")
    assert judgments.answer_for("key") is None
    assert judgments.completion_failure_for("failed") == {"tokens": 1}
    assert library_period_account(store, "2025-06") == "June."


class _Card:
    def __init__(self, episode_id: str, evidence_key: str) -> None:
        self.episode_id = episode_id
        self.evidence_key = evidence_key
