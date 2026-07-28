#!/usr/bin/env python3
"""
FPL Predictor — chip-planerare
==============================
Värderar FPL:s fyra chips omgång för omgång och föreslår bästa tillfälle inom
varje halva av säsongen. Chips förnyas vid halvtid, så det finns två fönster
och ett av varje chip i vardera.

FÖNSTER (från FPL:s egna regler för 26/27):
  Bench Boost     GW1-19   och  GW20-38
  Triple Captain  GW1-19   och  GW20-38
  Free Hit        GW2-19   och  GW20-38
  Wildcard        GW2-19   och  GW20-38

SÅ VÄRDERAS DE:
  Triple Captain  extra poäng av att kaptenen räknas en gång till
  Bench Boost     summan av de fyra bänkspelarnas projektion
  Free Hit        bästa möjliga elva ur hela ligan minus din egen elva
  Wildcard        nyoptimerad trupp för resten av fönstret minus din nuvarande

ANVÄNDNING:
  python3 fpl_chips.py                      # från optimalt lag
  python3 fpl_chips.py --team-id 1234567    # från ditt lag
  python3 fpl_chips.py --squad "Haaland,Saka,..."

VIKTIG BEGRÄNSNING:
  Dubbel- och blankomgångar avgör chip-timing i praktiken, men de uppstår först
  när cupmatcher tvingar fram ommatchningar under säsongen. Saknas de i schemat
  varnar scriptet — kör om det när omgångarna börjar spricka.
"""
import argparse, sys
import pandas as pd

import fpl_optimize as core
import fpl_plan as planner

POSMAP = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
XI_MIN = {1: 1, 2: 3, 3: 2, 4: 1}
XI_MAX = {1: 1, 2: 5, 3: 5, 4: 3}
SQUAD_NEED = {1: 2, 2: 5, 3: 5, 4: 3}

# FPL:s fönster för 26/27 (name, start, stop) per halva
CHIP_WINDOWS = {
    "Bench Boost":    [(1, 19), (20, 38)],
    "Triple Captain": [(1, 19), (20, 38)],
    "Free Hit":       [(2, 19), (20, 38)],
    "Wildcard":       [(2, 19), (20, 38)],
}


def best_xi(ids, gw, pts):
    """Bästa lagliga startelva ur en trupp. Returnerar (xi_ids, poäng, kapten)."""
    val = lambda p: pts.get((p, gw), 0.0)
    pos = lambda p: POS_OF[p]
    gk = sorted([p for p in ids if pos(p) == 1], key=val, reverse=True)
    out = sorted([p for p in ids if pos(p) != 1], key=val, reverse=True)
    if not gk:
        return [], 0.0, None
    xi = [gk[0]]
    cnt = {1: 1, 2: 0, 3: 0, 4: 0}
    for q in (2, 3, 4):
        for p in [p for p in out if pos(p) == q][:XI_MIN[q]]:
            xi.append(p); cnt[q] += 1
    for p in out:
        if len(xi) >= 11:
            break
        if p in xi or cnt[pos(p)] >= XI_MAX[pos(p)]:
            continue
        xi.append(p); cnt[pos(p)] += 1
    tot = sum(val(p) for p in xi)
    cap = max(xi, key=val) if xi else None
    return xi, tot, cap


