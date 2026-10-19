"""Selection reads each picture's hash and scene once per run, and decides the same cut."""

from __future__ import annotations

from collections import Counter

import numpy as np

from immich_memories.analysis.selection.picture_admission import PictureAdmission
from tests.test_editorial_thin_gates import Audience, Standing, shot

HASHES = {"a": "ffffffffffffffff", "b": "ffffffffffffff7f", "c": "0000ffff0000ffff"}


def _admission(reads, prints=None, scene_reads=None):
    def thumbnail_hash(asset):
        reads[asset] += 1
        return HASHES.get(asset)

    def scene_print(asset):
        scene_reads[asset] += 1
        return prints.get(asset)

    return PictureAdmission(
        standing=Standing({}),
        audience=Audience(),
        thumbnail_hash=thumbnail_hash,
        scene_print=scene_print if prints is not None else None,
    )


def test_a_candidate_is_read_once_however_many_candidates_are_tried_against_the_cut():
    reads: Counter[str] = Counter()
    admission = _admission(reads)
    cut = [shot("a", taken="2024-02-01T09:00:00"), shot("c", taken="2024-02-01T11:00:00")]
    tiers = {"S001": "remarkable"}

    answers = [
        admission.admits(shot(name, taken=f"2024-02-01T1{n}:30:00"), cut=cut, tier_of=tiers)
        for n, name in enumerate(["b", "b", "b"], start=2)
    ]

    assert [a.rule if a else None for a in answers] == ["look-alike"] * 3
    assert reads == {"a": 1, "b": 1, "c": 1}


def test_a_scene_print_is_read_once_across_admissions():
    reads: Counter[str] = Counter()
    scenes: Counter[str] = Counter()
    vector = np.array([1.0, 0.0])
    admission = _admission(reads, {"a": vector, "c": vector, "b": np.array([0.0, 1.0])}, scenes)
    cut = [shot("a", taken="2024-02-01T09:00:00")]
    tiers = {"S001": "remarkable"}

    for _ in range(4):
        refusal = admission.admits(shot("c", taken="2024-02-01T09:02:00"), cut=cut, tier_of=tiers)
        assert refusal is not None
        assert refusal.rule == "look-alike"

    assert scenes == {"a": 1, "c": 1}


def test_a_preview_that_was_not_there_yet_is_asked_again_once_it_is():
    answers = {"a": None}
    admission = PictureAdmission(
        standing=Standing({}),
        audience=Audience(),
        thumbnail_hash=lambda asset: answers.get(asset, HASHES.get(asset)),
    )
    cut = [shot("a", taken="2024-02-01T09:00:00")]
    tiers = {"S001": "remarkable"}
    candidate = shot("b", taken="2024-02-01T09:30:00")

    assert admission.admits(candidate, cut=cut, tier_of=tiers) is None
    answers["a"] = HASHES["a"]

    refusal = admission.admits(candidate, cut=cut, tier_of=tiers)
    assert refusal is not None
    assert refusal.rule == "look-alike"


def test_an_annotation_line_is_parsed_once_however_often_it_is_asked_about(monkeypatch):
    from immich_memories.analysis.stories import replies

    line = "Park | with Ana (partner; adult); Bo (son; aged 4)"
    replies._people_on.cache_clear()
    replies._relations_on.cache_clear()
    parsed = Counter[str]()

    class Counting:
        def __init__(self, pattern):
            self._pattern = pattern

        def findall(self, text):
            parsed["findall"] += 1
            return self._pattern.findall(text)

    monkeypatch.setattr(replies, "_PERSON_NOTE", Counting(replies._PERSON_NOTE))

    answers = [replies.close_family_on(line) for _ in range(5)]
    first = replies.people_on(line)
    first["Ana"] = "mutated"

    assert answers[0] == answers[4] == {"Ana": "partner", "Bo": "son"}
    assert replies.people_on(line)["Ana"] == "partner"
    assert parsed["findall"] == 1


