"""Cheaper machinery in front of Gemma, each part calibrated per request (owner 09-28).

Only ever faster answers or a calibrated "yes": nothing here drops a picture (owner ruling
09-28, "no gate, this is how we lose stuff").

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


