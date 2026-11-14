"""Sénat history of positions on titres-restaurant, from Ameli open data.

Usage: python3 history_ameli.py
Writes data/history/ameli.json

Sources (all public, senat.fr / data.senat.fr):
- per-text amendment CSV: https://www.senat.fr/amendements/[commissions/]<session>/<n>/jeu_complet_[commission_]<session>_<n>.csv
- group history: https://data.senat.fr/data/senateurs/ODSEN_HISTOGROUPES.csv
  -> the author's group ON THE FILING DATE (group_source "history").
  The CSV has no group column; "Au nom de" is used when it names a group.

Texts were found from the senat.fr dossiers and a full-text search of the
Sénat amendment base (Hémicycle, jeu senat_amendements, covers Oct. 2023 ->):
only these texts carry amendments on titres-restaurant. PLF 2023 (2022-2023
n°114) and PLFSS 2023 (2022-2023 n°96) were scanned: no titre-restaurant
amendment.

Classification is done by hand, amendment by amendment (CLASSIFY below),
after reading each dispositif/objet; every row keeps its senat.fr URL and a
quote of the dispositif so it can be checked.
"""
import csv
import html
import http.client
import json
import re
import urllib.request
from collections import defaultdict
from pathlib import Path

csv.field_size_limit(10**9)

HISTO_URL = "https://data.senat.fr/data/senateurs/ODSEN_HISTOGROUPES.csv"

# (session, number, stage, title, dossier url, filter)
# filter: None = keep every amendment (text entirely about titres-restaurant)
TEXTS = [
    ("2021-2022", "817", "commission", "Mesures d'urgence pour la protection du pouvoir d'achat (commission des affaires sociales)",
     "https://www.senat.fr/dossier-legislatif/pjl21-817.html", "tr"),
    ("2021-2022", "828", "seance", "Mesures d'urgence pour la protection du pouvoir d'achat (séance)",
     "https://www.senat.fr/dossier-legislatif/pjl21-817.html", "tr"),
    ("2022-2023", "96", "seance", "PLFSS pour 2023 (scanné, aucun amendement titres-restaurant)",
     "https://www.senat.fr/dossier-legislatif/plfss2023.html", "tr"),
    ("2022-2023", "114", "seance", "PLF pour 2023 (scanné, aucun amendement titres-restaurant)",
     "https://www.senat.fr/dossier-legislatif/pjlf2023.html", "tr"),
    ("2023-2024", "143", "commission", "Utilisation des titres-restaurant (prolongation 2024, commission)",
     "https://www.senat.fr/dossier-legislatif/ppl23-143.html", None),
    ("2023-2024", "173", "seance", "Utilisation des titres-restaurant (prolongation 2024, séance)",
     "https://www.senat.fr/dossier-legislatif/ppl23-143.html", None),
    ("2024-2025", "160", "commission", "Dérogation d'usage des titres-restaurant pour tout produit alimentaire (commission)",
     "https://www.senat.fr/dossier-legislatif/ppl24-160.html", None),
    ("2024-2025", "183", "seance", "Dérogation d'usage des titres-restaurant pour tout produit alimentaire (séance)",
     "https://www.senat.fr/dossier-legislatif/ppl24-160.html", None),
    ("2026-2027", "32", "commission", "Moderniser et rééquilibrer le fonctionnement du titre-restaurant (commission, même texte que le n°142)",
     "https://www.senat.fr/dossier-legislatif/ppl26-032.html", None),
]

TR = re.compile(r"titres?[\s‑-]restaurant|tickets?[\s‑-]restaurant|L\.\s?3262", re.I)

# Historical Ameli group codes -> sigles used in our feed (same group lineage).
SIGLE = {"UMP": "LR", "LREM": "RDPI", "SOC": "SER", "RTLI": "LIRT", "CRC": "CRCE-K",
         "UC": "UCI", "GEST": "GEST", "RDSE": "RDSE", "NI": "NI", "UNT": "UNT"}

