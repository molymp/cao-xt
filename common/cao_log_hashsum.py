"""
XT-eigener HASHSUM-Algorithmus fuer CAO-Audit-Log-Tabellen (`*_LOG`).

Hintergrund (Stand 2026-05-03)
=============================

CAO-Faktura schreibt bei jeder Aenderung an einer Stammdaten-Tabelle
(``ARTIKEL``, ``ADRESSEN``, ``MITARBEITER``, ``WARENGRUPPEN``,
``BENUTZERRECHTE``, ``REGISTRY``, ``NUMMERN``, ...) einen Snapshot in
die zugehoerige ``*_LOG``-Tabelle. Jeder Eintrag enthaelt eine
``HASHSUM`` (BLOB, Base64-Text), die als Audit-Trail-Verkettung
gedacht ist.

Der CAO-Algorithmus selbst ist **nicht** rekonstruierbar:

- DCPcrypt + UniDAC-Crypto im Binary
- Output-Laengen sind weder Block- noch Stream-Cipher-konform
- Kandidat-Keys (z.B. der bekannte JOURNAL-Salt
  ``cZodx62PyrgwlJKuj``) matchen nicht
- Tabellen-spezifische Magic-Bytes (``8p4K``, ``8q/f``, ``5Fwo``,
  Base64-decoded ``f29e0a``, ``f2afdf``, ``e45c28``) lassen IV/Salt-
  Derivation aus Tabellenname vermuten — Algorithmus aber unbekannt

Empirisch ist verifiziert (mehrfache Suche ueber alle CAO-Binaries):

- ``HASHSUM`` wird in ``*_LOG``-Tabellen **nirgendwo** per ``SELECT``
  abgefragt — d.h. CAO validiert die Hash-Kette **nicht zur Laufzeit**.
- Die einzige aktive HASHSUM-Validierung in CAO ist die
  ``TFRMDATENPRUEFUNG``-Funktion in ``cao_admin.exe``, und die prueft
  ausschliesslich ``JOURNAL`` (Kassenbelege, GoBD-Pflicht).
- ``*_LOG``-Eintraege werden geschrieben, nie gelesen.

Konsequenz fuer XT
==================

Wir brauchen den CAO-Algorithmus nicht zu kennen. Wir schreiben in
``*_LOG``-Tabellen unsere **eigenen** HASHSUMs, die:

1. zu unseren XT-Schreibvorgaengen einen **lueckenlosen Audit-Trail**
   bilden (auch nach Abloesung von CAO-Faktura noch nachvollziehbar)
2. **HMAC-SHA-256** mit pro Tabelle konfigurierbarem Salt verwenden
   (Salt liegt in ``DORFKERN_KONFIG``, kein hartcodiertes Geheimnis)
3. einen **eindeutigen XT-Magic-Prefix** (``XTL`` + Versions-Byte)
   tragen — bei einem spaeteren Forensik-Audit ist sofort sichtbar
   welche ``_LOG``-Eintraege von uns kommen
4. die gleiche **Chain-Verkettung** wie CAO benutzen
   (Separator ``|@#2@|`` zwischen aktuellem HASHSTRING und vorigem
   HASHSUM) — falls wir je die CAO-Kette validieren wollen, ist die
   Struktur kompatibel

Format
======

::

    HASHSUM (Base64-Text)
       │
       └─→ [4 Byte XT-Magic] || [32 Byte HMAC-SHA-256(salt, plain)]
                                 wobei
                                 plain = hashstring  (erster Eintrag)
                                       | hashstring + '|@#2@|' + prev_hashsum

XT-Magic
--------
- Bytes 0-2 ``X T L`` (= ASCII ``0x58 0x54 0x4C``)
- Byte 3:    Algorithmus-Version (``0x01`` = HMAC-SHA-256, dieser Code)

Base64-Encoding ergibt einen festen Anfang ``WFRMA…`` (4 chars) +
44 chars Hash = 48 chars total. CAO-Eintraege haben variable Laengen
(meist deutlich laenger), unsere sind also auf den ersten Blick
unterscheidbar.

Salt-Konfiguration
==================

Pro Tabelle ein eigener Konfig-Schluessel ``cao.hash_salt.<table>``
in ``DORFKERN_KONFIG`` (Kategorie ``CAO_HASH_SALT``). Die Schluessel
sind via :func:`common.cao_hashsum.seed_registry` bereits angelegt.

Wenn der Salt fuer eine Tabelle nicht gepflegt ist, faellt der
Algorithmus **nicht** still auf einen Default zurueck — er wirft
:class:`common.cao_hashsum.SaltFehlt`. Damit hat der Admin Kontrolle
ueber alle Schluessel-Werte und kann sie pro Instanz unterschiedlich
setzen.

Verwendung
==========

::

    from common import cao_log_hashsum
    from common.db import get_db

    # 1. Vorigen HASHSUM holen (Kette fortfuehren)
    with get_db() as cur:
        cur.execute(
            "SELECT HASHSUM FROM ARTIKEL_LOG ORDER BY REC_ID DESC LIMIT 1"
        )
        row = cur.fetchone()
    prev = row['HASHSUM'] if row else None

    # 2. HASHSTRING konstruieren (gleiche CONCAT_WS-Formel wie CAO)
    hashstring = "V1|123|007409|2.59|3.99|..."

    # 3. HASHSUM berechnen
    new_hashsum = cao_log_hashsum.compute(
        table_name='ARTIKEL_LOG',
        hashstring=hashstring,
        previous_hashsum=prev,
    )

    # 4. ARTIKEL_LOG-Eintrag schreiben
    cur.execute(
        "INSERT INTO ARTIKEL_LOG (..., HASHSUM) VALUES (..., %s)",
        (..., new_hashsum)
    )
"""
from __future__ import annotations

