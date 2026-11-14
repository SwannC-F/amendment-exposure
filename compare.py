"""Compare the pipeline's output for a text with the former hand-made files.

Usage: python3 compare.py [<session> <texte>]     default 2026-2027 142
Old: data/criteria_<texte>.json, data/engine_<texte>.json (hand-written themes and NAF).
New: data/<session>/<texte>/criteria.json, measures.json (and exposure.json if present).
Prints a short French report: measures found vs old themes (by amendment overlap),
pair agreement, NAF overlap per amendment, verified quotes.
"""
import json
import sys
from itertools import combinations
from pathlib import Path


def load(p):
    p = Path(p)
    return json.loads(p.read_text()) if p.exists() else None


def jaccard(a, b):
    a, b = set(a), set(b)
    return len(a & b) / len(a | b) if a | b else 1.0


def pct(x, n):
    return f"{100 * x / n:.0f} %" if n else "–"


def main(session, n):
    d = Path("data") / session / n
    old_c = {c["number"]: c["criteria"] for c in load(f"data/criteria_{n}.json")}
    old_m = load(f"data/engine_{n}.json")["measures"]
    new_c = {c["number"]: c for c in load(d / "criteria.json")}
    new_m = load(d / "measures.json")
    exp = load(d / "exposure.json")
    exp_m = {m["key"]: m for m in exp["measures"]} if exp else {}

    print(f"Comparaison n°{n} : version manuelle vs pipeline ({session})\n")
    common = sorted(set(old_c) & set(new_c), key=lambda x: (int(x.split()[0]), x))
    only_old, only_new = sorted(set(old_c) - set(new_c)), sorted(set(new_c) - set(old_c))
    print(f"Amendements : {len(old_c)} avant, {len(new_c)} maintenant, {len(common)} communs"
          + (f" ; disparus (votés depuis ?) : {', '.join(only_old)}" if only_old else "")
          + (f" ; nouveaux : {', '.join(only_new)}" if only_new else ""))
    found_old = sum(bool(old_c[a].get("criteria_found")) for a in common)
    found_new = sum(bool(new_c[a].get("criteria_found")) for a in common)
    print(f"Avec critères (communs) : {found_old} avant, {found_new} maintenant")

    # --- measures vs themes
    new_of = {a: m["key"] for m in new_m for a in m["amendments"]}
    theme_new = {m["key"]: m["theme"] for m in new_m}
    print(f"\nMesures : {len(old_m)} thèmes manuels, {len(new_m)} mesures générées")
    exact = 0
    for m in old_m:
        nums = [a for a in m["amendments"] if a in new_c]
        if not nums:
            print(f"  ✗ {m['theme']} : amendements absents du nouveau jeu")
            continue
        best = max(new_m, key=lambda x: jaccard(nums, x["amendments"]))
        j = jaccard(nums, best["amendments"])
        mark = "✓" if j == 1 else ("≈" if j >= 0.5 else "✗")
        exact += j == 1
        where = {}
        for a in nums:
            where.setdefault(theme_new.get(new_of.get(a), "(aucune mesure)"), []).append(a)
        extra = [a for a in best["amendments"] if a not in nums]
        split = ""
        if len(where) > 1:
            split += "  → éclaté : " + " | ".join(f"{t} : {', '.join(v)}" for t, v in where.items())
        if extra:
            split += f"  → le pipeline y ajoute n° {', '.join(extra)}"
        line = f"  {mark} {m['theme']} ({', '.join(nums)}) ↔ {best['theme']} [{j:.0%}]{split}"
        print(line)
    print(f"  Thèmes retrouvés à l'identique : {exact}/{len(old_m)}")

    old_of = {}
    for m in old_m:
        for a in m["amendments"]:
            old_of[a] = m["theme"]
    both = [a for a in common if a in old_of and a in new_of]
    pairs = list(combinations(both, 2))
    same_old = [p for p in pairs if old_of[p[0]] == old_of[p[1]]]
    same_new = [p for p in pairs if new_of[p[0]] == new_of[p[1]]]
    agree = sum((old_of[a] == old_of[b]) == (new_of[a] == new_of[b]) for a, b in pairs)
    print(f"  Paires d'amendements : accord {pct(agree, len(pairs))} ; "
          f"paires réunies à la main et aussi par le pipeline : {pct(len(set(same_old) & set(same_new)), len(same_old))} ; "
          f"paires réunies par le pipeline et aussi à la main : {pct(len(set(same_old) & set(same_new)), len(same_new))}")

    # --- NAF
    print("\nCodes NAF par amendement (communs avec critères des deux côtés) :")
    js, jc, rows = [], [], []
    for a in common:
        if not (old_c[a].get("criteria_found") and new_c[a].get("criteria_found")):
            continue
        o = {s["naf"] for s in old_c[a].get("sectors", []) if s.get("naf")}
        nw = {s["naf"] for s in new_c[a]["sectors"] if s["naf"]}
        js.append(jaccard(o, nw))
        jc.append(jaccard({x[:5] for x in o}, {x[:5] for x in nw}))
        rows.append((js[-1], a, o, nw))
    if js:
        print(f"  Recouvrement moyen (Jaccard) : {sum(js) / len(js):.0%} au code exact, "
              f"{sum(jc) / len(jc):.0%} à la classe (4 chiffres)")
        print(f"  Au moins un code commun : {sum(1 for r in rows if r[2] & r[3])}/{len(rows)}")
        print("  Plus grands écarts :")
        for j, a, o, nw in sorted(rows)[:6]:
            print(f"    n°{a:<8} {j:.0%}  avant {', '.join(sorted(o)) or '–'}  |  pipeline {', '.join(sorted(nw)) or '–'}")

    # --- quotes
    q = [c for c in new_c.values() if c.get("quote")]
    v = sum(c["quote_verified"] for c in q)
    print(f"\nCitations : {v}/{len(q)} vérifiées mot pour mot ({pct(v, len(q))})"
          + (f" ; non retrouvées : n° {', '.join(c['number'] for c in q if not c['quote_verified'])}"
             if v < len(q) else ""))
    roles = {}
    for c in new_c.values():
        for r in c.get("roles", []):
            roles[r] = roles.get(r, 0) + 1
    print("Rôles : " + ", ".join(f"{r} {k}" for r, k in sorted(roles.items(), key=lambda x: -x[1])))

    if exp_m:
        print("\nEntreprises comptées par mesure (pipeline vs thème manuel le plus proche) :")
        for m in new_m:
            e = exp_m.get(m["key"], {})
            old = max(old_m, key=lambda x: jaccard(x["amendments"], m["amendments"]))
            nafs = ", ".join(sorted({s["naf"] for s in e.get("sectors", []) if s["naf"]}))
            print(f"  {m['theme']:<42} {e.get('companies', 0):>9,}  (avant {old.get('companies') or 0:>9,})  {nafs}")


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0] if a else "2026-2027", a[1] if len(a) > 1 else "142")
