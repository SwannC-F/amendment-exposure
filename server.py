"""Live demo server: static files + fresh Sénat amendments + LLM extraction.

Usage: python3 server.py            # http://localhost:8766
       LLM_MOCK=1 python3 server.py # replay stored criteria, no API key needed

Endpoints
  GET  /api/live/health                    LLM configured? mock? model
  GET  /api/live/amendments?text=142       pending amendments, fetched now (cache 60 s)
  POST /api/live/extract                   {text_number, number} or {text, purpose}
  POST /api/live/extract?stream=1          same, as Server-Sent Events:
                                           event: token / reasoning  {"t": "..."}
                                           event: result             the measure card JSON
                                           event: error              {"error": "..."}

LLM config (.env): LLM_BASE_URL, LLM_API_KEY (fallback FEATHERLESS_API_KEY), LLM_MODEL.
Stdlib only. Never prints secrets. Dotfiles (.env, .git) are never served.
"""
import json
import os
import re
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from fetch_amendments import SETTLED, clean, fetch, matricule, senator_groups  # noqa: E402
from extract_criteria import SYSTEM, parse_json, prompt_for  # noqa: E402
from exposure import API as ENTREPRISES_API, BANDS, CAP, UA  # noqa: E402

PORT = int(os.environ.get("PORT", "8766"))
DEFAULT_BASE_URL = "https://api.featherless.ai/v1"
DEFAULT_MODEL = "deepseek-ai/DeepSeek-V4.1-Flash"
AMENDMENTS_TTL = 60
GROUPS_TTL = 3600
MAX_NAFS = 10  # live counting: 16 national queries per NAF


# ---------- config ----------

def env_file():
    out = {}
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def config():
    """Re-read each call so a key pasted into .env works without restart."""
    f = env_file()
    get = lambda k: os.environ.get(k) or f.get(k) or ""
    return {
        "base_url": (get("LLM_BASE_URL") or DEFAULT_BASE_URL).rstrip("/"),
        "key": get("LLM_API_KEY") or get("FEATHERLESS_API_KEY"),
        "model": get("LLM_MODEL") or get("FEATHERLESS_MODEL") or DEFAULT_MODEL,
        "mock": get("LLM_MOCK") not in ("", "0", "false", "False"),
    }


# ---------- Sénat amendments (live) ----------

_lock = threading.Lock()
_cache = {}  # text number -> (time, rows)
_groups = {"t": 0, "map": {}}


def groups_map():
    with _lock:
        if time.time() - _groups["t"] > GROUPS_TTL:
            try:
                _groups["map"], _groups["t"] = senator_groups(), time.time()
            except Exception:
                pass  # keep the previous map; author_group stays "" if never loaded
        return _groups["map"]


def live_rows(n):
    """All amendments of text n, fetched from senat.fr at most once per 60 s."""
    with _lock:
        hit = _cache.get(n)
        if hit and time.time() - hit[0] < AMENDMENTS_TTL:
            return hit[1], hit[0]
    rows = fetch(n)
    groups = groups_map()
    out = []
    for r in rows:
        url = r.get("Url amendement", "")
        out.append({
            "number": r.get("Numéro", ""),
            "article": r.get("Subdivision", ""),
            "author": r.get("Auteur", ""),
            "author_group": groups.get(matricule(r.get("Fiche Sénateur")), ""),
            "filed": r.get("Date de dépôt", ""),
            "status": r.get("Sort", ""),
            "text": clean(r.get("Dispositif", "")),
            "purpose": clean(r.get("Objet", "")),
            "url": ("https:" + url) if url.startswith("//") else url,
        })
    now = time.time()
    with _lock:
        _cache[n] = (now, out)
    return out, now


def stored_criteria(n):
    p = ROOT / f"data/criteria_{n}.json"
    if not p.exists():
        return {}
    return {c["number"]: c for c in json.loads(p.read_text())}


def num_key(number):
    m = re.match(r"\d+", number or "")
    return int(m.group(0)) if m else 0


def pending_amendments(n):
    rows, fetched = live_rows(n)
    known = stored_criteria(n)
    out = [{
        "number": a["number"], "article": a["article"], "author": a["author"],
        "author_group": a["author_group"], "filed": a["filed"], "status": a["status"],
        "purpose": a["purpose"][:400], "url": a["url"], "known": a["number"] in known,
    } for a in rows if not any(k in a["status"].lower() for k in SETTLED)]
    out.sort(key=lambda a: (a["filed"], num_key(a["number"])), reverse=True)
    return {"text": n, "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(fetched)),
            "source": f"https://www.senat.fr/amendements/2026-2027/{n}/jeu_complet_2026-2027_{n}.csv",
            "total": len(rows), "pending": len(out), "new": sum(not a["known"] for a in out),
            "amendments": out}


