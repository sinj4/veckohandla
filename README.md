# Veckohandla 🛒

Veckohandla är en bot som planerar veckans middagar utifrån butikernas veckokampanjer. Den fyller din varukorg på Willys och mejlar dig meny, recept och inköpslista.

*A bot that plans the week's dinners from Swedish grocery store deals (Willys, ICA), fills your Willys online cart and emails you the menu. Swedish-language project.*

## Vad den gör

Varje vecka:

1. **Skannar kampanjer** i Willys e-handel, Willys-butikens egna hyllkampanjer och valfria ICA-butiker (via ica.se/erbjudanden).
2. **Planerar middagar** med Claude utifrån kampanjerna och ditt hushåll: antal personer, barnens åldrar, önskemål och sådant som ska undvikas. Rätter från de senaste veckorna upprepas inte.
3. **Matchar varje ingrediens** mot sortimentet i *din* Willys-butik och väljer billigaste rimliga vara, plus upp till 3 reserver. Den tar hänsyn till "2 för"-kampanjer, "max 1 köp/hushåll" och lösvikt.
4. **Jämför med butikskampanjer, men korgen är alltid komplett.** Allt som finns i Willys e-handel läggs i korgen till e-handelns pris. Är en vara billigare som Willys butikskampanj eller på ICA flaggas raden i rapporten, till exempel "Billigare i butik: … spar 29,10 kr. Ta bort ur korgen om du köper den där." Direkt efter varukorgsrutan finns en sammanfattning per butik. Flaggor visas bara för en butik vars samlade besparing når tröskeln. Kostnaden för Willys butikskampanjer räknas ur kampanjen. Varor som inte finns i e-handeln alls listas som "Köp i butik".
5. **Kontrollerar att varan finns i butiken och att ingredienserna klarar dina spärrord**, till exempel fläsk i färdiga köttbullar. Faller huvudvalet bort tas nästa reserv.
6. **Fyller Willys-varukorgen.** Boten lägger bara till det som fattas och tar aldrig bort något. Den lägger **aldrig** någon order, det gör du själv efter att ha granskat korgen.
7. **Skickar en rapport** med meny, recept, varukorg och prisuppgifter, via mejl och som HTML-fil. Går något fel kommer ett felmejl i stället.

## Kom igång

