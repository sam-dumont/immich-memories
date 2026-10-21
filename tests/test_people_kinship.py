"""The relationships a family tree already implies, suggested and never assumed (#2795).

Every person here is invented.
"""

from __future__ import annotations

from immich_memories.people.kinship import Fact, Hop, suggest_relationships


def _kinds(facts, declined=()):
    return {(s.source, s.kind, s.target) for s in suggest_relationships(facts, declined)}


def _one(facts, source, kind, target):
    return next(
        s
        for s in suggest_relationships(facts)
        if (s.source, s.kind, s.target) == (source, kind, target)
    )


# Gran is Bob's and Alex's parent; Bob is Riley's parent, Alex is Sky's; Bob's partner is Jo.
TREE = (
    Fact("gran", "parent-of", "bob"),
    Fact("alex", "child-of", "gran"),
    Fact("bob", "father-of", "riley"),
    Fact("sky", "daughter-of", "alex"),
    Fact("bob", "partner-of", "jo"),
)


class TestTheRules:
    def test_two_children_of_one_parent_are_suggested_as_siblings_both_ways(self):
        found = _kinds(TREE)

        assert ("bob", "sibling-of", "alex") in found
        assert ("alex", "sibling-of", "bob") in found

    def test_a_parent_of_a_parent_is_a_grandparent_and_the_reverse_a_grandchild(self):
        found = _kinds(TREE)

        assert ("gran", "grandparent-of", "riley") in found
        assert ("riley", "grandchild-of", "gran") in found

    def test_a_siblings_child_is_a_niece_or_nephew(self):
        found = _kinds(TREE)

        assert ("alex", "aunt-or-uncle-of", "riley") in found
        assert ("riley", "nibling-of", "alex") in found

    def test_children_of_siblings_are_cousins(self):
        found = _kinds(TREE)

        assert ("riley", "cousin-of", "sky") in found
        assert ("sky", "cousin-of", "riley") in found

    def test_a_partners_parent_is_a_parent_in_law(self):
        found = _kinds(TREE)

        assert ("gran", "parent-in-law-of", "jo") in found
        assert ("jo", "child-in-law-of", "gran") in found

    def test_a_partners_sibling_and_a_siblings_partner_are_siblings_in_law(self):
        found = _kinds(TREE)

        assert ("jo", "sibling-in-law-of", "alex") in found
        assert ("alex", "sibling-in-law-of", "jo") in found

    def test_married_partners_count_for_in_laws_as_well(self):
        facts = (Fact("gran", "mother-of", "bob"), Fact("jo", "spouse-of", "bob"))

        assert ("jo", "child-in-law-of", "gran") in _kinds(facts)

    def test_an_explicit_sibling_counts_for_the_chain_without_a_shared_parent(self):
        facts = (Fact("bob", "brother-of", "alex"), Fact("alex", "parent-of", "sky"))

        assert ("bob", "aunt-or-uncle-of", "sky") in _kinds(facts)


class TestTheReason:
    def test_each_suggestion_names_the_chain_it_follows(self):
        cousin = _one(TREE, "riley", "cousin-of", "sky")

        assert cousin.hops == (Hop("child", "bob"), Hop("sibling", "alex"), Hop("parent", "sky"))
        assert cousin.reverse_kind == "cousin-of"

    def test_the_reverse_is_the_vocabularys_reciprocal(self):
        assert _one(TREE, "gran", "grandparent-of", "riley").reverse_kind == "grandchild-of"


class TestWhatIsNeverSuggested:
    def test_a_relationship_already_recorded_is_not_suggested_again(self):
        facts = (*TREE, Fact("gran", "grandparent-of", "riley"))

        assert ("gran", "grandparent-of", "riley") not in _kinds(facts)

    def test_one_recorded_from_the_other_side_counts_too(self):
        facts = (*TREE, Fact("riley", "grandchild-of", "gran"))

        found = _kinds(facts)
        assert ("gran", "grandparent-of", "riley") not in found
        assert ("riley", "grandchild-of", "gran") not in found

    def test_a_more_specific_kind_already_answers_the_general_one(self):
        facts = (*TREE, Fact("alex", "aunt-of", "riley"))

        found = _kinds(facts)
        assert ("alex", "aunt-or-uncle-of", "riley") not in found
        assert ("riley", "nibling-of", "alex") not in found

    def test_a_pair_with_a_closer_tie_gets_no_derived_one(self):
        # Jo is also recorded as Alex's partner: no sibling-in-law on top of it.
        facts = (*TREE, Fact("jo", "partner-of", "alex"))

        assert ("jo", "sibling-in-law-of", "alex") not in _kinds(facts)

    def test_a_declined_suggestion_stays_declined_from_either_side(self):
        declined = (Fact("sky", "cousin-of", "riley"),)

        found = _kinds(TREE, declined)
        assert ("sky", "cousin-of", "riley") not in found
        assert ("riley", "cousin-of", "sky") not in found
        assert ("riley", "grandchild-of", "gran") in found

    def test_a_pair_somebody_said_is_not_related_gets_nothing(self):
        declined = (Fact("riley", "tight-dyad", "sky"),)

        assert ("riley", "cousin-of", "sky") not in _kinds(TREE, declined)

    def test_nobody_is_suggested_a_relationship_with_themselves(self):
        assert all(s.source != s.target for s in suggest_relationships(TREE))

    def test_no_facts_no_suggestions(self):
        assert suggest_relationships(()) == []
