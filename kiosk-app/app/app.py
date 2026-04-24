"""
Bäckerei Kiosk – Flask-Hauptanwendung
Starten: cd app && python3 app.py
"""

from flask import Flask, render_template, request, jsonify, redirect, url_for, session, send_from_directory
from jinja2 import ChoiceLoader, FileSystemLoader
from datetime import datetime, timedelta, date
import base64
import os
import subprocess
import sys
import threading
import time
import config
import db
from db import get_db, get_db_transaction, cent_zu_euro_str
from common.auth import (login_required as _login_required, login_user,
                         logout_user, mitarbeiter_login_karte)
from functools import wraps
import ean as ean_modul
import druck
import mittagstisch as mt

app = Flask(__name__)
app.secret_key = config.SECRET_KEY

# Zusaetzliche Template-Quelle: common/templates/ fuer gemeinsame Bausteine
# (Navbar, Toast, Touch-Widgets, Login-Shell). Wird mit App-eigenen Templates
# ueber ChoiceLoader kombiniert (App-Templates haben Vorrang).
_COMMON_TEMPLATES = os.path.normpath(
    os.path.join(os.path.dirname(__file__), '..', '..', 'common', 'templates')
)
app.jinja_loader = ChoiceLoader([
    app.jinja_loader,
    FileSystemLoader(_COMMON_TEMPLATES),
])


@app.context_processor
def _inject_globals():
    """Stellt terminal_nr und update_verfuegbar in allen Templates bereit."""
    tnr = get_terminal_nr()
    kasse_url = config.KASSE_URL or (
        f'{request.scheme}://{request.host.split(":")[0]}:{config.KASSE_PORT}'
        if config.KASSE_PORT else '')
    orga_url = config.ORGA_URL or (
        f'{request.scheme}://{request.host.split(":")[0]}:{config.ORGA_PORT}'
        if config.ORGA_PORT else '')
    admin_url = config.ADMIN_URL or (
        f'{request.scheme}://{request.host.split(":")[0]}:{config.ADMIN_PORT}'
        if config.ADMIN_PORT else '')
    # Feature-Gating (Phase 7): deaktivierte Apps aus Switcher ausblenden.
    try:
        from common import aktivierung as _akt
        if not _akt.ist_aktiv('KASSE'): kasse_url = ''
        if not _akt.ist_aktiv('ORGA'):  orga_url  = ''
    except Exception:
        pass
    return {
        "terminal_nr":        tnr,
        "ist_kundenterminal": (tnr == 9),
        "kunden_name":        session.get('kunden_name', ''),
        "kunde_eingeloggt":   bool(session.get('kunden_kontakt_id')),
        "update_verfuegbar":  _update_status["verfuegbar"],
        "firma_name":         config.FIRMA_NAME,
        "db_name":            config.DB_NAME,
        "ma_login_name":      session.get('login_name', ''),
        "kasse_url":          kasse_url,
        "orga_url":           orga_url,
        "admin_url":          admin_url,
        "git_commit_short":   GIT_COMMIT_SHORT,
    }


# Verzeichnis für Produktbilder (app/produktbilder/<id>.jpg)
PRODUKTBILDER_DIR = os.path.join(os.path.dirname(__file__), "produktbilder")


# ── GitHub-Update-Prüfung ─────────────────────────────────────

def _find_git_root() -> str | None:
    """Sucht das .git-Verzeichnis/-Datei ab app/ aufwärts (max. 6 Ebenen).
    Unterstützt normale Repos und Git-Worktrees (.git als Datei)."""
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(6):
        git_path = os.path.join(d, ".git")
        if os.path.isdir(git_path) or os.path.isfile(git_path):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return None

GIT_ROOT = _find_git_root()

_update_status: dict = {
    "verfuegbar":    False,
    "local_hash":    None,
    "local_short":   None,
    "local_msg":     None,
    "remote_hash":   None,
    "letzter_check": None,
    "fehler":        None,
}

def _git(args: list[str], timeout: int = 25) -> str:
    """Führt einen git-Befehl in GIT_ROOT aus und gibt stdout zurück."""
    if not GIT_ROOT:
        raise RuntimeError("Kein Git-Repository gefunden")
    r = subprocess.run(
        ["git"] + args,
        cwd=GIT_ROOT, capture_output=True, text=True, timeout=timeout,
    )
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or r.stdout.strip() or f"exit {r.returncode}")
    return r.stdout.strip()


try:
    GIT_COMMIT_SHORT = _git(["rev-parse", "--short", "HEAD"]) if GIT_ROOT else ""
except Exception:
    GIT_COMMIT_SHORT = ""


def _pruefe_update_loop():
    """Hintergrund-Daemon: prüft alle 10 Minuten auf neue Commits in origin/master."""
    while True:
        try:
            _git(["fetch", "origin", "master"])
            ahead  = int(_git(["rev-list", "--count", "HEAD..origin/master"]))
            local  = _git(["rev-parse", "HEAD"])
            remote = _git(["rev-parse", "origin/master"])
            info   = _git(["log", "-1", "--format=%h|%s", "HEAD"]).split("|", 1)
            _update_status.update({
                "verfuegbar":    ahead > 0,
                "local_hash":    local,
                "local_short":   info[0] if info else local[:7],
                "local_msg":     info[1] if len(info) > 1 else "",
                "remote_hash":   remote,
                "letzter_check": datetime.now().strftime("%H:%M"),
                "fehler":        None,
            })
        except Exception as exc:
            _update_status["fehler"] = str(exc)
            _update_status["letzter_check"] = datetime.now().strftime("%H:%M")
        time.sleep(600)   # 10 Minuten

# Daemon-Thread startet sofort (funktioniert auch unter gunicorn)
threading.Thread(target=_pruefe_update_loop, daemon=True, name="update-checker").start()


# ── Einstellungen (XT_EINSTELLUNGEN) ─────────────────────────

def _einstellung_lesen(cursor, schluessel: str, default: bool = True) -> bool:
    """Liest einen booleschen Schalter aus XT_EINSTELLUNGEN."""
    try:
        cursor.execute(
            "SELECT wert FROM XT_EINSTELLUNGEN WHERE schluessel=%s",
            (schluessel,)
        )
        row = cursor.fetchone()
        return row['wert'] == '1' if row else default
    except Exception:
        return default


# ── Terminal-Nr aus Cookie ───────────────────────────────────

def get_terminal_nr() -> int:
    """
    Liest Terminal-Nr aus Cookie 'kiosk_terminal'.
    Fallback auf config.TERMINAL_NR wenn kein Cookie gesetzt.
    Gueltig: 1-9.
    """
    try:
        val = int(request.cookies.get('kiosk_terminal', str(config.TERMINAL_NR)))
        if 1 <= val <= 9:
            return val
    except (ValueError, TypeError):
        pass
    return config.TERMINAL_NR


# ── Caches ────────────────────────────────────────────────────

# Bild-Cache: beim ersten Aufruf alle vorhandenen Bilder einlesen,
# danach kein os.path.exists() mehr pro Produkt nötig.
# Wird einmalig beim Start befüllt und bei Bedarf manuell geleert.
_bild_cache: dict[int, str | None] = {}
_bild_cache_gebaut = False

def _bild_cache_aufbauen():
    """Liest produktbilder/ einmalig ein und baut den Cache auf."""
    global _bild_cache, _bild_cache_gebaut
    _bild_cache.clear()
    if os.path.isdir(PRODUKTBILDER_DIR):
        for datei in os.listdir(PRODUKTBILDER_DIR):
            name, _, ext = datei.rpartition(".")
            if name.isdigit() and ext.lower() in ("jpg", "jpeg", "png", "webp"):
                _bild_cache[int(name)] = f"/produktbilder/{datei}"
    _bild_cache_gebaut = True

def bild_url(produkt_id: int) -> str | None:
    """Gibt gecachte Bild-URL zurück, oder None."""
    if not _bild_cache_gebaut:
        _bild_cache_aufbauen()
    return _bild_cache.get(produkt_id)


# Produkt-Cache: XT_KIOSK_V_PRODUKTE ist teuer (Cross-DB-Join über WAN).
# 30 Sekunden TTL – reicht für den Kiosk-Betrieb.
_produkt_cache: list | None = None
_produkt_cache_ablauf: float = 0.0
PRODUKT_CACHE_TTL = 30  # Sekunden

def _produkte_laden() -> list:
    """Lädt Produkte aus DB oder aus Cache."""
    global _produkt_cache, _produkt_cache_ablauf
    jetzt = time.monotonic()
    if _produkt_cache is not None and jetzt < _produkt_cache_ablauf:
        return _produkt_cache
    with get_db() as cursor:
        cursor.execute("SELECT * FROM XT_KIOSK_V_PRODUKTE")
        rows = cursor.fetchall()
    _produkt_cache = rows
    _produkt_cache_ablauf = jetzt + PRODUKT_CACHE_TTL
    return rows

def produkt_cache_leeren():
    """Manuell aufrufen wenn Artikel-Admin Änderungen gespeichert hat."""
    global _produkt_cache
    _produkt_cache = None


# ── Produktbilder ─────────────────────────────────────────────

@app.route("/produktbilder/<path:dateiname>")
def produktbild(dateiname):
    """Liefert Produktbilder aus app/produktbilder/."""
    return send_from_directory(PRODUKTBILDER_DIR, dateiname)


# ── Hilfsfunktionen ───────────────────────────────────────────

def aktueller_warenkorb_id():
    with get_db() as cursor:
        cursor.execute(
            "SELECT id FROM XT_KIOSK_WARENKOERBE WHERE status='offen' AND gesperrt_von=%s",
            (get_terminal_nr(),)
        )
        row = cursor.fetchone()
        return row["id"] if row else None


def neuer_warenkorb():
    with get_db() as cursor:
        tnr = get_terminal_nr()
        cursor.execute(
            """INSERT INTO XT_KIOSK_WARENKOERBE
               (status, gesamtbetrag_cent, gesperrt_von, gesperrt_am, erstellt_von)
               VALUES ('offen', 0, %s, NOW(), %s)""",
            (tnr, tnr)
        )
        return cursor.lastrowid


def gesamtbetrag_aktualisieren(cursor, warenkorb_id):
    cursor.execute(
        """UPDATE XT_KIOSK_WARENKOERBE
           SET gesamtbetrag_cent = (
               SELECT COALESCE(SUM(zeilen_betrag_cent), 0)
               FROM XT_KIOSK_WARENKORB_POS WHERE warenkorb_id = %s
           ),
           geaendert_am = NOW()
           WHERE id = %s""",
        (warenkorb_id, warenkorb_id)
    )


# ── Login / Logout ────────────────────────────────────────────

@app.get('/login')
def login():
    return render_template('login.html')


def _login_erfolg_redirect():
    """Redirect nach erfolgreichem Login. Auf Terminal 9 → Terminal auf 8 setzen."""
    if ist_kundenterminal():
        resp = redirect(url_for('index'))
        resp.set_cookie(
            "kiosk_terminal", "8",
            max_age=365 * 24 * 3600, path="/", samesite="Lax",
        )
        return resp
    return redirect(url_for('index'))


@app.post('/login')
def login_post():
    login_name = request.form.get('login_name', '').strip()
    passwort   = request.form.get('passwort', '')
    from common.auth import mitarbeiter_login
    ma = mitarbeiter_login(login_name, passwort)
    if ma:
        login_user(ma)
        return _login_erfolg_redirect()
    return render_template('login.html', fehler='Ungültige Zugangsdaten.')


@app.post('/login/karte')
def login_karte():
    """Login per Mitarbeiter-Karte (Barcode-Scan)."""
    guid = request.form.get('guid', '').strip()
    if not guid:
        return render_template('login.html', fehler='Kein Barcode erkannt.')
    ma = mitarbeiter_login_karte(guid)
    if ma:
        login_user(ma)
        return _login_erfolg_redirect()
    return render_template('login.html',
                           fehler='Karte nicht erkannt oder keine Mitarbeiterkarte.')


