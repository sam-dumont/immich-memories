"""Unconstrained owner language is interpreted once, then checked against evidence."""
import hashlib
import re
from collections import defaultdict

from nltk.stem import PorterStemmer
from nltk.corpus import wordnet as wn

from discovery import words
from experiment_data import ROOT, save
from workflow import refine

PLAN = '''Turn the owner's request into a search of their photo library.
The captions were written by a small vision model: plain descriptions of what is
visible. They never contain names of events, trips or parks, so describe what those
look like in pictures instead, using words from caption_vocabulary where they fit.
- queries: 1-8 short phrases; a caption matches a phrase when it has all its words, and
  any phrase may match. Separate subjects are separate phrases. Empty when the request is
  only about a place or a time.
- places: every place the request names (country, city, region or continent), as written.
- people_request: true when the request is about who is in the pictures (us, the kids,
  a named person) rather than what they show.
- since/until: years the request states, else null. exclusions: what the owner wants left out.
Return JSON {"title":short film title,"queries":[phrases],"places":[names],
"people_request":boolean,"since":int or null,"until":int or null,
"interpretation":one sentence,"exclusions":[strings],"unresolved_claims":[strings]}.'''


def retrieve_plan(library, plan):
    """Subject phrases ORed, places from metadata, and the two intersected when both are given."""
    stemmer = PorterStemmer()
    postings = defaultdict(set)
    for term, refs in library.posts.items():
        postings[stemmer.stem(term)].update(refs)
    subject = set()
    # One phrase per query: its words are ANDed, the phrases ORed.
    for phrase in plan['queries']:
        matches = None
        for term in phrase.split():
            term_refs = set()
            for token in words(term):
                variants = {token}
                base = wn.morphy(token, wn.VERB)
                if base:
                    variants.add(base)
                    for sense in wn.synsets(base, pos=wn.VERB)[:1]:
                        for lemma in sense.lemmas():
                            variants.add(lemma.name())
                            variants.update(d.name() for d in lemma.derivationally_related_forms())
                for variant in variants:
                    if '_' not in variant:
                        term_refs |= postings.get(stemmer.stem(variant), set())
            if not words(term):
                continue
            matches = term_refs if matches is None else matches & term_refs
        subject |= matches or set()
    wanted = set(plan['places'])
    place = {i for i, r in enumerate(library.rows)
             if wanted & {r.get('country'), r.get('city'), r.get('region')} - {'', None}}
    if plan['queries'] and plan['places']:
        refs = subject & place
    else:
        refs = subject or place
    return sorted(i for i in refs if (plan['since'] or 1) <= int(library.rows[i]['taken_at'][:4]) <= (plan['until'] or 9999))


MIN_RETRIEVAL = 20
FILLER = set("since until after before about over again ever still just also very really some any every each all our ours we us you your it its they them their this that these those there here when where what which who whom how why want wants wanted like would could should will shall please make made get got bought buy one two".split())
VISIBLE = '''A photo library's captions describe only what is visible. List 6 to 10 short
phrases (one or two words each) for what would be visible in pictures of the activity or
change the owner asks for: the tools, materials, actions and work in progress, not the
ordinary setting around it. Use words from caption_vocabulary. Return JSON {"phrases":[strings]}.'''


COMPANIONS = '''Words that appear unusually often in this library's captions next to the
owner's request. Which of them are visible signs of what the owner asks for (not the
ordinary setting, not something else)? Return JSON {"terms":[terms from the list]}.'''


