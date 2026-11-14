"""Live server: static files + generated texts + fresh Sénat amendments + LLM (extract, scan).

Usage: python3 server.py            # http://localhost:8766, real model from .env
       LLM_MOCK=1 python3 server.py # UI development without a key (never produces data/)

Everything is indexed by (session, texte), e.g. 2026-2027 / 142.

  GET  /api/live/health
  GET  /api/text/<session>/<texte>                 data/<session>/<texte>/engine.json
                                                   (absent -> 404; ?refresh=1 -> runs pipeline.py, 202 {status:"running"})
  GET  /api/text/<session>/<texte>/status          pipeline run: status, elapsed, tail of its output
  GET  /api/live/amendments?session=&text=         pending amendments fetched now (cache 60 s), known = in criteria.json
  POST /api/live/extract[?stream=1]                {session, text_number, number} or {session, text_number, dispositif|text, objet|purpose}
                                                   criteria + exposure + attachment to the closest measure
  POST /api/live/scan[?stream=1]                   {session, text_number, company:{...}} which amendments concern one company

SSE events: start, reasoning {t}, token {t}, status {t}, result {...}, error {error}.
LLM config (.env, via llm.py): LLM_BASE_URL, LLM_API_KEY (or FEATHERLESS_API_KEY), LLM_MODEL.
Stdlib only. Never prints secrets. Dotfiles (.env, .git) are never served.
"""
import collections
import csv
import hashlib
import json
import os
import re
import subprocess
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

import llm  # noqa: E402
from fetch_amendments import SETTLED, URL as SENAT_CSV, clean, download, matricule, senator_groups  # noqa: E402
from exposure import API as ENTREPRISES_API, BANDS, CAP, UA  # noqa: E402

try:  # the pipeline's extraction prompt, once extract.py exists
    from extract import SYSTEM, prompt_for  # noqa: E402
except Exception:
    from extract_criteria import SYSTEM, prompt_for  # noqa: E402

PORT = int(os.environ.get("PORT", "8766"))
DEFAULT_SESSION, DEFAULT_TEXT = "2026-2027", "142"
AMENDMENTS_TTL = 60
GROUPS_TTL = 3600
MAX_NAFS = 10  # live counting: 16 national queries per NAF
SCAN_TOKENS = 8000
SESSION_RE = re.compile(r"^\d{4}-\d{4}$")


# ---------- config ----------

def config():
    cfg = llm.config()
    mock = os.environ.get("LLM_MOCK", "")
    return {"base_url": cfg["base"], "key": cfg["key"] or "", "model": cfg["model"],
            "mock": mock not in ("", "0", "false", "False")}


def valid(session, texte):
    return bool(SESSION_RE.match(session or "")) and (texte or "").isdigit()


def text_dir(session, texte):
    return ROOT / "data" / session / texte


def legacy(session, texte, name):
    """Pre-pipeline files (data/<name>_<texte>.json), used only when the pipeline output is absent."""
    return ROOT / "data" / f"{name}_{texte}.json" if session == DEFAULT_SESSION else None


def read_json(*paths):
    for p in paths:
        if p and p.exists():
            try:
                return json.loads(p.read_text())
            except ValueError:
                continue
    return None


# ---------- per-text stored data ----------

def criteria_of(entry):
    return entry.get("criteria") if isinstance(entry.get("criteria"), dict) else entry


def stored_criteria(session, texte):
    """number -> criteria dict, from data/<s>/<t>/criteria.json (or the legacy file)."""
    raw = read_json(text_dir(session, texte) / "criteria.json", legacy(session, texte, "criteria"))
    if isinstance(raw, dict):
        raw = [{"number": k, **(v if isinstance(v, dict) else {})} for k, v in raw.items()]
    out = {}
    for e in raw or []:
        if isinstance(e, dict) and e.get("number"):
            out[str(e["number"])] = criteria_of(e)
    return out


def measures_of(session, texte):
    """[{key, theme, amendments}] from measures.json, else rebuilt from engine.json / legacy engine."""
    m = read_json(text_dir(session, texte) / "measures.json")
    if isinstance(m, list):
        return [x for x in m if isinstance(x, dict)]
    eng = read_json(text_dir(session, texte) / "engine.json", legacy(session, texte, "engine")) or {}
    return [{"key": x.get("key") or x["theme"], "theme": x["theme"], "amendments": x.get("amendments", []),
             "effects": x.get("effects", [])} for x in eng.get("measures", []) if x.get("theme")]


