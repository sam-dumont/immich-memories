"""Hypothesize, challenge, then admit exact sources."""
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from experiment_data import ROOT, save
from handoff import build_handoff

JUDGE = '''Challenge this proposed long-term thread using the original caption witnesses.
Decide what is actually supported, without inventing ownership, causality, identity or improvement.
The owner_brief gives the authoritative scope. Do not narrow it to a shared pose, outfit, terrain,
or props. For geographic threads, different subjects and everyday situations are EXPECTED;
the connection is recorded places across years. Do not require one activity or kind of scenery.
The first-pass hypothesis is untrusted and often overenthusiastic. Actively test an alternative:
the same word may label unrelated objects, a picture of an object, or incidental background.
A long-term pursuit can repeat without improvement. Geographic recurrence can support a series
of visits if the captions show real scenes; country metadata alone does not prove travel.
For artifacts, clothes and scenery require a repeated human pursuit or documented concrete change;
mere object presence, colors, incidental furnishings, and symbolic depictions are not useful threads.
For animals distinguish live animals from statues/toys/signs. Different cats can form a broad cat
thread, but never infer the same pet or ownership from coat color, location, or co-present humans.
For progression require explicit comparable quantities or supported stages, never photo frequency.
Caption quantities can be garbled. Unknown identity or progression does not invalidate a broader
recurring pursuit; narrow the factual claim without narrowing the source scope to incidental props.
Return JSON {"decision":"keep|lead|reject","title":short title,
"supported_scope":one factual sentence,"connection":how years/settings/stages relate,
"unsupported_claims":[strings],"identity":"unknown|not_applicable",
"progression":"unknown|documented_stages","evidence_refs":[integer refs],
"counter_refs":[integer refs],"why":one sentence}.
Use only offered refs. A keep needs at least two relevant witnesses from different years.
If owner_brief is present, honor it in full; do not replace it with the hypothesis or a new brief.'''

MEMBERSHIP = '''Classify EACH offered source independently against the full owner_brief.
Use the source's own caption and metadata, never another source's action or identity.
The proposed scope is explanatory; it cannot impose extra requirements such as a particular
outfit, prop or place absent from the owner_brief. Follow explicit exclusions.
Literal words may be background, toys, statues, signs, screenshots, or another meaning.
Choose match only when the source itself supports the requested content. Choose reject for
clear nonmembers; unknown for missing evidence, uncertain identity, ownership or progression.
For broad recurring subjects, identity or measurable improvement need not be proven unless requested.
Do not reject an explicit activity just because incidental gear differs.
Return JSON {"decisions":[{"ref":integer,"decision":"match|reject|unknown","reason":short factual reason}]}.
Return exactly one decision for every offered ref, and no other refs.'''


def validate_partition(answer, refs):
    decisions = answer['decisions']
    if len(decisions) != len(refs) or {d['ref'] for d in decisions} != set(refs):
        raise ValueError('Missing, duplicate or invented source decision')
    for d in decisions:
        if type(d['ref']) is not int or d['decision'] not in {'match','reject','unknown'}:
            raise ValueError('Invalid source decision')
        if not isinstance(d['reason'],str):
            raise ValueError('Missing source reason')


def choose_sources(reader, library, key, brief, refs):
    """Small independent membership packets; invalid output never admits a source."""
    decisions = []
    for offset in range(0,len(refs),8):
        part = refs[offset:offset+8]
        data = {'owner_brief':brief,
                'sources':[library.source(i) for i in part]}
        answer = reader.ask('membership',f'{key}:{offset}',MEMBERSHIP,data,
                            lambda a:validate_partition(a,part),1100)
        if answer is None:
            for ref in part:
                single = data | {'sources':[library.source(ref)]}
                fixed = reader.ask('membership_repair',f'{key}:{ref}',MEMBERSHIP,single,
                                   lambda a:validate_partition(a,[ref]),260)
                decisions.extend(fixed['decisions'] if fixed else
                                 [{'ref':ref,'decision':'unknown','reason':'Invalid model response'}])
        else:
            decisions.extend(answer['decisions'])
    return decisions


