"""Who declared lobbying on titres-restaurant in the HATVP register (répertoire des représentants d'intérêts).

Stdlib only. Downloads the open data JSON (cached under data/raw/hatvp/, git-ignored),
searches every declared activity (objet, observation, décisions visées, tiers) for
titres-restaurant keywords, and writes data/history/hatvp.json.

Sides are assigned by hand in SIDES below, only where the declared text states a position;
the script checks that each quote is a verbatim substring of the declared activity.

    python3 history_hatvp.py            # uses the cached file if present
    python3 history_hatvp.py --refresh  # re-downloads
"""
import json
import os
import re
import sys
import urllib.request
from collections import defaultdict

URL = "https://www.hatvp.fr/agora/opendata/agora_repertoire_opendata.json"
PAGE = "https://www.hatvp.fr/open-data-repertoire/"
RAW_DIR = "data/raw/hatvp"
RAW = os.path.join(RAW_DIR, "agora_repertoire_opendata.json")
HEADERS = os.path.join(RAW_DIR, "headers.txt")
OUT = "data/history/hatvp.json"

KEYWORDS = re.compile(
    r"titres?[- ]?restaurants?|tickets?[- ]?restaurants?|ch[eè]ques?[- ]?d[eé]jeuners?|L\.? ?3262",
    re.I,
)

# Our label for each declarant, by HATVP identifiantNational. HATVP's own category is kept too.
TYPES = {
    # émetteurs and their association
    "393365135": "émetteur", "493322978": "émetteur (groupe)", "340393065": "émetteur",
    "824012173": "émetteur", "642044366": "émetteur", "718503386": "émetteur",
    "799025234": "émetteur", "W751228056": "association d'émetteurs",
    # restaurateurs
    "784357857": "fédération de restaurateurs", "778212779": "fédération de restaurateurs",
    "923291454": "fédération de restaurateurs", "422477224": "fédération de restaurateurs",
    "422477356": "fédération de restaurateurs", "822829727": "fédération de restaurateurs",
    "W442015468": "fédération de restaurateurs",
    # commerce alimentaire / artisans / distribution
    "784717225": "fédération du commerce alimentaire de proximité",
    "775691850": "fédération du commerce alimentaire de proximité",
    "308961978": "fédération du commerce alimentaire de proximité",
    "801316951": "fédération du commerce alimentaire de proximité",
    "784717498": "fédération de la distribution automatique",
    "784669152": "fédération de la distribution (grossistes)",
    "784855876": "fédération de la grande distribution",
    "652014051": "distribution", "403245061": "distribution", "789169323": "distribution",
    # syndicats patronaux interpro / autres
    "349681098": "syndicat patronal", "303215016": "syndicat patronal", "784717191": "syndicat patronal",
    "H747842583": "fédération (tourisme)",
    "501573158": "paiement",
    "784672792": "association", "339863417": "association", "453957623": "association",
}
CONSULTANCY_CODES = {"CABCON", "COCAB", "CABAVO", "AVCAB", "COIND", "AVIND"}

T_COMM = "Plafonner les commissions des émetteurs"
T_DP_ON = "Rendre effectif le double plafond journalier"
T_DP_OFF = "Supprimer le double plafond journalier"
T_LIMIT = "Limiter aux repas et fruits et légumes"
T_PAPER = "Repousser la fin des titres papier"
T_BONUS = "Titre-restaurant bonifié (bio, durable)"