def majority(session, texte):
    eng = read_json(text_dir(session, texte) / "engine.json", legacy(session, texte, "engine")) or {}
    return eng.get("majority", [])


def known_index(session, texte):
    """number -> {criteria, theme}; theme from the measure the amendment belongs to."""
    crit = stored_criteria(session, texte)
    theme_of = {}
    for m in measures_of(session, texte):
        for a in m.get("amendments", []):
            theme_of[str(a)] = m.get("theme")
    out = {}
    for num, c in crit.items():
        out[num] = {"criteria": c, "theme": theme_of.get(num) or (c.get("themes") or [None])[0] or c.get("effect")}
    return out


# ---------- Sénat amendments (live) ----------

_lock = threading.Lock()
_cache = {}  # (session, texte) -> (time, rows)
_groups = {"t": 0, "map": {}}


def groups_map():
    with _lock:
        if time.time() - _groups["t"] > GROUPS_TTL:
            try:
                _groups["map"], _groups["t"] = senator_groups(), time.time()
            except Exception:
                pass
        return _groups["map"]


def fetch_csv(session, texte):
    lines = download(SENAT_CSV.format(s=session, n=texte)).splitlines()
    if lines and lines[0].startswith("sep="):
        lines = lines[1:]
    rows = list(csv.reader(lines, delimiter="\t"))
    header = [h.strip() for h in rows[0]]
    return [dict(zip(header, (c.strip() for c in r))) for r in rows[1:] if len(r) >= len(header) - 1]


def live_rows(session, texte):
    with _lock:
        hit = _cache.get((session, texte))
        if hit and time.time() - hit[0] < AMENDMENTS_TTL:
            return hit[1], hit[0]
    rows = fetch_csv(session, texte)
    groups = groups_map()
    out = []
    for r in rows:
        url = r.get("Url amendement", "")
        out.append({
            "number": r.get("Numéro", ""), "article": r.get("Subdivision", ""), "author": r.get("Auteur", ""),
            "author_group": groups.get(matricule(r.get("Fiche Sénateur")), ""),
            "filed": r.get("Date de dépôt", ""), "status": r.get("Sort", ""),
            "text": clean(r.get("Dispositif", "")), "purpose": clean(r.get("Objet", "")),
            "url": ("https:" + url) if url.startswith("//") else url,
        })
    now = time.time()
    with _lock:
        _cache[(session, texte)] = (now, out)
    return out, now


def pending_of(rows):
    return [a for a in rows if not any(k in a["status"].lower() for k in SETTLED)]


def num_key(number):
    m = re.match(r"\d+", number or "")
    return int(m.group(0)) if m else 0


def pending_amendments(session, texte):
    rows, fetched = live_rows(session, texte)
    known = stored_criteria(session, texte)
    out = [{
        "number": a["number"], "article": a["article"], "author": a["author"],
        "author_group": a["author_group"], "filed": a["filed"], "status": a["status"],
        "purpose": a["purpose"][:400], "url": a["url"], "known": a["number"] in known,
    } for a in pending_of(rows)]
    out.sort(key=lambda a: (a["filed"], num_key(a["number"])), reverse=True)
    return {"session": session, "text": texte,
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(fetched)),
            "source": SENAT_CSV.format(s=session, n=texte).replace("http://", "https://"),
            "total": len(rows), "pending": len(out), "new": sum(not a["known"] for a in out),
            "amendments": out}


def find_amendment(session, texte, number):
    rows, _ = live_rows(session, texte)
    norm = lambda s: re.sub(r"\s+", " ", (s or "").strip().lower())
    for a in rows:
        if norm(a["number"]) == norm(number):
            return a
    for a in rows:  # "3" matches "3 rect."
        if norm(a["number"]).split(" ")[0] == norm(number):
            return a
    return None


# ---------- pipeline runs ----------

_runs = {}  # (session, texte) -> run dict