def discovery_brief(candidate):
    """Define the retrieval operator's broad scope before any model description."""
    operator=candidate['operator']
    if operator=='geographic_variation':
        subject='Scenes across the recorded countries and years, with different subjects and different settings. Geographic variation is the connection; it needs no single activity.'
    elif operator=='returning_geography':
        subject=f"Scenes recorded in {candidate['anchor']} across years, including everyday situations and different settings. The recurring place is the connection."
    elif operator=='appearance_continuity':
        subject=f"A possible appearance-continuity series: live animals described as '{candidate['anchor']}' around the recurring recorded places {candidate['place_labels']}, across years. Select the described appearance and recorded contexts, not every animal of the species. Multiple animals can share these attributes; same-individual identity is unresolved. Exclude depictions and toys."
    elif candidate.get('domain')=='noun.animal':
        subject=f"Live {candidate['anchor']} across the years and settings. Exclude toys, statues, drawings and symbolic depictions. Different individuals may belong to this broad subject."
    elif candidate.get('kind')=='verb':
        subject=f"Actual instances of the activity '{candidate['anchor']}' across years and settings. Observed word forms: {', '.join(candidate.get('terms',[]))}. Exclude incidental background and other meanings of the word."
    elif candidate.get('domain')=='noun.artifact':
        subject=f"Repeated human use, making, repairing or other participation involving {candidate['anchor']} across years. Mere incidental object presence is insufficient."
    else:
        subject=f"The observed subject '{candidate['anchor']}' as a central recurring subject across years and settings. Incidental background matches are insufficient."
    return subject+' Do not infer personal ownership, the same individual animal, causation, or improved performance. Do not require incidental clothing, equipment, terrain or mood.'