def test_an_assets_digest_is_computed_once_and_a_changed_copy_gets_its_own(monkeypatch):
    from immich_memories.analysis.clips.bound_sample import source_metadata_digest
    from immich_memories.analysis.clips.motion_facts import motion_source_key
    from immich_memories.api.models import Asset
    from tests.conftest import make_asset

    dumps = Counter[str]()
    original_dump = Asset.model_dump

    def counting_dump(self, *args, **kwargs):
        dumps[self.id] += 1
        return original_dump(self, *args, **kwargs)

    monkeypatch.setattr(Asset, "model_dump", counting_dump)
    asset = make_asset("digest-asset-001")

    digests = {source_metadata_digest(asset) for _ in range(10)}
    keys = {motion_source_key(asset) for _ in range(10)}
    starred = asset.model_copy(update={"is_favorite": True})

    assert len(digests) == len(keys) == 1
    assert dumps["digest-asset-001"] == 2
    assert source_metadata_digest(starred) != source_metadata_digest(asset)
    assert motion_source_key(starred) != motion_source_key(asset)


def test_a_story_folds_no_further_than_its_grant_and_keeps_the_same_first_moments():
    from immich_memories.analysis.selection.capacity import distinct_choices
    from immich_memories.analysis.stories.shortlist import DepictedChoice

    names = [f"p{n:02}" for n in range(40)]
    choices = [
        DepictedChoice(
            key=f"c{n}",
            episode="S1",
            taken=f"2030-05-01T{n // 4:02}:{n % 4 * 10:02}:00",
            content="",
            primary=name,
            alternatives=[],
        )
        for n, name in enumerate(names)
    ]
    units = {
        c.primary: (None, {"asset_id": c.primary, "taken": c.taken, "kind": "still"})
        for c in choices
    }
    asked = Counter[str]()

    def alike(candidate, keeper):
        asked["pairs"] += 1
        return int(candidate["asset_id"][1:]) % 3 == 0 and int(keeper["asset_id"][1:]) % 3 == 0

    everything = distinct_choices(choices, units, "S1", alike, None)
    full_pairs = asked["pairs"]
    asked.clear()
    first_three = distinct_choices(choices, units, "S1", alike, None, limit=3)

    assert [c.key for c in first_three] == [c.key for c in everything][:3]
    assert asked["pairs"] < full_pairs / 4


def test_the_partition_count_behind_free_matches_a_recount_of_the_cut_on_every_call(
    tmp_path, monkeypatch
):
    from immich_memories.analysis.selection.carriers import CarrierAdmission
    from immich_memories.analysis.stories.slots import PartitionedSlots
    from tests.editorial_story_fixtures import AnnualStoryJudge
    from tests.test_editorial_duration_planner_integration import run
    from tests.test_editorial_on_this_day_year_limit import make_source

    original_free = CarrierAdmission.free
    recounted = Counter[str]()
    asked = Counter[str]()
    original_of_asset = PartitionedSlots.of_asset

    def counting_of_asset(self, asset):
        asked["of_asset"] += 1
        return original_of_asset(self, asset)

    def checked_free(self, asset):
        answer = original_free(self, asset)
        limit = self.parts.limit
        expected = (
            asset not in self._taken
            and asset in self._unit_by_asset
            and asset not in self._excluded
            and (
                limit is None
                or original_of_asset(self.parts, asset) is None
                or sum(
                    original_of_asset(self.parts, c["asset_id"])
                    == original_of_asset(self.parts, asset)
                    for c in self.carriers
                )
                < limit
            )
        )
        recounted["calls"] += 1
        assert answer == expected
        return answer

    monkeypatch.setattr(CarrierAdmission, "free", checked_free)
    run(make_source(tmp_path, per_year_limit=1), AnnualStoryJudge())
    monkeypatch.undo()
    assert recounted["calls"] > 0

    monkeypatch.setattr(PartitionedSlots, "of_asset", counting_of_asset)
    run(make_source(tmp_path / "again", per_year_limit=1), AnnualStoryJudge())
    free_calls = recounted["calls"]
    # One partition lookup per question about a picture, not one per picture in the cut.
    assert asked["of_asset"] < 4 * free_calls


