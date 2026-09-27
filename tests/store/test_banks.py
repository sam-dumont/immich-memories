"""The audience bank, the block vote banks and the owner's review edits, on every backend."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import httpx
import pytest

from immich_memories.analysis import editorial_shareability as share
from immich_memories.analysis.editorial_block_votes import vote_blocks
from immich_memories.analysis.editorial_rule_banked_facts import open_banked_facts
from immich_memories.analysis.editorial_structure_audience import AudienceBank
from immich_memories.store.owner_edits import keep_owner_edits, owner_edits_of_attempt
from immich_memories.store.vote_banks import VoteBank

DETECTOR_HOLD = {"verdict": "do_not_show", "finding": "exposure_evidence", "policy": "nsfw-head"}


def _text_hold(verdict: str) -> dict:
    return {
        "verdict": verdict,
        "finding": share.PRIVATE_ACTIVITY,
        "policy": share.AUDIENCE_PROMPT_VERSION,
        "parsed": True,
        "activity": "bathing",
    }


def test_a_hold_outlives_the_bank_that_cast_it(store):
    AudienceBank(store, answerer="full|reader").hold("pic", DETECTOR_HOLD)

    assert AudienceBank(store, answerer="another|reader").held("pic")["verdict"] == "do_not_show"


def test_a_detector_hold_is_never_cleared_by_a_later_read(store):
    AudienceBank(store, answerer="full|reader").hold("pic", DETECTOR_HOLD)

    later = AudienceBank(store, answerer="full|reader")
    later.hold("pic", {"verdict": "share", "finding": "clear", "policy": "v9", "parsed": True})
    later.hold("pic", _text_hold("family_only") | {"activity": None})

    assert AudienceBank(store, answerer="x").held("pic")["verdict"] == "do_not_show"


def test_holds_are_kept_per_source_and_a_new_prompt_replaces_only_the_text_one(store):
    bank = AudienceBank(store, answerer="full|reader")
    bank.hold("pic", _text_hold("family_only"))
    bank.hold("pic", {**DETECTOR_HOLD, "verdict": "family_only"})

    with (
        patch.object(share, "AUDIENCE_PROMPT_VERSION", "audience-next"),
    ):
        fresh = AudienceBank(store, answerer="full|reader")
        # The old text hold no longer applies; the detector's still does.
        assert fresh.held("pic")["finding"] == "exposure_evidence"
        fresh.hold("pic", _text_hold("do_not_show") | {"policy": "audience-next"})
        assert AudienceBank(store, answerer="x").held("pic")["verdict"] == "do_not_show"

    # Back under the old prompt, the new text hold is stale and the detector's stands alone.
    assert AudienceBank(store, answerer="x").held("pic") == {
        "verdict": "family_only",
        "finding": "exposure_evidence",
        "policy": "nsfw-head",
    }


def test_a_refusal_the_bank_holds_reaches_the_draft_that_asks_nothing(store):
    AudienceBank(store, answerer="full|reader").hold("held", DETECTOR_HOLD)
    AudienceBank(store, answerer="full|reader").hold(
        "family", {**DETECTOR_HOLD, "verdict": "family_only"}
    )

    shareable = open_banked_facts(
        attempts_dir=None, store=store, audience="shareable", episode_cards={}
    )
    family = open_banked_facts(attempts_dir=None, store=store, audience="family", episode_cards={})

    assert shareable.refused == {"held", "family"}
    assert family.refused == {"held"}


def test_an_answer_is_served_only_to_the_reader_that_gave_it(store):
    AudienceBank(store, answerer="full|laya").keep("key", {"parsed": True, "verdict": "share"})
    AudienceBank(store, answerer="full|laya").keep(
        "unparsed", {"parsed": False, "verdict": "share"}
    )

    assert AudienceBank(store, answerer="full|laya").answer("key") == {
        "parsed": True,
        "verdict": "share",
    }
    assert AudienceBank(store, answerer="full|laya").answer("unparsed") is None
    assert AudienceBank(store, answerer="full|rules").answer("key") is None


def test_two_runs_keep_each_others_audience_answers_and_holds(store):
    first = AudienceBank(store, answerer="reader")
    second = AudienceBank(store, answerer="reader")

    first.hold("held-picture", DETECTOR_HOLD)
    first.keep("first-key", {"parsed": True, "verdict": "share"})
    second.keep("second-key", {"parsed": True, "verdict": "family_only"})

    reread = AudienceBank(store, answerer="reader")
    assert reread.answer("first-key") == {"parsed": True, "verdict": "share"}
    assert reread.answer("second-key") == {"parsed": True, "verdict": "family_only"}
    assert reread.held("held-picture")["verdict"] == "do_not_show"


def test_two_cuts_holding_one_picture_at_once_keep_the_stricter_hold(store):
    banks = [AudienceBank(store, answerer="r") for _ in range(8)]
    verdicts = ["family_only", "do_not_show"] * 4

    with ThreadPoolExecutor(8) as pool:
        list(
            pool.map(
                lambda pair: pair[0].hold("pic", {**DETECTOR_HOLD, "verdict": pair[1]}),
                zip(banks, verdicts, strict=True),
            )
        )

    assert AudienceBank(store, answerer="r").held("pic")["verdict"] == "do_not_show"


class _Judge:
    """# WHY: stands in for the model, the one outside call a vote makes; names every row."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def ask(self, stage: str, prompt: str, *, max_tokens: int) -> str:
        self.calls.append(stage)
        labels = [
            line.split(":")[0]
            for line in prompt.splitlines()
            if line[:1] == "P" and line[1:2].isdigit()
        ]
        return json.dumps({"worthy": dict.fromkeys(labels, "stands out")})


