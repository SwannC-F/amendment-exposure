"""Count exposed companies and an employee range per NAF code, then per amendment.

Usage: python3 exposure.py <session> <texte>
Reads data/<session>/<texte>/criteria.json and measures.json, writes exposure.json there
(per NAF, per measure, per amendment).
Source: API Recherche d'entreprises (active legal units, by main activity and
INSEE headcount band). Counts are cached in data/raw/counts.json.

Employee figures are a RANGE: each company only has a headcount band
(e.g. 20-49), so we sum the band bounds. The headcount is the whole company's,
not only the staff working in that activity.
"""
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from fetch_amendments import text_dir

API = "https://recherche-entreprises.api.gouv.fr/search"
UA = "amendment-exposure/0.1 (hackathon prototype)"
CAP = 10000  # the API never reports more than this

# INSEE headcount bands -> (low, high). 53 has no upper bound.
BANDS = {"NN": (0, 0), "00": (0, 0), "01": (1, 2), "02": (3, 5), "03": (6, 9),
         "11": (10, 19), "12": (20, 49), "21": (50, 99), "22": (100, 199),
         "31": (200, 249), "32": (250, 499), "41": (500, 999), "42": (1000, 1999),
         "51": (2000, 4999), "52": (5000, 9999), "53": (10000, None)}

DEPARTEMENTS = ([f"{i:02d}" for i in range(1, 20)] + ["2A", "2B"]
                + [f"{i:02d}" for i in range(21, 96)]
                + ["971", "972", "973", "974", "976"])

CACHE = Path("data/raw/counts.json")  # shared across texts
NAF_RE = re.compile(r"^\d{2}\.\d{1,2}[A-Z]?$")


def total(params):
    q = urllib.parse.urlencode({**params, "etat_administratif": "A", "per_page": 1, "minimal": "true"})
    req = urllib.request.Request(f"{API}?{q}", headers={"User-Agent": UA})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                time.sleep(0.15)  # stay under the 7 requests/second limit
                return json.load(r)["total_results"]
        except Exception:
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"API failed for {params}")


def count(naf, band, cache):
    key = f"{naf}|{band}"
    if key not in cache:
        n = total({"activite_principale": naf, "tranche_effectif_salarie": band})
        if n >= CAP:  # capped: split by département
            parts = [total({"activite_principale": naf, "tranche_effectif_salarie": band,
                            "departement": d}) for d in DEPARTEMENTS]
            if max(parts) >= CAP:
                print(f"  warning: {naf}/{band} still capped in one département, count is a floor")
            n = sum(parts)
        cache[key] = n
        CACHE.write_text(json.dumps(cache, indent=1))
    return cache[key]


NAF_CODES = Path("data/raw/naf_codes.json")


def valid_codes():
    """The API's own list of valid NAF sub-classes (it returns it on an invalid code), cached."""
    if NAF_CODES.exists():
        return json.loads(NAF_CODES.read_text())
    q = urllib.parse.urlencode({"activite_principale": "00.00", "per_page": 1})
    req = urllib.request.Request(f"{API}?{q}", headers={"User-Agent": UA})
    try:
        urllib.request.urlopen(req, timeout=60)
        body = ""
    except urllib.error.HTTPError as e:
        body = e.read().decode()
    codes = sorted(set(re.findall(r"'(\d{2}\.\d{2}[A-Z])'", body)))
    if codes:
        NAF_CODES.write_text(json.dumps(codes))
    return codes


def expand(naf, codes):
    """A sub-class stays itself; a class or group (e.g. 56.10, 56.1) becomes its sub-classes."""
    if naf in codes:
        return [naf]
    return [c for c in codes if c.startswith(naf)] if len(naf) >= 4 else []


def naf_exposure(naf, cache):
    companies, low, high, open_top = 0, 0, 0, False
    for band, (lo, hi) in BANDS.items():
        n = count(naf, band, cache)
        companies += n
        low += n * lo
        high += n * (hi if hi is not None else lo)
        open_top |= hi is None and n > 0
    return {"companies": companies, "employees_low": low, "employees_high": high, "open_top": open_top}


def add(tot, e):
    for k in ("companies", "employees_low", "employees_high"):
        tot[k] += e[k]
    tot["open_top"] |= e["open_top"]


def summarise(sectors, by_naf, by_sub):
    """Sum over distinct NAF sub-classes (56.10 and 56.10A listed together count 56.10A once)."""
    tot = {"companies": 0, "employees_low": 0, "employees_high": 0, "open_top": False}
    subs = {c for s in sectors if s["naf"] in by_naf for c in by_naf[s["naf"]].get("subclasses", [s["naf"]])}
    for c in sorted(subs):
        add(tot, by_sub[c])
    return {**tot, "not_counted": sorted({s["label"] for s in sectors if s["naf"] not in by_naf})}


def main(session, n):
    d = text_dir(session, n)
    criteria = {c["number"]: c for c in json.loads((d / "criteria.json").read_text())}
    measures = json.loads((d / "measures.json").read_text())
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}

    nafs = sorted({s["naf"] for c in criteria.values() if c.get("criteria_found")
                   for s in c["sectors"] if s["naf"]})
    codes = valid_codes()
    by_naf, by_sub = {}, {}
    for naf in nafs:
        subs = expand(naf, codes) if NAF_RE.match(naf) else []
        if not subs:
            print(f"{naf}: code NAF non reconnu, non compté")
            continue
        for c in subs:
            by_sub.setdefault(c, naf_exposure(c, cache))
        parts = [by_sub[c] for c in subs]
        by_naf[naf] = {k: sum(p[k] for p in parts) for k in ("companies", "employees_low", "employees_high")}
        by_naf[naf]["open_top"] = any(p["open_top"] for p in parts)
        if subs != [naf]:
            by_naf[naf]["subclasses"] = subs
        e = by_naf[naf]
        print(f"{naf}: {e['companies']:>8,} entreprises, {e['employees_low']:>10,}–{e['employees_high']:,} employés")

    out_a = []
    for c in criteria.values():
        if not c.get("criteria_found"):
            continue
        out_a.append({"number": c["number"],
                      "sectors": [{**s, **by_naf.get(s["naf"], {})} for s in c["sectors"]],
                      **summarise(c["sectors"], by_naf, by_sub)})

    out_m = []
    for m in measures:
        sectors, seen = [], set()
        for a in m["amendments"]:
            for s in criteria[a]["sectors"]:
                k = s["naf"] or s["label"]
                if k not in seen:
                    seen.add(k)
                    sectors.append({**s, **by_naf.get(s["naf"], {})})
        roles = sorted({r for a in m["amendments"] for r in criteria[a].get("roles", [])})
        out_m.append({"key": m["key"], "theme": m["theme"], "sectors": sectors, "roles": roles,
                      **summarise(sectors, by_naf, by_sub)})

    (d / "exposure.json").write_text(json.dumps(
        {"source": "API Recherche d'entreprises (unités légales actives, activité principale × tranche d'effectifs)",
         "by_naf": by_naf, "measures": out_m, "amendments": out_a}, ensure_ascii=False, indent=2))
    print(f"\n{len(out_m)} mesures, {len(out_a)} amendements -> {d / 'exposure.json'}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit("usage: python3 exposure.py <session> <texte>")
    main(sys.argv[1], sys.argv[2])
