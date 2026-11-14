"""One-off: criteria for the 34 pending amendments on titres-restaurant (Sénat n°142),
extracted by reading each amendment (Claude, 14/11/2026). Same schema as extract_criteria.py,
plus `effect`. Quotes are checked verbatim against the amendment text."""
import json, sys
from pathlib import Path

REPO = Path(sys.argv[1] if len(sys.argv) > 1 else ".")

RESTO = [{"naf": "56.10A", "label": "Restauration traditionnelle"},
         {"naf": "56.10C", "label": "Restauration de type rapide"}]
COMMERCE = [{"naf": "47.11B", "label": "Commerce d'alimentation générale"},
            {"naf": "47.11C", "label": "Supérettes"},
            {"naf": "47.24Z", "label": "Commerce de détail de pain, pâtisserie"},
            {"naf": "10.71C", "label": "Boulangerie et boulangerie-pâtisserie"}]
GMS = [{"naf": "47.11D", "label": "Supermarchés"},
       {"naf": "47.11F", "label": "Hypermarchés"}]
FRUITS = [{"naf": "47.21Z", "label": "Commerce de détail de fruits et légumes"}]
EMETTEURS = [{"naf": "", "label": "Émetteurs de titres-restaurant (4 acteurs > 99 % du marché ; pas de code NAF propre)"}]
PLATEFORMES = [{"naf": "", "label": "Plateformes de livraison de repas (pas de code NAF propre)"}]

COMMISSION_CAP = dict(sectors=RESTO + COMMERCE + EMETTEURS,
                      who="Restaurants et commerces alimentaires qui acceptent les titres (commissions plafonnées) ; émetteurs (revenus plafonnés)")
DOUBLE_CAP_REMOVED = dict(sectors=GMS + COMMERCE + RESTO,
                          who="Supermarchés et commerces alimentaires (plafond unique conservé) ; restaurants (perdent le plafond majoré)")
SUNDAY = dict(sectors=GMS + COMMERCE + RESTO,
              who="Commerces alimentaires et restaurants ouverts le dimanche")
ALL_EMPLOYERS = dict(sectors=[], who="Employeurs qui attribuent des titres-restaurant (tous secteurs)")
MEALS_ONLY = dict(sectors=GMS + FRUITS + RESTO,
                  who="Supermarchés (perdent les achats de produits à cuisiner) ; primeurs (fruits et légumes conservés) ; restaurants")
PLATFORM_BAN = dict(sectors=PLATEFORMES + [RESTO[1]],
                    who="Plateformes de livraison (exclues) ; restaurants qui vendent en livraison")
DEMAT_DELAY = dict(sectors=[{"naf": "18.12Z", "label": "Autre imprimerie (titres papier)"}] + EMETTEURS,
                   who="Imprimeurs de titres papier et émetteurs ; petites entreprises qui utilisent encore le papier")

