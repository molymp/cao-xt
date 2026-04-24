"""
CAO-XT – Terminal-Registry (TERMINAL-Tabelle)

Phase-4-Scope (Dorfkern v2): DB-basierte Terminal-Identifikation statt
Cookie. Jeder Host, auf dem Kasse/Kiosk/Admin/Orga laeuft, traegt sich
beim Start in die ``TERMINAL``-Tabelle ein (Auto-Discovery ueber
Hostname + MAC-Adresse) und aktualisiert ``LETZTER_KONTAKT``.

Auswahl-Reihenfolge (siehe :func:`erkenne`):
  1. Match ueber ``MAC_ADRESSE`` (stabilster Bezug: Hardware-seitig)
  2. Match ueber ``HOSTNAME`` (fuer VMs/Container ohne feste MAC)
  3. Kein Match → ``None`` (Admin muss das Terminal anlegen)

Die Admin-UI (Phase 5) verwaltet die Zuweisung ``HOSTNAME ↔ BEZEICHNUNG``;
daher erfolgt kein automatisches Anlegen neuer Terminals. Das macht die
Erst-Inbetriebnahme bewusst zu einem expliziten Akt.
"""
from __future__ import annotations

import logging
import socket
import uuid
from typing import Optional

from common.db import get_db, get_db_transaction

log = logging.getLogger(__name__)

_VALID_TYPEN = ('KASSE', 'KIOSK', 'ADMIN', 'ORGA')


