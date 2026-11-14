"""Which texts modified the titres-restaurant articles of the code du travail (L. 3262-x), from Légifrance (API PISTE).

Stdlib only. Reads PISTE_CLIENT_ID / PISTE_CLIENT_SECRET from .env (never printed), caches every raw
API response under data/raw/legifrance/ (git-ignored), and writes data/history/legifrance.json.

For each article found in the code (L3262-1 … plus any L3262-x-y), every version is fetched with
/consult/getArticle; the modifying text of a version is its lienModifications entry (orientation
"cible") whose dateDebutCible / signature is closest before the version start. The change summary
of each text is written by hand in CHANGES below, from the word diff that this script prints
(`--diff`), and every summary quotes words that the script checks are really added or removed.

    python3 history_legifrance.py           # uses the cache
    python3 history_legifrance.py --refresh # re-downloads
    python3 history_legifrance.py --diff    # prints version-to-version word diffs
"""
import datetime as dt
import difflib
import hashlib
import html
import http.client
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

TOKEN_URL = "https://oauth.piste.gouv.fr/api/oauth/token"
API = "https://api.piste.gouv.fr/dila/legifrance/lf-engine-app"
RAW_DIR = "data/raw/legifrance"
OUT = "data/history/legifrance.json"
CODE = "Code du travail"

# Candidate article numbers. Numbers that do not exist simply return no search hit.
CANDIDATES = [f"L3262-{i}" for i in range(1, 13)] + [
    f"L3262-{i}-{j}" for i in range(1, 8) for j in range(1, 4)
]
# Regulatory articles (décrets), where daily cap, Sunday use and validity live.
R_CANDIDATES = [f"R3262-{i}" for i in range(1, 50)] + [
    f"R3262-{i}-{j}" for i in range(1, 47) for j in range(1, 3)
]

REFRESH = "--refresh" in sys.argv
_token = None


def env():
    out = {}
    with open(".env") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip("'\"")
    return out


def token():
    global _token
    if _token is None:
        e = env()
        data = urllib.parse.urlencode({
            "grant_type": "client_credentials", "scope": "openid",
            "client_id": e["PISTE_CLIENT_ID"], "client_secret": e["PISTE_CLIENT_SECRET"],
        }).encode()
        with urllib.request.urlopen(TOKEN_URL, data, timeout=30) as r:
            _token = json.load(r)["access_token"]
    return _token