def find_amendment(n, number):
    rows, _ = live_rows(n)
    norm = lambda s: re.sub(r"\s+", " ", (s or "").strip().lower())
    for a in rows:
        if norm(a["number"]) == norm(number):
            return a
    for a in rows:  # "3" matches "3 rect."
        if norm(a["number"]).split(" ")[0] == norm(number):
            return a
    return None


# ---------- LLM ----------

class LLMError(Exception):
    pass


def llm_request(cfg, amendment, stream):
    body = json.dumps({
        "model": cfg["model"], "temperature": 0, "max_tokens": 1500, "stream": stream,
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": prompt_for(amendment)}],
    }).encode()
    req = urllib.request.Request(cfg["base_url"] + "/chat/completions", data=body, headers={
        "Authorization": f"Bearer {cfg['key']}", "Content-Type": "application/json",
        "Accept": "text/event-stream" if stream else "application/json"})
    try:
        return urllib.request.urlopen(req, timeout=180)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise LLMError(f"API LLM {e.code} : {detail}")
    except OSError as e:
        raise LLMError(f"API LLM injoignable : {e}")


def llm_tokens(cfg, amendment):
    """Yield (kind, text) with kind in {'token', 'reasoning'} from a streamed completion."""
    with llm_request(cfg, amendment, stream=True) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                delta = json.loads(data)["choices"][0].get("delta", {})
            except (ValueError, KeyError, IndexError):
                continue
            if delta.get("reasoning_content") or delta.get("reasoning"):
                yield "reasoning", delta.get("reasoning_content") or delta.get("reasoning")
            if delta.get("content"):
                yield "token", delta["content"]


def mock_tokens(n, amendment, delay=0.012):
    """Replay the stored criteria of a known amendment, a few characters at a time."""
    c = stored_criteria(n).get(amendment.get("number"))
    crit = dict(c["criteria"]) if c else {
        "criteria_found": False, "who": "", "sectors": [], "employee_min": None,
        "employee_max": None, "regions": [], "quote": ""}
    text = json.dumps(crit, ensure_ascii=False, indent=2)
    for i in range(0, len(text), 4):
        time.sleep(delay)
        yield "token", text[i:i + 4]


def run_extraction(n, amendment, on_token=None):
    """Return (criteria, model_label, elapsed_ms). Raises LLMError."""
    cfg = config()
    t0 = time.time()
    if cfg["mock"]:
        gen, model = mock_tokens(n, amendment, 0.012 if on_token else 0), "mock (critères stockés, data/criteria_%s.json)" % n
    elif not cfg["key"]:
        raise LLMError("NO_KEY")
    elif on_token is None:
        with llm_request(cfg, amendment, stream=False) as r:
            reply = json.load(r)["choices"][0]["message"]["content"]
        return parse_json(reply), cfg["model"], int((time.time() - t0) * 1000)
    else:
        gen, model = llm_tokens(cfg, amendment), cfg["model"]
    reply = []
    for kind, t in gen:
        if kind == "token":
            reply.append(t)
        if on_token:
            on_token(kind, t)
    try:
        crit = parse_json("".join(reply))
    except ValueError as e:
        raise LLMError(f"Réponse du modèle illisible : {e}")
    return crit, model, int((time.time() - t0) * 1000)


# ---------- enrichment ----------

DASHES = dict.fromkeys(map(ord, "‐‑‒–—−"), "-")
QUOTES = dict.fromkeys(map(ord, "’‘ʼ"), "'") | dict.fromkeys(map(ord, "«»“”"), '"')


def normalize(s):
    s = unicodedata.normalize("NFKC", s or "").translate(DASHES).translate(QUOTES)
    return re.sub(r"\s+", " ", s).strip()


def verify_quote(quote, amendment):
    """(verified, exact): exact = byte-for-byte substring; verified tolerates spaces/dashes/apostrophes."""
    if not quote or not quote.strip():
        return False, False
    hay = (amendment.get("text") or "") + "\n" + (amendment.get("purpose") or "")
    exact = quote.strip() in hay
    return exact or normalize(quote) in normalize(hay), exact


