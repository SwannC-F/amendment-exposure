"""Count exposed companies and an employee range per NAF code, then per amendment.

Usage: python3 exposure.py 142
Reads data/criteria_<n>.json, writes data/exposure_<n>.json.
Source: API Recherche d'entreprises (active legal units, by main activity and
INSEE headcount band). Counts are cached in data/raw/counts.json.

Employee figures are a RANGE: each company only has a headcount band
(e.g. 20-49), so we sum the band bounds. The headcount is the whole company's,
not only the staff working in that activity.
"""
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

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

CACHE = Path("data/raw/counts.json")


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


def naf_exposure(naf, cache):
    companies, low, high, open_top = 0, 0, 0, False
    for band, (lo, hi) in BANDS.items():
        n = count(naf, band, cache)
        companies += n
        low += n * lo
        high += n * (hi if hi is not None else lo)
        open_top |= hi is None and n > 0
    return {"companies": companies, "employees_low": low, "employees_high": high, "open_top": open_top}


def main(n):
    criteria = json.loads(Path(f"data/criteria_{n}.json").read_text())
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}

    nafs = sorted({s["naf"] for c in criteria for s in c["criteria"]["sectors"] if s["naf"]})
    by_naf = {}
    for naf in nafs:
        by_naf[naf] = naf_exposure(naf, cache)
        e = by_naf[naf]
        print(f"{naf}: {e['companies']:>8,} entreprises, {e['employees_low']:>10,}–{e['employees_high']:,} employés")

    out = []
    for c in criteria:
        sectors = c["criteria"]["sectors"]
        counted = [s for s in sectors if s["naf"]]
        tot = {"companies": 0, "employees_low": 0, "employees_high": 0, "open_top": False}
        for s in counted:
            e = by_naf[s["naf"]]
            for k in ("companies", "employees_low", "employees_high"):
                tot[k] += e[k]
            tot["open_top"] |= e["open_top"]
        out.append({"number": c["number"],
                    "sectors": [{**s, **by_naf.get(s["naf"], {})} for s in sectors],
                    **tot,
                    "not_counted": [s["label"] for s in sectors if not s["naf"]]})

    Path(f"data/exposure_{n}.json").write_text(json.dumps(
        {"source": "API Recherche d'entreprises (unités légales actives, activité principale × tranche d'effectifs)",
         "by_naf": by_naf, "amendments": out}, ensure_ascii=False, indent=2))
    print(f"\n{len(out)} amendments -> data/exposure_{n}.json")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "142")
