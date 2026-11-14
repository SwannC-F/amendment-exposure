"""Investor angle: regulatory exposure for due diligence + event study on listed issuers.

Stdlib only. Writes data/investors.json.

Part 1  For each profile in data/profiles.json, sum the per-company € ranges of the
        pending measures (data/feed_142.json, card.chiffrage.you) and divide by the
        company's latest revenue / net result (API Recherche d'entreprises).
Part 2  Market-adjusted event study on Edenred (EDEN) and Pluxee (PLX) vs CAC 40,
        daily closes from Euronext's public historical download (last 2 years only).

Raw downloads are cached under data/raw/prices/ and data/raw/investors/ (git-ignored).
"""
import csv
import http.client
import io
import json
import math
import os
import statistics
import time
import urllib.request
from datetime import date, datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
RAW_PRICES = os.path.join(DATA, "raw", "prices")
RAW_FIN = os.path.join(DATA, "raw", "investors")
UA = "amendment-exposure/0.1 (hackathon prototype)"

# ---------------------------------------------------------------- helpers

def get(url, cache, ua=UA):
    if os.path.exists(cache):
        with open(cache, encoding="utf-8") as f:
            return f.read()
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    with urllib.request.urlopen(req, timeout=60) as r:
        try:
            raw = r.read()
        except http.client.IncompleteRead as e:  # Euronext closes chunked responses early
            raw = e.partial
        body = raw.decode("utf-8-sig")
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    with open(cache, "w", encoding="utf-8") as f:
        f.write(body)
    time.sleep(0.3)
    return body


def pct(x, base):
    return round(100.0 * x / base, 2)


# ---------------------------------------------------------------- part 1

FIN_URL = "https://recherche-entreprises.api.gouv.fr/search?q={}&per_page=1"

# Opposite measures on the same mechanism: at most one can be adopted, so they are
# counted once in the totals (envelope of their ranges), never added.
EXCLUSIVE = [{"Supprimer le double plafond journalier", "Rendre effectif le double plafond journalier"}]


def finances(siren):
    body = get(FIN_URL.format(siren), os.path.join(RAW_FIN, f"finances_{siren}.json"))
    res = json.loads(body)["results"]
    if not res or res[0].get("siren") != siren:
        return None
    fin = res[0].get("finances") or {}
    if not fin:
        return None
    year = max(fin)
    return {"year": year, "revenue": fin[year].get("ca"), "net_result": fin[year].get("resultat_net"),
            "source": FIN_URL.format(siren)}


def exposure_for(cards):
    measures, unquantified = [], []
    for c in cards:
        you = (c.get("chiffrage") or {}).get("you")
        theme = c.get("theme")
        maj = bool(c.get("majority_groups"))
        if not you:
            unquantified.append({"number": c["number"], "theme": theme, "reason": "pas de chiffrage par entreprise"})
            continue
        rng = you.get("eur_per_year")
        if you.get("sign") not in ("gain", "perte") or not rng:
            unquantified.append({"number": c["number"], "theme": theme,
                                 "reason": f"sens « {you.get('sign')} », montant non chiffré"})
            continue
        measures.append({"number": c["number"], "theme": theme, "sign": you["sign"],
                         "eur_per_year": {"low": rng["low"], "high": rng["high"]},
                         "majority_backed": maj, "majority_groups": c.get("majority_groups") or [],
                         "method": you.get("method"), "url": c.get("url")})

    # collapse mutually exclusive measures into one envelope
    counted, notes = [], []
    used = set()
    for grp in EXCLUSIVE:
        same = [m for m in measures if m["theme"] in grp]
        if len(same) > 1:
            signs = {m["sign"] for m in same}
            if len(signs) == 1:
                env = {"theme": " / ".join(sorted(grp)) + " (mesures opposées, comptées une fois)",
                       "sign": same[0]["sign"],
                       "eur_per_year": {"low": min(m["eur_per_year"]["low"] for m in same),
                                        "high": max(m["eur_per_year"]["high"] for m in same)},
                       "majority_backed": any(m["majority_backed"] for m in same)}
                counted.append(env)
                notes.append(f"Les mesures {', '.join(m['number'] for m in same)} s'opposent sur le même mécanisme "
                             f"mais le chiffrage leur donne le même sens ({env['sign']}) : comptées une seule fois.")
            else:
                counted.extend(same)
            used.update(m["number"] for m in same)
    counted += [m for m in measures if m["number"] not in used]

    def total(sign, only_majority=False):
        lo = sum(m["eur_per_year"]["low"] for m in counted if m["sign"] == sign and (m["majority_backed"] or not only_majority))
        hi = sum(m["eur_per_year"]["high"] for m in counted if m["sign"] == sign and (m["majority_backed"] or not only_majority))
        return {"low": lo, "high": hi}

    out = {"measures": measures, "unquantified": unquantified, "notes": notes}
    for sign in ("perte", "gain"):
        t, tm = total(sign), total(sign, True)
        out["loss" if sign == "perte" else "gain"] = {
            "eur_per_year": t,
            "majority_backed_eur_per_year": tm,
            "majority_share_pct": {"low": pct(tm["low"], t["low"]) if t["low"] else None,
                                   "high": pct(tm["high"], t["high"]) if t["high"] else None},
        }
    g, l = out["gain"]["eur_per_year"], out["loss"]["eur_per_year"]
    out["net_eur_per_year"] = {"low": g["low"] - l["high"], "high": g["high"] - l["low"]}
    return out


