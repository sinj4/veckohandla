# Bidra till Veckohandla

Kul att du vill hjälpa till! Issues och pull requests får skrivas på svenska eller engelska.

## Utvecklingsmiljö
```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
cp config.example.yaml config.yaml
.venv/bin/python -m veckohandla erbjudanden    # snabbt test, kräver varken Claude eller inloggning
```

## Riktlinjer
- **Ingen kringgång av skydd.** Om en butik blockerar automatisering (bot-spärrar, CAPTCHA, WAF) respekterar vi det. PR:er som försöker ta sig förbi sådana spärrar tas inte emot.
- **Lägg aldrig order automatiskt.** Boten fyller varukorgen, men människan beställer.
- **Var snäll mot butikernas servrar.** Gör få anrop, lägg in pauser och undvik parallell skrapning.
- **Checka aldrig in personliga data**: `config.yaml`, `.env`, `browser-profiles/` och `data/` är undantagna i `.gitignore`.
- Matcha stilen i befintlig kod: små moduler och svenska namn och kommentarer där det redan används.

## Lägga till en ny butikskedja
1. Skapa `veckohandla/stores/<kedja>.py` med `fetch_offers(...) -> list[Offer]` och, om kedjan har e-handel, `search(...) -> list[Product]`.
2. Koppla in den i `pipeline.fetch_all_offers` och i `config.example.yaml`.
3. Beskriv i PR:en vilka endpoints som används och hur du har testat.
