"""Chiffrage of every measure of a Sénat text, with one generic formula.

Usage: python3 chiffrage.py <session> <texte>        e.g. python3 chiffrage.py 2026-2027 142

Reads  data/<session>/<texte>/{measures,amendments,criteria}.json
Writes data/<session>/<texte>/chiffrage.json   ({key: chiffrage} for every measure)

One LLM call per measure: it reads the full dispositif + objet of the measure's amendments and
returns the mechanism, winners, losers and three kinds of parameters, each with a verbatim quote:
  base   = annual € flow concerned (e.g. value of titres issued per year)
  delta  = the change, as a share of that flow (commission 4–5 % → cap 2,5 % gives 0,015–0,025)
  shares = part of a sector's revenue paid through the flow (« 15 % du chiffre d'affaires »)
Then the CODE, not the LLM, checks each parameter: the change (delta) must be quoted from the
dispositif of one of the measure's amendments; every quote must appear verbatim in an amendment
of the measure, and the figures must be found in the quote (directly or as a difference/product of
quoted figures). A parameter that fails is dropped with its reason. Formula:
  total = base × delta (range) ; per-sector rate = share × delta ; € for a company = CA × rate.
Missing base or delta → total null and `not_computable` gives the reason.

Two opposed measures (`opposes`): the first one is computed with both measures' texts in the
prompt, and the LLM says whether the opposite measure is its exact reverse (same flow, same change,
opposite direction). Only then is the opposite mirrored (winners/losers swapped); otherwise it gets
its own call.
"""
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from llm import chat_json, model_name, normalize, verify_quote

DATA = Path(os.environ.get("PIPELINE_DATA", "data"))
ROLES = ["employeurs", "emetteurs", "plateformes", "associations", "collectivites", "etat", "menages"]
MAX_CHARS = 12000  # per amendment, dispositif + objet

SYSTEM = f"""Tu es analyste économique au Sénat. On te donne une mesure (un groupe d'amendements déposés sur un texte)
avec le texte intégral de chaque amendement (dispositif et objet) et les critères déjà extraits.
Tu décris le transfert d'argent que la mesure provoque et tu en extrais les paramètres chiffrés.

Formule unique : transfert annuel total = assiette × écart ; pour une entreprise d'un secteur, € = CA × part × écart.
- base (assiette) : le flux annuel en euros concerné par la mesure (par ex. la valeur des titres émis par an).
- delta (écart) : la variation que la mesure impose, exprimée en part de l'assiette (nombre entre 0 et 1).
  Exemple : commission actuelle de 4 à 5 % plafonnée à 2,5 % → delta low 0.015, high 0.025.
  C'est l'écart entre la situation actuelle et la situation APRÈS la mesure, pas une évolution passée constatée.
  La nouvelle règle est écrite dans le DISPOSITIF d'un amendement de la mesure : la citation de delta doit inclure ce passage
  du dispositif (et, si besoin, après « | », le passage qui donne la situation actuelle).
  Si la mesure fait changer de mains la totalité du flux (par ex. la valeur des titres périmés reversée à quelqu'un
  d'autre), delta low = high = 1 et la citation est celle qui décrit ce flux.
- shares : pour chaque secteur concerné, la part de son chiffre d'affaires qui passe par ce flux
  (par ex. « le titre représente 15 % du chiffre d'affaires des restaurants » → low 0.15, high 0.15).

Règles strictes :
1. Prends les chiffres UNIQUEMENT dans les textes d'amendements fournis. Aucune connaissance extérieure, aucune estimation.
2. Les chiffres viennent d'abord des amendements de la mesure ; les passages chiffrés des autres amendements du texte
   peuvent servir pour l'assiette ou la part d'un secteur. Chaque paramètre porte une citation copiée mot pour mot (caractère pour caractère) dans un seul amendement,
   et le numéro de cet amendement. Si un paramètre combine plusieurs passages, sépare les citations par « | ».
   La citation doit contenir les chiffres utilisés.
3. Donne des fourchettes (low ≤ high). Si le texte donne un seul chiffre, low = high.
4. Si un paramètre n'est pas dans les textes, mets-le à null. Ne devine jamais. S'il manque l'assiette ou l'écart,
   explique en une phrase dans not_computable ce qui manque.
5. Gagnants et perdants : secteurs par code NAF (format 56.10A) quand il existe, sinon un rôle parmi {", ".join(ROLES)}.
6. N'emploie jamais le mot « impact ». Phrases courtes, en français.

Réponds en JSON seulement :
{{"mechanism": "une ou deux phrases : qui paie quoi à qui, et ce que la mesure change",
  "winners": [{{"naf": "56.10A" | null, "role": "<rôle>" | null, "label": "libellé"}}],
  "losers":  [{{"naf": ... , "role": ..., "label": ...}}],
  "base":  {{"name": "...", "low": nombre, "high": nombre, "unit": "€/an", "quote": "...", "amendment": "n°"}} | null,
  "delta": {{"name": "...", "low": nombre, "high": nombre, "unit": "part", "quote": "...", "amendment": "n°"}} | null,
  "shares": [{{"nafs": ["56.10A", ...], "role": "<rôle>" | null, "low": nombre, "high": nombre, "quote": "...", "amendment": "n°"}}],
  "not_computable": "raison" | null}}"""

