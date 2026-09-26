"""Unconstrained owner language is interpreted once, then checked against evidence."""
import hashlib
from collections import defaultdict

from nltk.stem import PorterStemmer
from nltk.corpus import wordnet as wn

from discovery import words
from experiment_data import ROOT, save
from workflow import refine

PLAN = '''Translate the full owner request into a broad caption/metadata retrieval plan.
Keep positive subject searches separate from exclusions. Each query is a list of words that
must occur together; queries are ORed. Include simple caption synonyms and related life stages
when needed. Do not require incidental props, clothing, particular terrain, or locations unless
the owner explicitly requires them. Queries must target the positive subject, not the exclusions.
Set retrieval_basis=caption_subject when there is a named pursuit, object, animal or other subject.
Words such as "across years" or "in different places" do not remove that subject restriction.
Set retrieval_basis=geographic_history only when geographic movement, journeys or returning to
destinations is itself the subject, even when captions lack travel words. Geographic contrast
then retrieves recorded locations. Only set countries from the supplied available list and only when explicitly requested.
For geographic_history use an EMPTY queries list: geography supplies the sources. Any nonempty
queries remain mandatory positive subject constraints, regardless of the retrieval_basis flag.
Year bounds are inclusive. Use null for unstated bounds. Do not invent a year range.
Return JSON {"title":short title,"queries":[[words]],"countries":[exact country names],
"geographic_contrast":boolean,"retrieval_basis":"caption_subject|geographic_history",
"since":integer or null,"until":integer or null,
"interpretation":one sentence,"exclusions":[strings],"unresolved_claims":[strings]}.
This is retrieval only. The complete original request, not this summary, will judge source membership.'''


def retrieve_plan(library, plan):
    """Union recall-oriented positive queries; leave nuanced exclusions to judgment."""
    stemmer = PorterStemmer()
    postings = defaultdict(set)
    for term, refs in library.posts.items():
        postings[stemmer.stem(term)].update(refs)
    refs = set()
    for group in plan['queries']:
        matches = None
        for term in group:
            term_refs = set()
            for token in words(term):
                variants = {token}
                base = wn.morphy(token,wn.VERB)
                if base:
                    variants.add(base)
                    senses=wn.synsets(base,pos=wn.VERB)[:1]
                    for sense in senses:
                        for lemma in sense.lemmas():
                            variants.add(lemma.name())
                            variants.update(d.name() for d in lemma.derivationally_related_forms())
                for variant in variants:
                    if '_' not in variant:
                        term_refs |= postings.get(stemmer.stem(variant),set())
            matches = term_refs if matches is None else matches & term_refs
        refs |= matches or set()
    # A model flag can never erase positive subject constraints. Contradictory
    # plans retain the narrower caption query; metadata remains attached context.
    if not plan['queries'] and plan['retrieval_basis']=='geographic_history' and plan['geographic_contrast']:
        for c in library.geographic_candidates():
            if c['operator']=='geographic_variation': refs.update(c['refs'])
    if plan['countries']:
        country_refs = {i for i,r in enumerate(library.rows) if r.get('country') in plan['countries']}
        refs = refs & country_refs if plan['queries'] or plan['geographic_contrast'] else country_refs
    return sorted(i for i in refs if (plan['since'] or 1)<=int(library.rows[i]['taken_at'][:4])<=(plan['until'] or 9999))


def find(reader, library, brief, sample_limit=48):
    """Preserve every character of the request, including late exclusions."""
    if not brief.strip():
        raise ValueError('Write a subject or request first')
    key = 'request:'+hashlib.sha256(brief.encode()).hexdigest()[:18]
    available = sorted({r.get('country','') for r in library.rows}-{''})
    def validate(plan):
        assert isinstance(plan['title'],str) and isinstance(plan['interpretation'],str)
        assert type(plan['geographic_contrast']) is bool
        assert plan['retrieval_basis'] in {'caption_subject','geographic_history'}
        assert isinstance(plan['queries'],list) and all(isinstance(q,list) and q and
                    all(isinstance(t,str) and t.strip() for t in q) for q in plan['queries'])
        assert isinstance(plan['countries'],list) and set(plan['countries'])<=set(available)
        for k in ('since','until'):
            assert plan[k] is None or type(plan[k]) is int and 1<=plan[k]<=9999
        assert (plan['since'] or 1)<=(plan['until'] or 9999)
        assert isinstance(plan['exclusions'],list) and isinstance(plan['unresolved_claims'],list)
    plan = reader.ask('query_plan',key,PLAN,{'owner_brief':brief,'available_countries':available},validate,1000)
    if plan is None:
        raise ValueError('E4B did not return a valid retrieval plan; the request was not shortened or replaced')
    refs = retrieve_plan(library,plan)
    save(ROOT/'requests'/f'{key[8:]}-plan.json',{'owner_brief':brief,'plan':plan,'retrieval':library.facts(refs)})
    if not refs:
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
