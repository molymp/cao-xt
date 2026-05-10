"""
CAO `BINAERDATEN` — gemeinsame Schreib-/Lese-Helper.

`BINAERDATEN` ist die zentrale CAO-Tabelle fuer Datei-Anhaenge (BLOB
in der DB). CAO selbst nutzt sie u.a. fuer Artikel-Bilder im Stamm-
daten-Reiter "Dateilinks". Wir nutzen sie zusaetzlich:

* fuer Lieferanten-Bild-Cache (XT-Sonder-MODUL_ID 91020)
* nach dem Stammdaten-Match: Umtaggen auf MODUL_ID=1020 (Artikel) +
  REFERENZ_ID=ARTIKEL.REC_ID, damit CAO-Faktura die Bilder direkt sieht

Schema-Doku: ``memory/reference_cao_binaerdaten.md``.

MyISAM-Disziplin: kein Rollback. Beim Re-Import desselben Bildes
zuerst DELETE, dann INSERT (siehe ``binaer_speichern_oder_ersetzen``).
"""
from __future__ import annotations

import datetime
import logging
import os
from typing import Optional

from .db import get_db

log = logging.getLogger(__name__)


# ── MODUL_ID-Konstanten (Auszug, vollstaendig in reference_cao_binaerdaten.md)
MODUL_ID_ADRESSEN     = 1010
MODUL_ID_ARTIKEL      = 1020
MODUL_ID_MITARBEITER  = 1040
MODUL_ID_NOTIZEN      = 1060
MODUL_ID_EINKAUF      = 2050
MODUL_ID_WARENEINGANG = 2065

# XT-eigener Bereich >= 90000 (CAO ignoriert unbekannte MODUL_IDs).
MODUL_ID_XT_LIEF_ARTIKEL_CACHE = 91020


# ── BINAER_KATEGORIE (von CAO vorbefuellt) ────────────────────────────
KATEGORIE_BILD       = 1
KATEGORIE_DOKUMENT   = 2
KATEGORIE_SONSTIGES  = 3


# Standard-Typname fuer Produktbilder. Wird beim ersten run_migration()
# in BINAER_TYPEN angelegt, danach immer per Cache-Lookup verwendet.
TYP_NAME_PRODUKTBILD = 'Produktbild'
TYP_FARBE_PRODUKTBILD = '#1a4010'

_TYP_CACHE: dict[str, int] = {}


def run_migration() -> None:
    """Legt fehlende BINAER_TYPEN-Eintraege an. Idempotent.

    Voraussetzung: BINAERDATEN/BINAER_TYPEN/BINAER_KATEGORIE existieren
    bereits (von CAO-Faktura mitgeliefert). Wir fuegen lediglich unsere
    Standard-Typen hinzu.
    """
    with get_db() as cur:
        # BINAER_TYPEN existiert? (nicht jede DB hat es)
        cur.execute("""
            SELECT COUNT(*) AS n FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'BINAER_TYPEN'
        """)
        if int((cur.fetchone() or {}).get('n', 0)) == 0:
            log.info(
                "BINAER_TYPEN nicht vorhanden — ueberspringe Init "
                "(keine CAO-DB?)")
            return
        # 'Produktbild' anlegen, falls fehlt
        cur.execute("""
            SELECT REC_ID FROM BINAER_TYPEN WHERE NAME = %s LIMIT 1
        """, (TYP_NAME_PRODUKTBILD,))
        row = cur.fetchone()
        if row is None:
            cur.execute("""
                INSERT INTO BINAER_TYPEN (NAME, FARBE, KATEGORIE_ID)
                VALUES (%s, %s, %s)
            """, (TYP_NAME_PRODUKTBILD, TYP_FARBE_PRODUKTBILD,
                  KATEGORIE_BILD))
            log.info("BINAER_TYPEN: '%s' angelegt.",
                     TYP_NAME_PRODUKTBILD)


