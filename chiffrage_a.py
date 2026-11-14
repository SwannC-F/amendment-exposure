"""Chiffrage (ordres de grandeur sourcés) pour 4 mesures de la PPL titres-restaurant (Sénat n° 142).

Écrit data/chiffrage/{commissions,plateformes,dimanche,papier}.json.

Règles : chaque paramètre vient d'une citation mot à mot (amendement ou source publique
nommée avec URL) ; toujours des fourchettes ; si un paramètre manque, total = null.
Les citations d'amendements sont vérifiées contre data/amendments_142.json.

Usage : python3 chiffrage_a.py            (utilise le CA figé ci-dessous)
        python3 chiffrage_a.py --refresh  (re-télécharge le CA via l'API Recherche d'entreprises)
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "chiffrage"
AMDTS = {str(a["number"]).split()[0]: a for a in json.load(open(ROOT / "data" / "amendments_142.json"))}

RAPPORT = "https://www.senat.fr/rap/l26-141/l26-141_mono.html"  # rapport n° 141 (2026-2027), F. Puissat
ADLC = "https://www.autoritedelaconcurrence.fr/en/press-release/meal-vouchers-autorite-de-la-concurrence-issues-opinion-government"
API = "https://recherche-entreprises.api.gouv.fr/search?q={}&per_page=1"
UA = "amendment-exposure/0.1 (hackathon prototype)"

# Chiffre d'affaires (champ results[0].finances), relevé le 14/11/2026.
FIN = {
    "322566043": {"name": "Hippopotamus (HIPPO EXPLOITATION)", "year": "2025", "ca": 77414755},
    "451321335": {"name": "Carrefour Hypermarchés", "year": "2025", "ca": 11312154354},
    "393365135": {"name": "Edenred France", "year": "2025", "ca": 711301164},
    "841983828": {"name": "Uber Eats France", "year": "2024", "ca": 1422065506},
}
HIPPO, CARREFOUR, EDENRED, UBER = "322566043", "451321335", "393365135", "841983828"


def refresh():
    for siren in FIN:
        req = urllib.request.Request(API.format(siren), headers={"User-Agent": UA})
        r = json.load(urllib.request.urlopen(req, timeout=20))["results"][0]
        year = max(r["finances"])
        FIN[siren].update(year=year, ca=r["finances"][year]["ca"])
        time.sleep(0.3)


def amdt_src(n):
    return f"amendement n°{n} | https:{AMDTS[n]['url']}"


def P(name, low, high, unit, quote, source):
    """Paramètre ; vérifie que la citation figure mot à mot dans l'amendement cité."""
    if source.startswith("amendement n°"):
        n = source.split("n°")[1].split()[0]
        a = AMDTS[n]
        assert quote in a["purpose"] or quote in a["text"], f"citation absente de l'amendement {n}: {quote}"
    return {"name": name, "low": low, "high": high, "unit": unit, "quote": quote, "source": source}


def rng(lo, hi):
    return {"low": round(lo), "high": round(hi)}


def ca_input(siren):
    f = FIN[siren]
    return {"ca_eur": f["ca"], "ca_year": f["year"], "ca_source": API.format(siren)}


def write(slug, doc):
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / f"{slug}.json", "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print(f"{slug}: total={doc['total_eur_per_year']}")