# theme, stance ("pour" = goes in the direction of the theme's measure,
# "contre" = goes against it), note. Themes in criteria_142.json are reused
# when they fit; a few extra themes are needed for older debates.
LIMIT = "Limiter aux repas et fruits et légumes"
DOUBLE = "Rendre effectif le double plafond journalier"
COMM = "Plafonner les commissions des émetteurs"
EMIT = "Encadrer les émetteurs (agrément, transparence, sanctions)"
CLASSIFY = {
    ("2021-2022", "828", "81 rect. quater"): ("Élargir les bénéficiaires", "pour", "rapport sur l'élargissement des bénéficiaires des tickets-restaurant"),
    ("2021-2022", "828", "248 rect. bis"): ("Relever le plafond d'exonération", "pour", "exonération 5,69 € -> 7,50 €"),
    ("2021-2022", "828", "379 rect. bis"): ("Relever le plafond d'exonération", "pour", "exonération 5,69 € -> 7,50 €"),
    ("2021-2022", "817", "COM-8"): ("Relever le plafond d'exonération", "pour", "exonération 5,69 € -> 7,50 €"),
    ("2021-2022", "817", "COM-258 rect."): ("Relever le plafond d'exonération", "pour", "exonération 5,69 € -> 7,50 €"),
    ("2021-2022", "817", "COM-177"): (LIMIT, "contre", "crée la dérogation : titres utilisables pour tout produit alimentaire jusqu'au 31/12/2023"),
    ("2023-2024", "143", "COM-1 rect."): (LIMIT, "pour", "raccourcir la dérogation tout produit alimentaire au 30/06/2024"),
    ("2023-2024", "173", "1 rect. bis"): ("Négociation syndicale avant mise en place", "pour", "concertation syndicats/employeurs sur l'assouplissement du titre"),
    ("2023-2024", "173", "2 rect."): (LIMIT, "pour", "raccourcir la dérogation tout produit alimentaire au 30/06/2024"),
    ("2023-2024", "173", "3 rect."): (LIMIT, "pour", "raccourcir la dérogation tout produit alimentaire au 30/06/2024"),
    ("2024-2025", "160", "COM-1"): (LIMIT, "pour", "dérogation tout produit alimentaire prolongée jusqu'à fin 2025 seulement (au lieu de 2026)"),
    ("2024-2025", "160", "COM-2"): (DOUBLE, "pour", "plafonds d'utilisation différenciés selon le type de commerce"),
    ("2024-2025", "183", "1 rect."): (DOUBLE, "pour", "plafonds d'utilisation différenciés selon le type de commerce"),
    ("2024-2025", "183", "2 rect."): (LIMIT, "contre", "dérogation tout produit alimentaire prolongée jusqu'à fin 2026"),
    ("2024-2025", "183", "3 rect. quater"): (LIMIT, "contre", "dérogation tout produit alimentaire prolongée jusqu'à fin 2026"),
    ("2024-2025", "183", "4"): (LIMIT, "contre", "dérogation tout produit alimentaire prolongée jusqu'à fin 2026"),
    ("2024-2025", "183", "5 rect. bis"): (DOUBLE, "pour", "plafond illimité pour les repas au restaurant"),
    ("2026-2027", "32", "COM-1"): (COMM, "pour", "plafonnement obligatoire des commissions, 2,5 % maximum"),
    ("2026-2027", "32", "COM-2"): (COMM, "pour", "plafonnement obligatoire (« est plafonnée ») des commissions"),
    ("2026-2027", "32", "COM-3"): (EMIT, "pour", "agrément des sociétés émettrices"),
    ("2026-2027", "32", "COM-4"): (EMIT, "pour", "amende jusqu'à 1 % du CA pour les émetteurs (remises aux employeurs)"),
    ("2026-2027", "32", "COM-5"): ("Coordination rédactionnelle", "neutre", "coordination"),
    ("2026-2027", "32", "COM-6"): (EMIT, "pour", "précise les obligations de transparence tarifaire des émetteurs"),
    ("2026-2027", "32", "COM-7"): (COMM, "pour", "avis « motivé » avant plafonnement des commissions"),
    ("2026-2027", "32", "COM-8"): (COMM, "pour", "plafond calculé sur les coûts « en moyenne »"),
    ("2026-2027", "32", "COM-9"): (EMIT, "pour", "comptes de titres hébergés dans l'UE/EEE"),
    ("2026-2027", "32", "COM-10"): ("Exclure les plateformes de livraison", "contre", "supprime l'exclusion des plateformes de livraison"),
    ("2026-2027", "32", "COM-11"): ("Utilisation le dimanche", "contre", "supprime l'usage les dimanches et jours fériés"),
    ("2026-2027", "32", "COM-12"): (DOUBLE, "pour", "plafond journalier majoré pour repas, produits consommables, fruits et légumes"),
    ("2026-2027", "32", "COM-13"): ("Durée de validité des titres", "contre", "revient sur l'extension à trois ans de la validité"),
    ("2026-2027", "32", "COM-14"): ("Don de titres aux associations", "pour", "dons limités aux associations habilitées"),
    ("2026-2027", "32", "COM-15"): ("Don de titres aux associations", "pour", "sécurise le régime fiscal des dons de titres"),
    ("2026-2027", "32", "COM-16"): ("Maintien pendant les congés familiaux", "contre", "supprime l'attribution obligatoire pendant les congés liés à l'arrivée d'un enfant"),
    ("2026-2027", "32", "COM-17"): ("Calendrier d'entrée en vigueur", "neutre", "entrées en vigueur différenciées (2027)"),
    ("2026-2027", "32", "COM-18"): ("Rapport sur les titres perdus", "contre", "supprime la demande de rapport sur la contre-valeur des titres perdus"),
}