def post(route, body):
    """POST with cache under RAW_DIR and retries (the network path drops connections at times)."""
    key = hashlib.sha1((route + json.dumps(body, sort_keys=True)).encode()).hexdigest()[:16]
    path = os.path.join(RAW_DIR, route.strip("/").replace("/", "_") + "_" + key + ".json")
    if os.path.exists(path) and not REFRESH:
        with open(path) as f:
            return json.load(f)["response"]
    last = None
    for attempt in range(6):
        try:
            req = urllib.request.Request(API + route, json.dumps(body).encode(), {
                "Authorization": "Bearer " + token(), "Content-Type": "application/json",
                "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
            resp = json.loads(raw)
            break
        except (http.client.HTTPException, urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            if isinstance(exc, urllib.error.HTTPError) and exc.code in (400, 404):
                raise
            last = exc
            time.sleep(1 + attempt)
    else:
        raise RuntimeError(f"{route} failed: {last}")
    os.makedirs(RAW_DIR, exist_ok=True)
    with open(path, "w") as f:
        json.dump({"route": route, "body": body, "fetched": dt.datetime.now().isoformat(timespec="seconds"),
                   "response": resp}, f, ensure_ascii=False)
    return resp


def day(ms):
    if ms is None:
        return None
    d = dt.datetime(1970, 1, 1) + dt.timedelta(milliseconds=ms)
    return None if d.year >= 2999 else d.date().isoformat()


def find_article(num, code=CODE):
    """Return one LEGIARTI id for this article number in `code` (default: code du travail), or None."""
    body = {"recherche": {"champs": [{"typeChamp": "NUM_ARTICLE", "criteres": [
        {"typeRecherche": "EXACTE", "valeur": num, "operateur": "ET"}], "operateur": "ET"}],
        "filtres": [{"facette": "NOM_CODE", "valeurs": [code]}],
        "pageNumber": 1, "pageSize": 3, "operateur": "ET", "sort": "PERTINENCE", "typePagination": "ARTICLE"},
        "fond": "CODE_DATE"}
    resp = post("/search", body)
    for res in resp.get("results") or []:
        for sec in res.get("sections") or []:
            for ex in sec.get("extracts") or []:
                if ex.get("num") == num and ex.get("id", "").startswith("LEGIARTI"):
                    return ex["id"]
    return None


def get_article(aid):
    return post("/consult/getArticle", {"id": aid})["article"]


def clean(text):
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    return re.sub(r"\s+", " ", text).strip()


def text_url(cid):
    return f"https://www.legifrance.gouv.fr/jorf/id/{cid}"


def article_url(aid):
    return f"https://www.legifrance.gouv.fr/codes/article_lc/{aid}"


def text_info(cid):
    """Title, NOR and dates of a JORF text."""
    resp = post("/consult/jorf", {"textCid": cid})
    return {
        "title": clean(resp.get("title") or ""),
        "nor": resp.get("nor") or None,
        "date_signature": day(resp.get("dateTexte")) if isinstance(resp.get("dateTexte"), int) else None,
    }


def modifier_of(version, start):
    """The text that created this version: lienModifications 'cible' entry starting closest before `start`."""
    best = None
    for link in version.get("lienModifications") or []:
        if link.get("linkOrientation") != "cible":
            continue
        if link.get("linkType") not in ("MODIFIE", "CREATION", "ABROGE", "TRANSFERE", "CREE", "DEPLACE"):
            continue
        d = link.get("datePubliTexte") or ""
        if start and d and d > start:
            # published after the version start: a later modification of this version
            continue
        if best is None or d > (best.get("datePubliTexte") or ""):
            best = link
    if best is None:
        # first version of a recodified article: the codifying ordinance
        for link in version.get("lienModifications") or []:
            if link.get("linkType") == "CODIFICATION":
                return link
    return best


def words(t):
    return re.findall(r"\w+(?:[’'-]\w+)*|[^\w\s]", t)


def diff(old, new, ctx=0):
    """(removed, added) runs of words between two article texts, with `ctx` words of context on each side."""
    a, b = words(old), words(new)
    removed, added = [], []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op in ("delete", "replace"):
            removed.append(" ".join(a[max(0, i1 - ctx):i2 + ctx]))
        if op in ("insert", "replace"):
            added.append(" ".join(b[max(0, j1 - ctx):j2 + ctx]))
    return removed, added


def collect(candidates):
    articles = {}
    for num in candidates:
        aid = find_article(num)
        if not aid:
            continue
        cur = get_article(aid)
        versions = []
        for v in sorted(cur.get("articleVersions") or [], key=lambda v: v["dateDebut"]):
            full = get_article(v["id"])
            start, end = day(v["dateDebut"]), day(v["dateFin"])
            versions.append({"id": v["id"], "etat": v["etat"], "start": start, "end": end,
                             "text": clean(full.get("texte") or full.get("texteHtml")),
                             "nota": clean(full.get("nota")),
                             "links": full.get("lienModifications") or [],
                             "modifier": modifier_of(full, start)})
        articles[num] = versions
    return articles


def main():
    arts = collect(CANDIDATES + R_CANDIDATES)
    if "--diff" in sys.argv:
        for num, versions in arts.items():
            prev = None
            for v in versions:
                m = v["modifier"] or {}
                print(f"\n=== {num} {v['id']} {v['start']} -> {v['end']} [{v['etat']}] by {clean(m.get('textTitle'))} ({m.get('textCid')})")
                if prev is None:
                    print("  TEXT:", v["text"][:1500])
                else:
                    rem, add = diff(prev["text"], v["text"])
                    for r in rem:
                        print("  -", r[:400])
                    for a in add:
                        print("  +", a[:400])
                prev = v
        return
    build(arts)


# Hand-written summary of each modifying text, from the `--diff` output. Every `evidence` string must be
# found (word for word) in what that text added or removed (with three words of context), or in the text of an article it created;
# build() stops otherwise. Themes are the criteria_142 themes the change bears on directly;
# context_themes are themes it only gives background to.
T_REPAS = "Limiter aux repas et fruits et légumes"
T_DIM = "Utilisation le dimanche"
T_VALID = "Durée de validité des titres"
T_PLAF_R = "Rendre effectif le double plafond journalier"
T_PLAF_S = "Supprimer le double plafond journalier"
T_PAPIER = "Repousser la fin des titres papier"
T_COMM = "Plafonner les commissions des émetteurs"
CHANGES = {
    "JORFTEXT000051018078": {  # loi 2025-56
        "change": "Prolonge la dérogation « tout produit alimentaire » (art. 6 de la loi n° 2022-1158) du 31 décembre 2024 au 31 décembre 2026.",
        "evidence": ["31 décembre 2024", "31 décembre 2026"], "themes": [T_REPAS]},
    "JORFTEXT000048668803": {  # loi 2023-1252
        "change": "Prolonge la dérogation « tout produit alimentaire » (art. 6 de la loi n° 2022-1158) du 31 décembre 2023 au 31 décembre 2024.",
        "evidence": ["31 décembre 2023", "31 décembre 2024"], "themes": [T_REPAS]},
    "JORFTEXT000046343485": {  # décret 2022-1266
        "change": "Relève le plafond d'utilisation journalier des titres-restaurant (R. 3262-10) de dix-neuf à vingt-cinq euros par jour.",
        "evidence": ["dix-neuf", "vingt-cinq"], "themes": [T_PLAF_R, T_PLAF_S]},
    "JORFTEXT000046186723": {  # loi 2022-1158
        "change": "Crée, sans la codifier, une dérogation à L. 3262-1 : jusqu'au 31 décembre 2023, les titres paient tout produit alimentaire, directement consommable ou non, chez les commerces mentionnés à L. 3262-3.",
        "evidence": ["Par dérogation à l'article L. 3262-1 du code du travail", "jusqu'au 31 décembre 2023",
                     "tout produit alimentaire"], "themes": [T_REPAS]},
    "JORFTEXT000039727052": {  # décret 2019-1586
        "change": "Abroge R. 3262-20, qui obligeait l'employeur émettant lui-même ses titres, dans les entreprises de plus de vingt-cinq salariés, à verser les fonds sur son compte sous huit jours.",
        "evidence": ["Dans les entreprises de plus de vingt-cinq salariés", "huit jours"], "themes": []},
    "JORFTEXT000038496102": {  # loi 2019-486 PACTE
        "change": "L. 3262-2 : l'employeur émettant ses propres titres est dispensé du compte dédié quel que soit son effectif (le seuil de vingt-cinq salariés est supprimé).",
        "evidence": ["salariés lorsque l'effectif n'excède par vingt-cinq"], "themes": []},
    "JORFTEXT000036336033": {  # décret 2017-1819
        "change": "R. 3262-14 et R. 3262-34 : remplace le comité d'entreprise par le comité social et économique pour le reversement des titres perdus ou périmés.",
        "evidence": ["d'entreprise", "social et économique"], "themes": []},
    "JORFTEXT000035607348": {  # ordonnance 2017-1386
        "change": "L. 3262-1 : remplace le comité d'entreprise par le comité social et économique comme intermédiaire d'émission.",
        "evidence": ["d'entreprise", "social et économique"], "themes": []},
    "JORFTEXT000029001649": {  # décret 2014-551
        "change": "R. 3262-16 : l'attestation d'ouverture du compte titres-restaurant est remise au directeur départemental ou régional des finances publiques et non plus au directeur des impôts.",
        "evidence": ["impôts", "finances publiques"], "themes": []},
    "JORFTEXT000028690805": {  # décret 2014-294
        "change": "Autorise les titres dématérialisés (R. 3262-1, R. 3262-1-1, R. 3262-1-2) ; fixe la validité à l'année civile plus deux mois (R. 3262-5) ; plafonne l'usage à dix-neuf euros par jour avec débit de la somme exacte en dématérialisé (R. 3262-10) ; maintient l'interdiction le dimanche et les jours fériés sauf décision de l'employeur (R. 3262-8).",
        "evidence": ["sous forme dématérialisée", "et durant une période de deux mois à compter du 1er janvier de l'année suivante",
                     "est limitée à un montant maximum de dix-neuf euros par jour", "décision contraire"],
        "themes": [T_VALID, T_DIM, T_PLAF_R, T_PLAF_S], "context_themes": [T_PAPIER]},
    "JORFTEXT000023152756": {  # décret 2010-1460
        "change": "R. 3262-4 : le repas payé en titres peut être composé de préparations directement consommables, à réchauffer ou à décongeler, notamment de produits laitiers, et de fruits et légumes consommables ou non ; ajoute les détaillants en fruits et légumes à la Commission nationale (R. 3262-40).",
        "evidence": ["préparations alimentaires directement consommables , le cas échéant à réchauffer ou à décongeler , notamment de produits laitiers",
                     "de détaillants de fruits et légumes"], "themes": [T_REPAS]},
    "JORFTEXT000022521587": {  # loi 2010-874
        "change": "L. 3262-1 : le repas peut être acheté auprès de tout commerce mentionné à L. 3262-3 et être composé de fruits et légumes, directement consommables ou non.",
        "evidence": ["auprès d'une personne ou d'un organisme mentionné au deuxième alinéa de l'article L . 3262-3",
                     "qu'ils soient ou non directement consommables"], "themes": [T_REPAS]},
    "JORFTEXT000021902986": {  # décret 2010-220
        "change": "Étend la partie réglementaire aux détaillants en fruits et légumes (mentions, utilisation, remboursement, Commission nationale) et soumet les préparations vendues par les assimilés à un arrêté de composition et de prix (R. 3262-4).",
        "evidence": ["ou les détaillants en fruits et légumes", "préparation alimentaire immédiatement consommable dont la composition et le prix sont fixés par"],
        "themes": [T_REPAS]},
    "JORFTEXT000020879475": {  # loi 2009-879 HPST
        "change": "Ouvre les titres-restaurant aux détaillants en fruits et légumes (L. 3262-1, L. 3262-3, L. 3262-5).",
        "evidence": ["ou acheté chez un détaillant en fruits et légumes", "ou la profession de détaillant en fruits et légumes"],
        "themes": [T_REPAS]},
    "JORFTEXT000020014790": {  # loi 2008-1443 LFR 2008
        "change": "L. 3262-6 : l'exonération d'impôt sur le revenu de la contribution patronale renvoie désormais à la limite fixée au 19° de l'article 81 du CGI (le montant de 0,46 euro par titre disparaît du code du travail).",
        "evidence": ["de 0 , 46 euros par titre", "prévue au 19 ° dudit article"], "themes": []},
    "JORFTEXT000017942034": {  # loi 2008-67
        "change": "Ratifie la recodification : L. 3262-5 verse les titres périmés au budget des activités sociales et culturelles ; L. 3262-6 devient l'article d'exonération fiscale et sociale ; crée L. 3262-7 (décret en Conseil d'État).",
        "evidence": ["du comité d'entreprise , consacré aux", "est exonéré", "Un décret en Conseil d'Etat détermine les modalités d'application du présent titre"],
        "themes": []},
    "JORFTEXT000018442415": {  # décret 2008-244
        "change": "Recodification de la partie réglementaire : crée R. 3262-1 à R. 3262-46 (dont l'interdiction le dimanche sauf mention de l'employeur, R. 3262-8, et un titre par repas, R. 3262-10).",
        "evidence": ["ne sont pas utilisables les dimanches et jours fériés", "Un même repas ne peut être payé avec plusieurs titres-restaurant"],
        "themes": [], "codification": True},
    "JORFTEXT000000465978": {  # ordonnance 2007-329
        "change": "Recodification de la partie législative : crée L. 3262-1 à L. 3262-6 à partir de l'ordonnance n° 67-830, en vigueur le 1er mai 2008.",
        "evidence": ["Le titre-restaurant est un titre spécial de paiement remis par l'employeur aux salariés"],
        "themes": [], "codification": True},
}


def norm_words(t):
    return " ".join(words(t))


def derogations(arts):
    """Non-codified law articles that cite L3262-x and derogate from it (e.g. loi 2022-1158 art. 6)."""
    out = {}
    for versions in arts.values():
        for v in versions:
            if v["etat"] != "VIGUEUR":
                continue
            for link in get_article(v["id"]).get("lienCitations") or []:
                aid = link.get("articleId") or ""
                if link.get("natureText") != "LOI" or not aid.startswith("LEGIARTI"):
                    continue
                art = get_article(aid)
                if "dérogation" not in clean(art.get("texte")) or "3262" not in clean(art.get("texte")):
                    continue
                key = clean(link["textTitle"]).split(" - ")[0].replace("LOI n°", "Loi n° ") + " - art. " + str(art.get("num"))
                if key in out:
                    continue
                vs = []
                for av in sorted(art.get("articleVersions") or [], key=lambda x: x["dateDebut"] or 0):
                    if not av["id"].startswith("LEGIARTI"):
                        continue
                    full = get_article(av["id"])
                    start = day(av["dateDebut"])
                    mod = modifier_of(full, start)
                    if mod is None:  # original version: the law itself
                        mod = {"textCid": link["textCid"], "textTitle": link["textTitle"], "articleId": aid}
                    vs.append({"id": av["id"], "etat": av["etat"], "start": start, "end": day(av["dateFin"]),
                               "text": clean(full.get("texte")), "nota": clean(full.get("nota")), "modifier": mod})
                out[key] = vs
    return out


def senat_texts(prep):
    part = prep.split("Sénat :", 1)[1] if "Sénat :" in prep else ""
    return [{"num": n, "session": sess} for n, sess in re.findall(r"n° (\d+) \((\d{4}-\d{4})\)", part)]


def build(arts):
    derog = derogations(arts)
    allarts = {**arts, **derog}
    texts, out_articles = {}, {}
    for num, versions in allarts.items():
        out_articles[num] = []
        prev = None
        for v in versions:
            m = v["modifier"]
            cid = m["textCid"] if m else None
            info = text_info(cid) if cid else None
            if num in derog:
                aurl = f"https://www.legifrance.gouv.fr/loda/article_lc/{v['id']}"
            else:
                aurl = article_url(v["id"])
            entry = {"version_id": v["id"], "version_start": v["start"], "version_end": v["end"], "etat": v["etat"],
                     "url": aurl, "modified_by": None}
            if m:
                art_title = clean(m.get("textTitle"))
                entry["modified_by"] = {"title": info["title"], "id": cid, "nor": info["nor"], "date": info["date_signature"],
                                        "url": text_url(cid), "article": art_title.split(" - ", 1)[1] if " - " in art_title else None,
                                        "link_type": m.get("linkType")}
            out_articles[num].append(entry)
            if cid:
                if prev is None:
                    delta = v["text"]
                else:
                    rem, add = diff(prev["text"], v["text"], ctx=3)
                    delta = " | ".join(rem + add)
                t = texts.setdefault(cid, {"info": info, "articles": [], "deltas": [], "starts": []})
                if num not in t["articles"]:
                    t["articles"].append(num)
                t["deltas"].append(norm_words(delta))
                t["starts"].append(v["start"])
            prev = v
        # abrogation of the last version (e.g. R3262-20)
        last = versions[-1]
        if last["etat"] == "ABROGE":
            for link in get_article(last["id"]).get("lienModifications") or []:
                if link.get("linkType") == "ABROGE" and link.get("linkOrientation") == "cible":
                    cid = link["textCid"]
                    info = text_info(cid)
                    out_articles[num].append({"version_id": None, "version_start": last["end"], "version_end": None,
                                              "etat": "ABROGE", "url": None,
                                              "modified_by": {"title": info["title"], "id": cid, "nor": info["nor"],
                                                              "date": info["date_signature"], "url": text_url(cid),
                                                              "article": clean(link["textTitle"]).split(" - ", 1)[-1],
                                                              "link_type": "ABROGE"}})
                    t = texts.setdefault(cid, {"info": info, "articles": [], "deltas": [], "starts": []})
                    t["articles"].append(num)
                    t["deltas"].append(norm_words(last["text"]))
                    t["starts"].append(last["end"])

    missing = [c for c in texts if c not in CHANGES]
    if missing:
        raise SystemExit(f"no CHANGES entry for {missing}: run --diff and write one")
    out_texts = []
    for cid, t in texts.items():
        ch = CHANGES[cid]
        blob = " || ".join(t["deltas"])
        for ev in ch["evidence"]:
            if norm_words(ev) not in blob:
                raise SystemExit(f"{cid}: evidence not in diff: {ev!r}")
        prep = clean(post("/consult/jorf", {"textCid": cid}).get("prepWork") or "")
        out_texts.append({
            "title": t["info"]["title"], "id": cid, "nor": t["info"]["nor"], "date": t["info"]["date_signature"],
            "in_force": min(s for s in t["starts"] if s), "url": text_url(cid),
            "articles": t["articles"], "change": ch["change"], "evidence": ch["evidence"],
            "themes": ch["themes"], "context_themes": ch.get("context_themes", []),
            "codification": ch.get("codification", False),
            "senat_documents": senat_texts(prep), "prep_work": prep or None,
        })
    out_texts.sort(key=lambda x: (x["date"] or "", x["in_force"]), reverse=True)

    findings = make_findings(out_articles, out_texts)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump({
            "source": "Légifrance, API PISTE lf-engine-app (routes /search, /consult/getArticle, /consult/jorf)",
            "generated": dt.date.today().isoformat(),
            "scope": "Code du travail, chapitre « Titres-restaurant » : L. 3262-1 à L. 3262-7 et R. 3262-1 à R. 3262-46 "
                     "(aucun autre L. 3262-x ou R. 3262-x trouvé), plus les articles de loi non codifiés qui dérogent à ces articles.",
            "method": "Toutes les versions de chaque article ; le texte modificateur d'une version est son lien « cible » "
                      "publié le plus récemment avant le début de la version. Le résumé de chaque texte est rédigé à partir "
                      "du diff mot à mot entre versions ; les mots cités dans « evidence » sont vérifiés dans ce diff.",
            "articles": out_articles, "texts": out_texts, "findings": findings,
        }, f, ensure_ascii=False, indent=1)
    print(f"wrote {OUT}: {len(out_articles)} articles, {len(out_texts)} texts, {len(findings)} findings")


def make_findings(arts, texts):
    by = {t["id"]: t for t in texts}
    L = [t for t in texts if any(a.startswith("L3262") for a in t["articles"]) and not t["codification"]]
    last_L = max(L, key=lambda t: t["in_force"])
    assert last_L["id"] == "JORFTEXT000038496102", last_L["id"]
    derog = next(k for k in arts if "2022-1158" in k)
    dv = arts[derog]
    assert [v["modified_by"]["id"] for v in dv] == ["JORFTEXT000046186723", "JORFTEXT000048668803", "JORFTEXT000051018078"]
    assert dv[-1]["etat"] == "VIGUEUR"
    r10 = [v["modified_by"]["id"] for v in arts["R3262-10"]]
    assert r10[-2:] == ["JORFTEXT000028690805", "JORFTEXT000046343485"]
    assert arts["R3262-8"][-1]["modified_by"]["id"] == "JORFTEXT000028690805" and arts["R3262-8"][-1]["etat"] == "VIGUEUR"
    assert arts["R3262-5"][-1]["modified_by"]["id"] == "JORFTEXT000028690805" and arts["R3262-5"][-1]["etat"] == "VIGUEUR"
    s23 = [x["num"] for x in by["JORFTEXT000048668803"]["senat_documents"]]
    s25 = [x["num"] for x in by["JORFTEXT000051018078"]["senat_documents"]]
    assert "173" in s23 and "183" in s25
    assert "Aeschlimann" in by["JORFTEXT000048668803"]["prep_work"] and "Aeschlimann" in by["JORFTEXT000051018078"]["prep_work"]
    return [
        f"Depuis leur codification en 2008, les articles L. 3262-1 à L. 3262-7 n'ont été modifiés que par {len(L)} textes ; "
        "le dernier est la loi PACTE n° 2019-486 (L. 3262-2, en vigueur le 1er janvier 2020) : aucune loi de 2022 à 2025 n'a modifié ces articles.",
        "L'utilisation des titres pour tout produit alimentaire repose sur l'article 6 de la loi n° 2022-1158 du 16 août 2022, non codifié, "
        "prolongé deux fois (jusqu'au 31 décembre 2024 par la loi n° 2023-1252, puis jusqu'au 31 décembre 2026 par la loi n° 2025-56) ; "
        "dans sa version en vigueur, la dérogation prend fin le 31 décembre 2026.",
        "Le plafond journalier d'utilisation (R. 3262-10) est fixé par décret : créé à dix-neuf euros par le décret n° 2014-294 du 6 mars 2014, "
        "porté à vingt-cinq euros par le décret n° 2022-1266 du 29 septembre 2022 à compter du 1er octobre 2022.",
        "L'interdiction d'usage le dimanche et les jours fériés sauf décision de l'employeur (R. 3262-8) et la validité limitée à l'année civile "
        "plus deux mois (R. 3262-5) sont fixées par décret, dans la rédaction du décret n° 2014-294, inchangée depuis le 2 avril 2014.",
        "Les deux prolongations de la dérogation ont été examinées au Sénat sur les textes de commission n° 173 (2023-2024) et n° 183 (2024-2025), "
        "avec Mme Marie-Do Aeschlimann pour rapporteure (commission des affaires sociales) les deux fois.",
        "L'ouverture des titres aux fruits et légumes vient de la loi HPST n° 2009-879 (détaillants en fruits et légumes), "
        "élargie par la loi n° 2010-874 (fruits et légumes consommables ou non) et le décret n° 2010-1460 (préparations à réchauffer, produits laitiers).",
    ]


if __name__ == "__main__":
    main()
