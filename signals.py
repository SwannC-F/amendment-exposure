"""Adoption signal: how many political groups carry the same measure.

Usage: python3 signals.py 142
Reads data/amendments_<n>.json (author_group) and data/criteria_<n>.json (themes),
writes data/signals_<n>.json.

This is a descriptive signal, not a probability: we report which groups filed
amendments on the same theme, and whether the Sénat majority groups are among them.
"""
import json
import sys
from pathlib import Path

# Groups forming the Sénat majority (LR + Union centriste), session 2026-2027.
MAJORITY = {"Les Républicains", "UCI"}


def main(n):
    amendments = {a["number"]: a for a in json.loads(Path(f"data/amendments_{n}.json").read_text())}
    criteria = json.loads(Path(f"data/criteria_{n}.json").read_text())

    themes = {}
    for c in criteria:
        a = amendments.get(c["number"], {})
        for t in c["criteria"].get("themes", []):
            entry = themes.setdefault(t, {"amendments": [], "groups": set()})
            entry["amendments"].append(c["number"])
            if a.get("author_group"):
                entry["groups"].add(a["author_group"])

    out = []
    for c in criteria:
        a = amendments.get(c["number"], {})
        support = set()
        same = set()
        for t in c["criteria"].get("themes", []):
            support |= themes[t]["groups"]
            same |= set(themes[t]["amendments"])
        out.append({
            "number": c["number"],
            "author_group": a.get("author_group", ""),
            "themes": c["criteria"].get("themes", []),
            "same_theme_amendments": sorted(same - {c["number"]}),
            "groups": sorted(support),
            "n_groups": len(support),
            "majority_groups": sorted(support & MAJORITY),
        })

    Path(f"data/signals_{n}.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"{len(out)} amendments -> data/signals_{n}.json\n")
    for t, e in sorted(themes.items(), key=lambda kv: -len(kv[1]["groups"])):
        maj = " + majorité" if e["groups"] & MAJORITY else ""
        print(f"{len(e['groups'])} groupes{maj:<11} {t:<48} {', '.join(sorted(e['groups']))}  (n° {', '.join(e['amendments'])})")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "142")
