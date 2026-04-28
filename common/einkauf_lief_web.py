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


def _utz_artikel_probe(sess, artnr: str) -> dict:
    """Diagnose-Hilfe: Versucht nach erfolgreichem Login mehrere
    plausible Detail/Such-URLs fuer eine Lieferanten-ArtNr und liefert
    den vielversprechendsten Response zurueck.

    Da wir das echte UTZ-URL-Schema noch nicht kennen, probieren wir
    typische Muster:
      ?suche=<artnr>
      ?action=search&suche=<artnr>
      ?action=artikel&id=<artnr>
      /artikel/<artnr>/
      /grosshandlung/de/?suche=<artnr>
    """
    base = 'https://www.utz24.online/grosshandlung/de/'
    kandidaten = [
        f'{base}?suche={artnr}',
        f'{base}?action=search&suche={artnr}',
        f'{base}?action=search&q={artnr}',
        f'{base}?action=artikel&id={artnr}',
        f'{base}?action=detail&id={artnr}',
        f'{base}artikel/{artnr}/',
        f'{base}?artnr={artnr}',
    ]
    versuche: list[dict] = []
    bester: Optional[dict] = None
    for url in kandidaten:
        try:
            r = sess.get(url, timeout=_TIMEOUT, allow_redirects=True)
            body = r.text or ''
            # Heuristik: Treffer hat artnr im Body und schickt nicht
            # einfach die Login-Seite zurueck.
            hat_artnr = artnr in body
            ist_login_seite = ('form_shop_login' in body
                                and 'b2b-login' in r.url.lower())
            score = 0
            if hat_artnr:        score += 2
            if not ist_login_seite: score += 1
            if r.status_code == 200: score += 1
            versuche.append({
                'url':     url,
                'final':   r.url,
                'status':  r.status_code,
                'len':     len(body),
                'hat_artnr': hat_artnr,
                'login_seite': ist_login_seite,
                'score':   score,
            })
            if bester is None or score > bester['score']:
                bester = {**versuche[-1], 'body': body}
        except Exception as exc:
            versuche.append({
                'url': url, 'fehler': str(exc), 'score': -1,
            })

    # Title + Snippet aus dem besten Kandidaten
    body = (bester or {}).get('body', '')
    m = re.search(r'<title>([^<]{1,200})</title>', body, re.IGNORECASE)
    titel = (m.group(1).strip() if m else '')[:200]
    sichtbar = re.sub(r'<script[\s\S]*?</script>', ' ', body)
    sichtbar = re.sub(r'<style[\s\S]*?</style>',  ' ', sichtbar)
    sichtbar = re.sub(r'<[^>]+>', ' ', sichtbar)
    sichtbar = re.sub(r'\s+', ' ', sichtbar).strip()
    # Snippet rund um die ArtNr suchen, falls vorhanden
    if artnr in sichtbar:
        i = sichtbar.find(artnr)
        snippet = sichtbar[max(0, i - 100): i + 700]
    else:
        snippet = sichtbar[:800]

    # Sicherheits-Snippet: rohes HTML rund um die ArtNr (bis ~1500 chars)
    raw_snippet = ''
    if body and artnr in body:
        i = body.find(artnr)
        raw_snippet = body[max(0, i - 200): i + 1300]

    return {
        'best_url':    (bester or {}).get('url'),
        'best_final':  (bester or {}).get('final'),
        'best_score':  (bester or {}).get('score'),
        'best_status': (bester or {}).get('status'),
        'best_len':    (bester or {}).get('len'),
        'titel':       titel,
        'snippet':     snippet,
        'raw_snippet': raw_snippet,
        'versuche':    versuche,
    }


def web_artikel_diagnose(lief_rec_id: int, artnr: str) -> dict:
    """Loggt sich beim Lieferanten ein und probiert eine ArtNr-Suche.
    Liefert ein Diagnose-Dict – kein Persistieren, keine Cache-Schreibe.

    Soll uns helfen, das URL-Schema und HTML-Markup pro Lieferant zu
    verstehen, bevor wir den eigentlichen Artikel-Lookup hart codieren.
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
    probe = _utz_artikel_probe(sess, artnr.strip())
    return {'ok': True, 'login': {'titel': login_res.get('titel'),
                                   'cookies': login_res.get('cookies')},
            'probe': probe}


_UTZ_TREIBER = {
    'login':            _utz_login,
    'artikel_probe':    _utz_artikel_probe,
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