def ratios(rng, fin):
    r = {}
    if not fin:
        return {"revenue": "comptes non publiés dans l'API", "net_result": "comptes non publiés dans l'API"}
    ca, rn = fin.get("revenue"), fin.get("net_result")
    r["revenue_pct"] = ({"low": pct(rng["low"], ca), "high": pct(rng["high"], ca)} if ca and ca > 0
                        else "chiffre d'affaires absent")
    if rn is None:
        r["net_result_pct"] = "résultat net absent"
    elif rn <= 0:
        r["net_result_pct"] = f"résultat net négatif ({rn:,} €) : ratio non calculé".replace(",", " ")
    else:
        r["net_result_pct"] = {"low": pct(rng["low"], rn), "high": pct(rng["high"], rn)}
    return r


def part1():
    profiles = json.load(open(os.path.join(DATA, "profiles.json"), encoding="utf-8"))
    feed = json.load(open(os.path.join(DATA, "feed_142.json"), encoding="utf-8"))
    out = {}
    for p in profiles:
        s = p["siren"]
        fin = finances(s)
        e = exposure_for(feed.get(s, []))
        e["name"] = p["name"]
        e["finances"] = fin
        e["loss"]["ratios"] = ratios(e["loss"]["eur_per_year"], fin)
        e["gain"]["ratios"] = ratios(e["gain"]["eur_per_year"], fin)
        e["caveats"] = ["Montants bruts annuels avant impôt et avant report éventuel sur les clients ; "
                        "le résultat net est après impôt, le ratio surestime donc l'effet net.",
                        "Comptes sociaux de l'entité (SIREN), pas du groupe consolidé."]
        out[s] = e
    return out


# ---------------------------------------------------------------- part 2

EURONEXT = ("https://live.euronext.com/en/ajax/AwlHistoricalPrice/getFullDownloadAjax/{}"
            "?format=csv&decimal_separator=.&date_form=d/m/Y&adjusted=Y&startdate=2023-01-01&enddate={}")
INSTRUMENTS = {"EDEN": "FR0010908533-XPAR", "PLX": "NL0015001W49-XPAR", "CAC40": "FR0003500008-XPAR"}
END = "2026-11-13"

