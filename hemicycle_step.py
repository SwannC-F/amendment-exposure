"""Hémicycle step: Orcet vote predictions and cross-references, written to hemicycle.json.

Usage: python3 hemicycle_step.py an <législature> <texte>     Assemblée, data/an/<lég>/<texte>/
       python3 hemicycle_step.py senat <session> <texte>      Sénat, data/<session>/<texte>/
       python3 hemicycle_step.py <session> <texte>            same CLI as the other steps (session "an/17" = Assemblée)

REST API https://api.hemicycle.ai/v1, key in HEMICYCLE_API_KEY (Bearer). Endpoints:
- GET  /amendements/{id}            1 crédit   (Assemblée: text id of the amendments)
- GET  /amendements?texte=…         1 crédit/page (Assemblée: sort of each amendment, Hémicycle ids)
- POST /orcet/predictions           50 crédits, 404 free when Orcet has no prediction (Assemblée only)
- POST /jeux/interroger             1 crédit/page (senat_amendements, representants_interets)
Orcet is called once per measure, on its first amendment that has a prediction; the raw fields
are kept as Hémicycle returns them (mean of the deputies' individual probabilities of voting for,
NOT a probability of adoption). Budget cap HEMICYCLE_BUDGET (default 3000 credits); predictions
already in hemicycle.json for the same amendment are reused, not paid again.
"""
import json
import time
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.hemicycle.ai/v1"
ORCET_COST = 50
BUDGET = int(os.environ.get("HEMICYCLE_BUDGET", "3000"))
ELIASSE = "https://eliasse.assemblee-nationale.fr/api-eliasse"


def load_env():
    p = Path(".env")
    if p.exists():
        for line in p.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


class Hemi:
    def __init__(self, key):
        self.key, self.spent, self.calls = key, 0, []

    def req(self, method, path, body=None, cost=1):
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(API + path, data=data, method=method, headers={
            "Authorization": f"Bearer {self.key}", "Content-Type": "application/json",
            "User-Agent": "amendment-exposure/1.0"})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(r, timeout=60) as resp:
                    out = json.loads(resp.read().decode())
                break
            except urllib.error.HTTPError as e:
                self.calls.append(f"{method} {path.split('?')[0]} -> {e.code}")
                if e.code in (404, 501):
                    return None  # not billed
                if e.code == 429 and attempt < 3:  # rate limit: wait as the API asks
                    try:
                        wait = int(json.loads(e.read().decode()).get("retry_after", 60))
                    except Exception:
                        wait = 60
                    print(f"  limite de débit Hémicycle, pause {wait} s", flush=True)
                    time.sleep(min(wait, 90))
                    continue
                raise RuntimeError(f"{method} {path.split('?')[0]}: HTTP {e.code} {e.read()[:300]!r}")
        billed = (out.get("credits") or {}).get("dus") if isinstance(out, dict) else None
        self.spent += billed if isinstance(billed, (int, float)) else cost
        self.calls.append(f"{method} {path.split('?')[0]} -> 200")
        return out

    def credits(self):
        return (self.req("GET", "/credits", cost=0) or {}).get("solde")


def text_dir(args):
    if args[0] == "an":
        return "an", Path("data") / "an" / args[1] / args[2], args[1], args[2]
    if args[0] == "senat":
        return "senat", Path("data") / args[1] / args[2], args[1], args[2]
    session, texte = args[0], args[1]
    if session.startswith("an/"):
        return "an", Path("data") / session / texte, session.split("/", 1)[1], texte
    return "senat", Path("data") / session / texte, session, texte


# ---------- Assemblée ----------

