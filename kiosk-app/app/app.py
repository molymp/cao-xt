"""
Bäckerei Kiosk – Flask-Hauptanwendung
Starten: cd app && python3 app.py
"""

from flask import Flask, render_template, request, jsonify, redirect, url_for, send_from_directory
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
import ean as ean_modul
import druck
import mittagstisch as mt

app = Flask(__name__)


@app.context_processor
def _inject_globals():
    """Stellt terminal_nr und update_verfuegbar in allen Templates bereit."""
    return {
        "terminal_nr":      get_terminal_nr(),
        "update_verfuegbar": _update_status["verfuegbar"],
        "firma_name":        config.FIRMA_NAME,
        "db_name":           config.DB_NAME,
        "kasse_url":         config.KASSE_URL or (
                                 f'{request.scheme}://{request.host.split(":")[0]}:{config.KASSE_PORT}'
                                 if config.KASSE_PORT else ''),
        "wawi_url":          config.WAWI_URL or (
                                 f'{request.scheme}://{request.host.split(":")[0]}:{config.WAWI_PORT}'
                                 if config.WAWI_PORT else ''),
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


# Produkt-Cache: v_kiosk_produkte ist teuer (Cross-DB-Join über WAN).
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
        cursor.execute("SELECT * FROM v_kiosk_produkte")
        rows = cursor.fetchall()
    _produkt_cache = rows
    _produkt_cache_ablauf = jetzt + PRODUKT_CACHE_TTL
    return rows

def produkt_cache_leeren():
    """Manuell aufrufen wenn Artikel-Verwaltung Änderungen gespeichert hat."""
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
            "SELECT id FROM warenkoerbe WHERE status='offen' AND gesperrt_von=%s",
            (get_terminal_nr(),)
        )
        row = cursor.fetchone()
        return row["id"] if row else None


def neuer_warenkorb():
    with get_db() as cursor:
        tnr = get_terminal_nr()
        cursor.execute(
            """INSERT INTO warenkoerbe
               (status, gesamtbetrag_cent, gesperrt_von, gesperrt_am, erstellt_von)
               VALUES ('offen', 0, %s, NOW(), %s)""",
            (tnr, tnr)
        )
        return cursor.lastrowid


def gesamtbetrag_aktualisieren(cursor, warenkorb_id):
    cursor.execute(
        """UPDATE warenkoerbe
           SET gesamtbetrag_cent = (
               SELECT COALESCE(SUM(zeilen_betrag_cent), 0)
               FROM warenkorb_positionen WHERE warenkorb_id = %s
           ),
           geaendert_am = NOW()
           WHERE id = %s""",
        (warenkorb_id, warenkorb_id)
    )


# ── Kiosk-Hauptansicht ────────────────────────────────────────

@app.route("/")
def index():
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

    # Warenkorb + Positionen in einer Verbindung holen
    with get_db() as cursor:
        cursor.execute("SELECT * FROM warenkoerbe WHERE id=%s", (wk_id,))
        warenkorb = cursor.fetchone()
        cursor.execute(
            "SELECT * FROM warenkorb_positionen WHERE warenkorb_id=%s ORDER BY id",
            (wk_id,)
        )
        positionen = cursor.fetchall()

    return render_template(
        "kiosk.html",
        kategorien=kategorien_sorted,
        warenkorb=warenkorb,
        positionen=positionen,
        cent_zu_euro=cent_zu_euro_str,
        terminal_nr=get_terminal_nr(),
    )


# ── Warenkorb-API ─────────────────────────────────────────────

@app.route("/warenkorb/neu", methods=["POST"])
def warenkorb_neu():
    wk_id = neuer_warenkorb()
    return jsonify({"ok": True, "warenkorb_id": wk_id})


