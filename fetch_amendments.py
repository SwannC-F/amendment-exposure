"""Download a Sénat text's amendments and keep those not yet voted.

Usage: python3 fetch_amendments.py <session> <texte>     e.g. 2026-2027 142
Writes data/<session>/<texte>/amendments.json
(server.py imports SETTLED, clean, fetch, matricule, senator_groups: keep their signatures.)
"""
import csv
import html
import http.client
import json
import re
import sys
import urllib.request
from pathlib import Path

SESSION = "2026-2027"
URL = "https://www.senat.fr/amendements/{s}/{n}/jeu_complet_{s}_{n}.csv"
SENATORS_URL = "https://data.senat.fr/data/senateurs/ODSEN_GENERAL.csv"

# A "sort" containing one of these means the amendment is settled.
SETTLED = ("adopt", "rejet", "retir", "tomb", "non soutenu", "irrecevable", "satisfait")


def text_dir(session, n):
    return Path("data") / session / str(n)


def clean(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def download(url):
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return r.read().decode("latin-1")
        except (http.client.IncompleteRead, OSError):
            if attempt == 2:  # senat.fr sometimes truncates responses: last try with curl
                import subprocess
                return subprocess.run(["curl", "-sSf", "--retry", "3", "-m", "120", url],
                                      capture_output=True, check=True).stdout.decode("latin-1")


def senator_groups():
    """Matricule (lowercase, e.g. '07004j') -> political group, for sitting senators."""
    lines = [l for l in download(SENATORS_URL).splitlines() if not l.startswith("%")]
    return {r["Matricule"].lower(): r["Groupe politique"]
            for r in csv.DictReader(lines) if r["État"] == "ACTIF"}


def matricule(fiche_url):
    m = re.search(r"(\d{5}[a-z])\.html", fiche_url or "")
    return m.group(1) if m else None


def fetch(n, session=SESSION):
    raw = download(URL.format(s=session, n=n))
    lines = raw.splitlines()
    if lines and lines[0].startswith("sep="):
        lines = lines[1:]
    rows = list(csv.reader(lines, delimiter="\t"))
    header = [h.strip() for h in rows[0]]
    return [dict(zip(header, (c.strip() for c in r))) for r in rows[1:] if len(r) >= len(header) - 1]


TEXT_PAGE = "https://www.senat.fr/amendements/{s}/{n}/accueil.html"


def text_title(session, n):
    """Bill title from the Sénat amendments page, e.g. 'Proposition de loi : … – 1ère lecture'."""
    try:
        raw = download(TEXT_PAGE.format(s=session, n=n))  # decoded as latin-1 for the CSVs
        try:
            raw = raw.encode("latin-1").decode("utf-8")   # the HTML page is UTF-8
        except UnicodeError:
            pass
        page = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    except Exception:
        return None
    m = re.search(r"((?:Proposition|Projet) de loi[^\n]{5,250}?)(?:\s{2,}|$)", page)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else None


def write_text_meta(session, n):
    title = text_title(session, n)
    d = text_dir(session, n)
    d.mkdir(parents=True, exist_ok=True)
    (d / "text.json").write_text(json.dumps(
        {"session": session, "number": str(n), "chamber": "Sénat", "title": title,
         "url": TEXT_PAGE.format(s=session, n=n)}, ensure_ascii=False, indent=2))
    return title


def main(session, n):
    print("titre :", write_text_meta(session, n))
    rows = fetch(n, session)
    groups = senator_groups()
    out = []
    for r in rows:
        sort = r.get("Sort", "")
        if any(k in sort.lower() for k in SETTLED):
            continue
        out.append({
            "number": r.get("Numéro", ""),
            "article": r.get("Subdivision", ""),
            "author": r.get("Auteur", ""),
            "author_group": groups.get(matricule(r.get("Fiche Sénateur")), ""),
            "on_behalf_of": r.get("Au nom de", ""),
            "filed": r.get("Date de dépôt", ""),
            "status": sort,
            "text": clean(r.get("Dispositif", "")),
            "purpose": clean(r.get("Objet", "")),
            "url": r.get("Url amendement", ""),
        })
    d = text_dir(session, n)
    d.mkdir(parents=True, exist_ok=True)
    path = d / "amendments.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"{len(rows)} amendments, {len(out)} pending -> {path}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit("usage: python3 fetch_amendments.py <session> <texte>")
    main(sys.argv[1], sys.argv[2])
