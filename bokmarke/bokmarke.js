/*
 Veckohandla-bokmärket: fyller korgen på www.willys.se eller www.hemkop.se från länken
 https://www.willys.se/#veckohandla=<data> i veckans rapport.

 - Kräver att du är inloggad. Lägger bara till det som fattas, prövar reserver när butiken nekar en vara,
   lägger aldrig någon order och tar aldrig bort något.
 - Samma logik som korg_diff och fyll_korg i veckohandla/cart.py.
 - Fungerar som bokmärke (javascript:-URL) och som iPhone-genväg ("Kör JavaScript på webbsida").

 Skriv med semikolon och bara helradskommentarer: verktyg/bokmarke_url.py minifierar genom att ta bort
 kommentarer och radbrytningar.
*/
(function () {
  'use strict';
  var KEDJOR = {'www.willys.se': 'willys', 'www.hemkop.se': 'hemkop'};
  var NAMN = {willys: 'Willys', hemkop: 'Hemköp'};
  var ENHET = {p: 'pieces', k: 'kilogram'};

  function rad(r) {
    return {
      kod: r.kod || r.k,
      antal: Number(r.antal != null ? r.antal : r.a),
      enhet: ENHET[r.enhet || r.e] || r.enhet || r.e || 'pieces',
      reserver: (r.reserver || r.r || []).map(rad)
    };
  }

  function avkoda(hash) {
    var m = /[#&]veckohandla=([A-Za-z0-9_-]+)/.exec(hash || '');
    if (!m) { return null; }
    var b64 = m[1].replace(/-/g, '+').replace(/_/g, '/');
    while (b64.length % 4) { b64 += '='; }
    var bin = atob(b64);
    var bytes = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) { bytes[i] = bin.charCodeAt(i); }
    var d = JSON.parse(new TextDecoder().decode(bytes));
    return {kedja: d.kedja || d.s, rader: (d.rader || d.r || []).map(rad)};
  }

  function summera(rader) {
    var ut = [];
    var index = {};
    rader.forEach(function (r) {
      var nyckel = r.kod + '|' + r.enhet;
      if (nyckel in index) { ut[index[nyckel]].antal += r.antal; return; }
      index[nyckel] = ut.length;
      ut.push({kod: r.kod, antal: r.antal, enhet: r.enhet, reserver: r.reserver.slice()});
    });
    return ut;
  }

  function iKorgen(korg) {
    var ut = {};
    (korg.products || []).forEach(function (p) {
      ut[p.code] = {antal: Number(p.pickQuantity || 0), enhet: (p.pickUnit && p.pickUnit.code) || 'pieces', namn: p.name || ''};
    });
    return ut;
  }

  function diff(onskat, korg) {
    var finns = iKorgen(korg);
    var d = {att: [], redan: [], annan: []};
    summera(onskat).forEach(function (r) {
      var f = finns[r.kod];
      if (f && f.enhet !== r.enhet) { d.annan.push(r); }
      else if (f && f.antal >= r.antal) { d.redan.push(r); }
      else { d.att.push({kod: r.kod, antal: Math.ceil(r.antal - (f ? f.antal : 0)), enhet: r.enhet, reserver: r.reserver}); }
    });
    return d;
  }

  async function fyll(rader, api) {
    rader = summera(rader);
    var korg = await api.hamtaKorg();
    var d = diff(rader, korg);
    var nekade = [];
    for (var i = 0; i < d.att.length; i++) {
      if (!(await api.laggTill(d.att[i]))) { nekade.push(d.att[i].kod); }
    }
    korg = await api.hamtaKorg();
    var perKod = {};
    rader.forEach(function (r) { perKod[r.kod] = r; });
    var byten = [];
    var misslyckade = [];
    for (var j = 0; j < nekade.length; j++) {
      var r = perKod[nekade[j]];
      var ok = false;
      for (var k = 0; k < r.reserver.length && !ok; k++) {
        var behov = diff([r.reserver[k]], korg);
        if (!behov.att.length) { ok = !behov.annan.length; }
        else { ok = await api.laggTill(behov.att[0]); korg = await api.hamtaKorg(); }
        if (ok) { byten.push({fran: r, till: r.reserver[k]}); }
      }
      if (!ok) { misslyckade.push(r); }
    }
    return {
      tillagda: d.att.filter(function (r) { return nekade.indexOf(r.kod) < 0; }),
      redan: d.redan, annan: d.annan, byten: byten, misslyckade: misslyckade, namn: iKorgen(korg)
    };
  }

  function text(res, kedja) {
    function n(r) { return (res.namn[r.kod] && res.namn[r.kod].namn) || r.kod; }
    var rader = [NAMN[kedja] + '-korgen är uppdaterad.', 'Lade till ' + res.tillagda.length + ' varor, ' + res.redan.length + ' fanns redan.'];
    res.byten.forEach(function (b) { rader.push('Bytt till reserv: ' + n(b.fran) + ' → ' + n(b.till)); });
    if (res.annan.length) { rader.push('Finns redan i annan enhet (rördes inte): ' + res.annan.map(n).join(', ')); }
    if (res.misslyckade.length) { rader.push('Gick inte att lägga till: ' + res.misslyckade.map(n).join(', ')); }
    rader.push('Ingen order är lagd. Granska korgen och beställ själv.');
    return rader.join('\n');
  }

  function visa(doc, meddelande) {
    var gammal = doc.getElementById('veckohandla-ruta');
    if (gammal) { gammal.remove(); }
    var ruta = doc.createElement('div');
    ruta.id = 'veckohandla-ruta';
    ruta.setAttribute('style', 'position:fixed;z-index:2147483647;left:12px;right:12px;top:12px;max-height:80vh;overflow:auto;background:#fff;color:#222;border:2px solid #2a7a2a;border-radius:12px;padding:16px;font:16px/1.4 -apple-system,Helvetica,Arial,sans-serif;white-space:pre-wrap;box-shadow:0 4px 24px rgba(0,0,0,.3)');
    ruta.textContent = '🛒 Veckohandla\n\n' + meddelande;
    var knapp = doc.createElement('button');
    knapp.textContent = 'Stäng';
    knapp.setAttribute('style', 'display:block;margin-top:12px;padding:8px 16px;font-size:16px');
    knapp.onclick = function () { ruta.remove(); };
    ruta.appendChild(knapp);
    doc.body.appendChild(ruta);
    return meddelande;
  }

  async function kor(w) {
    var kedja = KEDJOR[w.location.hostname];
    if (!kedja) { return visa(w.document, 'Öppna länken från veckans rapport, så att sidan är www.willys.se eller www.hemkop.se, och kör sedan bokmärket igen.'); }
    var data = avkoda(w.location.hash);
    if (!data) { return visa(w.document, 'Ingen veckohandla-länk i adressen. Öppna "Fyll korgen på mobilen" i veckans rapport och kör sedan bokmärket igen.'); }
    if (data.kedja && data.kedja !== kedja) { return visa(w.document, 'Länken gäller ' + NAMN[data.kedja] + ', men sidan är ' + NAMN[kedja] + '.'); }
    var hamta = function (sokvag) { return w.fetch(sokvag, {credentials: 'same-origin'}).then(function (r) { return r.json(); }); };
    var kund = await hamta('/axfood/rest/customer');
    if (!kund || !kund.uid || kund.uid === 'anonymous') { return visa(w.document, 'Logga in på ' + NAMN[kedja] + ' först och kör sedan bokmärket igen. Länken finns kvar i adressen.'); }
    var tok = JSON.parse(await (await w.fetch('/axfood/rest/csrf-token', {credentials: 'same-origin'})).text());
    var api = {
      hamtaKorg: function () { return hamta('/axfood/rest/cart'); },
      laggTill: async function (r) {
        var svar = await w.fetch('/axfood/rest/cart/addProducts', {
          method: 'POST', credentials: 'same-origin',
          headers: {'Content-Type': 'application/json', 'X-CSRF-Token': tok},
          body: JSON.stringify({products: [{productCodePost: r.kod, qty: r.antal, pickUnit: r.enhet, hideDiscountToolTip: false, noReplacementFlag: false}]})
        });
        return svar.ok;
      }
    };
    var res = await fyll(data.rader, api);
    w.history.replaceState(null, '', w.location.pathname + w.location.search);
    return visa(w.document, text(res, kedja));
  }

  var exporter = {avkoda: avkoda, summera: summera, iKorgen: iKorgen, diff: diff, fyll: fyll, text: text, kor: kor};
  if (typeof window === 'undefined') { module.exports = exporter; return; }
  var klar = kor(window).catch(function (e) { return visa(document, 'Något gick fel: ' + e.message); });
  if (typeof completion === 'function') { klar.then(function (t) { completion(t); }); }
})();
