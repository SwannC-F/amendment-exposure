"""Build data/engine_142.json: everything the page needs to compute the feed of ANY company.

Usage: python3 build_engine.py 142

One entry per measure (theme): targeted NAF codes and roles, political support, exposure,
history, and the sourced chiffrage turned into per-sector RATES (€ per € of revenue), so the
page can estimate a gain/loss for any company of a sector the chiffrage covers.

Rates come from the per-profile estimates of chiffrage_a.py / chiffrage_b.py, which are all
linear in revenue (revenue × share paid in titres × rate change). A rate is only given for
the NAF codes its parameter is about (restaurants: 15 % of revenue; supermarkets and
hypermarkets: 1 %), both quoted in amendment n°24. Issuers get a fixed range (market share
10–40 %, Autorité de la concurrence). Other sectors: "non chiffré pour votre secteur".
"""
import json
import sys
from pathlib import Path

from profiles import load_history

# Which NAF codes a demo profile's rate generalises to, and why (the parameter's scope).
RATE_SCOPE = {
    "322566043": {"nafs": ["56.10A", "56.10C"], "scope": "restaurants (le titre = 15 % du CA, amendement n°24)"},
    "451321335": {"nafs": ["47.11D", "47.11F"], "scope": "grande distribution (le titre = 1 % du CA, amendement n°24)"},
}
ROLE_SCOPE = {
    "393365135": {"role": "Émetteurs", "scope": "grands émetteurs (part de marché 10 à 40 %, Autorité de la concurrence)"},
    "841983828": {"role": "Plateformes", "scope": "plateformes de livraison (sens seulement, montant non sourcé)"},
}
SIGN_FLIP = {"gain": "perte", "perte": "gain"}


def revenue_by_siren(chiffrage):
    rev = {}
    for ch in chiffrage.values():
        for siren, p in ch.get("per_profile", {}).items():
            inp = p.get("inputs") or {}
            ca = inp.get("ca_eur") or inp.get("ca")
            if ca:
                rev[siren] = ca
    return rev


def main(n):
    criteria = json.loads(Path(f"data/criteria_{n}.json").read_text())
    signals = {s["number"]: s for s in json.loads(Path(f"data/signals_{n}.json").read_text())}
    exposure = {e["number"]: e for e in json.loads(Path(f"data/exposure_{n}.json").read_text())["amendments"]}
    chiffrage = {}
    for f in sorted(Path("data/chiffrage").glob("*.json")):
        ch = json.loads(f.read_text())
        chiffrage[ch["theme"]] = ch
    if "Supprimer le double plafond journalier" in chiffrage:
        chiffrage.setdefault("Rendre effectif le double plafond journalier",
                             chiffrage["Supprimer le double plafond journalier"])
    history = load_history()
    revenue = revenue_by_siren(chiffrage)

    measures = {}
    for c in criteria:
        if not c["criteria"]["criteria_found"]:
            continue
        theme = (c["criteria"]["themes"] or [c["criteria"]["effect"]])[0]
        s, e = signals.get(c["number"], {}), exposure.get(c["number"], {})
        m = measures.setdefault(theme, {
            "theme": theme, "amendments": [], "effects": [], "nafs": set(), "roles": set(), "sectors": {},
            "n_groups": s.get("n_groups", 0), "groups": s.get("groups", []),
            "majority_groups": s.get("majority_groups", []),
            "companies": e.get("companies") or None, "employees_low": e.get("employees_low"),
            "employees_high": e.get("employees_high"), "not_counted": e.get("not_counted", []),
            "who": c["criteria"]["who"], "quote": c["criteria"]["quote"],
        })
        m["amendments"].append(c["number"])
        if c["criteria"]["effect"] not in m["effects"]:
            m["effects"].append(c["criteria"]["effect"])
        for sec in c["criteria"]["sectors"]:
            if sec["naf"]:
                m["nafs"].add(sec["naf"])
            else:
                m["roles"].add(sec["label"].split(" ")[0])  # "Émetteurs", "Plateformes", "Associations"
            m["sectors"].setdefault(sec["naf"] or sec["label"], sec["label"])

        ch = chiffrage.get(theme)
        if ch and "chiffrage" not in m:
            rates = []
            for siren, p in ch.get("per_profile", {}).items():
                eur, sign = p.get("eur_per_year"), p.get("sign")
                if siren in RATE_SCOPE and eur and revenue.get(siren):
                    # "Rendre effectif" is the opposite of "Supprimer": same money, flipped sign.
                    if theme == "Rendre effectif le double plafond journalier":
                        sign = SIGN_FLIP.get(sign, sign)
                    rates.append({"nafs": RATE_SCOPE[siren]["nafs"], "scope": RATE_SCOPE[siren]["scope"],
                                  "sign": sign, "rate_low": eur["low"] / revenue[siren],
                                  "rate_high": eur["high"] / revenue[siren], "method": p.get("method")})
                elif siren in ROLE_SCOPE and sign:
                    rates.append({"role": ROLE_SCOPE[siren]["role"], "scope": ROLE_SCOPE[siren]["scope"],
                                  "sign": sign, "eur": eur, "method": p.get("method")})
            m["chiffrage"] = {"mechanism": ch["mechanism"], "winners": ch["winners"], "losers": ch["losers"],
                              "total_eur_per_year": ch.get("total_eur_per_year"), "rates": rates,
                              "parameters": ch["parameters"], "not_computable": ch.get("not_computable")}
        if theme in history and "history" not in m:
            m["history"] = history[theme]

    out = []
    for m in measures.values():
        m["nafs"], m["roles"] = sorted(m["nafs"]), sorted(m["roles"])
        m["sectors"] = [{"key": k, "label": v} for k, v in m["sectors"].items()]
        out.append(m)
    out.sort(key=lambda m: (-m["n_groups"], -len(m["majority_groups"]), -(m["companies"] or 0)))

    Path(f"data/engine_{n}.json").write_text(json.dumps(
        {"text": {"chamber": "Sénat", "number": n, "title": "Titres-restaurant", "seance": "2026-11-19"},
         "majority": ["Les Républicains", "UCI"], "measures": out}, ensure_ascii=False, indent=2))
    print(f"{len(out)} measures -> data/engine_{n}.json")
    for m in out:
        r = (m.get("chiffrage") or {}).get("rates", [])
        print(f"  {m['n_groups']} gr. {m['theme'][:45]:<45} NAF {len(m['nafs']):>2}  roles {m['roles']}  rates {len(r)}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "142")