@app.get('/logout')
def logout():
    logout_user()
    return redirect(url_for('login'))


# ── Terminal 9: Kundenterminal ──────────────────────────────────

def ist_kundenterminal() -> bool:
    """Prüft ob das aktuelle Terminal ein Kundenterminal (Terminal 9) ist."""
    return get_terminal_nr() == 9


def _kunde_eingeloggt() -> bool:
    """Prüft ob ein Kunde per Kundenkarte eingeloggt ist."""
    return bool(session.get('kunden_kontakt_id'))


def _kunden_kontakt_id() -> int | None:
    """Gibt die kontakt_id des eingeloggten Kunden zurück."""
    return session.get('kunden_kontakt_id')


def _kunden_session_required(f):
    """Decorator: erfordert Kunden-Session auf Terminal 9."""
    @wraps(f)
    def _wrapper(*args, **kwargs):
        if ist_kundenterminal() and not _kunde_eingeloggt():
            return redirect(url_for('kunden_scan'))
        return f(*args, **kwargs)
    return _wrapper


def _kunde_per_karte(guid: str) -> dict | None:
    """Löst eine Kundenkarte (KARTEN.TYP='K') auf.

    Returns:
        dict mit id (ADRESSEN.REC_ID), kunnum, name, telefon oder None.
    """
    with get_db() as cur:
        cur.execute(
            """SELECT a.REC_ID AS id, a.KUNNUM1 AS kunnum,
                      CONCAT(IFNULL(a.NAME1,''), ' ', IFNULL(a.NAME2,'')) AS name,
                      IFNULL(a.TELE1, '') AS telefon
               FROM KARTEN k
               JOIN ADRESSEN a ON a.REC_ID = k.ID
               WHERE k.GUID = %s AND k.TYP = 'K'""",
            (guid,)
        )
        return cur.fetchone()


def _kontakt_fuer_kunde(adr_id: int, name: str, telefon: str) -> int:
    """Findet oder erstellt einen XT_KIOSK_KONTAKTE-Eintrag für einen CAO-Kunden.

    Sucht zuerst nach adr_id-Verknüpfung, dann nach Name/Telefon.
    """
    with get_db() as cur:
        # Erst nach adr_id suchen
        cur.execute("SELECT id FROM XT_KIOSK_KONTAKTE WHERE adr_id=%s", (adr_id,))
        row = cur.fetchone()
        if row:
            return row["id"]
        # Dann nach Name/Telefon
        tel = (telefon or "").strip()
        name_clean = name.strip()
        cur.execute(
            "SELECT id FROM XT_KIOSK_KONTAKTE WHERE name=%s AND telefon=%s",
            (name_clean, tel)
        )
        row = cur.fetchone()
        if row:
            # adr_id nachpflegen
            cur.execute(
                "UPDATE XT_KIOSK_KONTAKTE SET adr_id=%s WHERE id=%s",
                (adr_id, row["id"])
            )
            return row["id"]
        # Neu anlegen
        cur.execute(
            "INSERT INTO XT_KIOSK_KONTAKTE (name, telefon, adr_id) VALUES (%s, %s, %s)",
            (name_clean, tel, adr_id)
        )
        return cur.lastrowid


@_login_required
@app.route("/kunden-scan")
def kunden_scan():
    """Karten-Scan-Screen für Terminal 9 (Kundenterminal)."""
    if not ist_kundenterminal():
        return redirect(url_for('index'))
    return render_template("kunden_scan.html")


@_login_required
@app.route("/api/kundenkarte/scan", methods=["POST"])
def api_kundenkarte_scan():
    """Löst einen Kundenkarten-Barcode auf und startet die Kunden-Session."""
    data = request.get_json(force=True) or {}
    barcode = (data.get("barcode") or "").strip()
    if not barcode:
        return jsonify({"ok": False, "fehler": "Kein Barcode gescannt"})

    kunde = _kunde_per_karte(barcode)
    if not kunde:
        return jsonify({"ok": False, "fehler": "Kundenkarte nicht erkannt"})

    kontakt_id = _kontakt_fuer_kunde(
        kunde["id"], kunde["name"], kunde["telefon"]
    )
    session['kunden_kontakt_id'] = kontakt_id
    session['kunden_name'] = kunde["name"].strip()
    session['kunden_adr_id'] = kunde["id"]

    return jsonify({
        "ok": True,
        "name": kunde["name"].strip(),
        "kontakt_id": kontakt_id,
    })


@_login_required
@app.route("/kunden-abmelden")
def kunden_abmelden():
    """Beendet die Kunden-Session (nicht den Mitarbeiter-Login)."""
    session.pop('kunden_kontakt_id', None)
    session.pop('kunden_name', None)
    session.pop('kunden_adr_id', None)
    return redirect(url_for('kunden_scan'))


# ── Meine Bestellungen (Terminal 9 – Kunden-Selbstbedienung) ──

@_login_required
@app.route("/meine-bestellungen")
def meine_bestellungen_view():
    """Kunden-Bestellungsübersicht (nur eigene, gefiltert nach kontakt_id)."""
    if not ist_kundenterminal():
        return redirect(url_for('bestellungen_view'))
    if not _kunde_eingeloggt():
        return redirect(url_for('kunden_scan'))

    kontakt_id = _kunden_kontakt_id()
    with get_db() as cursor:
        cursor.execute(
            """SELECT b.*,
                      GROUP_CONCAT(CONCAT(bp.menge,'x ',bp.name_snapshot)
                                   ORDER BY bp.id SEPARATOR ', ') AS artikel_kurz,
                      COUNT(bp.id) AS pos_anzahl
               FROM XT_KIOSK_BESTELLUNGEN b
               LEFT JOIN XT_KIOSK_BESTELL_POS bp ON bp.bestell_id = b.id
               WHERE b.kontakt_id = %s AND b.status != 'storniert'
               GROUP BY b.id
               ORDER BY b.erstellt_am DESC""",
            (kontakt_id,)
        )
        bestellungen = cursor.fetchall()

    return render_template(
        "meine_bestellungen.html",
        bestellungen=bestellungen,
        kunden_name=session.get('kunden_name', ''),
        terminal_nr=get_terminal_nr(),
    )


@_login_required
@app.route("/meine-bestellungen/neu")
def meine_bestellung_neu_view():
    """Neue Bestellung anlegen (Terminal 9 – Kunden-Selbstbedienung)."""
    if not ist_kundenterminal() or not _kunde_eingeloggt():
        return redirect(url_for('kunden_scan'))
    return render_template(
        "meine_bestellung_neu.html",
        kunden_name=session.get('kunden_name', ''),
        terminal_nr=get_terminal_nr(),
    )


@_login_required
@app.route("/meine-bestellungen/<int:bestell_id>")
def meine_bestellung_detail_view(bestell_id):
    """Bestelldetail (Terminal 9 – nur eigene Bestellungen)."""
    if not ist_kundenterminal() or not _kunde_eingeloggt():
        return redirect(url_for('kunden_scan'))

    kontakt_id = _kunden_kontakt_id()
    with get_db() as cursor:
        cursor.execute(
            "SELECT * FROM XT_KIOSK_BESTELLUNGEN WHERE id=%s AND kontakt_id=%s",
            (bestell_id, kontakt_id)
        )
        bestellung = cursor.fetchone()
        if not bestellung:
            return "Bestellung nicht gefunden", 404
        cursor.execute(
            "SELECT * FROM XT_KIOSK_BESTELL_POS WHERE bestell_id=%s ORDER BY id",
            (bestell_id,)
        )
        positionen = cursor.fetchall()

    return render_template(
        "meine_bestellung_detail.html",
        bestellung=bestellung,
        positionen=positionen,
        kunden_name=session.get('kunden_name', ''),
        terminal_nr=get_terminal_nr(),
    )


