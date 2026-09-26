"""Distinguish a pictured cross-context connection from a captioned general fact."""
import json

from experiment_data import ROOT, load_library, save
from model_reader import Reader

PROMPT='''Recheck the proposed connection as a connection BETWEEN PICTURED SUBJECTS in this library.
A general fact printed on a label, diagram or sign alone is not a personal-library thread.
The input_candidates and outcome_candidates are distinct source groups. Input_refs MUST come
from input_candidates, and outcome_refs MUST come from outcome_candidates. Input candidates
must depict the connector itself: a pictured plant/material, not a label mentioning it or a
diagram about it. A map or anatomical model does not prove a pictured journey, injury or treatment.
Do not select a generic definition as the pictured input. If neither group establishes its role,
return fact_only. The connection can remain a useful research lead without being a pictured thread.
Look for concrete pictured inputs/materials/life stages in one context AND concrete outcomes,
making/usage or later stages in another. The connector may establish the relation between them.
Use the supplied independent action witnesses to test the interpretation. Do not borrow an action
from another source. Both endpoints must be represented; background co-occurrence is insufficient.
Keep the factual claim modest: the library may show a plant and beer without proving the plant was
grown by the owner, used in that beer, or photographed earlier. This is a possible thread, not causality.
Return JSON {"decision":"cross_context|fact_only|reject","title":short title,
"claim":one caption-grounded sentence,"input_refs":[refs],"outcome_refs":[refs],
"relation_refs":[refs],"unknowns":[strings]}.
Use offered refs only. cross_context requires at least one input and one outcome from different
capture dates. Reject purported personal health/work/identity claims derived only from diagrams or labels.'''


def validate_sides(answer, inputs, outcomes, offered, dates):
    """The model cannot move a general relation fact into an endpoint slot."""
    if answer['decision'] not in {'cross_context','fact_only','reject'}:
        raise ValueError('Unknown connection verdict')
    for field,allowed in [('input_refs',inputs),('outcome_refs',outcomes),('relation_refs',offered)]:
        refs=answer[field]
        if not isinstance(refs,list) or any(type(i) is not int or i not in allowed for i in refs):
            raise ValueError('Connection source used outside its offered role')
    if answer['decision']=='cross_context':
        if not answer['input_refs'] or not answer['outcome_refs']:
            raise ValueError('Both pictured endpoints are required')
        if not any(dates[i]!=dates[j] for i in answer['input_refs'] for j in answer['outcome_refs']):
            raise ValueError('Connection has no evidence across dates')
    if not all(isinstance(answer[k],str) for k in ('title','claim')) or not isinstance(answer['unknowns'],list):
        raise ValueError('Invalid connection description')


def recheck(reader,library):
    path=ROOT/'data/connections.json'
    links=json.loads(path.read_text())
    anchors=json.loads((ROOT/'data/all-candidates.json').read_text())
    by_key={a['key']:a for a in anchors}
    action_sets=[(a,set(a['refs'])) for a in anchors if a['kind']=='verb' and a['domain'] in {'verb.creation','verb.change','verb.contact'}]
    for c in links:
        if (c.get('answer') or {}).get('decision')!='supported':continue
        noun_refs=set().union(*(set(by_key[a['key']]['refs']) for a in c['candidate']['related_anchors'][:4]))
        actions=[]
        for a,refs in action_sets:
            overlap=refs&noun_refs
            if overlap:
                actions.append((len(overlap)/len(refs),a,overlap))
        actions.sort(key=lambda x:-x[0])
        extra=[]
        for _,a,overlap in actions[:6]:
            extra.extend(s['ref'] for s in library.witnesses(overlap,2))
        first=[s['ref'] for s in library.witnesses(c['candidate']['witness_refs'],12)]
        offered=list(dict.fromkeys(first+extra))
        relation_refs=set(c['candidate']['direct_relation_refs'])|set(c['answer']['evidence_refs'])
        inputs=set(first)-relation_refs
        outcomes=set(first)&relation_refs
        dates={i:library.rows[i]['taken_at'][:10] for i in offered}
        def validate(a):
            validate_sides(a,inputs,outcomes,set(offered),dates)
        data={'proposal':c['answer'],'connector':c['connector'],
              'input_candidates':[library.source(i) for i in sorted(inputs)],
              'outcome_candidates':[library.source(i) for i in sorted(outcomes)],
              'independent_action_witnesses':[library.source(i) for i in extra]}
        answer=reader.ask('connection_recheck',c['connector'],PROMPT,data,validate,1000)
        if answer is None:
            answer=reader.ask('connection_role_repair',c['connector'],PROMPT+' If roles are not supported, return fact_only with empty endpoint lists.',data,validate,1000)
        c['crosscheck']=answer
        c['crosscheck_offered_refs']=offered
        c['crosscheck_witnesses']=[library.source(i) for i in dict.fromkeys(
            (answer or {}).get('input_refs',[])+(answer or {}).get('outcome_refs',[])+(answer or {}).get('relation_refs',[]))]
        save(path,links)
        print(json.dumps({'crosscheck':c['connector'],'decision':(answer or {}).get('decision','invalid')}),flush=True)
    return links


if __name__=='__main__':
    reader=Reader();recheck(reader,load_library())