@app.route("/warenkorb/<int:wk_id>/positionen")
def warenkorb_positionen(wk_id):
    with get_db() as cursor:
        cursor.execute(
            "SELECT * FROM warenkorb_positionen WHERE warenkorb_id=%s ORDER BY id",
            (wk_id,)
        )
        positionen = cursor.fetchall()
        cursor.execute("SELECT gesamtbetrag_cent FROM warenkoerbe WHERE id=%s", (wk_id,))
        wk = cursor.fetchone()
    return jsonify({
        "ok": True,
        "positionen": positionen,
        "gesamtbetrag_cent": wk["gesamtbetrag_cent"] if wk else 0,
    })


@app.route("/warenkorb/<int:wk_id>/position", methods=["POST"])
def position_hinzufuegen(wk_id):
    produkt_id = request.get_json(force=True).get("produkt_id")
    with get_db() as cursor:
        cursor.execute(
            "SELECT id, name, preis_cent FROM v_kiosk_produkte WHERE id=%s",
            (produkt_id,)
        )
        produkt = cursor.fetchone()
        if not produkt:
            return jsonify({"ok": False, "fehler": "Produkt nicht gefunden"}), 404

        # Sicherstellen dass ein produkte-Eintrag existiert (FK-Constraint).
        cursor.execute(
            """INSERT IGNORE INTO produkte (id, kategorie_id, einheit, wochentage, aktiv)
               VALUES (%s, NULL, 'Stck.', '', 1)""",
            (produkt_id,)
        )

        cursor.execute(
            "SELECT id, menge FROM warenkorb_positionen WHERE warenkorb_id=%s AND produkt_id=%s",
            (wk_id, produkt_id)
        )
        pos = cursor.fetchone()

        if pos:
            neue_menge = pos["menge"] + 1
            cursor.execute(
                "UPDATE warenkorb_positionen SET menge=%s, zeilen_betrag_cent=%s WHERE id=%s",
                (neue_menge, neue_menge * produkt["preis_cent"], pos["id"])
            )
        else:
            cursor.execute(
                """INSERT INTO warenkorb_positionen
                   (warenkorb_id, produkt_id, name_snapshot,
                    preis_snapshot_cent, menge, zeilen_betrag_cent)
                   VALUES (%s, %s, %s, %s, 1, %s)""",
                (wk_id, produkt_id, produkt["name"],
                 produkt["preis_cent"], produkt["preis_cent"])
            )

        gesamtbetrag_aktualisieren(cursor, wk_id)
        cursor.execute("SELECT gesamtbetrag_cent FROM warenkoerbe WHERE id=%s", (wk_id,))
        wk = cursor.fetchone()

    return jsonify({"ok": True, "gesamtbetrag_cent": wk["gesamtbetrag_cent"]})


@app.route("/warenkorb/<int:wk_id>/position/<int:pos_id>/menge", methods=["POST"])
def menge_setzen(wk_id, pos_id):
    menge = int(request.get_json(force=True).get("menge", 0))
    with get_db() as cursor:
        if menge <= 0:
            cursor.execute(
                "DELETE FROM warenkorb_positionen WHERE id=%s AND warenkorb_id=%s",
                (pos_id, wk_id)
            )
        else:
            cursor.execute(
                """UPDATE warenkorb_positionen
                   SET menge=%s, zeilen_betrag_cent=%s * preis_snapshot_cent
                   WHERE id=%s AND warenkorb_id=%s""",
                (menge, menge, pos_id, wk_id)
            )
        gesamtbetrag_aktualisieren(cursor, wk_id)
        cursor.execute("SELECT gesamtbetrag_cent FROM warenkoerbe WHERE id=%s", (wk_id,))
        wk = cursor.fetchone()
    return jsonify({"ok": True, "gesamtbetrag_cent": wk["gesamtbetrag_cent"]})


