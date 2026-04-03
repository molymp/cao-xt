// Google Apps Script – Mittagstisch Web App
// Einrichten: Erweiterungen → Apps Script → Code einfügen → Bereitstellen → Neue Bereitstellung → Web-App
// Zugriff: "Jeder" (anonym), ausführen als: "Ich"

const SPREADSHEET_ID = '1Fr2INvHllH61SjIkuTOCrMATrC78xxYW0W-2Rre2ALQ';
const SHEET_GID      = '1709744959';

function doGet() {
  const data = getSheetData();
  const html = buildHtml(data);
  return HtmlService.createHtmlOutput(html)
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

function getSheetData() {
  const ss    = SpreadsheetApp.openById(SPREADSHEET_ID);
  const sheet = ss.getSheets().find(s => String(s.getSheetId()) === SHEET_GID)
             || ss.getSheets()[0];
  const rows  = sheet.getDataRange().getValues();
  return rows;
}

function buildHtml(rows) {
  // Zeile 0: Titel, Zeilen 1-5: Wochentage, danach: Fußzeilen
  const title      = rows[0]  ? rows[0][0]  : 'Mittagstisch';
  const weekdays   = rows.slice(1, 6);          // Zeilen 1–5: Mo–Fr
  const footerRows = rows.slice(6).filter(r => r[0] || r[1]); // Rest

  const dayRows = weekdays.map(r => {
    const label = r[0] ? String(r[0]) : '';
    const meal  = r[1] ? String(r[1]) : '';
    if (!label && !meal) return '';
    return `
      <tr>
        <td class="day">${escHtml(label)}</td>
        <td class="meal">${escHtml(meal)}</td>
      </tr>`;
  }).join('');

  const footerHtml = footerRows.map(r => {
    const text = [r[0], r[1]].filter(Boolean).join(' ');
    return `<p class="footer-line">${escHtml(String(text))}</p>`;
  }).join('');

  return `<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>${escHtml(title)}</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      font-family: 'Segoe UI', Arial, sans-serif;
      background: #fffdf8;
      color: #2c2c2c;
      padding: 20px 16px 24px;
    }

    h1 {
      font-size: 1.25rem;
      font-weight: 700;
      color: #b03a2e;
      letter-spacing: 0.02em;
      margin-bottom: 16px;
      padding-bottom: 8px;
      border-bottom: 2px solid #e8d5c4;
    }

    table {
      width: 100%;
      border-collapse: collapse;
    }

    tr { border-bottom: 1px solid #ede3d8; }
    tr:last-child { border-bottom: none; }

    td {
      padding: 10px 6px;
      vertical-align: top;
      font-size: 0.95rem;
      line-height: 1.45;
    }

    td.day {
      font-weight: 600;
      color: #7d4e24;
      white-space: nowrap;
      padding-right: 16px;
      width: 30%;
    }

    td.meal { color: #2c2c2c; }

    .footer {
      margin-top: 18px;
      padding-top: 14px;
      border-top: 1px solid #e8d5c4;
    }

    .footer-line {
      font-size: 0.82rem;
      color: #666;
      line-height: 1.5;
      margin-bottom: 4px;
    }

    .footer-line:first-child { font-weight: 500; color: #444; }

    .updated {
      font-size: 0.72rem;
      color: #aaa;
      margin-top: 10px;
    }
  </style>
</head>
<body>
  <h1>${escHtml(title)}</h1>
  <table>${dayRows}</table>
  <div class="footer">
    ${footerHtml}
    <p class="updated">Zuletzt geladen: ${new Date().toLocaleString('de-DE', {timeZone:'Europe/Berlin'})}</p>
  </div>
</body>
</html>`;
}

function escHtml(str) {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