# (identifiantFiche, theme, side, verbatim quote from that fiche)
SIDES = [
    # commissions
    ("2VRW615H", T_COMM, "pour", "demander plafonnement des commissions sur les cartes à puce"),
    ("QV7OWEXV", T_COMM, "pour", "Obtenir le plafonnement des commissions des émetteurs de titres restaurant"),
    ("JVDFIAEH", T_COMM, "pour", "plafonner le montant des commissions facturées aux commerçants accepteurs"),
    ("0V5DEB7V", T_COMM, "pour", "Demande d'encadrement des commissions des titres restaurant"),
    ("OHZABTM3", T_COMM, "pour", "Encadrer le montant des commissions exigées par les émetteurs historiques de titres restaurant"),
    ("Q36K42Z3", T_COMM, "pour", "Encadrer le montant des commissions exigées par les émetteurs de titres restaurant"),
    ("EVJF69KH", T_COMM, "pour", "Encadrer le montant des commissions exigées par les émetteurs historiques de titres restaurant"),
    ("A3YPU0G3", T_COMM, "pour", "Encadrer le montant des commissions exigées par les émetteurs historiques de titres restaurant"),
    ("EVJQ5P13", T_COMM, "pour", "Revoir l'encadrement des commissions sur les titres restaurants, sur le modèle juridique déjà applicable aux commissions sur les cartes bancaires"),
    ("DVS14Y6H", T_COMM, "pour", "proposer un plafonnement des commissions titre-restaurant"),
    ("PVX9WOKH", T_COMM, "pour", "proposer un plafonnement des commissions titre-restaurant"),
    ("PVX9AO1H", T_COMM, "pour", "proposer un plafonnement des commissions titre-restaurant"),
    ("O3862LAH", T_COMM, "pour", "Prévoir un plafonnement tarifaire des commissions pour les titres restaurant"),
    ("Q36SZW8V", T_COMM, "pour", "Encadrer les commissions que les professionnels versent aux émetteurs de titres restaurant"),
    # double plafond (mirrored onto T_DP_OFF below)
    ("5HASE8EH", T_DP_ON, "pour", "Inscrire dans la réforme du titre-restaurant le double plafond"),
    ("SVFGO5U3", T_DP_ON, "pour", "Demande d'inscription dans la loi d'un double plafond d'utilisation des titres restaurant"),
    ("SVFGPSI3", T_DP_ON, "pour", "Instaurer un double plafond d'utilisation du titre-restaurant"),
    ("0V2L6UBH", T_DP_ON, "pour", "Instaurer un double plafond d’utilisation du titre-restaurant"),
    ("0V2LXKSH", T_DP_ON, "pour", "Instaurer un double plafond d’utilisation du titre-restaurant"),
    ("Y3GQN05H", T_DP_ON, "pour", "MAINTIEN D'UN PLAFOND D'UTILISATION JOURNALIER SUPERIEUR DANS LES RESTAURANTS"),
    ("W3UNA42V", T_DP_ON, "contre", "s'opposer à différencier les plafonds d'utilisation en fonction des types de commerce"),
    # fin de l'usage « tout produit alimentaire » (dérogation)
    ("LV14J2LV", T_LIMIT, "pour", "METTRE FIN A L'EXTENSION DE L UTILISATIO DU TITRE-RESTAURANT DANS LA GRANDE DISTRIBUTION"),
    ("EVJFRPFH", T_LIMIT, "pour", "LE RESERVER A LA RESTAURATION"),
    ("5HASE8EH", T_LIMIT, "pour", "y supprimerl'extension du titre à la grande distribution"),
    ("Y3G7DR2V", T_LIMIT, "pour", "NE FASSE PAS L'OBJET D'UNE RECONDUCTION"),
    ("DVS2W6ZV", T_LIMIT, "pour", "ne fasse pas l’objet d’une reconduction"),
    ("UVPEBWD3", T_LIMIT, "pour", "ne fasse pas l’objet d’une reconduction"),
    ("X3CF9YI3", T_LIMIT, "pour", "plaidoyer contre l'élargissement de l'utilisation des titres-restaurant à l'achat de tous les produits alimentaires"),
    ("DVSJ2CFV", T_LIMIT, "pour", "plaidoyer contre l'élargissement de l'utilisation des titres-restaurant à l'achat de tous les produits alimentaires"),
    ("O386NIEH", T_LIMIT, "pour", "opposition à la proposition de loi visant à prolonger la dérogation d’usage des titres-restaurant pour tout produit alimentaire"),
    ("A3YPGDY3", T_LIMIT, "pour", "Réduire dans la loi la prolongation de l’utilisation des titres-restaurant pour des achats de produits alimentaires non directement consommables"),
    ("DHMQ4XBV", T_LIMIT, "pour", "Réduire dans la loi la prolongation de l’utilisation des titres-restaurant pour des achats de produits alimentaires non directement consommables"),
    ("LV1DNKF3", T_LIMIT, "pour", "limiter la prolongation de cette dérogation à un an"),
    ("UVPEED23", T_LIMIT, "pour", "limiter la prolongation dans le temps pour préserver sa vocation sociale et économique"),
    ("W3UNS4JV", T_LIMIT, "pour", "ALERTANT SUR LES RISQUES DE LA POSSIBLE PERENNISATION D'USAGE DES TR POUR ACHETER TOUT PRODUIT ALIMENTAIRE"),
    ("2VRNAL2H", T_LIMIT, "pour", "en sensibilisant sur les risques d'une prorogation excessive de la dérogation"),
    ("Y3K4MPFH", T_LIMIT, "pour", "alertant sur les risques de la possible pérennisation d'usage des titres pour acheter tout produit alimentaire"),
    ("JVDFK60H", T_LIMIT, "pour", "en sensibilisant sur les risques d'une prorogation excessive de la dérogation"),
    ("9V0PIPSH", T_LIMIT, "pour", "la suspension des autorisations pour les enseignes non spécialisées"),
    ("Q36KU1P3", T_LIMIT, "pour", "Revenir à la liste de 2021 des produits éligibles aux titres restaurants"),
    ("O3WIWQIH", T_LIMIT, "contre", "demander la pérennisation du dispositif"),
    ("ZV9R0E13", T_LIMIT, "contre", "demander la pérennisation du dispositif"),
    ("BHOW7JI3", T_LIMIT, "contre", "DEMANDER LA PROLONGATION LE DISPOSITIF DES TITRES RESTAURANTS"),
    ("OHZUXTKV", T_LIMIT, "contre", "Demander la prolongation le dispositif des titres restaurants jusqu’en 2026"),
    ("0V2LCCZH", T_LIMIT, "contre", "DÉFENDRE LE PROLONGEMENT DE L'USAGE DES TICKETS RESTAURANTS DANS LES GRANDES SURFACES"),
    ("DVS2AZDV", T_LIMIT, "contre", "DÉFENDRE LE PROLONGEMENT DE L'AUTORISATION D'USAGE DES"),
    ("6VBQUMUV", T_LIMIT, "contre", "Défendre le prolongement de l'usage des tickets restaurants dans les grandes surfaces"),
    ("0VESNIWH", T_LIMIT, "contre", "Défendre le prolongement de l'autorisation d'usage des tickets restaurants dans les grandes surfaces"),
    ("O3WIZ60H", T_LIMIT, "contre", "soutenir la prorogation du dispositif jusqu'au 31.12.2026"),
    ("Y3G7BC8V", T_LIMIT, "contre", "Soutenir une proposition de loi pérennisant l’usage des titres-restaurant pour tout aliment"),
    ("0V5X579H", T_LIMIT, "contre", "Prolonger et pérenniser la possibilité d'utiliser ses titres-restaurant pour un salarié pour l'ensemble des achats alimentaires"),
    ("PVXI2I2V", T_LIMIT, "contre", "Inscrire dans la loi la prolongation et la pérennisation de l'usage des titres-restaurant pour l'ensemble des achats alimentaires"),
    ("9V0KZ1KV", T_LIMIT, "contre", "Inscrire dans la loi la prolongation de la dérogation d'usage du titre-restaurant"),
    ("SVFGQKM3", T_LIMIT, "contre", "Inscrire dans la loi une prolongation de la dérogation d'usage du titre-restaurant"),
    ("YVNFAOJ3", T_LIMIT, "contre", "en faveur de la prolongation de l'élargissement de l'utilisation du titre-restaurant"),
    ("W3UWTJFV", T_LIMIT, "contre", "élargissement de l'usage du titre-restaurant à tout produit alimentaire"),
    ("UHQ1SWMV", T_LIMIT, "contre", "Prolonger d’un an la dérogation d’usage des titres restaurant pour l’achat de produits alimentaires"),
    ("LV1D2PQ3", T_LIMIT, "contre", "Proroger le dérogation instaurer par l’art 6 de la loi du 16 août 2022"),
    ("Y3GQ0M4H", T_LIMIT, "contre", "demander l'élargissement du champ d'application des tickets restaurants à tous les produits alimentaires"),
    ("UVPUL1XH", T_LIMIT, "contre", "Demander la prolongation de l'utilisation dérogatoire des titres restaurants"),
    # fin du papier (pushing for an early end = against postponing it)
    ("0VEST8UH", T_PAPER, "contre", "Acter le plus rapidement possible une date officielle d’arrêt du titre-restaurant papier"),
    ("SVFGPSI3", T_PAPER, "contre", "Acter le plus rapidement possible une date officielle d'arrêt du titre-restaurant papier"),
    ("0V2LXKSH", T_PAPER, "contre", "Acter le plus rapidement possible une date officielle d’arrêt du titre-restaurant papier"),
    ("2VRN1ZTH", T_PAPER, "contre", "acter la dématérialisation complète du dispositif"),
    ("O38S0423", T_PAPER, "contre", "acter la dématérialisation complète du dispositif"),
    ("0V2P11QV", T_PAPER, "contre", "acter la dématérialisation complète du dispositif"),
    ("YVNTG9MV", T_PAPER, "contre", "Acter la dématérialisation complète des titres-restaurants"),
    ("W3U97L5V", T_PAPER, "contre", "basculer intégralement à la dématérialisation"),
    ("Q36A8TLV", T_PAPER, "contre", "acter la dématérialisation complète du dispositif"),
    ("YVNFMQQ3", T_PAPER, "contre", "acter la dématérialisation complète du dispositif"),
    ("DHMQSMIV", T_PAPER, "contre", "accélérer la transition vers du 100% digital"),
    ("BHOWS473", T_PAPER, "contre", "Généraliser la dématérialisation des titres-restaurant"),
    ("5HABWNYV", T_PAPER, "contre", "Généraliser la dématérialisation des titres restaurants"),
    ("LV1D15E3", T_PAPER, "contre", "Demander la mise en oeuvre de la dématérialisation généralisée des titres restaurants"),
    ("EHLFUZ9H", T_PAPER, "contre", "Inscrire dans la loi le principe de dématérialisation à 100 % des titres restaurants"),
    ("QEVJ1A7H", T_PAPER, "contre", "INSCRIRE DANS LA LOI le principe de DEMATERIALISATION à 100 % DES TITRES RESTAURANTS"),
    ("0VES60NH", T_PAPER, "contre", "Demander l'accélération de la dématérialisation des titres restaurants"),
    ("0V2PF5NV", T_PAPER, "contre", "Demander l'accélération de la dématérialisation des titres restaurants"),
    ("GVT2YQBH", T_PAPER, "contre", "Acter la dématérialisation complète des titres restaurants"),
    ("JA3YZR6H", T_PAPER, "contre", "Transformer intégralement le titre-restaurant en version dématérialisé"),
    # titre bonifié
    ("DVS2UMLV", T_BONUS, "pour", "des chèques verts ou des tickets-restaurants bonifiés"),
]
MIRROR = {T_DP_ON: T_DP_OFF}
FLIP = {"pour": "contre", "contre": "pour"}

