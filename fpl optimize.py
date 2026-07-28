#!/usr/bin/env python3
"""
FPL Predictor — exakt lagoptimering (Python)
============================================
Samma modell som webb-appen (xG, xA, bonus, DefCon, ClubElo-fixtures), men med en
EXAKT linjär optimering (PuLP/CBC) istället för webbläsarens heuristik. Använd den
här när du vill ha det matematiskt optimala laget för en slutgiltig uttagning.

Data hämtas automatiskt från FPL Core Insights:
  https://github.com/olbauday/FPL-Core-Insights

ANVÄNDNING:
  pip install pandas numpy pulp requests
  python3 fpl_optimize.py                          # hämtar och kör med standardvärden
  python3 fpl_optimize.py --horizon 10 --lock Haaland
  python3 fpl_optimize.py --no-bonus --no-defcon   # stäng av poängkomponenter
  python3 fpl_optimize.py --offline                # använd bara cachade filer

UTDATA:
  squad_optimal.csv   det valda laget
  proj_all.csv        alla spelares projektion
  proj_by_gw.csv      projektion per spelare per gameweek (indata till evaluate.py)
"""
import argparse, io, math, os, sys, unicodedata
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

try:
    import requests
except ImportError:
    requests = None
    from urllib.request import urlopen

GH = "https://raw.githubusercontent.com/olbauday/FPL-Core-Insights/main/data"
S_NOW, S_PREV, PREV_LAST_GW, N_GW = "2026-2027", "2025-2026", 38, 38
POSNUM = {"Goalkeeper": 1, "Defender": 2, "Midfielder": 3, "Forward": 4}
POSMAP = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
GOAL_PTS = {1: 10, 2: 6, 3: 5, 4: 4}
CS_PTS = {1: 4, 2: 4, 3: 1, 4: 0}
DC_THR = {1: 999, 2: 10, 3: 12, 4: 12}


def norm(s):
    return unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower().strip()


# ---------------------------------------------------------------- hämtning
def fetch(path, cache_dir, offline=False):
    """Hämta en CSV från repot, med lokal cache."""
    safe = path.replace("/", "__").replace("%20", "_")
    local = os.path.join(cache_dir, safe)
    if os.path.exists(local):
        return pd.read_csv(local)
    if offline:
        raise FileNotFoundError(f"saknas i cache och --offline är satt: {path}")
    url = f"{GH}/{path}"
    if requests:
        r = requests.get(url, timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"{r.status_code} {url}")
        text = r.text
    else:
        text = urlopen(url, timeout=30).read().decode("utf-8")
    os.makedirs(cache_dir, exist_ok=True)
    with open(local, "w", encoding="utf-8") as f:
        f.write(text)
    return pd.read_csv(io.StringIO(text))


def load_all(cache_dir, offline=False, quiet=False):
    def say(m):
        if not quiet:
            print(m, file=sys.stderr)

    say("Hamtar data ...")
    teams = fetch(f"{S_NOW}/teams.csv", cache_dir, offline)
    players = fetch(f"{S_NOW}/players.csv", cache_dir, offline)
    prices = fetch(f"{S_NOW}/playerstats.csv", cache_dir, offline)
    prev_players = fetch(f"{S_PREV}/players.csv", cache_dir, offline)
    hist = fetch(f"{S_PREV}/By%20Gameweek/GW{PREV_LAST_GW}/playerstats.csv", cache_dir, offline)

    def one_gw(i):
        try:
            return fetch(f"{S_NOW}/By%20Gameweek/GW{i}/fixtures.csv", cache_dir, offline)
        except Exception:
            return pd.DataFrame()

    with ThreadPoolExecutor(max_workers=8) as ex:
        parts = list(ex.map(one_gw, range(1, N_GW + 1)))
    fixtures = pd.concat([p for p in parts if len(p)], ignore_index=True)
    say(f"  {len(players)} spelare, {len(teams)} lag, {len(fixtures)} matcher")
    return teams, players, prices, prev_players, hist, fixtures


