"""
CAO-XT – Rechtemodell (Dorfkern v2, Phase 6)

Granulares Zugriffsmodell aus 4 Rollen x N Permission-Objekten. Die
Rolle kommt aus der CAO-Tabelle ``BENUTZERRECHTE`` (Gruppenname per
MITARBEITER); die Zuordnung Rolle -> Objekt-Recht liegt in den
Dorfkern-eigenen Tabellen ``DORFKERN_PERMISSION_OBJEKT`` und
``DORFKERN_ROLLE_PERMISSION``.

Rollen (Stand v2): ``Administratoren``, ``Geschäftsführung``,
``Ladenleitung``, ``Mitarbeiter``. ``Administratoren`` sind implizit
auf allen Objekten berechtigt – **keine Eintraege in
DORFKERN_ROLLE_PERMISSION noetig**.

Beispiele::

    from common import permission
    if permission.hat_recht(ma_id, 'kiosk.backwaren'):
        ...
    if permission.hat_recht(ma_id, 'orga.schichtplan', recht='PFLEGEN'):
        ...

Fail-closed: Bei DB-Fehlern / unbekannter Rolle / nicht-existentem
Objekt gibt :func:`hat_recht` ``False`` zurueck.
"""
from __future__ import annotations

import logging
from typing import Optional

from common.db import get_db, get_db_transaction

log = logging.getLogger(__name__)

# ── Konstanten ────────────────────────────────────────────────────────────────

_VALID_APPS = ('KIOSK', 'KASSE', 'ORGA', 'ADMIN')
_VALID_UNTERSCHEIDUNG = ('KEINE', 'LESE_PFLEGE')
_VALID_RECHTE = ('LESEN', 'PFLEGEN', 'BEIDES')

ROLLE_ADMIN = 'Administratoren'

# DB-RECHT -> Menge der Anfrage-RECHT, die damit abgedeckt sind.
# Strikt: ``PFLEGEN`` impliziert NICHT ``LESEN`` (zwei unabhaengige Bits
# zusammengefasst im Enum-Wert ``BEIDES``).
_DECKT_AB: dict[str, frozenset[str]] = {
    'LESEN':   frozenset({'LESEN'}),
    'PFLEGEN': frozenset({'PFLEGEN'}),
    'BEIDES':  frozenset({'LESEN', 'PFLEGEN', 'BEIDES'}),
}


# ── Schema ────────────────────────────────────────────────────────────────────