OPPOSITE = """
Une mesure contraire existe sur le même texte (amendements ci-dessous, sous « MESURE CONTRAIRE »). Ajoute à ta réponse :
  "opposite_is_mirror": true seulement si cette mesure contraire porte sur le même flux et inverse exactement le même
     changement (même assiette, même écart, sens opposé) d'après les textes ; sinon false,
  "opposite_reason": "une phrase qui justifie",
  "opposite_mechanism": "le mécanisme de la mesure contraire, une ou deux phrases" """


# ---------- inputs ----------

def load(d, name, default=None):
    p = d / name
    if not p.exists():
        if default is not None:
            return default
        sys.exit(f"manque {p}")
    return json.loads(p.read_text())


def amendment_texts(a):
    """(dispositif, objet) whatever the field names of amendments.json."""
    disp = a.get("dispositif") or a.get("text") or ""
    obj = a.get("objet") or a.get("purpose") or ""
    return disp, obj


def criteria_of(c):
    """criteria.json rows are either flat or {number, criteria: {...}}."""
    return c.get("criteria") if isinstance(c.get("criteria"), dict) else c


def render_amendments(numbers, amendments, criteria):
    out = []
    for n in numbers:
        a = amendments.get(n)
        if not a:
            continue
        disp, obj = amendment_texts(a)
        cr = criteria_of(criteria.get(n, {}))
        crit = {k: cr.get(k) for k in ("effect", "who", "sectors", "roles") if cr.get(k)}
        out.append(f"### Amendement n°{n} ({a.get('author_group') or a.get('groupe') or ''})\n"
                   f"Critères extraits : {json.dumps(crit, ensure_ascii=False)}\n"
                   f"DISPOSITIF : {disp[:MAX_CHARS]}\nOBJET : {obj[:MAX_CHARS]}")
    return "\n\n".join(out)


_FIGURE = re.compile(r"\d[\d  .\u202f]*(?:,\d+)?\s*(?:%|€|euros?|milliards?|millions?)", re.I)


def figure_passages(exclude, amendments):
    """Sentences with a figure (%, €, millions…) from the text's other amendments, chosen by code."""
    out = []
    for n, a in amendments.items():
        if n in exclude:
            continue
        for part in amendment_texts(a):
            for sent in re.split(r"(?<=[.;!?])\s+", part or ""):
                if _FIGURE.search(sent) and len(sent) < 600:
                    out.append(f"[n°{n}] {sent.strip()}")
    return "\n".join(dict.fromkeys(out))


# ---------- checks (code, not LLM) ----------

_NUM = re.compile(r"(\d{1,3}(?:[  . ]\d{3})+|\d+)(?:,(\d+))?\s*(milliards?|millions?|md|m€|k€|%|pour\s*cent)?",
                  re.I)
_SCALE = {"milliard": 1e9, "milliards": 1e9, "md": 1e9, "million": 1e6, "millions": 1e6, "m€": 1e6, "k€": 1e3}