import base64
import hmac
import logging
from hashlib import sha256
from typing import Optional, Union

from common import cao_hashsum as _cao_hashsum

log = logging.getLogger(__name__)


# ── XT-Magic-Prefix ────────────────────────────────────────────────

# 3 ASCII-Bytes 'XTL' + 1 Byte Algorithmus-Version.
# Version 0x01 = HMAC-SHA-256 (dieses Modul).
# Bei zukuenftigen Algo-Wechseln: Version hochzaehlen, alte Version
# fuer Verifikation bestehender Eintraege beibehalten.
_MAGIC_XT_V1 = b'XTL\x01'

# Chain-Separator (identisch zu CAO, damit die Plaintext-Struktur
# bei einer eventuellen spaeteren CAO-Algo-Reproduktion kompatibel
# ist – siehe Doku oben).
_CHAIN_SEP = '|@#2@|'

# Aktuelle Algorithmus-Version. Bei Aenderungen Version hochzaehlen
# UND alte Version fuer Read-Back bestehender Eintraege im
# :func:`verify`-Zweig erhalten.
ALGO_VERSION_AKTUELL = 1


# ── Hauptfunktion ──────────────────────────────────────────────────

def compute(table_name: str,
            hashstring: str,
            previous_hashsum: Optional[Union[bytes, str]] = None) -> bytes:
    """Berechnet die XT-HASHSUM fuer einen ``*_LOG``-Eintrag.

    Args:
        table_name: Name der Log-Tabelle, z.B. ``'ARTIKEL_LOG'``.
            Wird zur Salt-Aufloesung in ``DORFKERN_KONFIG`` benutzt
            (``cao.hash_salt.<table_name_lower>``).
        hashstring: Der CONCAT_WS('|','V1', spalten...)-String fuer
            den aktuellen Eintrag. Format ist fix vorgegeben durch
            CAO (siehe ``reference_cao_journal_write.md``).
        previous_hashsum: HASHSUM des vorigen Eintrags in dieser
            Tabelle (BLOB aus DB). ``None`` fuer den ersten Eintrag
            ueberhaupt.

    Returns:
        ``bytes``: 48-Zeichen Base64-Text (binaer 36 Bytes:
        4 Byte Magic + 32 Byte HMAC-SHA-256).

    Raises:
        common.cao_hashsum.SaltFehlt: Salt fuer ``table_name`` ist in
            ``DORFKERN_KONFIG`` nicht gepflegt.
        ValueError: ``table_name`` oder ``hashstring`` ist leer.
    """
    if not table_name:
        raise ValueError('table_name darf nicht leer sein')
    if hashstring is None or hashstring == '':
        raise ValueError('hashstring darf nicht leer sein')

    salt = _cao_hashsum.get_salt(_salt_key(table_name))

    plain = hashstring
    if previous_hashsum:
        prev = (previous_hashsum.decode('ascii')
                if isinstance(previous_hashsum, bytes)
                else previous_hashsum)
        plain = f'{hashstring}{_CHAIN_SEP}{prev}'

    digest = hmac.new(
        salt.encode('utf-8'),
        plain.encode('utf-8'),
        sha256,
    ).digest()                                             # 32 Bytes

    return base64.b64encode(_MAGIC_XT_V1 + digest)         # 48 chars


# ── Verifikation ───────────────────────────────────────────────────

def is_xt_hashsum(hashsum: Union[bytes, str]) -> bool:
    """True wenn ``hashsum`` von uns (XT) erzeugt wurde.

    Erkennt am Magic-Prefix. Hilfreich fuer Reports / Forensik um
    XT-Eintraege von CAO-Eintraegen zu trennen, ohne den
    HASHSUM-Inhalt zu kennen.
    """
    if not hashsum:
        return False
    h = hashsum if isinstance(hashsum, bytes) else hashsum.encode('ascii')
    # Base64('XTL\x01...') beginnt mit 'WFRMA' (5 chars,
    # davon WFRM = b'XTL' und das A ist der erste 6-bit-Block des
    # Versions-Bytes 0x01 = 0b00000001 -> '000000' = 'A').
    return h.startswith(b'WFRMA')


def verify(table_name: str,
           hashstring: str,
           hashsum: Union[bytes, str],
           previous_hashsum: Optional[Union[bytes, str]] = None) -> bool:
    """Prueft ob ``hashsum`` mit dem aktuellen Salt + plain reproduzierbar
    ist. Liefert ``True`` bei Match, ``False`` sonst.

    Nuetzlich fuer Audit-Reports (eigene Datenpruefung-Funktion in
    XT-Admin-UI, die unsere XT-erzeugten LOG-Eintraege gegen die
    Quell-Daten validiert).
    """
    try:
        erwartet = compute(table_name, hashstring, previous_hashsum)
    except Exception as exc:
        log.warning('verify: compute fehlgeschlagen: %s', exc)
        return False
    h = hashsum if isinstance(hashsum, bytes) else hashsum.encode('ascii')
    return hmac.compare_digest(erwartet, h)


# ── Helpers ────────────────────────────────────────────────────────

def _salt_key(table_name: str) -> str:
    """Mappt einen ``*_LOG``-Tabellennamen auf den DORFKERN_KONFIG-
    Schluessel ``cao.hash_salt.<table>`` (lowercase)."""
    return f'cao.hash_salt.{table_name.lower()}'
