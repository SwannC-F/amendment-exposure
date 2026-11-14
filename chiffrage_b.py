"""Chiffrage (sourced € ranges) for 4 measures of Sénat bill n°142 (titres-restaurant).

Writes data/chiffrage/{double-plafond,validite,repas,conges}.json.
Stdlib only. Every parameter carries a verbatim quote; quotes attributed to an
amendment are checked against data/amendments_142.json (script fails otherwise).
Company revenue: recherche-entreprises.api.gouv.fr (fetched live; cached copy
below so the run is reproducible offline, use --refresh to re-fetch).
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "chiffrage"
AMDTS = {str(a["number"]).split()[0]: a for a in json.load(open(ROOT / "data" / "amendments_142.json"))}
API = "https://recherche-entreprises.api.gouv.fr/search?q={}&per_page=1"
UA = "amendment-exposure/0.1 (hackathon prototype)"

HIPPO, CARREFOUR, EDENRED, UBER = "322566043", "451321335", "393365135", "841983828"
# Fetched 14/11/2026 from API (results[0].finances); latest year available.
FIN_CACHE = {
    HIPPO: {"year": "2025", "ca": 77414755},
    CARREFOUR: {"year": "2025", "ca": 11312154354},
    EDENRED: {"year": "2025", "ca": 711301164},
    UBER: {"year": "2024", "ca": 1422065506},
}


def fetch_finances():
    out = {}
    for siren in FIN_CACHE:
        req = urllib.request.Request(API.format(siren), headers={"User-Agent": UA})
        r = json.load(urllib.request.urlopen(req, timeout=20))["results"][0]
        year = max(r["finances"])
        out[siren] = {"year": year, "ca": r["finances"][year]["ca"]}
        time.sleep(0.3)
    return out


FIN = fetch_finances() if "--refresh" in sys.argv else FIN_CACHE


def src(n):
    return f"amendment n°{n}"


def P(name, low, high, unit, quote, source):
    """Parameter; checks the quote is verbatim in the cited amendment."""
    if source.startswith("amendment n°"):
        num = source.split("°")[1]
        a = AMDTS[num]
        if quote not in a["purpose"] and quote not in a["text"]:
            raise SystemExit(f"quote not found in amendment {num}: {quote!r}")
    return {"name": name, "low": low, "high": high, "unit": unit, "quote": quote, "source": source}


def rng(lo, hi):
    lo, hi = sorted((lo, hi))
    return {"low": round(lo), "high": round(hi)}


def ca_param(siren, label):
    f = FIN[siren]
    return P(f"Chiffre d'affaires {label} ({f['year']})", f["ca"], f["ca"], "€",
             f"finances.{f['year']}.ca = {f['ca']}", API.format(siren))


# ---------------------------------------------------------------- shared parameters
MARKET = P("Valeur des titres émis par an", 8.5e9, 11e9, "€/an",
           "Leur valeur faciale totale s’élevait à près de 8,5 milliards d’euros en 2022", src(4))
MARKET_Q2 = P("Valeur des titres émis par an (2026, borne haute)", 11e9, 11e9, "€/an",
              "six millions de salariés, onze milliards d’euros de titres", src(1))
SHARE = P("Part des restaurateurs dans la valeur des titres (fin 2022 → début 2026)", 0.343, 0.465, "part",
          "La part des restaurateurs dans la valeur des titres est passée de 46,5 % fin 2022 à 34,3 % début 2026.", src(24))
RESTO_RATE = P("Poids du titre dans le CA des restaurants", 0.15, 0.15, "part du CA",
               "le titre représente 15 % du chiffre d’affaires des restaurants, contre 1 % pour la grande distribution", src(24))
GD_RATE = P("Poids du titre dans le CA de la grande distribution", 0.01, 0.01, "part du CA",
            "le titre représente 15 % du chiffre d’affaires des restaurants, contre 1 % pour la grande distribution", src(24))
COMMISSION = P("Commission des émetteurs sur les montants remboursés", 0.04, 0.042, "part",
               "Quatre émetteurs se partagent plus de 99 % du marché et prélèvent environ 4 % aux restaurateurs et commerçants.", src(27))
COMMISSION_EDENRED = P("Commission Edenred sur titres dématérialisés (2022)", 0.042, 0.042, "part",
                       "de 4,10 % à 4,20 % chez Edenred", src(4))
M_LO, M_HI = MARKET["low"], MARKET_Q2["high"]
S_NOW, S_2022 = 0.343, 0.465
HIPPO_TR = FIN[HIPPO]["ca"] * 0.15          # titres encaissés estimés par Hippopotamus
CARREFOUR_TR = FIN[CARREFOUR]["ca"] * 0.01  # titres encaissés estimés par Carrefour Hypermarchés


def write(slug, obj):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{slug}.json").write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
    print(slug, json.dumps(obj["total_eur_per_year"]),
          {k: (v["sign"], v["eur_per_year"]) for k, v in obj["per_profile"].items()})


# ---------------------------------------------------------------- 1. double plafond
# Flow at stake = drift of restaurants' share since end-2022 applied to annual issuance.
shift_lo, shift_hi = (S_2022 - S_NOW) * M_LO, (S_2022 - S_NOW) * M_HI
# What a restaurant could recover if the share went back to 46,5 %: +(46,5/34,3 - 1) of its current titres.
hippo_up = HIPPO_TR * (S_2022 / S_NOW - 1)
# What a non-restaurant acceptor would lose: -(1 - 53,5/65,7) of its current titres.
carrefour_up = CARREFOUR_TR * (1 - (1 - S_2022) / (1 - S_NOW))
write("double-plafond", {
    "theme": "Supprimer le double plafond journalier",
    "amendments": [6, 10, 16, 19],
    "mechanism": "Le double plafond (texte de la commission) réduit la part des titres payable en produits à cuisiner, ce qui peut ramener vers les restaurants une partie des titres aujourd'hui dépensés en grande distribution ; le supprimer (n° 6, 10, 16) laisse ce flux en grande distribution, le rendre effectif (n° 19) l'en retire.",
    "winners": ["Grande distribution et commerces alimentaires (si suppression)", "Salariés qui cuisinent leurs repas (si suppression)"],
    "losers": ["Restaurants (si suppression : manque à gagner par rapport au texte de la commission)"],
    "parameters": [
        MARKET, MARKET_Q2, SHARE, RESTO_RATE, GD_RATE,
        P("Plafond journalier actuel", 25, 25, "€/jour",
          "Aujourd’hui les titres‑restaurants sont limités à un plafond d’utilisation de 25 € par jour.", src(16)),
        P("Plafond produits à cuisiner proposé par n° 19 (illustration 2026)", 12.20, 12.20, "€/jour",
          "cette référence correspond à 12,20 euros en 2026", src(19)),
        P("Scénario où le double plafond ne change rien", 25, 50, "€/jour (cuisine / restauration)",
          "le pouvoir réglementaire pourrait fixer un plafond de 25 euros pour les produits alimentaires non directement consommables et un plafond de 50 euros pour la restauration. Une telle situation respecterait formellement le principe d’un double plafond, mais ne modifierait en rien les possibilités actuelles d’utilisation des titres‑restaurant dans la grande distribution.", src(19)),
        ca_param(HIPPO, "Hippopotamus"), ca_param(CARREFOUR, "Carrefour Hypermarchés"),
    ],
    "total_eur_per_year": rng(0, shift_hi),
    "per_profile": {
        HIPPO: {"eur_per_year": rng(0, hippo_up), "sign": "perte",
                "method": "Suppression = manque à gagner jusqu'au retour de la part des restaurants à 46,5 % : CA × 15 % × (46,5/34,3 − 1) ; borne basse 0 si les plafonds du décret ne contraignent rien (25 €/50 €).",
                "inputs": {"ca": FIN[HIPPO]["ca"], "titres_encaisses_estimes": round(HIPPO_TR), "taux_titre_ca": 0.15, "part_2022": S_2022, "part_2026": S_NOW}},
        CARREFOUR: {"eur_per_year": rng(0, carrefour_up), "sign": "gain",
                    "method": "Suppression = perte évitée : CA × 1 % × (1 − 53,5/65,7), part hors restaurants ramenée de 65,7 % à 53,5 % au plus ; borne basse 0 (plafonds 25 €/50 €).",
                    "inputs": {"ca": FIN[CARREFOUR]["ca"], "titres_encaisses_estimes": round(CARREFOUR_TR), "taux_titre_ca": 0.01, "part_hors_resto_2022": round(1 - S_2022, 3), "part_hors_resto_2026": round(1 - S_NOW, 3)}},
        EDENRED: {"eur_per_year": None, "sign": "neutre",
                  "method": "La commission (~4 %) porte sur le volume total, qui ne change pas : seul le lieu de dépense bouge. Coût d'adaptation des systèmes (n° 6, n° 19) non chiffré.",
                  "inputs": {"commission": 0.04}},
        UBER: {"eur_per_year": None, "sign": "perte",
               "method": "Les repas livrés relèvent du plafond « repas » ; la suppression leur retire un report possible de dépenses, mais aucune source ne donne la part des titres dépensée via les plateformes.",
               "inputs": {"ca": FIN[UBER]["ca"]}},
    },
    "variants": [
        {"amendments": [6, 10], "label": "Suppression du double plafond, plafond unique réglementaire maintenu (25 €/jour) : 0 à 1,3 Md€/an restent en grande distribution (borne haute = glissement observé depuis fin 2022)",
         "total_eur_per_year": rng(0, shift_hi)},
        {"amendments": [16], "label": "Suppression de tout plafond journalier et usage le dimanche : au moins l'effet de n° 6/10, effet supplémentaire de la levée des 25 € non chiffrable",
         "total_eur_per_year": None},
        {"amendments": [19], "label": "Double plafond rendu effectif (≤ 12,20 € pour les produits à cuisiner) : flux vers les restaurants plafonné par le glissement observé (1,0 à 1,3 Md€/an), borne basse non chiffrable",
         "total_eur_per_year": None},
    ],
    "not_computable": None,
})

# ---------------------------------------------------------------- 2. validité
EXPIRED = 54.6e6
PAPER = 0.86
exp_lo, exp_hi = EXPIRED * (1 - PAPER), EXPIRED  # paper gone (commission's argument) vs paper stays


def acceptor_share(rev_titres):
    """Range of the profile's share of all titres spent (market 8,5–11 Md€)."""
    return rev_titres / M_HI, rev_titres / M_LO


