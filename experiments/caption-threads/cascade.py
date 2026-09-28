"""Cheaper machinery in front of Gemma, each part calibrated per request (owner 09-28). The default
and only path: no switch (owner ruling, "no gate, this is how we lose stuff").

- Captions: grammar proposes "belongs" when a main-subject word sits before the caption's verb
  ("A black cat is sleeping...", "A car's dashboard with..."). Gemma judges a sample of those; the
  grammar's yeses stand only when Gemma agrees on at least AGREE of the sample.
- Photos: the stack's own captioner (SmolVLM-500M, ~0.7 s a photo against ~5.6 s) answers the
  same yes/no question. Both answer the first photos; SmolVLM answers the rest only when they agree
  on at least AGREE of them.
Nothing here knows a request: the sample decides, every time.
"""

import hashlib
import json
import re

import httpx

from experiment_data import ROOT, save

AGREE = 0.9
GRAMMAR_SAMPLE = 48
SMOL_SAMPLE = 24
# English grammar, not meaning: the first verb or preposition ends a caption's subject.
SUBJECT_ENDS = re.compile(
    r"\b(is|are|was|were|sits|sit|sitting|stands|standing|lies|lying|lays|laying|rests|resting|with|on|in|at|"
    r"near|next|inside|under|behind|beside|by|against|holding|holds|filled|displays|displayed|shows|showing|"
    r"parked|driving|riding|walking|covered|surrounded|featuring|that|which|while|as|from|into|through)\b")


def _stem(word):
    return word[:-1] if word.endswith("s") and len(word) > 3 else word


def grammar_says_subject(caption, core, not_this=()):
    """True when a main-subject word names the caption's grammatical subject."""
    text = (caption or "").lower()
    if not text or any(p.lower() in text for p in not_this or ()):
        return False
    end = SUBJECT_ENDS.search(text)
    subject = {_stem(w) for w in re.findall(r"[a-z]+", text[:end.start()] if end else text)}
    wanted = {_stem(w) for phrase in core for w in re.findall(r"[a-z]+", phrase.lower())}
    return bool(subject & wanted)


def _captioner(config):
    base = config.editorial.preparation.caption_base_url.rstrip("/")
    models = httpx.get(base + "/models", timeout=10, trust_env=False).json()["data"]
    return base, models[0]["id"]


_ENDPOINT = {}


def smol_yes(config, question, asset_id, preview):
    """The captioner's yes/no on one photo; None when it gives no usable answer. Cached."""
    if "base" not in _ENDPOINT:
        _ENDPOINT["base"], _ENDPOINT["model"] = _captioner(config)
    cache = ROOT / "looks-smol"
    cache.mkdir(exist_ok=True)
    path = cache / (hashlib.sha256((_ENDPOINT["model"] + question + asset_id).encode()).hexdigest()[:24] + ".json")
    if path.exists():
        return json.loads(path.read_text()).get("yes")
    body = {"model": _ENDPOINT["model"], "max_tokens": 3, "temperature": 0,
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": preview(config, asset_id)}},
                {"type": "text", "text": question + " Answer yes or no."}]}]}
    try:
        reply = httpx.post(_ENDPOINT["base"] + "/chat/completions", json=body, timeout=120, trust_env=False).json()
        text = reply["choices"][0]["message"]["content"].strip().lower()
    except (httpx.HTTPError, KeyError, IndexError, ValueError):
        return None
    answer = True if text.startswith("yes") else False if text.startswith("no") else None
    save(path, {"yes": answer, "raw": text})
    return answer



# ---- The look ladder: pictures only after every free check, and only where they change the film.

EPISODE_GAP_S = 90 * 60  # the product's episode gap (selection_source_groups)
PER_MOMENT = 2           # photos looked at per open moment; the engine keeps a few per moment anyway
HEADS = ("doc_docling", "location", "venue", "activity", "people", "children")

CONTRADICT = '''The owner asked for a film (owner_request). Small image models recorded these facts about
each photo. Which facts mean a photo cannot belong in this film? Pick only facts that clearly
contradict the request; none when none does. Return JSON.'''


def banked_heads(bank, asset_ids):
    """The small heads preparation already ran, read from the annotation store: free."""
    import sqlite3

    out = {}
    wanted = list(set(asset_ids))
    with sqlite3.connect(f"file:{bank}?mode=ro", uri=True) as db:
        for start in range(0, len(wanted), 900):
            part = wanted[start:start + 900]
            rows = db.execute(
                f"SELECT asset_id, head, label FROM head_facts WHERE head IN ({','.join('?' * len(HEADS))}) "
                f"AND asset_id IN ({','.join('?' * len(part))}) ORDER BY decided_at", (*HEADS, *part))
            for asset_id, head, label in rows:
                out.setdefault(asset_id, {})[head] = label
    return out