@app.route("/warenkorb/<int:wk_id>/position/<int:pos_id>", methods=["DELETE"])
def position_loeschen(wk_id, pos_id):
    with get_db() as cursor:
        cursor.execute(
            "DELETE FROM warenkorb_positionen WHERE id=%s AND warenkorb_id=%s",
            (pos_id, wk_id)
        )
        gesamtbetrag_aktualisieren(cursor, wk_id)
        cursor.execute("SELECT gesamtbetrag_cent FROM warenkoerbe WHERE id=%s", (wk_id,))
        wk = cursor.fetchone()
    return jsonify({"ok": True, "gesamtbetrag_cent": wk["gesamtbetrag_cent"]})


@app.route("/warenkorb/<int:wk_id>/parken", methods=["POST"])
def parken(wk_id):
    with get_db() as cursor:
        cursor.execute(
            """UPDATE warenkoerbe SET status='geparkt', gesperrt_von=NULL,
               gesperrt_am=NULL, geaendert_am=NOW()
               WHERE id=%s AND gesperrt_von=%s""",
            (wk_id, get_terminal_nr())
        )
    return jsonify({"ok": True})


@app.route("/warenkorb/<int:wk_id>/abbrechen", methods=["POST"])
def abbrechen(wk_id):
    with get_db() as cursor:
        cursor.execute(
            """UPDATE warenkoerbe SET status='abgebrochen', gesperrt_von=NULL,
               gesperrt_am=NULL, geaendert_am=NOW()
               WHERE id=%s AND gesperrt_von=%s""",
            (wk_id, get_terminal_nr())
        )
    return jsonify({"ok": True})