def test_pictures_in_one_cell_cost_one_store_question_and_name_the_same_place():
    from immich_memories.analysis.places.geocoder import PlaceGeocoder
    from immich_memories.db import open_store

    store = open_store()
    connects = Counter[str]()

    class CountingStore:
        """# WHY: the real store, with every question to it counted."""

        def connect(self):
            connects["connect"] += 1
            return store.connect()

        def begin(self):
            return store.begin()

    fetched = Counter[str]()

    def fetch(_latitude, _longitude):
        fetched["calls"] += 1
        return {"city": "River City", "country": "France"}

    geocoder = PlaceGeocoder(CountingStore(), "fr", fetch)  # type: ignore[arg-type]
    first = geocoder.address(48.8566, 2.3522)
    again = [geocoder.address(48.85661, 2.35221) for _ in range(20)]
    fresh = PlaceGeocoder(store, "fr", lambda *_: {"city": "Never Asked"}).address(48.8566, 2.3522)

    assert all(answer == first for answer in again)
    assert fresh == first
    assert fetched["calls"] == 1
    assert connects["connect"] == 1


def test_pixel_facts_are_read_for_the_run_assets_only_and_agree_with_the_whole_table():
    from immich_memories.analysis.preparation.pixels import PRODUCER_KEY
    from immich_memories.analysis.structure.planning_input import read_pixel_facts
    from immich_memories.db import now_db, open_store
    from immich_memories.db.tables import pixel_facts
    from immich_memories.store.batches import bank_rows

    store = open_store()
    rows = [
        {
            "asset_id": f"asset-{n:03}",
            "producer_key": PRODUCER_KEY,
            "sharpness": float(n),
            "brightness": 100.0 + n,
            "computed_at": now_db(),
        }
        for n in range(30)
    ]
    bank_rows(store, pixel_facts, rows, keys=("asset_id",))
    wanted = ["asset-003", "asset-004", "asset-029", "asset-missing"]

    facts = read_pixel_facts(store, PRODUCER_KEY, wanted)
    everything = read_pixel_facts(store, PRODUCER_KEY, [row["asset_id"] for row in rows])

    assert facts == {key: everything[key] for key in wanted if key in everything}
    assert set(facts) == {"asset-003", "asset-004", "asset-029"}
    assert facts["asset-004"] == (4.0, 104.0)
    assert len(everything) == 30


def test_the_audit_copy_of_the_audience_answers_is_written_once_at_flush(tmp_path, monkeypatch):
    import json

    from immich_memories.analysis.audience import verdicts
    from immich_memories.analysis.audience.verdicts import AudienceBank, AudienceGate
    from immich_memories.db import open_store
    from tests.test_editorial_shareability_tiers import Annotation
    from tests.test_editorial_strict_sharing import Judge

    writes = Counter[str]()
    original = verdicts.write_secret_file

    def counting_write(path, text):
        writes["writes"] += 1
        return original(path, text)

    monkeypatch.setattr(verdicts, "write_secret_file", counting_write)
    names = [f"scene-{n}" for n in range(12)]
    bank_path = tmp_path / "shareability.private.json"
    library = AudienceBank(open_store(), answerer="full|model-a")
    gate = AudienceGate(
        Judge(),
        audience="family",
        annotations={n: Annotation(f"A landscape number {n} at sunset.") for n in names},
        flag_rows={},
        lines={n: f"A landscape number {n} at sunset." for n in names},
        bank_path=bank_path,
        library=library,
    )

    verdicts_seen = [gate.verdict_of({"asset_id": n, "members": [n]}) for n in names]
    assert writes["writes"] == 0

    library.flush()
    library.flush()

    assert writes["writes"] == 1
    assert len(json.loads(bank_path.read_text())) == len(gate.bank) > 1
    assert set(verdicts_seen) == {"share"}


def test_the_banked_refusals_the_cut_reads_are_the_holds_its_bank_already_loaded():
    from immich_memories.analysis.audience.verdicts import AudienceBank, library_refusals
    from immich_memories.db import open_store

    store = open_store()
    bank = AudienceBank(store, answerer="full|model-a")
    bank.hold(
        "held-picture",
        {"verdict": "do_not_show", "finding": "nudity", "source": "head", "parsed": True},
    )
    bank.flush()
    loaded = AudienceBank(store, answerer="full|model-a")

    assert loaded.refusals("family") == library_refusals(store, "family") == {"held-picture"}