def start_pipeline(session, texte):
    key = (session, texte)
    with _lock:
        run = _runs.get(key)
        if run and run["status"] == "running":
            return run, False
        if not (ROOT / "pipeline.py").exists():
            run = {"status": "error", "error": "pipeline.py absent", "tail": collections.deque(maxlen=40),
                   "started_at": time.time(), "finished_at": time.time(), "returncode": None}
            _runs[key] = run
            return run, False
        run = {"status": "running", "started_at": time.time(), "finished_at": None, "returncode": None,
               "tail": collections.deque(maxlen=40), "error": None}
        _runs[key] = run

    def work():
        env = {k: v for k, v in os.environ.items() if k != "LLM_MOCK"}  # the pipeline never uses the mock
        env["PYTHONUNBUFFERED"] = "1"
        try:
            p = subprocess.Popen([sys.executable, "pipeline.py", session, texte], cwd=ROOT, env=env,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            for line in p.stdout:
                run["tail"].append(line.rstrip())
            run["returncode"] = p.wait()
            run["status"] = "done" if run["returncode"] == 0 else "error"
            if run["returncode"]:
                run["error"] = f"pipeline.py a échoué (code {run['returncode']})"
        except Exception as e:
            run["status"], run["error"] = "error", str(e)
        run["finished_at"] = time.time()

    threading.Thread(target=work, daemon=True).start()
    return run, True


def run_status(session, texte):
    run = _runs.get((session, texte))
    engine = text_dir(session, texte) / "engine.json"
    base = {"session": session, "text": texte, "engine_exists": engine.exists(),
            "engine_updated": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(engine.stat().st_mtime))
            if engine.exists() else None}
    if not run:
        return {**base, "status": "idle"}
    end = run["finished_at"] or time.time()
    return {**base, "status": run["status"], "error": run["error"], "returncode": run["returncode"],
            "elapsed_s": round(end - run["started_at"], 1), "tail": list(run["tail"])}


# ---------- LLM (streaming; non-streaming goes through llm.chat_json) ----------

class LLMError(Exception):
    pass


def cache_path(cfg, system, user):
    key = hashlib.sha256(json.dumps([cfg["model"], system, user]).encode()).hexdigest()
    return llm.CACHE_DIR / f"{key}.json"


def stream_request(cfg, messages, max_tokens):
    body = json.dumps({"model": cfg["model"], "temperature": 0, "max_tokens": max_tokens, "stream": True,
                       "messages": messages}).encode()
    req = urllib.request.Request(cfg["base_url"] + "/chat/completions", data=body, headers={
        "Authorization": f"Bearer {cfg['key']}", "Content-Type": "application/json",
        "Accept": "text/event-stream"})
    try:
        return urllib.request.urlopen(req, timeout=300)
    except urllib.error.HTTPError as e:
        raise LLMError(f"API LLM {e.code} : {e.read().decode('utf-8', 'replace')[:300]}")
    except OSError as e:
        raise LLMError(f"API LLM injoignable : {e}")


def stream_tokens(cfg, messages, max_tokens, meta):
    """Yield (kind, text). meta gets finish_reason and usage."""
    with stream_request(cfg, messages, max_tokens) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
            except ValueError:
                continue
            if obj.get("usage"):
                meta["usage"] = obj["usage"]
            choices = obj.get("choices") or [{}]
            if choices[0].get("finish_reason"):
                meta["finish_reason"] = choices[0]["finish_reason"]
            delta = choices[0].get("delta") or {}
            if delta.get("reasoning_content") or delta.get("reasoning"):
                yield "reasoning", delta.get("reasoning_content") or delta.get("reasoning")
            if delta.get("content"):
                yield "token", delta["content"]


def ask(system, user, max_tokens, on_event=None):
    """JSON answer from the real model: (answer, model, cached). Streams when on_event is given.
    Shares llm.py's disk cache, so a replay is instant and free."""
    cfg = config()
    if not cfg["key"]:
        raise LLMError("NO_KEY")
    path = cache_path(cfg, system, user)
    if path.exists():
        answer = json.loads(path.read_text())["answer"]
        if on_event:
            on_event("status", {"t": "Réponse déjà calculée (cache), relue sans appeler le modèle."})
            text = json.dumps(answer, ensure_ascii=False, indent=2)
            for i in range(0, len(text), 12):
                on_event("token", {"t": text[i:i + 12]})
        return answer, cfg["model"], True
    if not on_event:
        try:
            return llm.chat_json(system, user, max_tokens=max_tokens), cfg["model"], False
        except Exception as e:
            raise LLMError(str(e))
    meta, reply = {}, []
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    for kind, t in stream_tokens(cfg, messages, max(max_tokens, llm.MIN_TOKENS), meta):
        if kind == "token":
            reply.append(t)
        on_event(kind, {"t": t})
    text = "".join(reply)
    if not text.strip():  # reasoning ate the budget: retry without streaming, budget doubled
        on_event("status", {"t": f"Budget épuisé par le raisonnement ({meta.get('finish_reason')}), relance…"})
        try:
            return llm.chat_json(system, user, max_tokens=2 * max(max_tokens, llm.MIN_TOKENS)), cfg["model"], False
        except Exception as e:
            raise LLMError(str(e))
    try:
        answer = llm.parse_json(text)
    except ValueError as e:
        raise LLMError(f"Réponse du modèle illisible : {e}")
    llm.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"model": cfg["model"], "usage": meta.get("usage"), "answer": answer},
                               ensure_ascii=False))
    return answer, cfg["model"], False