def challenge_refs(library, candidate, initial, limit=12):
    unseen = set(candidate.get('retrieval_refs',candidate['refs'])) - set(initial)
    # Spread across still-unseen years and places, then add literal measurements
    # wherever observed. Numerical-looking captions remain unvalidated evidence.
    initial_tokens = set().union(*(library.tokens[i] for i in initial)) if initial else set()
    ranked = sorted(unseen, key=lambda i: -sum(
        math.log1p(len(library.rows)/len(library.posts[t])) for t in library.tokens[i]-initial_tokens))
    novel = ranked[:max(30,len(ranked)//3)]
    measurements = [i for i in unseen if re.search(r'\b\d+(?:[.,]\d+)?\s*(?:km|miles?|minutes?|bpm|kcal)\b',library.rows[i]['caption'],re.I)]
    witnesses = library.witnesses(novel,limit-3 if measurements else limit)
    refs = [s['ref'] for s in witnesses]
    if measurements:
        refs.extend(s['ref'] for s in library.witnesses(measurements,3))
    return list(dict.fromkeys(refs))


def refine(reader, library, candidate, nomination, brief=None, sample_limit=40):
    key = candidate['key']
    owner_brief = brief or discovery_brief(candidate)
    first = [w['ref'] for w in candidate['witnesses']]
    challenge = challenge_refs(library,candidate,first)
    offered = list(dict.fromkeys(first+challenge))
    def validate(answer):
        assert answer['decision'] in {'keep','lead','reject'}
        assert answer['identity'] in {'unknown','not_applicable'}
        assert answer['progression'] in {'unknown','documented_stages'}
        for field in ('evidence_refs','counter_refs'):
            assert isinstance(answer[field],list)
            assert all(type(i) is int and i in offered for i in answer[field])
        assert isinstance(answer['unsupported_claims'],list)
        assert all(isinstance(answer[k],str) for k in ('title','supported_scope','connection','why'))
        if answer['decision']=='keep':
            assert len({library.rows[i]['taken_at'][:4] for i in answer['evidence_refs']})>=2
    data = {'owner_brief':owner_brief,'hypothesis':nomination,'operator':candidate['operator'],
            'retrieval_counts':{k:candidate[k] for k in ('days','years','countries')},
            'context':candidate['context'],
            'initial_witnesses':[library.source(i) for i in first],
            'targeted_challenge':[library.source(i) for i in challenge]}
    judgment = reader.ask('challenge',key,JUDGE,data,validate,1200)
    if judgment is None:
        judgment = reader.ask('challenge_repair',key,JUDGE+' Keep the JSON short and complete.',data,validate,1500)
    record = {'key':key,'anchor':candidate['anchor'],'operator':candidate['operator'],
              'nomination':nomination,'judgment':judgment,'context':candidate['context'],
              'retrieval':{k:candidate[k] for k in ('captions','days','years','countries','span')},
              'initial_refs':first,'challenge_refs':challenge,'source_decisions':[],
              'sources':[],'status':'invalid' if judgment is None else judgment['decision']}
    if judgment is None or judgment['decision']=='reject':
        save(ROOT/'results'/f'{hashlib.sha256(key.encode()).hexdigest()[:14]}.json',record)
        return record
    # Original user text is authoritative. Discovery uses an explicit broad scope,
    # not a first-pass imaginative claim such as ownership or skill improvement.
    if candidate['operator']=='geographic_variation':
        judgment['title']='Places across the years'
    elif candidate['operator']=='returning_geography':
        judgment['title']=candidate['anchor']+' across the years'
    all_refs = candidate.get('retrieval_refs',candidate['refs'])
    selected = [s['ref'] for s in library.witnesses(all_refs,sample_limit)]
    # Include the evidence cited by the judge and important challenges within the budget.
    selected = list(dict.fromkeys(judgment['evidence_refs']+challenge+selected))[:sample_limit]
    decisions = choose_sources(reader,library,key,owner_brief,selected)
    admitted = [d['ref'] for d in decisions if d['decision']=='match']
    accepted_facts = library.facts(admitted)
    record.update({'owner_brief':owner_brief,'source_decisions':decisions,
                   'sources':[library.source(d['ref'])|{'decision':d['decision'],'reason':d['reason']} for d in decisions],
                   'accepted':{k:v for k,v in accepted_facts.items() if k!='refs'},
                   'unreviewed_retrieval_sources':len(set(all_refs)-set(selected)),
                   'status':'reviewable' if accepted_facts['days']>=4 and len(accepted_facts['years'])>=3 else 'thin_lead'})
    result = build_handoff(library,key,judgment['title'],owner_brief,judgment['supported_scope'],
                           {d['ref']:d['decision'] for d in decisions})
    record['handoff'] = result.model_dump(mode='json')
    save(ROOT/'results'/f'{hashlib.sha256(key.encode()).hexdigest()[:14]}.json',record)
    return record


def run_refinement(reader, library, candidates, nominations, limit=80, workers=2):
    decisions = {d['key']:d for d in nominations}
    eligible = [c for c in candidates if decisions.get(c['key'],{}).get('decision') in {'keep','uncertain'}
                or c['operator'] in {'geographic_variation','returning_geography'}]
    groups = defaultdict(list)
    for c in eligible:
        domain = c.get('domain','geography')
        groups[domain].append(c)
    # Interleave domains; within each use both prevalent and distinctive subjects.
    for domain,group in groups.items():
        if domain in {'noun.animal','geography'}:
            group.sort(key=lambda c:-c['days'])
    order = sorted(groups)
    allocations = {'geography':4,'noun.animal':4,'verb.motion':16,'verb.creation':24,
                   'noun.act':8,'noun.artifact':8,'noun.plant':4,'noun.food':4}
    selected = [c for domain,count in allocations.items() for c in groups[domain][:count]]
    for round_no in range(max(map(len,groups.values()),default=0)):
        for domain in order:
            # Broad context-only grammatical families already had a nomination;
            # spend deep reads on concrete subjects and actions first.
            if domain in {'noun.attribute','noun.body','noun.Tops','noun.shape','noun.state','noun.quantity',
                          'noun.relation','noun.time','noun.possession','unclassified','verb.stative'}:
                continue
            if round_no<len(groups[domain]) and groups[domain][round_no] not in selected:
                selected.append(groups[domain][round_no])
    selected = selected[:limit]
    save(ROOT/'data/refinement-coverage.json',{'selected':[c['key'] for c in selected],
         'deferred':[c['key'] for c in eligible if c not in selected]})
    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(refine,reader,library,c,decisions[c['key']]) for c in selected]
        for future in as_completed(futures):
            r = future.result();results.append(r)
            save(ROOT/'data/threads.json',results)
            print(json.dumps({'stage':'refinement','done':len(results),'total':len(selected),
                              'anchor':r['anchor'],'status':r['status'],
                              'accepted':r.get('accepted',{}).get('captions',0)}),flush=True)
    save(ROOT/'data/model-stats.json',reader.statistics())
    return results
