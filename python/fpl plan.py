#!/usr/bin/env python3
"""
FPL Predictor — bytesplanerare (flerperiods MILP)
=================================================
Planerar byten över flera gameweeks samtidigt istället för en omgång i taget.
Löser hela sekvensen exakt med MILP (PuLP/CBC): vilka byten som ska göras vilken
omgång, när det lönar sig att ta ett -4, och när man ska spara fria byten.

Modellen bestämmer samtidigt trupp, startelva och kapten för varje omgång.

ANVÄNDNING:
  python3 fpl_plan.py                              # utgår från optimalt GW1-lag
  python3 fpl_plan.py --squad "Haaland,Saka,..."   # utgår från ditt lag
  python3 fpl_plan.py --squad-file mitt_lag.txt    # ett namn per rad
  python3 fpl_plan.py --horizon 5 --ft 1 --bank 0.5

FÖRENKLINGAR (viktiga att känna till):
  * Inga prisförändringar och ingen försäljningspris-regel — inköpspris = dagens pris.
  * Inga chips (wildcard, free hit, bench boost, triple captain).
  * Deterministiska projektioner — ingen osäkerhetsfördelning som Solio visar.
  * Bänken ger inga poäng (utom via bench boost, som inte modelleras).
"""
import argparse, sys, unicodedata
import pandas as pd

import fpl_optimize as core

POSMAP = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
SQUAD_NEED = {1: 2, 2: 5, 3: 5, 4: 3}
XI_MIN = {1: 1, 2: 3, 3: 2, 4: 1}
XI_MAX = {1: 1, 2: 5, 3: 5, 4: 3}
MAX_FT = 5          # nuvarande FPL-regler: max 5 sparade fria byten
HIT_COST = 4


def norm(s):
    return unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower().strip()


def resolve_names(names, proj):
    """Matcha inklistrade namn mot modellen. Exakt först, sedan prefix.
    Delsträngsmatchning mitt i ett namn tillåts inte ('Wood' ska inte bli
    'Hinshelwood'). Returnerar (ids, ej_hittade)."""
    ids, missing = [], []
    rows = [(norm(r["name"]), int(r["id"]), r["name"]) for _, r in proj.iterrows()]
    for n in names:
        k = norm(n)
        if not k:
            continue
        exact = [i for nm, i, _ in rows if nm == k]
        if len(exact) == 1:
            ids.append(exact[0]); continue
        if len(exact) > 1:
            print(f"  '{n}' är tvetydigt ({len(exact)} spelare) — hoppar över",
                  file=sys.stderr)
            missing.append(n); continue
        # prefix, eller matchar ett helt ord i namnet (t.ex. "Timber" i "J.Timber")
        pref = [(i, disp) for nm, i, disp in rows
                if nm.startswith(k) or any(w == k for w in nm.replace(".", " ").split())]
        if len(pref) == 1:
            ids.append(pref[0][0]); continue
        if len(pref) > 1:
            print(f"  '{n}' matchar flera: {', '.join(d for _, d in pref[:4])}"
                  f" — hoppar över", file=sys.stderr)
        missing.append(n)
    return ids, missing


