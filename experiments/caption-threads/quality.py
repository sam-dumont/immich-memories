"""Separate source validity from whether a thread is worth offering."""
import hashlib
import json
import re
from collections import Counter

from experiment_data import ROOT, RECURRENCES, save
from handoff import build_handoff
from report import records
from workflow import validate_partition

AUDIT = '''Recheck this ONE source against the complete owner_brief. The retrieval audit found
a possible mistake. Treat the flags as questions, not as facts. Judge the original caption.
A vaguely compatible setting is not evidence of a named activity. A picture of an animal,
text, toy or illustration does not establish a live animal. An unusual descriptor or garbled
quantity can make a caption ambiguous. Return unknown when the requested fact is not established.
Do not impose incidental clothing, props or location requirements. Explicit requested activity
is sufficient even without the usual equipment. Identity/ownership/progress cannot be borrowed
from other sources. Return JSON {"decisions":[{"ref":integer,
"decision":"match|reject|unknown","reason":one short evidence-based reason}]}.
There is exactly one source; return its exact ref.'''


def source_audit(reader, library, limit_per_thread=6):
    index=json.loads(RECURRENCES.read_text())
    rare={}
    for p in index['profiles']+index['single_date_terms']:
        if p['kind']=='phrase' and p.get('days',1)<=2:
            for i in p['source_refs']:rare.setdefault(i,[]).append(p['key'].split(':',1)[1])
    summaries=[]
    for record in records():
        if not record.get('source_decisions'):continue
        if record.get('membership_audit',{}).get('revision')=='caption-source-audit-v1':continue
        sources={s['ref']:s for s in record['sources']}
        anchor=record.get('anchor','').casefold()
        counters=set((record.get('judgment') or {}).get('counter_refs',[]))
        flagged=[]
        for d in record['source_decisions']:
            s=sources[d['ref']];flags=[]
            if d['decision']=='match' and d['ref'] in counters:flags.append('The hypothesis check cited this source as a counterexample.')
            if d['decision']=='match' and re.search(r'\b(?:toy|statue|cartoon|drawing|illustration|poster|screenshot|screen|text reads)\b',s['caption'],re.I):
                flags.append('The caption may describe a representation or text, not the requested real subject.')
            if d['decision']=='match' and re.search(r'\b(?:suggest|suggesting|consistent with|imply|likely)\b',d['reason'],re.I):
                flags.append('The first reason relied on compatibility or suggestion. Is the requested content actually established?')
            unusual=[p for p in rare.get(d['ref'],[]) if p.endswith(' '+anchor)]
            if d['decision']=='match' and unusual:
                flags.append('Unusual subject description seen on at most two capture days: '+', '.join(unusual[:3]))
            if flags:flagged.append((d['ref'],flags))
        checks=[]
        for ref,flags in sorted(flagged,key=lambda item:-len(item[1]))[:limit_per_thread]:
            answer=reader.ask('source_audit',record['key']+':'+str(ref),AUDIT,
                {'owner_brief':record['owner_brief'],'retrieval_questions':flags,'source':library.source(ref)},
                lambda a:validate_partition(a,[ref]),420)
            d=answer['decisions'][0] if answer else {'ref':ref,'decision':'unknown','reason':'Targeted check returned no valid decision'}
            previous=next(old.copy() for old in record['source_decisions'] if old['ref']==ref)
            checks.append({'ref':ref,'flags':flags,'before':previous,'after':d})
            for old in record['source_decisions']:
                if old['ref']==ref:old.update(d)
            sources[ref].update(d)
        if not checks:continue
        record['membership_audit']={'revision':'caption-source-audit-v1','checks':checks,'flagged':len(flagged),'deferred':max(0,len(flagged)-limit_per_thread)}
        record['sources']=list(sources.values())
        accepted=library.facts(d['ref'] for d in record['source_decisions'] if d['decision']=='match')
        record['accepted']={k:v for k,v in accepted.items() if k!='refs'}
        record['status']='reviewable' if accepted['days']>=4 and len(accepted['years'])>=3 else 'thin_lead'
        record['handoff']=build_handoff(library,record['key'],record['judgment']['title'],record['owner_brief'],
                            record['judgment']['supported_scope'],{d['ref']:d['decision'] for d in record['source_decisions']}).model_dump(mode='json')
        path=ROOT/'requests'/f"{record['key'][8:]}.json" if record['key'].startswith('request:') else ROOT/'results'/f"{hashlib.sha256(record['key'].encode()).hexdigest()[:14]}.json"
        save(path,record)
        summary={'key':record['key'],'checked':len(checks),'changed':sum(x['before']['decision']!=x['after']['decision'] for x in checks)}
        summaries.append(summary);print(json.dumps({'source_audit':summary}),flush=True)
    save(ROOT/'data/source-audit.json',summaries)
    return summaries


CURATE = '''Compare these caption-checked proposals as possible personal memory videos.
Source matching has already been checked. Now judge USEFULNESS, not just whether words recur.
Choose at most TWO strong proposals in this group; all can be weak. Do not reward a large count
of a pose, color, incidental object, physical shape or generic scenery. Such recurrence is weak
unless these captions establish a specific pursuit, deliberate practice or actual transformation.
A coherent recurring activity, live-animal presence, making/repairing, work, or travel can be useful
without a dramatic plot or proven improvement. Broad geographic history is valid across varied
subjects. Uncertain individual pet identity must be labeled; it does not erase the broad animal thread.
Do not infer a hobby merely from one tool, nor a personal condition from medical text/diagrams.
Return JSON {"decisions":[{"key":exact key,"usefulness":"strong|possible|weak",
"why":short concrete reason,"identity_or_progress_gap":short limitation or empty string}]}.
Return exactly one decision per key. No more than two strong; do not invent stories.'''


def curate(reader, library):
    items=[r for r in records() if r['status']=='reviewable' and not r['key'].startswith('request:')]
    # Interleave the chronology-ordered catalogue so adjacent noun/action variants
    # do not receive isolated, uncompetitive approval pages.
    items=items[::2]+items[1::2]
    results={}
    for offset in range(0,len(items),6):
        page=items[offset:offset+6];allowed={r['key'] for r in page}
        data=[]
        for r in page:
            refs=[d['ref'] for d in r['source_decisions'] if d['decision']=='match']
            data.append({'key':r['key'],'title':r['judgment']['title'],
                         'scope':r['owner_brief'],'connection':r['judgment']['connection'],
                         'counts':r['accepted'],'witnesses':library.witnesses(refs,5)})
        def validate(answer):
            ds=answer['decisions'];assert len(ds)==len(allowed) and {d['key'] for d in ds}==allowed
            assert sum(d['usefulness']=='strong' for d in ds)<=2
            for d in ds:
                assert d['usefulness'] in {'strong','possible','weak'}
                assert isinstance(d['why'],str) and isinstance(d['identity_or_progress_gap'],str)
        answer=reader.ask('curate',str(offset),CURATE,{'proposals':data},validate,1400)
        if answer:
            results.update({d['key']:d for d in answer['decisions']})
        else:
            results.update({r['key']:{'key':r['key'],'usefulness':'unresolved','why':'No valid comparative judgment'} for r in page})
        save(ROOT/'data/curation.json',results)
        print(json.dumps({'curation':offset,'total':len(items)}),flush=True)
    return results


if __name__=='__main__':
    from experiment_data import load_library
    from model_reader import Reader
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['sources','curate']);args=parser.parse_args()
    reader=Reader();library=load_library()
    source_audit(reader,library) if args.stage=='sources' else curate(reader,library)
