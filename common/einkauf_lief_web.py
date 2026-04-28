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

# UTZ Mobile-API (dynamic-commerce). Aus dem Frontend-Bundle der
# externen Such-App (intelligent-search.die.app) extrahiert:
#   GET https://www.utz24.online/userdata/dcshop/mobile-api-live-327-int.php
#       ?action=getItemsFromSearch
#       &search=<URL-encoded ArtNr; '&' wird zu '_' ersetzt>
#       &customer=<Kunden-Nr>
#       &price=no|yes
# Erfordert Session-Cookies vom Login (withCredentials=true).
_UTZ_API_URL = 'https://www.utz24.online/userdata/dcshop/mobile-api-live-327-int.php'

# Die `customer`-ID in der Mobile-API ist NICHT die Kunden-Nr (101772),
# sondern die UTZ-Mandanten-ID auf der externen die.app-Such-Plattform.
# Erkennbar aus der Such-URL der intelligent-search-App:
# https://intelligent-search.die.app/search/6826/false/<artnr>
_UTZ_DIE_APP_CUSTOMER = '6826'


def _utz_search_api(sess, artnr: str, _kunden_nr_unused: str = '') -> dict:
    """Ruft die UTZ Mobile-API auf, um alle Suchtreffer zu einer ArtNr
    zu erhalten. Bevorzugter Pfad gegenueber dem HTML-Scraping –
    liefert strukturierte JSON-Daten und braucht keinen Slug-Roulette.

    Args:
        sess:  requests.Session mit Login-Cookies.
        artnr: Lieferanten-Artikelnummer.
        _kunden_nr_unused: belanglos; ``customer`` in der Mobile-API
            ist die die.app-Mandanten-ID des Shops (6826 fuer UTZ),
            nicht die Habacher-Kunden-Nr.

    Returns: ``{'ok': bool, 'msg': str, 'json': dict|list|None,
        'items': list[dict], 'final_url': str, 'status': int,
        'raw_text': str}``.
    """
    from urllib.parse import quote
    such = quote(artnr.replace('&', '_'), safe='')
    url = (f'{_UTZ_API_URL}?action=getItemsFromSearch'
           f'&search={such}&customer={_UTZ_DIE_APP_CUSTOMER}&price=no')
    headers = {
        'Accept': 'application/json, text/plain, */*',
        'Origin': 'https://intelligent-search.die.app',
        'Referer': 'https://intelligent-search.die.app/',
        'X-Requested-With': 'XMLHttpRequest',
    }
    try:
        r = sess.get(url, headers=headers, timeout=_TIMEOUT)
    except Exception as exc:
        return {'ok': False, 'msg': f'GET-Fehler: {exc}', 'json': None,
                'items': [], 'final_url': url, 'status': 0,
                'raw_text': ''}
    raw = r.text or ''
    js: Any = None
    items: list[dict] = []
    msg = ''
    try:
        import json as _json
        js = _json.loads(raw)
        # Format-Heuristik: kann ein flaches Array sein, oder ein dict
        # mit Schluessel 'items'/'data'/'result'.
        if isinstance(js, list):
            items = js
        elif isinstance(js, dict):
            for key in ('items', 'data', 'result', 'list', 'artikel'):
                v = js.get(key)
                if isinstance(v, list):
                    items = v
                    break
            if not items and any(isinstance(v, dict) and v.get('itemNumber')
                                  for v in js.values()):
                items = [v for v in js.values() if isinstance(v, dict)]
    except Exception as exc:
        msg = f'JSON-Parse: {exc}'

    return {
        'ok':        len(items) > 0,
        'msg':       msg or (f'{len(items)} Treffer'
                              if items else 'Keine Treffer in API-Antwort'),
        'json':      js,
        'items':     items,
        'final_url': r.url,
        'status':    r.status_code,
        'raw_text':  raw[:2000],
    }