h_lo, h_hi = acceptor_share(HIPPO_TR)
c_lo, c_hi = acceptor_share(CARREFOUR_TR)
write("validite", {
    "theme": "Durée de validité des titres",
    "amendments": [32, 33],
    "mechanism": "Les titres non utilisés à l'échéance sont perdus pour le salarié ; sans date limite (n° 32) ou avec 3 ans et contre-valeur au budget des activités sociales et culturelles (n° 33), cette valeur reste aux salariés et est dépensée chez les commerçants au lieu de revenir à l'employeur.",
    "winners": ["Salariés bénéficiaires", "Budget des activités sociales et culturelles / CSE (n° 33)", "Restaurants et commerces qui encaissent les titres"],
    "losers": ["Employeurs qui récupèrent la contre-valeur des titres périmés (selon n° 32)"],
    "parameters": [
        P("Titres perdus ou périmés par an (2024)", EXPIRED, EXPIRED, "€/an",
          "Cela représentait 54,6 millions d’euros en 2024, soit 0,5 % de la valeur des titres émis, dont 86 % sur les seuls titres papier.", src(32)),
        P("Part des titres périmés venant du papier", PAPER, PAPER, "part",
          "dont 86 % sur les titres papier, qui ne représentent que 20 % du marché", src(33)),
        P("Destination actuelle de la contre-valeur", None, None, "texte",
          "un titre non utilisé à l’échéance est définitivement perdu et sa contre‑valeur revient à l’employeur.", src(32)),
        P("Argument de la commission (borne basse : papier supprimé)", None, None, "texte",
          "supprimé en commission au motif que la dématérialisation rendrait la mesure sans effet", src(33)),
        MARKET, MARKET_Q2, RESTO_RATE, GD_RATE, COMMISSION,
        ca_param(HIPPO, "Hippopotamus"), ca_param(CARREFOUR, "Carrefour Hypermarchés"),
    ],
    "total_eur_per_year": rng(exp_lo, exp_hi),
    "per_profile": {
        HIPPO: {"eur_per_year": rng(exp_lo * h_lo, exp_hi * h_hi), "sign": "gain",
                "method": "Titres sauvés × part d'Hippopotamus dans les titres dépensés (CA × 15 % / 8,5–11 Md€). Effet employeur (s'il distribue des titres) non connu.",
                "inputs": {"titres_sauves": [round(exp_lo), round(exp_hi)], "titres_encaisses_estimes": round(HIPPO_TR), "part_marche": [round(h_lo, 5), round(h_hi, 5)]}},
        CARREFOUR: {"eur_per_year": rng(exp_lo * c_lo, exp_hi * c_hi), "sign": "gain",
                    "method": "Titres sauvés × part de Carrefour Hypermarchés dans les titres dépensés (CA × 1 % / 8,5–11 Md€). Effet employeur non connu.",
                    "inputs": {"titres_sauves": [round(exp_lo), round(exp_hi)], "titres_encaisses_estimes": round(CARREFOUR_TR), "part_marche": [round(c_lo, 5), round(c_hi, 5)]}},
        EDENRED: {"eur_per_year": None, "sign": "gain",
                  "method": "Commission ~4 % sur le volume supplémentaire remboursé : 0,3 à 2,3 M€/an pour l'ensemble des émetteurs ; la part de marché d'Edenred n'est pas sourcée. n° 33 autorise des prélèvements par décret.",
                  "inputs": {"commission": [0.04, 0.042], "tous_emetteurs_eur": [round(exp_lo * 0.04), round(exp_hi * 0.042)]}},
        UBER: {"eur_per_year": None, "sign": "gain",
               "method": "Encaisse une partie des titres dépensés en livraison de repas ; part non sourcée.",
               "inputs": {"ca": FIN[UBER]["ca"]}},
    },
    "variants": [
        {"amendments": [32], "label": "Titres sans limite de durée : toute la valeur aujourd'hui perdue reste aux salariés",
         "total_eur_per_year": rng(exp_lo, exp_hi)},
        {"amendments": [33], "label": "Validité 3 ans, contre-valeur des titres encore périmés versée au budget des activités sociales et culturelles : même enveloppe, partagée entre salariés et CSE (répartition non chiffrable)",
         "total_eur_per_year": rng(exp_lo, exp_hi)},
    ],
    "not_computable": None,
})

