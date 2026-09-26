"""Data-derived appearance + recurring-place hypotheses; never an animal identity ID."""
import hashlib
import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from experiment_data import ROOT, RECURRENCES, load_library, save
from model_reader import Reader
from workflow import refine


def candidates(library,limit=6):
    contexts=json.loads((ROOT/'data/entity-contexts.json').read_text())
    profiles=json.loads(RECURRENCES.read_text())['profiles']
    by_phrase={p['term']:p for p in profiles if p['kind']=='phrase'}
    out=[]
    for entity,context in contexts.items():
        for pattern in context['patterns'][:2]:
            p=by_phrase[pattern['pattern']]
            places=pattern['places'][:2]
            pairs={(place['country'],place['region']) for place in places}
            refs=[i for i in p['source_refs'] if (library.rows[i]['country'],library.rows[i]['region']) in pairs]
            facts=library.facts(refs)
            if facts['days']<8 or len(facts['years'])<4:continue
            label=', '.join(place['region'] or place['country'] for place in places)
            key='continuity:'+hashlib.sha256((entity+p['key']+label).encode()).hexdigest()[:16]
            out.append({'key':key,'anchor':p['term'],'entity':entity,'operator':'appearance_continuity',
                        'place_labels':label,'domain':'noun.animal','terms':p['variants'],
                        **facts,'context':library.context(refs),'witnesses':library.witnesses(refs,12)})
    out.sort(key=lambda c:(-c['days'],-len(c['years'])))
    save(ROOT/'data/continuity-candidates.json',out)
    return out[:limit]


def run(reader,library,limit=6):
    offers=candidates(library,limit)
    results=[]
    with ThreadPoolExecutor(max_workers=2) as pool:
        tasks=[pool.submit(refine,reader,library,c,
            {'hypothesis':f"Recurring descriptions of {c['anchor']} around {c['place_labels']} may form an appearance-continuity series.",
             'alternative':'Multiple different animals can share an appearance and locations. Look for simultaneous animals or conflicting descriptions.'},
             sample_limit=28) for c in offers]
        for task in as_completed(tasks):
            r=task.result();results.append(r)
            print(json.dumps({'continuity':r['anchor'],'status':r['status'],'accepted':r.get('accepted')}),flush=True)
    return results


if __name__=='__main__':
    reader=Reader();run(reader,load_library())
