"""The companion editor's model: what the page shows and what it writes back.

Every person here is invented. The registry this mirrors holds the names of a
real household, which is why no fixture in this repo — or in any issue or PR —
resembles one.
"""

from __future__ import annotations

from immich_memories.db import Store, open_store
from immich_memories.people.companion import load_document, people_entries
from immich_memories.people.editor import curation_flags, load_people, save_person
from tests.people_registry_seed import seed_people


def _registry(*entries: str) -> Store:
    return seed_people("version: 1\npeople:\n" + "".join(entries))


def _entry(
    name: str,
    person_id: str,
    *,
    tier: str = "recurring",
    count: int = 100,
    links: str = "[]",
    confirmed: str = "{role: null, links: [], notes: null}",
    birth_date: str = "null",
    counts_reliable: str = "true",
) -> str:
    return (
        f"  - ids: [{person_id}]\n"
        f"    name: {name}\n"
        f"    birth_date: {birth_date}\n"
        f"    inferred:\n"
        f"      tier: {tier}\n"
        f"      counts_reliable: {counts_reliable}\n"
        f"      evidence: {{count: {count}, active_months: 12, first_month: '2019-01',"
        f" last_month: '2021-06', span_years: 2.4, onset: '2019-03',"
        f" concentration: 8.3, continuity: 0.4}}\n"
        f"      links: {links}\n"
        f"    confirmed: {confirmed}\n"
    )


class TestTheRoster:
    def test_it_reads_the_inner_circle_first_and_the_busiest_of_each_tier_above(self):
        store = _registry(
            _entry("Quiet Neighbour", "id-quiet", tier="event", count=300),
            _entry("Sam Sample", "id-sam", tier="recurring", count=90),
            _entry("Robin Placeholder", "id-robin", tier="recurring", count=410),
            _entry("Alex Example", "id-alex", tier="inner", count=120),
        )

        assert [person.name for person in load_people(store)] == [
            "Alex Example",
            "Robin Placeholder",
            "Sam Sample",
            "Quiet Neighbour",
        ]

    def test_a_person_carries_the_evidence_the_scan_read_them_from(self):
        store = _registry(_entry("Alex Example", "id-alex", count=412))

        person = load_people(store)[0]

        assert person.count == 412
        assert "412 pictures" in person.evidence
        assert "12 months" in person.evidence
        assert "2019-03" in person.evidence

    def test_an_empty_registry_is_an_empty_roster_rather_than_a_crash(self):
        assert load_people(open_store()) == []


class TestConfirmingARole:
    def test_a_confirmed_role_persists_through_a_rescan_that_disagrees(self):
        from datetime import date, datetime

        from immich_memories.people.companion import save_graph
        from immich_memories.people.graph import Owner, PeopleGraph, PersonNode
        from immich_memories.people.signatures import PersonEvidence, Tier

        store = open_store()
        node = PersonNode(
            evidence=PersonEvidence("id-alex", "Alex Example", 120, (date(2019, 1, 1),)),
            tier=Tier.EPISODIC,
        )
        save_graph(store, PeopleGraph((node,), Owner(None, "Someone", "told"), datetime.now()))

        person = load_people(store)[0]
        person.role = "partner"
        save_person(store, person)

        # WHY not a mock: the rescan is the real writer, on a real store. That
        # the two write paths agree is the whole contract under test.
        save_graph(
            store,
            PeopleGraph(
                (PersonNode(evidence=node.evidence, tier=Tier.EVENT),),
                Owner(None, "Someone", "told"),
                datetime.now(),
            ),
        )

        assert load_people(store)[0].role == "partner"
        assert load_people(store)[0].tier == "event"

    def test_a_role_typed_by_hand_is_kept_as_typed(self):
        store = _registry(_entry("Alex Example", "id-alex"))

        person = load_people(store)[0]
        person.role = "  godmother  "
        save_person(store, person)

        assert load_people(store)[0].role == "godmother"

    def test_clearing_a_role_puts_the_field_back_to_empty(self):
        store = _registry(_entry("Alex Example", "id-alex", confirmed="{role: friend}"))

        person = load_people(store)[0]
        person.role = ""
        save_person(store, person)

        assert load_people(store)[0].role is None