_counts_live = {}  # NAF|band -> count, fetched this run (never written to data/raw)


def national_total(naf, band):
    key = f"{naf}|{band}"
    if key not in _counts_live:
        q = urllib.parse.urlencode({"activite_principale": naf, "tranche_effectif_salarie": band,
                                    "etat_administratif": "A", "per_page": 1, "minimal": "true"})
        req = urllib.request.Request(f"{ENTREPRISES_API}?{q}", headers={"User-Agent": UA})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=20) as r:
                    _counts_live[key] = json.load(r)["total_results"]
                time.sleep(0.15)  # 7 requests/second limit
                break
            except Exception:
                time.sleep(1 + attempt)
        else:
            return None
    return _counts_live[key]


def bands_for(emin, emax):
    out = {}
    for band, (lo, hi) in BANDS.items():
        if emin is not None and (hi if hi is not None else 10**9) < emin:
            continue
        if emax is not None and lo > emax:
            continue
        if emin and band in ("NN", "00"):
            continue
        out[band] = (lo, hi)
    return out


def naf_exposure(naf, bands, cached):
    """Companies and employee range for one NAF. Cached counts first, else live national queries."""
    if all(f"{naf}|{b}" in cached for b in bands):
        source, get = "cache", lambda b: cached[f"{naf}|{b}"]
    else:
        source, get = "live", lambda b: national_total(naf, b)
    companies = low = high = 0
    approx = source == "live"
    for band, (lo, hi) in bands.items():
        n = get(band)
        if n is None:
            return None
        approx |= source == "live" and n >= CAP  # live national query caps at 10 000: a floor
        companies += n
        low += n * lo
        high += n * (hi if hi is not None else lo)
    return {"naf": naf, "companies": companies, "employees_low": low, "employees_high": high,
            "source": source, "approx": approx}


def majority():
    p = ROOT / "data/engine_142.json"
    try:
        return json.loads(p.read_text()).get("majority", [])
    except (OSError, ValueError):
        return []


def as_measure(n, amendment, crit, model, elapsed_ms):
    """Shape the result like a measure of data/engine_<n>.json, plus live fields."""
    found = bool(crit.get("criteria_found"))
    sectors = crit.get("sectors") or []
    nafs = sorted({s["naf"].strip() for s in sectors if (s.get("naf") or "").strip()})
    roles = sorted({(s.get("label") or "").split(" ")[0] for s in sectors
                    if not (s.get("naf") or "").strip() and s.get("label")})
    quote = crit.get("quote") or ""
    verified, exact = verify_quote(quote, amendment)

    companies = low = high = None
    per_naf, not_counted, approx = [], [], False
    if found and nafs:
        cached = {}
        p = ROOT / "data/raw/counts.json"
        if p.exists():
            cached = json.loads(p.read_text())
        bands = bands_for(crit.get("employee_min"), crit.get("employee_max"))
        for naf in nafs[:MAX_NAFS]:
            e = naf_exposure(naf, bands, cached)
            if e is None:
                not_counted.append(naf)
                continue
            per_naf.append(e)
            approx |= e["approx"]
        not_counted += nafs[MAX_NAFS:]
        if per_naf:
            companies = sum(e["companies"] for e in per_naf)
            low = sum(e["employees_low"] for e in per_naf)
            high = sum(e["employees_high"] for e in per_naf)
    not_counted += [r for r in roles]

    group = amendment.get("author_group") or ""
    groups = [group] if group else []
    maj = majority()
    return {
        "theme": ((crit.get("themes") or [None])[0] or crit.get("effect") or crit.get("who")
                  or "Aucun critère d'entreprise identifié"),
        "amendments": [amendment.get("number")] if amendment.get("number") else [],
        "effects": [crit["effect"]] if crit.get("effect") else [],
        "nafs": nafs, "roles": roles,
        "sectors": [{"key": s.get("naf") or s.get("label"), "label": s.get("label")} for s in sectors],
        "n_groups": len(groups), "groups": groups,
        "majority_groups": [g for g in groups if g in maj],
        "companies": companies, "employees_low": low, "employees_high": high,
        "approx": approx, "per_naf": per_naf, "not_counted": not_counted,
        "employee_min": crit.get("employee_min"), "employee_max": crit.get("employee_max"),
        "regions": crit.get("regions") or [],
        "who": crit.get("who") or "", "quote": quote,
        "quote_verified": verified, "quote_exact": exact,
        "criteria_found": found, "criteria": crit,
        "author": amendment.get("author", ""), "author_group": group,
        "article": amendment.get("article", ""), "url": amendment.get("url", ""),
        "live": True, "model": model, "elapsed_ms": elapsed_ms,
        "sources": {
            "amendement": amendment.get("url") or "texte collé",
            "comptage": "API Recherche d'entreprises (unités légales actives par NAF et tranche d'effectif)"
                        + (" ; requête nationale, plafonnée à 10 000 par tranche" if approx else ""),
        },
    }