# Events: only those about issuers' economics (scope of use, commission cap, dematerialisation).
EVENTS = [
    {"date": "2024-11-20", "label": "AN adopte la prolongation de la dérogation « tout produit alimentaire » (PPL, scrutin n°455)",
     "channel": "périmètre d'usage", "expected_sign_issuers": "+",
     "source": "https://www.assemblee-nationale.fr/dyn/17/scrutins/455 (via data/history/clair.json)"},
    {"date": "2025-01-14", "label": "Sénat adopte la prolongation de la dérogation (scrutin n°150, amdts n°2 rect. identiques)",
     "channel": "périmètre d'usage", "expected_sign_issuers": "+",
     "source": "Sénat scrutin n°150 (2024-2025) via data/history/clair.json ; data/history/ameli.json"},
    {"date": "2025-01-21", "label": "Loi n° 2025-56 promulguée : dérogation prolongée au 31/12/2026",
     "channel": "périmètre d'usage", "expected_sign_issuers": "+",
     "source": "https://www.legifrance.gouv.fr/jorf/id/JORFTEXT000051018078 (via data/history/legifrance.json)"},
    {"date": "2026-06-09", "label": "Dépôt à l'AN de la PPL « moderniser et rééquilibrer le titre-restaurant »",
     "channel": "plafond des commissions, dématérialisation", "expected_sign_issuers": "-",
     "source": "https://www.senat.fr/dossier-legislatif/ppl26-032.html (« Première lecture - Assemblée nationale 9 juin 2026 »)"},
    {"date": "2026-10-12", "label": "AN adopte la PPL en 1re lecture, dont l'amdt n°63 (plafond des commissions) adopté",
     "channel": "plafond des commissions, dématérialisation", "expected_sign_issuers": "-",
     "source": "https://www.assemblee-nationale.fr/dyn/17/scrutins/8693 et /8685 (via data/history/clair.json)"},
    {"date": "2026-11-03", "label": "Commission des affaires sociales du Sénat : texte n°142 et rapport n°141 déposés (COM-7, COM-8 plafond adoptés)",
     "channel": "plafond des commissions", "expected_sign_issuers": "-",
     "source": "https://www.senat.fr/dossier-legislatif/ppl26-032.html ; data/history/ameli.json (COM-7, COM-8 adoptés)"},
]
NOT_COVERED = [
    {"date": "2023-10-12", "label": "Autorité de la concurrence, avis 23-A-16",
     "reason": "hors fenêtre : l'export Euronext ne remonte qu'à 2 ans (début 15/11/2024)",
     "source": "https://www.autoritedelaconcurrence.fr/en/press-release/meal-vouchers-autorite-de-la-concurrence-issues-opinion-government"},
    {"date": "2023-11-23 / 2023-12-18", "label": "Prolongation 2024 (AN puis Sénat)", "reason": "hors fenêtre de prix",
     "source": "data/history/clair.json"},
]


def load_prices(code, isin):
    url = EURONEXT.format(isin, END)
    body = get(url, os.path.join(RAW_PRICES, f"{code}_{isin}_{END}.csv"), ua="Mozilla/5.0")
    rows = {}
    lines = body.splitlines()
    hdr = next(i for i, l in enumerate(lines) if l.startswith("Date;"))
    for r in csv.DictReader(io.StringIO("\n".join(lines[hdr:])), delimiter=";"):
        try:
            d = datetime.strptime(r["Date"], "%d/%m/%Y").date()
            rows[d] = (float(r["Close"]), float(r["Number of Shares"] or 0))
        except (ValueError, KeyError):
            continue
    return rows, url


def tstat(x, se):
    return round(x / se, 2) if se else None