# ---------------------------------------------------------------- 1. commissions
def commissions():
    vol = P("Valeur faciale des titres émis par an", 10.8e9, 11e9, "€/an",
            "sa valeur atteint 10,8 milliards d'euros en 2024 | représenter un marché de 11 milliards d'euros",
            f"rapport Sénat n° 141 (2026-2027) | {RAPPORT}")
    r_avg_lo = P("Taux moyen actuel des commissions côté commerçant (bas)", 4, 4, "%",
                 "les commissions sur la face acceptation avoisinent 4 % en moyenne",
                 f"rapport Sénat n° 141 (2026-2027) | {RAPPORT}")
    r_avg_hi = P("Taux actuel des commissions côté commerçant (haut)", 5, 5, "%",
                 "les commissions et frais supportés par les commerçants atteignent aujourd’hui environ 5 % des montants encaissés",
                 amdt_src("22"))
    r_resto_lo = P("Taux négocié via une organisation professionnelle (restaurateurs)", 3, 3, "%",
                   "Les restaurateurs sont toutefois susceptibles d'obtenir des taux plus avantageux - autour de 3 % - en adhérant à une organisation professionnelle",
                   f"rapport Sénat n° 141 (2026-2027) | {RAPPORT}")
    part_ca_resto = P("Part du titre dans le CA des restaurants", 15, 15, "% du CA",
                      "le titre représente 15 % du chiffre d’affaires des restaurants, contre 1 % pour la grande distribution",
                      amdt_src("24"))
    part_ca_gms = P("Part du titre dans le CA de la grande distribution", 1, 1, "% du CA",
                    "le titre représente 15 % du chiffre d’affaires des restaurants, contre 1 % pour la grande distribution",
                    amdt_src("24"))
    pdm = P("Part de marché individuelle de chacun des 4 grands émetteurs (dont Edenred France)", 10, 40, "%",
            "with individual market share being between 10 and 40%",
            f"Autorité de la concurrence, avis 23-A-16 du 12/10/2023 (communiqué) | {ADLC}")
    caps = [
        P("Plafond 2 %", 2, 2, "%", "un plafonnement obligatoire déterminé par la loi d’une borne maximale de 2 %", amdt_src("14")),
        P("Plafond 2,5 %", 2.5, 2.5, "%", "il est proposé de fixer un plafond fixé à 2,5 % du montant réglé au moyen de titres‑restaurant", amdt_src("4")),
        P("Plafond 3 %", 3, 3, "%", "il est proposé de fixer un plafond fixé à 3 % du montant réglé au moyen de titres‑restaurant", amdt_src("5")),
    ]
    V_lo, V_hi = vol["low"], vol["high"]
    r_lo, r_hi = r_avg_lo["low"], r_avg_hi["high"]

    def total(cap):
        return rng(V_lo * max(0, r_lo - cap) / 100, V_hi * max(0, r_hi - cap) / 100)

    variants = [
        {"amendments": ["14"], "label": "plafond 2 %", "total_eur_per_year": total(2)},
        {"amendments": ["2", "4", "9", "22", "29"], "label": "plafond 2,5 %", "total_eur_per_year": total(2.5)},
        {"amendments": ["5"], "label": "plafond 3 %", "total_eur_per_year": total(3)},
        {"amendments": ["3 rect.", "23"], "label": "plafond obligatoire, taux fixé par décret", "total_eur_per_year": None},
    ]
    env = rng(V_lo * (r_lo - 3) / 100, V_hi * (r_hi - 2) / 100)  # du plus doux (3 %) au plus strict (2 %)

    def spread(cur_lo, cur_hi):
        return {f"cap_{c}": [max(0, cur_lo - c), max(0, cur_hi - c)] for c in (2, 2.5, 3)}

    def by_cap(base_lo, base_hi, cur_lo, cur_hi):
        return {f"plafond {c} %": rng(base_lo * max(0, cur_lo - c) / 100, base_hi * max(0, cur_hi - c) / 100)
                for c in (2, 2.5, 3)}

    h_tr = FIN[HIPPO]["ca"] * 0.15
    c_tr = FIN[CARREFOUR]["ca"] * 0.01
    per_profile = {
        HIPPO: {
            "eur_per_year": rng(h_tr * max(0, 3 - 3) / 100, h_tr * (5 - 2) / 100),
            "sign": "gain",
            "method": "CA × 15 % (part du titre dans le CA des restaurants) × (taux actuel 3 à 5 % − plafond 3 à 2 %)",
            "inputs": {**ca_input(HIPPO), "part_titre_ca": 0.15, "taux_actuel_pct": [3, 5],
                       "titres_encaisses_eur": round(h_tr), "par_variante": by_cap(h_tr, h_tr, 3, 5)},
        },
        CARREFOUR: {
            "eur_per_year": rng(c_tr * (4 - 3) / 100, c_tr * (5 - 2) / 100),
            "sign": "gain",
            "method": "CA × 1 % (part du titre dans le CA de la grande distribution) × (taux moyen 4 à 5 % − plafond 3 à 2 %)",
            "inputs": {**ca_input(CARREFOUR), "part_titre_ca": 0.01, "taux_actuel_pct": [4, 5],
                       "titres_encaisses_eur": round(c_tr), "par_variante": by_cap(c_tr, c_tr, 4, 5)},
        },
        EDENRED: {
            "eur_per_year": rng(V_lo * 0.10 * (r_lo - 3) / 100, V_hi * 0.40 * (r_hi - 2) / 100),
            "sign": "perte",
            "method": "volume national × part de marché 10 à 40 % × (taux moyen 4 à 5 % − plafond 3 à 2 %) ; perte brute avant report éventuel sur les employeurs",
            "inputs": {**ca_input(EDENRED), "volume_eur": [V_lo, V_hi], "part_de_marche": [0.10, 0.40],
                       "taux_actuel_pct": [r_lo, r_hi],
                       "par_variante": {f"plafond {c} %": rng(V_lo * 0.10 * max(0, r_lo - c) / 100, V_hi * 0.40 * (r_hi - c) / 100)
                                        for c in (2, 2.5, 3)}},
        },
        UBER: {
            "eur_per_year": None,
            "sign": "neutre",
            "method": "pas partie au flux de commissions émetteur → commerçant (la plateforme n'encaisse pas elle-même les titres)",
            "inputs": ca_input(UBER),
        },
    }
    write("commissions", {
        "theme": "Plafonner les commissions des émetteurs",
        "amendments": ["2", "3 rect.", "4", "5", "9", "14", "22", "23", "29"],
        "mechanism": "Les commerçants qui encaissent des titres paient aux émetteurs une commission sur chaque titre remboursé ; un plafond légal réduit ce que les émetteurs prélèvent et laisse l'écart aux restaurateurs et commerçants.",
        "winners": ["Restaurants (56.10A, 56.10C)", "Grande distribution et commerces alimentaires (47.11*)", "Boulangeries (10.71C, 47.24Z)"],
        "losers": ["Émetteurs de titres-restaurant (66.19B)"],
        "parameters": [vol, r_avg_lo, r_avg_hi, r_resto_lo, part_ca_resto, part_ca_gms, pdm] + caps,
        "total_eur_per_year": env,
        "per_profile": per_profile,
        "variants": variants,
        "not_computable": "Le total est une enveloppe de toutes les variantes chiffrables (plafond 3 % au plus doux, 2 % au plus strict). Sans taux dans la loi (n° 3 rect., 23), le montant dépend du décret : non chiffrable. Montant brut : les émetteurs peuvent reporter une partie de la baisse sur les frais facturés aux employeurs, et l'Autorité de la concurrence note qu'un plafond peut faire remonter vers lui les taux inférieurs.",
    })


