"""Reusable episode meaning is stored at full-membership identity."""

from __future__ import annotations

from dataclasses import replace

from tests.annotation_rows import annotation_store


def test_episode_reading_round_trips_only_for_the_version_that_produced_it() -> None:
    from immich_memories.store.episode_readings import (
        BankedEpisodeReading,
        EpisodeCullDecision,
        EpisodeReadingIdentity,
        EpisodeReadingStore,
        EpisodeRepresentative,
    )

    identity = EpisodeReadingIdentity.from_annotations(
        group_id="episode-v1-full-library-membership",
        producer_key="episode-text:model-a:prompt-v1:schema-v1",
        annotation_lines={
            "party-wide": "party-wide | birthday party",
            "friend-closeup": "friend-closeup | friend beside cake",
            "receipt": "receipt | photographed receipt",
        },
    )
    reading = BankedEpisodeReading(
        identity=identity,
        full_asset_ids=("party-wide", "friend-closeup", "receipt"),
        what_happened="A friend joins a birthday party.",
        representatives=(
            EpisodeRepresentative(
                asset_id="friend-closeup",
                reason="Shows the friend beside the cake.",
            ),
        ),
        cull_decisions=(EpisodeCullDecision(asset_id="receipt", bucket="notes"),),
    )
    store = EpisodeReadingStore(annotation_store())
    store.remember((reading,))

    assert (
        store.readings_for((identity,)),
        store.readings_for(
            (
                replace(
                    identity,
                    producer_key="episode-text:model-a:prompt-v2:schema-v1",
                ),
            )
        ),
    ) == ({identity.group_id: reading}, {})


def test_episode_producer_key_covers_every_semantic_input() -> None:
    from immich_memories.store.episode_readings import EpisodeReadingProducer

    producer = EpisodeReadingProducer(
        model_id="qwen3-vl-30b",
        prompt_version="episode-prompt-v1",
        schema_version="episode-schema-v1",
        annotation_renderer_version="annotation-line-v1",
        annotation_versions=(
            "description:smolvlm2-envelope-v2",
            "heads:public-v1",
        ),
    )

    keys = {
        producer.key(),
        replace(producer, model_id="qwen3-vl-30b-v2").key(),
        replace(producer, prompt_version="episode-prompt-v2").key(),
        replace(producer, schema_version="episode-schema-v2").key(),
        replace(producer, annotation_renderer_version="annotation-line-v2").key(),
        replace(producer, annotation_versions=("description:smolvlm2-envelope-v3",)).key(),
    }

    assert len(keys) == 6


def test_episode_identity_changes_when_rendered_annotation_evidence_changes() -> None:
    from immich_memories.store.episode_readings import EpisodeReadingIdentity

    original = EpisodeReadingIdentity.from_annotations(
        group_id="episode-v1-full-library-membership",
        producer_key="producer-v1",
        annotation_lines={"asset-a": "asset-a | at home", "asset-b": "asset-b | outside"},
    )
    reordered = EpisodeReadingIdentity.from_annotations(
        group_id="episode-v1-full-library-membership",
        producer_key="producer-v1",
        annotation_lines={"asset-b": "asset-b | outside", "asset-a": "asset-a | at home"},
    )
    changed = EpisodeReadingIdentity.from_annotations(
        group_id="episode-v1-full-library-membership",
        producer_key="producer-v1",
        annotation_lines={"asset-a": "asset-a | at home", "asset-b": "asset-b | at a race"},
    )

    assert original == reordered
    assert original != changed


def test_changed_episode_evidence_is_a_cache_miss() -> None:
    from immich_memories.store.episode_readings import (
        BankedEpisodeReading,
        EpisodeReadingIdentity,
        EpisodeReadingStore,
        EpisodeRepresentative,
    )

    old_identity = EpisodeReadingIdentity.from_annotations(
        group_id="episode-v1-full-library-membership",
        producer_key="producer-v1",
        annotation_lines={"asset-a": "asset-a | an ordinary walk"},
    )
    changed_identity = EpisodeReadingIdentity.from_annotations(
        group_id=old_identity.group_id,
        producer_key=old_identity.producer_key,
        annotation_lines={"asset-a": "asset-a | a charity walk"},
    )
    reading = BankedEpisodeReading(
        identity=old_identity,
        full_asset_ids=("asset-a",),
        what_happened="An ordinary walk.",
        representatives=(EpisodeRepresentative("asset-a", "Shows the walk."),),
        cull_decisions=(),
    )
    store = EpisodeReadingStore(annotation_store())
    store.remember((reading,))

    assert store.readings_for((old_identity,)) == {old_identity.group_id: reading}
    assert store.readings_for((changed_identity,)) == {}


def test_a_reading_keeps_the_moments_it_said_are_worth_a_record() -> None:
    from immich_memories.store.episode_readings import (
        BankedEpisodeReading,
        EpisodeReadingIdentity,
        EpisodeReadingStore,
        EpisodeRepresentative,
    )

    identity = EpisodeReadingIdentity.from_annotations(
        group_id="episode-with-a-record",
        producer_key="producer-v3",
        annotation_lines={"wide": "wide | the room", "steps": "steps | walking unaided"},
    )
    reading = BankedEpisodeReading(
        identity=identity,
        full_asset_ids=("wide", "steps"),
        what_happened="An afternoon at home.",
        representatives=(EpisodeRepresentative("wide", "Shows the room."),),
        cull_decisions=(),
        notable_moments=(EpisodeRepresentative("steps", "walking unaided for the first time"),),
    )
    store = EpisodeReadingStore(annotation_store())
    store.remember((reading,))

    assert store.readings_for((identity,)) == {identity.group_id: reading}


def test_a_refusal_is_kept_under_the_exact_question_that_earned_it() -> None:
    from immich_memories.store.episode_readings import (
        EpisodeReadingIdentity,
        EpisodeReadingStore,
    )

    identity = EpisodeReadingIdentity(
        group_id="unreadable", producer_key="producer-v3", evidence_key="evidence-a"
    )
    store = EpisodeReadingStore(annotation_store())
    store.remember_refusals([(identity, "the answer named no offered asset")])

    assert store.refusals_for((identity,)) == {"unreadable": "the answer named no offered asset"}
    assert store.refusals_for((replace(identity, producer_key="producer-v4"),)) == {}
    assert store.refusals_for((replace(identity, evidence_key="evidence-b"),)) == {}