@_login_required
@app.route("/api/meine-bestellungen/neu", methods=["POST"])
def api_meine_bestellung_neu():
    """Neue Bestellung anlegen (Terminal 9 – Kunden-Selbstbedienung).

    Name/Telefon kommen aus der Kunden-Session.
    Zahlungsart ist immer 'abholung' (Kunde kann nicht 'sofort' zahlen am Terminal).
    """
    if not ist_kundenterminal() or not _kunde_eingeloggt():
        return jsonify({"ok": False, "fehler": "Nicht angemeldet"}), 401

    kontakt_id = _kunden_kontakt_id()
    data = request.get_json(force=True)
    positionen = data.get("positionen", [])
    if not positionen:
        return jsonify({"ok": False, "fehler": "Mindestens ein Artikel erforderlich"})

    typ = data.get("typ", "einmalig")
    if typ == "einmalig" and not data.get("abhol_datum"):
        return jsonify({"ok": False, "fehler": "Abholdatum fehlt"})
    if typ == "wiederkehrend" and not data.get("wochentag"):
        return jsonify({"ok": False, "fehler": "Wochentag fehlt"})

    kunden_name = session.get('kunden_name', '')
    with get_db() as cur:
        cur.execute("SELECT telefon FROM XT_KIOSK_KONTAKTE WHERE id=%s", (kontakt_id,))
        k_row = cur.fetchone()
    telefon = k_row["telefon"] if k_row else ""

    total_cent = sum(int(p["menge"]) * int(p["preis_cent"]) for p in positionen)
    try:
        ean_code = ean_modul.generiere_ean(total_cent)
    except ValueError as e:
        return jsonify({"ok": False, "fehler": str(e)})

    jetzt = datetime.now()

    try:
        with get_db_transaction() as cursor:
            cursor.execute(
                """INSERT INTO XT_KIOSK_BESTELLUNGEN
                       (bestell_nr, name, telefon, typ, abhol_datum, wochentag,
                        start_datum, end_datum, abhol_uhrzeit, notiz, kanal,
                        zahlungsart, ean_barcode, kontakt_id)
                   VALUES ('', %s, %s, %s, %s, %s, %s, %s, %s, %s, 'terminal', 'abholung', %s, %s)""",
                (
                    kunden_name, telefon, typ,
                    data.get("abhol_datum") or None,
                    data.get("wochentag") or None,
                    data.get("start_datum") or None,
                    data.get("end_datum") or None,
                    data.get("abhol_uhrzeit") or None,
                    data.get("notiz") or None,
                    ean_code, kontakt_id,
                ),
            )
            bestell_id = cursor.lastrowid
            bestell_nr = f"B-{jetzt.year}-{bestell_id:04d}"
            cursor.execute(
                "UPDATE XT_KIOSK_BESTELLUNGEN SET bestell_nr=%s WHERE id=%s",
                (bestell_nr, bestell_id),
            )
            for pos in positionen:
                cursor.execute(
                    """INSERT INTO XT_KIOSK_BESTELL_POS
                           (bestell_id, produkt_id, name_snapshot, preis_cent, menge)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (bestell_id, pos["produkt_id"], pos["name"],
                     pos["preis_cent"], pos["menge"]),
                )
    except Exception as e:
        app.logger.error(f"Kunden-Bestellung neu: {e}")
        return jsonify({"ok": False, "fehler": str(e)}), 500

    return jsonify({
        "ok": True, "id": bestell_id, "bestell_nr": bestell_nr,
    })


@_login_required
@app.route("/api/meine-bestellungen/<int:bestell_id>/stornieren", methods=["POST"])
def api_meine_bestellung_stornieren(bestell_id):
    """Kunden-Storno (Terminal 9 – nur eigene Bestellungen)."""
    if not ist_kundenterminal() or not _kunde_eingeloggt():
        return jsonify({"ok": False, "fehler": "Nicht angemeldet"}), 401

    kontakt_id = _kunden_kontakt_id()
    try:
        with get_db() as cursor:
            cursor.execute(
                """SELECT id FROM XT_KIOSK_BESTELLUNGEN
                   WHERE id=%s AND kontakt_id=%s AND status != 'storniert'""",
                (bestell_id, kontakt_id)
            )
            if not cursor.fetchone():
                return jsonify({"ok": False, "fehler": "Nicht gefunden oder keine Berechtigung"}), 404
            cursor.execute(
                "UPDATE XT_KIOSK_BESTELLUNGEN SET status='storniert' WHERE id=%s",
                (bestell_id,),
            )
    except Exception as e:
        return jsonify({"ok": False, "fehler": str(e)}), 500

    return jsonify({"ok": True})


# ── Kiosk-Hauptansicht ────────────────────────────────────────

@app.route("/")
@_login_required
def index():
    # Terminal 9 (Kundenterminal) → Kunden-Scan / Meine Bestellungen
    if ist_kundenterminal():
        if _kunde_eingeloggt():
            return redirect(url_for('meine_bestellungen_view'))
        return redirect(url_for('kunden_scan'))

    wk_id = aktueller_warenkorb_id()
    if not wk_id:
        wk_id = neuer_warenkorb()

    # Produkte aus Cache (spart Cross-DB-Query über WAN)
    produkte = _produkte_laden()

    kategorien = {}
    for p in produkte:
        k = p["kategorie_name"]
        if k not in kategorien:
            kategorien[k] = {"sort": p["kategorie_sort"], "artikel": []}
        artikel = dict(p)
        artikel["bild_pfad"] = bild_url(p["id"]) or p.get("bild_pfad")
        kategorien[k]["artikel"].append(artikel)
    kategorien_sorted = sorted(kategorien.items(), key=lambda x: x[1]["sort"])

    # Warenkorb + Positionen + Parken-Einstellung in einer Verbindung holen
    with get_db() as cursor:
        cursor.execute("SELECT * FROM XT_KIOSK_WARENKOERBE WHERE id=%s", (wk_id,))
        warenkorb = cursor.fetchone()
        cursor.execute(
            "SELECT * FROM XT_KIOSK_WARENKORB_POS WHERE warenkorb_id=%s ORDER BY id",
            (wk_id,)
        )
        positionen = cursor.fetchall()
        parken_aktiv = _einstellung_lesen(cursor, 'kiosk_parken_aktiv')

    return render_template(
        "kiosk.html",
        kategorien=kategorien_sorted,
        warenkorb=warenkorb,
        positionen=positionen,
        cent_zu_euro=cent_zu_euro_str,
        terminal_nr=get_terminal_nr(),
        parken_aktiv=parken_aktiv,
    )


# ── Warenkorb-API ─────────────────────────────────────────────

@_login_required
@app.route("/warenkorb/neu", methods=["POST"])
def warenkorb_neu():
    wk_id = neuer_warenkorb()
    return jsonify({"ok": True, "warenkorb_id": wk_id})


@_login_required
@app.route("/warenkorb/<int:wk_id>/positionen")
def XT_KIOSK_WARENKORB_POS(wk_id):
    with get_db() as cursor:
        cursor.execute(
            "SELECT * FROM XT_KIOSK_WARENKORB_POS WHERE warenkorb_id=%s ORDER BY id",
            (wk_id,)
        )
        positionen = cursor.fetchall()
        cursor.execute("SELECT gesamtbetrag_cent FROM XT_KIOSK_WARENKOERBE WHERE id=%s", (wk_id,))
        wk = cursor.fetchone()
    return jsonify({
        "ok": True,
        "positionen": positionen,
        "gesamtbetrag_cent": wk["gesamtbetrag_cent"] if wk else 0,
    })


@_login_required
@app.route("/warenkorb/<int:wk_id>/position", methods=["POST"])
def position_hinzufuegen(wk_id):
    produkt_id = request.get_json(force=True).get("produkt_id")
    with get_db() as cursor:
        cursor.execute(
            "SELECT id, name, preis_cent FROM XT_KIOSK_V_PRODUKTE WHERE id=%s",
            (produkt_id,)
        )
        produkt = cursor.fetchone()
        if not produkt:
            return jsonify({"ok": False, "fehler": "Produkt nicht gefunden"}), 404

        # Sicherstellen dass ein produkte-Eintrag existiert (FK-Constraint).
        cursor.execute(
            """INSERT IGNORE INTO XT_KIOSK_PRODUKTE (id, kategorie_id, einheit, wochentage, aktiv)
               VALUES (%s, NULL, 'Stck.', '', 1)""",
            (produkt_id,)
        )

        cursor.execute(
            "SELECT id, menge FROM XT_KIOSK_WARENKORB_POS WHERE warenkorb_id=%s AND produkt_id=%s",
            (wk_id, produkt_id)
        )
        pos = cursor.fetchone()

        if pos:
            neue_menge = pos["menge"] + 1
            cursor.execute(
                "UPDATE XT_KIOSK_WARENKORB_POS SET menge=%s, zeilen_betrag_cent=%s WHERE id=%s",
                (neue_menge, neue_menge * produkt["preis_cent"], pos["id"])
            )
        else:
            cursor.execute(
                """INSERT INTO XT_KIOSK_WARENKORB_POS
                   (warenkorb_id, produkt_id, name_snapshot,
                    preis_snapshot_cent, menge, zeilen_betrag_cent)
                   VALUES (%s, %s, %s, %s, 1, %s)""",
                (wk_id, produkt_id, produkt["name"],
                 produkt["preis_cent"], produkt["preis_cent"])
            )

        gesamtbetrag_aktualisieren(cursor, wk_id)
        cursor.execute("SELECT gesamtbetrag_cent FROM XT_KIOSK_WARENKOERBE WHERE id=%s", (wk_id,))
        wk = cursor.fetchone()

    return jsonify({"ok": True, "gesamtbetrag_cent": wk["gesamtbetrag_cent"]})


@_login_required
@app.route("/warenkorb/<int:wk_id>/position/<int:pos_id>/menge", methods=["POST"])
def menge_setzen(wk_id, pos_id):
    menge = int(request.get_json(force=True).get("menge", 0))
    with get_db() as cursor:
        if menge <= 0:
            cursor.execute(
                "DELETE FROM XT_KIOSK_WARENKORB_POS WHERE id=%s AND warenkorb_id=%s",
                (pos_id, wk_id)
            )
        else:
            cursor.execute(
                """UPDATE XT_KIOSK_WARENKORB_POS
                   SET menge=%s, zeilen_betrag_cent=%s * preis_snapshot_cent
                   WHERE id=%s AND warenkorb_id=%s""",
                (menge, menge, pos_id, wk_id)
            )
        gesamtbetrag_aktualisieren(cursor, wk_id)
        cursor.execute("SELECT gesamtbetrag_cent FROM XT_KIOSK_WARENKOERBE WHERE id=%s", (wk_id,))
        wk = cursor.fetchone()
    return jsonify({"ok": True, "gesamtbetrag_cent": wk["gesamtbetrag_cent"]})


@_login_required
@app.route("/warenkorb/<int:wk_id>/position/<int:pos_id>", methods=["DELETE"])
def position_loeschen(wk_id, pos_id):
    with get_db() as cursor:
        cursor.execute(
            "DELETE FROM XT_KIOSK_WARENKORB_POS WHERE id=%s AND warenkorb_id=%s",
            (pos_id, wk_id)
        )
        gesamtbetrag_aktualisieren(cursor, wk_id)
        cursor.execute("SELECT gesamtbetrag_cent FROM XT_KIOSK_WARENKOERBE WHERE id=%s", (wk_id,))
        wk = cursor.fetchone()
    return jsonify({"ok": True, "gesamtbetrag_cent": wk["gesamtbetrag_cent"]})


@_login_required
@app.route("/warenkorb/<int:wk_id>/parken", methods=["POST"])
def parken(wk_id):
    with get_db() as cursor:
        cursor.execute(
            """UPDATE XT_KIOSK_WARENKOERBE SET status='geparkt', gesperrt_von=NULL,
               gesperrt_am=NULL, geaendert_am=NOW()
               WHERE id=%s AND gesperrt_von=%s""",
            (wk_id, get_terminal_nr())
        )
    return jsonify({"ok": True})


@_login_required
@app.route("/warenkorb/<int:wk_id>/abbrechen", methods=["POST"])
def abbrechen(wk_id):
    with get_db() as cursor:
        cursor.execute(
            """UPDATE XT_KIOSK_WARENKOERBE SET status='abgebrochen', gesperrt_von=NULL,
               gesperrt_am=NULL, geaendert_am=NOW()
               WHERE id=%s AND gesperrt_von=%s""",
            (wk_id, get_terminal_nr())
        )
    return jsonify({"ok": True})


@_login_required
@app.route("/warenkorb/<int:wk_id>/buchen", methods=["POST"])
def buchen(wk_id):
    with get_db() as cursor:
        cursor.execute(
            "SELECT * FROM XT_KIOSK_WARENKOERBE WHERE id=%s AND gesperrt_von=%s",
            (wk_id, get_terminal_nr())
        )
        warenkorb = cursor.fetchone()
        if not warenkorb:
            return jsonify({"ok": False, "fehler": "Warenkorb nicht gefunden"}), 404
        if warenkorb["gesamtbetrag_cent"] <= 0:
            return jsonify({"ok": False, "fehler": "Warenkorb ist leer"}), 400

        cursor.execute(
            "SELECT * FROM XT_KIOSK_WARENKORB_POS WHERE warenkorb_id=%s ORDER BY id",
            (wk_id,)
        )
        positionen = cursor.fetchall()

    try:
        ean_code = ean_modul.generiere_ean(warenkorb["gesamtbetrag_cent"])
    except ValueError as e:
        return jsonify({"ok": False, "fehler": str(e)}), 400

    jetzt = datetime.now()

    tnr = get_terminal_nr()
    bon_text = druck.generiere_bon_text(
        warenkorb_id=wk_id, positionen=positionen,
        gesamtbetrag_cent=warenkorb["gesamtbetrag_cent"],
        ean_barcode=ean_code, terminal_nr=tnr,
        ist_kopie=False, zeitpunkt=jetzt,
    )
    bon_bytes = druck.generiere_bon_bytes(
        warenkorb_id=wk_id, positionen=positionen,
        gesamtbetrag_cent=warenkorb["gesamtbetrag_cent"],
        ean_barcode=ean_code, terminal_nr=tnr,
        ist_kopie=False, zeitpunkt=jetzt,
    )

    try:
        with get_db_transaction() as cursor:
            cursor.execute(
                """INSERT INTO XT_KIOSK_JOURNAL
                   (warenkorb_id, terminal_nr, erstellt_am, gebucht_am,
                    gesamtbetrag_cent, ean_barcode, bon_text, bon_data, status)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'gebucht')""",
                (wk_id, tnr, warenkorb["erstellt_am"], jetzt,
                 warenkorb["gesamtbetrag_cent"], ean_code, bon_text, bon_bytes)
            )
            journal_id = cursor.lastrowid

            for pos in positionen:
                cursor.execute(
                    """INSERT INTO XT_KIOSK_JOURNAL_POS
                       (journal_id, produkt_id, name_snapshot,
                        preis_snapshot_cent, menge, zeilen_betrag_cent)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (journal_id, pos["produkt_id"], pos["name_snapshot"],
                     pos["preis_snapshot_cent"], pos["menge"], pos["zeilen_betrag_cent"])
                )

            cursor.execute(
                """UPDATE XT_KIOSK_WARENKOERBE SET status='abgebrochen', gesperrt_von=NULL,
                   gesperrt_am=NULL, geaendert_am=NOW() WHERE id=%s""",
                (wk_id,)
            )
    except Exception as e:
        app.logger.error(f"Buchen-Fehler Warenkorb {wk_id}: {e}")
        return jsonify({"ok": False, "fehler": str(e)}), 500

    try:
        druck.drucke_bon(
            warenkorb_id=wk_id, positionen=positionen,
            gesamtbetrag_cent=warenkorb["gesamtbetrag_cent"],
            ean_barcode=ean_code, terminal_nr=tnr,
            ist_kopie=False, zeitpunkt=jetzt,
        )
    except Exception as e:
        app.logger.error(f"Druckfehler bei Journal {journal_id}: {e}")

    return jsonify({"ok": True, "journal_id": journal_id, "bon_nr": wk_id, "ean": ean_code})


