"""Expose appearance/place continuity without pretending it is animal identity."""
import json

from experiment_data import ROOT, RECURRENCES, load_library, save


def build(library):
    index=json.loads(RECURRENCES.read_text())
    candidates=json.loads((ROOT/'data/candidates.json').read_text())
    result={}
    for c in candidates:
        if c.get('domain')!='noun.animal':continue
        terms=set(c['terms'])|{c['anchor']}
        patterns=[]
        for p in index['profiles']:
            if p['kind']!='phrase' or p['key'].split()[-1] not in terms:
                continue
            if p['days']<4 or len(p['years'])<3:continue
            refs=set(p['source_refs'])&set(c.get('retrieval_refs',c['refs']))
            facts=library.facts(refs)
            if facts['days']<4 or len(facts['years'])<3:continue
            patterns.append({'pattern':p['term'],**{k:v for k,v in facts.items() if k!='refs'},
                             'places':library.context(refs)['places'][:3],
                             'examples':library.witnesses(refs,4)})
        patterns.sort(key=lambda p:(-p['days'],-len(p['years'])))
        result[c['key']]={'status':'appearance and place recurrence; individual identity unverified',
                          'patterns':patterns[:10],
                          'places':c['context']['places'],
                          'warning':'Patterns can overlap and can contain different animals. Matching appearance, place or human co-presence is not an identity ID.'}
    save(ROOT/'data/entity-contexts.json',result)
    return result


if __name__=='__main__':
    data=build(load_library())
    print(json.dumps({k:[(p['pattern'],p['days'],list(p['years'])) for p in v['patterns'][:4]] for k,v in data.items()},ensure_ascii=False))
