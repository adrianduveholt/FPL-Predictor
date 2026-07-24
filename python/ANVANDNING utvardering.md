# Utvärderingsloop — bruksanvisning

## Så här gör du när säsongen rullar

1. **Skaffa färsk resultatdata** efter varje omgång i samma CSV-format som
   `fpl-data-stats.csv`. Måste innehålla kolumnerna: `gameweek`, `web_name`,
   `team_name`, `total_points`. (Ladda upp den till mig, eller kör lokalt.)

2. **Kör utvärderingen:**
   ```
   python3 evaluate.py din_resultatfil.csv
   ```
   eller för specifika omgångar:
   ```
   python3 evaluate.py din_resultatfil.csv --gw 1 2 3
   ```

3. **Läs rapporten.** Den visar:
   - MAE, bias och korrelation (hur nära modellen låg)
   - Vilka spelare den över-/undervärderade mest
   - Hur din faktiska trupp gick mot projektionen

4. **Kalibrera om.** Detaljfilen `evaluation_detail.csv` (en rad per spelare/GW)
   är underlaget för att justera modellen — t.ex. sänka K (mindre krympning)
   om modellen är för trög, eller ändra fixture-multiplikatorn om svåra matcher
   straffar för hårt/mjukt.

## Att tänka på (tolkning)
- **En enskild omgång säger nästan ingenting.** FPL har enorm slumpvarians per
  vecka. Utvärdera helst över 5-10 omgångar innan du drar slutsatser.
- **Modellen undervärderar toppar med flit.** Den projicerar snitt; enskilda
  15-24-poängare kan den aldrig förutse. Det är ett drag, inte en bugg.
- **Överpresterar din trupp?** Kan vara skicklighet ELLER tur. Mät över tid.
