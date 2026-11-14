"""Company profiles (by SIREN) and the amendment feed ranked for each.

Usage: python3 profiles.py 142
Reads data/criteria_<n>.json, data/signals_<n>.json, data/exposure_<n>.json (optional),
writes data/profiles.json and data/feed_<n>.json.

A profile is a SIREN. Its NAF code comes from the API Recherche d'entreprises.
Some actors have no NAF code of their own in our criteria (titre-restaurant issuers,
delivery platforms), so a profile can also carry a role matched against sector labels.

Ranking, for amendments that concern the profile:
  1. number of political groups carrying the same measure (signals.py)
  2. whether the Sénat majority groups are among them
  3. number of exposed companies (exposure.py), if available
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

API = "https://recherche-entreprises.api.gouv.fr/search?q={}&per_page=1"
UA = "amendment-exposure/0.1 (hackathon prototype)"

PROFILES = [
    {"siren": "322566043", "roles": []},                       # Hippopotamus (restaurants)
    {"siren": "451321335", "roles": []},                       # Carrefour Hypermarchés
    {"siren": "393365135", "roles": ["Émetteurs"]},            # Edenred France (issuer)
    {"siren": "841983828", "roles": ["Plateformes"]},          # Uber Eats France (platform)
]


def company(siren):
    req = urllib.request.Request(API.format(siren), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        res = json.load(r)["results"][0]
    time.sleep(0.2)
    return {"siren": siren, "name": res["nom_complet"], "naf": res["activite_principale"],
            "headcount_band": res["tranche_effectif_salarie"],
            "city": (res.get("siege") or {}).get("libelle_commune")}


def load_history():
    """Per theme: past Sénat amendments by group (Ameli), findings, and who lobbied
    for / against (HATVP). Files are optional; missing ones are skipped."""
    out = {}

    def theme_entry(t):
        return out.setdefault(t, {"senate_by_group": {}, "findings": [], "lobby_pour": [], "lobby_contre": [],
                                  "lobby_quotes": []})

    ameli_path = Path("data/history/ameli.json")
    if ameli_path.exists():
        a = json.loads(ameli_path.read_text())
        theme_of = {(x["session"], x["number"]): x["theme"] for x in a["amendments"]}
        for t, groups in a["by_theme"].items():
            theme_entry(t)["senate_by_group"] = groups
        for f in a.get("findings_detail", []):
            themes = {theme_of.get((x["session"], x["number"])) for x in f["amendments"]} - {None}
            for t in themes:
                theme_entry(t)["findings"].append({"text": f["text"], "source": "Sénat (Ameli)"})

    hatvp_path = Path("data/history/hatvp.json")
    if hatvp_path.exists():
        h = json.loads(hatvp_path.read_text())
        for o in h["organisations"]:
            for s in o.get("sides", []):
                e = theme_entry(s["theme"])
                key = "lobby_pour" if s["side"] == "pour" else "lobby_contre"
                if o["name"] not in e[key]:
                    e[key].append(o["name"])
                    e["lobby_quotes"].append({"org": o["name"], "side": s["side"], "year": s.get("year"),
                                              "quote": s["quote"], "fiche": s.get("fiche")})
    return out


def concerns(profile, sectors):
    for s in sectors:
        if s["naf"] and s["naf"] == profile["naf"]:
            return s["label"]
        if not s["naf"] and any(s["label"].startswith(r) for r in profile["roles"]):
            return s["label"]
    return None


def main(n):
    criteria = json.loads(Path(f"data/criteria_{n}.json").read_text())
    signals = {s["number"]: s for s in json.loads(Path(f"data/signals_{n}.json").read_text())}
    exp_path = Path(f"data/exposure_{n}.json")
    exposure = ({e["number"]: e for e in json.loads(exp_path.read_text())["amendments"]}
                if exp_path.exists() else {})

    # Sourced € estimates per measure (chiffrage_a.py / chiffrage_b.py), keyed by theme.
    chiffrage = {}
    for f in sorted(Path("data/chiffrage").glob("*.json")):
        ch = json.loads(f.read_text())
        chiffrage[ch["theme"]] = ch
    if "Supprimer le double plafond journalier" in chiffrage:  # same file covers both sides
        chiffrage.setdefault("Rendre effectif le double plafond journalier",
                             chiffrage["Supprimer le double plafond journalier"])

    history = load_history()

    profiles_path = Path("data/profiles.json")
    if profiles_path.exists():
        profiles = json.loads(profiles_path.read_text())
    else:
        profiles = [{**company(p["siren"]), "roles": p["roles"]} for p in PROFILES]
        profiles_path.write_text(json.dumps(profiles, ensure_ascii=False, indent=2))

    feed = {}
    for p in profiles:
        items = []
        for c in criteria:
            if not c["criteria"]["criteria_found"]:
                continue
            why = concerns(p, c["criteria"]["sectors"])
            if not why:
                continue
            s = signals.get(c["number"], {})
            e = exposure.get(c["number"], {})
            items.append({"number": c["number"], "effect": c["criteria"]["effect"],
                          "who": c["criteria"]["who"], "author": c.get("author", ""),
                          "themes": c["criteria"]["themes"], "matched_sector": why,
                          "n_groups": s.get("n_groups", 0), "groups": s.get("groups", []),
                          "majority_groups": s.get("majority_groups", []),
                          "companies": e.get("companies") or None,
                          "not_counted": e.get("not_counted", []),
                          "employees_low": e.get("employees_low"), "employees_high": e.get("employees_high"),
                          "url": c["url"], "quote": c["criteria"]["quote"]})
        items.sort(key=lambda i: (-i["n_groups"], -len(i["majority_groups"]), -(i["companies"] or 0)))
        # One card per measure (first theme): near-identical amendments from several
        # senators are the same fight, not five different ones.
        cards = {}
        for i in items:
            theme = (i["themes"] or [i["effect"]])[0]
            card = cards.setdefault(theme, {**i, "theme": theme, "amendments": [], "effects": []})
            card["amendments"].append(i["number"])
            if i["effect"] not in card["effects"]:
                card["effects"].append(i["effect"])
        for card in cards.values():
            ch = chiffrage.get(card["theme"])
            if ch:
                mine = ch.get("per_profile", {}).get(p["siren"], {})
                card["chiffrage"] = {
                    "mechanism": ch["mechanism"], "winners": ch["winners"], "losers": ch["losers"],
                    "total_eur_per_year": ch.get("total_eur_per_year"),
                    "you": {"sign": mine.get("sign"), "eur_per_year": mine.get("eur_per_year"),
                            "method": mine.get("method")},
                    "parameters": ch["parameters"], "not_computable": ch.get("not_computable"),
                }
        for card in cards.values():
            h = history.get(card["theme"])
            if not h:
                continue
            sign = (card.get("chiffrage") or {}).get("you", {}).get("sign")
            allies, opponents = [], []
            if sign == "gain":
                allies, opponents = h["lobby_pour"], h["lobby_contre"]
            elif sign == "perte":
                allies, opponents = h["lobby_contre"], h["lobby_pour"]
            me = p["name"].split(" (")[0].upper()
            card["history"] = {**h,
                               "allies": [o for o in allies if o.upper() != me],
                               "opponents": [o for o in opponents if o.upper() != me]}
        feed[p["siren"]] = list(cards.values())

    Path(f"data/feed_{n}.json").write_text(json.dumps(feed, ensure_ascii=False, indent=2))
    for p in profiles:
        items = feed[p["siren"]]
        n_amdts = sum(len(i["amendments"]) for i in items)
        print(f"\n{p['name']} ({p['naf']}) — {len(items)} mesures, {n_amdts} amendements")
        for i in items[:5]:
            maj = " +maj" if i["majority_groups"] else ""
            print(f"  {i['n_groups']} gr.{maj:<5} {i['theme'][:48]:<48} n° {', '.join(i['amendments'])}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "142")
