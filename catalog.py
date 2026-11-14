"""Build data/catalog.json: every text in discussion that has amendments, computed or not.

Usage: python3 catalog.py [session]          (default 2026-2027)

Sénat: the Sénat has no public list of amended texts, so we probe text numbers of the session
(the per-text amendments CSV exists only for texts that have amendments) and stop after a long
run of misses. For each hit: official title (text page), total and pending amendments.
Assemblée: texts already fetched under data/an/ (their amendments.json / text.json).
"""
import csv
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import fetch_amendments as sen

DATA = Path("data")
MAX_MISSES = 60      # consecutive numbers without a CSV before we stop
UPPER = 600          # never probe beyond this


def probe(session, n):
    try:
        raw = sen.download(sen.URL.format(s=session, n=n))
    except Exception:
        return None
    lines = raw.splitlines()
    if not lines or "Numéro" not in "".join(lines[:2]):
        return None
    if lines[0].startswith("sep="):
        lines = lines[1:]
    rows = list(csv.reader(lines, delimiter="\t"))[1:]
    sorts = [r[9].strip().lower() if len(r) > 9 else "" for r in rows]
    pending = sum(1 for s in sorts if not any(k in s for k in sen.SETTLED))
    return {"chamber": "senat", "session": session, "number": str(n),
            "title": sen.text_title(session, n), "url": sen.TEXT_PAGE.format(s=session, n=n),
            "n_amendments": len(rows), "n_pending": pending,
            "computed": (DATA / session / str(n) / "engine.json").exists()}


def senate(session):
    found, misses, n = [], 0, 1
    with ThreadPoolExecutor(max_workers=8) as pool:
        while n <= UPPER and misses < MAX_MISSES:
            batch = list(range(n, min(n + 16, UPPER + 1)))
            for num, res in zip(batch, pool.map(lambda k: probe(session, k), batch)):
                if res:
                    found.append(res)
                    misses = 0
                else:
                    misses += 1
            n += 16
    return found


def assemblee():
    out = []
    for d in sorted(DATA.glob("an/*/*")):
        meta = json.loads((d / "text.json").read_text()) if (d / "text.json").exists() else {}
        am = json.loads((d / "amendments.json").read_text()) if (d / "amendments.json").exists() else []
        out.append({"chamber": "an", "session": d.parent.name, "number": d.name,
                    "title": meta.get("title") or f"Texte n°{d.name}", "url": meta.get("url"),
                    "n_amendments": len(am), "n_pending": len(am),
                    "computed": (d / "engine.json").exists()})
    return out


def main(session="2026-2027"):
    texts = senate(session) + assemblee()
    texts.sort(key=lambda t: (t["chamber"], not t["computed"], -t["n_pending"]))
    (DATA / "catalog.json").write_text(json.dumps(texts, ensure_ascii=False, indent=2))
    print(f"{len(texts)} texts -> data/catalog.json")
    for t in texts:
        print(f"  {t['chamber']:<5} {t['session']}/{t['number']:<5} {t['n_pending']:>5} en attente / {t['n_amendments']:<5}"
              f" {'calculé' if t['computed'] else '       '}  {(t['title'] or '')[:60]}")


if __name__ == "__main__":
    main(*(sys.argv[1:2] or []))
