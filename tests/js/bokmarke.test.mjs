// Tester för bokmärket med Nodes inbyggda testlöpare och fejkade svar från cart-API:t.
// BOKMARKE_FIL väljer fil (standard: källan); pytest kör även den minifierade versionen.
// BOKMARKE_LANKAR pekar på länkar som Python-koden har kodat (veckohandla/mobil.py).
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const fil = process.env.BOKMARKE_FIL || new URL('../../bokmarke/bokmarke.js', import.meta.url);
const kod = readFileSync(fil, 'utf8');

function ladda() {
  // Samma realm som testerna (vm-kontexter har egna Array-prototyper); window saknas -> skriptet exporterar
  const module = {exports: {}};
  new Function('module', kod)(module);
  return module.exports;
}

const B = ladda();
const b64 = (obj) => Buffer.from(JSON.stringify(obj)).toString('base64url');
const rad = (kod, antal, enhet = 'pieces', reserver = []) => ({kod, antal, enhet, reserver});
const korg = (...p) => ({products: p.map(([code, n, unit = 'pieces', name = '']) => ({code, pickQuantity: n, pickUnit: {code: unit}, name}))});

// ---------- avkodning ----------

test('avkodar både långa och korta fältnamn', () => {
  const lang = B.avkoda('#veckohandla=' + b64({version: 1, kedja: 'willys', rader: [
    {kod: '1_ST', antal: 2, enhet: 'pieces', reserver: [{kod: '2_ST', antal: 4, enhet: 'pieces'}]}]}));
  const kort = B.avkoda('#veckohandla=' + b64({v: 1, s: 'hemkop', r: [{k: '1_KG', a: 1, e: 'k', r: [{k: '2_ST', a: 3, e: 'p'}]}]}));
  assert.equal(lang.kedja, 'willys');
  assert.deepEqual(lang.rader, [rad('1_ST', 2, 'pieces', [rad('2_ST', 4)])]);
  assert.equal(kort.kedja, 'hemkop');
  assert.deepEqual(kort.rader, [rad('1_KG', 1, 'kilogram', [rad('2_ST', 3)])]);
  assert.equal(B.avkoda('#annat=1'), null);
  assert.equal(B.avkoda(''), null);
});

test('avkodar länkar som Python har gjort', {skip: !process.env.BOKMARKE_LANKAR}, () => {
  const fall = JSON.parse(readFileSync(process.env.BOKMARKE_LANKAR, 'utf8'));
  for (const {lank, kedja, rader} of fall) {
    const d = B.avkoda(new URL(lank).hash);
    assert.equal(d.kedja, kedja);
    assert.deepEqual(d.rader, rader);
  }
});

// ---------- korg_diff ----------

test('diff som korg_diff: summerar, räknar det som fattas och hoppar över annan enhet', () => {
  const d = B.diff([rad('BANAN', 3), rad('BANAN', 5), rad('MJOLK', 2), rad('OST', 1), rad('POTATIS', 1.2, 'kilogram')],
    korg(['BANAN', 3], ['MJOLK', 2], ['POTATIS', 1, 'pieces']));
  assert.deepEqual(d.att.map((r) => [r.kod, r.antal]), [['BANAN', 5], ['OST', 1]]);
  assert.deepEqual(d.redan.map((r) => r.kod), ['MJOLK']);
  assert.deepEqual(d.annan.map((r) => r.kod), ['POTATIS']);
});

// ---------- fyll ----------

function fejkApi(startkorg, nekas = []) {
  const innehall = new Map(startkorg.products.map((p) => [p.code, {...p}]));
  const anrop = [];
  return {
    anrop,
    hamtaKorg: async () => ({products: [...innehall.values()].map((p) => ({...p}))}),
    laggTill: async (r) => {
      anrop.push(['laggTill', r.kod, r.antal, r.enhet]);
      if (nekas.includes(r.kod)) return false;
      const p = innehall.get(r.kod) || {code: r.kod, pickQuantity: 0, pickUnit: {code: r.enhet}, name: 'Namn ' + r.kod};
      p.pickQuantity += r.antal;
      innehall.set(r.kod, p);
      return true;
    },
  };
}

test('lägger bara till det som fattas och prövar reserver i ordning', async () => {
  const api = fejkApi(korg(['MJOLK', 2, 'pieces', 'Mjölk']), ['LAX', 'LAX2']);
  const res = await B.fyll([rad('MJOLK', 2), rad('AGG', 12), rad('LAX', 1, 'pieces', [rad('LAX2', 1), rad('LAX3', 2)])], api);
  assert.deepEqual(api.anrop, [['laggTill', 'AGG', 12, 'pieces'], ['laggTill', 'LAX', 1, 'pieces'],
    ['laggTill', 'LAX2', 1, 'pieces'], ['laggTill', 'LAX3', 2, 'pieces']]);
  assert.deepEqual(res.tillagda.map((r) => r.kod), ['AGG']);
  assert.deepEqual(res.redan.map((r) => r.kod), ['MJOLK']);
  assert.deepEqual(res.byten.map((b) => [b.fran.kod, b.till.kod]), [['LAX', 'LAX3']]);
  assert.deepEqual(res.misslyckade, []);
  assert.match(B.text(res, 'willys'), /Lade till 1 varor, 1 fanns redan\.\nBytt till reserv: LAX → Namn LAX3/);
});