# Each finding lists the amendment keys (session, text, number) it rests on;
# main() checks that every one is in the output.
FINDINGS = [
    ("La dérogation « tout produit alimentaire » est née au Sénat : amendement COM-177 de la rapporteure Puissat (LR), déposé le 25/07/2022 et adopté en commission sur le projet de loi pouvoir d'achat.",
     [("2021-2022", "817", "COM-177")]),
    ("Restreindre de nouveau le titre aux repas a échoué en 2023 : UC, aujourd'hui UCI (Canévet) et GEST (Poncet Monge) ont proposé d'arrêter la dérogation au 30/06/2024, rejeté les deux fois (et rejeté aussi en commission, COM-1 GEST).",
     [("2023-2024", "173", "2 rect."), ("2023-2024", "173", "3 rect."), ("2023-2024", "143", "COM-1 rect.")]),
    ("En janvier 2025, RDSE (Guillotin), UC (Sollogoub) et RDPI (Iacovelli) ont fait adopter en séance la prolongation de la dérogation jusqu'à fin 2026, contre la commission qui avait voté (COM-1, rapporteure LR Aeschlimann) une fin en 2025.",
     [("2024-2025", "183", "2 rect."), ("2024-2025", "183", "3 rect. quater"), ("2024-2025", "183", "4"), ("2024-2025", "160", "COM-1")]),
    ("Le double plafond journalier (plafond différencié selon le commerce) a été proposé par Cambier (UC) en commission puis en séance en 2024-2025 sans être adopté (rejeté, puis non soutenu) ; la commission l'a adopté en 2026 (COM-12, rapporteure LR Puissat).",
     [("2024-2025", "160", "COM-2"), ("2024-2025", "183", "1 rect."), ("2026-2027", "32", "COM-12")]),
    ("Plafonnement des commissions des émetteurs : les deux versions obligatoires de Longeot (UCI) ont été rejetées en commission (amendements déposés le 02/11/2026), la commission préférant le plafonnement facultatif renforcé de sa rapporteure LR (COM-7, COM-8 adoptés).",
     [("2026-2027", "32", "COM-1"), ("2026-2027", "32", "COM-2"), ("2026-2027", "32", "COM-7"), ("2026-2027", "32", "COM-8")]),
    ("En commission (amendements déposés le 02/11/2026), la rapporteure LR a fait supprimer l'usage le dimanche, l'exclusion des plateformes de livraison, la validité de trois ans et le maintien pendant les congés familiaux présents dans le texte transmis par l'Assemblée : le texte de la commission arrive en séance sans ces quatre mesures.",
     [("2026-2027", "32", "COM-11"), ("2026-2027", "32", "COM-10"), ("2026-2027", "32", "COM-13"), ("2026-2027", "32", "COM-16")]),
    ("Relever le plafond d'exonération du titre (5,69 € -> 7,50 €) a été proposé en 2022 par Billon (UC) et Menonville (LIRT) : rejeté en commission, retiré en séance.",
     [("2021-2022", "817", "COM-8"), ("2021-2022", "817", "COM-258 rect."), ("2021-2022", "828", "248 rect. bis"), ("2021-2022", "828", "379 rect. bis")]),
]


