"""
CAO-Rechte – Read-only Data-Access fuer die Admin-Ansicht.

Liest den BENUTZERRECHTE-Katalog direkt aus der CAO-DB. Pflege erfolgt
ausschliesslich in ``cao_admin.exe``; diese Ansicht dient nur der
Nachvollziehbarkeit, welche CAO-Gruppe welches Modul darf.

Semantik der ``BENUTZERRECHTE``-Zeilen::

    USER_ID = -1  AND MODUL_ID = 0  AND SUBMODUL_ID = 0  → Gruppen-Definition
    USER_ID = -1  AND MODUL_ID > 0                       → Gruppen-Recht
    GRUPPEN_ID = -1  AND USER_ID > 0                     → User-Override
    USER_ID > 0   AND MODUL_ID = 0  AND SUBMODUL_ID = 0  → User→Gruppe-Mapping

Bitmasken in ``RECHTE`` (``bigint unsigned``) sind modul-spezifisch.
Wir haben sie direkt aus ``cao_admin.exe`` extrahiert:

* Bit-Label-Array (Delphi-UnicodeString-Literal): 16 Labels pro Array;
  Array-A deckt praktisch alle Module ab, Array-B ist fuer Kasse-spezifische
  Checkboxen (siehe ``_ARRAY_STANDARD`` / ``_ARRAY_KASSE``).
* Default-RECHTE je ``(MODUL_ID, SUBMODUL_ID)`` aus den eingebackenen
  INSERT-Statements (``_MODUL_DEFAULT_MASK``). Diese Maske definiert,
  welche Bits CAO fuer das Modul ueberhaupt als Checkboxen anzeigt.

Unbekannte Module erhalten als Fallback nur ``Bit 0 = „Modul aufrufen"``.
"""
from __future__ import annotations

import logging
from typing import Optional

from db import get_db

log = logging.getLogger(__name__)

# ── Kategorie-Header (MODUL_ID // 1000 * 1000 → Label) ────────────────────────
# Quelle: BENUTZERRECHTE-Definitionen in CAO-Faktura + empirischer Abgleich
# mit den cao_XT_DEV-Daten. Nicht alle Kategorien haben eine eigene Zeile in
# der DB, daher hardcoded Fallback.
_KATEGORIEN: list[tuple[int, str]] = [
    (1000,  'Stammdaten'),
    (2000,  'Vorgänge'),
    (3000,  'Journale'),
    (4000,  'Finanzen'),
    (5000,  'Tools'),
    (6000,  'Projektverwaltung'),
    (9000,  'Spezial'),
    (10000, 'Kasse'),
    (12000, 'Projekt-Zeiten'),
]


# ── Bit-Label-Arrays (aus cao_admin.exe extrahiert) ────────────────────────
# CAO-Admin hat zwei 16-Bit-Label-Arrays als Delphi-UnicodeString-Literale im
# Binary. Array-A wird fuer praktisch alle Module verwendet. Array-B ist
# speziell fuer Kassenbuch-artige Module (aktuell keine bekannte Zuordnung
# im beobachteten Datenbestand — reserviert).
_ARRAY_STANDARD: dict[int, str] = {
    0:  'Modul aufrufen',
    1:  'Datensatz ändern',
    2:  'Datensatz neu',
    3:  'Datensatz löschen bzw. Storno',
    4:  'Erlaubt',
    5:  'Anzeigen',
    6:  'frei 6',
    7:  'frei 7',
    8:  'EK-Preise anzeigen',
    9:  'EK-Preise ändern',
    10: 'Import',
    11: 'Export',
    12: 'Vorgang abschließen',
    13: 'Drucken',
    14: 'Formulare bearbeiten',
    15: 'frei 15',
}

_ARRAY_KASSE: dict[int, str] = {
    0:  'Modul aufrufen',
    1:  'Kassenbuch',
    2:  'Kassenbuch Storno',
    3:  'Kassensturz',
    4:  'Erlaubt',
    5:  'Anzeigen',
    6:  'frei 6',
    7:  'frei 7',
    8:  'Kassenabschluss Z-Bon',
    9:  'Zwischenbericht X-Bon',
    10: 'Kassenjournal',
    11: 'Export Kassenjournal',
    12: 'Kassenprotokoll',
    13: 'Unbelegt',
    14: 'frei 15',
}