def plan(proj, gwproj, horizon, start_ids, ft0, bank, budget, candidates, verbose=True):
    """Flerperiods MILP. Returnerar (lösning per gw, totalpoäng)."""
    import pulp

    gws = sorted({int(g) for g in gwproj["gw"].unique() if int(g) <= horizon})
    if not gws:
        raise RuntimeError("Inga gameweeks inom horisonten.")

    # Kandidatpool: begränsa för att hålla problemet lösbart
    pool = proj.sort_values("proj", ascending=False).head(candidates)
    if start_ids:
        extra = proj[proj["id"].isin(start_ids) & ~proj["id"].isin(pool["id"])]
        pool = pd.concat([pool, extra], ignore_index=True)
    pool = pool.drop_duplicates("id").reset_index(drop=True)
    P = list(pool["id"])
    info = pool.set_index("id")

    # Poäng per spelare och omgång (0 om laget inte spelar den omgången)
    pts = {(int(r["id"]), int(r["gw"])): float(r["proj"])
           for _, r in gwproj[gwproj["gw"] <= horizon].iterrows()}
    def pt(p, g): return pts.get((p, g), 0.0)

    if verbose:
        print(f"Planerar GW{gws[0]}-{gws[-1]} över {len(P)} kandidater …", file=sys.stderr)

    m = pulp.LpProblem("fpl_plan", pulp.LpMaximize)
    x  = pulp.LpVariable.dicts("x",  (P, gws), cat="Binary")   # i truppen
    y  = pulp.LpVariable.dicts("y",  (P, gws), cat="Binary")   # i startelvan
    c  = pulp.LpVariable.dicts("c",  (P, gws), cat="Binary")   # kapten
    ti = pulp.LpVariable.dicts("ti", (P, gws), cat="Binary")   # in
    to = pulp.LpVariable.dicts("to", (P, gws), cat="Binary")   # ut
    ft = pulp.LpVariable.dicts("ft", gws, lowBound=0, upBound=MAX_FT, cat="Integer")
    us = pulp.LpVariable.dicts("us", gws, lowBound=0, cat="Integer")  # använda fria byten
    hi = pulp.LpVariable.dicts("hi", gws, lowBound=0, cat="Integer")  # betalda byten

    free_first = not start_ids   # utan startlag är GW1 fri laguttagning

    # ---- Mål: startelvans poäng + kaptenens extra, minus poängavdrag
    m += (pulp.lpSum(pt(p, g) * (y[p][g] + c[p][g]) for p in P for g in gws)
          - HIT_COST * pulp.lpSum(hi[g] for g in gws))

    for gi, g in enumerate(gws):
        # trupp: 15 spelare med rätt positionsfördelning
        for pos, n in SQUAD_NEED.items():
            m += pulp.lpSum(x[p][g] for p in P if info.loc[p, "pos"] == pos) == n
        # startelva: 11 spelare inom tillåten formation
        m += pulp.lpSum(y[p][g] for p in P) == 11
        for pos in (1, 2, 3, 4):
            sel = [y[p][g] for p in P if info.loc[p, "pos"] == pos]
            m += pulp.lpSum(sel) >= XI_MIN[pos]
            m += pulp.lpSum(sel) <= XI_MAX[pos]
        # kapten: exakt en, måste starta
        m += pulp.lpSum(c[p][g] for p in P) == 1
        for p in P:
            m += y[p][g] <= x[p][g]
            m += c[p][g] <= y[p][g]
        # budget och max 3 per klubb
        m += pulp.lpSum(x[p][g] * float(info.loc[p, "cost"]) for p in P) <= budget + bank
        for t in info["team_short"].unique():
            m += pulp.lpSum(x[p][g] for p in P if info.loc[p, "team_short"] == t) <= 3

        # ---- Kontinuitet mellan omgångar
        if gi == 0:
            if free_first:
                for p in P:
                    m += ti[p][g] == 0
                    m += to[p][g] == 0
                m += hi[g] == 0
                m += us[g] == 0
                m += ft[g] == ft0
            else:
                for p in P:
                    prev = 1 if p in start_ids else 0
                    m += x[p][g] == prev + ti[p][g] - to[p][g]
                    m += ti[p][g] + to[p][g] <= 1
                T = pulp.lpSum(ti[p][g] for p in P)
                m += us[g] <= ft0
                m += us[g] <= T
                m += hi[g] >= T - us[g]
                m += ft[g] == ft0
        else:
            pg = gws[gi - 1]
            for p in P:
                m += x[p][g] == x[p][pg] + ti[p][g] - to[p][g]
                m += ti[p][g] + to[p][g] <= 1
            T = pulp.lpSum(ti[p][g] for p in P)
            m += us[g] <= ft[pg]
            m += us[g] <= T
            m += hi[g] >= T - us[g]
            # sparade fria byten: +1 per omgång, tak MAX_FT
            m += ft[g] <= ft[pg] - us[g] + 1
            m += ft[g] <= MAX_FT

    m.solve(pulp.PULP_CBC_CMD(msg=0))
    status = pulp.LpStatus[m.status]
    if status != "Optimal":
        raise RuntimeError(f"Ingen optimal lösning ({status}). Prova färre kandidater eller kortare horisont.")

    # ---- Läs ut lösningen
    out = []
    for g in gws:
        squad = [p for p in P if x[p][g].value() > 0.5]
        xi    = [p for p in P if y[p][g].value() > 0.5]
        cap   = [p for p in P if c[p][g].value() > 0.5]
        ins   = [p for p in P if ti[p][g].value() > 0.5]
        outs  = [p for p in P if to[p][g].value() > 0.5]
        gpts  = sum(pt(p, g) for p in xi) + (pt(cap[0], g) if cap else 0)
        out.append(dict(gw=g, squad=squad, xi=xi, cap=cap[0] if cap else None,
                        ins=ins, outs=outs, hits=int(round(hi[g].value() or 0)),
                        ft=int(round(ft[g].value() or 0)), pts=gpts))
    total = sum(o["pts"] for o in out) - HIT_COST * sum(o["hits"] for o in out)
    return out, total, info