def moments(library, refs):
    """Episode id per ref: a new moment after a 90-minute gap, as the product groups them."""
    from datetime import datetime

    ordered = sorted(refs, key=lambda i: library.rows[i]["taken_at"])
    out, current, last = {}, -1, None
    for i in ordered:
        t = datetime.fromisoformat(library.rows[i]["taken_at"].replace("Z", "+00:00")).timestamp()
        if last is None or t - last > EPISODE_GAP_S:
            current += 1
        out[i], last = current, t
    return out


def ask_contradictions(reader, key, brief, heads):
    labels = sorted({f"{h}: {v}" for facts in heads.values() for h, v in facts.items()
                     if h != "doc_docling" and v not in {"other", "undetermined"}})
    if not labels:
        return set()
    answer = reader.ask("ladder_contradicts", key, CONTRADICT, {"owner_request": brief, "facts": labels},
                        lambda a: None, 200, schema={"type": "object", "additionalProperties": False,
                        "required": ["facts"], "properties": {"facts": {"type": "array", "maxItems": 6,
                        "items": {"type": "string", "enum": labels}}}}) or {}
    return {tuple(f.split(": ", 1)) for f in answer.get("facts") or []}


def ladder(look, library, plan, kept, unsure, captionless, anchors, score, heads, contradicts, rng_seed=11):
    """Text yes, unsure captions and caption-less pictures through the cheapest checks first.

    look(refs) -> (confirmed, log). Returns (kept, log, stats)."""
    import random

    stats = {}
    aid = lambda i: library.rows[i]["asset_id"]  # noqa: E731
    photo = lambda i: heads.get(aid(i), {}).get("doc_docling", "photograph") == "photograph"  # noqa: E731
    ruled = lambda i: any(heads.get(aid(i), {}).get(h) == v for h, v in contradicts)  # noqa: E731
    # 1. Free: a film is made of photographs (screenshots, logos, maps and tables out).
    kept = [i for i in kept if photo(i)]
    open_ = [i for i in set(unsure) | set(captionless) | set(anchors) if photo(i)]
    stats["not_photographs"] = len(set(unsure) | set(captionless) | set(anchors)) - len(open_)
    # 2. Free: a banked fact Gemma said contradicts the request (never applied to anchors: letters vouch).
    before = len(open_)
    open_ = [i for i in open_ if i in anchors or not ruled(i)]
    stats["ruled_out_by_facts"] = before - len(open_)
    log = []
    # 3. The caption yeses: a sample calibrates them (and, first, SmolVLM against E4B).
    sample = random.Random(rng_seed).sample(sorted(kept), min(24, len(kept)))
    confirmed, sample_log = look(set(sample))
    log += sample_log
    agree = len(confirmed) / max(1, len(sample))
    stats["text_yes_agreement"] = round(agree, 2)
    moment = moments(library, set(kept) | set(open_))
    if agree >= 0.8 or len(kept) <= len(sample):
        kept = (set(kept) - set(sample)) | set(confirmed) if agree >= 0.8 else set(confirmed)
    else:
        # Not trusted: look at up to PER_MOMENT yeses per moment; a moment passes or fails together.
        by = {}
        for i in sorted(set(kept) - set(sample), key=lambda i: -(score or {}).get(i, 0)):
            by.setdefault(moment[i], []).append(i)
        probe = [i for refs in by.values() for i in refs[:PER_MOMENT]]
        passed, probe_log = look(set(probe))
        log += probe_log
        good = {moment[i] for i in passed} | {moment[i] for i in confirmed}
        kept = set(confirmed) | {i for m, refs in by.items() if m in good for i in refs}
        stats["yes_moments_looked"] = len(by)
    # 4. Free: a moment already in the pool needs no more looking.
    covered = {moment[i] for i in kept}
    waiting = [i for i in open_ if moment[i] not in covered or i in anchors]
    stats["open_in_covered_moments"] = len(open_) - len(waiting)
    # 5. Up to PER_MOMENT photos per open moment, best-ranked first (SmolVLM or E4B inside look()).
    by = {}
    for i in sorted(waiting, key=lambda i: (i not in anchors, -(score or {}).get(i, 0))):
        by.setdefault(moment[i], []).append(i)
    probe = [i for refs in by.values() for i in refs[:PER_MOMENT]]
    stats["open_moments"], stats["open_looked"] = len(by), len(probe)
    seen, open_log = look(set(probe))
    log += open_log
    return sorted(set(kept) | set(seen), key=lambda i: library.rows[i]["taken_at"]), log, stats