def dream_xi(proj, gw, pts, budget=100.0):
    """Bästa möjliga elva (inkl. kapten) för EN omgång med fri laguttagning.
    Free Hit ger en helt ny trupp för en omgång, så detta löses exakt med LP:
    15 spelare inom budget, 11 i elvan, en kapten som dubblas."""
    import pulp
    d = proj.copy()
    d["p"] = [pts.get((int(i), gw), 0.0) for i in d["id"]]
    d = d.reset_index(drop=True)
    m = pulp.LpProblem("fh", pulp.LpMaximize)
    x = [pulp.LpVariable(f"x{i}", cat="Binary") for i in d.index]   # i truppen
    y = [pulp.LpVariable(f"y{i}", cat="Binary") for i in d.index]   # i elvan
    c = [pulp.LpVariable(f"c{i}", cat="Binary") for i in d.index]   # kapten
    m += pulp.lpSum((y[i] + c[i]) * d.loc[i, "p"] for i in d.index)
    m += pulp.lpSum(x[i] * d.loc[i, "cost"] for i in d.index) <= budget
    for pos, n in SQUAD_NEED.items():
        m += pulp.lpSum(x[i] for i in d.index if d.loc[i, "pos"] == pos) == n
    m += pulp.lpSum(y[i] for i in d.index) == 11
    for pos in (1, 2, 3, 4):
        sel = [y[i] for i in d.index if d.loc[i, "pos"] == pos]
        m += pulp.lpSum(sel) >= XI_MIN[pos]
        m += pulp.lpSum(sel) <= XI_MAX[pos]
    m += pulp.lpSum(c[i] for i in d.index) == 1
    for i in d.index:
        m += y[i] <= x[i]
        m += c[i] <= y[i]
    for t in d["team_short"].unique():
        m += pulp.lpSum(x[i] for i in d.index if d.loc[i, "team_short"] == t) <= 3
    m.solve(pulp.PULP_CBC_CMD(msg=0))
    if pulp.LpStatus[m.status] != "Optimal":
        return 0.0
    return float(sum((y[i].value() + c[i].value()) * d.loc[i, "p"] for i in d.index))


def squad_xi_total(ids, g_from, g_to, pts):
    """Summan av elva+kapten över ett omgångsintervall för en given trupp."""
    tot = 0.0
    for g in range(g_from, g_to + 1):
        _, t, cap = best_xi(ids, g, pts)
        tot += t + (pts.get((cap, g), 0.0) if cap else 0.0)
    return tot


def greedy_squad_for(proj, pts, g_from, g_to, budget):
    """Bästa trupp för ett omgångsintervall, rankad på hur mycket spelarna
    faktiskt bidrar i elvan. Enkel greedy, men ett bättre ombud för elvans poäng
    än att maximera summan av alla 15 (som straffar bänkstarka men startsvaga val)."""
    ids = [int(i) for i in proj["id"]]
    cost = dict(zip(proj["id"].astype(int), proj["cost"].astype(float)))
    pos = dict(zip(proj["id"].astype(int), proj["pos"].astype(int)))
    team = dict(zip(proj["id"].astype(int), proj["team_short"]))
    rem = {i: sum(pts.get((i, g), 0.0) for g in range(g_from, g_to + 1)) for i in ids}
    # billigaste pris per position — behövs för att inte spendera slut och fastna
    cheap = {}
    for q in (1, 2, 3, 4):
        c = [cost[i] for i in ids if pos[i] == q]
        cheap[q] = min(c) if c else 4.0
    cnt, tc, sq, spend = {1: 0, 2: 0, 3: 0, 4: 0}, {}, [], 0.0

    def reserve(after_pos):
        """Minsta summa som krävs för att fylla resterande platser."""
        need = 0.0
        for q in (1, 2, 3, 4):
            left = SQUAD_NEED[q] - cnt[q] - (1 if q == after_pos else 0)
            need += max(0, left) * cheap[q]
        return need

    for i in sorted(ids, key=lambda x: -rem[x]):
        if len(sq) >= 15:
            break
        if cnt[pos[i]] >= SQUAD_NEED[pos[i]]:
            continue
        if tc.get(team[i], 0) >= 3:
            continue
        if spend + cost[i] + reserve(pos[i]) > budget + 1e-9:
            continue
        sq.append(i); cnt[pos[i]] += 1
        tc[team[i]] = tc.get(team[i], 0) + 1; spend += cost[i]

    # Andra pass: en enkel genomgång kan avvisa en billig spelare tidigt och sedan
    # inte hitta tillbaka. Fyll därför resten med de billigaste som får plats.
    if len(sq) < 15:
        chosen = set(sq)
        for q in (1, 2, 3, 4):
            while cnt[q] < SQUAD_NEED[q]:
                cands = [i for i in ids if pos[i] == q and i not in chosen
                         and tc.get(team[i], 0) < 3
                         and spend + cost[i] <= budget + 1e-9]
                if not cands:
                    break
                i = min(cands, key=lambda x: cost[x])
                sq.append(i); chosen.add(i); cnt[q] += 1
                tc[team[i]] = tc.get(team[i], 0) + 1; spend += cost[i]
    return sq if len(sq) == 15 else None