# ── Default-RECHTE je (MODUL_ID, SUBMODUL_ID) ──────────────────────────────
# Aus den INSERT-Statements in cao_admin.exe ausgelesen. Zweck: zu wissen,
# *welche* Bits fuer ein Modul ueberhaupt definiert sind — CAO zeigt im UI
# nur genau diese Checkboxen an. Der konkret gesetzte Wert in BENUTZERRECHTE
# ist davon unabhaengig und wird fuer die Anzeige mit der Maske verundet.
_MODUL_DEFAULT_MASK: dict[tuple[int, int], int] = {
    # Stammdaten
    (1010, 0): 27663, (1010, 1): 15, (1010, 2): 15, (1010, 3): 15,
    (1010, 9): 1,
    (1020, 0): 28431, (1020, 1): 15, (1020, 2): 3, (1020, 3): 15,
    (1020, 4): 15, (1020, 5): 15, (1020, 6): 15, (1020, 8): 15,
    (1020, 9): 15, (1020, 10): 15, (1020, 11): 15, (1020, 12): 15,
    (1020, 13): 15, (1020, 98): 15, (1020, 99): 1,
    (1030, 0): 15, (1040, 0): 15, (1050, 0): 1, (1060, 0): 15,
    (1070, 0): 15, (1990, 0): 1,
    # Verkauf / Vorgaenge
    (2010, 0): 20495, (2020, 0): 20495, (2030, 0): 20495,
    (2040, 0): 20495, (2045, 0): 20495, (2050, 0): 20495,
    (2060, 0): 20495, (2070, 0): 20495, (2080, 0): 28679,
    (2090, 0): 24591, (2100, 0): 20495,
    # Journale
    (3010, 0): 24587, (3020, 0): 24587, (3030, 0): 24587,
    (3040, 0): 24587, (3050, 0): 24585, (3060, 0): 24587,
    (3100, 0): 24587, (3110, 0): 24587, (3120, 0): 24587,
    # Finanzen
    (4010, 0): 24591, (4020, 0): 16397, (4030, 0): 16389,
    (4040, 0): 4103,  (4050, 0): 4103,  (4060, 0): 6145,
    # Tools
    (5010, 0): 8193,  (5020, 0): 3073,  (5030, 0): 12295,
    (5040, 0): 10255, (5050, 0): 15,
    # Spezial
    (9010, 0): 1, (9020, 0): 1, (9030, 0): 1, (9040, 0): 1,
    (9060, 0): 1, (9070, 0): 1, (9080, 0): 1,
    # Kasse
    (10010, 0): 28673,
    (10100, 0): 1, (10101, 0): 1, (10102, 0): 1, (10103, 0): 1,
    (10104, 0): 1, (10105, 0): 1, (10106, 0): 1, (10107, 0): 1,
    (10108, 0): 1,
    (10200, 0): 783, (10300, 0): 15,
    (10910, 0): 1, (10920, 0): 1, (10925, 0): 1,
    (10960, 0): 1, (10970, 0): 1,
}

# Zuordnung MODUL_ID → Label-Array. Default ist ARRAY_STANDARD; nur Module,
# die nachweislich eine andere Beschriftung haben, bekommen einen Override.
# (Aktuell keine verifizierten Kandidaten fuer _ARRAY_KASSE.)
_MODUL_ARRAY_OVERRIDE: dict[int, dict[int, str]] = {}

# Universelle Bit-0-Bedeutung ueber alle Module (Fallback bei unbekannter
# MODUL_ID).
_BIT_0_LABEL = 'Modul aufrufen'


