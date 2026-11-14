"""Analyse automatically the texts on the Sénat and Assemblée agendas (this week and next).

Usage: python3 batch.py [--dry-run] [--cap 10] [--parallel 3] [--max-pending 400] [--stop-at HH:MM]

1. Discover: Sénat ordre du jour (texts with a non-empty amendments CSV), Assemblée eLiasse
   examens in séance publique still running (texts fetch_amendments_an.py can read).
   Texts already in data/index.json and SKIP are left out.
2. Estimate: pending amendments x observed cost per amendment (cache usage.cost) + FIXED.
3. Run pipeline.py, PARALLEL at a time, cheapest first. Spend cap measured from real cost
   (usage.cost of cache files written since start) + estimates of texts still running.
4. Log: data/batch/<date>.json.
"""
import csv
import datetime as dt
import html
import json
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from fetch_amendments import SETTLED, download
import fetch_amendments_an as an

DATA = Path("data")
CACHE = DATA / "cache" / "llm"
ODJ = "https://www.senat.fr/ordre-du-jour/ordre-du-jour.html"
CSV_URL = "https://www.senat.fr/amendements/{s}/{n}/jeu_complet_{s}_{n}.csv"
SKIP = {("senat", "2026-2027", "142"), ("senat", "2026-2027", "168"), ("an", "17", "2864")}
FALLBACK_PER_AMDT = 0.006
FIXED = 0.10
MONTHS = {m: i for i, m in enumerate(["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
                                      "août", "septembre", "octobre", "novembre", "décembre"], 1)}