# ── Offene Warenkörbe ─────────────────────────────────────────

@_login_required
@app.route("/offen")
def offene_warenkoerbe():
    with get_db() as cursor:
        cursor.execute("SELECT * FROM XT_KIOSK_V_OFFENE_WK")
        koerbe = cursor.fetchall()
    return render_template(
        "offen.html", koerbe=koerbe,
        cent_zu_euro=cent_zu_euro_str, terminal_nr=get_terminal_nr(),
    )


@_login_required
@app.route("/offen/<int:wk_id>/uebernehmen", methods=["POST"])
def uebernehmen(wk_id):
    with get_db() as cursor:
        cursor.execute(
            """UPDATE XT_KIOSK_WARENKOERBE SET status='abgebrochen',
               gesperrt_von=NULL, gesperrt_am=NULL
               WHERE gesperrt_von=%s AND status='offen' AND gesamtbetrag_cent=0""",
            (get_terminal_nr(),)
        )
        cursor.execute(
            """UPDATE XT_KIOSK_WARENKOERBE SET status='offen', gesperrt_von=%s,
               gesperrt_am=NOW(), geaendert_am=NOW(), erstellt_von=%s
               WHERE id=%s AND status='geparkt'""",
            (get_terminal_nr(), get_terminal_nr(), wk_id)
        )
    return redirect(url_for("index"))


# ── Journal ───────────────────────────────────────────────────

@_login_required
@app.route("/journal")
def journal():
    with get_db() as cursor:
        cursor.execute("SELECT COUNT(*) AS n FROM XT_KIOSK_V_JOURNAL")
        gesamt = cursor.fetchone()["n"]
        cursor.execute("SELECT * FROM XT_KIOSK_V_JOURNAL LIMIT %s", (100,))
        eintraege = cursor.fetchall()
    return render_template(
        "journal.html", eintraege=eintraege, gesamt=gesamt,
        seite_groesse=100,
        cent_zu_euro=cent_zu_euro_str, terminal_nr=get_terminal_nr(),
    )


@_login_required
@app.route("/journal/mehr")
def journal_mehr():
    """Liefert weitere Journal-Einträge als JSON (für 'Mehr laden'-Button)."""
    offset = int(request.args.get("offset", 0))
    limit  = int(request.args.get("limit", 100))
    with get_db() as cursor:
        cursor.execute(
            "SELECT * FROM XT_KIOSK_V_JOURNAL LIMIT %s OFFSET %s",
            (limit, offset)
        )
        eintraege = cursor.fetchall()
    # datetime-Felder als String serialisieren
    result = []
    for e in eintraege:
        row = dict(e)
        for k, v in row.items():
            if hasattr(v, "strftime"):
                row[k] = v.strftime("%Y-%m-%d %H:%M:%S")
        result.append(row)
    return jsonify({"ok": True, "eintraege": result, "anzahl": len(result)})


@_login_required
@app.route("/journal/<int:journal_id>/positionen")
def XT_KIOSK_JOURNAL_POS(journal_id):
    with get_db() as cursor:
        cursor.execute(
            "SELECT * FROM XT_KIOSK_JOURNAL_POS WHERE journal_id=%s ORDER BY id",
            (journal_id,)
        )
        positionen = cursor.fetchall()
    return jsonify({"ok": True, "positionen": positionen})


@_login_required
@app.route("/journal/<int:journal_id>/bon_data")
def journal_bon_data(journal_id):
    with get_db() as cursor:
        cursor.execute(
            "SELECT bon_data FROM XT_KIOSK_JOURNAL WHERE id=%s", (journal_id,)
        )
        row = cursor.fetchone()
    if not row:
        return jsonify({"ok": False, "fehler": "Nicht gefunden"}), 404
    bon_data = row["bon_data"]
    if bon_data:
        return jsonify({"ok": True, "bon_data_b64": base64.b64encode(bon_data).decode()})
    return jsonify({"ok": True, "bon_data_b64": None})


@_login_required
@app.route("/journal/<int:journal_id>/nachdruck", methods=["POST"])
def nachdruck(journal_id):
    with get_db() as cursor:
        cursor.execute("SELECT * FROM XT_KIOSK_JOURNAL WHERE id=%s", (journal_id,))
        eintrag = cursor.fetchone()
        if not eintrag:
            return jsonify({"ok": False, "fehler": "Nicht gefunden"}), 404
        cursor.execute(
            "SELECT * FROM XT_KIOSK_JOURNAL_POS WHERE journal_id=%s ORDER BY id",
            (journal_id,)
        )
        positionen = cursor.fetchall()

    druck.drucke_bon(
        warenkorb_id=eintrag["warenkorb_id"], positionen=positionen,
        gesamtbetrag_cent=eintrag["gesamtbetrag_cent"],
        ean_barcode=eintrag["ean_barcode"],
        terminal_nr=get_terminal_nr(), ist_kopie=True,
    )
    return jsonify({"ok": True})


@_login_required
@app.route("/journal/<int:journal_id>/stornieren", methods=["POST"])
def stornieren(journal_id):
    with get_db() as cursor:
        cursor.execute(
            """UPDATE XT_KIOSK_JOURNAL SET status='storniert', storniert_am=NOW()
               WHERE id=%s AND status='gebucht'""",
            (journal_id,)
        )
    return jsonify({"ok": True})


# ── Mittagstisch ──────────────────────────────────────────────

@_login_required
@app.route("/mittagstisch")
def mittagstisch_view():
    heute = date.today()
    wochen = []
    for delta in range(3):   # aktuelle, nächste, übernächste Woche
        montag = mt.montag_der_woche(heute) + timedelta(weeks=delta)
        daten  = mt.woche_laden_oder_anlegen(montag)
        wochen.append({
            "montag":   montag.isoformat(),
            "kw_name":  mt.kw_name(montag),
            "kw_nr":    montag.isocalendar()[1],
            "daten":    daten,
        })
    return render_template(
        "mittagstisch.html",
        wochen=wochen,
        terminal_nr=get_terminal_nr(),
    )


@_login_required
@app.route("/mittagstisch/speichern", methods=["POST"])
def mittagstisch_speichern():
    data = request.get_json(force=True)
    try:
        montag = date.fromisoformat(data["montag"])
        mt.woche_speichern(montag, data["daten"])
        return jsonify({"ok": True})
    except Exception as e:
        app.logger.error(f"mittagstisch_speichern: {e}")
        return jsonify({"ok": False, "fehler": str(e)}), 500


# ── Bestellungen ──────────────────────────────────────────────

WOCHENTAG_KUERZEL = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So']

def _heute_wochentag() -> str:
    return WOCHENTAG_KUERZEL[date.today().weekday()]

def _datum_zu_wochentag(d) -> str:
    return WOCHENTAG_KUERZEL[d.weekday()]

# Für die Heute-Ansicht: alle nicht-stornierten heutigen Bestellungen (auch bereits gedruckte)
_HEUTE_SQL = """(
    (b.typ='einmalig' AND b.status != 'storniert' AND b.abhol_datum = CURDATE())
    OR
    (b.typ='wiederkehrend' AND b.status != 'storniert'
     AND NOT (b.pausiert = 1 AND (b.pause_bis IS NULL OR b.pause_bis >= CURDATE()))
     AND b.wochentag = %(wt)s
     AND (b.start_datum IS NULL OR b.start_datum <= CURDATE())
     AND (b.end_datum   IS NULL OR b.end_datum   >= CURDATE()))
)"""

# Für den Badge: nur noch unbearbeitete heutige Bestellungen
_BADGE_SQL = """(
    (b.typ='einmalig' AND b.status='offen' AND b.abhol_datum = CURDATE())
    OR
    (b.typ='wiederkehrend' AND b.status != 'storniert'
     AND NOT (b.pausiert = 1 AND (b.pause_bis IS NULL OR b.pause_bis >= CURDATE()))
     AND b.wochentag = %(wt)s
     AND (b.start_datum IS NULL OR b.start_datum <= CURDATE())
     AND (b.end_datum   IS NULL OR b.end_datum   >= CURDATE())
     AND (b.gedruckt_datum IS NULL OR b.gedruckt_datum < CURDATE()))
)"""

@_login_required
@app.route("/bestellungen")
def bestellungen_view():
    wt = _heute_wochentag()
    with get_db() as cursor:
        cursor.execute(
            """SELECT b.*,
                      GROUP_CONCAT(CONCAT(bp.menge,'x ',bp.name_snapshot)
                                   ORDER BY bp.id SEPARATOR ', ') AS artikel_kurz,
                      COUNT(bp.id) AS pos_anzahl
               FROM XT_KIOSK_BESTELLUNGEN b
               LEFT JOIN XT_KIOSK_BESTELL_POS bp ON bp.bestell_id = b.id
               WHERE """ + _HEUTE_SQL + """
               GROUP BY b.id
               ORDER BY b.abhol_uhrzeit IS NULL, b.abhol_uhrzeit, b.id""",
            {"wt": wt}
        )
        heute = cursor.fetchall()

        cursor.execute(
            """SELECT b.*,
                      GROUP_CONCAT(CONCAT(bp.menge,'x ',bp.name_snapshot)
                                   ORDER BY bp.id SEPARATOR ', ') AS artikel_kurz
               FROM XT_KIOSK_BESTELLUNGEN b
               LEFT JOIN XT_KIOSK_BESTELL_POS bp ON bp.bestell_id = b.id
               WHERE b.status != 'storniert'
               GROUP BY b.id
               ORDER BY b.erstellt_am DESC"""
        )
        alle = cursor.fetchall()

    return render_template(
        "bestellungen.html",
        heute=heute, alle=alle,
        heute_wt=wt,
        heute_datum=date.today(),
        terminal_nr=get_terminal_nr(),
    )


@_login_required
@app.route("/bestellungen/neu")
def bestellung_neu_view():
    return render_template("bestellung_neu.html", terminal_nr=get_terminal_nr())


@_login_required
@app.route("/bestellungen/<int:bestell_id>")
def bestellung_detail_view(bestell_id):
    with get_db() as cursor:
        cursor.execute("SELECT * FROM XT_KIOSK_BESTELLUNGEN WHERE id=%s", (bestell_id,))
        bestellung = cursor.fetchone()
        if not bestellung:
            return "Bestellung nicht gefunden", 404
        cursor.execute(
            "SELECT * FROM XT_KIOSK_BESTELL_POS WHERE bestell_id=%s ORDER BY id",
            (bestell_id,)
        )
        positionen = cursor.fetchall()
    return render_template(
        "bestellung_detail.html",
        bestellung=bestellung,
        positionen=positionen,
        terminal_nr=get_terminal_nr(),
    )


@_login_required
@app.route("/api/bestellungen/badge")
def api_bestellungen_badge():
    wt = _heute_wochentag()
    with get_db() as cursor:
        cursor.execute(
            "SELECT COUNT(*) AS n FROM XT_KIOSK_BESTELLUNGEN b WHERE " + _BADGE_SQL,
            {"wt": wt}
        )
        row = cursor.fetchone()
    return jsonify({"ok": True, "anzahl": row["n"]})


@_login_required
@app.route("/api/offen/badge")
def api_offen_badge():
    with get_db() as cursor:
        cursor.execute("SELECT COUNT(*) AS n FROM XT_KIOSK_WARENKOERBE WHERE status='geparkt'")
        row = cursor.fetchone()
    return jsonify({"ok": True, "anzahl": row["n"]})


@_login_required
@app.route("/api/bestellungen/produkte")
def api_bestellungen_produkte():
    wt = request.args.get("wochentag", "")
    with get_db() as cursor:
        if wt:
            cursor.execute(
                """SELECT id, name, preis_cent, einheit, wochentage,
                          kategorie_name, COALESCE(kategorie_sort, 999) AS kategorie_sort
                   FROM XT_KIOSK_V_PRODUKTE
                   WHERE aktiv > 0
                     AND (wochentage = '' OR FIND_IN_SET(%s, wochentage) > 0)
                   ORDER BY kategorie_sort, name""",
                (wt,)
            )
        else:
            cursor.execute(
                """SELECT id, name, preis_cent, einheit, wochentage,
                          kategorie_name, COALESCE(kategorie_sort, 999) AS kategorie_sort
                   FROM XT_KIOSK_V_PRODUKTE
                   WHERE aktiv > 0
                   ORDER BY kategorie_sort, name"""
            )
        produkte = cursor.fetchall()
    return jsonify({"ok": True, "produkte": produkte})


