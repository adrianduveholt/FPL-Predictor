# FPL Projektor

En xG-baserad laguttagning för Fantasy Premier League som körs **helt i webbläsaren**. Ladda upp din data, få projektioner, ett optimerat lag och konkreta bytesförslag. Ingen server, ingen inloggning, ingen data lämnar din dator.

![Status](https://img.shields.io/badge/körs-i%20webbläsaren-3ddc97) ![Data](https://img.shields.io/badge/data-lokal%20%C2%B7%20aldrig%20uppladdad-5fb2ff)

---

## Vad den gör

Modellen räknar inte på förra säsongens *poäng* rakt av — den bygger på **underliggande prestation** och projicerar framåt:

- **xG per 90 minuter** (non-penalty xG, xA, xGC, xClean sheet) per spelare
- **Regularisering** som krymper små stickprov mot positionssnittet, så en spelare med 200 tursamma minuter inte rankas över en pålitlig helårsspelare
- **Fixture-viktning** mot kommande motstånds svårighet (FDR), med hemma/borta-justering
- **Tillgänglighet** utifrån skadestatus och spelchans
- **Lagoptimering** inom FPL:s regler: 100.0m, 2 GK / 5 DEF / 5 MID / 3 FWD, max 3 per klubb

Resultatet är ett förslag på det bästa laget för din valda horisont — plus en fullständig, sorterbar rankning av alla spelare.

## Använda den

1. Öppna appen (se **Publicera** nedan, eller öppna `fpl-projektor.html` direkt i en webbläsare).
2. Ladda upp tre filer:

   | Fil | Vad det är | Var den hämtas |
   |-----|-----------|----------------|
   | **Spelarstatistik (CSV)** | Föregående säsongs per-omgång-stats | Din FPL-data-export |
   | **Bootstrap (JSON)** | Aktuella priser, lag, positioner | [bootstrap-static](https://fantasy.premierleague.com/api/bootstrap-static/) |
   | **Fixtures (JSON)** | Kommande säsongs schema med svårighet | [fixtures](https://fantasy.premierleague.com/api/fixtures/) |

   De två JSON-länkarna finns också direkt i appen, under uppladdningsrutorna — klicka, spara filen, ladda upp. Uppdatera dem inför varje ny säsong (och vid behov under säsongen när priser ändras).

3. Tryck **Kör projektion**.

### Funktioner

- **Modellparametrar** — vrid på horisont (1–38 GW), regularisering, fixture-vikt och lägsta speltid och se laget uppdateras direkt.
- **Lås spelare** (○ / ● i tabellen) — tvinga in en spelare, t.ex. Haaland, så byggs laget om runt honom. Kaptenen sätts automatiskt till lagets högst projicerade utespelare.
- **Exportera** — ladda ner laget eller alla projektioner som CSV.
- **Jämför mot mitt lag** — klistra in dina spelares namn och få en rättvis jämförelse (poäng per spelare) plus konkreta uppgraderingsförslag i samma prisklass.

## Publicera på GitHub Pages

1. Lägg `fpl-projektor.html` i ett repo (döp den gärna till `index.html` om den ska vara startsidan).
2. **Settings → Pages → Source: `main` / root.**
3. Öppna `https://<ditt-användarnamn>.github.io/<repo>/`.

Eftersom allt räknas i webbläsaren behövs ingen backend — Pages serverar bara filen.

## Att veta om modellen

Modellen är ett **beslutsstöd, inte facit.** Var ärlig mot dig själv om vad den kan och inte kan:

- Den bygger på **föregående säsongs** data. Nyförvärv utan Premier League-historik och nyuppflyttade lags spelare är osynliga eller undervärderade.
- Den ser inte **straffläggare, hörnor eller uppställningsbyten** — bara underliggande xG.
- Enskilda gameweeks har **stor slumpvarians**. Projektionen är ett snitt; den kan aldrig förutse en enskild 20-poängare. Utvärdera över 5–10 omgångar, inte en.
- Optimeraren i webbläsaren är en **value-driven heuristik** med swap-förbättring — mycket nära, men inte garanterat matematiskt optimal. För exakt optimum, använd Python-scripten (se nedan).

## Exakt optimering & utvärdering (Python)

Webb-appens optimerare är snabb men en heuristik. För det **matematiskt optimala** laget, och för att **utvärdera modellen mot facit** allteftersom säsongen spelas, finns två Python-script i `python/`:

```bash
pip install pandas numpy pulp

# Exakt LP-optimering (samma modell, exakt lösning)
python3 python/fpl_optimize.py stats.csv bootstrap.json fixtures.json
python3 python/fpl_optimize.py stats.csv bootstrap.json fixtures.json --horizon 10 --lock Haaland

# Utvärdera projektion mot verkligt utfall (kör när omgångar spelats)
python3 python/evaluate.py fardiga_resultat.csv --gw 1 2 3
```

`fpl_optimize.py` skriver ut det optimala laget och sparar `squad_optimal.csv` + `proj_by_gw.csv`. `evaluate.py` jämför projektion mot faktiska poäng och rapporterar träffsäkerhet (MAE, bias, korrelation) plus var modellen över-/undervärderade — underlaget för att kalibrera om den. Se `python/ANVANDNING_utvardering.md` för hela flödet.

## Filer i repot

| Fil | Beskrivning |
|-----|-------------|
| `fpl-projektor.html` | Hela webb-appen — en enda fil, inga beroenden |
| `python/fpl_optimize.py` | Exakt LP-optimering (CBC via PuLP) |
| `python/evaluate.py` | Utvärdering av projektion mot verkligt utfall |
| `python/ANVANDNING_utvardering.md` | Så använder du utvärderingsloopen |
| `README.md` | Den här filen |

## Sekretess

All databehandling sker lokalt i din webbläsare via JavaScript. Filerna du laddar upp skickas aldrig någonstans. Du kan verifiera det genom att köra appen offline.

---

*Byggd som ett internt verktyg. FPL och Premier League är varumärken som tillhör sina respektive ägare; det här projektet är inte anslutet till dem.*