def part2():
    px, urls = {}, {}
    for code, isin in INSTRUMENTS.items():
        px[code], urls[code] = load_prices(code, isin)
    days = sorted(set(px["EDEN"]) & set(px["PLX"]) & set(px["CAC40"]))
    ret = {c: [None] + [px[c][days[i]][0] / px[c][days[i - 1]][0] - 1 for i in range(1, len(days))] for c in px}
    ar = {s: [None] + [ret[s][i] - ret["CAC40"][i] for i in range(1, len(days))] for s in ("EDEN", "PLX")}

    def idx(dstr):
        d = date.fromisoformat(dstr)
        return next(i for i, x in enumerate(days) if x >= d)

    ev_idx = [idx(e["date"]) for e in EVENTS]
    excl = set()
    for i in ev_idx:
        excl.update(range(i - 10, i + 11))
    clean = [i for i in range(1, len(days)) if i not in excl]
    sigma = {s: statistics.stdev([ar[s][i] for i in clean]) for s in ar}
    # market model on non-event days (robustness; beta from full sample = mild look-ahead)
    beta, alpha = {}, {}
    for s in ar:
        xs = [ret["CAC40"][i] for i in clean]
        ys = [ret[s][i] for i in clean]
        mx, my = statistics.mean(xs), statistics.mean(ys)
        b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
        beta[s], alpha[s] = round(b, 3), my - b * mx
    mm_res = {s: [None] + [ret[s][i] - alpha[s] - beta[s] * ret["CAC40"][i] for i in range(1, len(days))] for s in ar}
    sigma_mm = {s: statistics.stdev([mm_res[s][i] for i in clean]) for s in ar}

    def med_vol(s, i):
        v = [px[s][days[j]][1] for j in range(max(1, i - 60), i - 1)]
        return statistics.median(v) if v else None

    events, cars = [], {k: {s: [] for s in ar} for k in ("car_1_1", "car_1_5")}
    for e, i in zip(EVENTS, ev_idx):
        rec = {**e, "day0": days[i].isoformat(), "car_1_1": {}, "car_1_5": {}, "t_1_1": {}, "t_1_5": {},
               "car_1_1_market_model": {}, "volume_flags": [], "confounders": []}
        for s in ar:
            for key, (a, b) in (("car_1_1", (-1, 1)), ("car_1_5", (-1, 5))):
                rng = range(i + a, min(i + b, len(days) - 1) + 1)
                car = sum(ar[s][j] for j in rng)
                rec[key][s] = round(100 * car, 2)
                rec["t" + key[3:]][s] = tstat(car, sigma[s] * math.sqrt(len(rng)))
                cars[key][s].append(car)
                if len(rng) < b - a + 1:
                    rec["confounders"].append(f"fenêtre {key} tronquée à {len(rng)} jours (fin des données)")
            rec["car_1_1_market_model"][s] = round(100 * sum(mm_res[s][j] for j in range(i - 1, i + 2)), 2)
            mv = med_vol(s, i)
            for j in range(i - 1, min(i + 5, len(days) - 1) + 1):
                if mv and px[s][days[j]][1] > 2.5 * mv:
                    rec["volume_flags"].append(f"{s} {days[j].isoformat()} : volume {px[s][days[j]][1] / mv:.1f}× la médiane 60 j")
        events.append(rec)
    # overlapping windows
    for k in range(1, len(ev_idx)):
        if ev_idx[k] - ev_idx[k - 1] <= 6:
            events[k]["confounders"].append(f"fenêtre [-1,+5] chevauche l'événement du {EVENTS[k - 1]['date']}")
            events[k - 1]["confounders"].append(f"fenêtre [-1,+5] chevauche l'événement du {EVENTS[k]['date']}")
    for rec in events:
        if rec["volume_flags"]:
            rec["confounders"].append("volume anormal dans la fenêtre : nouvelle possible sans lien (publication de résultats non vérifiée)")

    summary = {}
    for key, L in (("car_1_1", 3), ("car_1_5", 7)):
        summary[key] = {}
        for s in ar:
            for grp, sel in (("all", lambda e: True), ("cap_events", lambda e: e["expected_sign_issuers"] == "-"),
                             ("scope_events", lambda e: e["expected_sign_issuers"] == "+")):
                xs = [c for c, e in zip(cars[key][s], EVENTS) if sel(e)]
                n = len(xs)
                m = statistics.mean(xs)
                summary[key].setdefault(grp, {})[s] = {
                    "n": n, "mean_pct": round(100 * m, 2),
                    "t_time_series": tstat(m, sigma[s] * math.sqrt(L) / math.sqrt(n)),
                    "t_cross_section": tstat(m, statistics.stdev(xs) / math.sqrt(n)) if n > 2 else None,
                }
    summary["sigma_daily_ar_pct"] = {s: round(100 * sigma[s], 2) for s in ar}
    summary["market_model"] = {s: {"beta": beta[s], "sigma_daily_pct": round(100 * sigma_mm[s], 2)} for s in ar}
    summary["price_window"] = [days[0].isoformat(), days[-1].isoformat()]
    summary["trading_days"] = len(days)

    return {
        "prices_source": urls,
        "prices_note": "Euronext live.euronext.com, téléchargement « Historical Data » public, cours de clôture ajustés (adjusted=Y) ; l'export ne fournit que les 2 dernières années.",
        "benchmark": "CAC 40 (FR0003500008, Euronext Paris)",
        "method": "Rendements anormaux ajustés du marché AR = R_titre − R_CAC40 ; CAR sur [-1,+1] et [-1,+5] autour du jour 0 (premier jour de bourse ≥ date de l'événement). "
                  "t = CAR / (σ_AR · √L), σ_AR estimé sur tous les jours hors ±10 jours de chaque événement. "
                  "Robustesse : modèle de marché (α, β estimés sur les mêmes jours hors événements).",
        "events": events,
        "events_not_covered": NOT_COVERED,
        "summary": summary,
        "limits": [
            "6 événements seulement, dont 3 sur le même sujet en 2 mois (prolongation 2024-2025) : aucune puissance statistique.",
            "Événements largement anticipés (dépôt, commission, vote) : l'information est souvent intégrée avant le jour 0.",
            "L'avis 23-A-16 de l'Autorité de la concurrence (12/10/2023) et la prolongation 2023 sont hors de la fenêtre de prix gratuite (2 ans).",
            "Dates de publication de résultats et de détachement de dividende non vérifiées (calendriers investisseurs en JavaScript) ; seuls les pics de volume sont signalés.",
            "Edenred et Pluxee sont internationaux : la France n'est qu'une part de leur activité, l'effet attendu sur le cours est dilué.",
            "β du modèle de marché estimé sur l'échantillon complet (léger biais de look-ahead) ; résultat principal en rendements ajustés du marché.",
        ],
    }


