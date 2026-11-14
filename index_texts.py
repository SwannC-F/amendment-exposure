"""Build data/index.json: every text that has an engine.json, for the app's tabs.

Usage: python3 index_texts.py
Sénat texts live in data/<session>/<texte>/, Assemblée texts in data/an/<législature>/<texte>/.
"""
import json
from pathlib import Path

DATA = Path("data")


def entry(path, chamber, session, number):
    e = json.loads(path.read_text())
    text = e.get("text") or {}
    return {"chamber": chamber, "session": session, "number": number,
            "title": text.get("title") or f"Texte n°{number}",
            "path": str(path.parent.relative_to(DATA.parent)),
            "generated_at": e.get("generated_at") or text.get("generated_at"),
            "n_measures": len(e.get("measures", []))}


def main():
    out = []
    for p in sorted(DATA.glob("*/*/engine.json")):
        session, number = p.parent.parent.name, p.parent.name
        if session[:4].isdigit():
            out.append(entry(p, "senat", session, number))
    for p in sorted(DATA.glob("an/*/*/engine.json")):
        out.append(entry(p, "an", p.parent.parent.name, p.parent.name))
    (DATA / "index.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"{len(out)} texts -> data/index.json")
    for e in out:
        print(f"  {e['chamber']:<5} {e['session']}/{e['number']:<5} {e['n_measures']:>3} mesures  {e['title'][:70]}")


if __name__ == "__main__":
    main()
