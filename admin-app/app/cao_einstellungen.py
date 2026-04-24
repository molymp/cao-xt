"""
CAO-Einstellungen – Read-only Data-Access fuer die Admin-Ansicht.

Liest die ``REGISTRY``-Tabelle der CAO-DB und praesentiert die dort
abgelegten Anwendungseinstellungen strukturiert. Pflege erfolgt wie
gewohnt in ``cao_admin.exe`` (Menue *Einstellungen*); diese Ansicht
dient der Nachvollziehbarkeit.

REGISTRY-Schema (CAO-Faktura 1.5)::

    MAINKEY    varchar   Kategorie-Pfad (z.B. 'MAIN\\EMAIL')
    NAME       varchar   Einstellungsschluessel (z.B. 'SMTP_HOST')
    VAL_CHAR   varchar   Textwert
    VAL_DATE   date      Datumswert
    VAL_INT    integer   Primaerer INT-Wert
    VAL_INT2   integer   Zweiter INT-Wert (selten)
    VAL_INT3   integer   Dritter INT-Wert (selten)
    VAL_DOUBLE double    Fliesskommawert
    VAL_BLOB   blob      Freitext (z.B. Signaturen, Stadien-Listen)
    VAL_BIN    blob      Binaerwert
    VAL_TYP    varchar   Typ-Hinweis (selten gesetzt, optional)
    CACHABLE   smallint  1 = darf im CAO-Client gecached werden
    READONLY   smallint  1 = read-only (z.B. Installationsdefaults)

Die Kategorie-Tabelle (``_KATEGORIEN``) ordnet MAINKEY-Praefixen die im
``cao_admin.exe``-Einstellungsdialog sichtbaren deutschen Labels zu und
legt die Reihenfolge fest. Unbekannte MAINKEYs werden ans Ende sortiert.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from db import get_db

log = logging.getLogger(__name__)


# ── Kategorie-Katalog (MAINKEY → Label, Icon, Reihenfolge) ─────────────
# Quelle: cao_admin.exe – REGISTRY-Prefix-Strings + Einstellungsdialog-
# Kategorieliste. Nicht jede Dialog-Kategorie ist REGISTRY-backed (z.B.
# 'Zahlungsarten' liegt in der Tabelle ZAHLUNGSARTEN, nicht in REGISTRY);
# die entsprechenden Panels bekommen spaeter eigene Ansichten.
_KATEGORIEN: list[tuple[str, str, str]] = [
    # (MAINKEY, deutsches Label, Icon)
    ('MAIN',                       'Allgemein',            '⚙️'),
    ('MAIN\\ADRESSEN',             'Adressen',             '📇'),
    ('MAIN\\ADRESSEN\\USERFELDER', 'Adressen – Userfelder', '📇'),
    ('MAIN\\ARTIKEL',              'Artikel',              '📦'),
    ('MAIN\\ARTIKEL\\USERFELDER',  'Artikel – Userfelder', '📦'),
    ('MAIN\\KFZ\\USERFELDER',      'KFZ – Userfelder',     '🚗'),
    ('MAIN\\BELEGE',               'Belege / Kopf- & Fußtexte', '📄'),
    ('MAIN\\NUMBERS',              'Nummernkreise',        '#️⃣'),
    ('MAIN\\MWST',                 'MwSt-Saetze',          '💰'),
    ('MAIN\\WAEHRUNG',             'Waehrung',             '💱'),
    ('MAIN\\FIBU',                 'Fibu',                 '📊'),
    ('FIBU',                       'Fibu (legacy)',        '📊'),
    ('MAIN\\KONTEN',               'Kontenrahmen',         '🏦'),
    ('MAIN\\EMAIL',                'EMail-Einstellungen',  '✉️'),
    ('MAIN\\PFADE',                'Verzeichnisse',        '📁'),
    ('MAIN\\TELEFONIE',            'Telefonie (TAPI)',     '📞'),
    ('MAIN\\AUTOWV',               'Autom. Wiedervorlage', '🔁'),
    ('MAIN\\MAHNUNG',              'Mahnungen',            '⚠️'),
    ('MAIN\\GFK_EXPORT',           'GFK-Export',           '📤'),
    ('MAIN\\EXPORT',               'Export',               '📤'),
    ('MAIN\\AUFBEWAHRUNGSFRISTEN', 'Datenbereinigung',     '🗑️'),
    ('MAIN\\BACKUP',               'Backup',               '💾'),
    ('MAIN\\SICHERUNG',            'Sicherung',            '🛡️'),
    ('MAIN\\PROJEKTE',             'Projektverwaltung',    '📋'),
    ('MAIN\\PIM',                  'PIM',                  '🗓️'),
    ('MAIN\\REPORT',               'Report-Texte',         '📝'),
    ('MAIN\\MODULE\\ERECHNUNG',    'Modul E-Rechnung',     '🧾'),
    ('MAIN\\TERMINAL',             'Terminal',             '💻'),
    ('MAIN\\ENDS',                 'Modul-Abschluss',      '🚪'),
    ('MAIN\\ENDSWGR',              'Warengruppen-Abschluss', '🚪'),
    ('MODUL',                      'Module (Flags)',       '🧩'),
    ('SHOP',                       'Shop-Transfer',        '🛒'),
    ('BINAER',                     'Binaerdaten',          '🗄️'),
]

# Schneller Lookup: MAINKEY → (Label, Icon, Sortier-Index).
_KATEGORIE_INFO: dict[str, tuple[str, str, int]] = {
    mk: (label, icon, idx) for idx, (mk, label, icon) in enumerate(_KATEGORIEN)
}


def kategorie_fuer(mainkey: str) -> tuple[str, str, int]:
    """MAINKEY → (Label, Icon, Sortier-Index).

    Unbekannte MAINKEYs erhalten ein generisches Label und den Sortier-
    Index ``len(_KATEGORIEN)`` (ganz am Ende).
    """
    info = _KATEGORIE_INFO.get(mainkey)
    if info is not None:
        return info
    return (mainkey or '(ohne Kategorie)', '❓', len(_KATEGORIEN))


# ── Typ-Erkennung und Wert-Extraktion ──────────────────────────────────
# REGISTRY-Spalten in Priorisierungs-Reihenfolge (Typ, DB-Spalte, Label).
_WERT_SPALTEN: list[tuple[str, str]] = [
    ('char',   'VAL_CHAR'),
    ('int',    'VAL_INT'),
    ('int2',   'VAL_INT2'),
    ('int3',   'VAL_INT3'),
    ('double', 'VAL_DOUBLE'),
    ('date',   'VAL_DATE'),
    ('blob',   'VAL_BLOB'),
    ('bin',    'VAL_BIN'),
]


def wert_extrahieren(row: dict) -> tuple[Optional[str], str]:
    """Ermittelt den primaeren Wert und seinen Typ aus einer REGISTRY-Zeile.

    Strategie: die erste nicht-``NULL`` Spalte aus ``_WERT_SPALTEN``
    gewinnt. ``VAL_TYP`` liefert einen ergaenzenden Hinweis, wenn mehrere
    Spalten belegt waeren – wir nehmen ihn zusaetzlich als Label mit.

    Rueckgabe: ``(wert_als_str_oder_None, typ_label)`` – ``typ_label``
    ist z.B. ``"int"``, ``"char"``, ``"blob (1234 Bytes)"``.
    """
    for typ, spalte in _WERT_SPALTEN:
        v = row.get(spalte)
        if v is None:
            continue
        if typ in ('blob', 'bin'):
            try:
                laenge = len(v)
            except TypeError:
                laenge = -1
            # Blob-Inhalt bei Bedarf als UTF-8 zeigen, sonst nur Metadaten.
            anzeige: Optional[str]
            try:
                if isinstance(v, (bytes, bytearray)):
                    txt = bytes(v).decode('utf-8', errors='replace')
                else:
                    txt = str(v)
                # Nur die ersten ~4000 Zeichen durchreichen – reicht fuer
                # Signaturen/Stadien-Listen und verhindert Megabyte-Dumps.
                anzeige = txt[:4000] + ('…' if len(txt) > 4000 else '')
            except Exception:
                anzeige = None
            return anzeige, f'{typ} ({laenge} Bytes)'
        return (str(v) if v is not None else None), typ
    return None, '(leer)'


# ── DB-Zugriff ──────────────────────────────────────────────────────────
def registry_laden() -> list[dict[str, Any]]:
    """Liest die gesamte REGISTRY-Tabelle.

    Rueckgabe: Liste von Dicts pro Eintrag mit den Feldern
    ``mainkey``, ``name``, ``wert``, ``typ``, ``cachable``, ``readonly``.
    Sortierung: gruppiert nach Kategorie-Sortier-Index, dann MAINKEY,
    dann NAME.
    """
    with get_db() as cur:
        cur.execute(
            """
            SELECT MAINKEY, NAME, VAL_CHAR, VAL_INT, VAL_INT2, VAL_INT3,
                   VAL_DOUBLE, VAL_DATE, VAL_BLOB, VAL_BIN, VAL_TYP,
                   CACHABLE, READONLY
            FROM REGISTRY
            ORDER BY MAINKEY, NAME
            """
        )
        rows = cur.fetchall() or []

    ergebnis: list[dict[str, Any]] = []
    for r in rows:
        # MySQL-Connector liefert dicts mit Originalspaltennamen.
        mainkey = (r.get('MAINKEY') or '').strip()
        name    = (r.get('NAME') or '').strip()
        wert, typ = wert_extrahieren(r)
        val_typ_hinweis = r.get('VAL_TYP')
        if val_typ_hinweis:
            typ = f'{typ} / VAL_TYP={val_typ_hinweis}'
        ergebnis.append({
            'mainkey':   mainkey,
            'name':      name,
            'wert':      wert,
            'typ':       typ,
            'cachable':  bool(r.get('CACHABLE')),
            'readonly':  bool(r.get('READONLY')),
        })
    return ergebnis


def gruppiert_nach_kategorie() -> list[dict[str, Any]]:
    """REGISTRY-Eintraege in Kategorien gruppiert, fertig fuers Template.

    Jede Kategorie enthaelt ``mainkey``, ``label``, ``icon`` und
    ``eintraege`` (Liste). Leere Kategorien (aus ``_KATEGORIEN``, ohne
    DB-Zeilen) werden nicht zurueckgegeben. Unbekannte MAINKEYs aus der
    DB bekommen eine generische Kategorie.
    """
    eintraege = registry_laden()
    bucket: dict[str, list[dict[str, Any]]] = {}
    for e in eintraege:
        bucket.setdefault(e['mainkey'], []).append(e)

    # Sortiere nach Kategorie-Index.
    kategorien: list[dict[str, Any]] = []
    for mainkey in sorted(bucket.keys(),
                          key=lambda mk: (kategorie_fuer(mk)[2], mk)):
        label, icon, _idx = kategorie_fuer(mainkey)
        kategorien.append({
            'mainkey':   mainkey,
            'label':     label,
            'icon':      icon,
            'eintraege': bucket[mainkey],
        })
    return kategorien