# ---------------------------------------------------------------- findings

def fmt_m(x):
    return f"{x / 1e6:.1f}".replace(".", ",") + " M€"


def findings(exp, es):
    f = []
    for s, e in exp.items():
        l, fin = e["loss"], e["finances"]
        lr = l["ratios"]
        if l["eur_per_year"]["high"] and fin:
            line = (f"{e['name']} ({s}) : pertes chiffrées {fmt_m(l['eur_per_year']['low'])} à {fmt_m(l['eur_per_year']['high'])} par an, "
                    f"soit {lr['revenue_pct']['low']} à {lr['revenue_pct']['high']} % du CA {fin['year']}")
            line += (f" et {lr['net_result_pct']['low']} à {lr['net_result_pct']['high']} % du résultat net"
                     if isinstance(lr["net_result_pct"], dict) else f" ({lr['net_result_pct']})")
            sh = l["majority_share_pct"]
            lo = "n.d. (bas de fourchette à 0 €)" if sh["low"] is None else f"{sh['low']} %"
            line += f" ; part portée par des mesures soutenues par la majorité sénatoriale : {lo} à {sh['high']} %."
            f.append(line)
        g = e["gain"]
        if g["eur_per_year"]["high"] and fin:
            gr = g["ratios"]["revenue_pct"]
            f.append(f"{e['name']} ({s}) : gains chiffrés {fmt_m(g['eur_per_year']['low'])} à {fmt_m(g['eur_per_year']['high'])} par an, "
                     f"soit {gr['low']} à {gr['high']} % du CA {fin['year']}"
                     + ("" if isinstance(g["ratios"]["net_result_pct"], dict) else f" ({g['ratios']['net_result_pct']})") + ".")
        if not l["eur_per_year"]["high"] and not g["eur_per_year"]["high"]:
            f.append(f"{e['name']} ({s}) : aucune mesure chiffrée en euros pour cette entreprise ({len(e['unquantified'])} mesure(s) non chiffrée(s)).")
    if es:
        for key in ("car_1_1",):
            for s in ("EDEN", "PLX"):
                a = es["summary"][key]["cap_events"][s]
                f.append(f"{s} : CAR moyen [-1,+1] sur les {a['n']} événements « plafond des commissions » = {a['mean_pct']} % (t = {a['t_time_series']}).")
        sig = [(e["date"], s, e["car_1_1"][s], e["t_1_1"][s]) for e in es["events"] for s in ("EDEN", "PLX")
               if e["t_1_1"][s] is not None and abs(e["t_1_1"][s]) >= 1.96]
        if sig:
            f.append("CAR [-1,+1] individuellement significatifs à 5 % : " +
                     "; ".join(f"{s} le {d} ({c} %, t = {t})" for d, s, c, t in sig) + ".")
        else:
            f.append("Aucun CAR [-1,+1] individuellement significatif à 5 % pour EDEN ou PLX.")
    return f


def main():
    exp = part1()
    try:
        es = part2()
    except Exception as ex:  # no free source -> null, as specified
        print("event study failed:", ex)
        es = None
    out = {"generated": date.today().isoformat(),
           "sources": {"finances": "API Recherche d'entreprises (https://recherche-entreprises.api.gouv.fr), champ finances",
                       "exposure": "data/feed_142.json (chiffrage.you par carte)"},
           "exposure": exp, "event_study": es, "findings": findings(exp, es)}
    with open(os.path.join(DATA, "investors.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    for line in out["findings"]:
        print("-", line)


if __name__ == "__main__":
    main()