# ---------------------------------------------------------------- modell
def pois_at_least(k, lam):
    """P(X >= k) for Poisson med medelvarde lam. Validerad mot empiriska
    DefCon-frekvenser: r = 0.97, MAE 0.037."""
    if lam <= 0 or k > 400:
        return 0.0
    term = math.exp(-lam)
    cdf = term
    for i in range(1, k):
        term *= lam / i
        cdf += term
    return max(0.0, min(1.0, 1.0 - cdf))


def elo_exp(elo_for, elo_against, home, ha=60.0):
    """Forvantad poangandel (0-1) enligt Elo, med hemmaplansfordel."""
    f = elo_for + (ha if home else 0.0)
    a = elo_against + (0.0 if home else ha)
    return 1.0 / (1.0 + 10 ** ((a - f) / 400.0))


def exp_to_fdr(e):
    """Forvantad poangandel -> 1-5 (1 = mycket latt motstand)."""
    if e >= 0.70: return 1
    if e >= 0.575: return 2
    if e >= 0.425: return 3
    if e >= 0.30: return 4
    return 5


def build_players(teams, players, prices, prev_players, hist, K, minmin, use_bonus, use_defcon):
    elo = dict(zip(teams["code"].astype(int), teams["elo"].astype(float)))
    short = dict(zip(teams["code"].astype(int), teams["short_name"]))

    # Stabil koppling mellan sasonger via player_code (ingen namnmatchning)
    prev_code = dict(zip(prev_players["player_id"].astype(int),
                         prev_players["player_code"].astype(int)))
    hist = hist.copy()
    hist["code"] = hist["id"].astype(int).map(prev_code)
    hist = hist.dropna(subset=["code"])
    hist["code"] = hist["code"].astype(int)
    hist = hist.drop_duplicates("code").set_index("code")

    pl = players.drop_duplicates("player_id").copy()
    pl.index = pl["player_id"].astype(int)

    rows = []
    for _, r in prices.iterrows():
        pid = int(r["id"])
        if pid not in pl.index:
            continue
        m = pl.loc[pid]
        code = int(m["player_code"])
        if code not in hist.index:
            continue
        h = hist.loc[code]
        mins = float(h.get("minutes", 0) or 0)
        if mins < minmin:
            continue
        cop = r.get("chance_of_playing_next_round")
        cop = None if (pd.isna(cop) or cop == "") else float(cop)
        pen = r.get("penalties_order")
        pen = None if (pd.isna(pen) or pen == "") else int(float(pen))
        rows.append(dict(
            id=pid, name=m["web_name"], tc=int(m["team_code"]),
            team_short=short.get(int(m["team_code"]), "?"),
            pos=POSNUM.get(m["position"], 3), cost=float(r["now_cost"]),
            status=r.get("status", "a"), cop=cop, pen_order=pen,
            minutes=mins, starts=max(1.0, float(h.get("starts", 0) or 0)),
            xg=float(h.get("expected_goals", 0) or 0),
            xa=float(h.get("expected_assists", 0) or 0),
            xgc=float(h.get("expected_goals_conceded", 0) or 0),
            cs=float(h.get("clean_sheets", 0) or 0),
            bonus=float(h.get("bonus", 0) or 0),
            dc=float(h.get("defensive_contribution", 0) or 0),
        ))
    d = pd.DataFrame(rows)
    if d.empty:
        return d, elo, short
    d["p90"] = d["minutes"] / 90.0

    pm = {}
    for et, g in d.groupby("pos"):
        pm[et] = dict(
            xg=g["xg"].sum() / g["p90"].sum(), xa=g["xa"].sum() / g["p90"].sum(),
            xgc=g["xgc"].sum() / g["p90"].sum(), cs=g["cs"].sum() / g["starts"].sum(),
            bon=g["bonus"].sum() / g["p90"].sum(), dc=g["dc"].sum() / g["p90"].sum(),
        )

    def shrink(v, n, prior):
        return (v * n + prior * K) / (n + K)

    pp90, dcr_out, bon_out = [], [], []
    for _, a in d.iterrows():
        et, p90 = a["pos"], a["p90"]
        xg90 = shrink(a["xg"] / p90, p90, pm[et]["xg"])
        xa90 = shrink(a["xa"] / p90, p90, pm[et]["xa"])
        xgc90 = shrink(a["xgc"] / p90, p90, pm[et]["xgc"])
        csr = shrink(a["cs"] / a["starts"], a["starts"], pm[et]["cs"])
        bon90 = shrink(a["bonus"] / p90, p90, pm[et]["bon"]) if use_bonus else 0.0
        lam = shrink(a["dc"] / p90, p90, pm[et]["dc"])
        dcr = pois_at_least(DC_THR[et], lam) if use_defcon else 0.0
        # OBS: repots expected_goals innehaller redan straffar - inget separat tillagg
        pp = 2 + xg90 * GOAL_PTS[et] + xa90 * 3 + bon90
        if et in (1, 2):
            pp += csr * CS_PTS[et] - xgc90 / 2.0
        elif et == 3:
            pp += csr * CS_PTS[et]
        pp += dcr * 2
        pp90.append(pp); dcr_out.append(dcr); bon_out.append(bon90)

    d["pp90"] = pp90
    d["dc_rate"] = dcr_out
    d["bonus90"] = bon_out
    d["minshare"] = (d["minutes"] / (38 * 90)).clip(upper=1.0)
    avail = np.ones(len(d))
    avail[d["status"].values != "a"] = 0.5
    copv = d["cop"].fillna(100).values
    has_cop = d["cop"].notna().values & (copv < 100)
    avail[has_cop] = copv[has_cop] / 100.0
    d["avail"] = avail
    return d, elo, short


