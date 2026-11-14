"""Group the amendments of a text into measures, with ONE LLM call.

Usage: python3 group.py <session> <texte>
Reads data/<session>/<texte>/criteria.json, writes measures.json:
  [{key, theme, amendments: [...], opposes: key|null}]
Every amendment with criteria_found lands in exactly one measure: the answer is checked,
the model is asked once more with the errors if needed, then any remaining gap is closed
by code (missing amendment -> its own measure, duplicate -> first measure kept), flagged
with "repaired": true.
"""
import json
import re
import sys
import unicodedata

from fetch_amendments import text_dir
from llm import chat_json

SYSTEM = """Tu regroupes les amendements d'un même texte parlementaire français en MESURES.
Une mesure = un même changement voulu (par exemple « plafonner les commissions »), quelles que soient
les variantes (taux, dates, rédaction). Deux amendements qui veulent la même chose vont dans la même mesure ;
deux amendements qui veulent des choses contraires vont dans deux mesures distinctes reliées par "opposes".
Réponds UNIQUEMENT par un objet JSON, sans texte autour :
{"measures": [
  {"key": "slug-court-en-minuscules", "theme": "libellé court en français (verbe à l'infinitif, 3 à 7 mots)",
   "amendments": ["numéros exacts"], "opposes": "key d'une autre mesure contraire, ou null"}
]}
Règles :
- Chaque numéro fourni apparaît dans exactement une mesure ; recopie les numéros tels quels (ex. "3 rect.").
- N'invente aucun numéro. Une mesure peut ne contenir qu'un amendement.
- "opposes" seulement si les deux mesures s'excluent (ex. supprimer un dispositif / le rendre effectif)."""


def slug(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:48] or "mesure"


def check(measures, expected):
    seen, problems = {}, []
    for m in measures:
        for a in m.get("amendments") or []:
            if a not in expected:
                problems.append(f"numéro inconnu : {a}")
            elif a in seen:
                problems.append(f"n°{a} est dans deux mesures ({seen[a]}, {m.get('key')})")
            else:
                seen[a] = m.get("key")
    missing = [a for a in expected if a not in seen]
    problems += [f"n°{a} n'est dans aucune mesure" for a in missing]
    return problems


def normalise(raw, expected, effects):
    """Clean keys/numbers, enforce one measure per amendment."""
    out, keys, placed = [], set(), set()
    for m in raw:
        key = slug(str(m.get("key") or m.get("theme") or "mesure"))
        while key in keys:
            key += "-2"
        nums = [str(a).strip() for a in m.get("amendments") or []]
        nums = [a for a in nums if a in expected and a not in placed]
        if not nums:
            continue
        placed.update(nums)
        keys.add(key)
        out.append({"key": key, "theme": str(m.get("theme") or key).strip(), "amendments": nums,
                    "opposes": m.get("opposes"), "_raw_key": str(m.get("key") or "")})
    for a in expected:
        if a not in placed:
            key = slug(f"amendement-{a}")
            out.append({"key": key, "theme": effects[a][:80], "amendments": [a], "opposes": None,
                        "repaired": True, "_raw_key": key})
    by_raw = {}
    for m in out:
        raw_key = m.pop("_raw_key")
        by_raw.setdefault(raw_key, m["key"])
        by_raw.setdefault(slug(raw_key), m["key"])
    for m in out:
        o = m.get("opposes")
        m["opposes"] = (by_raw.get(str(o)) or by_raw.get(slug(str(o)))) if o else None
        if m["opposes"] == m["key"]:
            m["opposes"] = None
    order = {a: i for i, a in enumerate(expected)}
    for m in out:
        m["amendments"].sort(key=order.get)
    return sorted(out, key=lambda m: order[m["amendments"][0]])


def main(session, n):
    d = text_dir(session, n)
    criteria = [c for c in json.loads((d / "criteria.json").read_text()) if c.get("criteria_found")]
    expected = [c["number"] for c in criteria]
    effects = {c["number"]: c["effect"] or c["who"] for c in criteria}
    items = [{"number": c["number"], "effect": c["effect"], "who": c["who"]} for c in criteria]
    if not items:
        (d / "measures.json").write_text("[]")
        print(f"aucun amendement ne vise d'acteur identifiable -> 0 mesure -> {d / 'measures.json'}")
        return
    user = json.dumps(items, ensure_ascii=False, indent=1)

    raw = chat_json(SYSTEM, user, max_tokens=8000)
    raw = raw.get("measures", []) if isinstance(raw, dict) else raw
    problems = check(raw, expected)
    if problems:
        print("Regroupement incomplet, nouvelle demande :", "; ".join(problems[:8]))
        retry = (user + "\n\nTa réponse précédente avait ces erreurs, corrige-les :\n- " + "\n- ".join(problems)
                 + "\n\nRéponse précédente :\n" + json.dumps({"measures": raw}, ensure_ascii=False))
        raw2 = chat_json(SYSTEM, retry, max_tokens=8000)
        raw2 = raw2.get("measures", []) if isinstance(raw2, dict) else raw2
        problems2 = check(raw2, expected)
        if len(problems2) <= len(problems):
            raw, problems = raw2, problems2
        if problems:
            print("Toujours incomplet, réparé par le code :", "; ".join(problems[:8]))

    measures = normalise(raw, expected, effects)
    assert not check(measures, expected)
    (d / "measures.json").write_text(json.dumps(measures, ensure_ascii=False, indent=2))
    print(f"{len(expected)} amendements -> {len(measures)} mesures -> {d / 'measures.json'}")
    for m in measures:
        opp = f"  (contraire de {m['opposes']})" if m["opposes"] else ""
        print(f"  {m['theme']:<50} n° {', '.join(m['amendments'])}{opp}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit("usage: python3 group.py <session> <texte>")
    main(sys.argv[1], sys.argv[2])