def companion_terms(reader, library, brief, key, rare=0.05, min_lift=8, specific=0.01):
    """Lift over the captions that use the request's own uncommon words; E4B keeps the signs."""
    n = len(library.rows)
    stem = PorterStemmer().stem
    by_stem = defaultdict(set)
    for term, refs in library.posts.items():
        by_stem[stem(term)] |= refs
    # The request's most specific words: present, uncommon, and within 10x of the rarest.
    counted = {w: len(by_stem.get(stem(w), ())) for w in words(brief) if w not in FILLER}
    usable = {w: c for w, c in counted.items() if 3 <= c <= rare * n}
    if not usable:
        return [], []
    rarest = min(usable.values())
    own = [w for w, c in usable.items() if c <= 10 * rarest]
    seed = set().union(*(by_stem[stem(w)] for w in own))
    counts = defaultdict(int)
    for i in seed:
        for t in library.tokens[i]:
            counts[t] += 1
    said = {stem(w) for w in words(brief)}
    lifted = sorted(((c / len(seed)) / (len(library.posts[t]) / n), t) for t, c in counts.items()
                    if c >= 3 and len(library.posts[t]) <= specific * n and stem(t) not in said)
    candidates = [t for l, t in reversed(lifted) if l >= min_lift][:30]
    if not candidates:
        return own, []

    def valid(a):
        assert set(a['terms']) <= set(candidates)

    answer = reader.ask('companions', key, COMPANIONS,
                        {'owner_brief': brief, 'terms': candidates}, valid, 300)
    return own, (answer or {'terms': []})['terms']


def resolve_places(reader, named, available):
    """A named place is kept when the library records it; anything else (a continent, a
    park) is one short question: which recorded places lie inside it."""
    resolved = []
    for name in named:
        exact = [p for p in available if p.casefold() == name.casefold()]
        if exact:
            resolved += exact
            continue

        def valid(a):
            assert set(a['places']) <= set(available)

        answer = reader.ask('place', name, 'Which of these recorded places are located in, or '
                            'are part of, the named place? Return JSON {"places":[exact names]}.',
                            {'named_place': name, 'recorded_places': available}, valid, 400)
        resolved += (answer or {'places': []})['places']
    return sorted(set(resolved))


def vocabulary(n=200):
    """The words this library's captions actually use, by how many days they recur on."""
    import json
    profiles = json.loads((ROOT/'data/recurrence-index.json').read_text())['profiles']
    picked = [p for p in profiles if p['kind'] in {'noun', 'verb'} and p['status'] == 'recurring']
    return [p['term'] for p in sorted(picked, key=lambda p: -p['days'])[:n]]