def an_uids(d):
    """numero -> AN uid, from eLiasse (free), using the examen of text.json."""
    meta = json.loads((d / "text.json").read_text())
    req = urllib.request.Request(f"{ELIASSE}/examens/{meta['examen']}/derouleur",
                                 headers={"User-Agent": "amendment-exposure/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        places = json.loads(r.read().decode())["places"]
    return {str(a["numero"]): a["uid"] for p in places for a in p.get("amendements", [])}


def an_listing(h, texte_id):
    rows, cursor = {}, None
    for _ in range(10):
        q = f"/amendements?texte={texte_id}&limit=100" + (f"&cursor={cursor}" if cursor else "")
        page = h.req("GET", q) or {}
        for a in page.get("data", []):
            rows[str(a["numero"])] = a
        cursor = page.get("next_cursor")
        if not page.get("has_more") or not cursor:
            break
    return rows


def an_run(h, d, measures, previous):
    uids = an_uids(d)
    first = next((uids[str(n)] for m in measures for n in m["amendments"] if str(n) in uids), None)
    one = h.req("GET", f"/amendements/{first}") if first else None
    texte_id = (one or {}).get("texte")
    listing = an_listing(h, texte_id) if texte_id else {}
    out, n_pred = {}, 0
    for m in measures:
        refs, pred = [], None
        for n in m["amendments"]:
            uid = uids.get(str(n))
            if not uid:
                continue
            a = listing.get(str(n), {})
            refs.append({"type": "amendement", "numero": str(n), "id": uid,
                         "sort": a.get("sort_libelle") or a.get("sort"), "date_sort": a.get("date_sort"),
                         "source": "Hémicycle · Assemblée nationale (Licence Ouverte 2.0)"})
        prev = (previous.get(m["key"]) or {}).get("vote_prediction")
        if prev and prev.get("amendement") in {r["id"] for r in refs}:
            pred = prev  # cached: not paid again
        else:
            for r in refs:
                if h.spent + ORCET_COST > BUDGET:
                    print(f"  budget {BUDGET} crédits atteint, Orcet arrêté")
                    break
                p = h.req("POST", "/orcet/predictions", {"amendement": r["id"]}, cost=ORCET_COST)
                if p:
                    pred = {k: v for k, v in p.items() if k != "source"}
                    pred.update({"numero": r["numero"], "source": "Hémicycle · Orcet"})
                    break
        n_pred += bool(pred)
        out[m["key"]] = {"vote_prediction": pred, "hemicycle_refs": refs}
    return out, {"texte_hemicycle": texte_id, "measures_with_prediction": n_pred}


# ---------- Sénat ----------

def senat_run(h, d, measures, previous):
    am = json.loads((d / "amendments.json").read_text())
    am = am if isinstance(am, list) else am.get("amendments", [])
    urls = {str(a["number"]): "https:" + a["url"] if a.get("url", "").startswith("//") else a.get("url")
            for a in am}
    wanted = sorted({u for m in measures for n in m["amendments"] if (u := urls.get(str(n)))})
    rows = {}
    for i in range(0, len(wanted), 100):
        page = h.req("POST", "/jeux/interroger", {
            "jeu": "senat_amendements", "filtres": [{"colonne": "url", "op": "in", "valeur": wanted[i:i + 100]}],
            "colonnes": ["id", "texte_id", "numero", "sort", "avis_commission", "avis_gouvernement", "url"],
            "limite": 200}) or {}
        for r in page.get("lignes", []):
            rows[r.get("url")] = r
    out = {}
    for m in measures:
        refs = []
        for n in m["amendments"]:
            r = rows.get(urls.get(str(n)))
            if r:
                refs.append({"type": "amendement", "numero": str(n), "id": r.get("id"), "sort": r.get("sort"),
                             "avis_commission": r.get("avis_commission"),
                             "avis_gouvernement": r.get("avis_gouvernement"),
                             "source": "Hémicycle · Sénat (licence data.senat.fr)"})
        out[m["key"]] = {"vote_prediction": None, "hemicycle_refs": refs}  # Orcet: Assemblée only
    return out, {"senat_amendements_matched": len(rows)}


# ---------- HATVP (both chambers): organisations already in history.json ----------

def hatvp_refs(h, d, out):
    p = d / "history.json"
    if not p.exists():
        return 0
    hist = json.loads(p.read_text()).get("measures", {})
    by_measure = {k: {o["hatvp_id"] for side in ("lobby_pour", "lobby_contre", "lobby_both")
                      for o in (m.get(side) or []) if o.get("hatvp_id")} for k, m in hist.items()}
    ids = sorted(set().union(*by_measure.values())) if by_measure else []
    if not ids:
        return 0
    rows = {}
    for i in range(0, len(ids), 100):
        page = h.req("POST", "/jeux/interroger", {
            "jeu": "representants_interets",
            "filtres": [{"colonne": "identifiant_national", "op": "in", "valeur": ids[i:i + 100]}],
            "colonnes": ["identifiant_national", "denomination", "categorie", "secteurs", "nb_salaries",
                         "depenses_tranche", "maj_le"], "limite": 200}) or {}
        for r in page.get("lignes", []):
            rows[r["identifiant_national"]] = r
    for k, ids_k in by_measure.items():
        if k in out:
            out[k]["hemicycle_refs"] += [dict(rows[i], type="representant_interets",
                                              source="Hémicycle · HATVP (Licence Ouverte)")
                                         for i in sorted(ids_k) if i in rows]
    return len(rows)


def main(args):
    if len(args) < 2:
        sys.exit(__doc__)
    load_env()
    key = os.environ.get("HEMICYCLE_API_KEY")
    if not key:
        sys.exit("HEMICYCLE_API_KEY absent : étape Hémicycle sautée")
    chamber, d, _, _ = text_dir(args)
    measures = json.loads((d / "measures.json").read_text())
    path = d / "hemicycle.json"
    previous = json.loads(path.read_text()).get("measures", {}) if path.exists() else {}
    h = Hemi(key)
    before = h.credits()
    out, info = (an_run if chamber == "an" else senat_run)(h, d, measures, previous)
    try:
        info["hatvp_orgs_matched"] = hatvp_refs(h, d, out)
    except RuntimeError as e:
        print("  HATVP :", e)
    after = h.credits()
    spent = before - after if isinstance(before, (int, float)) and isinstance(after, (int, float)) else h.spent
    path.write_text(json.dumps({"source": "Hémicycle (api.hemicycle.ai/v1)", "chamber": chamber, **info,
                                "credits_spent": spent, "credits_left": after, "budget": BUDGET,
                                "calls": h.calls, "measures": out}, ensure_ascii=False, indent=2))
    n = sum(1 for v in out.values() if v["vote_prediction"])
    print(f"{len(out)} mesures, {n} avec prédiction Orcet, {spent} crédits -> {path}")
    for k, v in out.items():
        p = v["vote_prediction"]
        if p:
            print(f"  {k[:45]:<45} n°{p['numero']:<5} pour {p.get('moyenne_probabilites_pour')} "
                  f"confiance {p.get('confiance')}")


if __name__ == "__main__":
    main(sys.argv[1:])
