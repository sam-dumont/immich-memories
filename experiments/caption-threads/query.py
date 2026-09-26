"""Unconstrained owner language is interpreted once, then checked against evidence."""
import hashlib
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
        # With the place resolved, a subject phrase sharing no word with the sentence is
        # the model's own guess at what the place looks like: it would only narrow it.
        said = {PorterStemmer().stem(w) for w in words(brief)}
        plan['dropped_queries'] = [p for p in plan['queries']
                                   if not {PorterStemmer().stem(w) for w in words(p)} & said]
        plan['queries'] = [p for p in plan['queries'] if p not in plan['dropped_queries']]
    refs = retrieve_plan(library,plan)
    save(ROOT/'requests'/f'{key[8:]}-plan.json',{'owner_brief':brief,'plan':plan,'retrieval':library.facts(refs)})
    if not refs and plan['people_request']:
        # Who is in a picture is Immich's face data, not a caption: a person film's job.
        result = {'key':key,'owner_brief':brief,'plan':plan,'status':'person_request','sources':[]}
    elif not refs:
        result = {'key':key,'owner_brief':brief,'plan':plan,'status':'no_caption_matches','sources':[]}
    else:
        candidate = {'key':key,'anchor':plan['title'],'operator':'owner_request',
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