# Demo profiles: how each one connects to HATVP declarants. Links come from the HATVP file
# (registered name/SIREN, affiliations, tiers) except where link_basis says otherwise.
PROFILES = {
    "393365135": {"name": "Edenred France", "group_name_re": r"^EDENRED\b", "federations": ["W751228056"]},
    "451321335": {"name": "Carrefour Hypermarchés", "group_name_re": r"^CARREFOUR( MANAGEMENT| FRANCE)?$", "federations": ["784855876"]},
    "841983828": {"name": "Uber Eats France", "group_name_re": r"^UBER\b", "federations": []},
    "322566043": {"name": "Hippopotamus (Hippo Exploitation)", "group_name_re": r"^BERTRAND CORP", "federations": ["923291454"],
                  "caveat": "Le fichier HATVP ne relie pas Hippopotamus à Bertrand Corp. : le lien de groupe est à vérifier hors HATVP (Sirene / rapport annuel)."},
}


def norm(s):
    return re.sub(r"\s+", " ", (s or "").replace("\u0092", "’")).strip()


def download(refresh):
    if os.path.exists(RAW) and not refresh:
        return
    os.makedirs(RAW_DIR, exist_ok=True)
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0 (open-data research script)"})
    with urllib.request.urlopen(req, timeout=600) as r, open(RAW, "wb") as f:
        with open(HEADERS, "w") as h:
            h.write("".join(f"{k}: {v}\n" for k, v in r.headers.items()))
        while chunk := r.read(1 << 20):
            f.write(chunk)