class TestDecidingOnALink:
    def test_rejecting_an_inferred_link_is_recorded_as_a_rejection(self):
        store = _registry(
            _entry(
                "Alex Example",
                "id-alex",
                links="[{kind: tight-dyad, with: id-robin, confidence: 0.51, via: co-occurrence}]",
            ),
            _entry("Robin Placeholder", "id-robin"),
        )

        person = load_people(store)[0]
        person.links[0].decision = "rejected"
        save_person(store, person)

        written = people_entries(load_document(store))[0]["confirmed"]["links"]
        assert written == [{"kind": "tight-dyad", "with": "id-robin", "decision": "rejected"}]
        assert load_people(store)[0].links[0].decision == "rejected"

    def test_an_undecided_link_writes_nothing_into_the_confirmed_block(self):
        store = _registry(
            _entry(
                "Alex Example",
                "id-alex",
                links="[{kind: twin, with: id-robin, confidence: 0.9, via: birth-date}]",
            ),
        )

        person = load_people(store)[0]
        save_person(store, person)

        assert people_entries(load_document(store))[0]["confirmed"]["links"] == []

    def test_a_link_names_the_person_on_its_other_end(self):
        store = _registry(
            _entry(
                "Alex Example",
                "id-alex",
                links="[{kind: twin, with: id-robin, confidence: 0.9, via: birth-date}]",
            ),
            _entry("Robin Placeholder", "id-robin"),
        )

        assert load_people(store)[0].links[0].target_name == "Robin Placeholder"

    def test_a_link_confirmed_by_hand_is_not_dropped_by_the_editor(self):
        # The file is hand-editable and documents this shape. An editor that
        # only knew about links the scan inferred would delete it on save.
        store = _registry(
            _entry(
                "Alex Example",
                "id-alex",
                confirmed="{role: null, links: [{kind: couple, with: id-robin}], notes: null}",
            ),
        )

        person = load_people(store)[0]
        person.role = "partner"
        save_person(store, person)

        written = people_entries(load_document(store))[0]["confirmed"]["links"]
        assert written == [{"kind": "couple", "with": "id-robin", "decision": "confirmed"}]

    def test_two_relationships_to_the_same_person_remain_distinct(self):
        store = _registry(
            _entry(
                "Alex Example",
                "id-alex",
                confirmed=(
                    "{role: null, links: [{kind: sibling-of, with: id-robin}, "
                    "{kind: twin-of, with: id-robin}], notes: null}"
                ),
            ),
            _entry("Robin Placeholder", "id-robin"),
        )

        links = load_people(store)[0].links

        assert [(link.kind, link.target_name) for link in links] == [
            ("sibling-of", "Robin Placeholder"),
            ("twin-of", "Robin Placeholder"),
        ]


class TestNotes:
    def test_a_note_survives_the_round_trip(self):
        store = _registry(_entry("Alex Example", "id-alex"))

        person = load_people(store)[0]
        person.notes = "met at the running club"
        save_person(store, person)

        assert load_people(store)[0].notes == "met at the running club"


class TestCurationFlags:
    def test_twins_are_flagged_once_for_the_pair_with_their_counts_disowned(self):
        store = _registry(
            _entry(
                "Robin Placeholder",
                "id-robin",
                counts_reliable="false",
                links="[{kind: twin, with: id-remy, confidence: 0.9, via: birth-date}]",
            ),
            _entry(
                "Remy Placeholder",
                "id-remy",
                counts_reliable="false",
                links="[{kind: twin, with: id-robin, confidence: 0.9, via: birth-date}]",
            ),
        )

        flags = curation_flags(load_people(store))

        assert len(flags) == 1
        assert flags[0].kind == "twin"
        assert set(flags[0].names) == {"Robin Placeholder", "Remy Placeholder"}

    def test_one_name_on_two_records_is_flagged_as_a_merge_for_immich(self):
        store = _registry(
            _entry(
                "Alex Example",
                "id-alex",
                links="[{kind: duplicate, with: id-alex-2, confidence: 0.6, via: name}]",
            ),
            _entry(
                "Alex Example",
                "id-alex-2",
                links="[{kind: duplicate, with: id-alex, confidence: 0.6, via: name}]",
            ),
        )

        flags = curation_flags(load_people(store))

        assert [flag.kind for flag in flags] == ["duplicate"]
        assert "Immich" in flags[0].message

    def test_each_flagged_name_is_paired_with_that_persons_own_record(self):
        # The page turns these into one "open in Immich" link each. Sorting the
        # ids for the dedup key and reading them back as if they matched the
        # names would send somebody to the wrong person's record.
        store = _registry(
            _entry(
                "Zoe Placeholder",
                "id-aaa",
                links="[{kind: twin, with: id-zzz, confidence: 0.9, via: birth-date}]",
            ),
            _entry(
                "Alex Placeholder",
                "id-zzz",
                links="[{kind: twin, with: id-aaa, confidence: 0.9, via: birth-date}]",
            ),
        )

        flag = curation_flags(load_people(store))[0]

        assert dict(zip(flag.names, flag.person_ids, strict=True)) == {
            "Zoe Placeholder": "id-aaa",
            "Alex Placeholder": "id-zzz",
        }

    def test_saying_they_are_not_twins_stops_the_page_asking(self):
        # Two people can share a surname and a birthday without being twins.
        # A flag you have already answered is nagging, not curation.
        store = _registry(
            _entry(
                "Robin Placeholder",
                "id-robin",
                links="[{kind: twin, with: id-remy, confidence: 0.9, via: birth-date}]",
            ),
            _entry(
                "Remy Placeholder",
                "id-remy",
                links="[{kind: twin, with: id-robin, confidence: 0.9, via: birth-date}]",
            ),
        )
        robin = load_people(store)[0]
        robin.links[0].decision = "rejected"
        save_person(store, robin)

        assert curation_flags(load_people(store)) == []

    def test_a_tidy_roster_raises_no_flags(self):
        store = _registry(_entry("Alex Example", "id-alex"))

        assert curation_flags(load_people(store)) == []