# ---------------------------------------------------------------- 2. plateformes
def plateformes():
    params = [
        P("Valeur faciale des titres émis par an", 10.8e9, 11e9, "€/an",
          "sa valeur atteint 10,8 milliards d'euros en 2024 | représenter un marché de 11 milliards d'euros",
          f"rapport Sénat n° 141 (2026-2027) | {RAPPORT}"),
        P("Plateformes agréées comme acceptants aujourd'hui", 0, 0, "plateformes principales",
          "Les principales plateformes ne sont d'ailleurs pas agréées aujourd'hui",
          f"rapport Sénat n° 141 (2026-2027) | {RAPPORT}"),
    ]
    na = None
    write("plateformes", {
        "theme": "Exclure les plateformes de livraison",
        "amendments": ["21 rect.", "26"],
        "mechanism": "Les salariés ne pourraient plus payer en titres le repas commandé via une plateforme ; ces dépenses se reporteraient vers la salle, la vente à emporter ou la livraison assurée par le restaurant, et la plateforme perdrait sa commission sur ces commandes.",
        "winners": ["Restaurants vendant en salle, à emporter ou livrant eux-mêmes (56.10A, 56.10C)"],
        "losers": ["Plateformes de livraison (63.12Z)", "Restaurants vendant surtout via plateformes"],
        "parameters": params,
        "total_eur_per_year": na,
        "per_profile": {
            HIPPO: {"eur_per_year": na, "sign": "neutre", "method": "effet ambigu : perd les commandes livrées par plateforme payées en titres, peut les récupérer en salle ; aucune donnée publique sur la part livrée", "inputs": ca_input(HIPPO)},
            CARREFOUR: {"eur_per_year": na, "sign": "neutre", "method": "peu concerné : vente en magasin ; part des courses en ligne via plateforme payées en titres inconnue", "inputs": ca_input(CARREFOUR)},
            EDENRED: {"eur_per_year": na, "sign": "neutre", "method": "le volume de titres émis ne change pas ; seul le lieu de dépense change", "inputs": ca_input(EDENRED)},
            UBER: {"eur_per_year": na, "sign": "perte", "method": "perte de la commission sur les commandes payées en titres ; volume de ces commandes non publié", "inputs": ca_input(UBER)},
        },
        "variants": [
            {"amendments": ["21 rect."], "label": "plateformes de mise en relation (art. 242 bis CGI)", "total_eur_per_year": na},
            {"amendments": ["26"], "label": "plateformes en ligne (règlement UE 2022/2065)", "total_eur_per_year": na},
        ],
        "not_computable": "Aucune source publique trouvée sur le montant de titres-restaurant dépensés via les plateformes de livraison, ni sur le taux de commission des plateformes. Le rapport de la commission juge en outre la mesure soit déjà satisfaite (les frais de service et de livraison ne sont pas payables en titres), soit contraire au principe d'égalité.",
    })


