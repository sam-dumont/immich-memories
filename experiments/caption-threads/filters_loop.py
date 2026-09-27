"""Gemma revises its own filters after seeing what they found (owner 09-27).

Gemma translates; code only runs the filters and shows the result back: how many photos per
year, the phrases the captions use around the subject, a sample over time. Gemma then drops
phrases that are not the ask and proposes words that would find more of it. Code keeps a
proposed word only if captions really use it (grounding), reruns, and stops when Gemma changes
nothing. No rule here knows what any request means.
"""

import re
from collections import Counter

from nltk.stem import PorterStemmer

from discovery import GLUE, words
from query import retrieve_plan

ROUNDS = 3
POOL_TARGET = 600  # a film's pool, not a library: past it, Gemma is told to narrow
STEM = PorterStemmer()
ARTICLES = {"a", "an", "the", "some", "two", "three", "several", "his", "her", "their", "its"}


def _schema(**props):
    return {"type": "object", "additionalProperties": False, "properties": props, "required": list(props)}


def _tokens(caption):
    return re.findall(r"[a-z]+", (caption or "").lower())


def phrases(library, pool, heads, shown):
    """What the captions call the subject: the words just before each subject word ('toy car',
    'race car'), plus the pool's most over-represented words. Counted once per caption."""
    # Deterministic order: a set's order changes per process, which changed the prompt, missed
    # the call cache and let Gemma answer afresh (birth pool 535 one run, 10372 the next; 09-28).
    around, found = Counter(), Counter()
    for i in sorted(pool):
        toks = _tokens(library.rows[i]["caption"])
        seen = set()
        for k, t in enumerate(toks):
            if t not in heads:
                continue
            for n in (1, 2):
                gram = [w for w in toks[max(0, k - n):k] if w not in ARTICLES]
                if gram and not set(gram) <= GLUE:
                    seen.add(" ".join(gram + [t]))
            after = toks[k + 1:k + 2]
            if after and after[0] not in GLUE:
                seen.add(f"{t} {after[0]}")  # "car seat", "cat tree"
        around.update(seen)
        found.update(library.tokens[i])
    total = len(library.tokens)
    lift = {w: c / len(pool) / (len(library.posts.get(w, ())) / total or 1)
            for w, c in found.items() if c >= 3 and w not in heads}
    rare = sorted(lift, key=lambda w: (-lift[w], w))[:15]
    candidates = [p for p, c in sorted(around.items(), key=lambda x: (-x[1], x[0]))[:40] if c >= 2] + rare
    return [p for p in dict.fromkeys(candidates) if p not in shown][:40], around


REVISE = '''The owner asked for a film (owner_request). Your filters found the photos summarised below.
Captions are short and written by a small model.
- terms: the search terms you used, each with how many photos it found and examples.
- phrases: phrases the found captions use, with a count and an example.
When too_many is given, the pool is too large for one film: narrow it by dropping broad terms,
keeping only the specific terms, excluding phrases. Answer: keep_terms (the search terms that find what the owner asked for; every term not listed is
dropped, so leave it empty to keep them all), exclude (phrases naming something that is NOT what the owner asked for; every photo whose
caption has one is removed, so keep anything that could be it), add (other words or short
phrases captions would use for what the owner asked for). Reason first. Return JSON.'''

COULD_BE = '''The owner asked for a film (owner_request). For each numbered group of photos below
(described by example captions), answer "yes" if any of them could be what the owner asked for,
"no" if none of them could. Return JSON with one answer per group, in order.'''

CONFIRM = '''The owner asked for a film (owner_request). Each proposed phrase below would add the photos
whose captions contain it: how many, and examples. Keep a phrase only if most of what it adds is
what the owner asked for. Reason first. Return JSON.'''


def contains(caption, phrase):
    return re.search(r"\b" + re.escape(phrase.lower()) + r"s?\b", (caption or "").lower()) is not None