def run_migration() -> None:
    """Legt die beiden Permission-Tabellen an. Idempotent."""
    try:
        with get_db() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS DORFKERN_PERMISSION_OBJEKT (
                  OBJEKT_KEY      VARCHAR(64) NOT NULL PRIMARY KEY,
                  APP             ENUM('KIOSK','KASSE','ORGA','ADMIN') NOT NULL,
                  BEZEICHNUNG     VARCHAR(128) NOT NULL,
                  BESCHREIBUNG    TEXT,
                  UNTERSCHEIDUNG  ENUM('KEINE','LESE_PFLEGE') NOT NULL
                                  DEFAULT 'KEINE',
                  INDEX idx_app (APP)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                  COMMENT='Permission-Objekte (Dorfkern v2, Phase 6)'
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS DORFKERN_ROLLE_PERMISSION (
                  ROLLE      VARCHAR(64) NOT NULL,
                  OBJEKT_KEY VARCHAR(64) NOT NULL,
                  RECHT      ENUM('LESEN','PFLEGEN','BEIDES') NOT NULL
                             DEFAULT 'BEIDES',
                  PRIMARY KEY (ROLLE, OBJEKT_KEY),
                  FOREIGN KEY (OBJEKT_KEY)
                    REFERENCES DORFKERN_PERMISSION_OBJEKT(OBJEKT_KEY)
                    ON DELETE CASCADE ON UPDATE CASCADE,
                  INDEX idx_rolle (ROLLE)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                  COMMENT='Rolle-zu-Objekt-Zuordnung (Dorfkern v2, Phase 6)'
            """)
        log.info("Migration: DORFKERN_PERMISSION_* geprueft/erstellt.")
    except Exception as exc:
        log.warning("Permission-Migration fehlgeschlagen: %s", exc)


# Initialer Objekt-Katalog laut Release-Plan §5.4.
#
# Pflege: idempotent — neue Objekte koennen jederzeit am Ende der Liste
# ergaenzt werden, der naechste App-Start ruft seed_objekte() auf, das
# INSERT IGNORE schreibt nur neue Zeilen.
#
# Granularitaet: ein Permission-Objekt pro Sidebar-Eintrag / sinnvolle
# Funktionsgruppe. Beim Setzen von "LESE_PFLEGE": Sichten sollten LESEN
# kriegen, Aenderungen brauchen PFLEGEN.
_SEED_OBJEKTE: list[tuple[str, str, str, str, str]] = [
    # (OBJEKT_KEY, APP, BEZEICHNUNG, BESCHREIBUNG, UNTERSCHEIDUNG)

    # ── KIOSK ─────────────────────────────────────────────────
    ('kiosk.zugriff',          'KIOSK',
     'Kiosk – Zugriff',
     'Grund-Zugriff auf die Kiosk-App.', 'KEINE'),
    ('kiosk.backwaren',        'KIOSK',
     'Kiosk – Backwaren',
     'Backwaren-Bestellung und -Liste im Kiosk.', 'KEINE'),
    ('kiosk.bestellverwaltung','KIOSK',
     'Kiosk – Bestellverwaltung',
     'Bestellverwaltung (anlegen, stornieren).', 'KEINE'),
    ('kiosk.mittagstisch',     'KIOSK',
     'Kiosk – Mittagstisch',
     'Mittagstisch-Ansicht und -Bestellung.', 'KEINE'),
    ('kiosk.stempeluhr',       'KIOSK',
     'Kiosk – Stempeluhr',
     'Zeiterfassungs-Stempeluhr am Kiosk.', 'KEINE'),

    # ── KASSE ─────────────────────────────────────────────────
    ('kasse.zugriff',          'KASSE',
     'Kasse – Zugriff',
     'Grund-Zugriff auf die Kassen-App.', 'KEINE'),
    ('kasse.storno',           'KASSE',
     'Kasse – Storno',
     'Storno-Buchungen in der Kasse.', 'KEINE'),
    ('kasse.einstellungen',    'KASSE',
     'Kasse – Einstellungen',
     'Kasse-Einstellungen (Drucker, Terminal).', 'KEINE'),

    # ── ORGA ──────────────────────────────────────────────────
    ('orga.zugriff',           'ORGA',
     'Orga – Zugriff',
     'Grund-Zugriff auf die Orga-App (Dashboard + Basis-Navigation).',
     'KEINE'),
    ('orga.artikel',           'ORGA',
     'Orga – Artikel',
     'Artikel-Suche und Detail-Ansicht.', 'KEINE'),
    ('orga.preispflege',       'ORGA',
     'Orga – Preispflege',
     'Artikel-VK-Preise und Kalkulation bearbeiten.', 'LESE_PFLEGE'),
    ('orga.personal.mitarbeiter', 'ORGA',
     'Orga – Personal: Mitarbeiter',
     'Stammdaten der Mitarbeiter (Personalnummer, Kontakt, Urlaub).',
     'LESE_PFLEGE'),
    ('orga.schichtplan',       'ORGA',
     'Orga – Personal: Schichtplan',
     'Schichtplan je Kalenderwoche.',
     'LESE_PFLEGE'),
    ('orga.personal.schichten', 'ORGA',
     'Orga – Personal: Schichten',
     'Vergangene und gebuchte Schichten (Zeiterfassung).',
     'LESE_PFLEGE'),
    ('orga.personal.abwesenheiten', 'ORGA',
     'Orga – Personal: Abwesenheiten',
     'Urlaub, Krankheit, Sonderurlaub – Kalender-Ansicht.',
     'LESE_PFLEGE'),
    ('orga.personal.arbeitszeitkonten', 'ORGA',
     'Orga – Personal: Arbeitszeitkonten',
     'Stunden-Salden, Ueberstunden, Urlaubs-Konten.',
     'LESE_PFLEGE'),
    ('orga.datev_export',      'ORGA',
     'Orga – DATEV-Export',
     'Buchungssaetze nach DATEV exportieren.', 'KEINE'),
    ('orga.reporting',         'ORGA',
     'Orga – Reporting',
     'Reporting-Dashboards (Umsatz, KPIs, Wettereffekt, '
     'Faktoren-Heatmap, Kategorie-Berichte).', 'KEINE'),
    ('orga.betriebserfolg',    'ORGA',
     'Orga – Reporting: Betriebserfolg',
     'Monatliche Betriebserfolgsmessung — Umsatz, MAI, Personalkosten, '
     'Rohertrag, Blitz-Ertragsrechnung, Hochrechnung. Inkl. Editor '
     'fuer Verderb/MA-Std/Krankstd/Fixkosten und Konfig-Quoten.',
     'LESE_PFLEGE'),
    ('orga.haccp',             'ORGA',
     'Orga – Hygiene/HACCP',
     'HACCP-Dashboard, Alarme, Sichtkontrolle.', 'KEINE'),
    ('orga.handbuch',          'ORGA',
     'Orga – Handbuch',
     'Internes Handbuch (Lesen/Editieren).', 'LESE_PFLEGE'),
    ('orga.bestellwesen',      'ORGA',
     'Orga – Bestellwesen',
     'Bestellungen, Wareneingaenge, Einkaeufe (EK-Rechnungen), '
     'Storno- und Buchen-Workflows.', 'LESE_PFLEGE'),
    ('orga.bestellvorschlag',  'ORGA',
     'Orga – Bestellvorschlag',
     'Backwaren-Bedarfsprognose (Luidl): Historie + Wetter + Feiertage. '
     'Vorhersage und Bestellzettel-Vorschlag.', 'KEINE'),
    ('orga.lieferantenkatalog', 'ORGA',
     'Orga – Lieferantenkataloge',
     'Lieferanten-Sortimente (Excel/E-Mail-Kataloge) sichten und '
     'Artikel zum Bestellen bzw. zur Übernahme in den Artikelstamm '
     'markieren.', 'LESE_PFLEGE'),
    ('orga.stammdaten.adressen', 'ORGA',
     'Orga – Stammdaten/Adressen',
     'CAO-Adressen anlegen und bearbeiten (ADRESSEN + ADRESSEN_LOG, '
     'CAO-Mimik mit Record-Lock).', 'LESE_PFLEGE'),
    ('orga.banking',           'ORGA',
     'Orga – Banking (Hibiscus)',
     'Bankkonten-Uebersicht, Umsaetze, SEPA-Sammelueberweisungen, '
     'Reconcile mit EK-Rechnungen.', 'LESE_PFLEGE'),

    # ── ADMIN ─────────────────────────────────────────────────
    ('admin.zugriff',          'ADMIN',
     'Admin – Zugriff',
     'Grund-Zugriff auf die Admin-App (Dashboard + Basis-Navigation).',
     'KEINE'),

    # System (technische Wartung)
    ('admin.system.apps',      'ADMIN',
     'Admin – System: App-Manager',
     'Status, Start/Stop von Admin/Orga/Kasse/Kiosk-Apps.', 'LESE_PFLEGE'),
    ('admin.system.drucker',   'ADMIN',
     'Admin – System: Drucker',
     'Drucker-Stammdaten und Test-Druck.', 'LESE_PFLEGE'),
    ('admin.system.terminals', 'ADMIN',
     'Admin – System: Terminals',
     'Terminal-Registry, Drucker-Zuordnung.', 'LESE_PFLEGE'),
    ('admin.system.tse',       'ADMIN',
     'Admin – System: TSE',
     'TSE-Status (KassenSichV).', 'LESE_PFLEGE'),
    ('admin.system.db_config', 'ADMIN',
     'Admin – System: DB-Konfiguration',
     'Datenbank-Verbindung (caoxt.ini).', 'LESE_PFLEGE'),
    ('admin.system.haccp_poller', 'ADMIN',
     'Admin – System: HACCP-Poller',
     'HACCP-Temperatur-Poller-Konfig.', 'LESE_PFLEGE'),
    ('admin.system.einkauf_poller', 'ADMIN',
     'Admin – System: Einkauf-Poller',
     'Einkauf-Email-Poller (Gmail OAuth, Cron-Intervall).',
     'LESE_PFLEGE'),
    ('admin.system.mitarbeiter', 'ADMIN',
     'Admin – System: Mitarbeiter',
     'Admin-System-Mitarbeiter (Login, Rolle in CAO-Gruppen).',
     'LESE_PFLEGE'),
    ('admin.system.updates',   'ADMIN',
     'Admin – System: Updates',
     'Software-Updates ausspielen.', 'LESE_PFLEGE'),
    ('admin.system.power',     'ADMIN',
     'Admin – System: Ein/Aus',
     'Rechner herunterfahren oder neu starten (Feierabend-Knopf).',
     'LESE_PFLEGE'),
    ('admin.system.maintenance', 'ADMIN',
     'Admin – System: Wartungs-Modus',
     'Box zwischen Kiosk-Vollbild und Wartungs-Desktop umschalten.',
     'LESE_PFLEGE'),
    ('admin.system.banking',   'ADMIN',
     'Admin – System: Banking',
     'Hibiscus-Anbindung: Jameica-Master-Passwort hinterlegen, '
     'Verbindung testen.', 'LESE_PFLEGE'),

    # Dorfkern-Konfiguration
    ('admin.dorfkern.konfig',  'ADMIN',
     'Admin – Dorfkern: Konfiguration',
     'Allgemeine Dorfkern-Konfiguration (Mandant, Bundesland etc.).',
     'LESE_PFLEGE'),
    ('admin.dorfkern.terminals', 'ADMIN',
     'Admin – Dorfkern: Terminal-Verwaltung',
     'Terminal-Konfiguration aus Dorfkern-Sicht.', 'LESE_PFLEGE'),
    ('admin.dorfkern.aktivierungen', 'ADMIN',
     'Admin – Dorfkern: App-Aktivierungen',
     'Welche Apps sind freigeschaltet (Lizenzierung).',
     'LESE_PFLEGE'),
    ('admin.dorfkern.rechte',  'ADMIN',
     'Admin – Dorfkern: Rechte-Editor',
     'Permission-Objekte und Rollen-Rechte verwalten. '
     'Kritisches Recht — wer hier PFLEGEN hat, kann jede Rolle '
     'umkonfigurieren.', 'LESE_PFLEGE'),
    ('admin.dorfkern.einstellungen', 'ADMIN',
     'Admin – Dorfkern: Einstellungen',
     'Allgemeine Einstellungen (XT_EINSTELLUNGEN) - z.B. '
     'Betriebserfolg-Quoten, Personal-Bundesland.', 'LESE_PFLEGE'),
    ('admin.dorfkern.benachrichtigungen', 'ADMIN',
     'Admin – Dorfkern: Benachrichtigungen',
     'Email-/Push-Benachrichtigungen konfigurieren.', 'LESE_PFLEGE'),
    ('admin.dorfkern.funktionen', 'ADMIN',
     'Admin – Dorfkern: Funktionen / Feature-Toggles',
     'Optionale Features ein-/ausschalten.', 'LESE_PFLEGE'),
    ('admin.dorfkern.feiertage', 'ADMIN',
     'Admin – Dorfkern: Feiertage',
     'Feiertage je Bundesland pflegen und syncen.', 'LESE_PFLEGE'),
    ('admin.dorfkern.handbuch', 'ADMIN',
     'Admin – Dorfkern: Handbuch',
     'Handbuch-Editor (Markdown).', 'LESE_PFLEGE'),

    # Stammdaten (CAO-Sicht). Sammelobjekt + Mittagstisch separat,
    # weil das pflegelastig ist.
    ('admin.stammdaten',       'ADMIN',
     'Admin – Stammdaten (CAO)',
     'CAO-Stammdaten — Mengeneinheiten, Zahlungsarten, Lieferarten, '
     'Laender, Adressgruppen, Warengruppen, Kontenrahmen, '
     'Firmenbankkonten, Firma, Artikelattribute, Nummernkreise, '
     'Exporte, Binaerdaten. LESEN = Listen einsehen, PFLEGEN = anlegen/'
     'aendern/loeschen.', 'LESE_PFLEGE'),
    ('admin.stammdaten.mittagstisch', 'ADMIN',
     'Admin – Stammdaten: Mittagstisch',
     'Mittagstisch-Karte konfigurieren (Sonderfall, oft taeglich '
     'gepflegt).', 'LESE_PFLEGE'),

    # Artikel (Bilder, Kategorien, Vorlauf — Backwaren-Pflege)
    # In der Sidebar liegt das unter „Daten → 🥐 Backwaren".
    ('admin.artikel',          'ADMIN',
     'Admin – Daten: Backwaren-Pflege',
     'Backwaren-Anzeige im Kiosk-Frontend pflegen (Bilder, '
     'Kategorien, Wochentage, Zutaten, Vorlaufzeit, Aktiv-Flag). '
     'Sidebar: Daten → 🥐 Backwaren. Endpoint /artikel.',
     'LESE_PFLEGE'),
    ('admin.zeiten_import',    'ADMIN',
     'Admin – Daten: Zeiten-Import',
     'CSV-Import von Mitarbeiter-Arbeitszeiten. '
     'Sidebar: Daten → 📥 Zeiten-Import. Endpoint /zeiten-import.',
     'LESE_PFLEGE'),

    # Einkauf (Lieferanten + Bestellbestaetigungen)
    ('admin.einkauf.lieferanten', 'ADMIN',
     'Admin – Einkauf: Lieferanten',
     'Lieferanten-Stammdaten, Web-Zugaenge (Username/Pwd), '
     'Email-Patterns.', 'LESE_PFLEGE'),
    ('admin.einkauf.bestellungen', 'ADMIN',
     'Admin – Einkauf: Bestellbestaetigungen',
     'Eingegangene Bestellbestaetigungen sichten, Positionen pruefen, '
     'CAO-Sync ausloesen.', 'LESE_PFLEGE'),
    ('admin.einkauf.oauth',    'ADMIN',
     'Admin – Einkauf: Gmail-OAuth',
     'Gmail-OAuth-Token holen/loeschen (für Bestellbestaetigungs-'
     'Email-Polling).', 'LESE_PFLEGE'),
]


def seed_objekte() -> int:
    """Uebernimmt den Start-Katalog in ``DORFKERN_PERMISSION_OBJEKT``.

    Code = Source of Truth: ``INSERT ... ON DUPLICATE KEY UPDATE`` —
    Bezeichnung/Beschreibung/Unterscheidung aus ``_SEED_OBJEKTE``
    werden bei jedem App-Start nachgezogen. Der App-Spalten-Wert wird
    nicht überschrieben (zur Sicherheit, falls ein Object mal manuell
    umgezogen wurde).

    Returns: Anzahl Zeilen, die NEU angelegt wurden (cur.rowcount
    liefert bei einem Update 2, bei einem Insert 1).
    """
    anzahl_neu = 0
    anzahl_update = 0
    for key, app, bez, beschr, unt in _SEED_OBJEKTE:
        try:
            with get_db_transaction() as cur:
                cur.execute("""
                    INSERT INTO DORFKERN_PERMISSION_OBJEKT
                      (OBJEKT_KEY, APP, BEZEICHNUNG, BESCHREIBUNG,
                       UNTERSCHEIDUNG)
                    VALUES (%s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                      BEZEICHNUNG    = VALUES(BEZEICHNUNG),
                      BESCHREIBUNG   = VALUES(BESCHREIBUNG),
                      UNTERSCHEIDUNG = VALUES(UNTERSCHEIDUNG)
                """, (key, app, bez, beschr, unt))
                # rowcount: 1 = INSERT, 2 = UPDATE, 0 = unveraendert
                if cur.rowcount == 1:
                    anzahl_neu += 1
                elif cur.rowcount == 2:
                    anzahl_update += 1
        except Exception as exc:
            log.warning("seed_objekte: %s fehlgeschlagen: %s", key, exc)
    if anzahl_neu or anzahl_update:
        log.info("seed_objekte: %d neu, %d aktualisiert.",
                 anzahl_neu, anzahl_update)
    return anzahl_neu


# ── CAO-Rollen-Lookup ─────────────────────────────────────────────────────────

def rolle_von(ma_id: int) -> Optional[str]:
    """Ermittelt die CAO-Gruppe eines Mitarbeiters.

    Nutzt das gleiche Schema wie ``modules/orga/personal/auth.py``:
    ``BENUTZERRECHTE`` fuer den User (MODUL_ID=0, SUBMODUL_ID=0)
    joinen mit der Gruppen-Definitionszeile (USER_ID=-1) und dort
    den Gruppen-Namen aus ``MODUL_NAME`` lesen.

    Returns:
        Gruppenname (z.B. ``'Administratoren'``) oder ``None``, wenn
        Mitarbeiter nicht gefunden oder DB-Fehler.
    """
    if not ma_id:
        return None
    try:
        with get_db() as cur:
            cur.execute("""
                SELECT br_grp.MODUL_NAME AS rolle
                  FROM BENUTZERRECHTE AS br_user
                  JOIN BENUTZERRECHTE AS br_grp
                    ON br_grp.GRUPPEN_ID  = br_user.GRUPPEN_ID
                   AND br_grp.USER_ID     = -1
                   AND br_grp.MODUL_ID    = 0
                   AND br_grp.SUBMODUL_ID = 0
                 WHERE br_user.USER_ID     = %s
                   AND br_user.MODUL_ID    = 0
                   AND br_user.SUBMODUL_ID = 0
                 LIMIT 1
            """, (int(ma_id),))
            row = cur.fetchone()
            if row and row.get('rolle'):
                return str(row['rolle']).strip()
    except Exception as exc:
        log.warning("rolle_von(%s): DB-Fehler: %s", ma_id, exc)
    return None


# ── Rechtepruefung ────────────────────────────────────────────────────────────

def _request_cache_get():
    """Liefert den Per-Request-Cache fuer Permissions (oder None ausserhalb
    eines Flask-Request-Contexts). Wir cachen ``rolle_von`` und die ganze
    Permission-Map auf ``flask.g``, damit base.html mit ihren 18 hat_recht-
    Aufrufen pro Page-Render nicht 18-mal die DB anfasst — das hat unter
    MyFRITZ-NAT (~170ms pro DB-Roundtrip) bis zu 4s Sidebar-Latenz erzeugt.
    """
    try:
        from flask import g, has_request_context
        if not has_request_context():
            return None
        cache = getattr(g, '_perm_cache', None)
        if cache is None:
            cache = {}
            g._perm_cache = cache
        return cache
    except Exception:
        return None


def _permissions_fuer_rolle(rolle: str) -> dict[str, str]:
    """Liest alle (OBJEKT_KEY, RECHT) fuer eine Rolle in einem Query.
    Wird nur einmal pro Request gemacht und im g-Cache gehalten."""
    out: dict[str, str] = {}
    try:
        with get_db() as cur:
            cur.execute(
                "SELECT OBJEKT_KEY, RECHT "
                "  FROM DORFKERN_ROLLE_PERMISSION "
                " WHERE ROLLE = %s",
                (rolle,),
            )
            for r in cur.fetchall():
                out[str(r['OBJEKT_KEY'])] = str(r.get('RECHT') or '').upper()
    except Exception as exc:
        log.warning("permissions_fuer_rolle(%s): DB-Fehler: %s",
                    rolle, exc)
    return out


def hat_recht(ma_id: int, objekt_key: str,
              recht: str = 'BEIDES') -> bool:
    """Prueft, ob der Mitarbeiter das geforderte Recht auf ``objekt_key`` hat.

    Args:
        ma_id:       CAO-Mitarbeiter-ID.
        objekt_key:  Permission-Objekt (z.B. ``'kasse.storno'``).
        recht:       Gefordertes Recht (``'LESEN'``, ``'PFLEGEN'`` oder
                     ``'BEIDES'``). Default ``'BEIDES'`` – passt fuer
                     ``UNTERSCHEIDUNG='KEINE'``-Objekte.

    Returns:
        ``True``, wenn erlaubt; sonst ``False`` (fail-closed).

    Performance: Innerhalb eines Flask-Requests werden Rolle und
    Permissions-Map auf ``g`` gecached. Das druckt 18 hat_recht()-Calls
    in der Sidebar von 18 x 2 DB-Hits = 36 Roundtrips auf 2 Roundtrips.
    """
    if recht not in _VALID_RECHTE:
        log.warning("hat_recht: ungueltiges Recht %r", recht)
        return False

    cache = _request_cache_get()

    # 1) Rolle ermitteln (gecached)
    if cache is not None and 'rolle' in cache:
        rolle = cache['rolle']
    else:
        rolle = rolle_von(ma_id)
        if cache is not None:
            cache['rolle'] = rolle
    if rolle is None:
        return False

    # 2) Admin-Wildcard
    if rolle == ROLLE_ADMIN:
        return True

    # 3) Permission-Map fuer die Rolle (gecached, einmaliger Bulk-Lookup)
    if cache is not None and 'perms' in cache:
        perms = cache['perms']
    else:
        perms = _permissions_fuer_rolle(rolle)
        if cache is not None:
            cache['perms'] = perms

    gewaehrt = perms.get(objekt_key)
    if not gewaehrt:
        return False
    return recht in _DECKT_AB.get(gewaehrt, frozenset())


def erlaubte_objekte(ma_id: int,
                     app: Optional[str] = None) -> list[str]:
    """Listet alle OBJEKT_KEYs, auf die der Mitarbeiter Zugriff hat.

    Fuer ``Administratoren`` werden alle Objekte geliefert; sonst nur
    die, fuer die ein Eintrag in ``DORFKERN_ROLLE_PERMISSION`` existiert
    (egal mit welchem RECHT-Wert).

    Args:
        ma_id: CAO-Mitarbeiter-ID.
        app:   Optional auf ``KIOSK|KASSE|ORGA|ADMIN`` filtern.
    """
    rolle = rolle_von(ma_id)
    if rolle is None:
        return []
    try:
        with get_db() as cur:
            if rolle == ROLLE_ADMIN:
                sql = ("SELECT OBJEKT_KEY FROM DORFKERN_PERMISSION_OBJEKT")
                params: tuple = ()
                if app is not None:
                    sql += " WHERE APP = %s"
                    params = (app,)
            else:
                sql = ("SELECT rp.OBJEKT_KEY "
                       "FROM DORFKERN_ROLLE_PERMISSION rp "
                       "JOIN DORFKERN_PERMISSION_OBJEKT po "
                       "  ON po.OBJEKT_KEY = rp.OBJEKT_KEY "
                       "WHERE rp.ROLLE = %s")
                params = (rolle,)
                if app is not None:
                    sql += " AND po.APP = %s"
                    params = (rolle, app)
            sql += " ORDER BY OBJEKT_KEY"
            cur.execute(sql, params)
            return [r['OBJEKT_KEY'] for r in (cur.fetchall() or [])]
    except Exception as exc:
        log.warning("erlaubte_objekte(%s): DB-Fehler: %s", ma_id, exc)
        return []


# ── Admin-UI-Helfer ───────────────────────────────────────────────────────────

def objekte_alle(app: Optional[str] = None) -> list[dict]:
    """Alle Permission-Objekte (fuer die Admin-Matrix-UI)."""
    sql = ("SELECT OBJEKT_KEY, APP, BEZEICHNUNG, BESCHREIBUNG, "
           "UNTERSCHEIDUNG FROM DORFKERN_PERMISSION_OBJEKT")
    params: tuple = ()
    if app is not None:
        sql += " WHERE APP = %s"
        params = (app,)
    sql += " ORDER BY APP, OBJEKT_KEY"
    try:
        with get_db() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall() or [])
    except Exception as exc:
        log.warning("objekte_alle(): DB-Fehler: %s", exc)
        return []


def rolle_permissions(rolle: str) -> dict[str, str]:
    """Liefert ``{OBJEKT_KEY: RECHT}`` fuer eine Rolle. Leer fuer Admin."""
    if rolle == ROLLE_ADMIN:
        return {}
    try:
        with get_db() as cur:
            cur.execute(
                "SELECT OBJEKT_KEY, RECHT FROM DORFKERN_ROLLE_PERMISSION "
                "WHERE ROLLE = %s", (rolle,))
            return {r['OBJEKT_KEY']: str(r['RECHT'])
                    for r in (cur.fetchall() or [])}
    except Exception as exc:
        log.warning("rolle_permissions(%s): DB-Fehler: %s", rolle, exc)
        return {}


def set_rolle_permission(rolle: str, objekt_key: str, recht: str) -> None:
    """UPSERT eines Rolle-Objekt-Rechts (Admin-UI).

    Raises:
        ValueError: bei ungueltigem RECHT.
    """
    if recht not in _VALID_RECHTE:
        raise ValueError(
            f'RECHT muss {_VALID_RECHTE} sein, war {recht!r}')
    if rolle == ROLLE_ADMIN:
        # Admin-Permissions sind implizit – Schreibversuche sind ein Bug.
        log.info("set_rolle_permission: Admin-Zuweisung ignoriert (%s)",
                 objekt_key)
        return
    with get_db_transaction() as cur:
        cur.execute("""
            INSERT INTO DORFKERN_ROLLE_PERMISSION (ROLLE, OBJEKT_KEY, RECHT)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE RECHT = VALUES(RECHT)
        """, (rolle, objekt_key, recht))


def flask_helpers():
    """Liefert zwei Flask-Helfer fuer die Kiosk/Kasse/Orga-Apps.

    Die Apps binden das in ihrer ``app.py`` wie folgt ein::

        from common.permission import flask_helpers
        require_permission, _ctx = flask_helpers()
        app.context_processor(_ctx)

        @app.route('/storno')
        @require_permission('kasse.storno')
        def storno():
            ...

    Und im Template::

        {% if hat_recht('kiosk.backwaren') %}
          <a href="/backwaren">Backwaren</a>
        {% endif %}

    Dadurch bleibt der App-spezifische Teil in ``app.py`` und das
    Sidebar-Filtering ist im Jinja-Template.

    Rueckgabe:
        ``(require_permission, context_processor_fn)``.
    """
    from functools import wraps
    try:
        from flask import session, flash, redirect, url_for, request
    except ImportError as e:
        raise RuntimeError(
            'common.permission.flask_helpers() setzt Flask voraus.') from e

    def require_permission(objekt_key: str, recht: str = 'BEIDES'):
        """Decorator: fordert ``hat_recht(session.ma_id, ...)`` ein.

        Fehlendes Recht -> Flash-Message + Redirect auf '/'. API-Routen
        (erkennbar an Accept: application/json oder Pfad
        /api/) bekommen stattdessen HTTP 403.
        """
        def deko(view):
            @wraps(view)
            def wrapper(*args, **kwargs):
                ma_id = session.get('ma_id')
                if not ma_id or not hat_recht(ma_id, objekt_key, recht):
                    # API-Antwort als JSON mit 403, sonst Redirect
                    will_json = (
                        request.path.startswith('/api/')
                        or 'application/json' in (
                            request.headers.get('Accept', '') or '')
                    )
                    if will_json:
                        from flask import jsonify
                        return jsonify(
                            ok=False,
                            msg=f'Keine Berechtigung fuer {objekt_key}',
                        ), 403
                    flash(
                        f'Keine Berechtigung fuer {objekt_key}.', 'error')
                    try:
                        return redirect(url_for('index'))
                    except Exception:
                        return redirect('/')
                return view(*args, **kwargs)
            return wrapper
        return deko

    def _context_processor():
        """Liefert ``hat_recht(key, recht='BEIDES')`` in Jinja-Templates."""
        ma_id = session.get('ma_id') if session else None

        def _hat_recht(objekt_key: str, recht: str = 'BEIDES') -> bool:
            return bool(ma_id) and hat_recht(ma_id, objekt_key, recht)

        return {'hat_recht': _hat_recht}

    return require_permission, _context_processor


def loesche_rolle_permission(rolle: str, objekt_key: str) -> None:
    """Entfernt eine Rolle-Objekt-Zuweisung (Entzug)."""
    with get_db_transaction() as cur:
        cur.execute(
            "DELETE FROM DORFKERN_ROLLE_PERMISSION "
            "WHERE ROLLE = %s AND OBJEKT_KEY = %s",
            (rolle, objekt_key))