def optimal_from(proj, gwproj, g_from, g_to, budget):
    """Optimal trupp för omgångarna g_from..g_to (för att värdera Wildcard)."""
    sub = gwproj[(gwproj["gw"] >= g_from) & (gwproj["gw"] <= g_to)]
    tot = sub.groupby("id")["proj"].sum().rename("p")
    d = proj.set_index("id").join(tot, how="inner").reset_index()
    d = d[d["p"] > 0].reset_index(drop=True)
    if len(d) < 15:
        return None, 0.0
    import pulp
    m = pulp.LpProblem("wc", pulp.LpMaximize)
    x = [pulp.LpVariable(f"x{i}", cat="Binary") for i in d.index]
    m += pulp.lpSum(x[i] * d.loc[i, "p"] for i in d.index)
    m += pulp.lpSum(x[i] * d.loc[i, "cost"] for i in d.index) <= budget
    for pos, n in SQUAD_NEED.items():
        m += pulp.lpSum(x[i] for i in d.index if d.loc[i, "pos"] == pos) == n
    for t in d["team_short"].unique():
        m += pulp.lpSum(x[i] for i in d.index if d.loc[i, "team_short"] == t) <= 3
    m.solve(pulp.PULP_CBC_CMD(msg=0))
    if pulp.LpStatus[m.status] != "Optimal":
        return None, 0.0
    ids = [int(d.loc[i, "id"]) for i in d.index if x[i].value() > 0.5]
    return ids, float(sum(d.loc[i, "p"] for i in d.index if x[i].value() > 0.5))