@_login_required
@app.route("/api/bestellungen/kunden")
def api_bestellungen_kunden():
    """Veraltet – leitet intern auf /api/kontakte weiter."""
    return api_kontakte()


@_login_required
@app.route("/api/kontakte")
def api_kontakte():
    """Autocomplete aus der kontakte-Tabelle."""
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify([])
    try:
        with get_db() as cursor:
            cursor.execute(
                """SELECT name, telefon FROM XT_KIOSK_KONTAKTE
                   WHERE name LIKE %s OR telefon LIKE %s
                   ORDER BY name
                   LIMIT 10""",
                (f"%{q}%", f"%{q}%"),
            )
            rows = cursor.fetchall()
        return jsonify([{"name": r["name"], "telefon": r["telefon"]} for r in rows])
    except Exception:
        return jsonify([])   # Autocomplete schlägt still fehl (Tabelle noch nicht vorhanden)


def _hole_oder_erstelle_kontakt(cursor, name: str, telefon: str) -> int:
    """Sucht einen Kontakt (name, telefon) oder legt ihn neu an. Gibt kontakt_id zurück."""
    tel = (telefon or "").strip()
    cursor.execute("SELECT id FROM XT_KIOSK_KONTAKTE WHERE name=%s AND telefon=%s", (name, tel))
    row = cursor.fetchone()
    if row:
        return row["id"]
    cursor.execute("INSERT INTO XT_KIOSK_KONTAKTE (name, telefon) VALUES (%s, %s)", (name, tel))
    return cursor.lastrowid


@_login_required
@app.route("/api/bestellungen/neu", methods=["POST"])
def api_bestellung_neu():
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "fehler": "Name ist erforderlich"})
    positionen = data.get("positionen", [])
    if not positionen:
        return jsonify({"ok": False, "fehler": "Mindestens ein Artikel erforderlich"})
    typ = data.get("typ", "einmalig")
    zahlungsart = data.get("zahlungsart", "abholung")
    if typ == "einmalig" and not data.get("abhol_datum"):
        return jsonify({"ok": False, "fehler": "Abholdatum fehlt"})
    if typ == "wiederkehrend" and not data.get("wochentag"):
        return jsonify({"ok": False, "fehler": "Wochentag fehlt"})
    if typ == "wiederkehrend" and zahlungsart == "sofort":
        return jsonify({"ok": False, "fehler": "Sofort zahlen ist bei wiederkehrenden Bestellungen nicht möglich"})

    # Gesamtbetrag + EAN vorab berechnen
    total_cent = sum(int(p["menge"]) * int(p["preis_cent"]) for p in positionen)
    try:
        ean_code = ean_modul.generiere_ean(total_cent)
    except ValueError as e:
        return jsonify({"ok": False, "fehler": str(e)})

    jetzt = datetime.now()
    terminal_nr = get_terminal_nr()

    try:
        with get_db_transaction() as cursor:
            cursor.execute(
                """INSERT INTO XT_KIOSK_BESTELLUNGEN
                       (bestell_nr, name, telefon, typ, abhol_datum, wochentag,
                        start_datum, end_datum, abhol_uhrzeit, notiz, kanal,
                        zahlungsart, ean_barcode)
                   VALUES ('', %s, %s, %s, %s, %s, %s, %s, %s, %s, 'kiosk', %s, %s)""",
                (
                    name,
                    data.get("telefon") or None,
                    typ,
                    data.get("abhol_datum") or None,
                    data.get("wochentag") or None,
                    data.get("start_datum") or None,
                    data.get("end_datum") or None,
                    data.get("abhol_uhrzeit") or None,
                    data.get("notiz") or None,
                    zahlungsart,
                    ean_code,
                ),
            )
            bestell_id = cursor.lastrowid
            bestell_nr = f"B-{jetzt.year}-{bestell_id:04d}"
            kontakt_id = _hole_oder_erstelle_kontakt(cursor, name, data.get("telefon") or "")
            cursor.execute(
                "UPDATE XT_KIOSK_BESTELLUNGEN SET bestell_nr=%s, kontakt_id=%s WHERE id=%s",
                (bestell_nr, kontakt_id, bestell_id),
            )
            for pos in positionen:
                cursor.execute(
                    """INSERT INTO XT_KIOSK_BESTELL_POS
                           (bestell_id, produkt_id, name_snapshot, preis_cent, menge)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (bestell_id, pos["produkt_id"], pos["name"],
                     pos["preis_cent"], pos["menge"]),
                )
    except Exception as e:
        app.logger.error(f"Bestellung neu: {e}")
        return jsonify({"ok": False, "fehler": str(e)}), 500

    # ── Sofort zahlen: Kassierbon drucken ────────────────────
    if zahlungsart == "sofort":
        # Phase 1: Bon-Bytes erzeugen + in DB speichern
        try:
            positionen_bon = [
                {
                    "name_snapshot":       p["name"],
                    "preis_snapshot_cent": int(p["preis_cent"]),
                    "menge":               int(p["menge"]),
                    "zeilen_betrag_cent":  int(p["menge"]) * int(p["preis_cent"]),
                }
                for p in positionen
            ]
            bon_bytes = druck.generiere_bon_bytes(
                warenkorb_id=bestell_id,
                positionen=positionen_bon,
                gesamtbetrag_cent=total_cent,
                ean_barcode=ean_code,
                terminal_nr=terminal_nr,
                ist_kopie=False,
                zeitpunkt=jetzt,
                bestell_nr=bestell_nr,
                notiz=data.get("notiz") or None,
            )
            # bon_data immer speichern (auch bei Druckfehler → Nachdruck möglich)
            with get_db() as cursor:
                cursor.execute(
                    "UPDATE XT_KIOSK_BESTELLUNGEN SET bon_data=%s WHERE id=%s",
                    (bon_bytes, bestell_id),
                )
        except Exception as e:
            app.logger.error(f"Bon-Generierung Bestellung {bestell_id}: {e}")
            return jsonify({
                "ok": True, "id": bestell_id, "bestell_nr": bestell_nr,
                "druckfehler": f"Bon-Erstellung fehlgeschlagen: {e}",
            })
        # Phase 2: An Drucker senden
        # Kein status='gedruckt' – der Kassierbon ist kein Ersatz für die Pickliste.
        # Die Bestellung bleibt 'offen' bis die Pickliste aus der Übersicht gedruckt wird.
        try:
            druck._sende_an_drucker(terminal_nr, bon_bytes)
        except Exception as e:
            app.logger.error(f"Sofort-Druck Bestellung {bestell_id}: {e}")
            return jsonify({
                "ok": True, "id": bestell_id, "bestell_nr": bestell_nr,
                "druckfehler": str(e),
            })
        return jsonify({"ok": True, "id": bestell_id, "bestell_nr": bestell_nr})

    # ── Zahlung bei Abholung: Frontend fragt nach Bestätigungsbon ──
    return jsonify({
        "ok": True,
        "id": bestell_id,
        "bestell_nr": bestell_nr,
        "frage_bestaetigung": True,
        "total_cent": total_cent,
    })


@_login_required
@app.route("/api/bestellungen/<int:bestell_id>/speichern", methods=["POST"])
def api_bestellung_speichern(bestell_id):
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "fehler": "Name ist erforderlich"})
    positionen = data.get("positionen", [])
    if not positionen:
        return jsonify({"ok": False, "fehler": "Mindestens ein Artikel erforderlich"})

    terminal_nr = get_terminal_nr()
    neu_gesamt_cent = sum(int(p["menge"]) * int(p["preis_cent"]) for p in positionen)

    try:
        with get_db_transaction() as cursor:
            # ── Alten Zustand vor dem Speichern lesen ──────────────
            cursor.execute("SELECT * FROM XT_KIOSK_BESTELLUNGEN WHERE id=%s", (bestell_id,))
            alt_bestellung = cursor.fetchone()
            if not alt_bestellung:
                return jsonify({"ok": False, "fehler": "Bestellung nicht gefunden"}), 404
            cursor.execute(
                "SELECT * FROM XT_KIOSK_BESTELL_POS WHERE bestell_id=%s ORDER BY id",
                (bestell_id,),
            )
            alt_pos = cursor.fetchall()
            alt_gesamt_cent = sum(p["menge"] * p["preis_cent"] for p in alt_pos)

            # Neues EAN für abholung-Bestellungen aktualisieren
            zahlungsart = alt_bestellung.get("zahlungsart", "abholung")
            neu_ean = alt_bestellung.get("ean_barcode")
            if zahlungsart != "sofort":
                try:
                    neu_ean = ean_modul.generiere_ean(neu_gesamt_cent)
                except Exception:
                    pass  # alten EAN behalten

            kontakt_id = _hole_oder_erstelle_kontakt(cursor, name, data.get("telefon") or "")
            cursor.execute(
                """UPDATE XT_KIOSK_BESTELLUNGEN
                   SET name=%s, telefon=%s, kontakt_id=%s, typ=%s, abhol_datum=%s,
                       wochentag=%s, start_datum=%s, end_datum=%s, abhol_uhrzeit=%s,
                       notiz=%s, ean_barcode=%s
                   WHERE id=%s""",
                (
                    name,
                    data.get("telefon") or None,
                    kontakt_id,
                    data.get("typ", "einmalig"),
                    data.get("abhol_datum") or None,
                    data.get("wochentag") or None,
                    data.get("start_datum") or None,
                    data.get("end_datum") or None,
                    data.get("abhol_uhrzeit") or None,
                    data.get("notiz") or None,
                    neu_ean,
                    bestell_id,
                ),
            )
            cursor.execute(
                "DELETE FROM XT_KIOSK_BESTELL_POS WHERE bestell_id=%s", (bestell_id,)
            )
            for pos in positionen:
                cursor.execute(
                    """INSERT INTO XT_KIOSK_BESTELL_POS
                           (bestell_id, produkt_id, name_snapshot, preis_cent, menge)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (bestell_id, pos["produkt_id"], pos["name"],
                     pos["preis_cent"], pos["menge"]),
                )

            # Neuen Zustand für den Bon laden
            cursor.execute("SELECT * FROM XT_KIOSK_BESTELLUNGEN WHERE id=%s", (bestell_id,))
            neu_bestellung = cursor.fetchone()
            cursor.execute(
                "SELECT * FROM XT_KIOSK_BESTELL_POS WHERE bestell_id=%s ORDER BY id",
                (bestell_id,),
            )
            neu_pos_rows = cursor.fetchall()

    except Exception as e:
        return jsonify({"ok": False, "fehler": str(e)}), 500

    # ── Diff-Liste für den Änderungsbon aufbauen ───────────────
    # Neue und unveränderte Artikel zuerst, dann weggefallene.
    alt_by_pid = {p["produkt_id"]: p for p in alt_pos}
    neu_by_pid = {p["produkt_id"]: p for p in neu_pos_rows}

    druckpositionen = []
    for pos in neu_pos_rows:
        p = dict(pos)
        if pos["produkt_id"] not in alt_by_pid:
            p["_aenderung"] = "neu"
        druckpositionen.append(p)
    for pid, alt_p in alt_by_pid.items():
        if pid not in neu_by_pid:
            p = dict(alt_p)
            p["_orig_menge"] = p["menge"]
            p["menge"] = 0          # kein Beitrag zum Gesamtbetrag
            p["_aenderung"] = "entfernt"
            # Negativer Betrag nur bei sofort-Zahlung (bereits bezahlter Betrag)
            p["_neg_betrag"] = (zahlungsart == "sofort")
            druckpositionen.append(p)

    # ── Bon drucken ────────────────────────────────────────────
    try:
        if zahlungsart == "sofort":
            # Differenz zum bereits gezahlten Betrag
            diff_cent = neu_gesamt_cent - alt_gesamt_cent
            diff_ean = None
            if diff_cent > 0:
                try:
                    diff_ean = ean_modul.generiere_ean(diff_cent)
                except Exception:
                    diff_ean = None
            druck.drucke_pickliste(
                neu_bestellung, druckpositionen, terminal_nr,
                mit_preisen=True,
                ean_barcode=diff_ean,
                titel_ueberschrift="Geaenderte Bestellung",
                aenderung_cent=diff_cent,
            )
        else:
            # abholung: aktualisierter Bon
            # Wiederkehrend → kein Barcode (Zahlung wöchentlich, nicht einmalig),
            # stattdessen "Zahlung bei Abholung: €X" als Hinweis auf neuen Wochenbetrag.
            # Einmalig → EAN-Barcode für die Kasse.
            ist_wiederkehrend = (neu_bestellung.get("typ") == "wiederkehrend")
            druck.drucke_pickliste(
                neu_bestellung, druckpositionen, terminal_nr,
                mit_preisen=True,
                ean_barcode=None if ist_wiederkehrend else neu_bestellung.get("ean_barcode"),
                gesamt_hinweis=neu_gesamt_cent if ist_wiederkehrend else None,
                titel_ueberschrift="Geaenderte Bestellung",
            )
    except Exception as pe:
        app.logger.warning(f"Aenderungsbon Druck fehlgeschlagen: {pe}")

    return jsonify({"ok": True})