def mock_stream(text, on_event, kind="token", step=4, delay=0.012):
    if on_event:
        for i in range(0, len(text), step):
            time.sleep(delay)
            on_event(kind, {"t": text[i:i + step]})


# ---------- quotes ----------

def verify_quote(quote, amendment):
    """(verified, exact). verified uses llm.verify_quote (typographic normalisation)."""
    q = (quote or "").strip()
    hay = [amendment.get("text") or "", amendment.get("purpose") or ""]
    exact = bool(q) and any(q in h for h in hay)
    return exact or llm.verify_quote(q, *hay), exact


# ---------- exposure ----------

_counts_live = {}


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
                time.sleep(0.15)
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
        approx |= source == "live" and n >= CAP
        companies += n
        low += n * lo
        high += n * (hi if hi is not None else lo)
    return {"naf": naf, "companies": companies, "employees_low": low, "employees_high": high,
            "source": source, "approx": approx}


# ---------- extract: one amendment ----------

ATTACH_SYSTEM = """Tu regroupes des amendements parlementaires en mesures.
On te donne la liste numérotée des mesures existantes d'un texte (id, thème, effets) et un nouvel amendement (effet, entreprises visées, citation).
Rattache le nouvel amendement à la mesure existante qui a le MÊME objet (même dispositif visé, même sens ou sens contraire explicite), sinon réponds null.
Réponds UNIQUEMENT par un objet JSON : {"id": numéro entier d'une mesure existante ou null, "reason": "une phrase"}"""


def closest_measure(ans, measures):
    """Measure designated by the answer: id first, else key/theme matched tolerantly (typos)."""
    import difflib
    if not isinstance(ans, dict):
        return None
    i = ans.get("id")
    if isinstance(i, str) and i.strip().isdigit():
        i = int(i)
    if isinstance(i, int) and 1 <= i <= len(measures):
        return measures[i - 1]
    label = fold(str(ans.get("key") or ans.get("theme") or ""))
    if not label:
        return None
    best = max(measures, key=lambda m: max(difflib.SequenceMatcher(None, label, fold(str(m.get(k) or ""))).ratio()
                                           for k in ("key", "theme")))
    score = max(difflib.SequenceMatcher(None, label, fold(str(best.get(k) or ""))).ratio() for k in ("key", "theme"))
    return best if score >= 0.85 else None


def attach_measure(session, texte, amendment, crit, on_event=None, mock=False):
    """Closest existing measure for this amendment: {key, theme, amendments, new, reason, method}."""
    measures = measures_of(session, texte)
    num = amendment.get("number")
    for m in measures:
        if num and num in [str(a) for a in m.get("amendments", [])]:
            return {"key": m.get("key"), "theme": m["theme"], "amendments": m.get("amendments", []),
                    "new": False, "reason": "amendement déjà rattaché à cette mesure", "method": "stocké"}
    new = {"key": None, "theme": "nouvelle mesure", "amendments": [], "new": True}
    if not measures or not crit.get("criteria_found"):
        return {**new, "reason": "aucune mesure existante" if not measures else "aucun critère trouvé",
                "method": "règle"}
    if mock:
        return {**new, "reason": "mode mock : pas de rattachement par le modèle", "method": "mock"}
    if on_event:
        on_event("status", {"t": "Rattachement à une mesure existante…"})
    user = ("Mesures existantes :\n" + json.dumps(
        [{"id": i, "theme": m["theme"], "effects": m.get("effects", [])[:4]} for i, m in enumerate(measures, 1)],
        ensure_ascii=False, indent=1) + "\n\nNouvel amendement :\n" + json.dumps(
        {"effet": crit.get("effect"), "visées": crit.get("who"), "citation": crit.get("quote"),
         "objet": (amendment.get("purpose") or "")[:800]}, ensure_ascii=False, indent=1))
    try:
        ans, _, _ = ask(ATTACH_SYSTEM, user, llm.MIN_TOKENS)
    except LLMError as e:
        return {**new, "reason": f"rattachement impossible : {e}", "method": "erreur"}
    m = closest_measure(ans, measures)
    if m:
        return {"key": m.get("key"), "theme": m["theme"], "amendments": m.get("amendments", []),
                "new": False, "reason": ans.get("reason", ""), "method": "llm"}
    return {**new, "reason": (ans.get("reason") if isinstance(ans, dict) else "") or "aucune mesure proche",
            "method": "llm"}