def quoted_numbers(quote):
    """Every number of the quote, as written and with its unit applied (% → /100, milliards → ×1e9)."""
    vals = set()
    for m in _NUM.finditer(quote or ""):
        x = float(re.sub(r"[  . ]", "", m.group(1)) + ("." + m.group(2) if m.group(2) else ""))
        unit = (m.group(3) or "").lower().replace(" ", "")
        vals.add(x)
        if unit in ("%", "pourcent"):
            vals.add(x / 100)
        elif unit in _SCALE:
            vals.add(x * _SCALE[unit])
        if x <= 100:  # « 4 à 5 % »: the % only follows the last number
            vals.add(x / 100)
    return vals


def close(a, b):
    return abs(a - b) <= 0.011 * max(abs(a), abs(b), 1e-12)


def supported(value, nums, kind):
    """Is value a quoted figure, or for the change a difference of two quoted figures, or for the
    base a product of two quoted figures (e.g. 5 millions de salariés × 2 000 €)?"""
    if any(close(value, n) for n in nums):
        return True
    pairs = [(a, b) for a in nums for b in nums]
    if kind in ("delta", "share"):
        return any(close(value, abs(a - b)) for a, b in pairs if a != b)
    if kind == "base":
        return any(close(value, a * b) for a, b in pairs)
    return False


def check_param(p, kind, allowed, amendments, own=()):
    """Return (clean parameter, None) or (None, reason). The quote must be found verbatim in an
    amendment of the measure; its figures must give low and high."""
    if not isinstance(p, dict):
        return None, "absent"
    name = p.get("name") or kind
    try:
        low, high = float(p.get("low")), float(p.get("high"))
    except (TypeError, ValueError):
        return None, f"{name} : chiffres manquants"
    low, high = min(low, high), max(low, high)
    if low < 0 or (kind in ("delta", "share") and high > 1) or (kind == "base" and high <= 0):
        return None, f"{name} : valeur hors bornes ({low}–{high})"
    parts = [q.strip() for q in str(p.get("quote") or "").split("|") if q.strip()]
    if not parts:
        return None, f"{name} : pas de citation"
    found = []
    for q in parts:
        where = [n for n in allowed if verify_quote(q, *amendment_texts(amendments.get(n, {})))]
        if not where:
            return None, f"{name} : citation introuvable mot pour mot dans les amendements de la mesure (« {q[:80]} »)"
        found.append(where[0])
    nums = set().union(*(quoted_numbers(q) for q in parts))
    if kind == "delta":
        # The change is what the measure writes into the law: its figures must come from the parts of
        # the quote found in the DISPOSITIF of one of the measure's amendments. A difference is allowed
        # only if one of its two terms is such a figure (current rate from the objet − cap from the
        # dispositif); a past trend quoted in an objet (« passée de 46,5 % à 34,3 % ») is not a change.
        disp = [q for q in parts if any(verify_quote(q, amendment_texts(amendments.get(n, {}))[0]) for n in own)]
        if not disp:
            return None, (f"{name} : le changement n'est écrit dans le dispositif d'aucun amendement de la mesure "
                          f"(citation tirée de l'objet ou d'un autre amendement)")
        disp_nums = set().union(*(quoted_numbers(q) for q in disp))
        for v in {low, high}:
            if v == 1:
                continue  # the whole flow changes hands: a mechanism, not a figure (base still needs its quote)
            if not (any(close(v, d) for d in disp_nums)
                    or any(close(v, abs(a - d)) for d in disp_nums for a in nums if a != d)):
                return None, f"{name} : le chiffre {v:g} ne vient pas du dispositif d'un amendement de la mesure"
    else:
        for v in {low, high}:
            if not supported(v, nums, kind):
                return None, f"{name} : le chiffre {v:g} ne se retrouve pas dans la citation"
    clean = {"name": name, "low": low, "high": high,
             "unit": {"base": "€/an", "delta": "part", "share": "part"}[kind],
             "quote": " | ".join(parts), "amendment": " | ".join(dict.fromkeys(found))}
    if kind == "share":
        clean = {"nafs": [n for n in p.get("nafs") or [] if n], "role": p.get("role"), **clean}
    return clean, None


