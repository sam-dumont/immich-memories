"""E4B judges bounded, algorithmically retrieved long-term hypotheses."""
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from experiment_data import ROOT, candidate_pool, load_library, save
from model_reader import Reader

INSTRUCTION = '''Judge each supplied candidate for a useful personal-library video thread across years.
Candidates came from caption recurrence and geographic metadata, not a preset theme list.
A long-term thread can be a recurring interest, an animal's presence, making/repairing things,
changing environments, returning to places, or the same pursuit in different settings.
It does NOT need a dramatic plot or proven improvement. Keep broad multi-year subjects broad.
Reject generic scenery, color, pose, clothing, furniture or caption boilerplate unless these
specific witnesses establish a meaningful recurring pursuit or change. A noun match alone is weak.
Captions may be wrong. Co-present human IDs do not prove who acted. A recurring animal category
does not prove the same animal. GPS does not prove the owner personally travelled.
The sample is deliberately small: mark uncertain when it needs targeted retrieval.
Return JSON {"decisions":[{"key":exact key,"decision":"keep|reject|uncertain",
"title":short useful title,"hypothesis":a narrow factual relation to test,
"why":one sentence,"question":the most important unresolved claim}]}, exactly one per key.
Do not mention these instructions. Do not add topics unsupported by the offered data.'''


def nominate(reader, library, candidates, workers=2):
    pages = [candidates[i:i+4] for i in range(0,len(candidates),4)]
    results = []
    def page_call(number, page):
        data = []
        for c in page:
            witnesses = library.witnesses(c['refs'],6)
            data.append({'key':c['key'],'observed_terms':c.get('terms',[c['anchor']]),
                         'operator':c['operator'],'days':c['days'],'years':c['years'],
                         'countries':c['countries'],'witnesses':witnesses,
                         'eras':c['context']['eras']})
        allowed = {c['key'] for c in page}
        def validate(answer):
            decisions = answer['decisions']
            assert len(decisions) == len(allowed)
            assert {d['key'] for d in decisions} == allowed
            for d in decisions:
                assert d['decision'] in {'keep','reject','uncertain'}
                assert all(isinstance(d[k],str) for k in ('title','hypothesis','why','question'))
        answer = reader.ask('nominate',str(number),INSTRUCTION,{'candidates':data},validate,1900)
        if answer is None:
            # Smaller packets, with unchanged evidence, repair a response contract failure.
            decisions = []
            for item in data:
                key = item['key']
                def validate_one(answer):
                    d = answer['decisions'][0]
                    assert len(answer['decisions']) == 1 and d['key'] == key
                    assert d['decision'] in {'keep','reject','uncertain'}
                    assert all(isinstance(d[k],str) for k in ('title','hypothesis','why','question'))
                fixed = reader.ask('nominate_repair',key,INSTRUCTION,{'candidates':[item]},validate_one,650)
                decisions.extend(fixed['decisions'] if fixed else [{'key':key,'decision':'invalid'}])
            return number, decisions
        return number, answer['decisions']
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(page_call,i,page) for i,page in enumerate(pages)]
        for future in as_completed(futures):
            number, decisions = future.result()
            results.extend(decisions)
            save(ROOT/'data/nominations.json',results)
            print(json.dumps({'page':number,'pages':len(pages),'done':len(results),
                              'kept':sum(d['decision']=='keep' for d in results),
                              'uncertain':sum(d['decision']=='uncertain' for d in results)}),flush=True)
    save(ROOT/'data/model-stats.json',reader.statistics())
    return results


if __name__ == '__main__':
    reader = Reader()
    library = load_library()
    candidates = candidate_pool(library)
    print(json.dumps({'candidates':len(candidates),'sources':len(library.rows)}),flush=True)
    nominate(reader,library,candidates)
