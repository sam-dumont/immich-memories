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


class TestChainedRules:
    """What the tree implies once its own implications count: siblings, parents, chains."""

    def test_a_parents_partner_is_suggested_as_the_other_parent(self):
        found = _kinds(TREE)

        assert ("jo", "parent-of", "riley") in found
        assert ("riley", "child-of", "jo") in found
        assert _one(TREE, "jo", "parent-of", "riley").hops == (
            Hop("partner", "bob"),
            Hop("parent", "riley"),
        )

    def test_a_siblings_parent_is_suggested_as_a_parent(self):
        facts = (Fact("bob", "sibling-of", "alex"), Fact("gran", "mother-of", "bob"))

        found = _kinds(facts)
        assert ("alex", "child-of", "gran") in found
        assert ("gran", "parent-of", "alex") in found

    def test_a_siblings_sibling_is_a_sibling(self):
        facts = (Fact("ann", "sister-of", "bob"), Fact("bob", "brother-of", "cid"))

        found = _kinds(facts)
        assert ("ann", "sibling-of", "cid") in found
        assert ("cid", "sibling-of", "ann") in found

    def test_a_chain_of_implications_reaches_the_grandchild(self):
        # Gran is only recorded as Ann's parent; Cid is only Bob's sibling, Bob only Ann's.
        facts = (
            Fact("gran", "parent-of", "ann"),
            Fact("ann", "sibling-of", "bob"),
            Fact("bob", "sibling-of", "cid"),
            Fact("cid", "parent-of", "kid"),
        )

        found = _kinds(facts)
        assert ("gran", "grandparent-of", "kid") in found
        assert ("kid", "grandchild-of", "gran") in found
        assert ("ann", "aunt-or-uncle-of", "kid") in found

    def test_a_partners_siblings_child_is_a_niece_or_nephew_by_marriage(self):
        found = _kinds(TREE)

        assert ("jo", "aunt-or-uncle-of", "sky") in found
        assert ("sky", "nibling-of", "jo") in found

    def test_cousins_follow_chained_siblings_and_parents(self):
        facts = (
            Fact("bob", "sibling-of", "alex"),
            Fact("bob", "partner-of", "jo"),
            Fact("jo", "parent-of", "riley"),
            Fact("alex", "parent-of", "sky"),
        )

        # Bob is Riley's parent only through Jo; Riley and Sky are cousins through that.
        assert ("riley", "cousin-of", "sky") in _kinds(facts)

    def test_a_declined_link_is_not_used_further_down_the_chain(self):
        facts = (*TREE, Fact("nan", "parent-of", "jo"))
        declined = (Fact("riley", "child-of", "jo"),)

        assert ("nan", "grandparent-of", "riley") in _kinds(facts)
        found = _kinds(facts, declined)
        assert ("jo", "parent-of", "riley") not in found
        assert ("nan", "grandparent-of", "riley") not in found

    def test_a_declined_sibling_breaks_the_cousins_it_would_make(self):
        declined = (Fact("alex", "sibling-of", "bob"),)

        found = _kinds(TREE, declined)
        assert ("bob", "sibling-of", "alex") not in found
        assert ("riley", "cousin-of", "sky") not in found
        assert ("riley", "grandchild-of", "gran") in found

    def test_a_derived_tie_never_contradicts_a_recorded_one(self):
        # Jo is recorded as Riley's sibling: no parent suggestion through Bob on top.
        facts = (*TREE, Fact("jo", "sibling-of", "riley"))

        assert ("jo", "parent-of", "riley") not in _kinds(facts)

    def test_a_contradictory_tree_still_ends(self):
        facts = (
            Fact("a", "parent-of", "b"),
            Fact("b", "parent-of", "a"),
            Fact("a", "sibling-of", "c"),
            Fact("c", "sibling-of", "b"),
            Fact("b", "partner-of", "c"),
        )

        assert all(s.source != s.target for s in suggest_relationships(facts))


class TestTheReason:
    def test_each_suggestion_names_the_chain_it_follows(self):
        cousin = _one(TREE, "riley", "cousin-of", "sky")

        # Bob and Alex are siblings only through Gran, so the chain goes through her.
        assert cousin.hops == (
            Hop("child", "bob"),
            Hop("child", "gran"),
            Hop("parent", "alex"),
            Hop("parent", "sky"),
        )
        assert cousin.reverse_kind == "cousin-of"

    def test_a_recorded_sibling_is_one_step_of_the_chain(self):
        facts = (
            Fact("bob", "father-of", "riley"),
            Fact("bob", "brother-of", "alex"),
            Fact("alex", "parent-of", "sky"),
        )

        cousin = _one(facts, "riley", "cousin-of", "sky")
        assert cousin.hops == (Hop("child", "bob"), Hop("sibling", "alex"), Hop("parent", "sky"))

    def test_the_shortest_chain_is_the_one_shown(self):
        # Alex is Bob's sibling twice over: recorded, and through Gran.
        facts = (*TREE, Fact("alex", "sibling-of", "bob"))

        cousin = _one(facts, "riley", "cousin-of", "sky")
        assert cousin.hops == (Hop("child", "bob"), Hop("sibling", "alex"), Hop("parent", "sky"))

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
