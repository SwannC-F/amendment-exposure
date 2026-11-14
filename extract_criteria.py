"""Ask an LLM (Featherless, OpenAI-compatible) which companies each amendment targets.

Usage:
  python3 extract_criteria.py 142            # all pending amendments
  python3 extract_criteria.py 142 --limit 3  # first 3 only
  python3 extract_criteria.py 142 --dry-run  # print the prompt, no API call

Reads data/amendments_<n>.json, writes data/criteria_<n>.json.
Needs FEATHERLESS_API_KEY in .env (FEATHERLESS_MODEL optional).
"""
import json
import os
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE_URL = "https://api.featherless.ai/v1/chat/completions"
DEFAULT_MODEL = "deepseek-ai/DeepSeek-V4.1-Flash"

SYSTEM = """Tu analyses des amendements parlementaires français.
Pour un amendement, identifie les ENTREPRISES directement visées par la mesure.
Réponds UNIQUEMENT par un objet JSON, sans texte autour :
{
  "criteria_found": true|false,
  "who": "description courte des entreprises visées (ou vide)",
  "sectors": [{"naf": "code NAF rév. 2, ex. 56.10A", "label": "libellé"}],
  "employee_min": entier ou null,
  "employee_max": entier ou null,
  "regions": ["régions ou départements, vide si national"],
  "quote": "phrase exacte de l'amendement qui justifie ces critères"
}
Règles :
- criteria_found = false si l'amendement est rédactionnel, procédural, ou ne vise pas un type d'entreprise identifiable.
- N'invente pas de seuil : employee_min/max seulement si le texte donne un seuil d'effectif.
- Codes NAF au niveau sous-classe (ex. 56.10A) quand c'est clair, sinon classe (ex. 56.10).
- quote doit être copiée mot pour mot depuis le dispositif ou l'objet."""


def load_env():
    env = Path(".env")
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


def prompt_for(a):
    return (f"Article visé : {a['article']}\n\n"
            f"Dispositif :\n{a['text'][:6000]}\n\n"
            f"Objet :\n{a['purpose'][:4000]}")


def parse_json(text):
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        raise ValueError(f"no JSON in reply: {text[:200]}")
    return json.loads(m.group(0))


def call_llm(a, key, model):
    body = json.dumps({
        "model": model,
        "temperature": 0,
        "max_tokens": 800,
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": prompt_for(a)}],
    }).encode()
    req = urllib.request.Request(BASE_URL, data=body, headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    last = None
    for _ in range(3):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                reply = json.load(r)["choices"][0]["message"]["content"]
            return parse_json(reply)
        except Exception as e:  # network, rate limit, bad JSON: retry
            last = e
    return {"criteria_found": False, "error": str(last)}


def main():
    args = sys.argv[1:]
    n = next((x for x in args if x.isdigit()), "142")
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else None
    amendments = json.loads(Path(f"data/amendments_{n}.json").read_text())[:limit]

    if "--dry-run" in args:
        print(SYSTEM, "\n---\n", prompt_for(amendments[0]))
        return

    load_env()
    key = os.environ.get("FEATHERLESS_API_KEY")
    if not key:
        sys.exit("FEATHERLESS_API_KEY missing: copy .env.example to .env and fill it")
    model = os.environ.get("FEATHERLESS_MODEL") or DEFAULT_MODEL

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda a: call_llm(a, key, model), amendments))

    out = [{**a, "criteria": c, "model": model} for a, c in zip(amendments, results)]
    path = Path(f"data/criteria_{n}.json")
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    found = sum(1 for c in results if c.get("criteria_found"))
    errors = sum(1 for c in results if "error" in c)
    print(f"{len(out)} amendments, {found} with criteria, {errors} errors -> {path}")
    for o in out:
        c = o["criteria"]
        naf = ", ".join(s.get("naf", "?") for s in c.get("sectors", []))
        print(f"  n°{o['number']:<10} {'OK ' if c.get('criteria_found') else '-- '} {naf:<25} {c.get('who', c.get('error', ''))[:70]}")


if __name__ == "__main__":
    main()
