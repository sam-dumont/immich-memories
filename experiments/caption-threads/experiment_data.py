"""Reuse the frozen bank and build data-derived semantic recurrence candidates."""
import hashlib
import json
import math
import sqlite3
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
from statistics import median

import nltk
from nltk.corpus import wordnet as wn

from immich_memories.security import write_secret_file
from discovery import Library

import os
# Per-library data lives outside the repo; THREADS_ROOT names it.
ROOT = Path(os.environ.get('THREADS_ROOT', Path(__file__).resolve().parent))
SNAPSHOT = Path('/private/tmp/immich-whole-library-20260926')
RECURRENCES = ROOT/'data/recurrence-index.json'
nltk.data.path.insert(0,str(ROOT/'data/nltk_data'))
nltk.data.path.append('/private/tmp/immich-theme-investigation/nltk_data')


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    write_secret_file(path, json.dumps(value, ensure_ascii=False, indent=2))


def load_library():
    """Freeze only captions and metadata; never read media or episode tables."""
    path = ROOT / 'data/corpus.json'
    if path.exists():
        library=Library(json.loads(path.read_text()))
        frozen=json.loads((ROOT/'data/snapshot.json').read_text())
        library.total_assets=frozen.get('total_assets',len(library.rows))
        return library
    rows = json.loads((SNAPSHOT / 'corpus.json').read_text())
    wanted = {r['asset_id'] for r in rows}
    with sqlite3.connect((Path.home()/'.immich-memories/cache/annotations.sqlite').as_uri()+'?mode=ro', uri=True) as db:
        assets = {key: (date, city or '', country or '', lat, lon)
                  for key, date, city, country, lat, lon in db.execute(
                      'SELECT asset_id,taken_at,city,country,latitude,longitude FROM assets') if key in wanted}
        people = defaultdict(set)
        for key, person in db.execute("SELECT asset_id,person_id FROM asset_people WHERE person_id IS NOT NULL AND person_id!=''"):
            if key in wanted:
                people[key].add('P'+hashlib.sha256(person.encode()).hexdigest()[:10])
    assert len(assets) == len(rows)
    city_coords = defaultdict(list)
    city_days = defaultdict(set)
    for date, city, country, lat, lon in assets.values():
        if city and country:
            city_days[country, city].add(date[:10])
            if lat is not None and lon is not None:
                city_coords[country, city].append((lat, lon))
    centers = {key: (median(p[0] for p in ps), median(p[1] for p in ps)) for key, ps in city_coords.items()}
    # Alias nearby city labels to a frequent regional representative. Raw city is retained.
    representatives = []
    aliases = {}
    for key in sorted(city_days, key=lambda k: -len(city_days[k])):
        target = None
        if key in centers:
            lat, lon = centers[key]
            for other in representatives:
                if key[0] != other[0] or other not in centers:
                    continue
                lat2, lon2 = centers[other]
                km = math.hypot((lat-lat2)*111.2, (lon-lon2)*111.2*math.cos(math.radians((lat+lat2)/2)))
                if km <= 10:
                    target = other
                    break
        if target is None:
            representatives.append(key)
            target = key
        aliases[key] = target[1]
    enriched = []
    for r in rows:
        date, city, country, _, _ = assets[r['asset_id']]
        assert r['taken_at'][:10] == date[:10]
        enriched.append({k:r[k] for k in ('asset_id','taken_at','caption','media_kind')} |
                        {'city':city,'country':country,'region':aliases.get((country,city),city),
                         'person_refs':sorted(people[r['asset_id']])})
    save(path, enriched)
    save(ROOT/'data/snapshot.json', {'captions':len(rows),'source':'frozen caption bank',
         'fingerprint':hashlib.sha256(json.dumps(enriched,sort_keys=True).encode()).hexdigest(),
         'location_method':'city median GPS; representative within 10 km; raw city retained',
         'fine_gps_exported':False,'image_reads':0,'episode_reads':0})
    return Library(enriched)


@lru_cache(None)
def semantics(term, pos):
    synsets = wn.synsets(term.replace(' ', '_'), pos=pos)
    if not synsets:
        return ('unclassified', 3, term)
    synset = synsets[0]
    return (synset.lexname(), synset.max_depth(), synset.name())


def candidate_pool(library):
    """Stratify observed vocabulary by general lexical classes, never named hobbies."""
    indexed = json.loads(RECURRENCES.read_text())['profiles']
    total_days = len({r['taken_at'][:10] for r in library.rows})
    anchors = {}
    for p in indexed:
        if p['kind'] not in {'noun','verb'} or p['days'] < 4 or len(p['years']) < 3:
            continue
        term = p['key'].split(':',1)[1]
        refs = set(p['source_refs'])
        retrieval_refs = set(refs)
        # Literal matches expand retrieval, not the evidence that a word is an action.
        for variant in p['variants'] + [term]:
            retrieval_refs |= library.posts.get(variant, set())
        domain, depth, family = semantics(term, wn.NOUN if p['kind']=='noun' else wn.VERB)
        key = p['kind'] + ':' + family
        if key not in anchors:
            anchors[key] = {'key':key,'anchor':term,'kind':p['kind'],'domain':domain,'depth':depth,
                            'terms':set(),'refs':set(),'retrieval_refs':set(),
                            'operator':'subject_across_contexts'}
        anchors[key]['terms'].update(p['variants'] + [term])
        anchors[key]['refs'] |= refs
        anchors[key]['retrieval_refs'] |= retrieval_refs
    for a in anchors.values():
        a.update(library.facts(a['refs']))
        a['terms'] = sorted(a['terms'])
        a['retrieval_refs'] = sorted(a['retrieval_refs'])
        a['score'] = round(math.log1p(a['days'])*math.log1p(len(a['years']))*
                           math.sqrt(min(a['depth'],14)+1)*math.log1p(total_days/a['days']),3)
    groups = defaultdict(list)
    for a in anchors.values():
        groups[a['domain']].append(a)
    for group in groups.values():
        group.sort(key=lambda a: (-a['score'],a['key']))
    # Weighted round-robin retains small semantic domains. These are broad lexical
    # dimensions (animals, acts, artifacts...), not user-specific topic categories.
    quotas = {'noun.artifact':32,'noun.animal':12,'noun.act':16,'noun.plant':8,
              'verb.motion':24,'verb.creation':24,'verb.contact':14,'noun.food':8,
              'noun.event':6,'noun.communication':5}
    chosen = []
    for domain, group in sorted(groups.items()):
        if domain in {'noun.person','noun.body','noun.attribute','noun.quantity',
                      'noun.state','noun.relation','noun.time','verb.stative','unclassified'}:
            take = 1
        else:
            take = quotas.get(domain,2)
        chosen.extend(group[:take])
        # Frequency and specificity answer different questions. Retain dominant
        # recurring subjects as well as distinctive but less common vocabulary.
        chosen.extend(sorted(group,key=lambda a:-a['days'])[:max(1,take//4)])
    # Preserve the domain allocations; a final global top-N would erase the rare
    # action families again.
    chosen = list({a['key']:a for a in chosen}.values())
    chosen.sort(key=lambda a:-a['score'])
    chosen.extend(library.geographic_candidates())
    for a in chosen:
        a['context'] = library.context(a['refs'])
        a['witnesses'] = library.witnesses(a['refs'],12)
    all_rows = sorted(anchors.values(),key=lambda a:-a['score'])
    save(ROOT/'data/all-candidates.json', all_rows)
    save(ROOT/'data/candidates.json', chosen)
    return chosen
