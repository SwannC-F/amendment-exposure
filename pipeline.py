"""Recompute everything for one text (Sénat or Assemblée nationale), from scratch, by code.

Usage: python3 pipeline.py <session> <texte> [--from step] [--until step]        Sénat, data/<session>/<texte>/
       python3 pipeline.py an <législature> <texte> [--from step] [--until step]  Assemblée, data/an/<lég>/<texte>/
Steps, in order: fetch extract group signals exposure chiffrage history hemicycle engine.
Each step is a script with the same CLI (python3 <script> <session> <texte>) that reads and
writes data/<session>/<texte>/; for the Assemblée, session is "an/<législature>" (so the same
data/an/<lég>/<texte>/ folder), except fetch (fetch_amendments_an.py <lég> <texte>). History is
built for the Sénat; at the Assemblée a failure there is a warning, not a stop. A step whose script is missing is skipped with a warning.
LLM answers and company counts are cached, so a rerun only pays for what changed.
"""
import os
import subprocess
import sys
import time
from pathlib import Path

STEPS = [("fetch", "fetch_amendments.py"), ("extract", "extract.py"), ("group", "group.py"),
         ("signals", "signals.py"), ("exposure", "exposure.py"), ("chiffrage", "chiffrage.py"),
         ("history", "history.py"), ("hemicycle", "hemicycle_step.py"), ("engine", "engine.py")]


def main(args):
    if len(args) < 2:
        sys.exit(__doc__)
    an = args[0] == "an"
    if an:
        if len(args) < 3:
            sys.exit(__doc__)
        leg, n = args[1], args[2]
        session = f"an/{leg}"
    else:
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
        if name == "hemicycle" and not os.environ.get("HEMICYCLE_API_KEY") and \
                "HEMICYCLE_API_KEY=" not in (Path(".env").read_text() if Path(".env").exists() else ""):
            print("\n== hemicycle : attention, pas de HEMICYCLE_API_KEY, étape sautée")
            skipped.append(name)
            continue
        if an and name == "fetch":
            script, cli = "fetch_amendments_an.py", [leg, n]
        else:
            cli = [session, n]
        print(f"\n== {name} ({script} {' '.join(cli)})", flush=True)
        t = time.time()
        r = subprocess.run([sys.executable, script, *cli])
        if r.returncode and (name == "hemicycle" or (an and name == "history")):
            print(f"   attention : {name} a échoué (code {r.returncode}), on continue sans")
            skipped.append(name)
            continue
        if r.returncode:
            sys.exit(f"\nÉchec à l'étape {name} (code {r.returncode}). "
                     f"Reprendre avec : python3 pipeline.py {'an ' + leg if an else session} {n} --from {name}")
        print(f"   {name} : {time.time() - t:.0f} s")
    print(f"\nTerminé -> data/{session}/{n}/" + (f" (sautées : {', '.join(skipped)})" if skipped else ""))


if __name__ == "__main__":
    main(sys.argv[1:])
