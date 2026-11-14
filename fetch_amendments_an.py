"""Download an Assemblée nationale text's amendments in séance and keep those not yet voted.

Usage: python3 fetch_amendments_an.py <législature> <texte>     e.g. 17 2864
Writes data/an/<législature>/<texte>/amendments.json and text.json (same shape as the Sénat ones).

Sources, all public, no key:
- eLiasse (eliasse.assemblee-nationale.fr/api-eliasse): the examen of the text in séance and its
  dérouleur (every amendment with its sort; "Aucun"/empty = not voted yet).
- Assemblée open data, one JSON per amendment (www.assemblee-nationale.fr/dyn/opendata/<uid>.json):
  dispositif, exposé sommaire, date of filing, and the author's political group AT FILING TIME
  (signataires.auteur.groupePolitiqueRef).
- Group names: data.assemblee-nationale.fr AMO10 archive (organes of sitting deputies), cached
  in data/an/groupes.json.
"""
import http.client
import io
import json
import subprocess
import sys
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fetch_amendments import SETTLED, clean

ELIASSE = "https://eliasse.assemblee-nationale.fr/api-eliasse"
OPENDATA = "https://www.assemblee-nationale.fr/dyn/opendata/{uid}.json"
AMO = ("https://data.assemblee-nationale.fr/static/openData/repository/{leg}/amo/"
       "deputes_actifs_mandats_actifs_organes/AMO10_deputes_actifs_mandats_actifs_organes.json.zip")
SEANCE_ABRV = "AN"  # organe abbreviation of the séance publique in eLiasse


def text_dir(leg, n):
    return Path("data") / "an" / str(leg) / str(n)


def get(url, binary=False):
    """GET with retries; falls back to curl when urllib gets a truncated (chunked) response."""
    raw = None
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "amendment-exposure/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
            break
        except (OSError, http.client.HTTPException):
            pass
    if raw is None:
        raw = subprocess.run(["curl", "-sSf", "--retry", "2", "-m", "120", url],
                             capture_output=True, check=True).stdout
    return raw if binary else json.loads(raw.decode("utf-8"))


def group_names(leg):
    """PO ref -> political group name (e.g. 'Les Démocrates'), cached in data/an/groupes.json."""
    cache = Path("data") / "an" / "groupes.json"
    if cache.exists():
        return json.loads(cache.read_text())
    z = zipfile.ZipFile(io.BytesIO(get(AMO.format(leg=leg), binary=True)))
    out = {}
    for name in z.namelist():
        if "/organe/" in name and name.endswith(".json"):
            o = json.loads(z.read(name))["organe"]
            if o.get("codeType") == "GP":
                out[o["uid"]] = o.get("libelle", "")
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    return out


def find_examen(n):
    """The examen of text n in séance publique (else any examen still running)."""
    organes = {o["uid"]: o.get("abreviation") for o in get(f"{ELIASSE}/organes")}
    exams = [e for e in get(f"{ELIASSE}/examens") if e["texte"]["bibard"] == str(n)]
    exams.sort(key=lambda e: (organes.get(e["organeRef"]) != SEANCE_ABRV, e["statut"] != "En cours"))
    if not exams:
        sys.exit(f"texte {n} introuvable dans eLiasse (textes en cours d'examen seulement)")
    return exams[0]


def title_of(texte):
    uid, lib = texte["uid"], texte.get("libelle", "")
    kind = "Proposition de loi" if uid.startswith("PION") else "Projet de loi" if uid.startswith("PRJL") else ""
    return f"{kind} {lib[0].lower() + lib[1:]}".strip() if kind and lib else lib


def write_text_meta(leg, n, exam):
    title = title_of(exam["texte"])
    d = text_dir(leg, n)
    d.mkdir(parents=True, exist_ok=True)
    (d / "text.json").write_text(json.dumps(
        {"session": str(leg), "number": str(n), "chamber": "Assemblée nationale", "title": title,
         "url": f"https://www.assemblee-nationale.fr/dyn/{leg}/amendements?examen={exam['uid']}",
         "examen": exam["uid"]}, ensure_ascii=False, indent=2))
    return title


def main(leg, n):
    exam = find_examen(n)
    print("examen :", exam["uid"], exam["statut"])
    print("titre :", write_text_meta(leg, n, exam))
    places = get(f"{ELIASSE}/examens/{exam['uid']}/derouleur")["places"]
    listed = [(p.get("libelle", ""), a) for p in places for a in p.get("amendements", [])]
    pending = [(art, a) for art, a in listed
               if not any(k in (a.get("sort") or "").lower() for k in SETTLED)]
    groups = group_names(leg)

    def detail(item):
        art, a = item
        j = get(OPENDATA.format(uid=a["uid"]))
        cycle = j.get("cycleDeVie") or {}
        sort = cycle.get("sort") or {}
        sort = sort if isinstance(sort, str) else ""
        etat = ((cycle.get("etatDesTraitements") or {}).get("etat") or {}).get("libelle", "")
        auteur = (j.get("signataires") or {}).get("auteur") or {}
        body = (j.get("corps") or {}).get("contenuAuteur") or {}
        return {
            "number": a["numero"],
            "article": art,
            "author": clean((a.get("auteur") or {}).get("libelle", "")),
            "author_group": groups.get(auteur.get("groupePolitiqueRef") or "", ""),
            "on_behalf_of": "",
            "filed": cycle.get("dateDepot", ""),
            "status": sort or etat,
            "text": clean(body.get("dispositif", "")),
            "purpose": clean(body.get("exposeSommaire", "")),
            "url": f"https://www.assemblee-nationale.fr/dyn/{leg}/amendements/{n}/AN/{a['numero']}",
        }

    with ThreadPoolExecutor(8) as pool:
        out = list(pool.map(detail, pending))
    out = [a for a in out if not any(k in a["status"].lower() for k in SETTLED)]
    d = text_dir(leg, n)
    path = d / "amendments.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    missing = sum(1 for a in out if not a["author_group"])
    print(f"{len(listed)} amendments, {len(out)} pending -> {path}"
          + (f" ({missing} sans groupe)" if missing else ""))


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit("usage: python3 fetch_amendments_an.py <législature> <texte>")
    main(sys.argv[1], sys.argv[2])
