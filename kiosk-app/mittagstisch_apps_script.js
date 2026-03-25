/**
 * Mittagstisch – Google Apps Script Web App
 * ==========================================
 * Zeigt die Angebote der aktuellen und nächsten Woche als styled HTML.
 *
 * Einrichtung:
 *   1. Im Google Sheet: Erweiterungen → Apps Script
 *   2. Diesen Code einfügen (alte Funktion myFunction ersetzen)
 *   3. Rechts oben: "Bereitstellen" → "Neue Bereitstellung"
 *      - Typ: Web-App
 *      - Ausführen als: Ich (dein Google-Konto)
 *      - Zugriff: Jeder
 *   4. Die angezeigte URL in Google Sites einbetten:
 *      Seite bearbeiten → Einfügen → Einbetten → URL einfügen
 *
 * Sheet-Struktur pro Tab (z.B. "KW13_2026"):
 *   A1      : Wochenplan Mittagstisch
 *   A3:C7   : Datum | Wochentag | Gericht
 *   A9, C9  : "Außerdem täglich:" | Text
 *   A10, C10: "Jetzt neu:" | Text
 *   A12     : Telefon
 *   A13     : Hinweis
 */

// ── Hilfsfunktionen ───────────────────────────────────────────

function getMontag(d) {
  var day = d.getDay();           // 0=So, 1=Mo … 6=Sa
  var diff = (day === 0) ? -6 : 1 - day;
  var m = new Date(d);
  m.setDate(d.getDate() + diff);
  m.setHours(0, 0, 0, 0);
  return m;
}

function isoWeek(d) {
  // ISO-Kalenderwoche nach ISO 8601
  var tmp = new Date(d.getTime());
  tmp.setHours(0, 0, 0, 0);
  tmp.setDate(tmp.getDate() + 3 - (tmp.getDay() + 6) % 7);
  var week1 = new Date(tmp.getFullYear(), 0, 4);
  return 1 + Math.round(((tmp - week1) / 86400000 - 3 + (week1.getDay() + 6) % 7) / 7);
}

function kwName(montag) {
  var kw   = isoWeek(montag);
  var jahr = montag.getFullYear();
  // Jahreswechsel: KW1 kann im Dezember liegen
  var kwMontag = getMontag(montag);
  if (kwMontag.getMonth() === 11 && kw === 1) jahr++;
  if (kwMontag.getMonth() === 0  && kw >= 52) jahr--;
  return 'KW' + (kw < 10 ? '0' : '') + kw + '_' + jahr;
}

function leseWoche(ss, montag) {
  var name = kwName(montag);
  var ws;
  try {
    ws = ss.getSheetByName(name);
  } catch(e) { return null; }
  if (!ws) return null;

  var daten = ws.getRange('A1:C13').getValues();
  function z(zeile, spalte) {   // 1-basiert
    var v = daten[zeile - 1][spalte - 1];
    return v ? String(v).trim() : '';
  }

  var tage = [];
  for (var i = 0; i < 5; i++) {
    tage.push({
      datum:   z(3 + i, 1),
      tag:     z(3 + i, 2),
      gericht: z(3 + i, 3)
    });
  }
  return {
    kwName:    name,
    tage:      tage,
    taeglich:  z(9, 3),
    jetzt_neu: z(10, 3),
    telefon:   z(12, 1),
    hinweis:   z(13, 1)
  };
}

// ── HTML-Rendering ────────────────────────────────────────────

function renderWoche(w, titel) {
  if (!w) return '';

  var zeilen = '';
  w.tage.forEach(function(tag) {
    if (!tag.gericht) return;
    zeilen += '<tr>'
      + '<td class="datum">' + esc(tag.datum) + '</td>'
      + '<td class="tag">'   + esc(tag.tag)   + '</td>'
      + '<td class="gericht">' + esc(tag.gericht) + '</td>'
      + '</tr>';
  });

  var zusatz = '';
  if (w.taeglich) {
    zusatz += '<div class="zusatz"><span class="zusatz-label">Außerdem täglich:</span> '
      + esc(w.taeglich) + '</div>';
  }
  if (w.jetzt_neu) {
    zusatz += '<div class="zusatz neu"><span class="zusatz-label">Jetzt neu:</span> '
      + esc(w.jetzt_neu) + '</div>';
  }

  return '<div class="woche">'
    + '<h2>' + esc(titel) + '</h2>'
    + '<table>'
    + '<thead><tr><th>Datum</th><th>Tag</th><th>Tagesangebot</th></tr></thead>'
    + '<tbody>' + zeilen + '</tbody>'
    + '</table>'
    + (zusatz ? '<div class="zusatz-bereich">' + zusatz + '</div>' : '')
    + '</div>';
}

function esc(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ── Web-App Einstiegspunkt ────────────────────────────────────

function doGet() {
  var ss    = SpreadsheetApp.getActiveSpreadsheet();
  var heute = new Date();
  var mo1   = getMontag(heute);
  var mo2   = new Date(mo1); mo2.setDate(mo1.getDate() + 7);

  var w1 = leseWoche(ss, mo1);
  var w2 = leseWoche(ss, mo2);

  var telefon = (w1 && w1.telefon) ? w1.telefon : '';
  var hinweis  = (w1 && w1.hinweis) ? w1.hinweis : '';

  var html = '<!DOCTYPE html><html lang="de"><head>'
    + '<meta charset="UTF-8">'
    + '<meta name="viewport" content="width=device-width,initial-scale=1">'
    + '<style>'
    + 'body{font-family:Arial,sans-serif;margin:0;padding:16px;background:#f7f3ea;color:#142808;font-size:15px}'
    + '.woche{background:white;border-radius:10px;box-shadow:0 2px 10px rgba(0,0,0,.1);'
    + '  padding:18px 22px;margin-bottom:20px}'
    + 'h2{font-size:1.15rem;color:#1a4010;margin:0 0 12px;font-weight:700;'
    + '  border-bottom:2px solid #d4e8c2;padding-bottom:6px}'
    + 'table{width:100%;border-collapse:collapse}'
    + 'thead tr{background:#1a4010;color:#f7f3ea}'
    + 'th{padding:8px 12px;text-align:left;font-size:0.75rem;text-transform:uppercase;letter-spacing:.06em}'
    + 'td{padding:8px 12px;border-bottom:1px solid #ece3cc;font-size:0.9rem}'
    + 'tr:last-child td{border-bottom:none}'
    + '.datum{width:60px;color:#5a7a3a;font-weight:700;white-space:nowrap}'
    + '.tag{width:90px;font-weight:700}'
    + '.zusatz-bereich{margin-top:12px}'
    + '.zusatz{font-size:0.88rem;padding:8px 12px;margin-top:6px;border-radius:6px;background:#d4e8c2;color:#1a4010}'
    + '.zusatz.neu{background:#fef8e2;color:#7a5a00}'
    + '.zusatz-label{font-weight:700}'
    + '.footer{font-size:0.78rem;color:#5a7a3a;text-align:center;margin-top:4px;line-height:1.6}'
    + '</style></head><body>'
    + renderWoche(w1, 'Diese Woche')
    + renderWoche(w2, 'Nächste Woche')
    + (telefon ? '<div class="footer">📞 ' + esc(telefon) + '</div>' : '')
    + (hinweis  ? '<div class="footer">' + esc(hinweis)  + '</div>' : '')
    + '</body></html>';

  return HtmlService
    .createHtmlOutput(html)
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}