def clean(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def download(url):
    for attempt in range(6):
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                return r.read().decode("latin-1")
        except (http.client.IncompleteRead, OSError):
            if attempt == 5:
                raise


def csv_url(session, n, stage):
    if stage == "commission":
        return f"https://www.senat.fr/amendements/commissions/{session}/{n}/jeu_complet_commission_{session}_{n}.csv"
    return f"https://www.senat.fr/amendements/{session}/{n}/jeu_complet_{session}_{n}.csv"


def rows(url):
    lines = download(url).splitlines()
    if lines and lines[0].startswith("sep="):
        lines = lines[1:]
    data = list(csv.reader(lines, delimiter="\t"))
    header = [h.strip() for h in data[0]]
    return [dict(zip(header, (c.strip() for c in r))) for r in data[1:] if len(r) >= len(header) - 1]


def group_history():
    """Matricule (lowercase) -> list of (start, end, code)."""
    lines = [l for l in download(HISTO_URL).splitlines() if not l.startswith("%")]
    out = defaultdict(list)
    for r in csv.DictReader(lines):
        out[r["Matricule"].lower()].append((r["Date de début d'appartenance"][:10] or "0000",
                                            r["Date de fin d'appartenance"][:10] or "9999",
                                            r["Code du groupe politique"]))
    return out


def group_at(hist, mat, date):
    for start, end, code in hist.get(mat, []):
        if start <= date <= end and code != "AUCUN":
            return SIGLE.get(code, code)
    return None


def outcome(sort):
    s = sort.lower()
    for key, val in (("adopt", "adopté"), ("rejet", "rejeté"), ("retir", "retiré"), ("tomb", "tombé"),
                     ("non soutenu", "non soutenu"), ("irrecevable", "irrecevable"), ("satisfait", "satisfait ou sans objet")):
        if key in s:
            return val
    return sort or "en attente"


def main():
    hist = group_history()
    texts, amendments = [], []
    for session, n, stage, title, dossier, filt in TEXTS:
        url = csv_url(session, n, stage)
        texts.append({"session": session, "number": n, "stage": stage, "title": title, "url": dossier, "csv": url})
        for r in rows(url):
            disp, obj = clean(r.get("Dispositif")), clean(r.get("Objet"))
            if filt and not TR.search(disp + " " + obj):
                continue
            num = r.get("Numéro", "")
            key = (session, n, num)
            if key not in CLASSIFY:
                print("not about titres-restaurant / unclassified, skipped:", key, disp[:80])
                continue
            theme, stance, note = CLASSIFY[key]
            date = r.get("Date de dépôt", "")
            m = re.search(r"(\d{5}[a-z])\.html", r.get("Fiche Sénateur", ""))
            group, source = None, None
            if m:
                group, source = group_at(hist, m.group(1), date), "history"
            if not group and "groupe" in r.get("Au nom de", "").lower():
                group, source = r["Au nom de"], "amendment"
            amendments.append({
                "session": session, "text_number": n, "stage": stage, "number": num,
                "year": int(date[:4]) if date else None, "filed": date,
                "theme": theme, "stance": stance, "note": note,
                "author": r.get("Auteur", ""), "group": group or "", "group_source": source or "unknown",
                "on_behalf_of": r.get("Au nom de", ""),
                "outcome": outcome(r.get("Sort", "")), "url": r.get("Url amendement", ""),
                "quote": disp[:280] + ("…" if len(disp) > 280 else ""),
            })
    keys = {(a["session"], a["text_number"], a["number"]) for a in amendments}
    missing = set(CLASSIFY) - keys
    assert not missing, f"classified but not found: {missing}"

    by_theme = defaultdict(lambda: defaultdict(lambda: {"filed": 0, "adopted": 0, "rejected": 0, "other": 0,
                                                         "pour": 0, "contre": 0, "years": set()}))
    for a in amendments:
        if a["stance"] == "neutre":
            continue
        g = by_theme[a["theme"]][a["group"] or "?"]
        g["filed"] += 1
        g[{"adopté": "adopted", "rejeté": "rejected"}.get(a["outcome"], "other")] += 1
        g[a["stance"]] += 1
        g["years"].add(a["year"])
    by_theme = {t: {grp: {**v, "years": sorted(v["years"])} for grp, v in gs.items()} for t, gs in by_theme.items()}

    findings, details = [], []
    for text, refs in FINDINGS:
        assert all(tuple(r) in keys for r in refs), f"finding not backed: {text}"
        findings.append(text)
        details.append({"text": text, "amendments": [{"session": s, "text_number": n, "number": num} for s, n, num in refs]})

    out = {
        "source": "Sénat, base Ameli (jeu_complet CSV par texte) et data.senat.fr ODSEN_HISTOGROUPES, Licence data.senat.fr",
        "notes": [
            "group = groupe du premier auteur à la date de dépôt (ODSEN_HISTOGROUPES), exprimé avec le sigle actuel de la même lignée : UMP->LR, LREM->RDPI, SOC->SER, RTLI->LIRT, CRC->CRCE-K, UC->UCI.",
            "Les cosignataires ne figurent pas dans le CSV Ameli : seul le premier auteur est compté.",
            "stance : « pour » va dans le sens de la mesure du thème, « contre » s'y oppose (ex. prolonger la dérogation tout produit alimentaire = contre « Limiter aux repas »).",
            "Les amendements COM-* du texte 2026-2027 n°32 sont l'étape commission du texte en séance n°142.",
            "Le portail Hémicycle (senat_amendements, depuis oct. 2023) ne trouve aucun autre texte avec des amendements titres-restaurant, PLF et PLFSS compris.",
        ],
        "texts": texts,
        "amendments": amendments,
        "by_theme": by_theme,
        "findings": findings,
        "findings_detail": details,
    }
    path = Path("data/history/ameli.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"{len(texts)} texts, {len(amendments)} amendments, {len(by_theme)} themes -> {path}")


if __name__ == "__main__":
    main()
