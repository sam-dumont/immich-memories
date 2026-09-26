"""Reviewable evidence ledger and exact-ID catalogues."""
import json
from pathlib import Path

from experiment_data import ROOT, save


def records():
    items = {}
    path=ROOT/'data/entity-contexts.json'
    contexts=json.loads(path.read_text()) if path.exists() else {}
    path=ROOT/'data/curation.json'
    curation=json.loads(path.read_text()) if path.exists() else {}
    for directory in ('results','requests'):
        for p in (ROOT/directory).glob('*.json'):
            if p.name.endswith('-plan.json'):
                continue
            row = json.loads(p.read_text())
            if 'key' in row:
                if row['key'] in contexts:row['entity_context']=contexts[row['key']]
                if row['key'] in curation:row['curation']=curation[row['key']]
                items[row['key']] = row
    return sorted(items.values(),key=lambda r:({'strong':0,'possible':1,'unresolved':3,'weak':4}.get(r.get('curation',{}).get('usefulness'),2),r['status']!='reviewable',
                  -len(r.get('accepted',{}).get('years',{})),r.get('anchor','')))


def write_report(reader, library):
    items = records()
    nominations_path = ROOT/'data/nominations.json'
    nominations = json.loads(nominations_path.read_text()) if nominations_path.exists() else []
    model = reader.statistics()
    reviewable = [r for r in items if r['status']=='reviewable']
    lines = ['# Long-term thread prototype', '',
             f"{len(library.rows):,} banked captions. {len(nominations)} first-pass hypotheses; "
             f"{len(items)} deeply checked threads/requests; {len(reviewable)} have at least four accepted dates across three years.", '',
             'These are caption-supported proposals for owner review. Same-pet identity, personal ownership and improvement remain unresolved unless separately established. Counts below describe individually checked samples, not complete retrieval results.', '',
             'No library images, recaptioning or episode readings. Configured E4B and full tier only.', '',
             '| Thread | Status | Checked matches | Dates | Years |',
             '|---|---|---:|---:|---|']
    for r in items:
        j=r.get('judgment') or {};a=r.get('accepted',{})
        title=j.get('title',r.get('anchor',r['key'])).replace('|','/')
        lines.append(f"| {title} | {r['status']} | {a.get('captions',0)} | {a.get('days',0)} | {', '.join(a.get('years',{}))} |")
        if r.get('handoff',{}).get('candidates'):
            name = __import__('hashlib').sha256(r['key'].encode()).hexdigest()[:14]+'.json'
            save(ROOT/'catalogues'/name,r['handoff'])
            r['catalogue_file'] = 'catalogues/'+name
    for r in items:
        j=r.get('judgment') or {}
        lines += ['', '## '+j.get('title',r.get('anchor',r['key'])), '', '**Status:** '+r['status'], '',
                  j.get('supported_scope','No supported scope.'), '',
                  '**Connection:** '+j.get('connection','Not established.'), '',
                  '**Not established:** '+('; '.join(j.get('unsupported_claims',[])) or 'See source decisions.'), '',
                  '**Original brief:** '+r.get('owner_brief','Automatic discovery'), '',
                  f"Unreviewed retrieved sources: {r.get('unreviewed_retrieval_sources','n/a')}", '']
        for s in r.get('sources',[]):
            lines += [f"- **{s['date']} · {s['city']}, {s['country']} · {s['decision']}**", 
                      f"  {s['caption']}",f"  Source: `{s['asset_id']}`. {s['reason']}"]
    save(ROOT/'review-data.json',{'threads':items,'statistics':model,
         'captions':len(library.rows),'nominations':len(nominations),
         'basis':'caption and metadata only; sampled membership checks; owner review pending'})
    p=ROOT/'review.md';p.write_text('\n'.join(lines)+'\n');p.chmod(0o600)
    save(ROOT/'data/model-stats.json',model)
    print(json.dumps({'review':str(p),'threads':len(items),'reviewable':len(reviewable),'model':model}),flush=True)
