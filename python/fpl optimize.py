#!/usr/bin/env python3
"""
FPL Projektor — exakt lagoptimering (Python)
============================================
Samma xG-modell som webb-appen, men med en EXAKT linjär optimering (PuLP/CBC)
istället för webbläsarens heuristik. Använd den här när du vill ha det
matematiskt optimala laget för en slutgiltig uttagning.

INDATA (samma tre filer som appen):
  - stats-CSV     (föregående säsongs per-omgång-statistik)
  - bootstrap.json (fantasy.premierleague.com/api/bootstrap-static/)
  - fixtures.json  (fantasy.premierleague.com/api/fixtures/)

ANVÄNDNING:
  pip install pandas numpy pulp
  python3 fpl_optimize.py stats.csv bootstrap.json fixtures.json
  python3 fpl_optimize.py stats.csv bootstrap.json fixtures.json --horizon 10 --lock Haaland
  python3 fpl_optimize.py ... --k 10 --fixweight 0.06 --minmin 900 --budget 100

UTDATA:
  - Utskrift av optimalt lag + kapten
  - proj_by_gw.csv        (projektion per spelare per gameweek)
  - squad_optimal.csv     (det valda laget)
"""
import argparse, json, sys, unicodedata
import numpy as np, pandas as pd

def norm(s):
    return unicodedata.normalize('NFKD', str(s)).encode('ascii','ignore').decode().lower().strip()

def load(stats_path, boot_path, fix_path):
    stats = pd.read_csv(stats_path)
    boot = json.load(open(boot_path, encoding='utf-8'))
    fix = json.load(open(fix_path, encoding='utf-8'))
    return stats, boot, fix

def build_pp90(stats, K):
    """Regulariserad förväntad poäng per 90 min per historik-spelare."""
    g = stats.groupby(['web_name','team_name','element_type']).agg(
        minutes=('minutes','sum'),
        npxg=('non_penalty_expected_goals','sum'),
        xa=('expected_assists','sum'),
        xgc=('expected_goals_conceded','sum'),
        xcs=('expected_clean_sheet','mean'),
        matches=('gameweek','count'),
    ).reset_index()
    g = g[g['minutes'] > 0].copy()
    g['p90'] = g['minutes'] / 90.0

    # positionssnitt
    pos_mean = {}
    for et, d in g.groupby('element_type'):
        pos_mean[et] = dict(
            npxg=d['npxg'].sum()/d['p90'].sum(),
            xa=d['xa'].sum()/d['p90'].sum(),
            xgc=d['xgc'].sum()/d['p90'].sum(),
            xcs=(d['xcs']*d['matches']).sum()/d['matches'].sum(),
        )

    def shrink(val, n, prior):
        return (val*n + prior*K) / (n + K)

    goal_pts = {1:10, 2:6, 3:5, 4:4}
    cs_pts   = {1:4, 2:4, 3:1, 4:0}
    rows = []
    for _, a in g.iterrows():
        et = a['element_type']; p90 = a['p90']
        npxg90 = shrink(a['npxg']/p90, p90, pos_mean[et]['npxg'])
        xa90   = shrink(a['xa']/p90,   p90, pos_mean[et]['xa'])
        xgc90  = shrink(a['xgc']/p90,  p90, pos_mean[et]['xgc'])
        xcs    = shrink(a['xcs'],      a['matches'], pos_mean[et]['xcs'])
        pp = 2 + npxg90*goal_pts[et] + xa90*3
        if et in (1,2):
            pp += xcs*cs_pts[et] - xgc90/2.0
        elif et == 3:
            pp += xcs*cs_pts[et]
        rows.append(dict(web_name=a['web_name'], team_name=a['team_name'],
                         element_type=et, minutes=a['minutes'], pp90=pp))
    return pd.DataFrame(rows)