def kategorie_fuer(modul_id: int) -> tuple[int, str]:
    """Liefert (kategorie_id, kategorie_label) fuer eine MODUL_ID.

    Rundet auf die naechst-kleinere 1000er-Grenze ab und sucht in der
    Kategorien-Tabelle. Fallback: ``(0, 'Sonstige')``.
    """
    kat = (modul_id // 1000) * 1000
    for kid, label in _KATEGORIEN:
        if kid == kat:
            return kid, label
    return 0, 'Sonstige'


def bit_labels(modul_id: int, submodul_id: int = 0) -> dict[int, str]:
    """Liefert die fuer ein (Sub-)Modul gueltigen Bit-Labels.

    Das Ergebnis enthaelt *nur* die Bits, die CAO fuer dieses Modul als
    Checkbox anzeigt (ermittelt aus der Default-Maske in cao_admin.exe).
    Labels stammen aus dem passenden Bit-Array (Standard oder Kasse).

    Fuer unbekannte Module gibt es mindestens Bit 0 (universell).
    """
    maske = _MODUL_DEFAULT_MASK.get((modul_id, submodul_id))
    array = _MODUL_ARRAY_OVERRIDE.get(modul_id, _ARRAY_STANDARD)
    if maske is None:
        return {0: _BIT_0_LABEL}
    ergebnis: dict[int, str] = {}
    for bit in range(16):
        if maske & (1 << bit):
            ergebnis[bit] = array.get(bit, f'Bit {bit}')
    # Sicherstellen, dass Bit 0 enthalten ist (sollte durch Maske schon
    # gegeben sein, aber doppelt halten ist billiger als der Support-Fall).
    ergebnis.setdefault(0, _BIT_0_LABEL)
    return ergebnis


def rechte_zu_bits(rechte: int, modul_id: int,
                   submodul_id: int = 0) -> list[dict]:
    """Zerlegt einen RECHTE-Wert in Einzelbits mit Labels.

    Gibt saemtliche fuer das (Sub-)Modul bekannten Bits aus – auch solche,
    die aktuell *nicht* gesetzt sind. So sieht der User in der UI auch
    nicht vergebene Rechte mit Namen. Unbekannte *gesetzte* Bits werden
    angehangen (label=None), damit nichts verborgen bleibt.

    Returns:
        Liste von ``{'bit': n, 'gesetzt': bool, 'label': str|None}``.
    """
    labels = bit_labels(modul_id, submodul_id)
    eintraege: list[dict] = []
    bekannte_bits = set(labels.keys())
    # Bekannte Bits zuerst, der Reihe nach.
    for bit in sorted(bekannte_bits):
        eintraege.append({
            'bit': bit,
            'gesetzt': bool(rechte & (1 << bit)),
            'label': labels[bit],
        })
    # Unbekannte gesetzte Bits anhaengen, damit nichts verborgen bleibt.
    for bit in range(64):
        if bit in bekannte_bits:
            continue
        if rechte & (1 << bit):
            eintraege.append({
                'bit': bit,
                'gesetzt': True,
                'label': None,
            })
    return eintraege


# ── DB-Lesefunktionen ─────────────────────────────────────────────────────────

def gruppen_laden() -> list[dict]:
    """Alle CAO-Gruppen. Gruppen-Definitionszeile: USER_ID=-1 AND MODUL_ID=0."""
    try:
        with get_db() as cur:
            cur.execute("""
                SELECT GRUPPEN_ID, MODUL_NAME AS NAME, BEMERKUNG, RECHTE
                  FROM BENUTZERRECHTE
                 WHERE USER_ID=-1 AND MODUL_ID=0 AND SUBMODUL_ID=0
                 ORDER BY GRUPPEN_ID
            """)
            return list(cur.fetchall() or [])
    except Exception as exc:
        log.warning("gruppen_laden: %s", exc)
        return []


def _modul_name_lookup() -> dict[tuple[int, int], str]:
    """Liefert {(modul_id, submodul_id): name} aus allen Zeilen.

    Auswahl:
    - Fuer ``(mid, 0)`` (Modul-Haupt-Eintrag): bevorzuge ``MODUL_NAME``;
      faellt sonst auf ``SUBMODUL_NAME`` zurueck.
    - Fuer ``(mid, sid > 0)`` (Sub-Eintrag): bevorzuge ``SUBMODUL_NAME``,
      weil ``MODUL_NAME`` hier oft den Namen des uebergeordneten Moduls
      wiederholt (z.B. steht auf der Sub=1-Zeile von 1010 Adressen
      ``MODUL_NAME='Adressen'`` und ``SUBMODUL_NAME='Erweitert'``).
    """
    try:
        with get_db() as cur:
            cur.execute("""
                SELECT MODUL_ID, SUBMODUL_ID, MODUL_NAME, SUBMODUL_NAME
                  FROM BENUTZERRECHTE
                 WHERE MODUL_ID > 0
            """)
            rows = cur.fetchall() or []
    except Exception as exc:
        log.warning("_modul_name_lookup: %s", exc)
        return {}
    ergebnis: dict[tuple[int, int], str] = {}
    for r in rows:
        mid = r['MODUL_ID']
        sid = r['SUBMODUL_ID']
        schluessel = (mid, sid)
        if schluessel in ergebnis:
            continue
        mname = (r['MODUL_NAME'] or '').strip() or None
        sname = (r['SUBMODUL_NAME'] or '').strip() or None
        if sid > 0:
            name = sname or mname
        else:
            name = mname or sname
        if name:
            ergebnis[schluessel] = name
    return ergebnis


def modul_baum(gruppe_id: int) -> list[dict]:
    """Liefert den Modul-Baum fuer eine Gruppe.

    Struktur::

        [
          {kategorie_id, kategorie_name, module: [
            {modul_id, name, rechte, submodule: [
              {modul_id, submodul_id, name, rechte}
            ]}
          ]}
        ]

    Administratoren (GRP=1) haben meist keine Detail-Zeilen, nur pauschale
    ``RECHTE=65535`` in der Definitionszeile → wir leiten ihren Rechte-Wert
    fuer alle Module aus dieser Pauschale ab.
    """
    namen = _modul_name_lookup()

    # Gruppenrechte (Detailzeilen) laden.
    rechte_map: dict[tuple[int, int], int] = {}
    try:
        with get_db() as cur:
            cur.execute("""
                SELECT MODUL_ID, SUBMODUL_ID, RECHTE
                  FROM BENUTZERRECHTE
                 WHERE USER_ID=-1 AND GRUPPEN_ID=%s AND MODUL_ID>0
            """, (int(gruppe_id),))
            for r in cur.fetchall() or []:
                rechte_map[(r['MODUL_ID'], r['SUBMODUL_ID'])] = int(r['RECHTE'])
    except Exception as exc:
        log.warning("modul_baum(%s): %s", gruppe_id, exc)

    # Admin-Pauschale auflesen.
    admin_pauschale: Optional[int] = None
    if int(gruppe_id) == 1:
        try:
            with get_db() as cur:
                cur.execute("""
                    SELECT RECHTE FROM BENUTZERRECHTE
                     WHERE USER_ID=-1 AND GRUPPEN_ID=1
                       AND MODUL_ID=0 AND SUBMODUL_ID=0
                     LIMIT 1
                """)
                row = cur.fetchone()
                if row:
                    admin_pauschale = int(row['RECHTE'])
        except Exception:
            pass

    # Alle (MODUL_ID, SUBMODUL_ID)-Kombinationen aus der Namens-Lookup
    # zusammensetzen — das ist unser Katalog.
    # Modul-ID bekommt SUB=0 als "Haupt-Eintrag".
    katalog: dict[int, set[int]] = {}
    for (mid, sid) in namen.keys():
        katalog.setdefault(mid, set()).add(sid)
    # Sicherstellen, dass jedes Modul mindestens SUB=0 hat.
    for mid in list(katalog.keys()):
        katalog[mid].add(0)

    def _rechte_fuer(mid: int, sid: int) -> int:
        if admin_pauschale is not None:
            return admin_pauschale
        return rechte_map.get((mid, sid), 0)

    # Gruppierung nach Kategorie aufbauen.
    kat_to_module: dict[int, list[dict]] = {}
    for mid in sorted(katalog.keys()):
        kat_id, kat_name = kategorie_fuer(mid)
        subs = sorted(s for s in katalog[mid] if s > 0)
        eintrag = {
            'modul_id':  mid,
            'name':      namen.get((mid, 0)) or namen.get((mid, -1))
                         or f'Modul {mid}',
            'rechte':    _rechte_fuer(mid, 0),
            'submodule': [
                {
                    'modul_id':    mid,
                    'submodul_id': sid,
                    'name':        namen.get((mid, sid)) or f'Sub {sid}',
                    'rechte':      _rechte_fuer(mid, sid),
                }
                for sid in subs
            ],
        }
        kat_to_module.setdefault(kat_id, []).append(eintrag)

    # Feste Reihenfolge der Kategorien.
    baum: list[dict] = []
    for kid, label in _KATEGORIEN:
        module = kat_to_module.pop(kid, [])
        if module:
            baum.append({
                'kategorie_id':   kid,
                'kategorie_name': label,
                'module':         module,
            })
    # Rest (unbekannte Kategorie-Range) ans Ende haengen.
    for kid, module in sorted(kat_to_module.items()):
        baum.append({
            'kategorie_id':   kid,
            'kategorie_name': f'Sonstige ({kid})',
            'module':         module,
        })
    return baum


def mitarbeiter_mit_gruppen() -> list[dict]:
    """Alle Mitarbeiter mit ihrer Gruppen-Zuordnung.

    Felder: ``MA_ID, LOGIN_NAME, ANZEIGE_NAME, GRUPPEN_ID, GRUPPEN_NAME,
    AKTIV`` (True wenn ``GUELTIG_BIS`` leer / in Zukunft).
    """
    try:
        with get_db() as cur:
            cur.execute("""
                SELECT m.MA_ID, m.LOGIN_NAME, m.ANZEIGE_NAME,
                       m.GUELTIG_BIS,
                       COALESCE(br.GRUPPEN_ID, 0) AS GRUPPEN_ID
                  FROM MITARBEITER m
                  LEFT JOIN BENUTZERRECHTE br
                    ON br.USER_ID = m.MA_ID
                   AND br.MODUL_ID = 0 AND br.SUBMODUL_ID = 0
                 WHERE (m.BEREINIGT IS NULL OR m.BEREINIGT = 'N')
                 ORDER BY m.MA_ID
            """)
            rows = cur.fetchall() or []
    except Exception as exc:
        log.warning("mitarbeiter_mit_gruppen: %s", exc)
        return []
    gruppen = {g['GRUPPEN_ID']: g['NAME'] for g in gruppen_laden()}
    from datetime import datetime
    jetzt = datetime.now()
    ergebnis = []
    for r in rows:
        gbis = r.get('GUELTIG_BIS')
        aktiv = (gbis is None) or (gbis >= jetzt)
        ergebnis.append({
            'MA_ID':         r['MA_ID'],
            'LOGIN_NAME':    r['LOGIN_NAME'],
            'ANZEIGE_NAME':  r['ANZEIGE_NAME'],
            'GRUPPEN_ID':    r['GRUPPEN_ID'],
            'GRUPPEN_NAME':  gruppen.get(r['GRUPPEN_ID'], '?'),
            'AKTIV':         aktiv,
        })
    return ergebnis


def benutzer_overrides(ma_id: int) -> list[dict]:
    """User-spezifische Abweichungen (GRUPPEN_ID=-1 AND USER_ID=ma_id)."""
    namen = _modul_name_lookup()
    try:
        with get_db() as cur:
            cur.execute("""
                SELECT MODUL_ID, SUBMODUL_ID, RECHTE
                  FROM BENUTZERRECHTE
                 WHERE GRUPPEN_ID=-1 AND USER_ID=%s AND MODUL_ID>0
                 ORDER BY MODUL_ID, SUBMODUL_ID
            """, (int(ma_id),))
            rows = cur.fetchall() or []
    except Exception as exc:
        log.warning("benutzer_overrides(%s): %s", ma_id, exc)
        return []
    ergebnis = []
    for r in rows:
        mid, sid = int(r['MODUL_ID']), int(r['SUBMODUL_ID'])
        kat_id, kat_name = kategorie_fuer(mid)
        ergebnis.append({
            'kategorie':  kat_name,
            'modul_id':   mid,
            'submodul_id': sid,
            'name':       namen.get((mid, sid)) or namen.get((mid, 0))
                          or f'Modul {mid}/{sid}',
            'rechte':     int(r['RECHTE']),
        })
    return ergebnis
