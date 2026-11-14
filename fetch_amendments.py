"""Download a Sénat text's amendments and keep those not yet voted.

Usage: python3 fetch_amendments.py 142
Writes data/amendments_<n>.json
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


def clean(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def download(url):
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return r.read().decode("latin-1")
        except (http.client.IncompleteRead, OSError):
            if attempt == 2:
                raise


def senator_groups():
    """Matricule (lowercase, e.g. '07004j') -> political group, for sitting senators."""
    lines = [l for l in download(SENATORS_URL).splitlines() if not l.startswith("%")]
    return {r["Matricule"].lower(): r["Groupe politique"]
            for r in csv.DictReader(lines) if r["État"] == "ACTIF"}


def matricule(fiche_url):
    m = re.search(r"(\d{5}[a-z])\.html", fiche_url or "")
    return m.group(1) if m else None


def fetch(n):
    raw = download(URL.format(s=SESSION, n=n))
    lines = raw.splitlines()
    if lines and lines[0].startswith("sep="):
        lines = lines[1:]
    rows = list(csv.reader(lines, delimiter="\t"))
    header = [h.strip() for h in rows[0]]
    return [dict(zip(header, (c.strip() for c in r))) for r in rows[1:] if len(r) >= len(header) - 1]


def main(n):
    rows = fetch(n)
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
    Path("data").mkdir(exist_ok=True)
    path = Path(f"data/amendments_{n}.json")
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"{len(rows)} amendments, {len(out)} pending -> {path}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "142")