def _old_pages(identity, ids, *, max_assets, facts, max_chars):
    """The paging rule as it was written: render the whole page again for every asset added."""
    from immich_memories.analysis.reading.episode_answers import EpisodeRequestScope
    from immich_memories.analysis.reading.episode_prompt import episode_prompt

    pages, current = [], ()
    count = max(len(ids), 2)
    for asset_id in ids:
        proposed = (*current, asset_id)
        scope = EpisodeRequestScope(identity, ids, proposed, count, count)
        if current and (
            len(proposed) > max_assets or len(episode_prompt((scope,), facts)) > max_chars
        ):
            pages.append(current)
            current = (asset_id,)
        else:
            current = proposed
    if current:
        pages.append(current)
    return pages


def test_episode_pages_split_where_they_always_did_and_render_the_prompt_once(monkeypatch):
    import random

    from immich_memories.analysis.reading import episode_paging
    from immich_memories.analysis.reading.episode_answers import EpisodeRequestScope
    from immich_memories.analysis.reading.episode_prompt import EpisodePromptFacts
    from immich_memories.store.episode_readings import EpisodeReadingIdentity

    identity = EpisodeReadingIdentity(group_id="e1", producer_key="p", evidence_key="e")
    rng = random.Random(7)
    renders = Counter[str]()
    split = Counter[str]()
    real_prompt = episode_paging.episode_prompt

    def counting_prompt(*args, **kwargs):
        renders["prompt"] += 1
        return real_prompt(*args, **kwargs)

    monkeypatch.setattr(episode_paging, "episode_prompt", counting_prompt)
    for _trial in range(40):
        ids = tuple(f"asset-{n:03}" for n in range(rng.randint(1, 60)))
        lines = {a: "x" * rng.randint(1, 400) for a in ids}
        facts = EpisodePromptFacts(lines=lines, album_names=lambda _ids: ["Holiday", "Beach"])
        # the fixed text of the prompt alone is a few thousand characters
        max_chars = 7000 + rng.choice([500, 3000, 9000])
        cap = rng.choice([3, 8, 100])
        renders.clear()

        got = episode_paging.episode_page_scopes(
            identity, ids, max_assets_per_page=cap, facts=facts, max_prompt_chars=max_chars
        )

        whole = EpisodeRequestScope(identity, ids, ids, 1, 1)
        if len(ids) <= cap and len(real_prompt((whole,), facts)) <= max_chars:
            assert [s.page_asset_ids for s in got] == [ids]
            continue
        expected = _old_pages(identity, ids, max_assets=cap, facts=facts, max_chars=max_chars)
        assert [s.page_asset_ids for s in got] == expected
        split["trials"] += len(expected) > 1
        assert renders["prompt"] <= 2
    assert split["trials"] > 10


def test_a_pack_merges_only_the_episodes_it_touched(tmp_path, monkeypatch):
    import asyncio
    import re

    from immich_memories.analysis.judgments import text_gateway as gateway
    from immich_memories.analysis.reading import episode_reader
    from immich_memories.config.models.llm import LLMConfig
    from tests.test_episode_reader_concurrency import _answer, _reader

    async def completion(prompt, _config, **_kwargs):
        await asyncio.sleep(0)
        return _answer(int(re.search(r"event-(\d+)", prompt)[1]))

    merged_rows: list[int] = []
    real_merge = episode_reader._merge_complete_readings

    def recording_merge(missing, request_scopes, page_readings):
        merged_rows.append(len(missing))
        return real_merge(missing, request_scopes, page_readings)

    # WHY: the hosted completion is the one outside call; the reader, store and merge are real.
    monkeypatch.setattr(gateway, "query_llm", completion)
    monkeypatch.setattr(episode_reader, "_merge_complete_readings", recording_merge)
    config = LLMConfig(
        enabled=True, base_url="https://api.openai.com/v1", provider="openai", model="test-reader"
    )
    reader, projections = _reader(tmp_path, config)

    result = reader.read(projections)

    assert [e.reading.what_happened for e in result.episodes] == [
        f"Family event {n} happened." for n in range(5)
    ]
    assert merged_rows == [1] * 5