def project(pp90df, boot, fix, horizon, fixweight, minmin):
    tshort = {t['id']: t['short_name'] for t in boot['teams']}
    tfull  = {t['id']: t['name'] for t in boot['teams']}

    # lookup: namn+lag+pos, fallback namn+pos (högsta minuter)
    pp90df = pp90df.copy()
    pp90df['nkey'] = pp90df['web_name'].map(norm)
    pp90df['tkey'] = pp90df['team_name'].map(norm)
    by_nlp = pp90df.set_index(['nkey','tkey','element_type'])
    tmp = pp90df.sort_values('minutes', ascending=False).drop_duplicates(['nkey','element_type'])
    by_np = tmp.set_index(['nkey','element_type'])

    def get(nk, tk, et):
        if (nk,tk,et) in by_nlp.index:
            r = by_nlp.loc[(nk,tk,et)]
            return r.iloc[0] if isinstance(r, pd.DataFrame) else r
        if (nk,et) in by_np.index:
            r = by_np.loc[(nk,et)]
            return r.iloc[0] if isinstance(r, pd.DataFrame) else r
        return None

    # fixtures per lag
    teamfix = {}
    for f in fix:
        if f['event'] is None: continue
        teamfix.setdefault(f['team_h'], []).append((f['event'], True,  f['team_h_difficulty'], f['team_a']))
        teamfix.setdefault(f['team_a'], []).append((f['event'], False, f['team_a_difficulty'], f['team_h']))

    rows, gwrows = [], []
    for e in boot['elements']:
        nk, tk, et = norm(e['web_name']), norm(tfull[e['team']]), e['element_type']
        h = get(nk, tk, et)
        if h is None or h['minutes'] < minmin:
            continue
        avail = 1.0
        if e['status'] != 'a': avail = 0.5
        cop = e.get('chance_of_playing_next_round')
        if cop is not None and cop < 100: avail = cop/100.0
        minshare = min(1.0, h['minutes']/(38*90))

        total, fdrs = 0.0, []
        for gw, home, fdr, opp in teamfix.get(e['team'], []):
            if gw > horizon: continue
            fmult = 1 + (3 - fdr)*fixweight
            hmult = 1.03 if home else 0.98
            pts = h['pp90']*minshare*fmult*hmult*avail
            total += pts
            fdrs.append(fdr)
            gwrows.append(dict(id=e['id'], name=e['web_name'], team=tshort[e['team']],
                               pos=et, cost=e['now_cost']/10, gw=gw, opp=tshort[opp],
                               home=home, fdr=fdr, proj=round(pts,2)))
        rows.append(dict(id=e['id'], name=e['web_name'], team_short=tshort[e['team']],
                         pos=et, cost=e['now_cost']/10, pp90=round(h['pp90'],2),
                         proj=round(total,1), value=round(total/(e['now_cost']/10),2),
                         fdr=round(np.mean(fdrs),1) if fdrs else 3.0))
    return pd.DataFrame(rows), pd.DataFrame(gwrows)

def optimize(players, budget, locks):
    import pulp
    p = players[players['proj'] > 0].reset_index(drop=True)
    prob = pulp.LpProblem('fpl', pulp.LpMaximize)
    x = [pulp.LpVariable(f'x{i}', cat='Binary') for i in p.index]
    prob += pulp.lpSum(x[i]*p.loc[i,'proj'] for i in p.index)
    prob += pulp.lpSum(x[i]*p.loc[i,'cost'] for i in p.index) <= budget
    for pos, n in {1:2, 2:5, 3:5, 4:3}.items():
        prob += pulp.lpSum(x[i] for i in p.index if p.loc[i,'pos']==pos) == n
    for t in p['team_short'].unique():
        prob += pulp.lpSum(x[i] for i in p.index if p.loc[i,'team_short']==t) <= 3
    # lås
    for name in locks:
        idx = p.index[p['name'].map(norm) == norm(name)]
        if len(idx):
            prob += x[idx[0]] == 1
        else:
            print(f"  (varning: kunde inte låsa '{name}' — hittades inte)", file=sys.stderr)
    prob.solve(pulp.PULP_CBC_CMD(msg=0))
    if pulp.LpStatus[prob.status] != 'Optimal':
        print("Ingen optimal lösning hittades — pröva lägre --minmin eller färre lås.", file=sys.stderr)
        sys.exit(1)
    return p[[bool(x[i].value()) for i in p.index]].copy()

def main():
    ap = argparse.ArgumentParser(description="FPL exakt lagoptimering")
    ap.add_argument('stats'); ap.add_argument('bootstrap'); ap.add_argument('fixtures')
    ap.add_argument('--horizon', type=int, default=10)
    ap.add_argument('--k', type=float, default=10.0, help='regularisering')
    ap.add_argument('--fixweight', type=float, default=0.06)
    ap.add_argument('--minmin', type=int, default=900)
    ap.add_argument('--budget', type=float, default=100.0)
    ap.add_argument('--lock', action='append', default=[], help='tvinga in spelare (kan upprepas)')
    args = ap.parse_args()

    stats, boot, fix = load(args.stats, args.bootstrap, args.fixtures)
    pp90 = build_pp90(stats, args.k)
    players, gw = project(pp90, boot, fix, args.horizon, args.fixweight, args.minmin)
    if len(players) < 15:
        print(f"För få spelare klarade filtret ({len(players)}). Sänk --minmin.", file=sys.stderr)
        sys.exit(1)

    squad = optimize(players, args.budget, args.lock)
    posmap = {1:'GK', 2:'DEF', 3:'MID', 4:'FWD'}
    squad['P'] = squad['pos'].map(posmap)
    squad = squad.sort_values(['pos','proj'], ascending=[True, False])
    cap = squad[squad['pos'] != 1].sort_values('proj', ascending=False).iloc[0]

    print(f"\n=== OPTIMALT LAG (GW1-{args.horizon}) ===")
    print(f"Kostnad: {squad['cost'].sum():.1f} / {args.budget}m   "
          f"Proj: {squad['proj'].sum():.1f}   Kapten: {cap['name']}\n")
    for pos in [1,2,3,4]:
        for _, r in squad[squad['pos']==pos].iterrows():
            c = ' (C)' if r['name']==cap['name'] else ''
            print(f"  {r['P']:3} {r['name']+c:18}{r['team_short']:5}{r['cost']:5.1f}m  "
                  f"proj {r['proj']:6.1f}  fdr {r['fdr']}")
        print()

    gw.to_csv('proj_by_gw.csv', index=False)
    squad.drop(columns='P').to_csv('squad_optimal.csv', index=False)
    print("Sparade: squad_optimal.csv, proj_by_gw.csv")

if __name__ == '__main__':
    main()