def project(d, fixtures, elo, short, horizon, fixweight):
    tf = {}
    has_tour = "tournament" in fixtures.columns
    for _, f in fixtures.iterrows():
        # repot tacker aven cup/Europa, som inte ger FPL-poang
        if has_tour and pd.notna(f["tournament"]) and f["tournament"] != "prem":
            continue
        try:
            gw, th, ta = int(f["gameweek"]), int(f["home_team"]), int(f["away_team"])
        except (ValueError, TypeError):
            continue
        if th not in short or ta not in short:
            continue
        eh = float(f["home_team_elo"]) if pd.notna(f.get("home_team_elo")) else elo.get(th, 1500)
        ea = float(f["away_team_elo"]) if pd.notna(f.get("away_team_elo")) else elo.get(ta, 1500)
        e_home = elo_exp(eh, ea, True)
        tf.setdefault(th, []).append((gw, ta, True, e_home))
        tf.setdefault(ta, []).append((gw, th, False, 1 - e_home))

    rows, gwrows = [], []
    for _, p in d.iterrows():
        fx = sorted(tf.get(p["tc"], []), key=lambda x: x[0])
        total, fdrs = 0.0, []
        for gw, opp, home, e in fx:
            if gw > horizon:
                continue
            # Elo ger forvantad poangandel 0-1; hemmaplan ligger redan i e
            mult = 1 + (e - 0.5) * 4 * fixweight
            pts = p["pp90"] * p["minshare"] * mult * p["avail"]
            total += pts
            fdrs.append(exp_to_fdr(e))
            gwrows.append(dict(id=p["id"], name=p["name"], team=p["team_short"], pos=p["pos"],
                               cost=p["cost"], gw=gw, opp=short.get(opp, "?"), home=home,
                               fdr=exp_to_fdr(e), proj=round(pts, 2)))
        nxt = [(g, short.get(o, "?"), h, exp_to_fdr(e)) for g, o, h, e in fx[:5]]
        rows.append(dict(
            id=p["id"], name=p["name"], team_short=p["team_short"], pos=p["pos"],
            cost=p["cost"], pp90=round(p["pp90"], 2), bonus90=round(p["bonus90"], 2),
            dc_rate=round(p["dc_rate"], 3), pen=("P" if p["pen_order"] == 1 else ""),
            proj=round(total, 1), value=round(total / p["cost"], 2) if p["cost"] else 0,
            fdr=round(float(np.mean(fdrs)), 1) if fdrs else 3.0,
            next5=" ".join(f"{o}({'H' if h else 'A'},{fd})" for _, o, h, fd in nxt),
        ))
    return pd.DataFrame(rows), pd.DataFrame(gwrows)