def clean_party(x):
    if not isinstance(x, dict):
        return None
    role = (x.get("role") or "").strip().lower() or None
    if role and role not in ROLES and not role.startswith("autre:"):
        role = f"autre:{role}"
    return {"naf": (x.get("naf") or "").strip() or None, "role": role, "label": x.get("label") or x.get("naf") or role}


# ---------- one measure ----------

def compute(measure, answer, allowed, amendments, own):
    """Turn the LLM answer into the chiffrage.json entry, dropping every unverified parameter."""
    dropped = []
    base, why = check_param(answer.get("base"), "base", allowed, amendments, own)
    if why and why != "absent":
        dropped.append({"parameter": "base", "reason": why})
    delta, why = check_param(answer.get("delta"), "delta", allowed, amendments, own)
    if why and why != "absent":
        dropped.append({"parameter": "delta", "reason": why})
    shares = []
    for s in answer.get("shares") or []:
        ok, why = check_param(s, "share", allowed, amendments, own)
        if ok:
            shares.append(ok)
        else:
            dropped.append({"parameter": "share", "reason": why})

    total = None
    if base and delta:
        total = {"low": round(base["low"] * delta["low"]), "high": round(base["high"] * delta["high"])}
    reason = None
    if not total:
        missing = [n for n, v in (("assiette annuelle en €", base), ("écart", delta)) if not v]
        reason = (answer.get("not_computable") or "").strip()
        reason = f"Non chiffrable : {' et '.join(missing)} absent{'s' if len(missing) > 1 else ''} des amendements " \
                 f"ou citation non vérifiée." + (f" {reason}" if reason else "")
    rates = []
    # delta = 1: the whole flow (e.g. expired titres) changes hands; a sector's revenue paid in titres is
    # not that flow, so share × delta would mean nothing: total only, no per-sector rate.
    if delta and delta["high"] < 1:
        for s in shares:
            rates.append({"nafs": s["nafs"], "role": s["role"], "rate_low": s["low"] * delta["low"],
                          "rate_high": s["high"] * delta["high"],
                          "method": f"CA × {fmt_part(s)} ({s['name']}) × {fmt_part(delta)} ({delta['name']})",
                          "quote": f"{s['quote']} | {delta['quote']}"})
    return {"key": measure["key"], "theme": measure.get("theme"),
            "mechanism": answer.get("mechanism"),
            "winners": [p for p in map(clean_party, answer.get("winners") or []) if p],
            "losers": [p for p in map(clean_party, answer.get("losers") or []) if p],
            "base": base, "delta": delta, "shares": shares, "rates": rates,
            "total_eur_per_year": total, "not_computable": reason, "dropped": dropped,
            "mirror_of": None, "model": model_name()}


def fmt_part(p):
    lo, hi = p["low"] * 100, p["high"] * 100
    return f"{lo:.3g} %" if lo == hi else f"{lo:.3g} à {hi:.3g} %"


def mirror(entry, measure, answer):
    m = dict(entry, key=measure["key"], theme=measure.get("theme"), winners=entry["losers"],
             losers=entry["winners"], mirror_of=entry["key"],
             mechanism=answer.get("opposite_mechanism") or f"Inverse de « {entry['theme']} ».",
             mirror_reason=answer.get("opposite_reason"))
    return m


