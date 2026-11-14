"""Recompute everything for one Sénat text, from scratch, by code.

Usage: python3 pipeline.py <session> <texte> [--from step] [--until step]
Steps, in order: fetch extract group signals exposure chiffrage history engine.
Each step is a script with the same CLI (python3 <script> <session> <texte>) that reads and
writes data/<session>/<texte>/. A step whose script is missing is skipped with a warning.
LLM answers and company counts are cached, so a rerun only pays for what changed.
"""
import subprocess
import sys
import time
from pathlib import Path

STEPS = [("fetch", "fetch_amendments.py"), ("extract", "extract.py"), ("group", "group.py"),
         ("signals", "signals.py"), ("exposure", "exposure.py"), ("chiffrage", "chiffrage.py"),
         ("history", "history.py"), ("engine", "engine.py")]


def main(args):
    if len(args) < 2:
        sys.exit(__doc__)
    session, n = args[0], args[1]
    names = [s for s, _ in STEPS]
    start = args[args.index("--from") + 1] if "--from" in args else "fetch"
    end = args[args.index("--until") + 1] if "--until" in args else "engine"
    for s in (start, end):
        if s not in names:
            sys.exit(f"étape inconnue : {s} (choix : {', '.join(names)})")
    skipped = []
    for name, script in STEPS[names.index(start):names.index(end) + 1]:
        if not Path(script).exists():
            print(f"\n== {name} : {script} absent, étape sautée")
            skipped.append(name)
            continue
        print(f"\n== {name} ({script} {session} {n})", flush=True)
        t = time.time()
        r = subprocess.run([sys.executable, script, session, n])
        if r.returncode:
            sys.exit(f"\nÉchec à l'étape {name} (code {r.returncode}). "
                     f"Reprendre avec : python3 pipeline.py {session} {n} --from {name}")
        print(f"   {name} : {time.time() - t:.0f} s")
    print(f"\nTerminé -> data/{session}/{n}/" + (f" (sautées : {', '.join(skipped)})" if skipped else ""))


if __name__ == "__main__":
    main(sys.argv[1:])
