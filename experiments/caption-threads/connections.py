"""Rare-term edges between recurring subjects, checked against actual captions."""
import json
import math
import re
from collections import Counter, defaultdict

from nltk.corpus import wordnet as wn
from nltk.stem import PorterStemmer

from experiment_data import ROOT, load_library, save, semantics
from model_reader import Reader

RELATION = re.compile(r'\b(?:used (?:to|for)|made (?:from|of|with)|grown|growing|produced|ingredient|built|building|repairing|restoring|converted|transformed)\b',re.I)
EXPLICIT = re.compile(r'\b(?:used (?:to|for)|made (?:from|with)|ingredient|converted|transformed)\b',re.I)


def build(library):
    anchors = json.loads((ROOT/'data/all-candidates.json').read_text())
    anchors = [a for a in anchors if a['kind']=='noun' and a['domain'] in
               {'noun.artifact','noun.food','noun.plant','noun.animal','noun.act','noun.substance'}]
    per_ref = defaultdict(list)
    for a in anchors:
        for ref in a['refs']:per_ref[ref].append(a['key'])
    by_key = {a['key']:a for a in anchors}
    stems=defaultdict(set);variants=defaultdict(set);stemmer=PorterStemmer()
    for term,refs in library.posts.items():
        stem=stemmer.stem(term);stems[stem].update(refs);variants[stem].add(term)
    results=[]
    for stem,refs in stems.items():
        days={library.rows[i]['taken_at'][:10] for i in refs}
        if not 1<=len(days)<=40:continue
        terms=variants[stem]
        if not any(wn.synsets(t,wn.NOUN) for t in terms):continue
        touched=defaultdict(set)
        for i in refs:
            for key in per_ref[i]:
                if not words_overlap(terms,by_key[key]['terms'],stemmer):touched[key].add(i)
        if len(touched)<2:continue
        related=sorted(touched,key=lambda k:(-len(touched[k]),by_key[k]['days']))[:8]
        witnesses=sorted(set().union(*(touched[k] for k in related)))
        relational=[i for i in witnesses if RELATION.search(library.rows[i]['caption'])]
        direct=[i for i in witnesses if EXPLICIT.search(library.rows[i]['caption'])]
        years={d[:4] for d in days}
        domains={by_key[k]['domain'] for k in related}
        score=(math.log1p(len(years))*math.log1p(len(days))*(1+len(domains))
               +8*len({library.rows[i]['taken_at'][:10] for i in relational}))
        results.append({'connector':sorted(terms,key=lambda t:(len(t),t))[0],
                        'variants':sorted(terms),'witness_refs':witnesses,
                        'related_anchors':[{'key':k,'anchor':by_key[k]['anchor'],'days':by_key[k]['days'],
                         'years':list(by_key[k]['years']),'refs':sorted(touched[k])} for k in related],
                        'relational_refs':relational,'days':len(days),'years':sorted(years),
                        'direct_relation_refs':direct,
                        'explicit_score':len({library.rows[i]['taken_at'][:10] for i in direct})/math.sqrt(len(days)),
                        'score':round(score,3)})
    results.sort(key=lambda r:(not(r['direct_relation_refs'] and len(r['years'])>=2),
                              -r['explicit_score'],-r['score']))
    save(ROOT/'data/connection-candidates.json',results)
    return results,by_key


def words_overlap(left,right,stemmer):
    return bool({stemmer.stem(t) for t in left}&{stemmer.stem(t) for t in right})


INSTRUCTION='''Test whether the rare connector links two recurring subjects in this library.
Require a meaningful explicit relation: ingredient to product, tools to making/repairing,
life stages, or a documented change. Mere co-occurrence, shared color, objects in a room,
and a container next to its contents are weak; reject them. Broad conceptual knowledge alone
is insufficient. Cite the supplied captions which establish the actual relation.
Different dated examples may connect a subject across contexts without proving causality.
Do not claim the owner grew, made, owns or used something unless a caption establishes it.
Return JSON {"decision":"supported|hypothesis|reject","title":short title,
"claim":one factual sentence,"relation":one sentence,"personal_link":"unknown|explicit",
"evidence_refs":[refs],"limitations":[strings]} using only offered refs.'''


def judge(reader,library,limit=32):
    candidates,anchors=build(library)
    results=[]
    for n,c in enumerate(candidates[:limit]):
        first=list(dict.fromkeys(c['direct_relation_refs'][:4]+c['relational_refs'][:2]+[s['ref'] for s in library.witnesses(c['witness_refs'],8)]))[:10]
        expansions=[]
        for a in c['related_anchors'][:4]:
            expansions.extend(s['ref'] for s in library.witnesses(set(anchors[a['key']]['refs'])-set(first),3))
        offered=list(dict.fromkeys(first+expansions))
        def validate(answer):
            assert answer['decision'] in {'supported','hypothesis','reject'}
            assert answer['personal_link'] in {'unknown','explicit'}
            assert all(isinstance(answer[k],str) for k in ('title','claim','relation'))
            assert isinstance(answer['limitations'],list)
            assert all(type(i) is int and i in offered for i in answer['evidence_refs'])
            if answer['decision']=='supported':assert answer['evidence_refs']
        data={'connector':c['connector'],'related_subjects':[{k:v for k,v in a.items() if k!='refs'} for a in c['related_anchors']],
              'link_witnesses':[library.source(i) for i in first],
              'independent_context':[library.source(i) for i in expansions]}
        answer=reader.ask('connection',c['connector'],INSTRUCTION,data,validate,950)
        record={'connector':c['connector'],'candidate':c,'answer':answer,
                'witnesses':[library.source(i) for i in (answer or {}).get('evidence_refs',[])],
                'offered_refs':offered}
        results.append(record);save(ROOT/'data/connections.json',results)
        print(json.dumps({'connection':c['connector'],'done':n+1,'decision':(answer or {}).get('decision','invalid')}),flush=True)
    return results


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--index-only',action='store_true');parser.add_argument('--limit',type=int,default=32)
    args=parser.parse_args();reader=Reader();library=load_library()
    if args.index_only:
        rows,_=build(library)
        print([(r['connector'],r['score'],r['days'],[a['anchor'] for a in r['related_anchors']]) for r in rows[:45]])
    else:judge(reader,library,args.limit)
