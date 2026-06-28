"""
CAO-XT – Zentrales Druck-Routing (Resolver)

Eine einzige Quelle der Wahrheit fuer die Frage "welcher Drucker bekommt
welches Dokument von welchem Terminal". Loest die drei historisch
verstreuten Tabellen ab (XT_KIOSK_DRUCKER, XT_KASSE_TERMINALS.DRUCKER_IP,
XT_DRUCKER_CONFIG) — diese bleiben physisch bestehen, werden fuers Drucken
aber nicht mehr gelesen.

Datenmodell (3 Tabellen, idempotent via CREATE TABLE IF NOT EXISTS):
  * XT_DRUCKER        – Geraete-Verzeichnis (IP/Port/Technik/Host)
  * XT_DRUCK_DOKTYP   – self-registering Dokumenttyp-Katalog (kein Enum!)
  * XT_DRUCK_ROUTING  – Matrix Terminal × Dokumenttyp -> Drucker

Verwendung::

    from common.druck import routing
    routing.drucke(terminal_nr=1, dok_key='bon', daten=buf)
    # oder nur aufloesen:
    d = routing.drucker_fuer(1, 'bon')   # -> dict mit ip_adresse, port, ...
"""
import logging
import socket
import threading

from common.db import get_db

logger = logging.getLogger(__name__)


class KeinDruckerError(Exception):
    """Kein (aktiver) Drucker fuer die Terminal/Dokumenttyp-Kombination."""


# Lazy-once: ensure_schema() macht echte Arbeit nur beim ersten Aufruf je
# Prozess. Doppel-Aufruf (oder Race vor gesetztem Flag) ist harmlos, da alle
# DDL idempotent ist — das Lock vermeidet nur unnoetige Roundtrips.
_schema_bereit = False
_schema_lock = threading.Lock()