# ---------------------------------------------------------------- 3. dimanche
def dimanche():
    params = [
        P("Employeurs ayant déjà ouvert l'usage dominical", 20, 30, "% des employeurs",
          "De 20 à 30 % des employeurs ont ouvert la possibilité",
          f"rapport Sénat n° 141 (2026-2027) | {RAPPORT}"),
        P("Employeurs ayant déjà ouvert l'usage dominical (amendement)", 20, 30, "% des employeurs",
          "20 à 30 % des employeurs ont déjà ouvert l’usage dominical à leurs salariés",
          amdt_src("31")),
        P("Nombre de titres inchangé", 0, 0, "titres supplémentaires",
          "Seul le jour d’utilisation est assoupli, sans incidence sur le nombre de titres ni sur leur régime social et fiscal.",
          amdt_src("7")),
    ]
    na = None
    write("dimanche", {
        "theme": "Utilisation le dimanche",
        "amendments": ["7", "12", "31"],
        "mechanism": "Le montant de titres émis ne change pas : une partie des dépenses se déplace vers les commerces et restaurants ouverts le dimanche (et les jours fériés pour n° 12 et 31), au détriment de ceux qui ferment ce jour-là.",
        "winners": ["Commerces alimentaires et grandes surfaces ouverts le dimanche (47.11*)", "Restaurants ouverts le dimanche (56.10A, 56.10C)"],
        "losers": ["Commerces fermés le dimanche (report de dépenses, non chiffré)"],
        "parameters": params,
        "total_eur_per_year": na,
        "per_profile": {
            HIPPO: {"eur_per_year": na, "sign": "gain", "method": "restaurant ouvert le dimanche : peut capter des dépenses dominicales ; part non publiée", "inputs": ca_input(HIPPO)},
            CARREFOUR: {"eur_per_year": na, "sign": "gain", "method": "hypermarchés ouverts le dimanche dans certaines zones : peut capter des courses dominicales ; part non publiée", "inputs": ca_input(CARREFOUR)},
            EDENRED: {"eur_per_year": na, "sign": "neutre", "method": "volume de titres émis inchangé (amendement n° 7)", "inputs": ca_input(EDENRED)},
            UBER: {"eur_per_year": na, "sign": "neutre", "method": "pas d'effet direct identifié", "inputs": ca_input(UBER)},
        },
        "variants": [
            {"amendments": ["7"], "label": "dimanche seulement", "total_eur_per_year": na},
            {"amendments": ["12", "31"], "label": "dimanches et jours fériés", "total_eur_per_year": na},
        ],
        "not_computable": "Mesure de répartition : le volume total ne change pas. Aucune source publique ne donne la part des dépenses en titres qui se ferait le dimanche, donc le montant déplacé entre commerces n'est pas chiffrable. Seul chiffre disponible : 20 à 30 % des employeurs l'autorisent déjà.",
    })