def _utz_item_to_parsed(item: dict) -> dict:
    """Mappt ein UTZ-API-Item-Dict auf unser geparstes Schema.

    Bestaetigte Feldnamen (aus dem Live-Test 2026-04-28, raw_keys):
        id           – interne Produkt-ID, fuer Detail-URL
                       /grosshandlung/de/<slug>-p<id>/
        item_no      – Lieferanten-Artikelnummer
        description  – Kurz-Bezeichnung
        summary      – Langtext / Untertitel
        vpe          – Verpackungseinheit
        uvp          – UVP (in der Such-API stehen Preise auf 0,
                       echte Werte holen wir aus der Detailseite)
        price        – EK
        img          – Produktbild-URL
        inv          – Verfuegbarkeit (z.B. „Nicht verfuegbar")
        vt, ld       – noch nicht eindeutig zugeordnet
        active, allow_invoice_discount – Flags
    """
    def _get(*keys):
        for k in keys:
            v = item.get(k)
            if v not in (None, ''):
                return v
        return None

    out = {
        'bezeichnung':    str(_get('description', 'itemName', 'name',
                                    'title') or '')[:255],
        'beschreibung':   str(_get('summary', 'description_long') or '')[:500],
        'barcode_stueck': '',     # nicht in der Such-API – via Detail-HTML
        'barcode_kt':     '',
        'artnr_lief':     str(_get('item_no', 'itemNumber',
                                    'articleNumber') or ''),
        # price ist in der Such-API 0 (kunden-spezifischer EK kommt
        # nur ueber die Detailseite); UVP ist dort allerdings schon
        # gefuellt.
        'ek_netto':       _maybe_float(_get('price', 'priceNet', 'ekNet')),
        'uvp_brutto':     _maybe_float(_get('uvp', 'rrp')),
        # 'v' = MwSt-Code, hier: '7' fuer 7%
        'mwst_pct':       _maybe_int(_get('v', 'vat', 'tax')),
        # 'vt' = Verkaufstext (z.B. '10er')
        'inhalt':         str(_get('vt', 'content', 'inhalt') or '')[:60],
        'einheit':        '',     # via Detail-HTML
        'vpe_ek':         _maybe_int(_get('vpe', 'packageSize')),
        'bild_url':       str(_get('img', 'imageUrl', 'image') or ''),
        'verfuegbarkeit': str(_get('inv', 'availability') or ''),
        'internal_id':    _get('id', 'productId', 'itemId'),
        # 'is' = URL-Slug (z.B. 'ferrero-kinder-riegel')
        'slug':           str(_get('is', 'slug', 'urlSlug') or ''),
        'raw_keys':       sorted(item.keys()) if isinstance(item, dict) else [],
    }
    if out['bild_url'] and out['bild_url'].startswith('/'):
        out['bild_url'] = 'https://www.utz24.online' + out['bild_url']
    return out


def _slug_aus_text(text: str) -> str:
    """Wandelt eine Bezeichnung in einen URL-Slug fuer UTZ-Detail-URLs.
    Beispiel: 'Ferrero Kinder-Riegel' -> 'ferrero-kinder-riegel'.
    Falls das Slug nicht 100%ig matcht, leitet UTZ trotzdem auf das
    richtige Ziel um (interne -p<id> ist eindeutig).
    """
    if not text:
        return 'p'
    s = text.lower()
    # Umlaute ausschreiben
    s = s.replace('ä', 'ae').replace('ö', 'oe').replace('ü', 'ue')
    s = s.replace('ß', 'ss')
    # Alles ausser a-z 0-9 zu '-'
    s = re.sub(r'[^a-z0-9]+', '-', s)
    s = re.sub(r'-+', '-', s).strip('-')
    return s or 'p'


def _maybe_float(v):
    if v is None or v == '':
        return None
    try:
        return float(str(v).replace(',', '.'))
    except (TypeError, ValueError):
        return None


def _maybe_int(v):
    if v is None or v == '':
        return None
    try:
        return int(float(str(v).replace(',', '.')))
    except (TypeError, ValueError):
        return None


