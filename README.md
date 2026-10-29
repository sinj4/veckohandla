# Veckohandla 🛒

[![Tester](https://github.com/sinj4/veckohandla/actions/workflows/tester.yml/badge.svg)](https://github.com/sinj4/veckohandla/actions/workflows/tester.yml)

Veckohandla är en bot som planerar veckans middagar utifrån butikernas veckokampanjer. Den fyller din varukorg på Willys och mejlar dig meny, recept och inköpslista.

*A bot that plans the week's dinners from Swedish grocery store deals (Willys, ICA), fills your Willys online cart and emails you the menu. Swedish-language project.*

## Tekniska val

Boten körs obevakad varje måndag morgon och rör mitt riktiga Willys-konto. Därför är den byggd för att hellre stanna än göra fel.

- **Den lägger aldrig en order.** Den fyller bara korgen, och bara med det som fattas. Körs den två gånger blir resultatet detsamma.
- **Claudes svar valideras mot strikta scheman** (Pydantic) innan något används. Ett svar som inte följer schemat stoppar körningen.
- **Matkraven ligger i koden, inte bara i prompten.** Spärrorden filtrerar bort produkter innan Claude ser dem, och ingredienslistan kontrolleras igen efter valet. En AI-modell som missar något ska inte kunna lägga fläsk i korgen.
- **Exit-koder för schemaläggning.** Kod 3 betyder att veckans kampanjer inte är uppe än, så schemat kan försöka igen senare. Kod 4 betyder att mejlet inte kom fram. Andra fel skickar ett felmejl.
- **Ingen hemlighet i repot.** API-nyckel och SMTP-lösenord ligger i `.env`, och den inloggade webbläsarprofilen i `browser-profiles/`. Båda ignoreras av git.
- **163 tester som körs utan nätverk.** `conftest.py` blockerar alla socket-anrop, och Willys- och ICA-svar kommer från sparade fixturer. Testerna körs i GitHub Actions på Python 3.11 och 3.12.
- **Tillgänglighet cachas aldrig**, eftersom en vara som tagit slut i butiken måste upptäckas samma dag. Ingredienslistor cachas i 30 dagar, för de ändras sällan.

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
- Python 3.12 eller senare.
- Ett konto hos Willys eller Hemköp för korgen.
- Antingen [Claude Code](https://claude.com/claude-code) inloggat med ett Claude Pro- eller Max-abonnemang, eller en `ANTHROPIC_API_KEY`.

Välj en av tre vägar.

### 1. Snabbast: på din dator
```sh
git clone https://github.com/sinj4/veckohandla ~/veckohandla && cd ~/veckohandla
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
.venv/bin/python -m veckohandla init       # installationsguide: skriver config.yaml (och SMTP-lösenordet i .env)
.venv/bin/python -m veckohandla kontroll   # checklista: butik, kampanjer, Claude, mejl, inloggning
```
Guiden frågar efter ort och butik, hushåll, vad ni inte äter, läge och mejl. Gmail: skapa ett app-lösenord på https://myaccount.google.com/apppasswords. Enter väljer standardsvaret. Den avslutar med `kontroll`, erbjuder `login` och skriver ut nästa steg. `init --ingen-fraga` tar alla svar från flaggor; se `init --help`.

Sedan:
```sh
.venv/bin/python -m veckohandla kor --ingen-mejl     # testkörning, rapporten hamnar i data/
.venv/bin/python -m veckohandla fyll-varukorg        # lägg den granskade listan i korgen
```

### 2. I molnet varje vecka: mallen
[sinj4/veckohandla-mall](https://github.com/sinj4/veckohandla-mall) är ett färdigt repo för GitHub Actions. Klicka på **Use this template**, lägg in `config.yaml` och två secrets, så planeras veckan varje måndag och rapporten mejlas. Korgen fylls sedan på datorn med `fyll.sh`. Mallens README går igenom det steg för steg.

### 3. För utvecklare
```sh
git clone https://github.com/<du>/veckohandla && cd veckohandla
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m playwright install chromium

cp config.example.yaml config.yaml   # anpassa hushåll, önskemål och butiker
cp .env.example .env                 # valfritt: API-nyckel och SMTP-lösenord

.venv/bin/python -m veckohandla hitta-willys <ort>   # hitta store_id för din Willys
.venv/bin/python -m veckohandla hitta-hemkop <ort>   # … eller för ditt Hemköp
.venv/bin/python -m veckohandla erbjudanden          # kontrollera att kampanjerna hämtas
.venv/bin/python -m veckohandla login                # logga in en gång hos kedjan i butiker.e_handel
.venv/bin/python -m veckohandla kor --ingen-mejl     # testkörning, rapporten hamnar i data/
.venv/bin/python -m veckohandla fyll-varukorg        # lägg den granskade listan i korgen
.venv/bin/python -m pytest                           # testerna, utan nätverk
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

### Välja och sätta betyg från mobilen
Mallen [sinj4/veckohandla-mall](https://github.com/sinj4/veckohandla-mall) har en mobilsida i katalogen `mobil/`. Det är en Cloudflare Worker där du väljer rätter, sätter betyg och ser körningarnas status. Sidan startar workflowen med inputs. Betygen sparas med `python -m veckohandla betyg --fran-text '{"vecka": "2026-v43", "betyg": [{"ratt": "Tacos", "betyg": 1, "kommentar": "god"}]}'`, och allt kontrolleras mot veckans plan innan något sparas.

Finns miljövariablerna **`MOBIL_ADRESS`** (sidans adress) och **`LANKNYCKEL`** (samma nyckel som sidan använder) får mejlen knapparna **Välj rätter** och **Sätt betyg**. Länkarna är signerade för en vecka: de innehåller `v=<vecka>&t=<HMAC>`, men aldrig själva nyckeln. Rapporterna som sparas i `data/` får inga sådana länkar.

### Fyll korgen på mobilen
Veckans rapport har knappen **📱 Fyll korgen på mobilen**. Den öppnar www.willys.se (eller www.hemkop.se) med veckans korg i adressen: `#veckohandla=…` innehåller bara produktkoder, antal och reserver. Ett bokmärke eller en iPhone-genväg läser sedan adressen och fyller korgen i mobilens webbläsare, där du redan är inloggad. Det lägger bara till det som fattas och prövar reserver när butiken nekar en vara, precis som `fyll-varukorg`. Det lägger aldrig någon order och tar aldrig bort något. Efteråt visas en ruta med vad som lades till, och länken rensas ur adressen.

**Bokmärke i Safari på iPhone**
1. Öppna valfri sida och tryck på dela-knappen → **Lägg till bokmärke**. Döp bokmärket till `Veckohandla` och spara.
2. Öppna **Bokmärken** → **Redigera** → **Veckohandla**. Ersätt adressen med hela texten i rutan *Bokmärkets adress* nedan och tryck **Klar**.
3. Använd det så här: tryck på **Fyll korgen på mobilen** i rapporten och logga in om det behövs. Tryck sedan i adressfältet, skriv `Veckohandla` och välj bokmärket.

**Bokmärke i Chrome på Android**
1. Lägg till ett bokmärke (⋮ → ☆) och redigera det: namn `Veckohandla`, adress = texten i *Bokmärkets adress* nedan.
2. Använd det så här: öppna **Fyll korgen på mobilen** från rapporten och logga in om det behövs. Skriv sedan `Veckohandla` i adressfältet och välj bokmärket i förslagen. Chrome kör `javascript:`-bokmärken bara på det sättet.

**iPhone-genväg (i stället för bokmärket)**
1. Öppna **Genvägar** → **+** → **Lägg till åtgärd** → **Kör JavaScript på webbsida**.
2. Ersätt exempelkoden med texten i *Kod för genvägen* nedan.
3. Öppna genvägens inställningar (ⓘ), slå på **Visa i delningsmenyn** och välj *Safari-webbsidor* som indata. Döp genvägen till `Veckohandla`.
4. Använd den så här: öppna **Fyll korgen på mobilen** från rapporten och logga in om det behövs. Tryck sedan på dela-knappen → **Veckohandla**. Första gången frågar iOS om genvägen får köras på sidan.

<details><summary>Bokmärkets adress (kopiera allt)</summary>

```text
javascript:(function%20()%20{%20'use%20strict';%20var%20KEDJOR%20=%20{'www.willys.se':%20'willys',%20'www.hemkop.se':%20'hemkop'};%20var%20NAMN%20=%20{willys:%20'Willys',%20hemkop:%20'Hemk%C3%B6p'};%20var%20ENHET%20=%20{p:%20'pieces',%20k:%20'kilogram'};%20function%20rad(r)%20{%20return%20{%20kod:%20r.kod%20||%20r.k,%20antal:%20Number(r.antal%20!=%20null%20?%20r.antal%20:%20r.a),%20enhet:%20ENHET[r.enhet%20||%20r.e]%20||%20r.enhet%20||%20r.e%20||%20'pieces',%20reserver:%20(r.reserver%20||%20r.r%20||%20[]).map(rad)%20};%20}%20function%20avkoda(hash)%20{%20var%20m%20=%20/[#&]veckohandla=([A-Za-z0-9_-]+)/.exec(hash%20||%20'');%20if%20(!m)%20{%20return%20null;%20}%20var%20b64%20=%20m[1].replace(/-/g,%20'+').replace(/_/g,%20'/');%20while%20(b64.length%20%25%204)%20{%20b64%20+=%20'=';%20}%20var%20bin%20=%20atob(b64);%20var%20bytes%20=%20new%20Uint8Array(bin.length);%20for%20(var%20i%20=%200;%20i%20<%20bin.length;%20i++)%20{%20bytes[i]%20=%20bin.charCodeAt(i);%20}%20var%20d%20=%20JSON.parse(new%20TextDecoder().decode(bytes));%20return%20{kedja:%20d.kedja%20||%20d.s,%20rader:%20(d.rader%20||%20d.r%20||%20[]).map(rad)};%20}%20function%20summera(rader)%20{%20var%20ut%20=%20[];%20var%20index%20=%20{};%20rader.forEach(function%20(r)%20{%20var%20nyckel%20=%20r.kod%20+%20'|'%20+%20r.enhet;%20if%20(nyckel%20in%20index)%20{%20ut[index[nyckel]].antal%20+=%20r.antal;%20return;%20}%20index[nyckel]%20=%20ut.length;%20ut.push({kod:%20r.kod,%20antal:%20r.antal,%20enhet:%20r.enhet,%20reserver:%20r.reserver.slice()});%20});%20return%20ut;%20}%20function%20iKorgen(korg)%20{%20var%20ut%20=%20{};%20(korg.products%20||%20[]).forEach(function%20(p)%20{%20ut[p.code]%20=%20{antal:%20Number(p.pickQuantity%20||%200),%20enhet:%20(p.pickUnit%20&&%20p.pickUnit.code)%20||%20'pieces',%20namn:%20p.name%20||%20''};%20});%20return%20ut;%20}%20function%20diff(onskat,%20korg)%20{%20var%20finns%20=%20iKorgen(korg);%20var%20d%20=%20{att:%20[],%20redan:%20[],%20annan:%20[]};%20summera(onskat).forEach(function%20(r)%20{%20var%20f%20=%20finns[r.kod];%20if%20(f%20&&%20f.enhet%20!==%20r.enhet)%20{%20d.annan.push(r);%20}%20else%20if%20(f%20&&%20f.antal%20>=%20r.antal)%20{%20d.redan.push(r);%20}%20else%20{%20d.att.push({kod:%20r.kod,%20antal:%20Math.ceil(r.antal%20-%20(f%20?%20f.antal%20:%200)),%20enhet:%20r.enhet,%20reserver:%20r.reserver});%20}%20});%20return%20d;%20}%20async%20function%20fyll(rader,%20api)%20{%20rader%20=%20summera(rader);%20var%20korg%20=%20await%20api.hamtaKorg();%20var%20d%20=%20diff(rader,%20korg);%20var%20nekade%20=%20[];%20for%20(var%20i%20=%200;%20i%20<%20d.att.length;%20i++)%20{%20if%20(!(await%20api.laggTill(d.att[i])))%20{%20nekade.push(d.att[i].kod);%20}%20}%20korg%20=%20await%20api.hamtaKorg();%20var%20perKod%20=%20{};%20rader.forEach(function%20(r)%20{%20perKod[r.kod]%20=%20r;%20});%20var%20byten%20=%20[];%20var%20misslyckade%20=%20[];%20for%20(var%20j%20=%200;%20j%20<%20nekade.length;%20j++)%20{%20var%20r%20=%20perKod[nekade[j]];%20var%20ok%20=%20false;%20for%20(var%20k%20=%200;%20k%20<%20r.reserver.length%20&&%20!ok;%20k++)%20{%20var%20behov%20=%20diff([r.reserver[k]],%20korg);%20if%20(!behov.att.length)%20{%20ok%20=%20!behov.annan.length;%20}%20else%20{%20ok%20=%20await%20api.laggTill(behov.att[0]);%20korg%20=%20await%20api.hamtaKorg();%20}%20if%20(ok)%20{%20byten.push({fran:%20r,%20till:%20r.reserver[k]});%20}%20}%20if%20(!ok)%20{%20misslyckade.push(r);%20}%20}%20return%20{%20tillagda:%20d.att.filter(function%20(r)%20{%20return%20nekade.indexOf(r.kod)%20<%200;%20}),%20redan:%20d.redan,%20annan:%20d.annan,%20byten:%20byten,%20misslyckade:%20misslyckade,%20namn:%20iKorgen(korg)%20};%20}%20function%20text(res,%20kedja)%20{%20function%20n(r)%20{%20return%20(res.namn[r.kod]%20&&%20res.namn[r.kod].namn)%20||%20r.kod;%20}%20var%20rader%20=%20[NAMN[kedja]%20+%20'-korgen%20%C3%A4r%20uppdaterad.',%20'Lade%20till%20'%20+%20res.tillagda.length%20+%20'%20varor,%20'%20+%20res.redan.length%20+%20'%20fanns%20redan.'];%20res.byten.forEach(function%20(b)%20{%20rader.push('Bytt%20till%20reserv:%20'%20+%20n(b.fran)%20+%20'%20%E2%86%92%20'%20+%20n(b.till));%20});%20if%20(res.annan.length)%20{%20rader.push('Finns%20redan%20i%20annan%20enhet%20(r%C3%B6rdes%20inte):%20'%20+%20res.annan.map(n).join(',%20'));%20}%20if%20(res.misslyckade.length)%20{%20rader.push('Gick%20inte%20att%20l%C3%A4gga%20till:%20'%20+%20res.misslyckade.map(n).join(',%20'));%20}%20rader.push('Ingen%20order%20%C3%A4r%20lagd.%20Granska%20korgen%20och%20best%C3%A4ll%20sj%C3%A4lv.');%20return%20rader.join('\n');%20}%20function%20visa(doc,%20meddelande)%20{%20var%20gammal%20=%20doc.getElementById('veckohandla-ruta');%20if%20(gammal)%20{%20gammal.remove();%20}%20var%20ruta%20=%20doc.createElement('div');%20ruta.id%20=%20'veckohandla-ruta';%20ruta.setAttribute('style',%20'position:fixed;z-index:2147483647;left:12px;right:12px;top:12px;max-height:80vh;overflow:auto;background:#fff;color:#222;border:2px%20solid%20#2a7a2a;border-radius:12px;padding:16px;font:16px/1.4%20-apple-system,Helvetica,Arial,sans-serif;white-space:pre-wrap;box-shadow:0%204px%2024px%20rgba(0,0,0,.3)');%20ruta.textContent%20=%20'%F0%9F%9B%92%20Veckohandla\n\n'%20+%20meddelande;%20var%20knapp%20=%20doc.createElement('button');%20knapp.textContent%20=%20'St%C3%A4ng';%20knapp.setAttribute('style',%20'display:block;margin-top:12px;padding:8px%2016px;font-size:16px');%20knapp.onclick%20=%20function%20()%20{%20ruta.remove();%20};%20ruta.appendChild(knapp);%20doc.body.appendChild(ruta);%20return%20meddelande;%20}%20async%20function%20kor(w)%20{%20var%20kedja%20=%20KEDJOR[w.location.hostname];%20if%20(!kedja)%20{%20return%20visa(w.document,%20'%C3%96ppna%20l%C3%A4nken%20fr%C3%A5n%20veckans%20rapport,%20s%C3%A5%20att%20sidan%20%C3%A4r%20www.willys.se%20eller%20www.hemkop.se,%20och%20k%C3%B6r%20sedan%20bokm%C3%A4rket%20igen.');%20}%20var%20data%20=%20avkoda(w.location.hash);%20if%20(!data)%20{%20return%20visa(w.document,%20'Ingen%20veckohandla-l%C3%A4nk%20i%20adressen.%20%C3%96ppna%20"Fyll%20korgen%20p%C3%A5%20mobilen"%20i%20veckans%20rapport%20och%20k%C3%B6r%20sedan%20bokm%C3%A4rket%20igen.');%20}%20if%20(data.kedja%20&&%20data.kedja%20!==%20kedja)%20{%20return%20visa(w.document,%20'L%C3%A4nken%20g%C3%A4ller%20'%20+%20NAMN[data.kedja]%20+%20',%20men%20sidan%20%C3%A4r%20'%20+%20NAMN[kedja]%20+%20'.');%20}%20var%20hamta%20=%20function%20(sokvag)%20{%20return%20w.fetch(sokvag,%20{credentials:%20'same-origin'}).then(function%20(r)%20{%20return%20r.json();%20});%20};%20var%20kund%20=%20await%20hamta('/axfood/rest/customer');%20if%20(!kund%20||%20!kund.uid%20||%20kund.uid%20===%20'anonymous')%20{%20return%20visa(w.document,%20'Logga%20in%20p%C3%A5%20'%20+%20NAMN[kedja]%20+%20'%20f%C3%B6rst%20och%20k%C3%B6r%20sedan%20bokm%C3%A4rket%20igen.%20L%C3%A4nken%20finns%20kvar%20i%20adressen.');%20}%20var%20tok%20=%20JSON.parse(await%20(await%20w.fetch('/axfood/rest/csrf-token',%20{credentials:%20'same-origin'})).text());%20var%20api%20=%20{%20hamtaKorg:%20function%20()%20{%20return%20hamta('/axfood/rest/cart');%20},%20laggTill:%20async%20function%20(r)%20{%20var%20svar%20=%20await%20w.fetch('/axfood/rest/cart/addProducts',%20{%20method:%20'POST',%20credentials:%20'same-origin',%20headers:%20{'Content-Type':%20'application/json',%20'X-CSRF-Token':%20tok},%20body:%20JSON.stringify({products:%20[{productCodePost:%20r.kod,%20qty:%20r.antal,%20pickUnit:%20r.enhet,%20hideDiscountToolTip:%20false,%20noReplacementFlag:%20false}]})%20});%20return%20svar.ok;%20}%20};%20var%20res%20=%20await%20fyll(data.rader,%20api);%20w.history.replaceState(null,%20'',%20w.location.pathname%20+%20w.location.search);%20return%20visa(w.document,%20text(res,%20kedja));%20}%20var%20exporter%20=%20{avkoda:%20avkoda,%20summera:%20summera,%20iKorgen:%20iKorgen,%20diff:%20diff,%20fyll:%20fyll,%20text:%20text,%20kor:%20kor};%20if%20(typeof%20window%20===%20'undefined')%20{%20module.exports%20=%20exporter;%20return;%20}%20var%20klar%20=%20kor(window).catch(function%20(e)%20{%20return%20visa(document,%20'N%C3%A5got%20gick%20fel:%20'%20+%20e.message);%20});%20if%20(typeof%20completion%20===%20'function')%20{%20klar.then(function%20(t)%20{%20completion(t);%20});%20}%20})();
```
</details>

<details><summary>Kod för genvägen (kopiera allt)</summary>

```js
(function () { 'use strict'; var KEDJOR = {'www.willys.se': 'willys', 'www.hemkop.se': 'hemkop'}; var NAMN = {willys: 'Willys', hemkop: 'Hemköp'}; var ENHET = {p: 'pieces', k: 'kilogram'}; function rad(r) { return { kod: r.kod || r.k, antal: Number(r.antal != null ? r.antal : r.a), enhet: ENHET[r.enhet || r.e] || r.enhet || r.e || 'pieces', reserver: (r.reserver || r.r || []).map(rad) }; } function avkoda(hash) { var m = /[#&]veckohandla=([A-Za-z0-9_-]+)/.exec(hash || ''); if (!m) { return null; } var b64 = m[1].replace(/-/g, '+').replace(/_/g, '/'); while (b64.length % 4) { b64 += '='; } var bin = atob(b64); var bytes = new Uint8Array(bin.length); for (var i = 0; i < bin.length; i++) { bytes[i] = bin.charCodeAt(i); } var d = JSON.parse(new TextDecoder().decode(bytes)); return {kedja: d.kedja || d.s, rader: (d.rader || d.r || []).map(rad)}; } function summera(rader) { var ut = []; var index = {}; rader.forEach(function (r) { var nyckel = r.kod + '|' + r.enhet; if (nyckel in index) { ut[index[nyckel]].antal += r.antal; return; } index[nyckel] = ut.length; ut.push({kod: r.kod, antal: r.antal, enhet: r.enhet, reserver: r.reserver.slice()}); }); return ut; } function iKorgen(korg) { var ut = {}; (korg.products || []).forEach(function (p) { ut[p.code] = {antal: Number(p.pickQuantity || 0), enhet: (p.pickUnit && p.pickUnit.code) || 'pieces', namn: p.name || ''}; }); return ut; } function diff(onskat, korg) { var finns = iKorgen(korg); var d = {att: [], redan: [], annan: []}; summera(onskat).forEach(function (r) { var f = finns[r.kod]; if (f && f.enhet !== r.enhet) { d.annan.push(r); } else if (f && f.antal >= r.antal) { d.redan.push(r); } else { d.att.push({kod: r.kod, antal: Math.ceil(r.antal - (f ? f.antal : 0)), enhet: r.enhet, reserver: r.reserver}); } }); return d; } async function fyll(rader, api) { rader = summera(rader); var korg = await api.hamtaKorg(); var d = diff(rader, korg); var nekade = []; for (var i = 0; i < d.att.length; i++) { if (!(await api.laggTill(d.att[i]))) { nekade.push(d.att[i].kod); } } korg = await api.hamtaKorg(); var perKod = {}; rader.forEach(function (r) { perKod[r.kod] = r; }); var byten = []; var misslyckade = []; for (var j = 0; j < nekade.length; j++) { var r = perKod[nekade[j]]; var ok = false; for (var k = 0; k < r.reserver.length && !ok; k++) { var behov = diff([r.reserver[k]], korg); if (!behov.att.length) { ok = !behov.annan.length; } else { ok = await api.laggTill(behov.att[0]); korg = await api.hamtaKorg(); } if (ok) { byten.push({fran: r, till: r.reserver[k]}); } } if (!ok) { misslyckade.push(r); } } return { tillagda: d.att.filter(function (r) { return nekade.indexOf(r.kod) < 0; }), redan: d.redan, annan: d.annan, byten: byten, misslyckade: misslyckade, namn: iKorgen(korg) }; } function text(res, kedja) { function n(r) { return (res.namn[r.kod] && res.namn[r.kod].namn) || r.kod; } var rader = [NAMN[kedja] + '-korgen är uppdaterad.', 'Lade till ' + res.tillagda.length + ' varor, ' + res.redan.length + ' fanns redan.']; res.byten.forEach(function (b) { rader.push('Bytt till reserv: ' + n(b.fran) + ' → ' + n(b.till)); }); if (res.annan.length) { rader.push('Finns redan i annan enhet (rördes inte): ' + res.annan.map(n).join(', ')); } if (res.misslyckade.length) { rader.push('Gick inte att lägga till: ' + res.misslyckade.map(n).join(', ')); } rader.push('Ingen order är lagd. Granska korgen och beställ själv.'); return rader.join('\n'); } function visa(doc, meddelande) { var gammal = doc.getElementById('veckohandla-ruta'); if (gammal) { gammal.remove(); } var ruta = doc.createElement('div'); ruta.id = 'veckohandla-ruta'; ruta.setAttribute('style', 'position:fixed;z-index:2147483647;left:12px;right:12px;top:12px;max-height:80vh;overflow:auto;background:#fff;color:#222;border:2px solid #2a7a2a;border-radius:12px;padding:16px;font:16px/1.4 -apple-system,Helvetica,Arial,sans-serif;white-space:pre-wrap;box-shadow:0 4px 24px rgba(0,0,0,.3)'); ruta.textContent = '🛒 Veckohandla\n\n' + meddelande; var knapp = doc.createElement('button'); knapp.textContent = 'Stäng'; knapp.setAttribute('style', 'display:block;margin-top:12px;padding:8px 16px;font-size:16px'); knapp.onclick = function () { ruta.remove(); }; ruta.appendChild(knapp); doc.body.appendChild(ruta); return meddelande; } async function kor(w) { var kedja = KEDJOR[w.location.hostname]; if (!kedja) { return visa(w.document, 'Öppna länken från veckans rapport, så att sidan är www.willys.se eller www.hemkop.se, och kör sedan bokmärket igen.'); } var data = avkoda(w.location.hash); if (!data) { return visa(w.document, 'Ingen veckohandla-länk i adressen. Öppna "Fyll korgen på mobilen" i veckans rapport och kör sedan bokmärket igen.'); } if (data.kedja && data.kedja !== kedja) { return visa(w.document, 'Länken gäller ' + NAMN[data.kedja] + ', men sidan är ' + NAMN[kedja] + '.'); } var hamta = function (sokvag) { return w.fetch(sokvag, {credentials: 'same-origin'}).then(function (r) { return r.json(); }); }; var kund = await hamta('/axfood/rest/customer'); if (!kund || !kund.uid || kund.uid === 'anonymous') { return visa(w.document, 'Logga in på ' + NAMN[kedja] + ' först och kör sedan bokmärket igen. Länken finns kvar i adressen.'); } var tok = JSON.parse(await (await w.fetch('/axfood/rest/csrf-token', {credentials: 'same-origin'})).text()); var api = { hamtaKorg: function () { return hamta('/axfood/rest/cart'); }, laggTill: async function (r) { var svar = await w.fetch('/axfood/rest/cart/addProducts', { method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': tok}, body: JSON.stringify({products: [{productCodePost: r.kod, qty: r.antal, pickUnit: r.enhet, hideDiscountToolTip: false, noReplacementFlag: false}]}) }); return svar.ok; } }; var res = await fyll(data.rader, api); w.history.replaceState(null, '', w.location.pathname + w.location.search); return visa(w.document, text(res, kedja)); } var exporter = {avkoda: avkoda, summera: summera, iKorgen: iKorgen, diff: diff, fyll: fyll, text: text, kor: kor}; if (typeof window === 'undefined') { module.exports = exporter; return; } var klar = kor(window).catch(function (e) { return visa(document, 'Något gick fel: ' + e.message); }); if (typeof completion === 'function') { klar.then(function (t) { completion(t); }); } })();
```
</details>

Källkoden finns i [`bokmarke/bokmarke.js`](bokmarke/bokmarke.js). Bokmärkets adress och genvägskoden byggs från den med `python verktyg/bokmarke_url.py` (`--kod` för genvägen).

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
- **`bara_lokalt: true`** (per ICA-butik under `butiker.ica`): butiken hämtas inte när miljövariabeln `GITHUB_ACTIONS` är satt, så inga anrop görs mot ica.se från molnet. ICA-jämförelsen kan vara blockerad: ica.se svarar just nu 403 på automatiska anrop, både från GitHub Actions och från en vanlig dator. Rapporten visar då en neutral rad i stället för en varning: "ICA blockerar automatiska anrop just nu (403). Rätterna och korgen påverkas inte, men ICA-priser jämförs inte." Andra fel ger fortfarande en varning. Vi försöker inte ta oss runt blockeringen.
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
  installera.py      installationsguiden (init)
  yamltext.py        ändrar config-text och behåller kommentarerna
  kontroll.py        checklistan (kontroll)
tests/               pytest med fixturer, utan nätverk
```

## Tester
```sh
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```
Testerna använder fixturer i `tests/fixtures/` och blockerar alla nätverksanrop.
Bokmärkets logik testas med Nodes inbyggda testlöpare (`node --test tests/js/*.test.mjs`). pytest kör de testerna mot både källan och den minifierade versionen, om `node` finns.

## Felsökning

Kör först `python -m veckohandla kontroll`. Den visar vad som saknas och vad du ska göra.

| Det här syns | Orsak | Gör så här |
|---|---|---|
| `API Error: 400 … does not support this model; version … or newer is required`, eller "Claude Code är för gammal för modellen" | Claude Code är äldre än modellen kräver | `npm install -g @anthropic-ai/claude-code@latest`. Loggen visar vilken binär som används. Välj en annan med `CLAUDE_BIN`. Mallens workflow installerar alltid senaste versionen. |
| "MEJLET SKICKADES INTE: SMTP_PASSWORD saknas" (exit-kod 4) | App-lösenordet för mejlet saknas | Lägg `SMTP_PASSWORD=…` i `.env` (eller kör `init` igen). Gmail: skapa ett app-lösenord på https://myaccount.google.com/apppasswords. I molnet: secret `SMTP_PASSWORD`. Rapporten är ändå sparad i `data/`. |
| "Inte inloggad på Willys – kör: python -m veckohandla login", eller "Willys-inloggningen har gått ut" i rapporten | Inloggningen i webbläsarprofilen har gått ut | `python -m veckohandla login` och sedan `fyll-varukorg <vecka>`. |
| "Veckans kampanjer är inte uppe än" (exit-kod 3) | Måndag morgon innan butikerna har publicerat veckans kampanjer | Inget fel. Schemat försöker igen senare på morgonen. Först i sista schemalagda körningen, eller i en manuell körning, blir det ett fel. Kör då lite senare. |
| "ICA blockerar automatiska anrop just nu (403). Rätterna och korgen påverkas inte, men ICA-priser jämförs inte." | ica.se blockerar automatiska anrop, både från molnet och från datorn | Inget att göra: rätterna och korgen påverkas inte. Vi försöker inte ta oss runt blockeringen. Med `bara_lokalt: true` görs inga anrop mot ica.se från molnet. |

## Begränsningar och ansvar

- **ICA:s e-handel stöds inte.** Den blockerar automatiserade webbläsare, och projektet försöker inte kringgå det. ICA-kampanjer används bara för jämförelse och blir en lista för butiksbesök.
- **ICA-jämförelsen kan vara blockerad.** ica.se svarar just nu 403 på automatiska anrop, både från GitHub Actions och från en vanlig dator. Rätterna och korgen påverkas inte, men ICA-priser jämförs inte. Vi försöker inte ta oss runt det.
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