def _vote(store, judge, items, scope="case"):
    bank = VoteBank(store, "memory-worthy", scope)
    return vote_blocks(
        judge,
        stage="worthy",
        items=items,
        label_of={x: f"P{i:02d}" for i, x in enumerate(items)},
        row_of=lambda x: f"P{items.index(x):02d}: {x}",
        prompt_of=lambda listing: f"Pick.\n{listing}",
        answer_key="worthy",
        bank_key=lambda block: "|".join(block),
        bank=bank,
        save=bank.save,
        model_identity="reader-v1",
        row_key=lambda x: x,
    )


def test_a_banked_vote_is_reused_by_the_next_film_without_asking(store):
    items = [f"happening-{n}" for n in range(15)]
    first = _Judge()
    votes, _rounds = _vote(store, first, items)
    second = _Judge()

    again, _ = _vote(store, second, items)

    assert first.calls and second.calls == []
    assert again == votes
    assert all(count == 2 for count, _why in again.values())


def test_a_vote_bank_is_scoped_to_its_case(store):
    _vote(store, _Judge(), ["a", "b"], scope="one-case")
    other = _Judge()

    _vote(store, other, ["a", "b"], scope="another-case")

    assert other.calls


def test_two_runs_saving_one_vote_bank_keep_both_runs_entries(store):
    first = VoteBank(store, "thesis-fit", "case")
    second = VoteBank(store, "thesis-fit", "case")
    first["block-1"] = {"source": {"P01": ""}}
    first.setdefault("rows", {}).update({"row-1": {"votes": 2, "why": ""}})
    second["block-2"] = {"source": {}}
    second.setdefault("rows-one-order", {})["partial-2"] = {"votes": 1, "why": "x"}
    first.save()
    second.save()

    banked = VoteBank(store, "thesis-fit", "case")

    assert set(banked) == {"block-1", "block-2", "rows", "rows-one-order"}
    assert banked["rows"] == {"row-1": {"votes": 2, "why": ""}}
    assert banked["rows-one-order"] == {"partial-2": {"votes": 1, "why": "x"}}


def test_an_owner_edit_comes_back_exactly_as_decided(store, tmp_path):
    record = {
        "version": "editorial-owner-edits-v1",
        "edit_id": "0f" * 16,
        "removed_asset_ids": ["chosen-0", "chosen-é"],
        "interval_edits": [
            {
                "asset_id": "chosen-2",
                "render_mode": "motion",
                "original_interval": [0, 4.25],
                "selected_interval": [1, 3.125],
            }
        ],
        "timing_policy_changed": False,
        "original_policy": {"target_seconds": 60.0, "transition": None},
        "requested_policy": {"target_seconds": 45.5, "transition": "fade"},
    }
    keep_owner_edits(store, record, film=tmp_path / "memory.mp4", attempt=tmp_path / "attempt-1")

    assert owner_edits_of_attempt(store, "attempt-1") == [record]
    assert owner_edits_of_attempt(store, "attempt-2") == []


@pytest.mark.asyncio
async def test_a_music_mood_is_asked_once_and_reused(store, tmp_path, monkeypatch):
    from immich_memories.audio.text_mood import mood_for_cut
    from immich_memories.config_loader import Config

    monkeypatch.setenv("IMMICH_MEMORIES_DATABASE_URL", store.location.url)
    if store.location.schema:
        monkeypatch.setenv("IMMICH_MEMORIES_DATABASE_SCHEMA", store.location.schema)
    config = Config(
        llm={"base_url": "http://localhost:11434", "model": "reader", "provider": "ollama"}
    )
    config.cache.directory = str(tmp_path / "cache")
    attempt = tmp_path / "attempt"
    attempt.mkdir()
    (attempt / "plan.private.json").write_text(
        json.dumps({"story": {"thesis": "A day at the fair"}})
    )
    response = httpx.Response(
        200,
        request=httpx.Request("POST", "http://localhost"),
        json={
            "response": '{"primary_mood":"playful","energy_level":"high",'
            '"tempo_suggestion":"fast","genre_suggestions":["pop"],"specific_style":null}',
            "done": True,
        },
    )
    # WHY: the model's HTTP endpoint is the only outside boundary; the bank is the real store.
    with patch("httpx.AsyncClient.post", return_value=response) as post:
        first = await mood_for_cut(config, attempt, ())
        second = await mood_for_cut(config, attempt, ())

    assert first == second and first.source == "cut_text"
    assert post.call_count == 1
