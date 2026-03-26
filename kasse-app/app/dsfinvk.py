"""
CAO-XT Kassen-App – DSFinV-K Export
Nutzt die Fiskaly DSFinV-K API um ein TAR-Archiv für
die Betriebsprüfung (§146b AO) zu generieren.

Der Export umfasst alle Kassenvorgänge eines Zeitraums
und kann direkt an das Finanzamt übergeben werden.
"""
import requests
import config
from db import get_db
import logging

log = logging.getLogger(__name__)


def _token_und_tss(terminal_nr: int):
    """Gibt (api_key, api_secret, tss_id, env) zurück."""
    with get_db() as cur:
        cur.execute(
            """SELECT FISKALY_API_KEY, FISKALY_API_SECRET,
                      FISKALY_TSS_ID, FISKALY_ENV
               FROM XT_KASSE_TERMINALS WHERE TERMINAL_NR = %s""",
            (terminal_nr,)
        )
        row = cur.fetchone()
    if not row:
        raise RuntimeError(f"Terminal {terminal_nr} nicht gefunden.")
    return row


def _auth_token(api_key: str, api_secret: str, env: str) -> str:
    resp = requests.post(
        f"{config.FISKALY_MGMT_URL}/auth",
        json={'api_key': api_key, 'api_secret': api_secret},
        timeout=15
    )
    resp.raise_for_status()
    return resp.json()['access_token']


def dsfinvk_export_starten(terminal_nr: int,
                            datum_von: str, datum_bis: str) -> dict:
    """
    Startet einen DSFinV-K-Export für den angegebenen Zeitraum.
    datum_von / datum_bis: 'YYYY-MM-DD'
    Gibt {'export_id': ..., 'state': 'PENDING'} zurück.
    """
    tconf = _token_und_tss(terminal_nr)
    token = _auth_token(tconf['FISKALY_API_KEY'], tconf['FISKALY_API_SECRET'],
                        tconf['FISKALY_ENV'])
    tss_id = tconf['FISKALY_TSS_ID']

    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    body = {
        'start_date': f'{datum_von}T00:00:00.000Z',
        'end_date':   f'{datum_bis}T23:59:59.999Z',
    }
    resp = requests.post(
        f"{config.FISKALY_MGMT_URL}/tss/{tss_id}/export",
        json=body, headers=headers, timeout=30
    )
    resp.raise_for_status()
    data = resp.json()
    return {
        'export_id': data.get('_id') or data.get('id'),
        'state':     data.get('state', 'PENDING'),
    }


def dsfinvk_export_status(terminal_nr: int, export_id: str) -> dict:
    """
    Prüft den Status eines laufenden Exports.
    Gibt {'state': 'PENDING'|'COMPLETED'|'ERROR', 'href': '...'} zurück.
    """
    tconf = _token_und_tss(terminal_nr)
    token = _auth_token(tconf['FISKALY_API_KEY'], tconf['FISKALY_API_SECRET'],
                        tconf['FISKALY_ENV'])
    tss_id = tconf['FISKALY_TSS_ID']

    headers = {'Authorization': f'Bearer {token}'}
    resp = requests.get(
        f"{config.FISKALY_MGMT_URL}/tss/{tss_id}/export/{export_id}",
        headers=headers, timeout=15
    )
    resp.raise_for_status()
    data = resp.json()
    return {
        'state': data.get('state', 'UNKNOWN'),
        'href':  data.get('href') or data.get('download_url'),
    }


def dsfinvk_export_herunterladen(terminal_nr: int, export_id: str) -> bytes:
    """
    Lädt das fertige TAR-Archiv herunter und gibt den Inhalt zurück.
    """
    status = dsfinvk_export_status(terminal_nr, export_id)
    if status['state'] != 'COMPLETED':
        raise RuntimeError(f"Export {export_id} noch nicht bereit: {status['state']}")

    tconf = _token_und_tss(terminal_nr)
    token = _auth_token(tconf['FISKALY_API_KEY'], tconf['FISKALY_API_SECRET'],
                        tconf['FISKALY_ENV'])
    tss_id = tconf['FISKALY_TSS_ID']

    headers = {'Authorization': f'Bearer {token}'}
    # Download-URL aus Status oder direkt von der API
    url = status.get('href') or \
          f"{config.FISKALY_MGMT_URL}/tss/{tss_id}/export/{export_id}/file"
    resp = requests.get(url, headers=headers, timeout=60)
    resp.raise_for_status()
    return resp.content


def lokale_export_daten(terminal_nr: int,
                         datum_von: str, datum_bis: str) -> dict:
    """
    Erstellt eine lokale Übersicht der Kassentransaktionen für den Export
    (ergänzend zum Fiskaly-TAR, z.B. für interne Prüfung).
    Gibt ein Dict zurück das direkt als JSON ausgeliefert werden kann.
    """
    with get_db() as cur:
        cur.execute(
            """SELECT v.*, GROUP_CONCAT(z.ZAHLART ORDER BY z.ID SEPARATOR ',') AS ZAHLARTEN
               FROM XT_KASSE_VORGAENGE v
               LEFT JOIN XT_KASSE_ZAHLUNGEN z ON z.VORGANG_ID = v.ID
               WHERE v.TERMINAL_NR = %s
                 AND v.STATUS = 'ABGESCHLOSSEN'
                 AND DATE(v.BON_DATUM) BETWEEN %s AND %s
               GROUP BY v.ID
               ORDER BY v.BON_DATUM""",
            (terminal_nr, datum_von, datum_bis)
        )
        vorgaenge = cur.fetchall()

        cur.execute(
            """SELECT DATUM, Z_NR, ZEITPUNKT, UMSATZ_BRUTTO, ANZAHL_BELEGE,
                      TSE_SIGNATUR_ZAEHLER
               FROM XT_KASSE_TAGESABSCHLUSS
               WHERE TERMINAL_NR = %s AND DATUM BETWEEN %s AND %s
               ORDER BY DATUM""",
            (terminal_nr, datum_von, datum_bis)
        )
        abschluesse = cur.fetchall()

    # Datetimes serialisierbar machen
    def _serial(obj):
        if hasattr(obj, 'isoformat'):
            return obj.isoformat()
        return str(obj)

    return {
        'terminal_nr':    terminal_nr,
        'datum_von':      datum_von,
        'datum_bis':      datum_bis,
        'anzahl_belege':  len(vorgaenge),
        'vorgaenge':      [{k: _serial(v) for k, v in row.items()} for row in vorgaenge],
        'tagesabschluesse': [{k: _serial(v) for k, v in row.items()} for row in abschluesse],
    }