C = {
 "1": dict(sectors=RESTO + COMMERCE, who="Commerces et restaurants qui rachètent des titres contre de l'argent (fraude)",
           effect="Amende administrative jusqu'à 15 000 € (ou double de la valeur des titres)",
           quote="Le fait, pour une personne ou un organisme acceptant des titres‑restaurant, de les accepter en contrepartie d’une somme d’argent"),
 "2": dict(**COMMISSION_CAP, effect="Plafond obligatoire des commissions : 2,5 %", quote="ne peut être supérieur à 2,5 %"),
 "3 rect.": dict(**COMMISSION_CAP, effect="Plafond des commissions rendu obligatoire (taux fixé par décret)",
                 quote="rendre obligatoire la fixation de ce plafond"),
 "4": dict(**COMMISSION_CAP, effect="Plafond obligatoire des commissions : 2,5 %", quote="dans la limite de 2,5 % du montant réglé au moyen de titres‑restaurant"),
 "5": dict(**COMMISSION_CAP, effect="Plafond obligatoire des commissions : 3 % (repli)", quote="dans la limite de 3 % du montant réglé au moyen de titres‑restaurant"),
 "6": dict(**DOUBLE_CAP_REMOVED, effect="Supprime le double plafond journalier", quote="Alinéas 38 et 39 Supprimer ces alinéas."),
 "7": dict(**SUNDAY, effect="Titres utilisables le dimanche par tous les salariés",
           quote="Les titres‑restaurant peuvent être utilisés le dimanche par l’ensemble des salariés bénéficiaires"),
 "9": dict(**COMMISSION_CAP, effect="Plafond obligatoire des commissions : 2,5 %", quote="ne peut être supérieur à 2,5 %"),
 "10": dict(**DOUBLE_CAP_REMOVED, effect="Supprime le double plafond journalier", quote="Alinéas 38 et 39 Supprimer ces alinéas."),
 "11": dict(sectors=[], who="Employeurs ayant au moins un délégué syndical (tous secteurs)",
            effect="Négociation obligatoire avant de mettre en place, supprimer ou modifier les titres",
            quote="Dans les entreprises pourvues d’au moins un délégué syndical"),
 "12": dict(**SUNDAY, effect="Titres utilisables tous les jours, dimanches et fériés compris",
            quote="Les titres‑restaurant peuvent être utilisés tous les jours de la semaine, y compris les dimanches et les jours fériés."),
 "13": dict(**ALL_EMPLOYERS, effect="Titres maintenus pendant les congés maternité, paternité, adoption, naissance",
            quote="L’attribution de titres‑restaurant ne peut être interrompue durant les périodes d’absence et de congé de maternité"),
 "14": dict(**COMMISSION_CAP, effect="Plafond obligatoire des commissions : 2 %", quote="qui ne peut excéder 2 %"),
 "15": dict(sectors=[{"naf": "47.29Z", "label": "Autres commerces de détail alimentaires (dont magasins bio)"}] + FRUITS,
            who="Commerces de produits bio et durables ; employeurs volontaires (bonification à leur charge)",
            effect="Crée un titre-restaurant bonifié pour les produits bio ou durables",
            quote="Le titre‑restaurant bonifié constitue une modalité particulière du titre‑restaurant"),
 "16": dict(sectors=GMS + COMMERCE, who="Supermarchés et commerces alimentaires (plus de plafond journalier, ouverture le dimanche)",
            effect="Supprime tout plafond journalier + utilisation tous les jours",
            quote="L’utilisation des titres‑restaurant n’est limitée à aucun montant maximal journalier."),
 "17": dict(found=False, sectors=EMETTEURS, who="Émetteurs (simple demande de rapport sur un monopole public)",
            effect="Rapport au Parlement sous 12 mois : aucune obligation directe",
            quote="le Gouvernement remet au Parlement un rapport"),
 "18": dict(**ALL_EMPLOYERS, effect="Titres maintenus pendant les congés maternité, paternité, adoption, naissance",
            quote="L’attribution de titres‑restaurant ne peut être interrompue durant les périodes d’absence et de congé de maternité"),
 "19": dict(sectors=RESTO + GMS, who="Restaurants (plafond majoré pour les repas) ; supermarchés (plafond réduit pour les produits à cuisiner)",
            effect="Rend effectif le double plafond : moins pour les courses, plus pour les repas",
            quote="L’utilisation des titres‑restaurant est soumise à un plafond journalier différencié selon la nature des produits ou prestations acquis."),
 "20": dict(**MEALS_ONLY, effect="Fin des achats de produits à cuisiner : repas, plats prêts et fruits et légumes seulement",
            quote="de préparations alimentaires directement consommables, ainsi que de fruits et légumes"),
 "21 rect.": dict(**PLATFORM_BAN, effect="Plateformes de livraison exclues des titres-restaurant",
                  quote="à l’exclusion des contrats conclus par l’intermédiaire d’une plateforme de mise en relation par voie électronique"),
 "22": dict(**COMMISSION_CAP, effect="Plafond obligatoire des commissions : 2,5 %", quote="ne peut être supérieur à 2,5 %"),
 "23": dict(**COMMISSION_CAP, effect="Plafond des commissions rendu obligatoire (taux fixé par décret)",
            quote="rendre obligatoire la fixation de ce plafond"),
 "24": dict(**MEALS_ONLY, effect="Fin des achats de produits à cuisiner : repas, plats prêts et fruits et légumes seulement",
            quote="de préparations alimentaires directement consommables ou de fruits et légumes"),
 "26": dict(**PLATFORM_BAN, effect="Plateformes de livraison exclues des titres-restaurant",
            quote="à l’exclusion des achats réalisés par l’intermédiaire d’une plateforme en ligne"),
 "27": dict(sectors=EMETTEURS + RESTO + COMMERCE, who="Émetteurs privés (nouveau concurrent public, l'ANCV) ; commerçants (commission ANCV ≤ 2,5 %)",
            effect="L'ANCV devient émetteur public, commissions ≤ 2,5 %",
            quote="Soit par l’Agence nationale pour les chèques‑vacances"),
 "28": dict(sectors=[{"naf": "94.99Z", "label": "Autres organisations fonctionnant par adhésion volontaire (associations)"}],
            who="Associations loi 1901 à gestion désintéressée qui servent des repas à leurs adhérents",
            effect="Commissions plafonnées à 2,5 % pour ces associations",
            quote="aux associations régies par la loi du 1 er juillet 1901"),
 "29": dict(**COMMISSION_CAP, effect="Plafond obligatoire des commissions : 2,5 %", quote="ne peut être supérieur à 2,5 %"),
 "31": dict(**SUNDAY, effect="Titres utilisables tous les jours, dimanches et fériés compris",
            quote="Les titres‑restaurant peuvent être utilisés tous les jours de la semaine, y compris les dimanches et les jours fériés."),
 "32": dict(sectors=EMETTEURS, who="Employeurs (ne récupèrent plus la contre-valeur des titres périmés) ; émetteurs",
            effect="Titres valables sans limite de durée",
            quote="Les titres‑restaurant sont valables sans limitation de durée."),
 "33": dict(sectors=EMETTEURS, who="Employeurs (titres périmés versés au budget du CSE) ; émetteurs",
            effect="Validité portée à 3 ans ; titres périmés versés au budget social et culturel",
            quote="Le délai d’utilisation du titre‑restaurant est de trois ans."),
 "34": dict(**DEMAT_DELAY, effect="Dématérialisation obligatoire repoussée à 2031",
            quote="entre en vigueur le 1 er janvier 2031"),
 "35": dict(**DEMAT_DELAY, effect="Dématérialisation obligatoire repoussée à 2030 (repli)",
            quote="entre en vigueur le 1 er janvier 2030"),
 "36": dict(**DEMAT_DELAY, effect="Dématérialisation obligatoire repoussée à 2029 (repli)",
            quote="entre en vigueur le 1 er janvier 2029"),
 "37": dict(found=False, sectors=[], who="",
            effect="Négociation interprofessionnelle sur l'avenir du titre : aucune obligation pour les entreprises",
            quote="engagent une négociation sur l’avenir du titre-restaurant"),
}