def arg(name, default):
    return type(default)(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default


def senat_texts(today):
    """(session, number) of texts on the Sénat agenda between today and the end of next week."""
    raw = an.get(ODJ, binary=True).decode("utf-8", errors="replace")  # get() retries + curl fallback
    s = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", raw)))
    horizon = today + dt.timedelta(days=6 - today.weekday() + 7)  # Sunday of next week
    day_re = r"(?:Lundi|Mardi|Mercredi|Jeudi|Vendredi|Samedi|Dimanche) (\d+)(?:er)? (\w+) (20\d\d)"
    tokens = re.finditer(day_re + r"|n°\s*(\d+)[^n]{0,40}?\(?(20\d\d-20\d\d)", s)
    cur, out = None, []
    for m in tokens:
        if m.group(1):
            mo = MONTHS.get(m.group(2).lower())
            cur = dt.date(int(m.group(3)), mo, int(m.group(1))) if mo else cur
        elif cur and today <= cur <= horizon:
            key = (m.group(5), m.group(4))
            if key not in out:
                out.append(key)
    return out


def senat_pending(session, n):
    try:
        raw = download(CSV_URL.format(s=session, n=n))
    except Exception:
        return None
    lines = raw.splitlines()
    if lines and lines[0].startswith("sep="):
        lines = lines[1:]
    rows = list(csv.reader(lines, delimiter="\t"))
    if len(rows) < 2:
        return None
    h = [x.strip() for x in rows[0]]
    rows = [dict(zip(h, r)) for r in rows[1:] if len(r) >= len(h) - 1]
    return sum(1 for r in rows if not any(k in r.get("Sort", "").lower() for k in SETTLED)), len(rows)


def an_texts(leg="17"):
    """Assemblée texts under examination in séance publique, with pending counts from eLiasse."""
    organes = {o["uid"]: o.get("abreviation") for o in an.get(f"{an.ELIASSE}/organes")}
    out, seen = [], set()
    exams = sorted(an.get(f"{an.ELIASSE}/examens"), key=lambda e: organes.get(e["organeRef"]) != an.SEANCE_ABRV)
    for e in exams:
        if e.get("statut") != "En cours":  # séance publique or commission
            continue
        n = e["texte"]["bibard"]
        if str(n) in seen:
            continue
        seen.add(str(n))
        try:
            places = an.get(f"{an.ELIASSE}/examens/{e['uid']}/derouleur")["places"]
        except Exception:
            continue
        listed = [a for p in places for a in p.get("amendements", [])]
        pending = sum(1 for a in listed if not any(k in (a.get("sort") or "").lower() for k in SETTLED))
        if listed:
            out.append({"chamber": "an", "session": leg, "number": str(n), "pending": pending,
                        "total": len(listed), "title": an.title_of(e["texte"])})
    return out


def cost_per_amendment():
    total = sum((json.loads(p.read_text()).get("usage") or {}).get("cost") or 0 for p in CACHE.glob("*.json"))
    n = 0
    for c, s, num in SKIP:
        p = DATA / ("an/" + s if c == "an" else s) / num / "amendments.json"
        if p.exists():
            n += len(json.loads(p.read_text()))
    return (total / n, total, n) if total and n else (FALLBACK_PER_AMDT, total, n)


def real_cost_since(t0):
    tot = 0.0
    for p in CACHE.glob("*.json"):
        if p.stat().st_mtime >= t0:
            try:
                tot += (json.loads(p.read_text()).get("usage") or {}).get("cost") or 0
            except Exception:
                pass
    return tot


def main():
    cap, par, maxp = arg("--cap", 10.0), arg("--parallel", 3), arg("--max-pending", 400)
    stop_at = arg("--stop-at", "17:05")
    today = dt.date.today()
    stop = dt.datetime.combine(today, dt.time(*map(int, stop_at.split(":"))))
    done = {(e["chamber"], e["session"], e["number"]) for e in json.loads((DATA / "index.json").read_text())}

    for lp in (DATA / "batch").glob(f"{today.isoformat()}*.json"):  # texts another run is computing
        for t in json.loads(lp.read_text()).get("texts", []):
            if t.get("state") == "running":
                done.add((t["chamber"], t["session"], t["number"]))
    per, tot, n = cost_per_amendment()
    print(f"coût observé : {tot:.3f} $ / {n} amendements = {per:.4f} $/amendement")
    texts = []
    for s, num in senat_texts(today):
        key = ("senat", s, num)
        if key in done or key in SKIP:
            continue
        r = senat_pending(s, num)
        if r:
            texts.append({"chamber": "senat", "session": s, "number": num, "pending": r[0], "total": r[1]})
    cat = DATA / "catalog.json"  # catalog.py: Sénat texts with pending amendments
    if cat.exists():
        have = {(t["chamber"], t["session"], t["number"]) for t in texts}
        for c in json.loads(cat.read_text()):
            key = (c["chamber"], c["session"], str(c["number"]))
            if c["chamber"] == "senat" and not c.get("computed") and c.get("n_pending") \
                    and key not in done | SKIP | have:
                texts.append({"chamber": "senat", "session": c["session"], "number": str(c["number"]),
                              "pending": c["n_pending"], "total": c.get("n_amendments"), "source": "catalog"})
    try:
        texts += [t for t in an_texts() if (t["chamber"], t["session"], t["number"]) not in done | SKIP]
    except Exception as ex:
        print("Assemblée : découverte en échec :", ex)
    for t in texts:
        t["estimate"] = round(t["pending"] * per + FIXED, 3)
        t["state"] = "skipped (>%d en attente)" % maxp if t["pending"] > maxp else \
            "skipped (0 en attente)" if t["pending"] == 0 else "queued"
    texts.sort(key=lambda t: t["estimate"])
    print(f"\n{len(texts)} textes trouvés :")
    for t in texts:
        print(f"  {t['chamber']:<5} {t['session']}/{t['number']:<5} {t['pending']:>4}/{t['total']:<4} en attente"
              f"  ~{t['estimate']:.2f} $  {t['state']}")

    suffix = arg("--log-suffix", "")
    log_path = DATA / "batch" / f"{today.isoformat()}{'-' + suffix if suffix else ''}.json"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    lock = threading.Lock()
    earlier = []
    if log_path.exists():  # several runs the same day: keep the earlier ones
        prev = json.loads(log_path.read_text())
        earlier = prev.pop("earlier_runs", []) + [prev]
    log = {"earlier_runs": earlier, "started": dt.datetime.now().isoformat(timespec="seconds"), "cap": cap,
           "cost_per_amendment": per, "texts": texts}

    def save():
        log["real_cost"] = round(real_cost_since(t0), 4)
        out = dict(log, texts=[{k: v for k, v in x.items() if k != "_th"} for x in log["texts"]])
        log_path.write_text(json.dumps(out, ensure_ascii=False, indent=2))

    if "--dry-run" in sys.argv:
        return
    save()

    def run(t):
        cli = ["an", t["session"], t["number"]] if t["chamber"] == "an" else [t["session"], t["number"]]
        lp = DATA / "batch" / f"{t['chamber']}_{t['session']}_{t['number']}.log"
        start = time.time()
        with open(lp, "w") as f:
            r = subprocess.run([sys.executable, "pipeline.py", *cli], stdout=f, stderr=subprocess.STDOUT)
        with lock:
            t["seconds"] = round(time.time() - start)
            t["state"] = "done" if r.returncode == 0 else f"failed (code {r.returncode})"
            if r.returncode:
                t["error"] = lp.read_text()[-600:]
            subprocess.run([sys.executable, "index_texts.py"], capture_output=True)
            save()
        print(f"{t['state']:<20} {t['chamber']} {t['session']}/{t['number']} ({t['seconds']} s)", flush=True)

    running = {}
    queue = [t for t in texts if t["state"] == "queued"]
    while queue or running:
        while queue and len(running) < par:
            if dt.datetime.now() >= stop:
                for t in queue:
                    t["state"] = "not launched (stop time)"
                queue = []
                break
            with lock:
                committed = real_cost_since(t0) + sum(x["estimate"] for x in running.values())
            t = queue[0]
            if committed + t["estimate"] > cap:
                if running:
                    break  # wait for a running text to finish, then re-check with real cost
                for x in queue:
                    x["state"] = "not launched (cap)"
                queue = []
                break
            queue.pop(0)
            t["state"] = "running"
            t["launched"] = dt.datetime.now().isoformat(timespec="seconds")
            th = threading.Thread(target=run, args=(t,))
            running[t["number"] + t["chamber"]] = t
            t["_th"] = th
            th.start()
            print(f"lancé  {t['chamber']} {t['session']}/{t['number']} (~{t['estimate']:.2f} $, engagé {committed:.2f} $)",
                  flush=True)
        running = {k: t for k, t in running.items() if t["_th"].is_alive()}
        with lock:
            save()
        time.sleep(5)
    log["finished"] = dt.datetime.now().isoformat(timespec="seconds")
    save()
    print(f"\ncoût réel : {log['real_cost']:.3f} $ -> {log_path}")


if __name__ == "__main__":
    main()