@_login_required
@app.route("/api/bestellungen/<int:bestell_id>/stornieren", methods=["POST"])
def api_bestellung_stornieren(bestell_id):
    terminal_nr = get_terminal_nr()
    try:
        with get_db() as cursor:
            cursor.execute("SELECT * FROM XT_KIOSK_BESTELLUNGEN WHERE id=%s", (bestell_id,))
            b_row = cursor.fetchone()
            if not b_row:
                return jsonify({"ok": False, "fehler": "Nicht gefunden"}), 404
            cursor.execute(
                "SELECT * FROM XT_KIOSK_BESTELL_POS WHERE bestell_id=%s ORDER BY id",
                (bestell_id,),
            )
            pos_rows = cursor.fetchall()
            cursor.execute(
                "UPDATE XT_KIOSK_BESTELLUNGEN SET status='storniert' WHERE id=%s AND status != 'storniert'",
                (bestell_id,),
            )
    except Exception as e:
        return jsonify({"ok": False, "fehler": str(e)}), 500

    # Storno-Bon nur bei bereits bezahlten Bestellungen
    if b_row.get("zahlungsart") == "sofort":
        try:
            total_cent = sum(p["menge"] * p["preis_cent"] for p in pos_rows)
            druck.drucke_pickliste(
                b_row, pos_rows, terminal_nr,
                mit_preisen=True,
                titel_ueberschrift="Stornierung",
                aenderung_cent=-total_cent,
            )
        except Exception as pe:
            app.logger.warning(f"Storno-Bon Druck fehlgeschlagen: {pe}")

    return jsonify({"ok": True})


@_login_required
@app.route("/api/bestellungen/<int:bestell_id>/pausieren", methods=["POST"])
def api_bestellung_pausieren(bestell_id):
    """
    body: {"wochen": N}
    N=0 → Toggle unbefristete Pause / Fortsetzen
    N>0 → Pause für N Wochen
    Nur für wiederkehrende Bestellungen. Druckt Bestätigungsbon.
    """
    data = request.get_json(force=True) or {}
    try:
        wochen = int(data.get("wochen", 0))
    except (TypeError, ValueError):
        wochen = 0
    terminal_nr = get_terminal_nr()

    try:
        with get_db() as cursor:
            cursor.execute("SELECT * FROM XT_KIOSK_BESTELLUNGEN WHERE id=%s", (bestell_id,))
            row = cursor.fetchone()
            if not row:
                return jsonify({"ok": False, "fehler": "Nicht gefunden"}), 404
            if row["typ"] != "wiederkehrend":
                return jsonify({"ok": False, "fehler": "Nur für wiederkehrende Bestellungen"}), 400

            if wochen == 0:
                neu_pausiert = 0 if row["pausiert"] else 1
                cursor.execute(
                    "UPDATE XT_KIOSK_BESTELLUNGEN SET pausiert=%s, pause_bis=NULL WHERE id=%s",
                    (neu_pausiert, bestell_id),
                )
                pb = None
                pause_text = "Pausiert (unbefristet)" if neu_pausiert else None
            else:
                cursor.execute(
                    """UPDATE XT_KIOSK_BESTELLUNGEN
                       SET pausiert=1, pause_bis=DATE_ADD(CURDATE(), INTERVAL %s WEEK)
                       WHERE id=%s""",
                    (wochen, bestell_id),
                )
                cursor.execute("SELECT pause_bis FROM XT_KIOSK_BESTELLUNGEN WHERE id=%s", (bestell_id,))
                r = cursor.fetchone()
                pb = r["pause_bis"].strftime('%d.%m.%Y') if r and r["pause_bis"] else None
                pause_text = f"Pausiert bis {pb}" if pb else "Pausiert"
                neu_pausiert = 1

            # Bon drucken (nur beim Pausieren, nicht beim Fortsetzen)
            if pause_text:
                cursor.execute(
                    "SELECT * FROM XT_KIOSK_BESTELL_POS WHERE bestell_id=%s ORDER BY id",
                    (bestell_id,)
                )
                pos_rows = cursor.fetchall()
                cursor.execute("SELECT * FROM XT_KIOSK_BESTELLUNGEN WHERE id=%s", (bestell_id,))
                b_row = cursor.fetchone()
                try:
                    druck.drucke_pickliste(
                        b_row, pos_rows, terminal_nr,
                        mit_preisen=False,
                        pause_hinweis=pause_text,
                    )
                except Exception as pe:
                    app.logger.warning(f"Pausierbon Druck fehlgeschlagen: {pe}")

        return jsonify({"ok": True, "pausiert": bool(neu_pausiert), "pause_bis": pb})
    except Exception as e:
        return jsonify({"ok": False, "fehler": str(e)}), 500


@_login_required
@app.route("/api/bestellungen/drucken", methods=["POST"])
def api_bestellungen_drucken():
    """Druckt Picklisten für 'abholung'-Bestellungen (mit Preisen + EAN)."""
    data = request.get_json(force=True)
    ids = [int(i) for i in (data.get("ids") or [])]
    if not ids:
        return jsonify({"ok": False, "fehler": "Keine IDs angegeben"})

    terminal_nr = get_terminal_nr()
    gedruckt = 0
    fehler_liste = []

    with get_db() as cursor:
        for bid in ids:
            cursor.execute("SELECT * FROM XT_KIOSK_BESTELLUNGEN WHERE id=%s", (bid,))
            b_row = cursor.fetchone()
            if not b_row or b_row["status"] == "storniert":
                continue
            cursor.execute(
                "SELECT * FROM XT_KIOSK_BESTELL_POS WHERE bestell_id=%s ORDER BY id",
                (bid,)
            )
            pos_rows = cursor.fetchall()
            try:
                ist_bezahlt = b_row.get("zahlungsart") == "sofort"
                druck.drucke_pickliste(
                    b_row, pos_rows, terminal_nr,
                    mit_preisen=True,
                    ean_barcode=None if ist_bezahlt else b_row.get("ean_barcode"),
                    bereits_bezahlt=ist_bezahlt,
                )
                if b_row["typ"] == "einmalig" and b_row["status"] == "offen":
                    cursor.execute(
                        "UPDATE XT_KIOSK_BESTELLUNGEN SET status='gedruckt', gedruckt_datum=CURDATE() WHERE id=%s",
                        (bid,)
                    )
                else:
                    cursor.execute(
                        "UPDATE XT_KIOSK_BESTELLUNGEN SET gedruckt_datum=CURDATE() WHERE id=%s",
                        (bid,)
                    )
                gedruckt += 1
            except Exception as e:
                fehler_liste.append(f"#{bid}: {e}")

    if fehler_liste:
        return jsonify({"ok": False, "fehler": "; ".join(fehler_liste)})
    return jsonify({"ok": True, "gedruckt": gedruckt})


@_login_required
@app.route("/api/bestellungen/<int:bestell_id>/nachdruck", methods=["POST"])
def api_bestellung_nachdruck(bestell_id):
    """
    Nachdruck / Bestätigungsbon:
      bestaetigung=True  → Bestätigungsbon für Kunden (ohne Preise, ohne EAN)
      bestaetigung=False → Nachdruck Pickliste (mit Preisen + EAN) oder
                           gespeicherter Kassierbon (bei zahlungsart='sofort')
    """
    data = request.get_json(force=True) or {}
    ist_bestaetigung = bool(data.get("bestaetigung", False))
    terminal_nr = get_terminal_nr()

    try:
        with get_db() as cursor:
            cursor.execute("SELECT * FROM XT_KIOSK_BESTELLUNGEN WHERE id=%s", (bestell_id,))
            b_row = cursor.fetchone()
            if not b_row:
                return jsonify({"ok": False, "fehler": "Nicht gefunden"}), 404
            cursor.execute(
                "SELECT * FROM XT_KIOSK_BESTELL_POS WHERE bestell_id=%s ORDER BY id",
                (bestell_id,)
            )
            pos_rows = cursor.fetchall()

        if ist_bestaetigung:
            # Bestätigungsbon: Artikel ohne Einzelpreise, kein EAN,
            # aber Gesamtbetrag + "Zahlung bei Abholung" am Ende
            gesamt_cent = sum(p["menge"] * p["preis_cent"] for p in pos_rows)
            druck.drucke_pickliste(
                b_row, pos_rows, terminal_nr,
                mit_preisen=False,
                ean_barcode=None,
                gesamt_hinweis=gesamt_cent,
            )
        elif b_row.get("zahlungsart") == "sofort" and b_row.get("bon_data"):
            # Nachdruck des gespeicherten Kassierbons
            druck._sende_an_drucker(terminal_nr, b_row["bon_data"])
        else:
            # Nachdruck Pickliste: mit Preisen + EAN (abholung) oder "Bereits bezahlt" (sofort)
            ist_bezahlt = b_row.get("zahlungsart") == "sofort"
            druck.drucke_pickliste(
                b_row, pos_rows, terminal_nr,
                mit_preisen=True,
                ean_barcode=None if ist_bezahlt else b_row.get("ean_barcode"),
                bereits_bezahlt=ist_bezahlt,
            )
    except Exception as e:
        return jsonify({"ok": False, "fehler": str(e)}), 500

    return jsonify({"ok": True})


# ── Handbuch ──────────────────────────────────────────────────

DOKU_DIR = os.path.join(os.path.dirname(__file__), "..", "doku")


@app.route("/doku/<path:dateiname>")
def doku_datei(dateiname):
    """Statische Dateien aus dem doku/-Verzeichnis (Bilder für Handbuch)."""
    return send_from_directory(os.path.abspath(DOKU_DIR), dateiname)


# ── Gemeinsame Brand-Assets (common/brand/*) ──────────────────
_BRAND_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), '..', '..', 'common', 'brand')
)


@app.route('/brand/<path:dateiname>')
def _brand_asset(dateiname):
    """Liefert Dorfkern-Logo-Assets (dorfkern-logo.js etc.) aus common/brand/."""
    return send_from_directory(_BRAND_DIR, dateiname, max_age=60 * 60 * 24)


