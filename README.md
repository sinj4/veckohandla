# Veckohandla 🛒

Veckohandla är en bot som planerar veckans middagar utifrån butikernas veckokampanjer. Den fyller din varukorg på Willys och mejlar dig meny, recept och inköpslista.

*A bot that plans the week's dinners from Swedish grocery store deals (Willys, ICA), fills your Willys online cart and emails you the menu. Swedish-language project.*

## Vad den gör

Varje vecka:

1. **Skannar kampanjer** i Willys e-handel och valfria ICA-butiker (via ica.se/erbjudanden).
2. **Planerar middagar** med Claude utifrån kampanjerna och ditt hushåll: antal personer, barnens åldrar, önskemål och sådant som ska undvikas. Rätter från de senaste veckorna upprepas inte.
3. **Matchar varje ingrediens** mot Willys sortiment och väljer billigaste rimliga vara. Den tar hänsyn till "2 för"-kampanjer, "max 1 köp/hushåll" och lösvikt.
4. **Jämför med ICA-kampanjer.** Sparar ett ICA-besök tillräckligt blir de varorna en separat butikslista.
5. **Fyller Willys-varukorgen.** Boten lägger **aldrig** någon order, det gör du själv efter att ha granskat korgen.
6. **Skickar en rapport** med meny, recept, varukorg och prisuppgifter, via mejl och som HTML-fil.

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

### Schemaläggning (macOS)
```sh
./schema/installera.sh    # körs måndagar 06:30
```
På Linux fungerar en cron-rad som kör `.venv/bin/python -m veckohandla kor --fyll-varukorg` från projektkatalogen.

## Konfiguration

Allt ställs in i `config.yaml`, se de kommenterade exemplen i [`config.example.yaml`](config.example.yaml).

- **`undvik`**: hårda krav som skickas till Claude, till exempel "fläsk i alla former" eller "nötter".
- **`sparrord`**: ett skyddsnät i koden. Produkter vars namn innehåller något av orden tas bort innan Claude ser dem.
- **`skafferi`**: varor som alltid finns hemma och därför aldrig köps.
- **`alltid_kop`**: basvaror som läggs i korgen varje vecka.
- **`min_besparing_for_delning_kr`**: hur mycket ett extra ICA-besök minst måste spara.

## Hur det fungerar

| Del | Källa |
|---|---|
| Willys-kampanjer och sök | Willys öppna JSON-endpoints (`/search/campaigns/online`, `/search`) |
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
  report.py          HTML-rapport och mejl
```

## Begränsningar och ansvar

- **ICA:s e-handel stöds inte.** Den blockerar automatiserade webbläsare, och projektet försöker inte kringgå det. ICA-kampanjer används bara för jämförelse och blir en lista för butiksbesök.
- Projektet använder **inofficiella** endpoints som kan ändras utan förvarning. Använd det för eget bruk och med måttlig belastning.
- Priser för lösvikt är uppskattningar tills varan har vägts. Kampanjrabatter syns på korgens total.
- **Granska alltid korgen innan du beställer.** Projektet är inte knutet till Willys, Axfood eller ICA.

## Bidra

Bidrag är välkomna! Se [CONTRIBUTING.md](CONTRIBUTING.md). Idéer:
- Fler kedjor: Coop, Hemköp (Axfood, troligen samma API som Willys), Lidl.
- Bättre mängdberäkning mellan recept och förpackningar.
- Tester med inspelade API-svar.
- Matpreferenser per veckodag och historik över vad familjen gillade.

## Licens

[MIT](LICENSE)