test('reserv som redan ligger i korgen räknas utan nytt anrop; utan fungerande reserv blir raden misslyckad', async () => {
  const api = fejkApi(korg(['RES', 3]), ['A', 'B', 'B2']);
  const res = await B.fyll([rad('A', 1, 'pieces', [rad('RES', 2)]), rad('B', 1, 'pieces', [rad('B2', 1)])], api);
  assert.deepEqual(api.anrop.map((a) => a[1]), ['A', 'B', 'B2']);
  assert.deepEqual(res.byten.map((b) => b.till.kod), ['RES']);
  assert.deepEqual(res.misslyckade.map((r) => r.kod), ['B']);
  assert.match(B.text(res, 'hemkop'), /^Hemköp-korgen är uppdaterad\.[\s\S]*Gick inte att lägga till: B\nIngen order är lagd/);
});

test('tom diff ger inga anrop', async () => {
  const api = fejkApi(korg(['A', 5]));
  const res = await B.fyll([rad('A', 2), rad('A', 3)], api);
  assert.deepEqual(api.anrop, []);
  assert.equal(res.redan.length, 1);
});

// ---------- kor() på en fejkad sida ----------

function fejkSida({host = 'www.willys.se', hash = '', inloggad = true, nekas = [], startkorg = korg()} = {}) {
  const api = fejkApi(startkorg, nekas);
  const anrop = [];
  const element = () => ({style: {}, children: [], setAttribute() {}, appendChild(c) { this.children.push(c); }, remove() { sida.document.ruta = null; }});
  const sida = {
    anrop,
    location: {hostname: host, hash, pathname: '/', search: ''},
    history: {replaceState: (a, b, url) => { anrop.push(['replaceState', url]); sida.location.hash = ''; }},
    document: {
      ruta: null,
      getElementById: () => sida.document.ruta,
      createElement: element,
      body: {appendChild: (e) => { sida.document.ruta = e; }},
    },
    fetch: async (url, opt = {}) => {
      anrop.push([opt.method || 'GET', url]);
      const json = (d) => ({ok: true, json: async () => d, text: async () => JSON.stringify(d)});
      if (url === '/axfood/rest/customer') return json({uid: inloggad ? '1234' : 'anonymous'});
      if (url === '/axfood/rest/csrf-token') return json('tok');
      if (url === '/axfood/rest/cart') return json(await api.hamtaKorg());
      if (url === '/axfood/rest/cart/addProducts') {
        assert.equal(opt.headers['X-CSRF-Token'], 'tok');
        const p = JSON.parse(opt.body).products;
        assert.equal(p.length, 1);
        const ok = await api.laggTill({kod: p[0].productCodePost, antal: p[0].qty, enhet: p[0].pickUnit});
        return {ok};
      }
      throw new Error('oväntat anrop ' + url);
    },
  };
  return sida;
}

const lank = '#veckohandla=' + b64({v: 1, s: 'willys', r: [{k: 'AGG', a: 12, e: 'p'}, {k: 'MJOLK', a: 1, e: 'p'}]});

test('fyller korgen, visar rutan och rensar länken ur adressen', async () => {
  const sida = fejkSida({hash: lank, startkorg: korg(['MJOLK', 1])});
  const t = await B.kor(sida);
  assert.match(t, /Lade till 1 varor, 1 fanns redan/);
  assert.equal(sida.anrop.filter((a) => a[0] === 'POST').length, 1);
  assert.deepEqual(sida.anrop.at(-1), ['replaceState', '/']);
  assert.match(sida.document.ruta.textContent, /^🛒 Veckohandla/);
  assert.ok(!sida.anrop.some((a) => /order|remove|delete/i.test(a[1])));
});

test('inte inloggad: inga POST och länken finns kvar', async () => {
  const sida = fejkSida({hash: lank, inloggad: false});
  assert.match(await B.kor(sida), /Logga in på Willys först/);
  assert.ok(!sida.anrop.some((a) => a[0] === 'POST'));
  assert.equal(sida.location.hash, lank);
});

test('fel webbplats, ingen länk och fel kedja ger besked utan anrop', async () => {
  for (const [sida, svar] of [
    [fejkSida({host: 'www.ica.se', hash: lank}), /www\.willys\.se eller www\.hemkop\.se/],
    [fejkSida({hash: ''}), /Ingen veckohandla-länk/],
    [fejkSida({host: 'www.hemkop.se', hash: lank}), /Länken gäller Willys, men sidan är Hemköp/],
  ]) {
    assert.match(await B.kor(sida), svar);
    assert.deepEqual(sida.anrop, []);
  }
});