# ---------------------------------------------------------------- 4. papier
def papier():
    lost = P("Titres perdus ou périmés (contre-valeur, 2024)", 54.6e6, 54.6e6, "€/an",
             "leur contre-valeur totale atteignait 54,6 millions d'euros en 2024, soit 0,5 % de la valeur agrégée du millésime",
             f"rapport Sénat n° 141 (2026-2027) | {RAPPORT}")
    q86 = "86 % de ce montant était concentré sur les titres-restaurant papier, qui ne représentent pourtant que 20 % du marché la même année"
    share_lost_paper = P("Part des titres perdus qui sont des titres papier (2024)", 86, 86, "% des pertes", q86,
                         f"rapport Sénat n° 141 (2026-2027) | {RAPPORT}")
    share_paper = P("Part du papier dans le marché (2024)", 20, 20, "% de la valeur émise", q86,
                    f"rapport Sénat n° 141 (2026-2027) | {RAPPORT}")
    vol = P("Valeur faciale des titres émis en 2024", 10.8e9, 10.8e9, "€/an",
            "sa valeur atteint 10,8 milliards d'euros en 2024",
            f"rapport Sénat n° 141 (2026-2027) | {RAPPORT}")
    trend = P("Recul spontané du papier", 10, 10, "points de part de marché par an",
              "le titre-restaurant papier perd depuis lors environ 10 points de part de marché par an",
              f"rapport Sénat n° 141 (2026-2027) | {RAPPORT}")
    dest = P("Destinataire des titres perdus", 0, 0, "-",
             "un titre non utilisé à l’échéance est définitivement perdu et sa contre‑valeur revient à l’employeur",
             amdt_src("32"))
    V = vol["low"]
    paper_v, demat_v = V * 0.20, V * 0.80
    lost_paper, lost_demat = lost["low"] * 0.86, lost["low"] * 0.14
    rate_p, rate_d = lost_paper / paper_v, lost_demat / demat_v
    excess_hi = paper_v * (rate_p - rate_d)  # si le papier restait à 20 % du marché (niveau 2024)
    tot = rng(0, excess_hi)

    def cum(n):
        return f"cumul {n} an(s) : 0 à {round(excess_hi * n / 1e6)} M€"

    write("papier", {
        "theme": "Repousser la fin des titres papier",
        "amendments": ["34", "35", "36"],
        "mechanism": "Tant que des titres papier circulent, les salariés en perdent bien plus qu'en carte (titres périmés) ; leur contre-valeur va au budget des activités sociales et culturelles (CSE ; l'entreprise à défaut de CSE), après un prélèvement de l'émetteur (L. 3262-5, R. 3262-13 et R. 3262-14). Repousser l'obligation de dématérialisation prolonge ces pertes des salariés, et l'activité des imprimeurs de titres.",
        "winners": ["CSE / budget des activités sociales et culturelles (entreprise à défaut de CSE)", "Émetteurs (prélèvement sur les titres périmés, R. 3262-13)", "Imprimeurs de titres papier (18.12Z, non chiffré)"],
        "losers": ["Salariés bénéficiaires de titres papier"],
        "parameters": [lost, share_lost_paper, share_paper, vol, trend, dest],
        "total_eur_per_year": tot,
        "per_profile": {
            HIPPO: {"eur_per_year": None, "sign": "perte", "method": "continue à traiter des titres papier (envois, délais) ; coût par commerçant non publié", "inputs": ca_input(HIPPO)},
            CARREFOUR: {"eur_per_year": None, "sign": "perte", "method": "continue à traiter des titres papier en caisse ; coût non publié", "inputs": ca_input(CARREFOUR)},
            EDENRED: {"eur_per_year": None, "sign": "neutre", "method": "garde une offre papier ; prélève une part de la contre-valeur des titres périmés (R. 3262-13), montant non publié", "inputs": ca_input(EDENRED)},
            UBER: {"eur_per_year": None, "sign": "neutre", "method": "titres papier non utilisables en ligne : pas d'effet direct", "inputs": ca_input(UBER)},
        },
        "variants": [
            {"amendments": ["36"], "label": f"papier autorisé pour 2028 ({cum(1)})", "total_eur_per_year": tot},
            {"amendments": ["35"], "label": f"papier autorisé pour 2028-2029 ({cum(2)})", "total_eur_per_year": tot},
            {"amendments": ["34"], "label": f"papier autorisé pour 2028-2030 ({cum(3)})", "total_eur_per_year": tot},
        ],
        "not_computable": "Haut de fourchette : surcroît de titres perdus si le papier restait à 20 % du marché (niveau 2024) : taux de perte papier ≈ {:.2f} % contre ≈ {:.2f} % en carte. Bas = 0 : au rythme de −10 points par an, le papier pourrait avoir disparu spontanément en 2028. Les coûts des commerçants et le chiffre d'affaires des imprimeurs ne sont pas chiffrables faute de source.".format(rate_p * 100, rate_d * 100),
    })


if __name__ == "__main__":
    if "--refresh" in sys.argv:
        refresh()
    commissions()
    plateformes()
    dimanche()
    papier()