def one(m, opp, session, texte, amendments, criteria):
    """One LLM call for measure m (with its opposite measure's texts if opp). Returns (entry, answer)."""
    nums = [str(n) for n in m["amendments"]]
    chamber = "Assemblée nationale, législature " + session.split("/")[-1] if session.startswith("an/") else "Sénat " + session
    user = f"Texte : {chamber} n°{texte}\nMESURE : {m.get('theme')}\n\n" + \
        render_amendments(nums, amendments, criteria)
    system, allowed = SYSTEM, nums
    if opp:
        opp_nums = [str(n) for n in opp["amendments"]]
        user += f"\n\n=== MESURE CONTRAIRE : {opp.get('theme')} ===\n\n" + \
            render_amendments(opp_nums, amendments, criteria)
        system += OPPOSITE
        allowed = nums + opp_nums
    own = list(allowed)  # the measure's (and opposite measure's) amendments: the change must be in their dispositif
    others = figure_passages(set(allowed), amendments)
    if others:
        user += ("\n\n=== PASSAGES CHIFFRÉS DES AUTRES AMENDEMENTS DU MÊME TEXTE ===\n"
                 "(utilisables seulement pour une part de secteur ou une assiette, en citant leur numéro)\n" + others)
        allowed = allowed + [n for n in amendments if n not in allowed]
    print(f"… {m['key']} ({len(nums)} amend.)", flush=True)
    try:
        answer = chat_json(system, user, max_tokens=8000)
    except Exception as e:
        return {"key": m["key"], "theme": m.get("theme"), "mechanism": None, "winners": [], "losers": [],
                "base": None, "delta": None, "shares": [], "rates": [], "total_eur_per_year": None,
                "dropped": [], "mirror_of": None, "error": str(e),
                "not_computable": f"Non chiffrable : échec de l'appel au modèle ({e})"}, {}
    answer = answer if isinstance(answer, dict) else {}
    return compute(m, answer, allowed, amendments, own), answer


def run(session, texte, workers=4):
    d = DATA / session / texte
    measures = load(d, "measures.json")
    amendments = {str(a["number"]): a for a in load(d, "amendments.json")}
    criteria = {str(c["number"]): c for c in load(d, "criteria.json")}
    by_key = {m["key"]: m for m in measures}

    # Round 1: every measure, except the second of an opposed pair, which waits for the mirror verdict.
    first, partner_of = [], {}
    for m in measures:
        opp = by_key.get(m.get("opposes") or "")
        if m["key"] in partner_of.values():
            continue  # m is the second of a pair
        if opp:
            partner_of[m["key"]] = opp["key"]
        first.append((m, opp))
    out = {}
    with ThreadPoolExecutor(workers) as pool:
        results = list(pool.map(lambda x: one(x[0], x[1], session, texte, amendments, criteria), first))
    second = []
    for (m, opp), (entry, answer) in zip(first, results):
        out[m["key"]] = entry
        if opp:
            if answer.get("opposite_is_mirror") is True and not entry.get("mirror_of"):
                out[opp["key"]] = mirror(entry, opp, answer)
            else:
                second.append(opp)  # not the exact reverse: computed on its own
    # Round 2: opposite measures the texts do not let us mirror.
    with ThreadPoolExecutor(workers) as pool:
        for opp, (entry, _) in zip(second, pool.map(
                lambda o: one(o, None, session, texte, amendments, criteria), second)):
            out[opp["key"]] = entry
    out = {m["key"]: out[m["key"]] for m in measures if m["key"] in out}
    (d / "chiffrage.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"{len(out)} mesures -> {d / 'chiffrage.json'}")
    report(out)
    failed = [k for k, c in out.items() if c.get("error")]
    if failed:  # those measures are marked not computable; the pipeline goes on (rerun to retry, cache kept)
        print(f"\n⚠ {len(failed)} appel(s) au modèle en échec : {', '.join(failed)} — relancer pour réessayer")
    return out


def eur(x):
    return f"{x / 1e6:,.1f} M€".replace(",", " ")


def report(out):
    for k, c in out.items():
        t = c["total_eur_per_year"]
        head = f"{eur(t['low'])} – {eur(t['high'])} /an" if t else "non chiffrable"
        print(f"\n■ {k} : {head}" + (f"  (miroir de {c['mirror_of']})" if c.get("mirror_of") else ""))
        for n in ("base", "delta"):
            p = c.get(n)
            if p:
                print(f"   ✓ {n:5} {p['low']:g}–{p['high']:g} {p['unit']}  n°{p['amendment']} « {p['quote'][:90]} »")
        for s in c.get("shares", []):
            print(f"   ✓ part  {s['low']:g}–{s['high']:g} {s['nafs'] or s['role']}  n°{s['amendment']} « {s['quote'][:70]} »")
        for x in c.get("dropped", []):
            print(f"   ✗ {x['parameter']:5} {x['reason'][:150]}")
        if not t and c.get("not_computable"):
            print(f"   → {c['not_computable'][:200]}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    run(sys.argv[1], sys.argv[2])