def run_extraction(session, texte, amendment, on_event=None):
    cfg = config()
    t0 = time.time()
    if cfg["mock"]:
        c = stored_criteria(session, texte).get(amendment.get("number"))
        crit = dict(c) if c else {"criteria_found": False, "who": "", "sectors": [], "employee_min": None,
                                  "employee_max": None, "regions": [], "quote": ""}
        mock_stream(json.dumps(crit, ensure_ascii=False, indent=2), on_event)
        model, cached = f"mock (critères stockés de data/{session}/{texte})", False
    else:
        crit, model, cached = ask(SYSTEM, prompt_for(amendment), llm.MIN_TOKENS, on_event)
        if not isinstance(crit, dict):
            raise LLMError("Réponse du modèle inattendue (pas un objet JSON)")
    elapsed = int((time.time() - t0) * 1000)
    measure = attach_measure(session, texte, amendment, crit, on_event, mock=cfg["mock"])
    return crit, model, elapsed, cached, measure, int((time.time() - t0) * 1000) - elapsed


def as_measure(session, texte, amendment, crit, model, elapsed_ms, cached, measure, attach_ms):
    found = bool(crit.get("criteria_found"))
    sectors = crit.get("sectors") or []
    nafs = sorted({s["naf"].strip() for s in sectors if (s.get("naf") or "").strip()})
    roles = sorted(set(crit.get("roles") or []) | {(s.get("label") or "").split(" ")[0] for s in sectors
                                                   if not (s.get("naf") or "").strip() and s.get("label")})
    quote = crit.get("quote") or ""
    verified, exact = verify_quote(quote, amendment)

    companies = low = high = None
    per_naf, not_counted, approx = [], [], False
    if found and nafs:
        cached_counts = read_json(ROOT / "data/raw/counts.json") or {}
        bands = bands_for(crit.get("employee_min"), crit.get("employee_max"))
        for naf in nafs[:MAX_NAFS]:
            e = naf_exposure(naf, bands, cached_counts)
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
    not_counted += roles

    group = amendment.get("author_group") or ""
    groups = [group] if group else []
    maj = majority(session, texte)
    extracted = ((crit.get("themes") or [None])[0] or crit.get("effect") or crit.get("who")
                 or "Aucun critère d'entreprise identifié")
    return {
        "theme": measure["theme"] if not measure["new"] else extracted,
        "extracted_theme": extracted, "measure": measure,
        "amendments": [amendment.get("number")] if amendment.get("number") else [],
        "effects": [crit["effect"]] if crit.get("effect") else [],
        "nafs": nafs, "roles": roles,
        "sectors": [{"key": s.get("naf") or s.get("label"), "label": s.get("label")} for s in sectors],
        "n_groups": len(groups), "groups": groups, "majority_groups": [g for g in groups if g in maj],
        "companies": companies, "employees_low": low, "employees_high": high,
        "approx": approx, "per_naf": per_naf, "not_counted": not_counted,
        "employee_min": crit.get("employee_min"), "employee_max": crit.get("employee_max"),
        "regions": crit.get("regions") or [], "who": crit.get("who") or "", "quote": quote,
        "quote_verified": verified, "quote_exact": exact, "criteria_found": found, "criteria": crit,
        "author": amendment.get("author", ""), "author_group": group,
        "article": amendment.get("article", ""), "url": amendment.get("url", ""),
        "session": session, "text": texte, "live": True, "model": model, "cached": cached,
        "elapsed_ms": elapsed_ms, "attach_ms": attach_ms,
        "sources": {
            "amendement": amendment.get("url") or "texte collé",
            "comptage": "API Recherche d'entreprises (unités légales actives par NAF et tranche d'effectif)"
                        + (" ; requête nationale, plafonnée à 10 000 par tranche" if approx else ""),
        },
    }


# ---------- scan: which pending amendments concern ONE company ----------

