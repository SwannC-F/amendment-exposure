"""Build data/<session>/<texte>/engine.json: everything the page needs, with no business constant.

Usage: python3 engine.py <session> <texte>        e.g. python3 engine.py 2026-2027 142

Reads criteria, measures, signals, exposure, chiffrage and (optional) history .json from
data/<session>/<texte>/. One entry per measure: targeted NAF codes and roles (from extract),
political support (signals), exposure (exposure), history, and the chiffrage turned into
per-sector rates (€ per € of revenue = share × delta). A sector is a gain if it is among the
chiffrage's winners, a loss if among its losers. No SIREN, no hand-written scope.
"""
import json
import os
import sys
from pathlib import Path

DATA = Path(os.environ.get("PIPELINE_DATA", "data"))


def load(d, name, required=True):
    p = d / name
    if not p.exists():
        if required:
            sys.exit(f"manque {p}")
        return None
    return json.loads(p.read_text())


def criteria_of(c):
    return c.get("criteria") if isinstance(c.get("criteria"), dict) else c


def index(rows, field):
    """List of rows or {"amendments"/"measures": [...]} → {row[field]: row}."""
    if isinstance(rows, dict):
        rows = rows.get("measures") or rows.get("amendments") or []
    return {str(r[field]): r for r in rows if isinstance(r, dict) and field in r}


# ---------- signals & exposure: per measure if the file has it, else rebuilt from amendments ----------

def measure_signals(m, sig_by_key, sig_by_num):
    s = sig_by_key.get(m["key"])
    if s:
        groups = s.get("groups", [])
        return {"n_groups": s.get("n_groups", len(groups)), "groups": groups,
                "majority_groups": s.get("majority_groups", [])}
    groups, majority = set(), set()
    for n in m["amendments"]:
        s = sig_by_num.get(str(n), {})
        groups |= set(s.get("groups") or [s.get("author_group")] if s else [])
        majority |= set(s.get("majority_groups") or [])
    groups.discard(None)
    return {"n_groups": len(groups), "groups": sorted(groups), "majority_groups": sorted(majority)}


def measure_exposure(m, nafs, not_counted, exp, exp_by_key):
    e = exp_by_key.get(m["key"])
    if e:
        return {"companies": e.get("companies"), "employees_low": e.get("employees_low"),
                "employees_high": e.get("employees_high"), "approx": bool(e.get("approx")),
                "not_counted": e.get("not_counted", not_counted)}
    by_naf = (exp or {}).get("by_naf", {})
    tot = {"companies": 0, "employees_low": 0, "employees_high": 0}
    approx = False
    for naf in nafs:
        x = by_naf.get(naf)
        if not x:
            not_counted = not_counted + [naf]
            continue
        for k in tot:
            tot[k] += x.get(k) or 0
        approx |= bool(x.get("open_top") or x.get("approx"))
    return {**{k: v or None for k, v in tot.items()}, "approx": approx, "not_counted": not_counted}


# ---------- chiffrage → rates with a sign ----------

def party_keys(parties):
    nafs = {p["naf"] for p in parties if p.get("naf")}
    roles = {p["role"] for p in parties if p.get("role")}
    return nafs, roles


def sign_of(nafs, role, winners, losers):
    wn, wr = party_keys(winners)
    ln, lr = party_keys(losers)
    nafs = set(nafs or [])
    if nafs & wn or (role and role in wr):
        return "gain"
    if nafs & ln or (role and role in lr):
        return "perte"
    return None


def engine_chiffrage(ch):
    if not ch:
        return None
    delta = ch.get("delta")
    rates = []
    for s in ch.get("shares") or []:
        if not delta or delta["high"] >= 1:
            break  # no delta, or the whole flow changes hands: share × delta is not a rate on revenue
        sign = sign_of(s.get("nafs"), s.get("role"), ch.get("winners", []), ch.get("losers", []))
        if not sign:
            continue  # sector is neither a winner nor a loser in the text: no rate
        rates.append({"nafs": s.get("nafs") or [], "role": s.get("role"), "sign": sign,
                      "rate_low": s["low"] * delta["low"], "rate_high": s["high"] * delta["high"],
                      "method": f"CA × part {s['low']:.4g}–{s['high']:.4g} ({s.get('name')}) "
                                f"× écart {delta['low']:.4g}–{delta['high']:.4g} ({delta.get('name')})",
                      "quote": f"n°{s.get('amendment')} « {s.get('quote')} » ; "
                               f"n°{delta.get('amendment')} « {delta.get('quote')} »"})
    parameters = [dict(p, kind=k) for k, p in (("base", ch.get("base")), ("delta", delta)) if p] + \
                 [dict(s, kind="share") for s in ch.get("shares") or []]
    return {"mechanism": ch.get("mechanism"), "winners": ch.get("winners", []), "losers": ch.get("losers", []),
            "total_eur_per_year": ch.get("total_eur_per_year"), "rates": rates, "parameters": parameters,
            "dropped": ch.get("dropped", []), "mirror_of": ch.get("mirror_of"),
            "not_computable": ch.get("not_computable")}