def typ_id_holen(name: str) -> int:
    """Liefert REC_ID aus BINAER_TYPEN per Name. Cached.

    Wirft KeyError, wenn der Typ nicht existiert (run_migration nicht
    gelaufen).
    """
    if name in _TYP_CACHE:
        return _TYP_CACHE[name]
    with get_db() as cur:
        cur.execute("SELECT REC_ID FROM BINAER_TYPEN WHERE NAME = %s",
                    (name,))
        row = cur.fetchone()
    if not row:
        raise KeyError(
            f"BINAER_TYPEN: '{name}' nicht gefunden — "
            "run_migration() vergessen?")
    _TYP_CACHE[name] = int(row['REC_ID'])
    return _TYP_CACHE[name]


def _format_groesse(b: int) -> str:
    """Anzeige-formatierte Groesse, wie CAO sie in DATEIGROESSE schreibt."""
    if b < 1024:
        return f"{b} Byte"
    if b < 1024 * 1024:
        return f"{round(b / 1024, 1):.1f} KB"
    if b < 1024 * 1024 * 1024:
        return f"{round(b / (1024 * 1024), 1):.1f} MB"
    return f"{round(b / (1024 * 1024 * 1024), 1):.1f} GB"


def binaer_speichern_oder_ersetzen(
    *,
    modul_id: int,
    referenz_id: int,
    binaer_typ: int,
    pfad: str,
    datei: str,
    daten: bytes,
    kurztext: Optional[str] = None,
    primaer: bool = False,
    erst_name: str = 'CAO-XT',
) -> int:
    """Schreibt BLOB in BINAERDATEN, ersetzt vorhandenen Eintrag mit
    gleichem (MODUL_ID, REFERENZ_ID, DATEI). Liefert die neue REC_ID.

    Idempotent (MyISAM-konform): DELETE existing → INSERT neu.
    """
    bytegroesse = len(daten)
    dateigroesse_str = _format_groesse(bytegroesse)
    with get_db() as cur:
        # Existierende Variante mit gleichem Dateinamen weg
        cur.execute("""
            DELETE FROM BINAERDATEN
            WHERE MODUL_ID = %s AND REFERENZ_ID = %s AND DATEI = %s
        """, (modul_id, referenz_id, datei))
        cur.execute("""
            INSERT INTO BINAERDATEN
              (MODUL_ID, REFERENZ_ID, BINAER_TYP, KURZTEXT, PFAD, DATEI,
               DATEIGROESSE, DATEN, PRIMAER, ERSTELLT, ERST_NAME, BYTEGROESSE)
            VALUES
              (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s, %s)
        """, (modul_id, referenz_id, binaer_typ, kurztext, pfad, datei,
              dateigroesse_str, daten, 1 if primaer else 0,
              erst_name, bytegroesse))
        cur.execute("SELECT LAST_INSERT_ID() AS id")
        return int(cur.fetchone()['id'])


def binaer_primaer_ersetzen(
    *,
    modul_id: int,
    referenz_id: int,
    binaer_typ: int,
    pfad: str,
    datei: str,
    daten: bytes,
    kurztext: Optional[str] = None,
    erst_name: str = 'CAO-XT',
) -> int:
    """Ersetzt das ``PRIMAER=1``-Bild fuer (MODUL_ID, REFERENZ_ID).

    Mehrere Anhaenge pro Datensatz sind erlaubt — aber genau einer ist
    das "Hauptbild" (PRIMAER=1). Diese Funktion loescht ein
    eventuelles altes Hauptbild und legt das neue als PRIMAER=1 an.
    Liefert die ``REC_ID`` der neuen Zeile.

    Idempotent: bei Re-Aufruf mit identischem ``daten`` wird das alte
    Hauptbild ersetzt — Re-Aufruf veraendert die DB also nicht
    inhaltlich, nur die REC_ID rotiert.
    """
    bytegroesse = len(daten)
    dateigroesse_str = _format_groesse(bytegroesse)
    with get_db() as cur:
        cur.execute("""
            DELETE FROM BINAERDATEN
            WHERE MODUL_ID = %s AND REFERENZ_ID = %s AND PRIMAER = 1
        """, (modul_id, referenz_id))
        cur.execute("""
            INSERT INTO BINAERDATEN
              (MODUL_ID, REFERENZ_ID, BINAER_TYP, KURZTEXT, PFAD, DATEI,
               DATEIGROESSE, DATEN, PRIMAER, ERSTELLT, ERST_NAME, BYTEGROESSE)
            VALUES
              (%s, %s, %s, %s, %s, %s, %s, %s, 1, NOW(), %s, %s)
        """, (modul_id, referenz_id, binaer_typ, kurztext, pfad, datei,
              dateigroesse_str, daten, erst_name, bytegroesse))
        cur.execute("SELECT LAST_INSERT_ID() AS id")
        return int(cur.fetchone()['id'])