THEMES = {
 "Plafonner les commissions des émetteurs": ["2", "3 rect.", "4", "5", "9", "14", "22", "23", "29"],
 "Supprimer le double plafond journalier": ["6", "10", "16"],
 "Rendre effectif le double plafond journalier": ["19"],
 "Utilisation le dimanche": ["7", "12", "31", "16"],
 "Limiter aux repas et fruits et légumes": ["20", "24"],
 "Exclure les plateformes de livraison": ["21 rect.", "26"],
 "Repousser la fin des titres papier": ["34", "35", "36"],
 "Maintien pendant les congés familiaux": ["13", "18"],
 "Durée de validité des titres": ["32", "33"],
 "Pôle public d'émission (ANCV)": ["17", "27", "37"],
 "Sanctionner le rachat frauduleux": ["1"],
 "Négociation syndicale avant mise en place": ["11"],
 "Titre-restaurant bonifié (bio, durable)": ["15"],
 "Commissions plafonnées pour les associations": ["28"],
}
THEME_OF = {}
for t, nums in THEMES.items():
    for n in nums:
        THEME_OF.setdefault(n, []).append(t)

amendments = json.loads((REPO / "data/amendments_142.json").read_text())
out, problems = [], []
for a in amendments:
    c = C.get(a["number"])
    if c is None:
        problems.append(f"no criteria for n°{a['number']}")
        continue
    c = dict(c)
    found = c.pop("found", True)
    q = c["quote"]
    if q not in a["text"] and q not in a["purpose"]:
        problems.append(f"quote not verbatim for n°{a['number']}: {q[:60]}")
    out.append({**a, "criteria": {"criteria_found": found, "who": c["who"], "sectors": c["sectors"],
                                  "employee_min": None, "employee_max": None, "regions": [],
                                  "effect": c["effect"], "themes": THEME_OF.get(a["number"], []), "quote": q},
                "model": "claude (lecture manuelle, 14/11/2026)"})
extra = set(C) - {a["number"] for a in amendments}
if extra:
    problems.append(f"criteria for unknown amendments: {extra}")
print("\n".join(problems) or "all quotes verbatim, all amendments covered")
(REPO / "data/criteria_142.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
print(len(out), "written,", sum(o["criteria"]["criteria_found"] for o in out), "with criteria")