SCAN_SYSTEM = """Tu analyses des amendements parlementaires français pour UNE entreprise donnée.
On te donne la fiche de l'entreprise (nom, activité, code NAF, tranche d'effectif, rôles) puis une liste d'amendements (numéro, dispositif, objet).
Pour chaque amendement qui toucherait CONCRÈTEMENT cette entreprise, compte tenu de son activité réelle (pas seulement de son code NAF), donne une ligne.
Réponds UNIQUEMENT par un tableau JSON, sans texte autour :
[{"number": "numéro exact de l'amendement", "concerned": true, "how": "une phrase : en quoi l'amendement la touche", "direction": "gain"|"perte"|"incertain", "quote": "extrait copié mot pour mot de CET amendement"}]
Règles :
- Sois prudent : aucun lien sans base textuelle dans l'amendement. Dans le doute, n'inclus pas l'amendement.
- N'inclus que les amendements qui la concernent ; tableau vide [] si aucun.
- N'invente aucun chiffre (montant, taux, nombre de salariés) qui ne figure pas dans l'amendement.
- direction = "incertain" si le sens dépend d'informations que tu n'as pas.
- quote doit être copiée mot pour mot depuis le dispositif ou l'objet de l'amendement cité, courte (une phrase au plus)."""

EMPLOYER_THEMES = {"Maintien pendant les congés familiaux", "Négociation syndicale avant mise en place",
                   "Durée de validité des titres"}  # legacy n°142 only; pipeline criteria carry roles
SCAN_STOP = {"commerce", "detail", "produits", "magasin", "magasins", "specialise", "specialises", "autres",
             "activites", "activite", "services", "service", "fabrication", "industrie", "industries",
             "entretien", "location", "conseil", "gestion", "travaux", "articles", "general", "generale",
             "divers", "diverses", "classes", "ailleurs", "principalement", "dominante", "personnes"}
NO_STAFF = {"", "NN", "00"}


def fold(s):
    s = unicodedata.normalize("NFD", (s or "").lower())
    return "".join(ch for ch in s if unicodedata.category(ch) != "Mn")


def company_prompt(company, pending):
    c = company
    head = (f"Entreprise : {c.get('name') or '?'} (SIREN {c.get('siren') or '?'})\n"
            f"Activité principale : {c.get('naf') or '?'} {c.get('naf_label') or ''}\n"
            f"Tranche d'effectif INSEE : {c.get('headcount_band') or 'inconnue'}\n"
            f"Rôles déclarés : {', '.join(c.get('roles') or []) or 'aucun'}\n\n"
            f"{len(pending)} amendements :\n")
    return head + "\n\n".join(f"### n°{a['number']} ({a['article']})\nDispositif : {a['text'][:1500]}\n"
                              f"Objet : {a['purpose'][:700]}" for a in pending)


def sentence_with(text, word):
    for s in re.split(r"(?<=[.;!?])\s+", text):
        if re.search(rf"\b{word}s?\b", fold(s)):
            if len(s) > 250:
                cut = s[:250]
                s = cut[:cut.rfind(" ")] if " " in cut else cut
            return s.strip()
    return None


def is_employer_measure(k):
    roles = [str(r).lower() for r in (k["criteria"].get("roles") or [])]
    return "employeurs" in roles or k["theme"] in EMPLOYER_THEMES


def mock_scan(known, company, pending):
    words = sorted({w for w in re.findall(r"[a-z]{5,}", fold(company.get("naf_label"))) if w not in SCAN_STOP})
    items = []
    for a in pending:
        hit = next(((w, q) for w in words for f in ("text", "purpose") if (q := sentence_with(a[f], w))), None)
        if hit:
            items.append({"number": a["number"], "concerned": True, "direction": "incertain", "quote": hit[1],
                          "how": f"Le mot « {hit[0]} » de l'activité ({company.get('naf_label')}) figure dans l'amendement."})
    if (company.get("headcount_band") or "") not in NO_STAFF:
        for a in pending:
            k = known.get(a["number"])
            if k and is_employer_measure(k) and not any(i["number"] == a["number"] for i in items):
                items.append({"number": a["number"], "concerned": True, "direction": "incertain",
                              "how": f"Mesure employeur ({k['theme']}) : la concerne si elle distribue des titres-restaurant à ses salariés.",
                              "quote": k["criteria"].get("quote", "")})
    return words, items


