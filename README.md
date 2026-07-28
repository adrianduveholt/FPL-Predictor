# FPL Predictor

En xG-baserad laguttagning för Fantasy Premier League som körs **helt i webbläsaren**. Ett klick hämtar färsk data, räknar projektioner och sätter ihop ett optimerat lag. Ingen server, ingen inloggning, inget konto.

![Status](https://img.shields.io/badge/körs-i%20webbläsaren-3ddc97) ![Data](https://img.shields.io/badge/data-auto%20från%20GitHub-5fb2ff)

---

## Använda den

1. Öppna appen (se **Publicera** nedan, eller öppna `fpl-projektor.html` direkt i en webbläsare).
2. Tryck **Hämta & kör**.

Det är allt. Inga filer att ladda ner, inga uppladdningar. Appen hämtar publika CSV-filer från [FPL Core Insights](https://github.com/olbauday/FPL-Core-Insights) och räknar allt lokalt. Datakällan uppdateras två gånger dagligen (07:30 och 17:30 UTC), så priser, skadelägen och spelschema är alltid färska.

Följande hämtas, ~630 kB totalt:

| Fil | Vad det ger |
|-----|-------------|
| `2026-2027/teams.csv` | lag + ClubElo-ratings |
| `2026-2027/players.csv` | namn, lag, position |
| `2026-2027/playerstats.csv` | priser, skadestatus, utsedd straffläggare |
| `2025-2026/By Gameweek/GW38/playerstats.csv` | förra säsongens totaler, inkl. bonuspoäng |
| `2026-2027/By Gameweek/GW{1-38}/fixtures.csv` | hela spelschemat med Elo per match |

Spelare kopplas mellan säsongerna via `player_code`, som är stabil över tid. Ingen namnmatchning, och därmed inga förväxlingar mellan spelare som delar efternamn.

## Vad modellen gör

- **xG och xA per 90 minuter** från föregående säsong
- **Bonuspoäng** per 90 minuter, regulariserat
- **DefCon** — sannolikheten att nå FPL:s tröskel för defensiva bidrag (10+ för backar, 12+ för mittfält och anfall), skattad med Poisson och värd 2 poäng vid trigger
- **Hållna nollor och insläppta mål** för målvakter och backar
- **Regularisering** som krymper små stickprov mot positionssnittet, så en spelare med 200 tursamma minuter inte rankas över en pålitlig helårsspelare
- **Fixture-viktning** via ClubElo — förväntad poängandel per match, med hemmaplansfördel inbakad
- **Tillgänglighet** utifrån skadestatus och spelchans
- **Lagoptimering** inom FPL:s regler: 100.0m, 2 GK / 5 DEF / 5 MID / 3 FWD, max 3 per klubb

Bonus och DefCon kan slås av och på i appen om du vill se hur mycket de påverkar.

## Gränssnittet

Fyra åtskilda vyer, så det alltid är tydligt vad du planerar:

| Vy | Innehåll |
|----|----------|
| **Optimerat lag** | Startelva per lagdel, bänk, poänguppdelning, pris-mot-poäng, fixtur-värmekarta |
| **Alla spelare** | Sökbar och sorterbar lista (poäng / värde / fixtur), lås spelare |
| **Bytesplan** | UT→IN-kort med motiv, plus plan per omgång |
| **Chip-plan** | Bästa omgång per chip och halva |

På dator ligger navigeringen i en vänstermeny och spelardetaljer i en högerpanel. På mobil blir
navigeringen en tab-bar i botten och detaljerna ett bottenblad. Samma fil, ingen separat mobilversion.

Klicka på en spelare — på planen, bänken eller i listan — för att se projektion, kommande fem
motstånd, var poängen kommer ifrån och nyckeltal, samt låsa spelaren i laget.

### Ingen simulerad osäkerhet

Gränssnittet visar medvetet **inga konfidensintervall eller sannolikheter**. Modellen ger
punktskattningar, och att rita fördelningskurvor kring dem skulle antyda en precision som inte
finns. Där en sådan panel annars hade legat visas istället **uppdelningen av var poängen kommer
ifrån** — grundpoäng, mål, assist, bonus, hållen nolla, DefCon och insläppta mål. Det är
modellens faktiska delar, inte en skattning av spridning.

## Funktioner

- **Modellparametrar** — vrid på horisont (1–38 GW), regularisering, fixture-vikt och lägsta speltid och se laget uppdateras direkt.
- **Kommande 5 matcher** — varje spelare visar nästa motståndare med hemma/borta, följt av små färgade pluppar för de återstående fyra. Mörkgrön = mycket lätt, grön = lätt, grå = lika, röd = svår, mörkröd = mycket svår. Håll pekaren över en plupp för motståndare och omgång.
- **Lås spelare** (○ / ● i tabellen) — tvinga in en spelare, t.ex. Haaland, så byggs laget om runt honom. Kaptenen sätts automatiskt till lagets högst projicerade utespelare.
- **Straffläggarflagga** — spelare markerade **P** är sitt lags utsedda straffläggare den här säsongen.
- **Exportera** — ladda ner laget eller alla projektioner som CSV.
- **Jämför mot mitt lag** — klistra in dina spelares namn och få en rättvis jämförelse (poäng per spelare) plus konkreta uppgraderingsförslag i samma prisklass.
- **Tre tydligt åtskilda flikar** — *Lag & spelare*, *Bytesplan* och *Chip-plan*, så det alltid är klart vad du planerar.
- **Chip-plan** — bästa omgång för Bench Boost, Triple Captain, Free Hit och Wildcard, per halva av säsongen.
- **Bytesplan** — planerar byten över 3, 5 eller 8 omgångar framåt: vilka byten, vilken omgång, när det lönar sig att spara fria byten och när ett −4 är värt det. Utgår från antingen det optimala laget eller ditt eget.

## Bytesplanen

Bytesplanering är ett flerperiodsproblem: ett byte i GW2 påverkar vad som är möjligt i GW5, och att spara ett fritt byte kan vara mer värt än att använda det direkt. Båda versionerna modellerar det, men olika noggrant.

**I appen** körs en beam search som testar noll, ett eller två byten per omgång — inklusive det klassiska draget att nedgradera en spelare för att finansiera en uppgradering av en annan. Snabbt och visuellt, men inte garanterat optimalt.

**I Python** (`fpl_plan.py`) löses hela sekvensen exakt med MILP. Den bestämmer trupp, startelva och kapten för varje omgång samtidigt, med bivillkor för fria byten (max 5 sparade), −4-avdrag, budget och max tre per klubb.

```bash
python3 python/fpl_plan.py                              # från optimalt lag
python3 python/fpl_plan.py --team-id 1234567            # hämtar DITT lag från FPL
python3 python/fpl_plan.py --squad "Haaland,Saka,..."   # klistra in manuellt
python3 python/fpl_plan.py --horizon 5 --ft 2 --bank 1.5
```

### Hämta ditt eget lag

`--team-id` läser ditt lag direkt från FPL:s publika API. **Ingen inloggning behövs och
appen frågar aldrig efter ditt lösenord.** Endpointen `entry/{id}/event/{gw}/picks/` är
öppen; det enda som krävs är ditt lag-ID.

Ditt ID hittar du genom att logga in på fantasy.premierleague.com, gå till *Pick Team* →
*View Gameweek history* och läsa av numret i URL:en.

Bank hämtas automatiskt från FPL om du inte anger `--bank` själv.

Tre saker att känna till:

- **Före säsongsstart finns ingenting att hämta.** FPL gör picks publika först efter att
  en gameweek-deadline passerat. Fram till dess får du använda `--squad`.
- **FPL kan blockera vissa nätverk** (servrar och VPN får ofta HTTP 403). Spara då
  `https://fantasy.premierleague.com/api/entry/<ID>/event/<GW>/picks/` till en fil och
  använd `--picks-file mitt_lag.json`.
- **Spelare utan Premier League-historik utesluts** ur modellen, och den tomma platsen
  räknas då som ett byte i planen. Kör med `--minmin 0` för att få med dem.

### Hämta ditt eget lag i appen

Kortet **MITT FPL-LAG** överst i appen tar ditt lag-ID och används sedan av Bytesplan,
Chip-plan och Jämför. Ingen inloggning — endpointen är publik.

Ditt ID hittar du på fantasy.premierleague.com under *Pick Team* → *View Gameweek history*;
siffran står i URL:en.

**Om direkthämtningen blockeras** visar appen automatiskt en manuell väg: två länkar att öppna
i en ny flik och en ruta att klistra in JSON-svaret i. Samma resultat, tar tio sekunder.
Anledningen är FPL:s CORS-policy, som avgör om en webbsida får läsa deras API — vi har inte
kunnat verifiera den, så appen försöker och faller tillbaka.

När laget är inläst fylls banken i automatiskt, spelarnamnen skrivs in i textrutorna så du ser
vad som hämtats, och spelare som saknas i modellen flaggas. Matchningen sker på FPL:s element-ID,
inte på namn, så det kan inte bli förväxlingar.

### Varför ingen inloggning

Det vore tekniskt möjligt att logga in och läsa `my-team`-endpointen, som visar byten du
gjort men inte låst än. Det gör vi medvetet inte: en statisk sida kan inte hantera
lösenord säkert, det kräver serversidig sessionshantering, och nyttan är marginell
jämfört med risken. Lag-ID ger nästan samma information utan att några uppgifter lämnar
din dator.

Körtid är några sekunder. `--candidates` styr poolens storlek — högre ger bättre lösning men tar längre tid (110 är standard, 220 tar ~7 sekunder).

### Vad planen inte tar hänsyn till

- **Prisförändringar och försäljningspris.** Inköpspris antas vara dagens pris. Det gör att modellen ibland säljer en spelare och köper tillbaka honom några omgångar senare — i verkligheten kostar det pengar.
- **Chips.** Wildcard, Free Hit, Bench Boost och Triple Captain modelleras inte.
- **Osäkerhet.** Solio visar en fördelning (t.ex. 306,5 ±29,4) från en stokastisk simulering. Den här modellen ger punktskattningar, ingen spridning.
- **Bänkpoäng.** Bänken antas ge noll.

En observation värd att ta med: utgår du från ett lag som redan använder hela budgeten finns det ofta *ingen* spelare som är både bättre och billigare, och då hittar planen få eller inga byten. Det är ett riktigt svar, inte ett fel — spara de fria bytena till skador och formförändringar istället.

## Chip-planen

FPL:s chips förnyas vid halvtid — du får ett av varje per halva, alltså åtta totalt. Fönstren
kommer från FPL:s egna regler:

| Chip | Första halvan | Andra halvan |
|---|---|---|
| Bench Boost | GW1–19 | GW20–38 |
| Triple Captain | GW1–19 | GW20–38 |
| Free Hit | GW2–19 | GW20–38 |
| Wildcard | GW2–19 | GW20–38 |

Wildcard och Free Hit går inte att spela i GW1; Bench Boost och Triple Captain gör det.

### Så värderas de

- **Triple Captain** — vad kaptenen ger en gång till, i den omgången.
- **Bench Boost** — summan av de fyra bänkspelarnas projektion.
- **Free Hit** — bästa möjliga elva minus din egen elva den omgången.
- **Wildcard** — nyoptimerad trupp för resten av fönstret minus din nuvarande trupp.

Wildcard och Free Hit räknas mot ditt **lagvärde**, inte mot 100m — ett wildcard ger dig det
laget är värt att handla för.

```bash
python3 python/fpl_chips.py                     # från optimalt lag
python3 python/fpl_chips.py --team-id 1234567   # från ditt lag
python3 python/fpl_chips.py --wc-stride 1       # utvärdera Wildcard varje omgång (långsamt)
```

### Den viktigaste begränsningen

**Dubbel- och blankomgångar avgör chip-timing i praktiken, men de finns inte i schemat än.**
De uppstår när cupmatcher tvingar fram ommatchningar under säsongen. Så länge schemat är
orört (760 lag-omgångar med exakt en match var) bygger rangordningen bara på motståndsstyrka,
och skillnaderna blir små — Triple Captain landar på ungefär samma värde i halva omgångarna.

Både appen och scriptet varnar när det ser ut så. Kör om analysen från oktober–november när
omgångarna börjar spricka; då blir siffrorna verkligt användbara. Bench Boost är värt ungefär
dubbelt i en dubbelomgång, och Free Hit får nästan hela sitt värde från blanka omgångar.

**Wildcard är det minst tillförlitliga av de fyra måtten.** Det jämför en nyoptimerad trupp mot
din nuvarande, men räknar inte in att du ändå skulle göra vanliga byten under perioden. Läs det
som "hur långt från optimalt ligger mitt lag" snarare än som en exakt poängvinst.

## Om svårighetsgraden

Svårigheten räknas ur **ClubElo-ratings**, inte FPL:s egen FDR — datakällan innehåller ingen FDR-kolumn. Formeln är standard Elo med ~60 poäng hemmaplansfördel, omräknad till en femgradig skala. Fördelningen över GW1–10 blir jämn: 18% mycket lätt, 16% lätt, 32% lika, 16% svår, 18% mycket svår.

Konsekvens: **färgerna matchar inte den officiella Fantasy-appen.** Elo skiljer starkare på lagen — Man City hemma mot Bournemouth blir mycket lätt här, medan FPL sätter den som neutral. Elo är sannolikt den bättre signalen, men det är ett annat mått.

## Vad modellen inte gör

**Straffar ingår implicit.** Datakällans `expected_goals` innehåller redan straffar, så modellen lägger inte på något separat strafftillägg — det vore dubbelräkning. Nackdelen är att *rollbyten* inte fångas: en spelare som blir ny straffläggare får ingen uppräkning. Utsedd läggare visas därför med **P** i tabellen så du kan väga in det själv.

**Nyförvärv utan Premier League-historik är osynliga**, liksom spelare från nyuppflyttade klubbar.

**Enskilda gameweeks har stor slumpvarians.** Projektionen är ett snitt och kan aldrig förutse en enskild 20-poängare. Utvärdera över 5–10 omgångar, inte en.

**Optimeraren i webbläsaren är en heuristik** (value-driven med swap-förbättring), mycket nära men inte garanterat matematiskt optimal. Python-scriptet nedan använder exakt LP och ger samma modell men optimal lösning.

## Jämfört med Solio Analytics

[Solio Analytics](https://fpl.solioanalytics.com/) bygger på spelmarknader och en stokastisk modell och är tydligt bättre som prediktionsmotor. Den här modellen ligger efter, men avståndet har krympt betydligt:

| Modell | Spearman ρ | MAE mot Solios GW1 |
|--------|-----------|--------------------|
| Ursprunglig (manuell CSV, ingen bonus) | 0,314 | 1,71 p |
| Nuvarande (GitHub-data, bonus + DefCon + Elo) | **0,414** | **1,08 p** |

MAE ner 37%, rangkorrelation upp 32%. Nyansen är att bonus förbättrar både rangordning och nivå, medan DefCon kraftigt förbättrar nivån men sänker rangkorrelationen något. Urvalet är bara Solios topp 30 för en enda omgång, så läs siffrorna som en indikation snarare än en dom.

Använd gärna Solio för skarpa beslut. Den här appen är ett transparent andra utlåtande där du kan läsa och ändra varje rad.

## Publicera på GitHub Pages

1. Lägg `fpl-projektor.html` i ett repo (döp den till `index.html` om den ska vara startsidan).
2. **Settings → Pages → Source: `main` / root.**
3. Öppna `https://<ditt-användarnamn>.github.io/<repo>/`.

Eftersom allt räknas i webbläsaren behövs ingen backend.

## Python-scripten

Samma modell och samma datakälla som webb-appen, men med **exakt** LP-optimering (PuLP/CBC)
istället för webbläsarens heuristik. Använd när du vill ha det matematiskt optimala laget.
Ingen indata behövs — scriptet hämtar allt själv och cachar i `.fplcache/`.

```bash
pip install pandas numpy pulp requests

# Hämta och kör
python3 python/fpl_optimize.py
python3 python/fpl_optimize.py --horizon 10 --lock Haaland
python3 python/fpl_optimize.py --no-bonus --no-defcon   # stäng av komponenter
python3 python/fpl_optimize.py --offline                # kör på cachad data

# Utvärdera projektionen mot verkligt utfall när omgångar spelats
python3 python/evaluate.py fardiga_resultat.csv --gw 1 2 3
```

`fpl_optimize.py` skriver `squad_optimal.csv`, `proj_all.csv` och `proj_by_gw.csv`.
`evaluate.py` läser den sista och jämför mot faktiska poäng — den rapporterar MAE, bias och
korrelation plus var modellen över- och undervärderade. Se `python/ANVANDNING_utvardering.md`.

Webb-appen och Python-scriptet ger identiska projektioner; skillnaden ligger bara i optimeraren.

## Filer i repot

| Fil | Beskrivning |
|-----|-------------|
| `fpl-projektor.html` | Hela webb-appen — en enda fil, inga beroenden |
| `python/fpl_optimize.py` | Exakt LP-optimering, hämtar data själv |
| `python/fpl_plan.py` | Bytesplanering över flera omgångar (MILP), hämtar ditt lag via lag-ID |
| `python/fpl_chips.py` | Chip-planering: bästa omgång per chip och halva |
| `python/evaluate.py` | Utvärdering mot verkligt utfall |
| `python/ANVANDNING_utvardering.md` | Så använder du utvärderingsloopen |

## Sekretess & källa

All databehandling sker lokalt i din webbläsare. Appen läser publika CSV-filer från GitHub och skickar ingenting någonstans.

Data från [olbauday/FPL-Core-Insights](https://github.com/olbauday/FPL-Core-Insights) och [ClubElo](http://clubelo.com/). FPL och Premier League är varumärken som tillhör sina respektive ägare; det här projektet är inte anslutet till dem.