@_login_required
@app.route("/handbuch")
def handbuch():
    """
    Mitarbeiter-Handbuch – Terminal-abhängige Darstellung:
      Terminal 1–7 : read-only
      Terminal 8   : bearbeitbar (Superuser)
      Terminal 9   : nur Kapitel 4 – Bestellabwicklung (Kundenterminal)
    """
    terminal_nr = get_terminal_nr()
    pfad = os.path.join(DOKU_DIR, "handbuch.html")
    try:
        with open(pfad, encoding="utf-8") as f:
            html = f.read()
    except FileNotFoundError:
        return "Handbuch nicht gefunden.", 404

    # Terminal-Nr als JS-Variable injizieren – wird vom Handbuch-JS ausgewertet
    inject = f'<script id="terminal-inject">window.TERMINAL_NR = {terminal_nr};</script>\n'
    html = html.replace("</head>", inject + "</head>", 1)
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}


@_login_required
@app.route("/handbuch/speichern", methods=["POST"])
def handbuch_speichern():
    """Speichert das bearbeitete Handbuch. Nur Terminal 8 (Superuser)."""
    if get_terminal_nr() != 8:
        return jsonify({"ok": False, "fehler": "Keine Berechtigung"}), 403
    data = request.get_json(force=True) or {}
    html = data.get("html", "").strip()
    if not html:
        return jsonify({"ok": False, "fehler": "Kein Inhalt"}), 400

    pfad = os.path.join(DOKU_DIR, "handbuch.html")
    backup = pfad + ".bak"
    try:
        if os.path.exists(pfad):
            with open(pfad, "rb") as f_in, open(backup, "wb") as f_bak:
                f_bak.write(f_in.read())
        with open(pfad, "w", encoding="utf-8") as f:
            f.write(html)
    except OSError as e:
        return jsonify({"ok": False, "fehler": str(e)}), 500

    return jsonify({"ok": True})


@_login_required
@app.route("/handbuch/upload", methods=["POST"])
def handbuch_upload():
    """Speichert ein hochgeladenes Bild im doku/-Verzeichnis. Nur Terminal 8."""
    if get_terminal_nr() != 8:
        return jsonify({"ok": False, "fehler": "Keine Berechtigung"}), 403
    data = request.get_json(force=True) or {}
    dateiname = os.path.basename(data.get("filename", ""))
    b64data   = data.get("data", "")
    if not dateiname or not b64data:
        return jsonify({"ok": False, "fehler": "filename oder data fehlt"}), 400
    if "," in b64data:
        b64data = b64data.split(",", 1)[1]
    try:
        bild_bytes = base64.b64decode(b64data)
        ziel = os.path.join(DOKU_DIR, dateiname)
        with open(ziel, "wb") as f:
            f.write(bild_bytes)
    except Exception as e:
        return jsonify({"ok": False, "fehler": str(e)}), 500

    return jsonify({"ok": True, "filename": f"/doku/{dateiname}"})


# ── App-Update (nur Terminal 8) ────────────────────────────────

# Ältester Commit, der die Update-/Rollback-Funktion bereits enthält.
# Rollback auf ältere Versionen wird nicht angeboten.
ROLLBACK_MIN_COMMIT = "abb491c"

def _parse_git_log(raw: str) -> list[dict]:
    ergebnis = []
    for zeile in raw.splitlines():
        teile = zeile.split("|", 3)
        if len(teile) == 4:
            ergebnis.append({
                "hash":  teile[0],
                "short": teile[1],
                "msg":   teile[2],
                "datum": teile[3][:16].replace("T", " ") if "T" in teile[3] else teile[3][:16],
            })
    return ergebnis


@_login_required
@app.route("/update")
def update_seite():
    if get_terminal_nr() != 8:
        return redirect("/")
    commits_neu   = []
    commits_lokal = []
    fehler = _update_status.get("fehler")
    try:
        if _update_status["verfuegbar"]:
            raw = _git(["log", "HEAD..origin/master", "--format=%H|%h|%s|%ai"])
            commits_neu = _parse_git_log(raw)
        # Nur Commits ab dem ersten mit Update-Funktion anzeigen
        raw2 = _git(["log", f"{ROLLBACK_MIN_COMMIT}^..HEAD", "--format=%H|%h|%s|%ai"])
        commits_lokal = _parse_git_log(raw2)
    except Exception as exc:
        fehler = str(exc)
    return render_template(
        "update.html",
        status=_update_status,
        commits_neu=commits_neu,
        commits_lokal=commits_lokal,
        git_verfuegbar=bool(GIT_ROOT),
        fehler=fehler,
    )


@_login_required
@app.route("/api/update/ausfuehren", methods=["POST"])
def api_update_ausfuehren():
    if get_terminal_nr() != 8:
        return jsonify({"ok": False, "fehler": "Keine Berechtigung"}), 403
    try:
        ausgabe = _git(["fetch", "origin", "master"], timeout=60)
        ausgabe += "\n" + _git(["reset", "--hard", "origin/master"], timeout=30)
    except Exception as exc:
        return jsonify({"ok": False, "fehler": str(exc)})

    def _neustart():
        time.sleep(2)
        os.execv(sys.executable, [sys.executable] + sys.argv)

    threading.Thread(target=_neustart, daemon=False).start()
    return jsonify({"ok": True, "ausgabe": ausgabe, "neustart": True})


@_login_required
@app.route("/api/update/rollback/<commit_hash>", methods=["POST"])
def api_update_rollback(commit_hash):
    if get_terminal_nr() != 8:
        return jsonify({"ok": False, "fehler": "Keine Berechtigung"}), 403
    # Sicherheit: nur hex-Zeichen, 7–40 Stellen
    if not all(c in "0123456789abcdefABCDEF" for c in commit_hash) or not (7 <= len(commit_hash) <= 40):
        return jsonify({"ok": False, "fehler": "Ungültiger Commit-Hash"}), 400
    try:
        ausgabe = _git(["reset", "--hard", commit_hash], timeout=30)
    except Exception as exc:
        return jsonify({"ok": False, "fehler": str(exc)})

    def _neustart():
        time.sleep(2)
        os.execv(sys.executable, [sys.executable] + sys.argv)

    threading.Thread(target=_neustart, daemon=False).start()
    return jsonify({"ok": True, "ausgabe": ausgabe, "neustart": True})


# ── Terminal-Einstellung ──────────────────────────────────────

@_login_required
@app.route("/terminal-einstellung")
def terminal_einstellung():
    return render_template("terminal_einstellung.html", terminal_nr=get_terminal_nr())


@_login_required
@app.route("/api/terminal-einstellung", methods=["POST"])
def terminal_einstellung_setzen():
    nr = request.json.get("nr") if request.is_json else None
    try:
        nr = int(nr)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "msg": "Ungültige Terminal-Nr."}), 400
    if nr < 1 or nr > 9:
        return jsonify({"ok": False, "msg": "Terminal-Nr muss 1–9 sein."}), 400
    resp = jsonify({"ok": True, "msg": f"Terminal {nr} gesetzt.", "nr": nr})
    resp.set_cookie(
        "kiosk_terminal", str(nr),
        max_age=365 * 24 * 3600, path="/", samesite="Lax",
    )
    return resp


# ── Stempeluhr (P3) ───────────────────────────────────────────
#
# Oeffentliche Route (kein Login): der Karten-Scan ist die Authentifizierung.
# Kommen/Gehen wird aus dem letzten Stempel des MA abgeleitet (siehe
# modules.orga.personal.models.stempel_naechste_richtung).

@app.route("/stempeluhr")
def stempeluhr():
    """Scan-Screen fuer die Stempeluhr. Public, kein Login.

    Bietet zusaetzlich den Einstieg ins PIN-Self-Service unter /stempeluhr/pin.
    """
    return render_template("stempeluhr.html", terminal_nr=get_terminal_nr())


@app.route("/api/stempeluhr/scan", methods=["POST"])
def api_stempeluhr_scan():
    """Nimmt den gescannten Barcode entgegen und stempelt den MA ein/aus."""
    data = request.get_json(silent=True) or {}
    guid = str(data.get("barcode", "")).strip()
    try:
        from modules.orga.personal.models import stempeln_karte
        ergebnis = stempeln_karte(guid, get_terminal_nr())
    except Exception as exc:
        return jsonify({"ok": False, "fehler": f"Serverfehler: {exc}"}), 500
    if not ergebnis.get("ok"):
        return jsonify({"ok": False, "fehler": ergebnis.get("msg", "Fehler")}), 400
    zeit = ergebnis["zeitpunkt"]
    return jsonify({
        "ok":        True,
        "richtung":  ergebnis["richtung"],
        "vname":     ergebnis["vname"],
        "name":      ergebnis["name"],
        "zeit":      zeit.strftime("%H:%M:%S"),
        "msg":       ergebnis["msg"],
    })


# ── Stempeluhr Self-Service (PIN-Authentifizierung) ─────────────────────────
#
# Flow: MA waehlt auf /stempeluhr/pin seine Kachel, tippt 4-stellige PIN,
# gelangt ins Menue /stempeluhr/menu. Die Session ist auf 10 Minuten begrenzt;
# bei Inaktivitaet muss neu authentifiziert werden. Kein CAO-Login noetig –
# Self-Service ist bewusst als separate Vertrauenszone modelliert.

_SS_TIMEOUT_MIN = 10


def _ss_ist_auth() -> bool:
    if not session.get('ss_pers_id'):
        return False
    auth_iso = session.get('ss_auth_at')
    if not auth_iso:
        return False
    try:
        auth_at = datetime.fromisoformat(auth_iso)
    except ValueError:
        return False
    return (datetime.now() - auth_at) <= timedelta(minutes=_SS_TIMEOUT_MIN)


def _ss_logout():
    session.pop('ss_pers_id', None)
    session.pop('ss_auth_at', None)
    session.pop('ss_name', None)


def _ss_auth_required(f):
    @wraps(f)
    def _wrapper(*args, **kwargs):
        if not _ss_ist_auth():
            _ss_logout()
            return redirect(url_for('stempeluhr_pin'))
        # Bei jedem Call Zeitstempel erneuern (rolling timeout).
        session['ss_auth_at'] = datetime.now().isoformat(timespec='seconds')
        return f(*args, **kwargs)
    return _wrapper


def _ss_pers_id() -> int:
    return int(session['ss_pers_id'])


@app.route("/stempeluhr/pin")
def stempeluhr_pin():
    """Kachel-Auswahl der MA (mit PIN) + PIN-Keypad."""
    from modules.orga.personal import models as pm
    mas = pm.ma_mit_pin_liste()
    return render_template("stempeluhr_pin.html",
                           terminal_nr=get_terminal_nr(), mitarbeiter=mas)