def _examples(library, refs, n=2):
    refs = sorted(refs, key=lambda i: library.rows[i]["taken_at"])
    return " | ".join(library.rows[i]["caption"][:80] for i in refs[:: max(1, len(refs) // n)][:n])


def revise(reader, key, brief, library, terms, within, protected):
    """terms: the search phrases; within: where they may find photos (dates, place, people, an
    OCR event); protected: refs no caption decides (OCR anchors, caption-less pictures).
    Returns (pool, log)."""
    def hits_of(t):
        return set(retrieve_plan(library, {"queries": [t], "places": [], "since": None, "until": None})) & within

    hits = {t: hits_of(t) for t in dict.fromkeys(terms)}
    excluded, shown, log = set(), set(), []
    dates = {"from": "0000", "to": "9999"}

    def current():
        found = set().union(*hits.values()) if hits else set()
        return {i for i in found if dates["from"] <= library.rows[i]["taken_at"][:10] <= dates["to"]
                and not any(contains(library.rows[i]["caption"], p) for p in excluded)} | protected

    for rnd in range(ROUNDS):
        pool = current()
        heads = {w for t in hits for w in words(t)}
        offered, counts = phrases(library, pool - protected, heads, shown)
        shown |= set(offered)
        term_list = [t for t in hits if hits[t]]
        ordered = sorted(pool - protected, key=lambda i: library.rows[i]["taken_at"])
        listed = [f'{p} ({counts.get(p) or sum(contains(library.rows[i]["caption"], p) for i in ordered)}): '
                  f'"{_examples(library, [i for i in ordered if contains(library.rows[i]["caption"], p)], 1)}"'
                  for p in offered]
        schema = _schema(reason={"type": "string", "maxLength": 300},
                         keep_terms={"type": "array", "items": {"type": "string", "enum": term_list or [""]},
                                     "maxItems": max(1, len(term_list))},
                         exclude={"type": "array", "items": {"type": "string", "enum": offered or [""]}, "maxItems": 20},
                         add={"type": "array", "items": {"type": "string", "maxLength": 40}, "maxItems": 8})
        per_year = Counter(library.rows[i]["taken_at"][:4] for i in pool)
        span = {library.rows[i]["taken_at"][:4] for i in pool}
        per_month = (dict(sorted(Counter(library.rows[i]["taken_at"][:7] for i in pool).items()))
                     if 0 < len(span) <= 3 else None)
        facts = {"too_many": f"{len(pool)} photos; a film's pool is at most about {POOL_TARGET}"} if len(pool) > POOL_TARGET else {}
        if per_month:
            facts["per_month"] = per_month
        answer = reader.ask("revise_filters", f"{key}:r{rnd}", REVISE, facts | {
            "owner_request": brief, "photos": len(pool), "per_year": dict(sorted(per_year.items())),
            "terms": [f"{t}: {len(hits[t])} photos, e.g. {_examples(library, hits[t])}" for t in term_list],
            "phrases": listed}, lambda a: None, 1600, schema=schema) or {}
        # The request's own words stay a filter: Gemma works around "cars", never drops it.
        own = {STEM.stem(w) for w in words(brief)}
        # Choosing the few that fit is easier for a 4B model than listing the many that do not.
        keep = set(answer.get("keep_terms") or []) & set(term_list)
        dropped = [t for t in (set(term_list) - keep if keep else []) if t in hits
                   and not {STEM.stem(w) for w in words(t)} <= own]
        excludes = [p for p in answer.get("exclude") or [] if p in offered]
        # Recheck: every removal is shown by what it would really take out, before it applies.
        # A term left out of keep_terms is a choice among terms: "could any of these be it?" is
        # always yes for a broad term, so only excluded phrases get the recheck.
        removals = {}
        for p in excludes:
            removals[f"phrase '{p}'"] = (p, {i for i in pool - protected if contains(library.rows[i]["caption"], p)})
        removals = {k: v for k, v in removals.items() if v[1]}
        if removals:
            # Asked neutrally, not "confirm your removal": the proposer agreed with itself every time.
            keys, confirmed = list(removals), set()
            for start in range(0, len(keys), 6):  # a long answer array loses its alignment at 4B
                part = keys[start:start + 6]
                check = reader.ask("could_be", f"{key}:x{rnd}:{start}", COULD_BE, {
                    "owner_request": brief,
                    "groups": [f'{n + 1}. photos whose caption says "{removals[k][0]}" ({len(removals[k][1])} photos), '
                               f"e.g. {_examples(library, removals[k][1], 3)}" for n, k in enumerate(part)]},
                    lambda a: None, 20 + 4 * len(part), schema=_schema(
                        answers={"type": "array", "items": {"type": "string", "enum": ["yes", "no"]},
                                 "minItems": len(part), "maxItems": len(part)})) or {}
                confirmed |= {removals[k][0] for k, v in zip(part, check.get("answers") or []) if v == "no"}
        else:
            confirmed = set()
        excludes = [p for p in excludes if p in confirmed]
        for t in dropped:
            hits.pop(t)
        excluded |= set(excludes)
        # No date revision: asked for a period, Gemma invented one (the birth moved to 2025-08,
        # the cars to 2019-2024; 09-27). Dates come only from the grounded first filter step.
        moved = {}
        # Grounding: a proposed phrase counts only by what it really adds, shown back before it joins.
        before = current()
        def fresh(refs):
            return {i for i in refs - before if not any(contains(library.rows[i]["caption"], x) for x in excluded)}

        gains = {p: fresh(h) for p in answer.get("add") or [] if p not in hits
                 for h in [hits_of(p)] if fresh(h)}
        accepted = []
        if gains:
            options = list(gains)
            confirm = reader.ask("confirm_adds", f"{key}:c{rnd}", CONFIRM, {
                "owner_request": brief,
                "proposed": [f"{p}: adds {len(h)} photos, e.g. {_examples(library, h, 3)}" for p, h in gains.items()]},
                lambda a: None, 400, schema=_schema(
                    reason={"type": "string", "maxLength": 300},
                    keep={"type": "array", "items": {"type": "string", "enum": options}, "maxItems": len(options)})) or {}
            accepted = [p for p in confirm.get("keep") or [] if p in gains]
            for p in accepted:
                hits[p] = hits_of(p)
        after = current()
        log.append({"round": rnd + 1, "reason": answer.get("reason", "")[:300], "dropped_terms": dropped,
                    "excluded": excludes, "proposed_add": {p: len(h) for p, h in gains.items()},
                    "added": accepted, "dates": moved, "pool_before": len(pool), "pool": len(after)})
        if not dropped and not excludes and not accepted and not moved:
            break
    return current(), log
