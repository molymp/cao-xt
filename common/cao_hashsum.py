"""
CAO-HASHSUM-Algorithmen + zentrale Salt-Registry.

CAO-Faktura speichert in mehreren Tabellen einen ``HASHSUM``-Wert
(JOURNAL, JOURNALPOS, ARTIKEL_LOG, NUMMERN_LOG, voraussichtlich
weitere). Der Algorithmus pro Tabelle ist reverse-engineered aus
``cao_kasse_pro.exe`` bzw. ``cao_faktura.exe``; die Salts werden in
``DORFKERN_KONFIG`` (Kategorie ``CAO_HASH_SALT``) gepflegt, damit sie
zentral nachschlagbar sind und in der Admin-UI verwaltet werden
koennen, ohne Code-Anpassung.

WICHTIG: Salt-Werte selbst sind NICHT im Code. Sie werden vom Admin
in DORFKERN_KONFIG eingetragen und liegen damit ausserhalb des
Repositories. Wer eine frische Installation aufsetzt, muss die
bekannten Salts einmalig manuell pflegen (z.B. via
Admin-UI → Dorfkern → Konfiguration → Kategorie CAO_HASH_SALT).

Bekannte Algorithmen
====================

JOURNAL / JOURNALPOS (HASHSUM = varchar(40), default ``'$$'``)
-------------------------------------------------------------
* Quelle: ``cao_kasse_pro.exe v1.5.5.66``
* MD5 ueber ``salt + CONCAT(MD5(<feldwerte pro Zeile>) ...)``
* Output: 32 Hex-Zeichen, uppercase
* Salt-Konfig-Schluessel: ``cao.hash_salt.journal``
* Bestehende Implementation: ``kasse-app/app/kasse_logik.py``
  nutzt jetzt :func:`journal_hashsum`.

ARTIKEL_LOG (HASHSUM = blob, NOT NULL)
--------------------------------------
* Format: BLOB, Base64-encoded, variable Laenge ~500-650 Bytes
* Beobachtung: alle Eintraege starten mit Praefix ``8p4K`` oder
  ``8q/f`` (PKCS#1-v1.5-Padding-Header → vermutlich RSA-Signatur
  oder asymmetrische Verschluesselung mit konstantem Initial-Block).
* Algorithmus noch nicht implementiert. Sobald er bekannt ist:
  Salt unter :data:`KEY_ARTIKEL_LOG` in DORFKERN_KONFIG ablegen,
  :func:`artikel_log_hashsum` implementieren, Phase-5b-Sync
  freischalten.

NUMMERN_LOG (HASHSUM = blob, NOT NULL)
--------------------------------------
* Format wie ARTIKEL_LOG.
* Eigener Salt unter ``cao.hash_salt.nummern_log``
  (User-Bestaetigung 2026-05-03: jede *_LOG-Tabelle hat einen
  eigenen Salt-Wert).

Verwaltung in der Admin-UI
==========================
Salts erscheinen unter ``Dorfkern → Konfiguration`` mit Kategorie
``CAO_HASH_SALT``. ``TYP='SECRET'`` (Klartext, aber maskiert in der
Anzeige). Aenderungen werden vom Cache in :func:`common.konfig`
60 s gehalten.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Optional

from common import konfig as _konfig

log = logging.getLogger(__name__)


# ── Konstanten / Konfig-Schluessel ─────────────────────────────────

_KAT = 'CAO_HASH_SALT'

# Annahme (User-Bestaetigung 2026-05-03): jede *_LOG-Tabelle benutzt
# einen EIGENEN Salt-Wert. Die Master-Tabellen (JOURNAL, EKBESTELL,
# LIEFERSCHEIN, ...) haben ebenfalls je einen eigenen Salt.
# Wir legen pro Tabelle einen Konfig-Schluessel `cao.hash_salt.<table>`
# an und pflegen sie zentral in DORFKERN_KONFIG (Kategorie
# CAO_HASH_SALT). Werte selbst NIE in den Code – sie kommen aus der
# laufenden Installation.

# Master-Tabellen mit HASHSUM
KEY_JOURNAL          = 'cao.hash_salt.journal'
KEY_JOURNAL_ABSCHLAG = 'cao.hash_salt.journal_abschlag'
KEY_EKBESTELL        = 'cao.hash_salt.ekbestell'
KEY_LIEFERSCHEIN     = 'cao.hash_salt.lieferschein'
KEY_KASSE_ABSCHLUSS  = 'cao.hash_salt.kasse_abschluss'
KEY_VERTRETER_ABR    = 'cao.hash_salt.vertreter_abr'
KEY_LOGIN            = 'cao.hash_salt.login'

# Audit-Trail-Tabellen (*_LOG)
KEY_ADRESSEN_LOG               = 'cao.hash_salt.adressen_log'
KEY_ARTIKEL_LOG                = 'cao.hash_salt.artikel_log'
KEY_ARTIKEL_SCHNELLZUGRIFF_LOG = 'cao.hash_salt.artikel_schnellzugriff_log'
KEY_BENUTZERRECHTE_LOG         = 'cao.hash_salt.benutzerrechte_log'
KEY_KASSE_LOG                  = 'cao.hash_salt.kasse_log'
KEY_MITARBEITER_LOG            = 'cao.hash_salt.mitarbeiter_log'
KEY_NUMMERN_LOG                = 'cao.hash_salt.nummern_log'
KEY_REGISTRY_LOG               = 'cao.hash_salt.registry_log'
KEY_RKSV_LOG                   = 'cao.hash_salt.rksv_log'
KEY_TSE_LOG                    = 'cao.hash_salt.tse_log'
KEY_WARENGRUPPEN_LOG           = 'cao.hash_salt.warengruppen_log'
KEY_ZAHLUNGSARTEN_LOG          = 'cao.hash_salt.zahlungsarten_log'


# ── Salt-Registry ──────────────────────────────────────────────────

class SaltFehlt(RuntimeError):
    """Wird geworfen, wenn ein Algorithmus aufgerufen wird, dessen Salt
    in DORFKERN_KONFIG nicht gepflegt ist. Aufrufer sollen das als
    klaren Hinweis im Log/UI weiterreichen, NICHT mit einem Default-
    Wert überdecken."""


def get_salt(schluessel: str) -> str:
    """Liefert einen Salt-Wert aus DORFKERN_KONFIG. Wirft
    :class:`SaltFehlt`, wenn der Schluessel nicht/leer gesetzt ist."""
    wert = _konfig.get(schluessel, default=None)
    if wert in (None, ''):
        raise SaltFehlt(
            f'CAO-Hash-Salt {schluessel!r} nicht in DORFKERN_KONFIG '
            f'gepflegt. Bitte in Admin-UI → Dorfkern → Konfiguration '
            f'(Kategorie CAO_HASH_SALT) eintragen.'
        )
    return str(wert)


def set_salt(schluessel: str, wert: str, beschreibung: str = '',
             ma_id: Optional[int] = None) -> None:
    """Speichert einen Salt-Wert in DORFKERN_KONFIG (TYP=SECRET)."""
    _konfig.set(schluessel, wert, typ='SECRET',
                kategorie=_KAT,
                beschreibung=beschreibung or None,
                ma_id=ma_id)


def seed_registry() -> None:
    """Trägt die LEEREN Salt-Schluessel in DORFKERN_KONFIG ein, damit
    sie in der Admin-UI sichtbar sind und befuellt werden koennen.
    Bestehende Werte werden NICHT angefasst.
    """
    eintraege = [
        # Master-Tabellen
        (KEY_JOURNAL,
         'JOURNAL/JOURNALPOS – MD5(salt + CONCAT(MD5-pro-Zeile)).'),
        (KEY_JOURNAL_ABSCHLAG, 'JOURNAL_ABSCHLAG – Algorithmus offen.'),
        (KEY_EKBESTELL,        'EKBESTELL (Einkaufsbestellung) – offen.'),
        (KEY_LIEFERSCHEIN,     'LIEFERSCHEIN – offen.'),
        (KEY_KASSE_ABSCHLUSS,  'KASSE_ABSCHLUSS – offen.'),
        (KEY_VERTRETER_ABR,    'VERTRETER_ABR – offen.'),
        (KEY_LOGIN,            'LOGIN – offen.'),
        # *_LOG-Tabellen
        (KEY_ADRESSEN_LOG,                'ADRESSEN_LOG – offen.'),
        (KEY_ARTIKEL_LOG,
         'ARTIKEL_LOG – Format BLOB ~500-650 Bytes, Praefix '
         '8p4K/8q/f. Phase 5b haengt davon ab.'),
        (KEY_ARTIKEL_SCHNELLZUGRIFF_LOG,  'ARTIKEL_SCHNELLZUGRIFF_LOG – offen.'),
        (KEY_BENUTZERRECHTE_LOG,          'BENUTZERRECHTE_LOG – offen.'),
        (KEY_KASSE_LOG,                   'KASSE_LOG – offen.'),
        (KEY_MITARBEITER_LOG,             'MITARBEITER_LOG – offen.'),
        (KEY_NUMMERN_LOG,
         'NUMMERN_LOG – ARTNUM-Vergabe schreibt hier. Phase 5b '
         'haengt davon ab.'),
        (KEY_REGISTRY_LOG,                'REGISTRY_LOG – offen.'),
        (KEY_RKSV_LOG,                    'RKSV_LOG (AT-Kassenpruefung) – offen.'),
        (KEY_TSE_LOG,                     'TSE_LOG – offen.'),
        (KEY_WARENGRUPPEN_LOG,            'WARENGRUPPEN_LOG – offen.'),
        (KEY_ZAHLUNGSARTEN_LOG,           'ZAHLUNGSARTEN_LOG – offen.'),
    ]
    for k, beschr in eintraege:
        if _konfig.get(k) in (None, ''):
            try:
                # Leerer Wert: Admin-UI zeigt den Schluessel mit
                # „nicht gesetzt"-Hinweis und der Beschreibung an.
                _konfig.set(k, '', typ='SECRET',
                            kategorie=_KAT, beschreibung=beschr)
            except Exception as exc:
                log.warning('CAO-Hash-Salt-Seed %s fehlgeschlagen: %s',
                            k, exc)


# ── JOURNAL / JOURNALPOS (MD5 + Salt) ──────────────────────────────

def journal_hashsum(concat_md5_strings: str) -> str:
    """Berechnet die JOURNAL.HASHSUM aus dem konkatenierten MD5-Output
    der MD5-Pro-Zeile-Querry (siehe ``kasse_logik._SQL_JOURNAL_HASHSTRING``).

    Args:
        concat_md5_strings: ``''.join(r['HASHSTRING'] for r in rows)`` –
            die MD5-Hex-Werte aller JOURNAL+JOURNALPOS-Zeilen.

    Returns:
        32 Hex-Zeichen uppercase.

    Raises:
        SaltFehlt: wenn der Salt nicht in DORFKERN_KONFIG gepflegt ist.
    """
    salt = get_salt(KEY_JOURNAL)
    return hashlib.md5(
        (salt + (concat_md5_strings or '')).encode('ascii', errors='replace')
    ).hexdigest().upper()


# ── ARTIKEL_LOG (noch nicht implementiert) ─────────────────────────

def artikel_log_hashsum(*_args, **_kwargs) -> bytes:
    """Stub fuer den ARTIKEL_LOG-HASHSUM-Algorithmus. Sobald Salt + Algo
    aus cao_faktura.exe extrahiert sind:

    1. Salt unter :data:`KEY_ARTIKEL_LOG` in DORFKERN_KONFIG hinterlegen
    2. Diese Funktion implementieren
    3. Phase 5b (Stammartikel-Anlage) freischalten

    Workaround bis dahin: keine Schreibvorgaenge auf ARTIKEL/ARTIKEL_LOG;
    Stammartikel-Anlage erfolgt manuell in der CAO-GUI, nur die
    Lieferantenpreis-Verknuepfung wird automatisiert (Phase 5a).
    """
    raise NotImplementedError(
        'ARTIKEL_LOG-HASHSUM-Algorithmus noch nicht extrahiert. '
        f'Salt unter DORFKERN_KONFIG-Schluessel {KEY_ARTIKEL_LOG!r} '
        'hinterlegen, sobald aus cao_faktura.exe bekannt; '
        'dann diese Funktion implementieren.'
    )


# ── NUMMERN_LOG (noch nicht implementiert) ─────────────────────────

def nummern_log_hashsum(*_args, **_kwargs) -> bytes:
    """Stub – Algorithmus identisch oder ähnlich zu ARTIKEL_LOG."""
    raise NotImplementedError(
        'NUMMERN_LOG-HASHSUM-Algorithmus noch nicht extrahiert. '
        f'Salt unter DORFKERN_KONFIG-Schluessel {KEY_NUMMERN_LOG!r} '
        'hinterlegen, sobald aus cao_faktura.exe bekannt.'
    )
