"""Shared LLM client for the pipeline: OpenAI-compatible chat, JSON answers, disk cache,
verbatim-quote check after typographic normalisation.

Config from .env: LLM_BASE_URL (default Featherless), LLM_API_KEY (or FEATHERLESS_API_KEY),
LLM_MODEL (default zai-org/GLM-5.2). LLM_MOCK=1 is for UI development only and must never
be used to produce data/.

    from llm import chat_json, verify_quote, normalize
    answer = chat_json(system, user)          # dict or list, cached on disk
    ok = verify_quote(answer["quote"], text_a, text_b)
"""
import hashlib
import json
import os
import re
import time
import unicodedata
import urllib.request
from pathlib import Path

CACHE_DIR = Path("data/cache/llm")
DEFAULT_BASE = "https://api.featherless.ai/v1"
DEFAULT_MODEL = "zai-org/GLM-5.2"
MIN_TOKENS = 4000  # GLM-5.2 reasons first; a small budget leaves `content` empty


def load_env(path=".env"):
    p = Path(path)
    if p.exists():
        for line in p.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


def config():
    load_env()
    return {
        "base": (os.environ.get("LLM_BASE_URL") or DEFAULT_BASE).rstrip("/"),
        "key": os.environ.get("LLM_API_KEY") or os.environ.get("FEATHERLESS_API_KEY"),
        "model": os.environ.get("LLM_MODEL") or DEFAULT_MODEL,
    }


# ---------- quotes ----------

_TRANSLATE = {
    "’": "'", "‘": "'", "ʼ": "'", "“": '"', "”": '"', "«": '"', "»": '"',
    " ": " ", " ": " ", " ": " ", " ": " ", "‑": "-", "‐": "-",
    "–": "-", "—": "-", "…": "...",
}


def normalize(text):
    """Lowercase-insensitive comparison form: NFKC, typographic quotes/spaces/hyphens unified,
    HTML entities and tags already removed upstream, whitespace collapsed."""
    t = unicodedata.normalize("NFKC", text or "")
    t = "".join(_TRANSLATE.get(ch, ch) for ch in t)
    t = re.sub(r'"\s+', '"', re.sub(r'\s+"', '"', t))  # « mot » vs "mot"
    return re.sub(r"\s+", " ", t).strip().lower()


def verify_quote(quote, *texts):
    """True if the quote appears verbatim (after normalisation) in one of the texts."""
    q = normalize(quote)
    return bool(q) and len(q) >= 8 and any(q in normalize(t) for t in texts if t)


# ---------- chat ----------

def parse_json(text):
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start = min([i for i in (text.find("{"), text.find("[")) if i >= 0], default=-1)
    if start < 0:
        raise ValueError(f"no JSON in reply: {text[:200]}")
    end = max(text.rfind("}"), text.rfind("]"))
    return json.loads(text[start:end + 1])


def _call(cfg, messages, max_tokens, temperature):
    body = json.dumps({"model": cfg["model"], "temperature": temperature, "max_tokens": max_tokens,
                       "messages": messages}).encode()
    req = urllib.request.Request(f"{cfg['base']}/chat/completions", data=body, headers={
        "Authorization": f"Bearer {cfg['key']}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)


def chat_json(system, user, *, max_tokens=MIN_TOKENS, temperature=0, use_cache=True):
    """Ask for a JSON answer. Cached on disk by (model, system, user). Raises on failure."""
    cfg = config()
    if os.environ.get("LLM_MOCK") == "1":
        raise RuntimeError("LLM_MOCK=1: the pipeline never produces data from the mock")
    if not cfg["key"]:
        raise RuntimeError("Clé LLM manquante : ajoutez LLM_API_KEY dans .env")
    key = hashlib.sha256(json.dumps([cfg["model"], system, user]).encode()).hexdigest()
    path = CACHE_DIR / f"{key}.json"
    if use_cache and path.exists():
        return json.loads(path.read_text())["answer"]

    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    budget, last = max(max_tokens, MIN_TOKENS), None
    for attempt in range(4):
        try:
            r = _call(cfg, messages, budget, temperature)
            choice = r["choices"][0]
            content = choice["message"].get("content") or ""
            if not content.strip() and choice.get("finish_reason") == "length":
                budget *= 2  # reasoning ate the budget: retry once bigger
                continue
            answer = parse_json(content)
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"model": cfg["model"], "usage": r.get("usage"), "answer": answer},
                                       ensure_ascii=False))
            return answer
        except Exception as e:  # network, rate limit, malformed JSON
            last = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"LLM failed: {last}")


def model_name():
    return config()["model"]