def _utz_artikel_info(sess, artnr: str, kunden_nr: str = '') -> dict:
    """Holt Stammdaten fuer eine UTZ-ArtNr.

    Bevorzugter Pfad: JSON-API
        GET /userdata/dcshop/mobile-api-live-327-int.php
            ?action=getItemsFromSearch&search=<artnr>&customer=<kunden_nr>
        – derselbe Endpoint, den die externe intelligent-search-App
        nutzt. Liefert strukturierte Daten und braucht keinen
        Slug-Roulette.

    Fallback: HTML-Scraping ueber /grosshandlung/de/?suche=<artnr>
        und Slug-Match. Wird beibehalten, falls die API-Antwort einmal
        unbrauchbar ist.

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
    # ── 1. JSON-API probieren (Primary-Pfad) ────────────────────────────
    api = _utz_search_api(sess, artnr)
    if api.get('ok') and api.get('items'):
        # Treffer mit exakter ArtNr suchen; "Wichtiger Hinweis"-
        # Platzhalter (id=0, item_no='') ueberspringen.
        match_item = None
        for it in api['items']:
            if not isinstance(it, dict):
                continue
            if (it.get('id') in (0, '0') or not it.get('item_no')):
                continue
            if str(it.get('item_no') or '').strip() == artnr.strip():
                match_item = it
                break
        if match_item is None:
            # Mehrdeutig: ersten echten Treffer nehmen
            for it in api['items']:
                if isinstance(it, dict) and it.get('id') and it.get('item_no'):
                    match_item = it
                    break
        if match_item is not None:
            parsed = _utz_item_to_parsed(match_item)

            # Detail-HTML holen, um die kunden-spezifischen Preise +
            # MwSt + Barcodes + Inhalt zu bekommen (die fehlen in der
            # Such-API).
            detail_html = ''
            detail_status = None
            if parsed.get('internal_id'):
                slug = (parsed.get('slug')
                        or _slug_aus_text(parsed.get('bezeichnung') or ''))
                detail_url = (f'https://www.utz24.online/grosshandlung/de/'
                              f'{slug}-p{parsed["internal_id"]}/')
                try:
                    rd = sess.get(detail_url, timeout=_TIMEOUT,
                                   allow_redirects=True)
                    detail_status = rd.status_code
                    if rd.status_code == 200:
                        detail_html = rd.text or ''
                except Exception as exc:
                    log.warning('Detail-GET %s: %s', detail_url, exc)

            if detail_html:
                from_html = _parse_utz_detail(detail_html)
                # Detail-Daten ueberlagern API-Daten (Preise/Barcodes
                # sind dort kunden-spezifisch).
                for k in ('barcode_stueck', 'barcode_kt', 'mwst_pct',
                          'inhalt', 'einheit', 'bild_url'):
                    if from_html.get(k):
                        parsed[k] = from_html[k]
                if from_html.get('ek_netto') is not None:
                    parsed['ek_netto'] = from_html['ek_netto']
                if from_html.get('uvp_brutto') is not None:
                    parsed['uvp_brutto'] = from_html['uvp_brutto']
                if from_html.get('vpe_ek'):
                    parsed['vpe_ek'] = from_html['vpe_ek']
                if not parsed.get('bezeichnung') and from_html.get('bezeichnung'):
                    parsed['bezeichnung'] = from_html['bezeichnung']

            return {
                'ok':            True,
                'quelle':        'mobile-api+detail-html',
                'such_url':      api['final_url'],
                'such_status':   api['status'],
                'api_treffer':   len(api['items']),
                'detail_url':    detail_url if parsed.get('internal_id') else '',
                'detail_status': detail_status,
                'detail_len':    len(detail_html),
                'parsed':        parsed,
                'raw_snippet':   api['raw_text'],
            }
    # Wenn API nichts liefert, weiter mit HTML-Fallback
    # ────────────────────────────────────────────────────────────────────

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
    # Die UTZ-Suche liefert auf der Ergebnisseite oft mehrere Slugs
    # (Empfehlungen, „Meinten Sie", Aktionen) – der eigentliche
    # Volltext-Treffer ist nicht zwingend der erste. Wir gehen alle
    # Kandidaten durch (gekappt auf MAX) und nehmen den, dessen
    # geparste ``artnr_lief`` exakt matcht. Falls keiner matcht:
    # ersten Slug als „bester Fallback" liefern – mit warning-msg.
    MAX = 10
    versuche: list[dict] = []
    parsed_match: Optional[dict] = None
    detail_url_match: Optional[str] = None
    detail_status_match: Optional[int] = None
    detail_len_match: Optional[int] = None
    raw_match: str = ''
    for slug in treffer[:MAX]:
        d_url = f'{base}{slug}/'
        try:
            r2 = sess.get(d_url, timeout=_TIMEOUT, allow_redirects=True)
        except Exception as exc:
            versuche.append({'slug': slug, 'fehler': str(exc)})
            continue
        body2 = r2.text or ''
        parsed = _parse_utz_detail(body2)
        versuche.append({
            'slug':        slug,
            'status':      r2.status_code,
            'len':         len(body2),
            'artnr_lief':  parsed.get('artnr_lief', ''),
            'bezeichnung': parsed.get('bezeichnung', ''),
        })
        if (parsed.get('artnr_lief') or '').strip() == artnr.strip():
            parsed_match        = parsed
            detail_url_match    = d_url
            detail_status_match = r2.status_code
            detail_len_match    = len(body2)
            raw_match           = body2[:3000]
            break

    if parsed_match is None:
        # ArtNr im Such-Body lokalisieren – mit Kontext, damit man im
        # Markup sieht, ob es ein data-Attribut oder einen JS-Handler
        # gibt, der zur Detail-URL fuehrt.
        artnr_kontexte = []
        if artnr in body1:
            start = 0
            while True:
                i = body1.find(artnr, start)
                if i < 0:
                    break
                kontext = body1[max(0, i - 200): i + 1200]
                artnr_kontexte.append(kontext)
                start = i + len(artnr)
                if len(artnr_kontexte) >= 4:
                    break
        return {
            'ok': False,
            'msg': (f'ArtNr {artnr} unter den ersten {len(versuche)} '
                    'Slug-Treffern nicht gefunden. UTZ-Suche liefert '
                    'offenbar nur Empfehlungen/Werbeartikel zurueck, '
                    'der echte Treffer steht im Such-Body unter einem '
                    'anderen Markup-Element.'),
            'such_url':       such_url,
            'such_status':    r1.status_code,
            'detail_links':   treffer[:MAX],
            'versuche':       versuche,
            'artnr_kontexte': artnr_kontexte,
            'such_snippet':   body1[:3000],
        }

    return {
        'ok':            True,
        'such_url':      such_url,
        'such_status':   r1.status_code,
        'detail_links':  treffer[:MAX],
        'versuche':      versuche,
        'detail_url':    detail_url_match,
        'detail_status': detail_status_match,
        'detail_len':    detail_len_match,
        'parsed':        parsed_match,
        'raw_snippet':   raw_match,
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

    # Inhalt: zwischen 'Inhalt' und dem naechsten bekannten Label.
    # Bekannte Folge-Labels: Zugabeaktion, Einheit, Artikel,
    # Warenkorb, Stueckpreis, MwSt, UVP, Lieferzeit.
    m = re.search(
        r'Inhalt\s*[:.]?\s+([^\s][^\n]{0,80}?)'
        r'(?=\s{2,}|Zugabeaktion|Einheit\b|Artikel\b|Warenkorb|MwSt|UVP\b|Stueckpr|St\xc3\xbcckpr)',
        sicht, re.IGNORECASE)
    if m:
        out['inhalt'] = m.group(1).strip(' ,;:')[:60]

    # Produktbild: bevorzugt itemprop="image" (Schema.org), dann
    # das erste img, dessen src auf eine sinnvolle Bildersammlung
    # zeigt (data, content, produkte, artikel, p\d+).
    bild = ''
    img_meta = soup.find('img', attrs={'itemprop': 'image'})
    if img_meta:
        bild = img_meta.get('src') or img_meta.get('data-src') or ''
    if not bild:
        # OpenGraph/Twitter-Image als Fallback
        og = soup.find('meta', attrs={'property': 'og:image'})
        if og and og.get('content'):
            bild = og['content']
    if not bild:
        for img in soup.find_all('img'):
            src = (img.get('src') or img.get('data-src') or '').strip()
            if not src or src.startswith('data:'):
                continue
            low = src.lower()
            if any(s in low for s in (
                    '/produkt', '/artikel', '/data/', '/content/',
                    '/p_', '/pic/', '/upload', '/media',
                    re.search(r'-p\d+', low) and '-p' or '')):
                # Layout-Pfade ('/layout/') sind Theme-Assets (Logo,
                # Icons), die wollen wir nicht.
                if '/layout/' in low or 'logo' in low or 'icon' in low:
                    continue
                bild = src
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
    probe = _utz_artikel_info(sess, artnr.strip(),
                              kunden_nr=creds.get('kunden_nr', ''))
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
