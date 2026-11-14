"""Adoption signal per measure: which political groups filed amendments carrying it.

Usage: python3 signals.py <session> <texte>
Reads data/<session>/<texte>/amendments.json (author_group) and measures.json,
writes signals.json: {majority, measures: [...], amendments: [...]}.

Descriptive signal, not a probability: which groups filed amendments for the same measure,
and whether the Sénat majority groups are among them.
"""
import json
import sys

from fetch_amendments import text_dir

# Groups forming the Sénat majority (LR + Union centriste), by session.
MAJORITY = {"2026-2027": ["Les Républicains", "UCI"]}


def main(session, n):
    d = text_dir(session, n)
    amendments = {a["number"]: a for a in json.loads((d / "amendments.json").read_text())}
    measures = json.loads((d / "measures.json").read_text())
    majority = set(MAJORITY.get(session, []))
    if not majority:
        print(f"attention : majorité du Sénat inconnue pour la session {session}")

    out_m, out_a = [], []
    for m in measures:
        groups = sorted({amendments[a]["author_group"] for a in m["amendments"]
                         if amendments.get(a, {}).get("author_group")})
        out_m.append({"key": m["key"], "theme": m["theme"], "amendments": m["amendments"],
                      "opposes": m.get("opposes"), "groups": groups, "n_groups": len(groups),
                      "majority_groups": sorted(set(groups) & majority)})
        for a in m["amendments"]:
            out_a.append({"number": a, "measure": m["key"],
                          "author_group": amendments.get(a, {}).get("author_group", ""),
                          "same_measure_amendments": [x for x in m["amendments"] if x != a]})

    (d / "signals.json").write_text(json.dumps(
        {"majority": sorted(majority), "measures": out_m, "amendments": out_a}, ensure_ascii=False, indent=2))
    print(f"{len(out_m)} mesures -> {d / 'signals.json'}")
    for e in sorted(out_m, key=lambda e: -e["n_groups"]):
        maj = " + majorité" if e["majority_groups"] else ""
        print(f"  {e['n_groups']} groupes{maj:<11} {e['theme']:<48} {', '.join(e['groups'])}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit("usage: python3 signals.py <session> <texte>")
    main(sys.argv[1], sys.argv[2])