def binaer_primaer_loeschen(modul_id: int, referenz_id: int) -> int:
    """Loescht das Hauptbild fuer (MODUL_ID, REFERENZ_ID). Liefert die
    Anzahl geloeschter Zeilen (0 oder 1)."""
    with get_db() as cur:
        cur.execute("""
            DELETE FROM BINAERDATEN
            WHERE MODUL_ID = %s AND REFERENZ_ID = %s AND PRIMAER = 1
        """, (modul_id, referenz_id))
        return cur.rowcount


def binaer_primaer_holen(modul_id: int,
                          referenz_id: int) -> Optional[dict]:
    """Liefert das Hauptbild-Tupel oder None (REC_ID, DATEI, DATEN, ...).
    """
    with get_db() as cur:
        cur.execute("""
            SELECT REC_ID, DATEI, PFAD, DATEN, BYTEGROESSE, ERSTELLT
            FROM BINAERDATEN
            WHERE MODUL_ID = %s AND REFERENZ_ID = %s AND PRIMAER = 1
            LIMIT 1
        """, (modul_id, referenz_id))
        return cur.fetchone()


def binaer_holen(rec_id: int) -> Optional[dict]:
    """Liefert BLOB + Metadaten zu einem REC_ID, oder None.

    Felder: REC_ID, MODUL_ID, REFERENZ_ID, DATEI, DATEN (bytes),
    BYTEGROESSE, ERSTELLT.
    """
    with get_db() as cur:
        cur.execute("""
            SELECT REC_ID, MODUL_ID, REFERENZ_ID, BINAER_TYP, DATEI,
                   PFAD, DATEN, BYTEGROESSE, ERSTELLT
            FROM BINAERDATEN
            WHERE REC_ID = %s
        """, (rec_id,))
        return cur.fetchone()


def binaer_loeschen(rec_id: int) -> None:
    with get_db() as cur:
        cur.execute("DELETE FROM BINAERDATEN WHERE REC_ID = %s",
                    (rec_id,))


def binaer_umtaggen(rec_id: int, neue_modul_id: int,
                    neue_referenz_id: int) -> None:
    """Verschiebt einen BLOB-Datensatz auf eine andere
    (MODUL_ID, REFERENZ_ID)-Verknuepfung — typischer Anwendungsfall:
    Lieferanten-Cache-Bild auf einen frisch angelegten CAO-ARTIKEL.REC_ID
    umtaggen, damit es im Artikelstamm sichtbar wird.
    """
    with get_db() as cur:
        cur.execute("""
            UPDATE BINAERDATEN
               SET MODUL_ID = %s, REFERENZ_ID = %s
             WHERE REC_ID = %s
        """, (neue_modul_id, neue_referenz_id, rec_id))


def mime_aus_dateiname(dateiname: str) -> str:
    """Mapped Endung → MIME-Type (mit Fallback). Bewusst schmaler als
    ``mimetypes.guess_type``, damit wir Browser-konsistent bleiben."""
    ext = os.path.splitext(dateiname or '')[1].lower().lstrip('.')
    return {
        'jpg':  'image/jpeg', 'jpeg': 'image/jpeg',
        'png':  'image/png',  'gif':  'image/gif',
        'webp': 'image/webp', 'svg':  'image/svg+xml',
        'bmp':  'image/bmp',  'ico':  'image/x-icon',
        'tiff': 'image/tiff', 'tif':  'image/tiff',
        'pdf':  'application/pdf',
    }.get(ext, 'application/octet-stream')