# ---------- HTTP ----------

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT), **kw)

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.log_date_time_string(), fmt % args))

    def cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")

    def end_headers(self):
        if self.path.startswith("/api/"):
            self.cors()
        else:
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def blocked(self, path):
        return any(part.startswith(".") for part in urllib.parse.unquote(path).split("/") if part)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == "/api/live/health":
            cfg = config()
            return self.json(200, {"llm_configured": bool(cfg["key"]), "mock": cfg["mock"],
                                   "model": cfg["model"], "base_url": cfg["base_url"]})
        if u.path == "/api/live/amendments":
            n = (urllib.parse.parse_qs(u.query).get("text") or ["142"])[0]
            if not n.isdigit():
                return self.json(400, {"error": "text doit être un numéro de texte"})
            try:
                return self.json(200, pending_amendments(n))
            except Exception as e:
                return self.json(502, {"error": f"Sénat injoignable : {e}"})
        if u.path.startswith("/api/"):
            return self.json(404, {"error": "endpoint inconnu"})
        if self.blocked(u.path):
            return self.send_error(404)
        return super().do_GET()

    def do_HEAD(self):
        if self.blocked(urllib.parse.urlparse(self.path).path):
            return self.send_error(404)
        return super().do_HEAD()

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        if u.path != "/api/live/extract":
            return self.json(404, {"error": "endpoint inconnu"})
        stream = (urllib.parse.parse_qs(u.query).get("stream") or ["0"])[0] not in ("0", "")
        try:
            length = int(self.headers.get("Content-Length") or 0)
            req = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self.json(400, {"error": "corps JSON invalide"})

        cfg = config()
        if not cfg["mock"] and not cfg["key"]:
            return self.json(503, {"error": "Clé LLM manquante : ajoutez LLM_API_KEY dans .env"})

        n = str(req.get("text_number") or "142")
        if req.get("number"):
            try:
                amendment = find_amendment(n, str(req["number"]))
            except Exception as e:
                return self.json(502, {"error": f"Sénat injoignable : {e}"})
            if not amendment:
                return self.json(404, {"error": f"Amendement n°{req['number']} introuvable sur le texte {n}"})
        elif req.get("text") or req.get("purpose"):
            amendment = {"number": "", "article": req.get("article", ""), "author": "",
                         "author_group": req.get("author_group", ""), "url": "",
                         "text": clean(req.get("text", "")), "purpose": clean(req.get("purpose", ""))}
        else:
            return self.json(400, {"error": "Donnez {text_number, number} ou {text, purpose}"})

        if not stream:
            try:
                crit, model, ms = run_extraction(n, amendment)
            except LLMError as e:
                return self.json(502, {"error": str(e)})
            except Exception as e:
                return self.json(502, {"error": f"Extraction impossible : {e}"})
            return self.json(200, as_measure(n, amendment, crit, model, ms))

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        def send(event, data):
            self.wfile.write(f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode())
            self.wfile.flush()

        try:
            send("start", {"number": amendment["number"], "author": amendment["author"],
                           "author_group": amendment["author_group"], "url": amendment["url"],
                           "model": "mock" if cfg["mock"] else cfg["model"]})
            crit, model, ms = run_extraction(n, amendment, on_token=lambda k, t: send(k, {"t": t}))
            send("status", {"t": "Comptage des entreprises (API Recherche d'entreprises)…"})
            send("result", as_measure(n, amendment, crit, model, ms))
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as e:
            try:
                send("error", {"error": str(e)})
            except OSError:
                pass


def main():
    cfg = config()
    state = "mock" if cfg["mock"] else ("clé présente" if cfg["key"] else "clé absente → 503")
    print(f"http://localhost:{PORT}  ·  LLM {cfg['model']} ({state})  ·  dossier {ROOT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