def file_date():
    if os.path.exists(HEADERS):
        for line in open(HEADERS):
            if line.lower().startswith("last-modified:"):
                return line.split(":", 1)[1].strip()
    return None


def activity_text(ac):
    parts = [ac.get("objet", "")]
    for x in ac.get("actionsRepresentationInteret", []):
        parts += [x.get("observation", ""), x.get("actionMeneeAutre", ""), x.get("responsablePublicAutre", "")]
        parts += x.get("decisionsConcernees", []) + x.get("tiers", [])
    return norm(" | ".join(p for p in parts if p))


def main():
    download("--refresh" in sys.argv)
    data = json.load(open(RAW, encoding="utf-8"))["publications"]
    by_id = {p.get("identifiantNational"): p for p in data}

    orgs = {}
    fiche_index = {}
    for p in data:
        sid = p.get("identifiantNational")
        for ex in p.get("exercices", []):
            pc = ex.get("publicationCourante", {})
            for a in pc.get("activites") or []:
                ac = a["publicationCourante"]
                text = activity_text(ac)
                if not KEYWORDS.search(text):
                    continue
                cat = p.get("categorieOrganisation", {})
                org = orgs.setdefault(sid, {
                    "name": norm(p["denomination"]),
                    "siren": sid if p.get("typeIdentifiantNational") == "SIREN" else None,
                    "hatvp_id": sid,
                    "hatvp_category": cat.get("label"),
                    "type": "cabinet de conseil / affaires publiques" if cat.get("code") in CONSULTANCY_CODES
                            else TYPES.get(sid, "entreprise (activité à préciser)"),
                    "spending_band": None, "spending_band_year": None,
                    "affiliations": [norm(x["denomination"]) for x in p.get("affiliations", [])],
                    "actions": [], "sides": [],
                })
                year = int(pc["dateDebut"][-4:])
                band = pc.get("montantDepense")
                if band and (org["spending_band_year"] is None or year > org["spending_band_year"]):
                    org["spending_band"], org["spending_band_year"] = band, year
                aris = ac.get("actionsRepresentationInteret", [])
                obs = [norm(x["observation"]) for x in aris if x.get("observation")]
                targets = sorted({norm(t) for x in aris for t in x.get("reponsablesPublics", [])}
                                 | {norm(x["responsablePublicAutre"]) for x in aris if x.get("responsablePublicAutre")})
                action = {
                    "year": year,
                    "period": f'{pc["dateDebut"]} → {pc["dateFin"]}',
                    "fiche": ac["identifiantFiche"],
                    "excerpt": norm(ac["objet"]),
                    "observation": " / ".join(o for o in obs if KEYWORDS.search(o) or len(obs) == 1) or None,
                    "on_behalf_of": sorted({norm(t) for x in aris for t in x.get("tiers", [])}),
                    "decisions": sorted({norm(t) for x in aris for t in x.get("decisionsConcernees", [])}),
                    "targets": targets,
                    "spending_band_that_year": band,
                }
                org["actions"].append(action)
                fiche_index[ac["identifiantFiche"]] = (sid, text, action)

    for _, fs in FINDINGS:
        missing = [f for f in fs if f not in fiche_index]
        if missing:
            sys.exit(f"finding cites unknown fiches {missing}")

    # sides, each quote verified verbatim against its fiche
    for fiche, theme, side, quote in SIDES:
        if fiche not in fiche_index:
            sys.exit(f"unknown fiche {fiche}")
        sid, text, action = fiche_index[fiche]
        if norm(quote) not in text:
            sys.exit(f"quote not found in {fiche}: {quote}")
        entries = [{"theme": theme, "side": side}]
        if theme in MIRROR:
            entries.append({"theme": MIRROR[theme], "side": FLIP[side], "derived_from": theme})
        for e in entries:
            e.update({"quote": norm(quote), "year": action["year"], "fiche": fiche,
                      "on_behalf_of": action["on_behalf_of"]})
            orgs[sid]["sides"].append(e)

    for o in orgs.values():
        o["actions"].sort(key=lambda a: (-a["year"], a["fiche"]))
        o["sides"].sort(key=lambda s: (s["theme"], -s["year"]))

    # by_profile
    by_profile = {}
    for siren, prof in PROFILES.items():
        hits = []
        if siren in by_id:
            hits.append({"link": "déclarant direct", "hatvp_id": siren, "name": norm(by_id[siren]["denomination"]),
                         "tr_actions": len(orgs.get(siren, {}).get("actions", []))})
        else:
            hits.append({"link": "absent du répertoire sous ce SIREN", "hatvp_id": siren})
        for p in data:
            pid = p.get("identifiantNational")
            if pid != siren and re.search(prof["group_name_re"], norm(p["denomination"]), re.I):
                hits.append({"link": "même nom de groupe (déclarant distinct)", "hatvp_id": pid,
                             "name": norm(p["denomination"]), "tr_actions": len(orgs.get(pid, {}).get("actions", [])),
                             "affiliations_declared": [norm(a["denomination"]) for a in p.get("affiliations", [])]})
        group_ids = {h["hatvp_id"] for h in hits if h.get("name")}
        group_names = {h["name"] for h in hits if h.get("name")}
        for fed in prof["federations"]:
            if fed in orgs:
                members = [n for n in group_names
                           if any(fed == a.get("identifiantNational") for a in
                                  next((p for p in data if norm(p["denomination"]) == n), {}).get("affiliations", []))]
                hits.append({"link": "fédération / association", "hatvp_id": fed, "name": orgs[fed]["name"],
                             "tr_actions": len(orgs[fed]["actions"]),
                             "membership_declared_by": members or None,
                             "sides": orgs[fed]["sides"]})
        # who lobbied on TR on behalf of the group (tiers)
        for sid, o in orgs.items():
            for a in o["actions"]:
                if sid not in group_ids and any(re.search(prof["group_name_re"], re.sub(r" \(en propre\)$", "", t), re.I)
                                                  for t in a["on_behalf_of"]):
                    hits.append({"link": "tiers : déclare agir pour le compte du groupe", "hatvp_id": sid,
                                 "name": o["name"], "year": a["year"], "fiche": a["fiche"], "excerpt": a["excerpt"]})
        if prof.get("caveat"):
            hits.append({"link": "avertissement", "note": prof["caveat"]})
        by_profile[siren] = hits

    result = {
        "source": {
            "name": "HATVP — répertoire des représentants d'intérêts (open data, JSON)",
            "url": URL, "page": PAGE, "file_last_modified": file_date(),
            "query": KEYWORDS.pattern,
            "note": "Une ligne par fiche d'activité déclarée. spending_band = dépenses totales de représentation d'intérêts "
                    "déclarées pour l'exercice, tous sujets confondus (pas spécifique aux titres-restaurant).",
        },
        "organisations": sorted(orgs.values(), key=lambda o: (-len(o["actions"]), o["name"])),
        "by_profile": by_profile,
        "findings": [f"{t} (fiches : {', '.join(fs)})" for t, fs in FINDINGS],
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    n_act = sum(len(o["actions"]) for o in orgs.values())
    print(f"{len(orgs)} organisations, {n_act} fiches, {sum(len(o['sides']) for o in orgs.values())} sides -> {OUT}")


# Each finding cites the fiches it rests on (all in this file's organisations[].actions).
FINDINGS = [
    ("En 2025, le même programme en cinq points (arrêt rapide du titre papier, double plafond, interdiction des RFA "
     "demandées par les grands groupes aux émetteurs, charte de transparence des tarifs, dématérialisation des agréments) "
     "est déclaré mot pour mot par Swile, par Image 7 pour le compte de Swile, et point par point par Flint pour le compte de Pluxee France",
     ["SVFGPSI3", "0V2LXKSH", "0VEST8UH", "0V2L6UBH", "LV14TGGV", "YVNW2Y8V", "EVJ6YEO3"]),
    ("Les déclarants qui demandent explicitement de plafonner ou d'encadrer les commissions des émetteurs sont des accepteurs "
     "(CGAD, charcutiers-traiteurs, Saveurs Commerce, SNRTC, GNI, CT-CHRDT) et Worklife, Lucca et Boury Tallon ; "
     "aucune fiche d'Edenred, Pluxee, Swile ou UP ne le demande, Pluxee citant seulement un « plafonnement éventuel des commissions affiliés »",
     ["JVDFIAEH", "QV7OWEXV", "O3862LAH", "OHZABTM3", "EVJQ5P13", "Q36K42Z3", "DVS14Y6H", "PVX9WOKH", "PVX9AO1H", "Q36K0CN3"]),
    ("Sur l'usage du titre-restaurant pour tout produit alimentaire, la grande distribution (Carrefour, Carrefour Management, "
     "Les Mousquetaires, FCD) demande la prolongation ou la pérennisation, tandis que les restaurateurs (UMIH, GHR, SNARR, SNRTC, GNI) "
     "et deux émetteurs (Swile, UP) demandent d'y mettre fin ou de la limiter",
     ["O3WIWQIH", "ZV9R0E13", "0V2LCCZH", "Y3G7BC8V", "LV14J2LV", "9V0PIPSH", "Y3G7DR2V", "X3CF9YI3", "DVSJ2CFV", "W3UNS4JV", "UVPEED23"]),
    ("Les émetteurs ne parlent pas d'une seule voix sur cette dérogation : en 2023, Commstrat déclare pour Edenred France "
     "« Demander la prolongation de l'utilisation dérogatoire des titres restaurants », quand Swile et UP déclarent vouloir la limiter",
     ["UVPUL1XH", "2VRNAL2H", "UVPEED23"]),
    ("En 2025, le cabinet Image 7 déclare deux mandats opposés sur la même dérogation : pour Les Mousquetaires, « Défendre le "
     "prolongement de l'usage des tickets restaurants dans les grandes surfaces », et pour Swile, alerter sur « les risques de la "
     "possible pérennisation »",
     ["6VBQUMUV", "Y3K4MPFH"]),
    ("Le double plafond journalier est demandé par l'UMIH, l'UMIH Côte-d'Or, Swile et Pluxee (via Flint), et combattu par la FCD "
     "(« s'opposer à différencier les plafonds d'utilisation en fonction des types de commerce ») ; Edenred France déclare y travailler "
     "sans indiquer de position",
     ["5HASE8EH", "SVFGO5U3", "SVFGPSI3", "0V2L6UBH", "W3UNA42V", "EHL7TI6H"]),
    ("Edenred France est le déclarant le plus actif sur le sujet (29 fiches de 2020 à 2025) et sa tranche de dépenses de "
     "représentation d'intérêts passe de 75 000–100 000 € en 2020-2021 à 400 000–500 000 € par an de 2022 à 2025",
     ["W3U97L5V", "BHO757DH", "LV1CNZWV", "2VRN1ZTH"]),
    ("Aucune plateforme de livraison n'a déclaré d'action mentionnant les titres-restaurant : Uber France SAS est inscrite au "
     "répertoire mais sans fiche sur le sujet, Uber Eats France (841983828) n'y figure pas, et la seule demande liée à la vente à distance "
     "vient de la FCD et de Publicis pour Carrefour Management",
     ["6VBOEZJ3", "EVJQ4OU3"]),
]

if __name__ == "__main__":
    main()