@app.route("/api/stempeluhr/pin-auth", methods=["POST"])
def api_stempeluhr_pin_auth():
    """Prueft PERS_ID + PIN; bei Erfolg wird Session gesetzt."""
    data = request.get_json(silent=True) or {}
    try:
        pers_id = int(data.get("pers_id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "fehler": "Mitarbeiter fehlt."}), 400
    pin = str(data.get("pin", "")).strip()
    from modules.orga.personal import models as pm
    ma = pm.authentifiziere_pers_pin(pers_id, pin)
    if not ma:
        return jsonify({"ok": False, "fehler": "PIN stimmt nicht."}), 401
    session['ss_pers_id']  = int(ma['PERS_ID'])
    session['ss_auth_at']  = datetime.now().isoformat(timespec='seconds')
    session['ss_name']     = f"{ma['VNAME']} {ma['NAME']}"
    return jsonify({"ok": True, "pers_id": int(ma['PERS_ID']),
                    "name": session['ss_name']})


@app.route("/stempeluhr/abmelden", methods=["GET", "POST"])
def stempeluhr_abmelden():
    _ss_logout()
    return redirect(url_for('stempeluhr'))


@app.route("/stempeluhr/menu")
@_ss_auth_required
def stempeluhr_menu():
    from modules.orga.personal import models as pm
    pers_id = _ss_pers_id()
    naechste = pm.stempel_naechste_richtung(pers_id)
    return render_template("stempeluhr_menu.html",
                           pers_id=pers_id,
                           name=session.get('ss_name', ''),
                           naechste_richtung=naechste,
                           terminal_nr=get_terminal_nr())


@app.route("/api/stempeluhr/pin-stempeln", methods=["POST"])
@_ss_auth_required
def api_stempeluhr_pin_stempeln():
    """Loest Stempel (Kommen/Gehen) fuer den authentifizierten MA aus."""
    from modules.orga.personal import models as pm
    pers_id = _ss_pers_id()
    richtung = pm.stempel_naechste_richtung(pers_id)
    zeitpunkt = datetime.now().replace(microsecond=0)
    tnr = get_terminal_nr() or None
    try:
        with db.get_db_transaction() as cur:
            cur.execute(
                """INSERT INTO XT_PERSONAL_STEMPEL
                     (PERS_ID, RICHTUNG, ZEITPUNKT, QUELLE, TERMINAL_NR)
                   VALUES (%s, %s, %s, 'kiosk', %s)""",
                (pers_id, richtung, zeitpunkt, tnr),
            )
    except Exception as exc:
        return jsonify({"ok": False, "fehler": f"Serverfehler: {exc}"}), 500
    return jsonify({
        "ok": True,
        "richtung": richtung,
        "zeit": zeitpunkt.strftime("%H:%M:%S"),
        "name": session.get('ss_name', ''),
    })


# ── Stempeluhr Self-Service: Korrektur eigener Stempel ─────────────────────

_KORREKTUR_MAX_TAGE = 14


@app.route("/stempeluhr/korrektur")
@_ss_auth_required
def stempeluhr_korrektur():
    from modules.orga.personal import models as pm
    pers_id = _ss_pers_id()
    bis = date.today()
    von = bis - timedelta(days=_KORREKTUR_MAX_TAGE)
    stempel = pm.stempel_ma_zeitraum(pers_id, von, bis)
    return render_template("stempeluhr_korrektur.html",
                           pers_id=pers_id,
                           name=session.get('ss_name', ''),
                           stempel=stempel, von=von, bis=bis,
                           max_tage=_KORREKTUR_MAX_TAGE)


def _ss_benutzer_ma_id(pers_id: int) -> int:
    """MA_ID fuers Log. Faellt auf PERS_ID zurueck, wenn CAO nicht verknuepft."""
    from modules.orga.personal import models as pm
    ma = pm.ma_by_id(pers_id) or {}
    return int(ma.get('CAO_MA_ID') or 0) or int(pers_id)


def _parse_hhmm_auf_datum(tag: date, hhmm: str) -> datetime:
    """Parst 'HH:MM' auf das uebergebene Datum. Wirft ValueError."""
    std, min_ = hhmm.strip().split(':', 1)
    return datetime.combine(tag, datetime.min.time()).replace(
        hour=int(std), minute=int(min_))


@app.route("/stempeluhr/korrektur/neu", methods=["POST"])
@_ss_auth_required
def stempeluhr_korrektur_neu():
    from modules.orga.personal import models as pm
    pers_id = _ss_pers_id()
    try:
        tag = date.fromisoformat(request.form.get("tag", "").strip())
    except ValueError:
        return redirect(url_for('stempeluhr_korrektur'))
    richtung = request.form.get("richtung", "").strip()
    grund    = request.form.get("grund", "").strip()
    try:
        zeitpunkt = _parse_hhmm_auf_datum(tag, request.form.get("zeit", ""))
    except (ValueError, TypeError):
        return redirect(url_for('stempeluhr_korrektur'))
    try:
        pm.stempel_korrektur_insert(
            pers_id=pers_id, richtung=richtung, zeitpunkt=zeitpunkt,
            grund=grund, benutzer_ma_id=_ss_benutzer_ma_id(pers_id),
        )
    except ValueError:
        pass
    return redirect(url_for('stempeluhr_korrektur'))


@app.route("/stempeluhr/korrektur/<int:rec_id>", methods=["POST"])
@_ss_auth_required
def stempeluhr_korrektur_update(rec_id: int):
    from modules.orga.personal import models as pm
    pers_id = _ss_pers_id()
    # Nur eigene Stempel korrigierbar.
    with db.get_db() as cur:
        cur.execute(
            "SELECT PERS_ID, ZEITPUNKT FROM XT_PERSONAL_STEMPEL WHERE REC_ID = %s",
            (int(rec_id),),
        )
        alt = cur.fetchone()
    if not alt or int(alt['PERS_ID']) != pers_id:
        return redirect(url_for('stempeluhr_korrektur'))
    richtung = request.form.get("richtung", "").strip()
    grund    = request.form.get("grund", "").strip()
    try:
        zeitpunkt = _parse_hhmm_auf_datum(
            alt['ZEITPUNKT'].date(), request.form.get("zeit", ""))
    except (ValueError, TypeError):
        return redirect(url_for('stempeluhr_korrektur'))
    try:
        pm.stempel_korrektur_update(
            rec_id=int(rec_id), richtung=richtung, zeitpunkt=zeitpunkt,
            grund=grund, benutzer_ma_id=_ss_benutzer_ma_id(pers_id),
        )
    except ValueError:
        pass
    return redirect(url_for('stempeluhr_korrektur'))


# ── Stempeluhr Self-Service: Urlaubsantrag einreichen ─────────────────────

@app.route("/stempeluhr/urlaub")
@_ss_auth_required
def stempeluhr_urlaub_neu():
    from modules.orga.personal import models as pm
    pers_id = _ss_pers_id()
    jahr = date.today().year
    saldo = pm.urlaub_saldo(pers_id, jahr)
    return render_template("stempeluhr_urlaub.html",
                           pers_id=pers_id,
                           name=session.get('ss_name', ''),
                           saldo=saldo, jahr=jahr,
                           heute=date.today().isoformat())


@app.route("/stempeluhr/urlaub", methods=["POST"])
@_ss_auth_required
def stempeluhr_urlaub_speichern():
    from modules.orga.personal import models as pm
    pers_id = _ss_pers_id()
    try:
        von = date.fromisoformat(request.form.get("von", "").strip())
        bis = date.fromisoformat(request.form.get("bis", "").strip())
    except ValueError:
        return redirect(url_for('stempeluhr_urlaub_neu'))
    kommentar = (request.form.get("kommentar", "").strip() or None)
    try:
        pm.urlaub_antrag_anlegen(
            pers_id=pers_id, von=von, bis=bis,
            kommentar=kommentar,
            benutzer_ma_id=_ss_benutzer_ma_id(pers_id),
            status='geplant',
        )
        zeitraum = (f'{von.strftime("%d.%m.%Y")}'
                    if von == bis
                    else f'{von.strftime("%d.%m.%Y")} bis {bis.strftime("%d.%m.%Y")}')
        details = f'Zeitraum: {zeitraum}'
        if kommentar:
            details += f'\nKommentar: {kommentar}'
        pm.benachrichtigung_antrag_senden(
            bereich='urlaub_antrag', pers_id=pers_id,
            titel='Neuer Urlaubsantrag', details=details,
        )
    except ValueError:
        pass
    return redirect(url_for('stempeluhr_uebersicht'))


# ── Stempeluhr Self-Service: Abwesenheit (Krankheit etc.) melden ───────────

@app.route("/stempeluhr/abwesenheit")
@_ss_auth_required
def stempeluhr_abwesenheit_neu():
    from modules.orga.personal import models as pm
    return render_template("stempeluhr_abwesenheit.html",
                           pers_id=_ss_pers_id(),
                           name=session.get('ss_name', ''),
                           heute=date.today().isoformat(),
                           typen=pm.ABWESENHEIT_TYP_LABELS)


@app.route("/stempeluhr/abwesenheit", methods=["POST"])
@_ss_auth_required
def stempeluhr_abwesenheit_speichern():
    from modules.orga.personal import models as pm
    pers_id = _ss_pers_id()
    typ = request.form.get("typ", "").strip()
    try:
        von = date.fromisoformat(request.form.get("von", "").strip())
        bis = date.fromisoformat(request.form.get("bis", "").strip())
    except ValueError:
        return redirect(url_for('stempeluhr_abwesenheit_neu'))
    bemerkung = (request.form.get("bemerkung", "").strip() or None)
    try:
        pm.abwesenheit_anlegen(
            pers_id=pers_id, typ=typ, von=von, bis=bis,
            bemerkung=bemerkung,
            status='beantragt',
            benutzer_ma_id=_ss_benutzer_ma_id(pers_id),
        )
        typ_label = pm.ABWESENHEIT_TYP_LABELS.get(typ, typ)
        zeitraum = (f'{von.strftime("%d.%m.%Y")}'
                    if von == bis
                    else f'{von.strftime("%d.%m.%Y")} bis {bis.strftime("%d.%m.%Y")}')
        details = f'Typ: {typ_label}\nZeitraum: {zeitraum}'
        if bemerkung:
            details += f'\nBemerkung: {bemerkung}'
        pm.benachrichtigung_antrag_senden(
            bereich='abwesenheit_antrag', pers_id=pers_id,
            titel='Neuer Abwesenheitsantrag', details=details,
        )
    except ValueError:
        pass
    return redirect(url_for('stempeluhr_uebersicht'))


# ── Stempeluhr Self-Service: Uebersicht eigener Urlaube + Abwesenheiten ───

@app.route("/stempeluhr/uebersicht")
@_ss_auth_required
def stempeluhr_uebersicht():
    from modules.orga.personal import models as pm
    pers_id = _ss_pers_id()
    jahr = date.today().year
    saldo = pm.urlaub_saldo(pers_id, jahr)
    antraege = pm.urlaub_antraege(pers_id, jahr)
    abwesenheiten = pm.abwesenheiten_ma(pers_id, jahr=jahr)
    return render_template("stempeluhr_uebersicht.html",
                           pers_id=pers_id,
                           name=session.get('ss_name', ''),
                           jahr=jahr, saldo=saldo,
                           antraege=antraege,
                           abwesenheiten=abwesenheiten,
                           typen=pm.ABWESENHEIT_TYP_LABELS)


# ── Stempeluhr Self-Service: Eigene PIN aendern ────────────────────────────

@app.route("/stempeluhr/pin-aendern")
@_ss_auth_required
def stempeluhr_pin_aendern_seite():
    return render_template("stempeluhr_pin_aendern.html",
                           pers_id=_ss_pers_id(),
                           name=session.get('ss_name', ''))


@app.route("/api/stempeluhr/pin-aendern", methods=["POST"])
@_ss_auth_required
def api_stempeluhr_pin_aendern():
    from modules.orga.personal import models as pm
    data = request.get_json(silent=True) or {}
    alte = str(data.get("alte_pin", "")).strip()
    neue = str(data.get("neue_pin", "")).strip()
    try:
        ok = pm.pin_aendern_self(_ss_pers_id(), alte, neue)
    except ValueError as exc:
        return jsonify({"ok": False, "fehler": str(exc)}), 400
    if not ok:
        return jsonify({"ok": False, "fehler": "Alte PIN stimmt nicht."}), 401
    return jsonify({"ok": True})


# ── Systemstatus ──────────────────────────────────────────────

@app.route("/status")
def status():
    db_ok = db.test_verbindung()
    drucker_ok = druck.test_drucker()
    return jsonify({
        "terminal_nr": get_terminal_nr(),
        "datenbank": "ok" if db_ok else "fehler",
        "drucker": "ok" if drucker_ok else "fehler",
        "ean_sammelartikel": config.EAN_SAMMELARTIKEL,
    })


# ── Start ─────────────────────────────────────────────────────

if __name__ == "__main__":
    # Bild-Cache beim Start befüllen
    _bild_cache_aufbauen()
    print(f"Habacher Dorfladen Kiosk – Terminal {config.TERMINAL_NR}")
    print(f"DB:      {config.DB_HOST}:{config.DB_PORT}/{config.DB_NAME}")
    print(f"Bilder:  {len(_bild_cache)} Produktbilder gefunden")
    print(f"Starte Flask auf {config.HOST}:{config.PORT}")
    # Terminal-Selbstregistrierung (Phase 9).
    try:
        from common.terminal_selbstregistrierung import selbst_registrieren
        selbst_registrieren('KIOSK')
    except Exception:
        pass
    app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG)