def find(reader, library, brief, sample_limit=48):
    """Preserve every character of the request, including late exclusions."""
    if not brief.strip():
        raise ValueError('Write a subject or request first')
    key = 'request:'+hashlib.sha256(brief.encode()).hexdigest()[:18]
    available = sorted({r.get(k,'') for r in library.rows for k in ('country','region')}-{''})
    def validate(plan):
        # A missing title or flag is filled in; only the search itself must be well formed.
        plan['title'] = plan.get('title') or brief.strip()[:60]
        # A year named as an event ("the facade we redid in 2022") is not an end date.
        if plan.get('until') and not re.search(r"\b(until|till|through|up to)\b|\b(to|before) \d{4}|\d{4}\s*-\s*\d{4}", brief, re.I):
            plan['until'] = None
        plan['people_request'] = bool(plan.get('people_request'))
        plan['places'] = [p for p in plan.get('places') or [] if isinstance(p, str) and p.strip()]
        plan['interpretation'] = plan.get('interpretation') or ''
        plan.setdefault('exclusions', []); plan.setdefault('unresolved_claims', [])
        assert type(plan['people_request']) is bool
        assert isinstance(plan['queries'],list) and all(isinstance(q,str) and q.strip()
                    for q in plan['queries'])
        for k in ('since','until'):
            assert plan[k] is None or type(plan[k]) is int and 1<=plan[k]<=9999
        assert (plan['since'] or 1)<=(plan['until'] or 9999)
        assert isinstance(plan['exclusions'],list) and isinstance(plan['unresolved_claims'],list)
    plan = reader.ask('query_plan',key,PLAN,{'owner_brief':brief,'available_places':available,
                      'caption_vocabulary':vocabulary()},validate,1000)
    if plan is None:
        raise ValueError('E4B did not return a valid retrieval plan; the request was not shortened or replaced')
    # A place counts when the sentence names it; otherwise it is the model's guess from
    # the list it was shown (skiing -> Norway).
    plan['named_places'] = [p for p in plan['places'] if p.casefold() in brief.casefold()]
    plan['places'] = resolve_places(reader, plan['named_places'], available)
    if plan['places']:
        # "The desert" resolved to the towns in it: the place now carries that word, so
        # also requiring it in captions would only empty the search.
        named = {w for p in plan['named_places'] for w in words(p)}
        plan['queries'] = [q for q in plan['queries'] if not words(q) <= named]
        # With the place resolved, a subject phrase sharing no word with the sentence is
        # the model's own guess at what the place looks like: it would only narrow it.
        said = {PorterStemmer().stem(w) for w in words(brief)}
        plan['dropped_queries'] = [p for p in plan['queries']
                                   if not {PorterStemmer().stem(w) for w in words(p)} & said]
        plan['queries'] = [p for p in plan['queries'] if p not in plan['dropped_queries']]
    refs = retrieve_plan(library,plan)
    if not plan['people_request']:
        # The owner's words are rarely the captioner's ("renovation" vs "peeling paint,
        # exposed brick"). Let the library say which words travel with the request's own
        # rare words, and have E4B judge only those.
        own, companions = companion_terms(reader, library, brief, key)
        named = {w for p in plan['named_places'] for w in words(p)} if plan['places'] else set()
        own = [w for w in own if w not in named]
        extra = own
        if len(companions) >= 2:
            # One companion word is a room; two together ("peeling paint", "exposed
            # brick") are the work. Their captions join the search as pairs.
            extra = own + [f"{a} {b}" for k, a in enumerate(companions) for b in companions[k + 1:]]
        stem_ = PorterStemmer().stem
        known = {stem_(t) for t in library.posts}
        unseen = [w for w in words(brief) if w not in FILLER and w not in named and stem_(w) not in known]
        if unseen and not companions:
            # The request's key word never appears in this library ("birthday" when the
            # captioner writes "cake with candles"): search for what it looks like instead
            # of the generic words the plan fell back on.
            plan['queries'] = []
        if (len(refs) < MIN_RETRIEVAL or unseen) and not companions and not own:
            seen = set(library.posts)

            def valid_visible(a):
                assert isinstance(a['phrases'], list) and a['phrases']

            visible = reader.ask('visible', key, VISIBLE, {'owner_brief': brief,
                                 'caption_vocabulary': vocabulary(300)}, valid_visible, 400)
            extra = [p for p in (visible or {'phrases': []})['phrases']
                     if isinstance(p, str) and words(p) and words(p) <= seen]
        if extra:
            plan['expanded_queries'] = extra
            plan['queries'] = list(dict.fromkeys(plan['queries'] + extra))
            refs = retrieve_plan(library, plan)
    save(ROOT/'requests'/f'{key[8:]}-plan.json',{'owner_brief':brief,'plan':plan,'retrieval':library.facts(refs)})
    if not refs and plan['people_request']:
        # Who is in a picture is Immich's face data, not a caption: a person film's job.
        result = {'key':key,'owner_brief':brief,'plan':plan,'status':'person_request','sources':[]}
    elif not refs:
        result = {'key':key,'owner_brief':brief,'plan':plan,'status':'no_caption_matches','sources':[]}
    else:
        stem_ = PorterStemmer().stem
        phrases = [{stem_(w) for w in words(p)} for p in plan['queries']]
        stems = {i: {stem_(t) for t in library.tokens[i]} for i in refs}
        strength = lambda i: sum(1 for p in phrases if p and p <= stems[i])
        candidate = {'ranked_refs': sorted(refs, key=lambda i: (-strength(i), library.rows[i]['taken_at'])),
                     'key':key,'anchor':plan['title'],'operator':'owner_request',
                     **library.facts(refs),'context':library.context(refs),
                     'witnesses':library.witnesses(refs,12)}
        result = refine(reader,library,candidate,{'title':plan['title'],'hypothesis':plan['interpretation'],
                        'unresolved_claims':plan['unresolved_claims']},brief,sample_limit)
        result['plan'] = plan
        if result.get('judgment'):
            result['judgment']['title'] = plan['title']
            for c in result.get('handoff',{}).get('candidates',[]):
                c['title'] = plan['title']
    result['owner_brief'] = brief
    save(ROOT/'requests'/f'{key[8:]}.json',result)
    return result