# ---------------------------------------------------------------- 3. repas
write("repas", {
    "theme": "Limiter aux repas et fruits et légumes",
    "amendments": [20, 24],
    "mechanism": "À partir de 2028 (n° 20) ou dès l'entrée en vigueur (n° 24), les titres ne paient plus que des repas, des préparations directement consommables et des fruits et légumes : les dépenses de produits à cuisiner payées en titres quittent la grande distribution, une partie revient aux restaurants.",
    "winners": ["Restaurants et commerces de restauration", "État (écart de taux de TVA, selon n° 24)"],
    "losers": ["Grande distribution", "Salariés qui paient leurs courses en titres"],
    "parameters": [
        MARKET, MARKET_Q2, SHARE, RESTO_RATE, GD_RATE,
        P("Emplois liés au titre dans la restauration", 0.8, 0.8, "part de ~100 000 emplois",
          "Près de 80 % des quelque 100 000 emplois liés au titre‑restaurant se trouvent dans la restauration.", src(24)),
        P("Date d'effet (n° 20)", 2028, 2028, "année",
          "À compter de 2028, le titre‑restaurant retrouverait sa vocation initiale", src(20)),
        ca_param(HIPPO, "Hippopotamus"), ca_param(CARREFOUR, "Carrefour Hypermarchés"),
    ],
    "total_eur_per_year": None,
    "per_profile": {
        HIPPO: {"eur_per_year": None, "sign": "gain",
                "method": "Récupère une partie des titres dépensés en produits à cuisiner ; la part qui se reporte sur les restaurants (plutôt que sur les préparations prêtes à manger en magasin) n'est pas sourcée.",
                "inputs": {"titres_encaisses_estimes": round(HIPPO_TR)}},
        CARREFOUR: {"eur_per_year": None, "sign": "perte",
                    "method": "Perd les titres dépensés en produits à cuisiner (hors fruits et légumes et produits directement consommables) ; cette part n'est pas sourcée. Assiette exposée : ~113 M€/an de titres encaissés (CA × 1 %).",
                    "inputs": {"titres_encaisses_estimes": round(CARREFOUR_TR)}},
        EDENRED: {"eur_per_year": None, "sign": "neutre",
                  "method": "Volume émis inchangé à court terme ; effet sur l'attrait du titre pour les salariés non chiffrable.",
                  "inputs": {}},
        UBER: {"eur_per_year": None, "sign": "gain",
               "method": "Les repas livrés restent éligibles ; part des titres dépensée via les plateformes non sourcée.",
               "inputs": {"ca": FIN[UBER]["ca"]}},
    },
    "variants": [
        {"amendments": [20], "label": "Recentrage à partir de 2028, double plafond supprimé", "total_eur_per_year": None},
        {"amendments": [24], "label": "Recentrage dès l'entrée en vigueur", "total_eur_per_year": None},
    ],
    "not_computable": f"Aucune source ne donne la part des titres dépensée en produits à cuisiner, ni le report de ces dépenses vers les restaurants. Repère seulement : la part des restaurants a perdu 12,2 points depuis fin 2022, soit {shift_lo/1e9:.2f} à {shift_hi/1e9:.2f} Md€/an aux volumes de 8,5 à 11 Md€.",
})