Det här behövs:
- Python 3.11 eller senare.
- Ett Willys-konto.
- Antingen [Claude Code](https://claude.com/claude-code) inloggat med ett Claude Pro- eller Max-abonnemang, eller en `ANTHROPIC_API_KEY`.

```sh
git clone https://github.com/<du>/veckohandla && cd veckohandla
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m playwright install chromium

cp config.example.yaml config.yaml   # anpassa hushåll, önskemål och butiker
cp .env.example .env                 # valfritt: API-nyckel och SMTP-lösenord

.venv/bin/python -m veckohandla hitta-willys <ort>   # hitta store_id för din Willys
.venv/bin/python -m veckohandla hitta-hemkop <ort>   # … eller för ditt Hemköp
.venv/bin/python -m veckohandla erbjudanden          # kontrollera att kampanjerna hämtas
.venv/bin/python -m veckohandla login                # logga in en gång hos kedjan i butiker.e_handel
.venv/bin/python -m veckohandla kor --ingen-mejl     # testkörning, rapporten hamnar i data/
.venv/bin/python -m veckohandla fyll-varukorg        # lägg den granskade listan i Willys-korgen
```

Du kan också planera och fylla korgen i ett steg med `kor --fyll-varukorg`.

Rapporten säger överst om korgen inte är fylld än och vilket kommando som fyller den. Kommandot tas från **`VECKOHANDLA_FYLL_KOMMANDO`**, med `python -m veckohandla fyll-varukorg <vecka>` som standard.

### Valläget: välj själv bland förslag
Med `meny: {lage: val, forslag: 10}` i `config.yaml` gör `kor` ingen färdig meny. I stället föreslår Claude (`model_meny`) tio numrerade rätter utifrån veckans kampanjer. Förslagen följer önskemålen och `undvik` och upprepar inga rätter från de senaste veckornas valda menyer. De sparas i `data/<vecka>-forslag.json` och mejlas som numrerade kort, med kommandot för att välja överst.
```sh
.venv/bin/python -m veckohandla forslag                     # visa förslagen med nummer
.venv/bin/python -m veckohandla valj 2 4 5 8 9 --fyll-varukorg
```
`valj` ger de valda rätterna veckodagar från måndag i den ordning du skrev numren. Claude (`model_produkter`) gör inköpslistan för just de rätterna, och sedan går resten precis som i auto-läget: kampanjerna hämtas på nytt, och produkter väljs i din Willys-butik med reserver, tillgänglighets- och ingredienskontroll, storpack, lager och butiksflaggor. Till sist sparas korgfilen och rapporten mejlas. `data/<vecka>.json` får bara de valda rätterna. `--vecka 2026-v43` väljer bland en viss veckas förslag; standard är de senaste. Ogiltiga nummer ger ett fel innan något anrop görs. `--en-gang-per-vecka` tittar i valläget på förslagsfilen.

Flaggor och miljövariabler för schemalagda körningar:
- **`kor --en-gang-per-vecka`** avslutar direkt om veckans plan (`data/<vecka>.json`) redan finns. Ett schema kan då köra flera gånger, och den första lyckade körningen gäller.
- **`kor --onskemal "fisk två gånger, ingen kyckling"`** lägger till önskemål bara för den här körningen.
- **Kontroll av kampanjerna:** innan Claude anropas kontrolleras att veckans kampanjer är uppe. Minst en Willys butikskampanj måste ha `startDate` i innevarande ISO-vecka. E-handelns kampanjer saknar startdatum. Är kampanjerna inte uppe avslutar `kor` med **exit-kod 3** och meddelandet "Veckans kampanjer är inte uppe än", utan Claude-anrop och utan felmejl.
- **Mejlet måste komma fram:** körs `kor` utan `--ingen-mejl` och rapporten inte kan mejlas (lösenordet saknas, SMTP-inloggningen nekas eller sändningen misslyckas) avslutar den med **exit-kod 4**. Rapporten är då redan sparad i `data/`.
- **Claude Code-binär:** `CLAUDE_BIN` väljer binär, annars `claude` i PATH och sist `~/.local/bin/claude`. Sökväg och version loggas en gång per körning.
- **`VECKOHANDLA_CONFIG`** pekar ut config-filen och **`VECKOHANDLA_DATA`** datakatalogen, till exempel i ett privat repo. Standard är `config.yaml` och `data/` i projektkatalogen.

`fyll-varukorg` går att köra flera gånger. Boten läser först korgen och lägger bara till det som fattas, så du får inga dubbla mängder och inget tas bort. Rader med samma vara, till exempel bananer både i `alltid_kop` och i ett recept, räknas ihop. Nekar Willys en vara prövas radens reserver i tur och ordning, och bytena visas i terminalen och rapporten. Har Willys-inloggningen gått ut kommer rapporten och mejlet ändå, med instruktioner om att köra `login` och sedan `fyll-varukorg <vecka>`.

### Schemaläggning (macOS)
```sh
./schema/installera.sh     # körs måndagar 06:30
./schema/avinstallera.sh   # tar bort schemat igen
```
Testa schemat direkt, utan att vänta till måndag. Det kör `kor --fyll-varukorg` på riktigt, alltså Claude, varukorg och mejl:
```sh
launchctl kickstart -k gui/$(id -u)/se.veckohandla
tail -f data/senaste-korning.log     # varje körning börjar med en rad med datum och tid
```
På Linux fungerar en cron-rad som kör `.venv/bin/python -m veckohandla kor --fyll-varukorg` från projektkatalogen.

### Willys eller Hemköp
Hemköp ägs av Axfood, precis som Willys, och har samma API. `butiker.e_handel` (`willys` eller `hemkop`, standard `willys`) väljer kedjan där varor söks och korgen fylls. Den andra kedjan kan stå med i `butiker` för jämförelse: dess butikskampanjer hämtas, kostnaden räknas ur kampanjen, och billigare varor flaggas i rapporten precis som för ICA. Samma ingredienskontroll gäller, eftersom produktkoderna är gemensamma, och prishistoriken sparas för båda kedjorna. Inloggningen sparas per kedja (`browser-profiles/willys`, `browser-profiles/hemkop`), så `login` och `fyll-varukorg` gäller kedjan i `e_handel`. Korgen hos Hemköp är byggd på samma API som Willys men inte provad mot ett riktigt konto.

## Konfiguration

Allt ställs in i `config.yaml`, se de kommenterade exemplen i [`config.example.yaml`](config.example.yaml).

- **`undvik`**: hårda krav som skickas till Claude, till exempel "fläsk i alla former" eller "nötter".
- **`sparrord`**: ett skyddsnät i koden. Produkter vars namn innehåller något av orden tas bort innan Claude ser dem.
- **`skafferi`**: varor som alltid finns hemma och därför aldrig köps.
- **`gar_alltid_at`**: varor som alltid går åt, antingen bara namnet (`ägg`) eller `{vara: ägg, per_vecka: 12}`, där `per_vecka` är vad hushållet gör av med totalt per vecka. Med `per_vecka` uppskattar boten lagret ur de fyra senaste `data/<vecka>-korg.json`: köpta enheter läggs till, och `per_vecka` dras av för varje vecka som gått. Räcker lagret till veckans behov, minst `per_vecka`, läggs varan inte i korgen. Den listas då under "Kolla om du har hemma" med "Uppskattat kvar: ca N st". Korgfilen visar vad som **planerades**, inte vad som faktiskt köptes eller åts, så det är en uppskattning. Har du ändrat i korgen på willys.se eller köpt ägg någon annanstans stämmer den inte. För sådana rader tar Claude med alla godtagbara storlekar, upp till ungefär 30 st eller 2 kg per förpackning. Koden väljer sedan den med lägst effektivt pris per enhet för det antal som faktiskt köps, med mängdkampanj och max per hushåll inräknade. En "2 för"-kampanj räknas alltså bara när man köper två. Enheter per förpackning räknas som ordinarie pris delat med ordinarie jämförpris. Övriga rader behåller Claudes val. Bara förpackningar med samma jämförenhet jämförs. Raden märks "Storpack, lägst jämförpris" i rapporten.
- **`alltid_kop`**: basvaror som läggs i korgen varje vecka.
- **`sparrord_ingredienser`**: ord som bara jämförs mot ingredienslistan för valda produkter. Det fångar till exempel köttbullar med fläsk utan att stoppa köttbullar på bara nöt. Även `sparrord` jämförs mot ingredienserna. En vara som matchar byts mot nästa reserv. Fungerar inget alternativ märks raden "Köp manuellt". Kött, chark och färdigmat utan ingrediensuppgift märks "Kontrollera ingredienser". Ingredienslistor cachas per produkt i `data/ingredienser-cache.json` och hämtas på nytt efter 30 dagar.
- **`butiker.willys.i_butik`** (standard `true`): hämta även Willys kampanjer som bara gäller i butiken. Kampanjer som också finns i e-handeln räknas bara en gång.
- **`min_besparing_willys_i_butik_kr`** (standard 10, under `optimering`): minsta samlade besparing för att Willys butikskampanjer ska flaggas i rapporten.
- **`min_besparing_for_delning_kr`** (under `optimering`): minsta samlade besparing per ICA-butik för att flagga dess kampanjer. Under trösklarna flaggas inget, men varorna ligger alltid i korgen.
- **`uteslut_kategorier`** (under `optimering`): kampanjkategorier som inte är mat och inte skickas till menyplaneraren. Saknas nyckeln används en standardlista, och `[]` stänger av filtret.
- **`claude.model_meny`** och **`claude.model_produkter`**: modell per steg. Saknas de används `claude.model`.
- **`hushall.matlador`** (standard av), t.ex. `{dagar: [tisdag, torsdag], extra_portioner: 2}`: de dagarna lagas extra portioner till matlådor. I auto-läget räknar menyn och inköpslistan med dem. I valläget gäller det de valda rätter som hamnar på de dagarna: inköpslistan skalas upp, och receptet får en första rad om hur många portioner som ska lagas. Rapporten märker rätterna med "+2 matlådor".
- **`meny.lage`** (standard `auto`): `auto` gör en färdig meny varje vecka, `val` gör förslag som du väljer bland (se Valläget). **`meny.forslag`** (standard 10) anger antalet förslag.

## Betyg

Efter veckan kan du betygsätta rätterna:
```sh
.venv/bin/python -m veckohandla betyg                  # förra veckans rätter
.venv/bin/python -m veckohandla betyg --vecka 2026-v43
```
Svara `+` eller `−` och skriv en valfri kommentar. Enter hoppar över en rätt. Betygen sparas i `data/betyg.json` som rätt, vecka, betyg (+1/−1) och kommentar. Betygsätter du samma rätt samma vecka igen ersätts det gamla betyget. Både meny och förslag får de 15 senaste gillade rätterna ("gärna liknande") och alla ogillade ("undvik dem och liknande"). Har en rätt fått flera betyg gäller det senaste.

## Prishistorik

Varje veckas kampanjer sparas kompakt i `data/priser/<vecka>.json` med butik, produktkod (Willys), namn, kampanjpris per styck, ordinarie pris och jämförpris. ICA:s id byts varje vecka, så ICA-varor känns igen på butik, namn och varumärke. Nästa vecka jämförs kampanjpriset med medianen av ordinarie pris de senaste 8 veckorna:
- **bra pris**: minst 15 % under medianen.
- **vanligt pris**: inom 5 % av medianen, alltså ingen riktig rea.

Med färre än 3 veckors historik för en vara görs ingen markering. Viktvaror markeras inte, eftersom kampanjpris och ordinarie pris kan ha olika enhet. Planeraren ser markeringen i kampanjlistan. Rapporten visar den på korgraderna och butiksalternativen, tillsammans med en lista över veckans bra priser.

## Kostnad

Varje körning gör 2–3 Claude-anrop: meny (eller förslag), produktval och, i valläget, inköpslistan. Förbrukningen summeras per körning och per steg. Den skrivs i loggen, på en liten rad längst ner i rapporten och i `data/<vecka>-kostnad.json` med en post per körning.

- **Abonnemang (Pro/Max) via Claude Code:** inget extra att betala, anropen räknas mot abonnemangets kvot. `claude -p` anger ändå tokens och vad anropen hade kostat till listpris, och det är den kostnaden som visas.
- **API-nyckel:** alternativet till abonnemang. Lägg `ANTHROPIC_API_KEY` i `.env`, så används Anthropic API direkt och du betalar per token. API-svaret anger tokens men inget pris, så då visas bara tokens.

Meny och förslag kräver mest omdöme, medan produktval och inköpslista är mer mekaniska. Vill du sänka förbrukningen kan du sätta en billigare modell per steg:
```yaml
claude:
  model: claude-sonnet-5-5
  model_meny: claude-sonnet-5-5       # meny och förslag
  model_produkter: claude-haiku-5-5   # produktval och inköpslista (valläget)
```

## Hur det fungerar

| Del | Källa |
|---|---|
| Willys- och Hemköp-kampanjer | Axfoods öppna JSON-endpoints (samma på willys.se och hemkop.se) `/search/campaigns/online` (e-handel) och `/search/campaigns/offline` (bara i butik; produktkoden ligger i `potentialPromotions[0].mainProductCode`) |
| Willys-sök och tillgänglighet | En anonym session per körning där din butik (`butiker.willys.store_id`) väljs via `/axfood/rest/v2/store/activate`. `/search` ignorerar `storeId`-parametrar, så sortimentet styrs av butiken i sessionen. Varor som inte finns i butiken ger 404 på `/axfood/rest/p/<kod>`. Cookies hålls bara i minnet, och tillgängligheten cachas aldrig. |
| ICA-kampanjer | JSON inbäddad i butikens erbjudandesida på ica.se |
| Meny och produktval | Claude via `claude -p` (Pro/Max) eller Anthropic API (om `ANTHROPIC_API_KEY` finns) |
| Varukorg | Playwright med din inloggade profil per kedja (`browser-profiles/<kedja>`, lokal och aldrig incheckad) |

```
veckohandla/
  stores/axfood.py   Axfood-API:t: kampanjer, sök, butikssök, butiksval, produktdetaljer
  stores/willys.py   Willys (tunt lager ovanpå axfood.py)
  stores/hemkop.py   Hemköp (tunt lager ovanpå axfood.py)
  stores/ica.py      ICA-erbjudanden
  planner.py         Claude-anrop (meny + produktval) med strikta JSON-scheman
  pipeline.py        hela veckoflödet
  cart.py            fyller varukorgen hos Willys eller Hemköp
  ingredienser.py    ingredienskontroll mot spärrorden
  report.py          HTML-rapport och mejl
tests/               pytest med fixturer, utan nätverk
```

## Tester
```sh
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```
Testerna använder fixturer i `tests/fixtures/` och blockerar alla nätverksanrop.

## Begränsningar och ansvar

- **ICA:s e-handel stöds inte.** Den blockerar automatiserade webbläsare, och projektet försöker inte kringgå det. ICA-kampanjer används bara för jämförelse och blir en lista för butiksbesök.
- Projektet använder **inofficiella** endpoints som kan ändras utan förvarning. Använd det för eget bruk och med måttlig belastning.
- Priser för lösvikt är uppskattningar tills varan har vägts. Kampanjrabatter syns på korgens total.
- **Granska alltid korgen innan du beställer.** Projektet är inte knutet till Willys, Axfood eller ICA.

## Bidra

Bidrag är välkomna! Se [CONTRIBUTING.md](CONTRIBUTING.md). Idéer:
- Fler kedjor: Coop, Hemköp (Axfood, troligen samma API som Willys), Lidl.
- Bättre mängdberäkning mellan recept och förpackningar.
- Matpreferenser per veckodag och historik över vad familjen gillade.

## Licens

[MIT](LICENSE)
