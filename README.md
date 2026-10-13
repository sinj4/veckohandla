# Veckohandla 🛒

Veckohandla är en bot som planerar veckans middagar utifrån butikernas veckokampanjer. Den fyller din varukorg på Willys och mejlar dig meny, recept och inköpslista.

*A bot that plans the week's dinners from Swedish grocery store deals (Willys, ICA), fills your Willys online cart and emails you the menu. Swedish-language project.*

## Vad den gör

Varje vecka:

1. **Skannar kampanjer** i Willys e-handel, Willys-butikens egna hyllkampanjer och valfria ICA-butiker (via ica.se/erbjudanden).
2. **Planerar middagar** med Claude utifrån kampanjerna och ditt hushåll: antal personer, barnens åldrar, önskemål och sådant som ska undvikas. Rätter från de senaste veckorna upprepas inte.
3. **Matchar varje ingrediens** mot sortimentet i *din* Willys-butik och väljer billigaste rimliga vara, plus upp till 3 reserver. Den tar hänsyn till "2 för"-kampanjer, "max 1 köp/hushåll" och lösvikt.
4. **Jämför med butikskampanjer.** Kampanjer som bara gäller i Willys-butiken hamnar på listan "Willys i butik", med kostnaden räknad ur kampanjen. Den listan köps när du hämtar ordern eller vid ett snabbt besök. Sparar ett ICA-besök tillräckligt blir de varorna en separat ICA-lista. Inget av detta läggs i e-handelskorgen.
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
.venv/bin/python -m veckohandla erbjudanden          # kontrollera att kampanjerna hämtas
.venv/bin/python -m veckohandla login                # logga in på Willys en gång
.venv/bin/python -m veckohandla kor --ingen-mejl     # testkörning, rapporten hamnar i data/
.venv/bin/python -m veckohandla fyll-varukorg        # lägg den granskade listan i Willys-korgen
```

Du kan också planera och fylla korgen i ett steg med `kor --fyll-varukorg`.

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

## Konfiguration

Allt ställs in i `config.yaml`, se de kommenterade exemplen i [`config.example.yaml`](config.example.yaml).

- **`undvik`**: hårda krav som skickas till Claude, till exempel "fläsk i alla former" eller "nötter".
- **`sparrord`**: ett skyddsnät i koden. Produkter vars namn innehåller något av orden tas bort innan Claude ser dem.
- **`skafferi`**: varor som alltid finns hemma och därför aldrig köps.
- **`alltid_kop`**: basvaror som läggs i korgen varje vecka.
- **`sparrord_ingredienser`**: ord som bara jämförs mot ingredienslistan för valda produkter. Det fångar till exempel köttbullar med fläsk utan att stoppa köttbullar på bara nöt. Även `sparrord` jämförs mot ingredienserna. En vara som matchar byts mot nästa reserv. Fungerar inget alternativ märks raden "Köp manuellt". Kött, chark och färdigmat utan ingrediensuppgift märks "Kontrollera ingredienser". Ingredienslistor cachas per produkt i `data/ingredienser-cache.json` och hämtas på nytt efter 30 dagar.
- **`butiker.willys.i_butik`** (standard `true`): hämta även Willys kampanjer som bara gäller i butiken. Kampanjer som också finns i e-handeln räknas bara en gång.
- **`butiker.willys.hamtar_i_butik`** (standard `false`): sätt till `true` om du hämtar e-handelsordern i butiken. Då kräver listan "Willys i butik" ingen besparingströskel.
- **`min_besparing_willys_i_butik_kr`** (standard 40, under `optimering`): minsta besparing för listan "Willys i butik" när du inte hämtar i butiken.
- **`min_besparing_for_delning_kr`**: hur mycket ett extra ICA-besök minst måste spara. Under gränsen köps allt som finns på Willys där.
- **`uteslut_kategorier`** (under `optimering`): kampanjkategorier som inte är mat och inte skickas till menyplaneraren. Saknas nyckeln används en standardlista, och `[]` stänger av filtret.
- **`claude.model_meny`** och **`claude.model_produkter`**: modell per steg. Saknas de används `claude.model`.

## Hur det fungerar

| Del | Källa |
|---|---|
| Willys-kampanjer | Willys öppna JSON-endpoints `/search/campaigns/online` (e-handel) och `/search/campaigns/offline` (bara i butik; produktkoden ligger i `potentialPromotions[0].mainProductCode`) |
| Willys-sök och tillgänglighet | En anonym session per körning där din butik (`butiker.willys.store_id`) väljs via `/axfood/rest/v2/store/activate`. `/search` ignorerar `storeId`-parametrar, så sortimentet styrs av butiken i sessionen. Varor som inte finns i butiken ger 404 på `/axfood/rest/p/<kod>`. Cookies hålls bara i minnet, och tillgängligheten cachas aldrig. |
| ICA-kampanjer | JSON inbäddad i butikens erbjudandesida på ica.se |
| Meny och produktval | Claude via `claude -p` (Pro/Max) eller Anthropic API (om `ANTHROPIC_API_KEY` finns) |
| Varukorg | Playwright med din inloggade Willys-profil (`browser-profiles/`, lokal och aldrig incheckad) |

```
veckohandla/
  stores/willys.py   kampanjer, sök, butikssök
  stores/ica.py      ICA-erbjudanden
  planner.py         Claude-anrop (meny + produktval) med strikta JSON-scheman
  pipeline.py        hela veckoflödet
  cart.py            fyller Willys-varukorgen
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