def finalize_scan(known, pending, items):
    by_num = {a["number"].strip().lower(): a for a in pending}
    by_base = {a["number"].strip().lower().split(" ")[0]: a for a in pending}
    matches, dropped, seen = [], [], set()
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        raw = re.sub(r"^n°\s*", "", str(it.get("number", "")).strip().lower())
        a = by_num.get(raw) or by_base.get(raw.split(" ")[0])
        if not it.get("concerned", True):
            dropped.append({"number": it.get("number"), "reason": "non concerné"})
            continue
        if not a:
            dropped.append({"number": it.get("number"), "reason": "amendement absent des amendements en attente"})
            continue
        if a["number"] in seen:
            continue
        verified, exact = verify_quote(it.get("quote") or "", a)
        if not verified:
            dropped.append({"number": a["number"], "reason": "citation introuvable dans l'amendement",
                            "quote": it.get("quote")})
            continue
        seen.add(a["number"])
        k = known.get(a["number"])
        direction = it.get("direction") if it.get("direction") in ("gain", "perte", "incertain") else "incertain"
        matches.append({
            "number": a["number"], "how": it.get("how") or "", "direction": direction,
            "quote": it.get("quote"), "quote_verified": True, "quote_exact": exact,
            "author": a["author"], "author_group": a["author_group"], "article": a["article"],
            "filed": a["filed"], "url": a["url"], "known": bool(k), "theme": k["theme"] if k else None,
        })
    return matches, dropped


def run_scan(session, texte, company, on_event=None):
    cfg = config()
    rows, _ = live_rows(session, texte)
    pending = pending_of(rows)
    known = known_index(session, texte)
    label = "mock (recherche par mots-clés)" if cfg["mock"] else cfg["model"]
    if on_event:
        on_event("start", {"n_amendments": len(pending), "model": label, "session": session, "text": texte})
    t0 = time.time()
    cached = False
    if cfg["mock"]:
        words, items = mock_scan(known, company, pending)
        mock_stream(f"Mode mock : pas de LLM. Je cherche les mots de l'activité « {company.get('naf_label') or '?'} » "
                    f"({', '.join(words) or 'aucun mot significatif'}) dans chaque amendement, puis j'ajoute les "
                    f"mesures employeurs si l'entreprise a des salariés.", on_event, kind="reasoning", step=6)
        mock_stream(json.dumps(items, ensure_ascii=False, indent=2), on_event, step=8, delay=0.006)
    else:
        items, _, cached = ask(SCAN_SYSTEM, company_prompt(company, pending), SCAN_TOKENS, on_event)
        if isinstance(items, dict):
            items = items.get("matches") or items.get("amendements") or []
    matches, dropped = finalize_scan(known, pending, items)
    return {"company": company, "session": session, "text": texte, "n_amendments": len(pending),
            "matches": matches, "dropped": len(dropped), "dropped_detail": dropped, "model": label,
            "cached": cached, "elapsed_ms": int((time.time() - t0) * 1000)}


# ---------- HTTP ----------

