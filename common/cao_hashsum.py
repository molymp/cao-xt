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

ARTIKEL_LOG / NUMMERN_LOG / *_LOG (HASHSUM = blob, NOT NULL)
------------------------------------------------------------
CAO-Algorithmus ist nicht reproduzierbar (DCPcrypt + UniDAC, weder
Block- noch Stream-Cipher-konform, Kandidat-Keys matchen nicht). Die
gute Nachricht: in den vier CAO-Binaries (cao_faktura, cao_admin,
cao_lib, cao_kasse_pro) gibt es **kein einziges** ``SELECT`` auf
``HASHSUM`` aus *_LOG-Tabellen — CAO validiert die Hash-Kette dort
**nicht**. Die einzige aktive HASHSUM-Validierung in CAO ist die
``TFRMDATENPRUEFUNG``-Funktion in ``cao_admin.exe``, die ausschliess-
lich JOURNAL prueft (Kassen-Belegkette, GoBD-Pflicht).

Konsequenz: wir schreiben in *_LOG-Tabellen unsere **eigenen**
HASHSUMs mit XT-eigenem Algorithmus. Implementation siehe
:mod:`common.cao_log_hashsum` (HMAC-SHA-256 + XT-Magic-Prefix
``XTL\\x01``). Die in ``DORFKERN_KONFIG`` gepflegten
``cao.hash_salt.*``-Schluessel werden vom XT-Modul als HMAC-Key
verwendet — der CAO-Algorithmus selbst kommt damit nicht zur
Anwendung.

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
    # *_LOG-Tabellen nutzen den XT-eigenen HASHSUM-Algorithmus
    # (HMAC-SHA-256, siehe common.cao_log_hashsum). CAO validiert die
    # Kette in *_LOG nicht zur Laufzeit, deshalb steht uns die
    # Salt-Wahl frei. Pro Tabelle eigener Wert empfohlen.
    _LOG_BESCHR = (
        'Salt fuer XT-eigenen HASHSUM-Algorithmus '
        '(HMAC-SHA-256, common.cao_log_hashsum). Frei waehlbar.'
    )
    eintraege = [
        # Master-Tabellen (CAO-Algorithmus, MD5 + Salt)
        (KEY_JOURNAL,
         'JOURNAL/JOURNALPOS – MD5(salt + CONCAT(MD5-pro-Zeile)).'),
        (KEY_JOURNAL_ABSCHLAG, 'JOURNAL_ABSCHLAG – Algorithmus offen.'),
        (KEY_EKBESTELL,        'EKBESTELL (Einkaufsbestellung) – offen.'),
        (KEY_LIEFERSCHEIN,     'LIEFERSCHEIN – offen.'),
        (KEY_KASSE_ABSCHLUSS,  'KASSE_ABSCHLUSS – offen.'),
        (KEY_VERTRETER_ABR,    'VERTRETER_ABR – offen.'),
        (KEY_LOGIN,            'LOGIN – offen.'),
        # *_LOG-Tabellen (XT-eigener Algorithmus, HMAC-SHA-256)
        (KEY_ADRESSEN_LOG,                _LOG_BESCHR),
        (KEY_ARTIKEL_LOG,                 _LOG_BESCHR),
        (KEY_ARTIKEL_SCHNELLZUGRIFF_LOG,  _LOG_BESCHR),
        (KEY_BENUTZERRECHTE_LOG,          _LOG_BESCHR),
        (KEY_KASSE_LOG,                   _LOG_BESCHR),
        (KEY_MITARBEITER_LOG,             _LOG_BESCHR),
        (KEY_NUMMERN_LOG,                 _LOG_BESCHR),
        (KEY_REGISTRY_LOG,                _LOG_BESCHR),
        (KEY_RKSV_LOG,                    _LOG_BESCHR),
        (KEY_TSE_LOG,                     _LOG_BESCHR),
        (KEY_WARENGRUPPEN_LOG,            _LOG_BESCHR),
        (KEY_ZAHLUNGSARTEN_LOG,           _LOG_BESCHR),
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


# ── *_LOG-Tabellen ─────────────────────────────────────────────────
#
# Fuer ARTIKEL_LOG, NUMMERN_LOG, ADRESSEN_LOG, MITARBEITER_LOG,
# WARENGRUPPEN_LOG, BENUTZERRECHTE_LOG, REGISTRY_LOG etc. ist der
# CAO-Algorithmus nicht reproduzierbar (DCPcrypt + UniDAC). CAO
# validiert die Kette dort aber auch nicht zur Laufzeit
# (kein SELECT auf *_LOG.HASHSUM in saemtlichen CAO-Binaries).
# Wir schreiben unsere eigenen HASHSUMs ueber HMAC-SHA-256 +
# XT-Magic-Prefix — siehe :mod:`common.cao_log_hashsum`.
#
# Die Salts pro Tabelle sind hier (Konfig-Schluessel ``KEY_*_LOG``)
# definiert und werden vom XT-Algorithmus als HMAC-Key benutzt. Salts
# liegen in ``DORFKERN_KONFIG`` (Kategorie ``CAO_HASH_SALT``), Werte
# selbst NIE im Code. Pro Instanz frei waehlbar.