def ensure_schema() -> None:
    """Legt die 3 Routing-Tabellen idempotent an und seedet einmalig.

    Wird je Prozess nur einmal wirklich ausgefuehrt (Modul-Flag). Alle DDL
    ist ``CREATE TABLE IF NOT EXISTS`` und damit gefahrlos wiederholbar.

    Seed (nur wenn XT_DRUCKER leer): uebernimmt den heute genutzten
    Einzeldrucker als XT_DRUCKER-Zeile (Quelle der Reihe nach:
    XT_KIOSK_DRUCKER standard, sonst XT_DRUCKER_CONFIG, sonst
    XT_KASSE_TERMINALS) und legt EINE globale Fallback-Routing-Zeile
    (terminal_nr=NULL, dok_key=NULL) darauf an.
    """
    global _schema_bereit
    if _schema_bereit:
        return
    with _schema_lock:
        if _schema_bereit:
            return
        try:
            with get_db() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS XT_DRUCKER (
                      id           INT AUTO_INCREMENT PRIMARY KEY,
                      name         VARCHAR(128) NOT NULL,
                      ip_adresse   VARCHAR(64) NOT NULL,
                      port         INT NOT NULL DEFAULT 9100,
                      technik      VARCHAR(32) NOT NULL DEFAULT 'escpos80',
                      host         VARCHAR(64) NOT NULL DEFAULT '',
                      aktiv        TINYINT(1) NOT NULL DEFAULT 1,
                      geaendert_am DATETIME DEFAULT CURRENT_TIMESTAMP
                                   ON UPDATE CURRENT_TIMESTAMP
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS XT_DRUCK_DOKTYP (
                      dok_key         VARCHAR(64) PRIMARY KEY,
                      bezeichnung     VARCHAR(128) NOT NULL DEFAULT '',
                      bereich         VARCHAR(32) NOT NULL DEFAULT '',
                      aktiv           TINYINT(1) NOT NULL DEFAULT 1,
                      zuletzt_gesehen DATETIME DEFAULT CURRENT_TIMESTAMP
                                      ON UPDATE CURRENT_TIMESTAMP
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS XT_DRUCK_ROUTING (
                      id           INT AUTO_INCREMENT PRIMARY KEY,
                      terminal_nr  INT NULL,
                      dok_key      VARCHAR(64) NULL,
                      drucker_id   INT NOT NULL,
                      geaendert_am DATETIME DEFAULT CURRENT_TIMESTAMP
                                   ON UPDATE CURRENT_TIMESTAMP,
                      INDEX idx_routing (terminal_nr, dok_key)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """)
            # Seed ist best-effort (faengt eigene Fehler ab) -> blockiert das
            # Setzen des bereit-Flags nicht, sobald die DDL durch ist.
            _seed_falls_leer()
            _schema_bereit = True
            logger.info("Druck-Routing: Schema geprueft/erstellt.")
        except Exception as exc:
            # Flag NICHT setzen -> naechster Aufruf versucht es erneut
            # (z.B. wenn die DB beim Start kurz nicht erreichbar war).
            logger.warning(
                "Druck-Routing: ensure_schema fehlgeschlagen: %s", exc)


def _ermittle_seed_drucker(cur) -> dict | None:
    """Sucht den heute aktiven Einzeldrucker in den Alt-Tabellen.

    Reihenfolge: XT_KIOSK_DRUCKER (Standard) -> XT_DRUCKER_CONFIG ->
    XT_KASSE_TERMINALS. Jede Quelle ist optional (Tabelle kann fehlen),
    daher einzeln defensiv abgesichert.

    Returns:
        dict mit name/ip_adresse/port, oder None wenn nichts gefunden.
    """
    # 1) Kiosk-Standarddrucker
    try:
        cur.execute(
            "SELECT name, ip_adresse, port FROM XT_KIOSK_DRUCKER "
            "WHERE standard=1 AND aktiv=1 LIMIT 1"
        )
        row = cur.fetchone()
        if row and row.get('ip_adresse'):
            return {
                'name':       row.get('name') or 'Drucker',
                'ip_adresse': row['ip_adresse'],
                'port':       int(row.get('port') or 9100),
            }
    except Exception as exc:
        logger.debug("Seed-Quelle XT_KIOSK_DRUCKER nicht nutzbar: %s", exc)

    # 2) Admin-Drucker-Config
    try:
        cur.execute(
            "SELECT bezeichnung, ip_adresse, port FROM XT_DRUCKER_CONFIG LIMIT 1"
        )
        row = cur.fetchone()
        if row and row.get('ip_adresse'):
            return {
                'name':       row.get('bezeichnung') or 'Drucker',
                'ip_adresse': row['ip_adresse'],
                'port':       int(row.get('port') or 9100),
            }
    except Exception as exc:
        logger.debug("Seed-Quelle XT_DRUCKER_CONFIG nicht nutzbar: %s", exc)

    # 3) Kassen-Terminal mit hinterlegter Drucker-IP
    try:
        cur.execute(
            "SELECT TERMINAL_NR, DRUCKER_IP, DRUCKER_PORT FROM XT_KASSE_TERMINALS "
            "WHERE AKTIV=1 AND DRUCKER_IP<>'' LIMIT 1"
        )
        row = cur.fetchone()
        if row and row.get('DRUCKER_IP'):
            return {
                'name':       f"Terminal {row.get('TERMINAL_NR')}",
                'ip_adresse': row['DRUCKER_IP'],
                'port':       int(row.get('DRUCKER_PORT') or 9100),
            }
    except Exception as exc:
        logger.debug("Seed-Quelle XT_KASSE_TERMINALS nicht nutzbar: %s", exc)

    return None


def _seed_falls_leer() -> None:
    """Uebernimmt einmalig den Alt-Einzeldrucker -> XT_DRUCKER + globale
    Fallback-Routing-Zeile. Nur wenn XT_DRUCKER leer ist. Best-effort.
    """
    try:
        with get_db() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM XT_DRUCKER")
            row = cur.fetchone()
            if row and int(row.get('n') or 0) > 0:
                return  # schon befuellt -> kein Seed

            seed = _ermittle_seed_drucker(cur)
            if seed is None:
                logger.info(
                    "Druck-Routing: kein Alt-Drucker zum Seeden gefunden.")
                return

            try:
                host = socket.gethostname() or ''
            except Exception:
                host = ''

            cur.execute(
                "INSERT INTO XT_DRUCKER "
                "(name, ip_adresse, port, technik, host, aktiv) "
                "VALUES (%s, %s, %s, 'escpos80', %s, 1)",
                (seed['name'], seed['ip_adresse'], seed['port'], host),
            )
            drucker_id = cur.lastrowid
            # Globale Fallback-Regel (alle Terminals, alle Dokumenttypen).
            cur.execute(
                "INSERT INTO XT_DRUCK_ROUTING (terminal_nr, dok_key, drucker_id) "
                "VALUES (NULL, NULL, %s)",
                (drucker_id,),
            )
            logger.info(
                "Druck-Routing: Seed-Drucker '%s' (%s:%s) als XT_DRUCKER #%s "
                "uebernommen, globale Fallback-Regel angelegt.",
                seed['name'], seed['ip_adresse'], seed['port'], drucker_id,
            )
    except Exception as exc:
        logger.warning("Druck-Routing: Seed fehlgeschlagen: %s", exc)


def register_doktyp(dok_key, bezeichnung='', bereich='') -> None:
    """Idempotenter Upsert in XT_DRUCK_DOKTYP (self-registering Katalog).

    Bei bestehendem Key wird ``zuletzt_gesehen`` aktualisiert; Bezeichnung
    und Bereich nur ueberschrieben, wenn ein nicht-leerer Wert geliefert
    wird. Best-effort: faengt alle Fehler ab und wirft nie — Drucken darf
    an einem Katalog-Update nicht scheitern.
    """
    if not dok_key:
        return
    try:
        with get_db() as cur:
            cur.execute(
                "INSERT INTO XT_DRUCK_DOKTYP (dok_key, bezeichnung, bereich) "
                "VALUES (%s, %s, %s) "
                "ON DUPLICATE KEY UPDATE "
                "  zuletzt_gesehen = NOW(), "
                "  bezeichnung = IF(VALUES(bezeichnung) <> '', "
                "                   VALUES(bezeichnung), bezeichnung), "
                "  bereich     = IF(VALUES(bereich) <> '', "
                "                   VALUES(bereich), bereich)",
                (dok_key, bezeichnung or '', bereich or ''),
            )
    except Exception as exc:
        logger.warning(
            "Druck-Routing: register_doktyp(%r) fehlgeschlagen: %s",
            dok_key, exc)


def drucker_fuer(terminal_nr, dok_key, host=None) -> dict:
    """Loest Terminal/Dokumenttyp zu genau einem aktiven Drucker auf.

    Auswahl NUR ueber aktive Drucker (XT_DRUCKER.aktiv=1), spezifischste
    Regel zuerst (erste Stufe mit Treffer gewinnt):

      1. terminal_nr=T  AND dok_key=D
      2. terminal_nr=NULL AND dok_key=D
      3. terminal_nr=T  AND dok_key=NULL
      4. terminal_nr=NULL AND dok_key=NULL   (globaler Fallback)

    Args:
        terminal_nr: Terminal-Nummer (None -> nur Wildcard-Regeln greifen).
        dok_key:     Dokumenttyp-Key (siehe XT_DRUCK_DOKTYP).
        host:        Optionaler Hostname des aufrufenden Rechners; dient nur
                     der Plausibilitaets-Warnung bei host-lokalen Druckern.

    Returns:
        dict mit id, name, ip_adresse, port, technik, host.

    Raises:
        KeinDruckerError: wenn keine aktive Regel matcht.
    """
    ensure_schema()
    register_doktyp(dok_key)

    basis = (
        "SELECT d.id, d.name, d.ip_adresse, d.port, d.technik, d.host "
        "FROM XT_DRUCK_ROUTING r "
        "JOIN XT_DRUCKER d ON d.id = r.drucker_id AND d.aktiv = 1 "
        "WHERE "
    )
    # Reihenfolge = Spezifitaet. NULL-Wildcards explizit mit IS NULL,
    # konkrete Werte mit = (parametrisiert).
    stufen = (
        ("r.terminal_nr = %s   AND r.dok_key = %s",   (terminal_nr, dok_key)),
        ("r.terminal_nr IS NULL AND r.dok_key = %s",  (dok_key,)),
        ("r.terminal_nr = %s   AND r.dok_key IS NULL", (terminal_nr,)),
        ("r.terminal_nr IS NULL AND r.dok_key IS NULL", ()),
    )

    drucker = None
    try:
        with get_db() as cur:
            for bedingung, params in stufen:
                cur.execute(basis + bedingung + " ORDER BY r.id LIMIT 1", params)
                row = cur.fetchone()
                if row:
                    drucker = row
                    break
    except Exception as exc:
        # DB-Fehler -> behandeln wie "nichts gefunden", aber Ursache loggen.
        logger.warning(
            "Druck-Routing: Aufloesung (T=%s, %r) DB-Fehler: %s",
            terminal_nr, dok_key, exc)

    if not drucker:
        raise KeinDruckerError(
            f"Kein aktiver Drucker fuer Terminal={terminal_nr}, "
            f"Dokumenttyp={dok_key!r} konfiguriert."
        )

    # Host-Bewusstsein: host-lokaler Drucker, Aufruf aber von anderem Host?
    # Heute Single-Host-Betrieb -> nur warnen, Drucker trotzdem liefern.
    d_host = (drucker.get('host') or '').strip()
    if host and d_host and d_host != host and d_host != 'LAN':
        logger.warning(
            "Druck-Routing: Drucker '%s' haengt host-lokal an '%s', Aufruf "
            "kommt von '%s' — sende trotzdem (Single-Host-Betrieb).",
            drucker.get('name'), d_host, host)

    return {
        'id':         drucker['id'],
        'name':       drucker['name'],
        'ip_adresse': drucker['ip_adresse'],
        'port':       drucker['port'],
        'technik':    drucker['technik'],
        'host':       drucker['host'],
    }


def drucke(terminal_nr, dok_key, daten: bytes, host=None) -> None:
    """Loest den Drucker auf und sendet ``daten`` per TCP/ESC-POS.

    Args:
        terminal_nr: Terminal-Nummer (oder None).
        dok_key:     Dokumenttyp-Key.
        daten:       Fertige ESC/POS-Byte-Sequenz.
        host:        Optionaler Hostname des aufrufenden Rechners.

    Raises:
        KeinDruckerError: wenn kein Drucker aufgeloest werden kann.
        OSError:          bei Verbindungs-/Sendefehler (aus tcp_send).
    """
    d = drucker_fuer(terminal_nr, dok_key, host=host)
    from common.druck.escpos import tcp_send
    tcp_send(d['ip_adresse'], d['port'], daten, timeout=10)