# ---------------------------------------------------------------- 4. congés familiaux
BIRTHS = 643905
SHARE_TR = 0.2
MAT_DAYS = 16 * 5            # 16 semaines × 5 jours travaillés
PAT_DAYS = 25 * 5 / 7        # 25 jours calendaires ramenés en jours travaillés
FACE = 12.20
beneficiaries = BIRTHS * SHARE_TR
face_total = beneficiaries * (MAT_DAYS + PAT_DAYS) * FACE
write("conges", {
    "theme": "Maintien pendant les congés familiaux",
    "amendments": [13, 18],
    "mechanism": "L'employeur continue d'attribuer des titres pendant les congés de maternité, paternité, adoption et naissance ; il en paie 50 à 60 %, et les titres sont dépensés chez les restaurants et commerces.",
    "winners": ["Salariés en congé de naissance ou d'adoption", "Restaurants et commerces qui encaissent les titres", "Émetteurs (volume émis)"],
    "losers": ["Employeurs qui attribuent des titres"],
    "parameters": [
        P("Naissances en France (2025)", BIRTHS, BIRTHS, "naissances/an",
          "Au total, 643 905 bébés sont nés en France en 2025", "https://www.insee.fr/fr/statistiques/9000195"),
        P("Part des salariés qui reçoivent des titres", SHARE_TR, SHARE_TR, "part",
          "réservé à environ un salarié sur cinq", src(24)),
        P("Congé de maternité (1er ou 2e enfant)", 16, 16, "semaines",
          "16 semaines", "https://www.service-public.gouv.fr/particuliers/vosdroits/F2265"),
        P("Congé de paternité et d'accueil de l'enfant", 25, 25, "jours calendaires",
          "La durée du congé de paternité et d'accueil de l'enfant est de 25 jours calendaires.", "https://www.service-public.gouv.fr/particuliers/vosdroits/F3156"),
        P("Valeur faciale de référence (exonération maximale, 2026)", FACE, FACE, "€/titre",
          "cette référence correspond à 12,20 euros en 2026", src(19)),
        P("Part employeur", 0.5, 0.6, "part",
          "Le titre‑restaurant est financé à hauteur de 40 à 50 % par le salarié, l’employeur prenant en charge entre 50 et 60 %.", src(32)),
    ],
    "total_eur_per_year": None,
    "per_profile": {
        HIPPO: {"eur_per_year": None, "sign": "neutre",
                "method": "Coût employeur seulement s'il distribue des titres (non connu) ; gain marginal comme restaurant qui les encaisse.",
                "inputs": {}},
        CARREFOUR: {"eur_per_year": None, "sign": "neutre",
                    "method": "Coût employeur seulement s'il distribue des titres (non connu) ; gain marginal comme commerce qui les encaisse.",
                    "inputs": {}},
        EDENRED: {"eur_per_year": None, "sign": "gain",
                  "method": "Volume émis en hausse (au plus ~154 M€/an de valeur faciale pour tous les émetteurs, borne haute) ; part de marché d'Edenred non sourcée.",
                  "inputs": {"valeur_faciale_max_tous_emetteurs": round(face_total)}},
        UBER: {"eur_per_year": None, "sign": "neutre",
               "method": "Effet marginal comme plateforme qui encaisse des titres ; part non sourcée.",
               "inputs": {}},
    },
    "variants": [
        {"amendments": [13, 18], "label": "Borne haute du coût employeur (tous les parents supposés salariés, 1 sur 5 avec titres, maternité 16 sem. + paternité 25 j, titre à 12,20 €, part employeur 50–60 %) ; congé d'adoption et congé supplémentaire de naissance non comptés",
         "total_eur_per_year": rng(face_total * 0.5, face_total * 0.6)},
    ],
    "not_computable": "La part des jeunes parents qui sont salariés et reçoivent des titres n'est pas sourcée (le « un salarié sur cinq » est appliqué à toutes les naissances, d'où une borne haute), ni le nombre d'accords d'entreprise qui maintiennent déjà les titres, ni la durée du congé supplémentaire de naissance.",
})
