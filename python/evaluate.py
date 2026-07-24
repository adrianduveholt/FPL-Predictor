#!/usr/bin/env python3
"""
FPL projektions-utvärdering
===========================
Kör detta när en eller flera gameweeks har spelats och du har en uppdaterad
resultat-CSV i SAMMA format som fpl-data-stats.csv (kolumnerna 'gameweek',
'web_name', 'team_name', 'total_points' måste finnas).

Det jämför modellens projektion (proj_by_gw.csv) mot faktiskt 'total_points'
och rapporterar:
  - Träffsäkerhet totalt (MAE, korrelation, bias)
  - Var modellen övervärderar / undervärderar mest (per spelare & position)
  - Om truppen (squad_xg.csv) presterade som väntat

ANVÄNDNING:
  python3 evaluate.py <resultat.csv>            # utvärdera alla spelade GW i filen
  python3 evaluate.py <resultat.csv> --gw 1 2 3 # bara vissa GW
"""
import sys, argparse, unicodedata
import pandas as pd, numpy as np

def norm(s):
    return unicodedata.normalize('NFKD', str(s)).encode('ascii','ignore').decode().lower().strip()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('results', help='CSV med faktiska resultat (samma format som ursprungsfilen)')
    ap.add_argument('--gw', type=int, nargs='*', default=None, help='Begränsa till dessa gameweeks')
    ap.add_argument('--proj', default='proj_by_gw.csv')
    ap.add_argument('--squad', default='squad_xg.csv')
    args = ap.parse_args()

    proj = pd.read_csv(args.proj)          # id,name,team_short,pos,cost,gw,opp,home,fdr,proj
    actual = pd.read_csv(args.results)     # ...,gameweek,web_name,team_name,total_points,...

    # normaliserad nyckel för join (namn+gw). Modellen har inte team i actual-format garanterat,
    # så vi joinar på namn + gameweek och löser dubbletter på högsta minuter om det finns.
    proj = proj.copy()
    proj['nkey'] = proj['name'].map(norm)
    actual = actual.copy()
    actual['nkey'] = actual['web_name'].map(norm)

    played_gws = sorted(actual['gameweek'].unique())
    if args.gw:
        played_gws = [g for g in played_gws if g in args.gw]
    if not played_gws:
        print('Inga gameweeks att utvärdera. Kontrollera --gw eller filen.'); return

    # Aggregera faktiskt utfall per (namn, gw) — summera om spelaren har flera rader
    act = (actual[actual['gameweek'].isin(played_gws)]
           .groupby(['nkey','gameweek'])['total_points'].sum().reset_index()
           .rename(columns={'total_points':'actual','gameweek':'gw'}))

    pr = proj[proj['gw'].isin(played_gws)][['nkey','gw','name','team_short','pos','proj']]

    m = pr.merge(act, on=['nkey','gw'], how='inner')
    if m.empty:
        print('Ingen matchning mellan projektion och resultat — kolla namnformat.'); return

    m['err'] = m['proj'] - m['actual']        # positiv = övervärderat
    m['abserr'] = m['err'].abs()

    posmap = {1:'GK',2:'DEF',3:'MID',4:'FWD'}
    print(f"=== UTVÄRDERING: GW {played_gws} ===")
    print(f"Matchade spelar-omgångar: {len(m)}")
    print(f"MAE (snittfel):      {m['abserr'].mean():.2f} poäng")
    print(f"Bias (medelfel):     {m['err'].mean():+.2f}  ({'övervärderar' if m['err'].mean()>0 else 'undervärderar'})")
    if m['proj'].std()>0 and m['actual'].std()>0:
        print(f"Korrelation:         {m['proj'].corr(m['actual']):.3f}")
    print()

    print("Per position (MAE / bias):")
    for pos,lbl in posmap.items():
        sub=m[m['pos']==pos]
        if len(sub):
            print(f"  {lbl}: MAE {sub['abserr'].mean():.2f}  bias {sub['err'].mean():+.2f}  (n={len(sub)})")
    print()

    print("Modellen ÖVERVÄRDERADE mest (proj >> faktiskt):")
    for _,r in m.sort_values('err',ascending=False).head(6).iterrows():
        print(f"  GW{int(r['gw'])} {r['name']:15}{r['team_short']:5} proj {r['proj']:.1f} vs verklig {r['actual']:.0f}")
    print()
    print("Modellen UNDERVÄRDERADE mest (missade poäng):")
    for _,r in m.sort_values('err').head(6).iterrows():
        print(f"  GW{int(r['gw'])} {r['name']:15}{r['team_short']:5} proj {r['proj']:.1f} vs verklig {r['actual']:.0f}")
    print()

    # Hur gick truppen?
    try:
        squad = pd.read_csv(args.squad)
        squad['nkey']=squad['name'].map(norm)
        sq = m[m['nkey'].isin(squad['nkey'])]
        if len(sq):
            print(f"=== DIN TRUPP ({squad.shape[0]} spelare) ===")
            print(f"Truppens faktiska poäng {played_gws}: {sq['actual'].sum():.0f}")
            print(f"Truppens projicerade:           {sq['proj'].sum():.1f}")
            print(f"Diff:                           {sq['actual'].sum()-sq['proj'].sum():+.1f}")
    except FileNotFoundError:
        pass

    m.to_csv('evaluation_detail.csv', index=False)
    print("\nSparade radnivå-detaljer: evaluation_detail.csv")
    print("(Använd dessa för att kalibrera om modellen — t.ex. justera K eller fixture-multiplikatorn.)")

if __name__ == '__main__':
    main()