NO_KEY = {"error": "Clé LLM manquante : ajoutez LLM_API_KEY dans .env"}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT), **kw)

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.log_date_time_string(), fmt % args))

    def end_headers(self):
        if self.path.startswith("/api/"):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Private-Network", "true")
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

    def sse_open(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        def send(event, data):
            self.wfile.write(f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode())
            self.wfile.flush()
        return send

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def blocked(self, path):
        return any(part.startswith(".") for part in urllib.parse.unquote(path).split("/") if part)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(u.query)
        q = lambda k, d="": (qs.get(k) or [d])[0]
        if u.path == "/api/live/health":
            cfg = config()
            return self.json(200, {"llm_configured": bool(cfg["key"]), "mock": cfg["mock"],
                                   "model": cfg["model"], "base_url": cfg["base_url"],
                                   "pipeline": (ROOT / "pipeline.py").exists()})
        m = re.match(r"^/api/text/([^/]+)/([^/]+)(/status)?/?$", u.path)
        if m:
            session, texte, status = m.groups()
            if not valid(session, texte):
                return self.json(400, {"error": "session au format 2026-2027 et texte numérique"})
            if status:
                return self.json(200, run_status(session, texte))
            engine = text_dir(session, texte) / "engine.json"
            if q("refresh") in ("", "0") and not engine.exists():
                return self.json(404, {"status": "absent", "error": f"data/{session}/{texte}/engine.json absent",
                                       "hint": f"/api/text/{session}/{texte}?refresh=1 lance pipeline.py"})
            if q("refresh") not in ("", "0"):
                run, started = start_pipeline(session, texte)
                if run["status"] == "error" and not started:
                    return self.json(501 if run["error"] == "pipeline.py absent" else 500,
                                     {"status": "error", "error": run["error"]})
                return self.json(202, {"status": "running", "started": started,
                                       "status_url": f"/api/text/{session}/{texte}/status"})
            return self.json(200, json.loads(engine.read_text()))
        if u.path == "/api/live/amendments":
            session, texte = q("session", DEFAULT_SESSION), q("text", DEFAULT_TEXT)
            if not valid(session, texte):
                return self.json(400, {"error": "session au format 2026-2027 et text numérique"})
            try:
                return self.json(200, pending_amendments(session, texte))
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
        if u.path not in ("/api/live/extract", "/api/live/scan"):
            return self.json(404, {"error": "endpoint inconnu"})
        qs = urllib.parse.parse_qs(u.query)
        stream = (qs.get("stream") or ["0"])[0] not in ("0", "")
        try:
            req = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except ValueError:
            return self.json(400, {"error": "corps JSON invalide"})
        cfg = config()
        if not cfg["mock"] and not cfg["key"]:
            return self.json(503, NO_KEY)

        session = str(req.get("session") or (qs.get("session") or [DEFAULT_SESSION])[0])
        txt = req.get("text")
        texte = str(req.get("text_number") or req.get("texte") or (txt if str(txt or "").isdigit() else "")
                    or (qs.get("text") or [DEFAULT_TEXT])[0])
        if not valid(session, texte):
            return self.json(400, {"error": "session au format 2026-2027 et text_number numérique"})
        if u.path == "/api/live/scan":
            return self.scan(session, texte, req, stream)

        if req.get("number"):
            try:
                amendment = find_amendment(session, texte, str(req["number"]))
            except Exception as e:
                return self.json(502, {"error": f"Sénat injoignable : {e}"})
            if not amendment:
                return self.json(404, {"error": f"Amendement n°{req['number']} introuvable sur le texte {session}/{texte}"})
        else:
            dispositif = req.get("dispositif") or ("" if str(txt or "").isdigit() else txt) or ""
            objet = req.get("objet") or req.get("purpose") or ""
            if not (dispositif or objet):
                return self.json(400, {"error": "Donnez {session, text_number, number} ou {dispositif, objet}"})
            amendment = {"number": "", "article": req.get("article", ""), "author": "",
                         "author_group": req.get("author_group", ""), "url": "",
                         "text": clean(dispositif), "purpose": clean(objet)}

        if not stream:
            try:
                return self.json(200, as_measure(session, texte, amendment, *run_extraction(session, texte, amendment)))
            except LLMError as e:
                return self.json(503 if str(e) == "NO_KEY" else 502, NO_KEY if str(e) == "NO_KEY" else {"error": str(e)})
            except Exception as e:
                return self.json(502, {"error": f"Extraction impossible : {e}"})
        send = self.sse_open()
        try:
            send("start", {"number": amendment["number"], "author": amendment["author"],
                           "author_group": amendment["author_group"], "url": amendment["url"],
                           "session": session, "text": texte, "model": "mock" if cfg["mock"] else cfg["model"]})
            res = run_extraction(session, texte, amendment, on_event=send)
            send("status", {"t": "Comptage des entreprises (API Recherche d'entreprises)…"})
            send("result", as_measure(session, texte, amendment, *res))
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as e:
            try:
                send("error", {"error": str(e)})
            except OSError:
                pass

    def scan(self, session, texte, req, stream):
        company = req.get("company")
        if not isinstance(company, dict) or not (company.get("naf") or company.get("naf_label") or company.get("name")):
            return self.json(400, {"error": "Donnez company {name, siren, naf, naf_label, headcount_band, roles}"})
        company = {k: company.get(k) for k in ("name", "siren", "naf", "naf_label", "headcount_band", "roles")}
        if not stream:
            try:
                return self.json(200, run_scan(session, texte, company))
            except LLMError as e:
                return self.json(502, {"error": str(e)})
            except Exception as e:
                return self.json(502, {"error": f"Analyse impossible : {e}"})
        send = self.sse_open()
        try:
            send("result", run_scan(session, texte, company, on_event=send))
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
    print(f"http://localhost:{PORT}  ·  LLM {cfg['model']} ({state})  ·  dossier {ROOT}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