def history_for(history, key):
    if not isinstance(history, dict):
        return None
    for field in ("measures", "by_measure", "by_key"):
        if isinstance(history.get(field), dict) and key in history[field]:
            return history[field][key]
    return history.get(key) if isinstance(history.get(key), (dict, list)) else None


def text_meta(d, session, texte, amendments, measures):
    meta = load(d, "text.json", required=False) or {}
    title = meta.get("title")
    if not title:
        for a in amendments or []:
            title = a.get("text_title") or a.get("texte_titre")
            if title:
                break
    return {"session": session, "number": texte, "title": title,
            **{k: v for k, v in meta.items() if k not in ("session", "number", "title")}}


def run(session, texte):
    d = DATA / session / texte
    criteria = {str(c["number"]): criteria_of(c) for c in load(d, "criteria.json")}
    measures = load(d, "measures.json")
    signals = load(d, "signals.json")
    exposure = load(d, "exposure.json")
    chiffrage = load(d, "chiffrage.json", required=False) or {}
    history = load(d, "history.json", required=False)
    amendments = load(d, "amendments.json", required=False)

    sig_by_key, sig_by_num = index(signals, "key"), index(signals, "number")
    exp_by_key = index(exposure, "key")

    out, majority = [], set(signals.get("majority", [])) if isinstance(signals, dict) else set()
    for m in measures:
        crits = [criteria.get(str(n)) or {} for n in m["amendments"]]
        crits = [c for c in crits if c.get("criteria_found", True)]
        effects, nafs, roles, sectors = [], set(), set(), {}
        for c in crits:
            if c.get("effect") and c["effect"] not in effects:
                effects.append(c["effect"])
            for s in c.get("sectors") or []:
                if s.get("naf"):
                    nafs.add(s["naf"])
                    sectors.setdefault(s["naf"], s.get("label") or s["naf"])
            for r in c.get("roles") or []:
                roles.add(r)
                sectors.setdefault(r, r)
        not_counted = sorted(roles)  # roles have no NAF code: not in the company count
        sig = measure_signals(m, sig_by_key, sig_by_num)
        if not isinstance(signals, dict) or "majority" not in signals:
            majority |= set(sig["majority_groups"])
        quote = next((c.get("quote") for c in crits if c.get("quote") and c.get("quote_verified", True)), None)
        entry = {"key": m["key"], "theme": m.get("theme"), "amendments": [str(n) for n in m["amendments"]],
                 "opposes": m.get("opposes"), "effects": effects, "nafs": sorted(nafs), "roles": sorted(roles),
                 "sectors": [{"key": k, "label": v} for k, v in sectors.items()], **sig,
                 **measure_exposure(m, sorted(nafs), not_counted, exposure, exp_by_key), "quote": quote}
        h = history_for(history, m["key"])
        if h:
            entry["history"] = h
        ch = engine_chiffrage(chiffrage.get(m["key"]))
        if ch:
            entry["chiffrage"] = ch
        out.append(entry)
    out.sort(key=lambda m: (-m["n_groups"], -len(m["majority_groups"]), -(m["companies"] or 0)))

    (d / "engine.json").write_text(json.dumps(
        {"text": text_meta(d, session, texte, amendments, measures), "majority": sorted(majority),
         "measures": out}, ensure_ascii=False, indent=2))
    print(f"{len(out)} mesures -> {d / 'engine.json'}")
    for m in out:
        ch = m.get("chiffrage") or {}
        t = ch.get("total_eur_per_year")
        tot = f"{t['low'] / 1e6:.0f}–{t['high'] / 1e6:.0f} M€/an" if t else "non chiffrable"
        print(f"  {m['n_groups']} gr. {(m['theme'] or m['key'])[:42]:<42} NAF {len(m['nafs']):>2} "
              f"rôles {m['roles']} taux {len(ch.get('rates', []))}  {tot}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    run(sys.argv[1], sys.argv[2])