def optimize(players, budget, locks):
    import pulp
    p = players[players["proj"] > 0].reset_index(drop=True)
    prob = pulp.LpProblem("fpl", pulp.LpMaximize)
    x = [pulp.LpVariable(f"x{i}", cat="Binary") for i in p.index]
    prob += pulp.lpSum(x[i] * p.loc[i, "proj"] for i in p.index)
    prob += pulp.lpSum(x[i] * p.loc[i, "cost"] for i in p.index) <= budget
    for pos, n in {1: 2, 2: 5, 3: 5, 4: 3}.items():
        prob += pulp.lpSum(x[i] for i in p.index if p.loc[i, "pos"] == pos) == n
    for t in p["team_short"].unique():
        prob += pulp.lpSum(x[i] for i in p.index if p.loc[i, "team_short"] == t) <= 3
    for name in locks:
        idx = p.index[p["name"].map(norm) == norm(name)]
        if len(idx):
            prob += x[idx[0]] == 1
        else:
            print(f"  (varning: kunde inte lasa '{name}' - hittades inte)", file=sys.stderr)
    prob.solve(pulp.PULP_CBC_CMD(msg=0))
    if pulp.LpStatus[prob.status] != "Optimal":
        print("Ingen optimal losning - prova lagre --minmin eller farre las.", file=sys.stderr)
        sys.exit(1)
    return p[[bool(x[i].value()) for i in p.index]].copy()


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="FPL Predictor - exakt lagoptimering")
    ap.add_argument("--horizon", type=int, default=10)
    ap.add_argument("--k", type=float, default=10.0, help="regularisering")
    ap.add_argument("--fixweight", type=float, default=0.06)
    ap.add_argument("--minmin", type=int, default=900, help="min speltid forra sasongen")
    ap.add_argument("--budget", type=float, default=100.0)
    ap.add_argument("--lock", action="append", default=[], help="tvinga in spelare (upprepas)")
    ap.add_argument("--no-bonus", action="store_true")
    ap.add_argument("--no-defcon", action="store_true")
    ap.add_argument("--cache-dir", default=".fplcache")
    ap.add_argument("--offline", action="store_true", help="anvand bara cachade filer")
    args = ap.parse_args()

    teams, players, prices, prev_players, hist, fixtures = load_all(args.cache_dir, args.offline)
    d, elo, short = build_players(teams, players, prices, prev_players, hist,
                                  args.k, args.minmin, not args.no_bonus, not args.no_defcon)
    if len(d) < 15:
        print(f"For fa spelare klarade filtret ({len(d)}). Sank --minmin.", file=sys.stderr)
        sys.exit(1)

    proj, gw = project(d, fixtures, elo, short, args.horizon, args.fixweight)
    squad = optimize(proj, args.budget, args.lock)
    squad = squad.sort_values(["pos", "proj"], ascending=[True, False])
    cap = squad[squad["pos"] != 1].sort_values("proj", ascending=False).iloc[0]

    print(f"\n=== OPTIMALT LAG (GW1-{args.horizon}) ===")
    print(f"Kostnad: {squad['cost'].sum():.1f} / {args.budget}m   "
          f"Proj: {squad['proj'].sum():.1f}   Kapten: {cap['name']}\n")
    for pos in (1, 2, 3, 4):
        for _, r in squad[squad["pos"] == pos].iterrows():
            tag = " (C)" if r["name"] == cap["name"] else ""
            pen = " P" if r["pen"] else "  "
            print(f"  {POSMAP[pos]:3} {r['name'] + tag:18}{r['team_short']:5}{r['cost']:5.1f}m"
                  f"{pen}  proj {r['proj']:6.1f}   {r['next5']}")
        print()

    gw.to_csv("proj_by_gw.csv", index=False)
    squad.to_csv("squad_optimal.csv", index=False)
    proj.sort_values("proj", ascending=False).to_csv("proj_all.csv", index=False)
    print("Sparade: squad_optimal.csv, proj_by_gw.csv, proj_all.csv")
    print("P = utsedd strafflaggare. Svarighet 1-5 fran ClubElo (1 = lattast).")


if __name__ == "__main__":
    main()