def main():
    ap = argparse.ArgumentParser(description="FPL bytesplanerare (flerperiods MILP)")
    ap.add_argument("--horizon", type=int, default=5, help="antal omgångar att planera")
    ap.add_argument("--squad", default=None, help="dina 15 spelare, kommaseparerat")
    ap.add_argument("--squad-file", default=None, help="fil med ett namn per rad")
    ap.add_argument("--ft", type=int, default=1, help="fria byten just nu")
    ap.add_argument("--bank", type=float, default=0.0, help="pengar i banken (m)")
    ap.add_argument("--budget", type=float, default=100.0)
    ap.add_argument("--candidates", type=int, default=110,
                    help="storlek på kandidatpoolen (högre = bättre men långsammare)")
    ap.add_argument("--k", type=float, default=10.0)
    ap.add_argument("--fixweight", type=float, default=0.06)
    ap.add_argument("--minmin", type=int, default=900)
    ap.add_argument("--no-bonus", action="store_true")
    ap.add_argument("--no-defcon", action="store_true")
    ap.add_argument("--cache-dir", default=".fplcache")
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()

    teams, players, prices, prev_players, hist, fixtures = core.load_all(args.cache_dir, args.offline)
    d, elo, short = core.build_players(teams, players, prices, prev_players, hist,
                                       args.k, args.minmin, not args.no_bonus, not args.no_defcon)
    proj, gwproj = core.project(d, fixtures, elo, short, args.horizon, args.fixweight)

    names = []
    if args.squad_file:
        names = [l.strip() for l in open(args.squad_file, encoding="utf-8") if l.strip()]
    elif args.squad:
        names = [n.strip() for n in args.squad.split(",") if n.strip()]

    start_ids = []
    if names:
        start_ids, missing = resolve_names(names, proj)
        if missing:
            print(f"Kunde inte matcha: {', '.join(missing)}", file=sys.stderr)
        if len(start_ids) != 15:
            print(f"Varning: {len(start_ids)} spelare matchade, förväntade 15. "
                  f"Planen kan bli fel.", file=sys.stderr)

    sol, total, info = plan(proj, gwproj, args.horizon, start_ids,
                            args.ft, args.bank, args.budget, args.candidates)

    nm = lambda p: info.loc[p, "name"]
    head = "DITT LAG" if start_ids else "OPTIMALT STARTLAG"
    print(f"\n=== BYTESPLAN GW1-{args.horizon}  (utgår från {head}) ===")
    print(f"Total projicerad poäng: {total:.1f}"
          f"   (poängavdrag: -{HIT_COST * sum(o['hits'] for o in sol)})\n")

    for o in sol:
        moves = ""
        if o["ins"] or o["outs"]:
            pairs = []
            outs, ins = list(o["outs"]), list(o["ins"])
            for i in range(max(len(outs), len(ins))):
                a = nm(outs[i]) if i < len(outs) else "—"
                b = nm(ins[i]) if i < len(ins) else "—"
                pairs.append(f"{a} → {b}")
            moves = "   " + " | ".join(pairs)
            if o["hits"]:
                moves += f"   [-{HIT_COST * o['hits']}]"
        print(f"GW{o['gw']:<3} {o['pts']:6.1f} p   C: {nm(o['cap']):<15} "
              f"FT kvar: {o['ft']}{moves}")

    print("\nStartelva sista omgången:")
    last = sol[-1]
    for pos in (1, 2, 3, 4):
        row = [nm(p) for p in last["xi"] if info.loc[p, "pos"] == pos]
        if row:
            print(f"  {POSMAP[pos]:4} " + ", ".join(row))
    bench = [nm(p) for p in last["squad"] if p not in last["xi"]]
    print(f"  Bänk {', '.join(bench)}")

    rows = []
    for o in sol:
        rows.append(dict(gw=o["gw"], points=round(o["pts"], 1), hits=o["hits"],
                         ft_left=o["ft"], captain=nm(o["cap"]) if o["cap"] else "",
                         transfers_in="; ".join(nm(p) for p in o["ins"]),
                         transfers_out="; ".join(nm(p) for p in o["outs"]),
                         xi="; ".join(nm(p) for p in o["xi"])))
    pd.DataFrame(rows).to_csv("transfer_plan.csv", index=False)
    print("\nSparade: transfer_plan.csv")
    print("Obs: inga prisförändringar, inga chips, deterministiska projektioner.")


if __name__ == "__main__":
    main()
