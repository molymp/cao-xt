"""
CAO-XT – Einkauf: Lieferanten-Web-Zugang (Phase 4).

Anreicherung der Lieferanten-Bestellpositionen mit Stammdaten aus dem
Web-Portal des jeweiligen Lieferanten – primaer Barcode + Bild + EK.

Modul-Aufbau (analog ``common.einkauf_parser``):
  * Eine generische Routing-Funktion ``web_login_test(lief)`` und
    ``web_artikel_holen(lief, artnr)``, die anhand
    ``XT_EINKAUF_LIEFERANT.WEB_KEY`` auf einen lieferanten-spezifischen
    Sub-Treiber routen.
  * Erster Treiber: ``utz24`` fuer https://www.utz24.online/.

Sicherheit:
  * Nur Lese-Zugriff auf das Lieferanten-Portal. Wir submitten
    ausschliesslich das Login-Formular und navigieren auf
    Stammdaten-Seiten.
  * Credentials kommen aus DORFKERN_KONFIG (SECRET) und werden hier
    NUR im Speicher genutzt.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

from common import einkauf as _einkauf

log = logging.getLogger(__name__)

# Vernuenftiger Default-User-Agent. Manche Portale lehnen "python-requests"
# pauschal ab oder triggern eine Bot-Schranke.
_USER_AGENT = (
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/130.0.0.0 Safari/537.36'
)
_TIMEOUT = 15  # Sekunden – Webseite ist nicht zeitkritisch


def _make_session():
    """Liefert eine frische ``requests.Session`` mit User-Agent.
    Lazy import, damit das Modul auch ohne installiertes ``requests``
    importierbar bleibt."""
    try:
        import requests
    except ImportError as exc:
        raise RuntimeError(
            'requests nicht installiert: '
            'pip install -r admin-app/app/requirements.txt'
        ) from exc
    sess = requests.Session()
    sess.headers.update({
        'User-Agent':      _USER_AGENT,
        'Accept-Language': 'de-DE,de;q=0.9,en;q=0.5',
    })
    return sess


def _credentials(lief: dict) -> dict:
    """Liest Username + Passwort + Kunden-Nr fuer einen Lieferanten."""
    return {
        'login_url':  lief.get('WEB_LOGIN_URL') or '',
        'username':   lief.get('WEB_USERNAME') or '',
        'kunden_nr':  lief.get('WEB_KUNDEN_NR') or '',
        'password':   _einkauf.web_password_holen(lief['KUERZEL']) or '',
    }


# ── UTZ-Treiber (utz24.online) ─────────────────────────────────────────────

# UTZ-Login-Form (Stand 2026-04-28, anonymes GET der Startseite):
#   POST /grosshandlung/de/?action=shop_login
#   action=shop_login
#   input_customer_no = <Kundennr>
#   input_login       = <Login>
#   input_password    = <Passwort>

_UTZ_LOGIN_URL_DEFAULT = (
    'https://www.utz24.online/grosshandlung/de/?action=shop_login'
)


def _utz_login(sess, creds: dict) -> dict:
    """Macht den Login-POST und prueft den Erfolg.

    Erfolgskriterium (Heuristik): finaler Pfad enthaelt nicht mehr
    ``b2b-login`` UND eine Logout-URL ist im Body sichtbar (manche
    UTZ-Themes zeigen die Login-Form auch nach Login als Sticky-Bar
    – nur das Wiederauftauchen der Form reicht also nicht als
    Fehlerzeichen).

    Liefert in jedem Fall ein Diagnose-Dict mit ausreichend Kontext
    zum Debuggen: HTTP-Status, finaler URL nach Redirects, Cookies,
    Page-Title, ein Body-Snippet und (bei Fehler) den Text rund um
    moegliche Error-Marker.
    """
    login_url = creds.get('login_url') or _UTZ_LOGIN_URL_DEFAULT
    if not all([creds.get('username'), creds.get('password'),
                creds.get('kunden_nr')]):
        return {'ok': False,
                'msg': 'Login, Kunden-Nr oder Passwort fehlt.'}

    # Browser-typische Header. Manche PHP-Shops weisen Bots ueber
    # fehlenden Referer/Origin zurueck.
    sess.headers.update({
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Origin': 'https://www.utz24.online',
        'Referer': login_url,
    })

    # Erst GET, damit Session-Cookies (PHPSESSID, ggf. Antibot) gesetzt sind.
    try:
        r0 = sess.get(login_url, timeout=_TIMEOUT, allow_redirects=True)
    except Exception as exc:
        return {'ok': False, 'msg': f'GET-Fehler: {exc}'}

    payload = {
        'action':            'shop_login',
        'input_customer_no': creds['kunden_nr'],
        'input_login':       creds['username'],
        'input_password':    creds['password'],
    }
    try:
        r = sess.post(login_url, data=payload, timeout=_TIMEOUT,
                      allow_redirects=True)
    except Exception as exc:
        return {'ok': False, 'msg': f'POST-Fehler: {exc}'}

    body = r.text or ''
    body_low = body.lower()
    final_url = r.url
    cookies = sorted(c.name for c in sess.cookies)

    # Title
    m = re.search(r'<title>([^<]{1,200})</title>', body, re.IGNORECASE)
    titel = (m.group(1).strip() if m else '')[:200]
    titel_low = titel.lower()

    # UTZ leitet nach Login NICHT weiter, sondern rendert die Shop-Seite
    # unter derselben URL. Erfolgskriterien daher mehrdimensional:
    #   1. Title hat keinen Login-/Anmelde-/Haendlerportal-Marker mehr
    #   2. Postlogin-Cookie 'sidgrosshandlung' ist gesetzt
    #   3. Body enthaelt einen Logout-/Mein-Konto-Marker
    # Mindestens zwei dieser drei -> eingeloggt.
    title_zeigt_login = (
        'login' in titel_low
        or 'anmeld' in titel_low
        or 'händlerportal' in titel_low
    )
    hat_shop_cookie = any(c.lower() == 'sidgrosshandlung' for c in cookies)
    hat_logout_indiz = any(
        t in body_low
        for t in ('shop_logout', 'action=shop_logout', 'abmelden',
                  'mein konto', 'meine bestellungen')
    )
    indizien = sum([
        not title_zeigt_login,
        hat_shop_cookie,
        hat_logout_indiz,
    ])
    erfolgreich = indizien >= 2

    # Bei Fehlversuch: Versuche eine konkrete Fehlermeldung aus dem
    # Body zu extrahieren (oft in <div class="alert">, <p class="error">
    # oder einem Text-Block direkt vor der Login-Form).
    fehler_snippet = ''
    if not erfolgreich:
        fehler_pattern = [
            # Rein generische Hinweise
            r'<(?:div|p|span)[^>]*class="[^"]*(?:alert|error|warning|message)[^"]*"[^>]*>([^<]{3,200})</',
            # UTZ-typische Strings
            r'(falsche?\s+(?:zugangs|login|passwort)[^<\n]{0,100})',
            r'(zugangsdaten[^<\n]{0,100}falsch[^<\n]{0,100})',
            r'(ung(?:ue|ü)ltig[^<\n]{0,150})',
        ]
        for pat in fehler_pattern:
            mm = re.search(pat, body, re.IGNORECASE)
            if mm:
                fehler_snippet = mm.group(1).strip()[:200]
                break

    # Body-Snippet zur Diagnose: erste 600 Zeichen sichtbarer Text
    sichtbar = re.sub(r'<script[\s\S]*?</script>', ' ', body)
    sichtbar = re.sub(r'<style[\s\S]*?</style>',  ' ', sichtbar)
    sichtbar = re.sub(r'<[^>]+>', ' ', sichtbar)
    sichtbar = re.sub(r'\s+', ' ', sichtbar).strip()
    snippet = sichtbar[:600]

    return {
        'ok':       erfolgreich,
        'msg':      ('Login erfolgreich' if erfolgreich
                     else (f'Login abgelehnt: {fehler_snippet}'
                           if fehler_snippet
                           else 'Login abgelehnt (kein Logout-Marker im Response)')),
        'status':   r.status_code,
        'final_url': final_url,
        'cookies':  cookies,
        'titel':    titel,
        'response_len': len(body),
        'snippet':  snippet,
        'fehler_snippet': fehler_snippet,
    }


# Detail-URL-Pattern aus dem UTZ-Markup:
#   /grosshandlung/de/<slug>-p<internal-id>/
# Die internal-id ist NICHT die Lieferanten-ArtNr, sondern eine
# UTZ-interne Produkt-ID; sie ist aus dem Suchergebnis extrahierbar.
_UTZ_DETAIL_LINK = re.compile(
    r'/grosshandlung/de/([a-z0-9][a-z0-9\-]*-p\d+)/',
    re.IGNORECASE,
)


def _utz_artikel_info(sess, artnr: str) -> dict:
    """Holt Stammdaten fuer eine UTZ-ArtNr in zwei Stufen:
        1. Suche: GET /grosshandlung/de/?suche=<artnr>
        2. Aus dem Such-Body wird der erste passende Slug-Link
           </grosshandlung/de/<slug>-p<id>/> extrahiert und gefolgt.
        3. Parser auf der Detailseite extrahiert Bezeichnung, Barcodes,
           EK, UVP, MwSt, VPE, Bild-URL.

    Gibt ein Diagnose-Dict zurueck (keine Persistierung):
        {
          'ok':            bool,
          'such_url':      str,
          'such_status':   int,
          'detail_links':  list[str],     # alle gefundenen Slug-Links
          'detail_url':    str | None,
          'detail_status': int | None,
          'parsed':        {bezeichnung, barcode_stueck, barcode_kt,
                            artnr_lief, ek_netto, uvp_brutto, mwst_pct,
                            inhalt, einheit, vpe_ek, bild_url}
                           | None,
          'raw_snippet':   str            # Detailseite, ~3kB
        }
    """
    base = 'https://www.utz24.online/grosshandlung/de/'
    such_url = f'{base}?suche={artnr}'
    try:
        r1 = sess.get(such_url, timeout=_TIMEOUT, allow_redirects=True)
    except Exception as exc:
        return {'ok': False, 'msg': f'Such-GET: {exc}',
                'such_url': such_url}
    body1 = r1.text or ''
    # Detail-Link kandidaten (dedup, Reihenfolge erhalten)
    treffer: list[str] = []
    seen: set = set()
    for m in _UTZ_DETAIL_LINK.finditer(body1):
        slug = m.group(1)
        if slug not in seen:
            seen.add(slug)
            treffer.append(slug)
    if not treffer:
        return {
            'ok': False,
            'msg': 'Kein Detail-Slug im Suchergebnis gefunden.',
            'such_url':    such_url,
            'such_status': r1.status_code,
            'detail_links': [],
            'raw_snippet': body1[:3000],
        }
    # Erstes Match nehmen
    detail_url = f'{base}{treffer[0]}/'
    try:
        r2 = sess.get(detail_url, timeout=_TIMEOUT, allow_redirects=True)
    except Exception as exc:
        return {'ok': False, 'msg': f'Detail-GET: {exc}',
                'such_url': such_url, 'detail_url': detail_url}
    body2 = r2.text or ''
    parsed = _parse_utz_detail(body2)
    return {
        'ok': bool(parsed and (parsed.get('barcode_stueck')
                                or parsed.get('bezeichnung'))),
        'such_url':      such_url,
        'such_status':   r1.status_code,
        'detail_links':  treffer[:6],
        'detail_url':    detail_url,
        'detail_status': r2.status_code,
        'detail_len':    len(body2),
        'parsed':        parsed,
        'raw_snippet':   body2[:3000],
    }


def _parse_utz_detail(html: str) -> dict:
    """Parst die Detailseite eines UTZ-Artikels.

    Erwartetes Markup (laut Screenshot vom 2026-04-28):
      <h1>Ferrero Kinder-Riegel</h1>
      ... „Barcode" ...
      „Stück - 4008400221021"
      „KT    - 4008400222806"
      „Artikel-Nr 35848" / „mit PZ 35848/4"
      „2,879 €"  (Verkaufs/EK)
      „UVP Preis 3,890 €"
      „zzgl. MwSt. 7%"
      „x28 Packung"
      „Inhalt 10er"
      <img class="..." src="/produktbilder/...">

    Heuristik: BeautifulSoup, dann Regex auf den Sicht-Text plus
    Verarbeitung wichtiger Spezial-Bereiche.
    """
    out: dict = {
        'bezeichnung':     '',
        'barcode_stueck':  '',
        'barcode_kt':      '',
        'artnr_lief':      '',
        'ek_netto':        None,   # EUR
        'uvp_brutto':      None,   # EUR
        'mwst_pct':        None,   # int (7 oder 19)
        'inhalt':          '',
        'einheit':         '',
        'vpe_ek':          None,   # int
        'bild_url':        '',
    }
    if not html:
        return out
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        # Fallback ohne bs4: nur grobes Regex-Parsing
        return _parse_utz_detail_regex(html, out)

    soup = BeautifulSoup(html, 'html.parser')

    # H1 = Bezeichnung
    h1 = soup.find('h1')
    if h1:
        out['bezeichnung'] = h1.get_text(strip=True)[:255]

    # Sichtbarer Text fuer alle weiteren Regex-Treffer
    for s in soup(['script', 'style', 'noscript']):
        s.decompose()
    sicht = soup.get_text(' ', strip=True)
    sicht = re.sub(r'\s+', ' ', sicht)

    # Barcode: zwei EAN-13-Zeilen, Praefix Stück / KT
    m = re.search(r'St(?:ü|ue)ck\s*[-–]\s*(\d{8,14})', sicht)
    if m: out['barcode_stueck'] = m.group(1)
    m = re.search(r'\bKT\s*[-–]\s*(\d{8,14})', sicht)
    if m: out['barcode_kt'] = m.group(1)

    # ArtNr (erste Treffer nach „Artikel-Nr.")
    m = re.search(r'Artikel-?Nr\.?\s*[:.]?\s*(\d{1,9})', sicht)
    if m: out['artnr_lief'] = m.group(1)

    # EK-Preis (oben grosser Preis): erstes „<komma>,<3-stellig> €" das
    # nicht direkt nach „UVP" steht.
    # Wir suchen alle Preis-Zahlen, sortieren in Reihenfolge des Auftretens.
    preise = list(re.finditer(r'(\d{1,4},\d{2,4})\s*€', sicht))
    if preise:
        # UVP-Marker
        uvp_marker = re.search(r'UVP[\s\w]*?(\d{1,4},\d{2,4})\s*€',
                               sicht, re.IGNORECASE)
        if uvp_marker:
            out['uvp_brutto'] = _komma_zu_float(uvp_marker.group(1))
        # EK = erster Preis, der nicht der UVP ist
        for p in preise:
            wert = _komma_zu_float(p.group(1))
            if out['uvp_brutto'] is None or abs(
                    (wert or 0) - (out['uvp_brutto'] or 0)) > 0.001:
                out['ek_netto'] = wert
                break

    # MwSt %
    m = re.search(r'MwSt\.?\s*(\d{1,2})\s*%', sicht, re.IGNORECASE)
    if m:
        try: out['mwst_pct'] = int(m.group(1))
        except ValueError: pass

    # VPE: „x28 Packung"
    m = re.search(r'x\s*(\d{1,4})\s*([A-Za-zäöüÄÖÜ]+)', sicht)
    if m:
        try: out['vpe_ek'] = int(m.group(1))
        except ValueError: pass
        out['einheit'] = m.group(2)[:40]

    # Inhalt
    m = re.search(r'Inhalt\s*[:.]?\s*([^\s][^\n]{0,40})', sicht,
                  re.IGNORECASE)
    if m:
        # Nimm bis zum naechsten Doppel-Leerzeichen oder „Zugabeaktion"
        wert = m.group(1).strip()
        wert = re.split(r'\s{2,}|Zugabeaktion|Einheit', wert)[0]
        out['inhalt'] = wert.strip(' ,;:')[:60]

    # Produktbild: erstes <img>, dessen Quelle „produkt" enthaelt;
    # sonst das groesste alt-Attribut, das die Bezeichnung enthaelt.
    bild = ''
    for img in soup.find_all('img'):
        src = img.get('src') or ''
        if not src:
            continue
        low = src.lower()
        if 'produkt' in low or 'artikel' in low or '/p4' in low:
            bild = src
            break
    if not bild and out['bezeichnung']:
        for img in soup.find_all('img'):
            alt = (img.get('alt') or '').lower()
            if alt and out['bezeichnung'].lower()[:15] in alt:
                bild = img.get('src') or ''
                break
    if bild and bild.startswith('/'):
        bild = 'https://www.utz24.online' + bild
    out['bild_url'] = bild

    return out


def _parse_utz_detail_regex(html: str, out: dict) -> dict:
    """Notnagel-Parser ohne bs4 (sehr grob)."""
    text = re.sub(r'<script[\s\S]*?</script>', ' ', html)
    text = re.sub(r'<style[\s\S]*?</style>',  ' ', text)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    m = re.search(r'St(?:ü|ue)ck\s*[-–]\s*(\d{8,14})', text)
    if m: out['barcode_stueck'] = m.group(1)
    m = re.search(r'\bKT\s*[-–]\s*(\d{8,14})', text)
    if m: out['barcode_kt'] = m.group(1)
    m = re.search(r'Artikel-?Nr\.?\s*[:.]?\s*(\d{1,9})', text)
    if m: out['artnr_lief'] = m.group(1)
    return out


def _komma_zu_float(s: str) -> Optional[float]:
    if not s:
        return None
    try:
        return float(s.replace('.', '').replace(',', '.'))
    except ValueError:
        return None


def web_artikel_diagnose(lief_rec_id: int, artnr: str) -> dict:
    """Loggt sich beim Lieferanten ein, holt die Detailseite zur ArtNr
    (Suche → Slug-Link → Detailseite) und parst sie.

    Reine Diagnose – kein Persistieren, keine Cache-Schreibe.
    """
    lief = _einkauf.holen(lief_rec_id)
    if not lief:
        return {'ok': False, 'msg': 'Lieferant nicht gefunden.'}
    web_key = (lief.get('WEB_KEY') or '').strip()
    if web_key != 'utz24':
        return {'ok': False,
                'msg': f'Diagnose nur fuer utz24 implementiert (WEB_KEY={web_key!r}).'}
    creds = _credentials(lief)
    if not all([creds['username'], creds['password'], creds['kunden_nr']]):
        return {'ok': False, 'msg': 'Zugangsdaten unvollstaendig.'}
    sess = _make_session()
    login_res = _utz_login(sess, creds)
    if not login_res.get('ok'):
        return {'ok': False, 'msg': 'Login fehlgeschlagen: '
                + str(login_res.get('msg')),
                'login': login_res}
    probe = _utz_artikel_info(sess, artnr.strip())
    return {'ok': probe.get('ok', False),
            'msg': probe.get('msg'),
            'login': {'titel':   login_res.get('titel'),
                      'cookies': login_res.get('cookies')},
            'probe': probe}


_UTZ_TREIBER = {
    'login':            _utz_login,
    'artikel_info':     _utz_artikel_info,
}


_TREIBER_REGISTRY = {
    'utz24': _UTZ_TREIBER,
}


def web_login_test(lief_rec_id: int) -> dict:
    """Diagnose-Endpoint: versucht den Login fuer den uebergebenen
    Lieferanten und gibt Status + Cookies + Titel zurueck.
    Liest selbst den Lieferanten + die Credentials aus der DB.
    """
    lief = _einkauf.holen(lief_rec_id)
    if not lief:
        return {'ok': False, 'msg': 'Lieferant nicht gefunden.'}
    web_key = (lief.get('WEB_KEY') or '').strip()
    if not web_key:
        return {'ok': False,
                'msg': 'Kein WEB_KEY hinterlegt – Lieferant kennt noch '
                       'keinen Web-Treiber. Erwartet z.B. "utz24".'}
    treiber = _TREIBER_REGISTRY.get(web_key)
    if not treiber:
        return {'ok': False,
                'msg': f'Kein Web-Treiber fuer WEB_KEY={web_key!r}.'}
    creds = _credentials(lief)
    if not all([creds['username'], creds['password'], creds['kunden_nr']]):
        fehlt = [k for k in ('username', 'kunden_nr', 'password')
                 if not creds.get(k)]
        return {'ok': False,
                'msg': 'Zugangsdaten unvollstaendig: ' + ', '.join(fehlt),
                'fehlt': fehlt}
    sess = _make_session()
    return treiber['login'](sess, creds)