@app.route("/warenkorb/<int:wk_id>/buchen", methods=["POST"])
def buchen(wk_id):
    with get_db() as cursor:
        cursor.execute(
            "SELECT * FROM warenkoerbe WHERE id=%s AND gesperrt_von=%s",
            (wk_id, get_terminal_nr())
        )
        warenkorb = cursor.fetchone()
        if not warenkorb:
            return jsonify({"ok": False, "fehler": "Warenkorb nicht gefunden"}), 404
        if warenkorb["gesamtbetrag_cent"] <= 0:
            return jsonify({"ok": False, "fehler": "Warenkorb ist leer"}), 400

        cursor.execute(
            "SELECT * FROM warenkorb_positionen WHERE warenkorb_id=%s ORDER BY id",
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
                """INSERT INTO journal_warenkoerbe
                   (warenkorb_id, terminal_nr, erstellt_am, gebucht_am,
                    gesamtbetrag_cent, ean_barcode, bon_text, bon_data, status)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'gebucht')""",
                (wk_id, tnr, warenkorb["erstellt_am"], jetzt,
                 warenkorb["gesamtbetrag_cent"], ean_code, bon_text, bon_bytes)
            )
            journal_id = cursor.lastrowid

            for pos in positionen:
                cursor.execute(
                    """INSERT INTO journal_positionen
                       (journal_id, produkt_id, name_snapshot,
                        preis_snapshot_cent, menge, zeilen_betrag_cent)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (journal_id, pos["produkt_id"], pos["name_snapshot"],
                     pos["preis_snapshot_cent"], pos["menge"], pos["zeilen_betrag_cent"])
                )

            cursor.execute(
                """UPDATE warenkoerbe SET status='abgebrochen', gesperrt_von=NULL,
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

@app.route("/offen")
def offene_warenkoerbe():
    with get_db() as cursor:
        cursor.execute("SELECT * FROM v_offene_warenkoerbe")
        koerbe = cursor.fetchall()
    return render_template(
        "offen.html", koerbe=koerbe,
        cent_zu_euro=cent_zu_euro_str, terminal_nr=get_terminal_nr(),
    )


@app.route("/offen/<int:wk_id>/uebernehmen", methods=["POST"])
def uebernehmen(wk_id):
    with get_db() as cursor:
        cursor.execute(
            """UPDATE warenkoerbe SET status='abgebrochen',
               gesperrt_von=NULL, gesperrt_am=NULL
               WHERE gesperrt_von=%s AND status='offen' AND gesamtbetrag_cent=0""",
            (get_terminal_nr(),)
        )
        cursor.execute(
            """UPDATE warenkoerbe SET status='offen', gesperrt_von=%s,
               gesperrt_am=NOW(), geaendert_am=NOW(), erstellt_von=%s
               WHERE id=%s AND status='geparkt'""",
            (get_terminal_nr(), get_terminal_nr(), wk_id)
        )
    return redirect(url_for("index"))


# ── Journal ───────────────────────────────────────────────────

@app.route("/journal")
def journal():
    with get_db() as cursor:
        cursor.execute("SELECT COUNT(*) AS n FROM v_journal_uebersicht")
        gesamt = cursor.fetchone()["n"]
        cursor.execute("SELECT * FROM v_journal_uebersicht LIMIT %s", (100,))
        eintraege = cursor.fetchall()
    return render_template(
        "journal.html", eintraege=eintraege, gesamt=gesamt,
        seite_groesse=100,
        cent_zu_euro=cent_zu_euro_str, terminal_nr=get_terminal_nr(),
    )


@app.route("/journal/mehr")
def journal_mehr():
    """Liefert weitere Journal-Einträge als JSON (für 'Mehr laden'-Button)."""
    offset = int(request.args.get("offset", 0))
    limit  = int(request.args.get("limit", 100))
    with get_db() as cursor:
        cursor.execute(
            "SELECT * FROM v_journal_uebersicht LIMIT %s OFFSET %s",
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


@app.route("/journal/<int:journal_id>/positionen")
def journal_positionen(journal_id):
    with get_db() as cursor:
        cursor.execute(
            "SELECT * FROM journal_positionen WHERE journal_id=%s ORDER BY id",
            (journal_id,)
        )
        positionen = cursor.fetchall()
    return jsonify({"ok": True, "positionen": positionen})


@app.route("/journal/<int:journal_id>/bon_data")
def journal_bon_data(journal_id):
    with get_db() as cursor:
        cursor.execute(
            "SELECT bon_data FROM journal_warenkoerbe WHERE id=%s", (journal_id,)
        )
        row = cursor.fetchone()
    if not row:
        return jsonify({"ok": False, "fehler": "Nicht gefunden"}), 404
    bon_data = row["bon_data"]
    if bon_data:
        return jsonify({"ok": True, "bon_data_b64": base64.b64encode(bon_data).decode()})
    return jsonify({"ok": True, "bon_data_b64": None})


@app.route("/journal/<int:journal_id>/nachdruck", methods=["POST"])
def nachdruck(journal_id):
    with get_db() as cursor:
        cursor.execute("SELECT * FROM journal_warenkoerbe WHERE id=%s", (journal_id,))
        eintrag = cursor.fetchone()
        if not eintrag:
            return jsonify({"ok": False, "fehler": "Nicht gefunden"}), 404
        cursor.execute(
            "SELECT * FROM journal_positionen WHERE journal_id=%s ORDER BY id",
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


@app.route("/journal/<int:journal_id>/stornieren", methods=["POST"])
def stornieren(journal_id):
    with get_db() as cursor:
        cursor.execute(
            """UPDATE journal_warenkoerbe SET status='storniert', storniert_am=NOW()
               WHERE id=%s AND status='gebucht'""",
            (journal_id,)
        )
    return jsonify({"ok": True})


# ── Admin: Artikelverwaltung ──────────────────────────────────

@app.route("/admin/artikel")
def admin_artikel():
    with get_db() as cursor:
        cursor.execute("SELECT * FROM v_artikel_verwaltung")
        artikel = cursor.fetchall()
        cursor.execute("SELECT * FROM kategorien ORDER BY sort_order")
        kategorien = cursor.fetchall()
    return render_template(
        "admin_artikel.html",
        artikel=artikel,
        kategorien=kategorien,
        cent_zu_euro=cent_zu_euro_str,
        terminal_nr=get_terminal_nr(),
    )


@app.route("/admin/artikel/<int:artikel_id>", methods=["POST"])
def admin_artikel_speichern(artikel_id):
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"ok": False, "fehler": "Keine Daten empfangen"}), 400

    kategorie_id = data.get("kategorie_id")
    wochentage   = data.get("wochentage", "")

    try:
        with get_db() as cursor:
            cursor.execute("SELECT id FROM produkte WHERE id=%s", (artikel_id,))
            exists = cursor.fetchone()

            if exists:
                cursor.execute(
                    """UPDATE produkte
                       SET kategorie_id=%s, einheit=%s, wochentage=%s,
                           zutaten=%s, aktiv=%s, hinweis=%s
                       WHERE id=%s""",
                    (kategorie_id, data.get("einheit", "Stck."), wochentage,
                     data.get("zutaten"), data.get("aktiv", 1),
                     data.get("hinweis"), artikel_id)
                )
            else:
                cursor.execute(
                    """INSERT INTO produkte
                       (id, kategorie_id, einheit, wochentage, zutaten, aktiv, hinweis)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    (artikel_id, kategorie_id, data.get("einheit", "Stck."),
                     wochentage, data.get("zutaten"),
                     data.get("aktiv", 1), data.get("hinweis"))
                )
    except Exception as e:
        app.logger.error(f"admin_artikel_speichern ID={artikel_id}: {e}")
        return jsonify({"ok": False, "fehler": str(e)}), 500

    # Produkt-Cache leeren damit Änderungen sofort sichtbar sind
    produkt_cache_leeren()
    return jsonify({"ok": True})


@app.route("/admin/bereinigen", methods=["POST"])
def admin_bereinigen():
    with get_db() as cursor:
        cursor.execute("SELECT id FROM v_verwaiste_produkte")
        ids = [r["id"] for r in cursor.fetchall()]
        geloescht = 0
        for pid in ids:
            try:
                cursor.execute("DELETE FROM produkte WHERE id=%s", (pid,))
                geloescht += 1
            except Exception:
                pass
    produkt_cache_leeren()
    return jsonify({"ok": True, "geloescht": geloescht})


# ── Mittagstisch ──────────────────────────────────────────────

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

@app.route("/bestellungen")
def bestellungen_view():
    wt = _heute_wochentag()
    with get_db() as cursor:
        cursor.execute(
            """SELECT b.*,
                      GROUP_CONCAT(CONCAT(bp.menge,'x ',bp.name_snapshot)
                                   ORDER BY bp.id SEPARATOR ', ') AS artikel_kurz,
                      COUNT(bp.id) AS pos_anzahl
               FROM bestellungen b
               LEFT JOIN bestell_positionen bp ON bp.bestell_id = b.id
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
               FROM bestellungen b
               LEFT JOIN bestell_positionen bp ON bp.bestell_id = b.id
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


@app.route("/bestellungen/neu")
def bestellung_neu_view():
    return render_template("bestellung_neu.html", terminal_nr=get_terminal_nr())


@app.route("/bestellungen/<int:bestell_id>")
def bestellung_detail_view(bestell_id):
    with get_db() as cursor:
        cursor.execute("SELECT * FROM bestellungen WHERE id=%s", (bestell_id,))
        bestellung = cursor.fetchone()
        if not bestellung:
            return "Bestellung nicht gefunden", 404
        cursor.execute(
            "SELECT * FROM bestell_positionen WHERE bestell_id=%s ORDER BY id",
            (bestell_id,)
        )
        positionen = cursor.fetchall()
    return render_template(
        "bestellung_detail.html",
        bestellung=bestellung,
        positionen=positionen,
        terminal_nr=get_terminal_nr(),
    )


@app.route("/api/bestellungen/badge")
def api_bestellungen_badge():
    wt = _heute_wochentag()
    with get_db() as cursor:
        cursor.execute(
            "SELECT COUNT(*) AS n FROM bestellungen b WHERE " + _BADGE_SQL,
            {"wt": wt}
        )
        row = cursor.fetchone()
    return jsonify({"ok": True, "anzahl": row["n"]})


@app.route("/api/bestellungen/produkte")
def api_bestellungen_produkte():
    wt = request.args.get("wochentag", "")
    with get_db() as cursor:
        if wt:
            cursor.execute(
                """SELECT id, name, preis_cent, einheit, wochentage,
                          kategorie_name, COALESCE(kategorie_sort, 999) AS kategorie_sort
                   FROM v_kiosk_produkte
                   WHERE aktiv > 0
                     AND (wochentage = '' OR FIND_IN_SET(%s, wochentage) > 0)
                   ORDER BY kategorie_sort, name""",
                (wt,)
            )
        else:
            cursor.execute(
                """SELECT id, name, preis_cent, einheit, wochentage,
                          kategorie_name, COALESCE(kategorie_sort, 999) AS kategorie_sort
                   FROM v_kiosk_produkte
                   WHERE aktiv > 0
                   ORDER BY kategorie_sort, name"""
            )
        produkte = cursor.fetchall()
    return jsonify({"ok": True, "produkte": produkte})


@app.route("/api/bestellungen/kunden")
def api_bestellungen_kunden():
    """Veraltet – leitet intern auf /api/kontakte weiter."""
    return api_kontakte()


@app.route("/api/kontakte")
def api_kontakte():
    """Autocomplete aus der kontakte-Tabelle."""
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify([])
    try:
        with get_db() as cursor:
            cursor.execute(
                """SELECT name, telefon FROM kontakte
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
    cursor.execute("SELECT id FROM kontakte WHERE name=%s AND telefon=%s", (name, tel))
    row = cursor.fetchone()
    if row:
        return row["id"]
    cursor.execute("INSERT INTO kontakte (name, telefon) VALUES (%s, %s)", (name, tel))
    return cursor.lastrowid


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
                """INSERT INTO bestellungen
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
                "UPDATE bestellungen SET bestell_nr=%s, kontakt_id=%s WHERE id=%s",
                (bestell_nr, kontakt_id, bestell_id),
            )
            for pos in positionen:
                cursor.execute(
                    """INSERT INTO bestell_positionen
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
                    "UPDATE bestellungen SET bon_data=%s WHERE id=%s",
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
            cursor.execute("SELECT * FROM bestellungen WHERE id=%s", (bestell_id,))
            alt_bestellung = cursor.fetchone()
            if not alt_bestellung:
                return jsonify({"ok": False, "fehler": "Bestellung nicht gefunden"}), 404
            cursor.execute(
                "SELECT * FROM bestell_positionen WHERE bestell_id=%s ORDER BY id",
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
                """UPDATE bestellungen
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
                "DELETE FROM bestell_positionen WHERE bestell_id=%s", (bestell_id,)
            )
            for pos in positionen:
                cursor.execute(
                    """INSERT INTO bestell_positionen
                           (bestell_id, produkt_id, name_snapshot, preis_cent, menge)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (bestell_id, pos["produkt_id"], pos["name"],
                     pos["preis_cent"], pos["menge"]),
                )

            # Neuen Zustand für den Bon laden
            cursor.execute("SELECT * FROM bestellungen WHERE id=%s", (bestell_id,))
            neu_bestellung = cursor.fetchone()
            cursor.execute(
                "SELECT * FROM bestell_positionen WHERE bestell_id=%s ORDER BY id",
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


@app.route("/api/bestellungen/<int:bestell_id>/stornieren", methods=["POST"])
def api_bestellung_stornieren(bestell_id):
    terminal_nr = get_terminal_nr()
    try:
        with get_db() as cursor:
            cursor.execute("SELECT * FROM bestellungen WHERE id=%s", (bestell_id,))
            b_row = cursor.fetchone()
            if not b_row:
                return jsonify({"ok": False, "fehler": "Nicht gefunden"}), 404
            cursor.execute(
                "SELECT * FROM bestell_positionen WHERE bestell_id=%s ORDER BY id",
                (bestell_id,),
            )
            pos_rows = cursor.fetchall()
            cursor.execute(
                "UPDATE bestellungen SET status='storniert' WHERE id=%s AND status != 'storniert'",
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
            cursor.execute("SELECT * FROM bestellungen WHERE id=%s", (bestell_id,))
            row = cursor.fetchone()
            if not row:
                return jsonify({"ok": False, "fehler": "Nicht gefunden"}), 404
            if row["typ"] != "wiederkehrend":
                return jsonify({"ok": False, "fehler": "Nur für wiederkehrende Bestellungen"}), 400

            if wochen == 0:
                neu_pausiert = 0 if row["pausiert"] else 1
                cursor.execute(
                    "UPDATE bestellungen SET pausiert=%s, pause_bis=NULL WHERE id=%s",
                    (neu_pausiert, bestell_id),
                )
                pb = None
                pause_text = "Pausiert (unbefristet)" if neu_pausiert else None
            else:
                cursor.execute(
                    """UPDATE bestellungen
                       SET pausiert=1, pause_bis=DATE_ADD(CURDATE(), INTERVAL %s WEEK)
                       WHERE id=%s""",
                    (wochen, bestell_id),
                )
                cursor.execute("SELECT pause_bis FROM bestellungen WHERE id=%s", (bestell_id,))
                r = cursor.fetchone()
                pb = r["pause_bis"].strftime('%d.%m.%Y') if r and r["pause_bis"] else None
                pause_text = f"Pausiert bis {pb}" if pb else "Pausiert"
                neu_pausiert = 1

            # Bon drucken (nur beim Pausieren, nicht beim Fortsetzen)
            if pause_text:
                cursor.execute(
                    "SELECT * FROM bestell_positionen WHERE bestell_id=%s ORDER BY id",
                    (bestell_id,)
                )
                pos_rows = cursor.fetchall()
                cursor.execute("SELECT * FROM bestellungen WHERE id=%s", (bestell_id,))
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
            cursor.execute("SELECT * FROM bestellungen WHERE id=%s", (bid,))
            b_row = cursor.fetchone()
            if not b_row or b_row["status"] == "storniert":
                continue
            cursor.execute(
                "SELECT * FROM bestell_positionen WHERE bestell_id=%s ORDER BY id",
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
                        "UPDATE bestellungen SET status='gedruckt', gedruckt_datum=CURDATE() WHERE id=%s",
                        (bid,)
                    )
                else:
                    cursor.execute(
                        "UPDATE bestellungen SET gedruckt_datum=CURDATE() WHERE id=%s",
                        (bid,)
                    )
                gedruckt += 1
            except Exception as e:
                fehler_liste.append(f"#{bid}: {e}")

    if fehler_liste:
        return jsonify({"ok": False, "fehler": "; ".join(fehler_liste)})
    return jsonify({"ok": True, "gedruckt": gedruckt})


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
            cursor.execute("SELECT * FROM bestellungen WHERE id=%s", (bestell_id,))
            b_row = cursor.fetchone()
            if not b_row:
                return jsonify({"ok": False, "fehler": "Nicht gefunden"}), 404
            cursor.execute(
                "SELECT * FROM bestell_positionen WHERE bestell_id=%s ORDER BY id",
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


@app.route("/api/update/ausfuehren", methods=["POST"])
def api_update_ausfuehren():
    if get_terminal_nr() != 8:
        return jsonify({"ok": False, "fehler": "Keine Berechtigung"}), 403
    try:
        ausgabe = _git(["pull", "origin", "master"], timeout=60)
    except Exception as exc:
        return jsonify({"ok": False, "fehler": str(exc)})

    def _neustart():
        time.sleep(2)
        os.execv(sys.executable, [sys.executable] + sys.argv)

    threading.Thread(target=_neustart, daemon=False).start()
    return jsonify({"ok": True, "ausgabe": ausgabe, "neustart": True})


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
    app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG)
