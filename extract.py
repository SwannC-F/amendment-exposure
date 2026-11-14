"""Per amendment, ask the LLM which companies the measure concerns (criteria, effect, roles).

Usage: python3 extract.py <session> <texte> [--limit N]
Reads data/<session>/<texte>/amendments.json, writes criteria.json in the same folder.
Every item carries a quote; quote_verified says whether it is found verbatim (after
typographic normalisation) in the amendment's dispositif or objet. Answers are cached on
disk by llm.py, so a rerun without change costs nothing.
"""
import hashlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor

from fetch_amendments import text_dir
from llm import chat_json, model_name, verify_quote

ROLES = ["employeurs", "emetteurs", "plateformes", "associations", "collectivites", "etat", "menages"]

SYSTEM = """Tu analyses des amendements parlementaires français, sur n'importe quel sujet.
Pour un amendement, identifie les ENTREPRISES et ACTEURS directement concernés par la mesure.
Réponds UNIQUEMENT par un objet JSON, sans texte autour :
{
  "criteria_found": true|false,
  "effect": "une phrase courte : ce que la mesure change concrètement",
  "who": "description courte des entreprises ou acteurs concernés (ou vide)",
  "sectors": [{"naf": "code NAF rév. 2, ex. 56.10A", "label": "libellé"}],
  "roles": ["rôles concernés, dans la liste fermée ci-dessous"],
  "regions": ["régions ou départements, vide si national"],
  "quote": "phrase exacte de l'amendement qui justifie ces critères"
}
Rôles (liste fermée) : employeurs, emetteurs, plateformes, associations, collectivites, etat, menages.
- emetteurs = entreprises qui émettent un titre, un moyen de paiement ou un produit financier visé par le texte.
- Si un acteur concerné n'entre dans aucun rôle, écris "autre:<libellé court>".
Règles :
- criteria_found = false si l'amendement est rédactionnel, procédural, ou ne vise aucun acteur identifiable ; dans ce cas effect peut rester renseigné, sectors et roles vides.
- Codes NAF au niveau sous-classe (ex. 56.10A) quand c'est clair, sinon classe (ex. 56.10). N'invente pas de code : laisse naf vide ("") si aucun code ne correspond, avec un libellé.
- N'invente aucun chiffre ni seuil absent du texte.
- quote doit être copiée mot pour mot depuis le dispositif ou l'objet (une phrase ou un membre de phrase, sans le modifier)."""


def prompt_for(a):
    return (f"Article visé : {a['article']}\n\n"
            f"Dispositif :\n{a['text'][:6000]}\n\n"
            f"Objet :\n{a['purpose'][:4000]}")


def clean_roles(roles):
    out = []
    for r in roles or []:
        r = str(r).strip()
        low = r.lower().replace("é", "e").replace("è", "e")
        if low in ROLES:
            r = low
        elif not low.startswith("autre:"):
            r = f"autre:{r}"
        if r not in out:
            out.append(r)
    return out


def extract_one(a):
    model = model_name()
    try:
        c = chat_json(SYSTEM, prompt_for(a))
        if not isinstance(c, dict):
            raise ValueError("reply is not an object")
    except Exception as e:
        return {"number": a["number"], "criteria_found": False, "effect": "", "who": "", "sectors": [],
                "roles": [], "regions": [], "quote": "", "quote_verified": False, "model": model,
                "error": str(e)[:300]}
    sectors = [{"naf": str(s.get("naf") or "").strip(), "label": str(s.get("label") or "").strip()}
               for s in c.get("sectors") or [] if isinstance(s, dict)]
    quote = str(c.get("quote") or "").strip()
    return {
        "number": a["number"],
        "criteria_found": bool(c.get("criteria_found")),
        "effect": str(c.get("effect") or "").strip(),
        "who": str(c.get("who") or "").strip(),
        "sectors": sectors,
        "roles": clean_roles(c.get("roles")),
        "regions": [str(r) for r in c.get("regions") or []],
        "quote": quote,
        "quote_verified": verify_quote(quote, a["text"], a["purpose"]),
        "model": model,
    }


def main(session, n, limit=None):
    d = text_dir(session, n)
    amendments = json.loads((d / "amendments.json").read_text())[:limit]
    with ThreadPoolExecutor(max_workers=4) as pool:
        out = list(pool.map(extract_one, amendments))
    ph = hashlib.sha256(SYSTEM.encode()).hexdigest()[:12]
    for o in out:
        o["prompt_hash"] = ph
    (d / "criteria.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
    found = sum(o["criteria_found"] for o in out)
    ver = sum(o["quote_verified"] for o in out if o["quote"])
    errors = sum("error" in o for o in out)
    print(f"{len(out)} amendements, {found} avec critères, {ver}/{sum(bool(o['quote']) for o in out)} "
          f"citations vérifiées, {errors} erreurs -> {d / 'criteria.json'}")
    for o in out:
        naf = ", ".join(s["naf"] or "?" for s in o["sectors"])
        flag = "OK " if o["criteria_found"] else "-- "
        q = "" if o["quote_verified"] else " [citation non retrouvée]"
        print(f"  n°{o['number']:<9} {flag}{naf:<30} {(o['effect'] or o.get('error', ''))[:70]}{q}")
    if errors:
        sys.exit(f"{errors} amendements en erreur : relancer (le cache garde les réussis)")


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) < 2:
        sys.exit("usage: python3 extract.py <session> <texte> [--limit N]")
    main(args[0], args[1], int(args[args.index("--limit") + 1]) if "--limit" in args else None)