def main():
    ap = argparse.ArgumentParser(description="FPL chip-planerare")
    ap.add_argument("--squad", default=None)
    ap.add_argument("--squad-file", default=None)
    ap.add_argument("--team-id", type=int, default=None)
    ap.add_argument("--team-gw", type=int, default=None)
    ap.add_argument("--picks-file", default=None)
    ap.add_argument("--budget", type=float, default=100.0)
    ap.add_argument("--top", type=int, default=4, help="hur många kandidatomgångar att visa")
    ap.add_argument("--wc-stride", type=int, default=3,
                    help="hur tätt Wildcard utvärderas (1 = varje omgång, men långsamt)")
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
    proj, gwproj = core.project(d, fixtures, elo, short, 38, args.fixweight)

    global POS_OF
    POS_OF = dict(zip(proj["id"].astype(int), proj["pos"].astype(int)))
    cost_of = dict(zip(proj["id"].astype(int), proj["cost"].astype(float)))
    team_of = dict(zip(proj["id"].astype(int), proj["team_short"]))
    name_of = dict(zip(proj["id"].astype(int), proj["name"]))
    pts = {(int(r["id"]), int(r["gw"])): float(r["proj"]) for _, r in gwproj.iterrows()}

    # ---- Startlag
    squad = None
    if args.team_id or args.picks_file:
        try:
            raw, fbank, tinfo = (planner.load_picks_file(args.picks_file) if args.picks_file
                                 else planner.fetch_fpl_team(args.team_id, args.team_gw))
            squad, dropped = planner.map_element_ids(raw, proj, players)
            print(f"Hämtade lag från GW{tinfo.get('gw')} "
                  f"({len(squad)} av {len(raw)} spelare i modellen)", file=sys.stderr)
            if dropped:
                print(f"  utesluts: {', '.join(dropped)}", file=sys.stderr)
        except Exception as e:
            print(f"Kunde inte hämta laget: {e}", file=sys.stderr); sys.exit(1)
    else:
        names = []
        if args.squad_file:
            names = [l.strip() for l in open(args.squad_file, encoding="utf-8") if l.strip()]
        elif args.squad:
            names = [n.strip() for n in args.squad.split(",") if n.strip()]
        if names:
            squad, missing = planner.resolve_names(names, proj)
            if missing:
                print(f"Kunde inte matcha: {', '.join(missing)}", file=sys.stderr)
    if not squad:
        squad, _ = optimal_from(proj, gwproj, 1, 10, args.budget)
        print("Utgår från optimalt GW1-10-lag (inget eget lag angivet).", file=sys.stderr)

    # ---- Dubbel- och blankomgångar?
    cnt = gwproj.groupby(["team", "gw"]).size()
    doubles = int((cnt > 1).sum())
    all_gw = sorted(gwproj["gw"].unique())
    teams_seen = gwproj.groupby("gw")["team"].nunique()
    blanks = int((teams_seen < gwproj["team"].nunique()).sum())

    squad_value = sum(cost_of[p] for p in squad)
    print(f"\n=== CHIP-PLAN ===")
    print(f"Trupp: {len(squad)} spelare, värde {squad_value:.1f}m")
    print(f"(Wildcard och Free Hit räknas mot lagvärdet {squad_value:.1f}m, "
          f"inte mot 100m.)\n")

    if not doubles and not blanks:
        print("VARNING: schemat innehåller inga dubbel- eller blankomgångar ännu.")
        print("Det är de som i praktiken avgör chip-timing — Bench Boost är värt")
        print("ungefär dubbelt i en dubbelomgång, och Free Hit får nästan hela sitt")
        print("värde från blanka omgångar. Rangordningen nedan bygger därför bara på")
        print("motståndsstyrka och är PRELIMINÄR. Kör om när omgångarna spricker.\n")

    rows = []
    for half, (lo_bb, hi_bb) in enumerate(CHIP_WINDOWS["Bench Boost"], start=1):
        lo_t, hi_t = CHIP_WINDOWS["Triple Captain"][half - 1]
        lo_f, hi_f = CHIP_WINDOWS["Free Hit"][half - 1]
        lo_w, hi_w = CHIP_WINDOWS["Wildcard"][half - 1]
        label = f"Halva {half}  (GW{lo_bb}-{hi_bb})"
        print(f"--- {label} ---")

        # Triple Captain & Bench Boost: per omgång
        tc, bb, fh = [], [], []
        for g in all_gw:
            xi, tot, cap = best_xi(squad, g, pts)
            if lo_t <= g <= hi_t and cap:
                tc.append((g, pts.get((cap, g), 0.0), name_of[cap]))
            if lo_bb <= g <= hi_bb:
                bench = [p for p in squad if p not in xi]
                bb.append((g, sum(pts.get((p, g), 0.0) for p in bench), ""))
            if lo_f <= g <= hi_f:
                dream = dream_xi(proj, g, pts, squad_value)
                mine = tot + (pts.get((cap, g), 0.0) if cap else 0)
                fh.append((g, max(0.0, dream - mine), ""))

        def show(title, data, unit="p"):
            data = sorted(data, key=lambda x: -x[1])[:args.top]
            best = data[0] if data else None
            if not best:
                print(f"  {title:15} —"); return
            extra = f"  ({best[2]})" if best[2] else ""
            alts = ", ".join(f"GW{g} {v:+.1f}" for g, v, _ in data[1:])
            print(f"  {title:15} bästa: GW{best[0]}  {best[1]:+.1f} {unit}{extra}")
            if alts:
                print(f"  {'':15} sedan:  {alts}")
            rows.append(dict(half=half, chip=title, best_gw=best[0],
                             value=round(best[1], 1), note=best[2]))

        show("Triple Captain", tc)
        show("Bench Boost", bb)
        show("Free Hit", fh)

        # Wildcard: dyrare — utvärderas med steg
        wc = []
        mine_total = {}
        for g in range(lo_w, hi_w + 1, max(1, args.wc_stride)):
            # ett wildcard ger dig ditt LAGVÄRDE att handla för, inte 100m
            ids = greedy_squad_for(proj, pts, g, hi_w, squad_value)
            if not ids:
                # greedyn kan misslyckas när budgeten är exakt utnyttjad —
                # LP:n är alltid lösbar och används då som reserv
                ids, _ = optimal_from(proj, gwproj, g, hi_w, squad_value)
            if not ids:
                continue
            # jämför elva+kapten mot elva+kapten så måtten är jämförbara
            opt_v = squad_xi_total(ids, g, hi_w, pts)
            mine_v = squad_xi_total(squad, g, hi_w, pts)
            wc.append((g, max(0.0, opt_v - mine_v), f"{hi_w - g + 1} omg."))
        show("Wildcard", wc)
        print()

    if rows:
        pd.DataFrame(rows).to_csv("chip_plan.csv", index=False)
        print("Sparade: chip_plan.csv")
    print("Wildcard utvärderas var", args.wc_stride, "omgång (--wc-stride 1 för alla).")


if __name__ == "__main__":
    main()