def run_migration() -> None:
    """Legt ``TERMINAL`` an, falls nicht vorhanden. Idempotent."""
    try:
        with get_db() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS TERMINAL (
                  TERMINAL_ID     INT AUTO_INCREMENT PRIMARY KEY,
                  BEZEICHNUNG     VARCHAR(64)  NOT NULL,
                  TYP             ENUM('KASSE','KIOSK','ADMIN','ORGA') NOT NULL,
                  HOSTNAME        VARCHAR(128) NULL,
                  MAC_ADRESSE     VARCHAR(17)  NULL,
                  IP_LETZTE       VARCHAR(45)  NULL,
                  AKTIV           TINYINT(1)   NOT NULL DEFAULT 1,
                  LETZTER_KONTAKT DATETIME     NULL,
                  UNIQUE KEY uq_typ_bezeichnung (TYP, BEZEICHNUNG),
                  INDEX idx_hostname (HOSTNAME),
                  INDEX idx_mac (MAC_ADRESSE)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                  COMMENT='Terminal-Registry (Dorfkern v2, Phase 4)'
            """)
        log.info("Migration: TERMINAL geprueft/erstellt.")
    except Exception as exc:
        log.warning("TERMINAL-Migration fehlgeschlagen: %s", exc)


# ── Host-Identitaet ───────────────────────────────────────────────────────────

def hostname() -> str:
    """Kurzer Hostname des aktuellen Rechners."""
    try:
        return socket.gethostname()
    except Exception:
        return ''


def mac_adresse() -> str:
    """MAC-Adresse als ``AA:BB:CC:DD:EE:FF`` (ohne Zusicherung der NIC).

    ``uuid.getnode()`` liefert die MAC der ersten brauchbaren NIC. Auf
    Systemen ohne echte NIC wird ein Zufallsbit gesetzt – dann geben wir
    leer zurueck (und der Match geht ueber den Hostname).
    """
    try:
        node = uuid.getnode()
        # Ist Bit 40 gesetzt, ist ``node`` ein synthetisches Zufallsergebnis.
        if (node >> 40) & 1:
            return ''
        hex_ = f'{node:012x}'
        return ':'.join(hex_[i:i + 2] for i in range(0, 12, 2)).upper()
    except Exception:
        return ''


def lokale_ip() -> str:
    """Beste Schaetzung der LAN-IP. Leer bei Offline-Host."""
    try:
        # Verbindungsversuch zu einer Routbaren (nicht-erreichbaren) Adresse
        # liefert die ausgehende IP ohne tatsaechlich Pakete zu senden.
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(('10.255.255.255', 1))
            return s.getsockname()[0]
        finally:
            s.close()
    except Exception:
        return ''


# ── CRUD-Primitive ────────────────────────────────────────────────────────────

def anlegen(bezeichnung: str, typ: str,
            hostname_: Optional[str] = None,
            mac: Optional[str] = None) -> int:
    """Legt ein Terminal an. Gibt ``TERMINAL_ID`` zurueck.

    Raises:
        ValueError: bei unbekanntem ``typ`` oder leerer Bezeichnung.
    """
    if typ not in _VALID_TYPEN:
        raise ValueError(f'TYP muss {_VALID_TYPEN} sein, war {typ!r}')
    if not bezeichnung or not bezeichnung.strip():
        raise ValueError('BEZEICHNUNG darf nicht leer sein')
    with get_db_transaction() as cur:
        cur.execute("""
            INSERT INTO TERMINAL (BEZEICHNUNG, TYP, HOSTNAME, MAC_ADRESSE)
            VALUES (%s, %s, %s, %s)
        """, (bezeichnung.strip(), typ, hostname_, mac))
        return cur.lastrowid


def aktualisieren(terminal_id: int, **felder) -> None:
    """Patch eines Terminals. Akzeptiert BEZEICHNUNG, HOSTNAME, MAC_ADRESSE,
    IP_LETZTE, AKTIV. Unbekannte Felder werden ignoriert (forgiving)."""
    erlaubt = {'BEZEICHNUNG', 'HOSTNAME', 'MAC_ADRESSE', 'IP_LETZTE', 'AKTIV'}
    paare = [(k.upper(), v) for k, v in felder.items()
             if k.upper() in erlaubt]
    if not paare:
        return
    set_sql = ', '.join(f'{k} = %s' for k, _ in paare)
    werte = [v for _, v in paare] + [terminal_id]
    with get_db_transaction() as cur:
        cur.execute(
            f'UPDATE TERMINAL SET {set_sql} WHERE TERMINAL_ID = %s',
            tuple(werte))


def setze_letzten_kontakt(terminal_id: int,
                          ip: Optional[str] = None) -> None:
    """Setzt ``LETZTER_KONTAKT = NOW()`` und optional die IP-Adresse.

    Gedacht als Heartbeat-Aufruf einmal pro Request (oder pro Minute
    mit App-seitigem Throttling, wenn die Last relevant wird).
    """
    with get_db_transaction() as cur:
        if ip:
            cur.execute("""
                UPDATE TERMINAL SET LETZTER_KONTAKT = NOW(), IP_LETZTE = %s
                 WHERE TERMINAL_ID = %s
            """, (ip, terminal_id))
        else:
            cur.execute("""
                UPDATE TERMINAL SET LETZTER_KONTAKT = NOW()
                 WHERE TERMINAL_ID = %s
            """, (terminal_id,))


def alle(typ: Optional[str] = None, nur_aktiv: bool = False) -> list[dict]:
    """Listet Terminals (fuer Admin-UI). Optional nach TYP/AKTIV filtern."""
    where: list[str] = []
    params: list = []
    if typ is not None:
        where.append('TYP = %s')
        params.append(typ)
    if nur_aktiv:
        where.append('AKTIV = 1')
    sql = ("SELECT TERMINAL_ID, BEZEICHNUNG, TYP, HOSTNAME, MAC_ADRESSE, "
           "IP_LETZTE, AKTIV, LETZTER_KONTAKT FROM TERMINAL")
    if where:
        sql += ' WHERE ' + ' AND '.join(where)
    sql += ' ORDER BY TYP, BEZEICHNUNG'
    try:
        with get_db() as cur:
            cur.execute(sql, tuple(params))
            return list(cur.fetchall() or [])
    except Exception as exc:
        log.warning("terminal.alle(): DB-Fehler: %s", exc)
        return []


def per_id(terminal_id: int) -> Optional[dict]:
    """Einzel-Lookup per ID. ``None``, wenn nicht vorhanden."""
    try:
        with get_db() as cur:
            cur.execute(
                "SELECT TERMINAL_ID, BEZEICHNUNG, TYP, HOSTNAME, MAC_ADRESSE, "
                "IP_LETZTE, AKTIV, LETZTER_KONTAKT FROM TERMINAL "
                "WHERE TERMINAL_ID = %s", (terminal_id,))
            return cur.fetchone()
    except Exception as exc:
        log.warning("terminal.per_id(%d): DB-Fehler: %s", terminal_id, exc)
        return None


def loeschen(terminal_id: int) -> None:
    """Harte Loeschung. Fuer das Normalbild bitte lieber ``AKTIV=0`` setzen."""
    with get_db_transaction() as cur:
        cur.execute('DELETE FROM TERMINAL WHERE TERMINAL_ID = %s',
                    (terminal_id,))


# ── Auto-Discovery ────────────────────────────────────────────────────────────

def erkenne(typ: str,
            host: Optional[str] = None,
            mac: Optional[str] = None) -> Optional[dict]:
    """Findet das Terminal fuer den aktuellen Host.

    Match-Reihenfolge:
      1. MAC-Adresse + TYP
      2. Hostname + TYP

    Args:
        typ:  Welcher App-Typ fragt (``'KASSE'`` etc.).
        host: Override fuer den Hostname (Default: ``socket.gethostname()``).
        mac:  Override fuer die MAC-Adresse (Default: :func:`mac_adresse`).

    Returns:
        Dict mit Terminal-Feldern oder ``None``, wenn nichts passt.
    """
    if typ not in _VALID_TYPEN:
        raise ValueError(f'TYP muss {_VALID_TYPEN} sein, war {typ!r}')
    host = host if host is not None else hostname()
    mac = mac if mac is not None else mac_adresse()

    try:
        with get_db() as cur:
            if mac:
                cur.execute(
                    "SELECT TERMINAL_ID, BEZEICHNUNG, TYP, HOSTNAME, "
                    "MAC_ADRESSE, IP_LETZTE, AKTIV, LETZTER_KONTAKT "
                    "FROM TERMINAL WHERE TYP = %s AND MAC_ADRESSE = %s "
                    "LIMIT 1", (typ, mac))
                row = cur.fetchone()
                if row is not None:
                    return row
            if host:
                cur.execute(
                    "SELECT TERMINAL_ID, BEZEICHNUNG, TYP, HOSTNAME, "
                    "MAC_ADRESSE, IP_LETZTE, AKTIV, LETZTER_KONTAKT "
                    "FROM TERMINAL WHERE TYP = %s AND HOSTNAME = %s "
                    "LIMIT 1", (typ, host))
                row = cur.fetchone()
                if row is not None:
                    return row
    except Exception as exc:
        log.warning("terminal.erkenne(%s): DB-Fehler: %s", typ, exc)
    return None
