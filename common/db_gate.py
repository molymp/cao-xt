"""
DB-Erreichbarkeits-Gate fuer die Flask-Apps.

Hintergrund: Nach einem Box-Reboot starten die Apps ~5 s nach Boot,
die LAN-Route zur (remote) DB steht aber erst ~15-25 s spaeter. In
diesem Fenster scheitert jede DB-Abfrage. Der Permission-Guard ist
(korrekt) fail-closed -> ``hat_recht`` = False -> der App-Guard leitet
auf ``index`` um -> ``index`` triggert denselben Guard -> Redirect-
Schleife -> Chromium ``ERR_TOO_MANY_REDIRECTS``. Loest sich erst auf,
wenn die DB da ist.

Dieses Gate haengt sich als ALLERERSTER ``before_request`` ein (vor
dem Permission-Guard) und liefert bei nicht erreichbarer DB eine
freundliche, sich selbst neu ladende Warteseite (HTTP 200) bzw. fuer
API/JSON ein 503 — statt der Redirect-Schleife. Sobald die DB
erreichbar ist, faellt das Gate transparent durch. Wirkt nicht nur
beim Boot, sondern bei jedem DB-Haenger.

Die Reachability-Pruefung ist ein billiger TCP-Connect (kein DB-Login,
kein Pool), Ergebnis ~2 s gecached — kein Connection-Sturm, keine
spuerbare Latenz im Normalbetrieb.
"""
import socket
import threading
import time
from typing import Iterable

from flask import request, Response, jsonify

from common.config import load_db_config


_TTL_S       = 2.0     # Cache-Lebensdauer des Reachability-Ergebnisses
_TCP_TIMEOUT = 1.5     # einzelner Connect-Versuch

_lock = threading.Lock()
_cache = {'ts': 0.0, 'ok': True}   # optimistischer Start (ok=True)

# Pfade, die AUCH bei toter DB erreichbar bleiben muessen (kein DB-
# Zugriff, statisch / Health). Bewusst knapp.
_DEFAULT_WHITELIST = (
    '/static/', '/brand/', '/favicon', '/healthz', '/status',
    '/api/status',
)


def _db_erreichbar() -> bool:
    """TCP-Connect zur konfigurierten DB. Ergebnis ~2 s gecached."""
    now = time.monotonic()
    with _lock:
        if now - _cache['ts'] < _TTL_S:
            return _cache['ok']
    ok = False
    try:
        # WICHTIG: die EFFEKTIVE DB-Config nutzen (das, womit die App
        # via init_pool/config_local wirklich verbunden ist), NICHT roh
        # load_db_config(). Sonst prueft das Gate in config_local-
        # basierten Umgebungen die Platzhalter-caoxt.ini → DB scheinbar
        # nie erreichbar → ALLE Apps haengen dauerhaft im "System
        # startet"-Splash.
        try:
            from common.db import effektive_db_config
            cfg = effektive_db_config()
        except Exception:
            cfg = load_db_config()
        host = cfg['host']
        port = int(cfg['port'])
        with socket.create_connection((host, port), timeout=_TCP_TIMEOUT):
            ok = True
    except Exception:
        ok = False
    with _lock:
        _cache['ts'] = time.monotonic()
        _cache['ok'] = ok
    return ok


_WARTE_HTML = """<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="4">
<title>System startet …</title>
<style>
 html,body{height:100%;margin:0}
 body{display:flex;align-items:center;justify-content:center;
   font-family:'Nunito',system-ui,sans-serif;background:#f0eee9;color:#141414}
 .box{text-align:center;max-width:30rem;padding:2rem}
 .logo{margin:0 auto 1.6rem;display:flex;justify-content:center}
 p{margin:.4rem 0;line-height:1.5} small{color:#8a8164}
</style></head><body><div class="box">
 <div class="logo">
   <span data-dorfkern-logo="vertical" data-size="132" data-theme="light"
         data-tagline="System startet …"
         data-autoplay="true" data-loop="900"></span>
 </div>
 <p>Die Datenbank ist gerade nicht erreichbar (z.&nbsp;B. direkt nach
 einem Neustart). Diese Seite lädt sich automatisch neu, sobald alles
 bereit ist – bitte einen Moment warten.</p>
 <p><small>Kein Eingreifen nötig.</small></p>
 <script src="/brand/dorfkern-logo.js" defer></script>
</div></body></html>"""


def _warte_response() -> Response:
    """Freundliche Warteantwort: JSON-503 fuer API, sonst HTML-200."""
    accept = request.headers.get('Accept', '') or ''
    if request.path.startswith('/api/') or 'application/json' in accept:
        r = jsonify(ok=False,
                    msg='Datenbank nicht erreichbar — bitte kurz warten.')
        r.status_code = 503
        return r
    # HTTP 200 (kein Browser-Fehler-UI); meta-refresh holt selbst nach.
    return Response(_WARTE_HTML, status=200, mimetype='text/html')


def install_db_gate(app, extra_whitelist: Iterable[str] = ()) -> None:
    """Registriert das DB-Gate als ERSTEN ``before_request`` von ``app``.

    Muss VOR dem Permission-Guard registriert werden (Flask fuehrt
    ``before_request`` in Registrierungsreihenfolge aus) — daher direkt
    nach ``app = Flask(...)`` aufrufen.
    """
    whitelist = tuple(_DEFAULT_WHITELIST) + tuple(extra_whitelist)

    @app.before_request
    def _db_gate():  # noqa: ANN202 - Flask-Hook
        path = request.path or ''
        if any(path.startswith(w) for w in whitelist):
            return None
        if _db_erreichbar():
            return None
        return _warte_response()
