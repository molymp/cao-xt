"""
CAO-XT Kassen-App – DSFinV-K Export

Unterstützt mehrere TSE-Geräte und TSE-Wechsel innerhalb des Exportzeitraums.
Wenn z.B. Fiskaly → Swissbit gewechselt wurde oder eine alte gegen eine neue
Swissbit wegen abgelaufenem Zertifikat getauscht wurde, werden alle im Zeitraum
aktiven Geräte erkannt und korrekt behandelt.

TSE-Typen im Exportkontext:
  FISKALY live  – Export via Fiskaly Management API (TAR-Archiv für Betriebsprüfung)
  FISKALY test  – Test-TSS, kein offizieller Export (Hinweis)
  SWISSBIT      – Lokaler DSFinV-K-Export (noch nicht implementiert, Hinweis)
  DEMO          – Keine prüfungsrelevanten Signaturen (Hinweis)

Trainings-/Demo-Bons (TSE_SERIAL = 'TRAININGSMODUS') werden vom Export
ausgeschlossen und separat gezählt.
"""
import requests
import config
from db import get_db
import logging

log = logging.getLogger(__name__)


# ── Interne Hilfsfunktionen ───────────────────────────────────────

def _auth_token(api_key: str, api_secret: str) -> str:
    """Holt einen Fiskaly Management API Access Token."""
    resp = requests.post(
        f"{config.FISKALY_MGMT_URL}/auth",
        json={'api_key': api_key, 'api_secret': api_secret},
        timeout=15
    )
    resp.raise_for_status()
    return resp.json()['access_token']


def _geraet_laden(geraet_id: int) -> dict:
    """Lädt ein TSE-Gerät aus XT_KASSE_TSE_GERAETE. Wirft RuntimeError wenn nicht gefunden."""
    with get_db() as cur:
        cur.execute(
            "SELECT * FROM XT_KASSE_TSE_GERAETE WHERE REC_ID = %s",
            (geraet_id,)
        )
        row = cur.fetchone()
    if not row:
        raise RuntimeError(f"TSE-Gerät {geraet_id} nicht gefunden.")
    return row


def _geraete_im_zeitraum(datum_von: str, datum_bis: str) -> dict:
    """
    Gibt alle TSE-Geräte zurück die im angegebenen Zeitraum aktiv waren,
    klassifiziert nach Export-Relevanz.

    Kriterium: IN_BETRIEB_SEIT <= datum_bis UND
               (AUSSER_BETRIEB IS NULL ODER AUSSER_BETRIEB >= datum_von)

    Rückgabe:
      {
        'fiskaly_live': [row, ...],  # → Export via Fiskaly API
        'fiskaly_test': [row, ...],  # → kein Betriebsprüfungs-Export (Hinweis)
        'swissbit':     [row, ...],  # → lokaler Export nicht implementiert (Hinweis)
        'demo':         [row, ...],  # → keine prüfungsrelevanten Signaturen (Hinweis)
      }
    """
    with get_db() as cur:
        cur.execute(
            """SELECT * FROM XT_KASSE_TSE_GERAETE
               WHERE (IN_BETRIEB_SEIT IS NULL OR IN_BETRIEB_SEIT <= %s)
                 AND (AUSSER_BETRIEB  IS NULL OR AUSSER_BETRIEB  >= %s)
               ORDER BY TYP, COALESCE(IN_BETRIEB_SEIT, ERSTELLT)""",
            (datum_bis, datum_von)
        )
        alle = cur.fetchall()

    result = {'fiskaly_live': [], 'fiskaly_test': [], 'swissbit': [], 'demo': []}
    for g in alle:
        typ = g.get('TYP', 'DEMO')
        if typ == 'FISKALY':
            env = (g.get('FISKALY_ENV') or 'test').lower()
            if env == 'live':
                result['fiskaly_live'].append(g)
            else:
                result['fiskaly_test'].append(g)
        elif typ == 'SWISSBIT':
            result['swissbit'].append(g)
        else:
            result['demo'].append(g)
    return result


def _trainings_bons_zaehlen(terminal_nr: int, datum_von: str, datum_bis: str) -> int:
    """Zählt abgeschlossene Trainings-/Demo-Bons im Zeitraum (TSE_SERIAL = 'TRAININGSMODUS')."""
    with get_db() as cur:
        cur.execute(
            """SELECT COUNT(*) AS N FROM XT_KASSE_VORGAENGE
               WHERE TERMINAL_NR = %s
                 AND STATUS = 'ABGESCHLOSSEN'
                 AND DATE(BON_DATUM) BETWEEN %s AND %s
                 AND TSE_SERIAL = 'TRAININGSMODUS'""",
            (terminal_nr, datum_von, datum_bis)
        )
        return cur.fetchone()['N']


# ── Öffentliche API ───────────────────────────────────────────────

def dsfinvk_export_starten(terminal_nr: int,
                            datum_von: str, datum_bis: str) -> dict:
    """
    Startet DSFinV-K-Exporte für alle im Zeitraum aktiven Fiskaly-live-TSEs.
    Berücksichtigt TSE-Wechsel: für jede TSS wird ein separater Export angestoßen.

    datum_von / datum_bis: 'YYYY-MM-DD'

    Rückgabe:
    {
      'ok':             bool,
      'exporte': [
        { 'geraet_id':   int,
          'bezeichnung': str,
          'tss_id':      str,
          'export_id':   str,
          'state':       str },  # PENDING, COMPLETED, ERROR
        ...
      ],
      'warnungen':      [str, ...],   # Hinweise zu Test/Swissbit/Demo-TSEs
      'fehler':         [str, ...],   # Fehlermeldungen bei einzelnen TSEs
      'trainings_bons': int,          # Anzahl ausgeschlossener Trainings-Bons
    }
    """
    geraete       = _geraete_im_zeitraum(datum_von, datum_bis)
    trainings_bons = _trainings_bons_zaehlen(terminal_nr, datum_von, datum_bis)
    exporte   = []
    warnungen = []
    fehler    = []

    # ── Fiskaly live TSEs ─────────────────────────────────────────
    for g in geraete['fiskaly_live']:
        bezeichnung = g.get('BEZEICHNUNG') or f"Fiskaly TSE #{g['REC_ID']}"
        if not (g.get('FISKALY_TSS_ID') and g.get('FISKALY_API_KEY')
                and g.get('FISKALY_API_SECRET')):
            fehler.append(
                f"Fiskaly TSE „{bezeichnung}" hat keine vollständige "
                f"API-Konfiguration (API-Key/Secret/TSS-ID fehlt)."
            )
            continue
        try:
            token   = _auth_token(g['FISKALY_API_KEY'], g['FISKALY_API_SECRET'])
            headers = {'Authorization': f'Bearer {token}',
                       'Content-Type': 'application/json'}
            body    = {
                'start_date': f'{datum_von}T00:00:00.000Z',
                'end_date':   f'{datum_bis}T23:59:59.999Z',
            }
            resp = requests.post(
                f"{config.FISKALY_MGMT_URL}/tss/{g['FISKALY_TSS_ID']}/export",
                json=body, headers=headers, timeout=30
            )
            resp.raise_for_status()
            data = resp.json()
            exporte.append({
                'geraet_id':   g['REC_ID'],
                'bezeichnung': bezeichnung,
                'tss_id':      g['FISKALY_TSS_ID'],
                'export_id':   data.get('_id') or data.get('id'),
                'state':       data.get('state', 'PENDING'),
            })
            log.info('DSFinV-K Export gestartet: TSE %s, Export-ID %s',
                     bezeichnung, exporte[-1]['export_id'])
        except Exception as e:
            fehler.append(f"Fiskaly TSE „{bezeichnung}": {e}")
            log.warning('DSFinV-K Export fehlgeschlagen für %s: %s', bezeichnung, e)

    # ── Fiskaly test TSEs ─────────────────────────────────────────
    for g in geraete['fiskaly_test']:
        warnungen.append(
            f"Fiskaly-Test-TSE „{g.get('BEZEICHNUNG', 'unbekannt')}" war im Zeitraum aktiv – "
            f"Test-Transaktionen sind nicht Bestandteil des offiziellen Exports."
        )

    # ── Swissbit TSEs ─────────────────────────────────────────────
    for g in geraete['swissbit']:
        warnungen.append(
            f"Swissbit USB-TSE „{g.get('BEZEICHNUNG', 'unbekannt')}" war im Zeitraum aktiv. "
            f"Für Swissbit-Transaktionen ist kein automatisierter DSFinV-K-Export implementiert – "
            f"bitte die lokale JSON-Übersicht als Grundlage verwenden."
        )

    # ── DEMO TSEs ─────────────────────────────────────────────────
    for g in geraete['demo']:
        warnungen.append(
            f"DEMO-TSE „{g.get('BEZEICHNUNG', 'unbekannt')}" ist kein prüfungsrelevantes Gerät "
            f"und wird nicht exportiert."
        )

    # ── Trainings-Bons ────────────────────────────────────────────
    if trainings_bons:
        warnungen.append(
            f"{trainings_bons} Trainings-/Demo-Bon(s) im Zeitraum werden vom Export "
            f"ausgeschlossen (keine echten TSE-Signaturen)."
        )

    if not geraete['fiskaly_live'] and not fehler:
        warnungen.insert(0,
            "Keine aktive Fiskaly-live-TSE im Zeitraum gefunden. "
            "Für den offiziellen DSFinV-K-Export wird eine Fiskaly-live-TSE benötigt."
        )

    return {
        'ok':             len(fehler) == 0,
        'exporte':        exporte,
        'warnungen':      warnungen,
        'fehler':         fehler,
        'trainings_bons': trainings_bons,
    }


def dsfinvk_export_status(geraet_id: int, export_id: str) -> dict:
    """
    Prüft den Status eines laufenden Fiskaly-Exports.
    Gibt {'state': 'PENDING'|'COMPLETED'|'ERROR', 'href': '...'} zurück.
    """
    g     = _geraet_laden(geraet_id)
    token = _auth_token(g['FISKALY_API_KEY'], g['FISKALY_API_SECRET'])
    resp  = requests.get(
        f"{config.FISKALY_MGMT_URL}/tss/{g['FISKALY_TSS_ID']}/export/{export_id}",
        headers={'Authorization': f'Bearer {token}'},
        timeout=15
    )
    resp.raise_for_status()
    data = resp.json()
    return {
        'state': data.get('state', 'UNKNOWN'),
        'href':  data.get('href') or data.get('download_url'),
    }


def dsfinvk_export_herunterladen(geraet_id: int, export_id: str) -> bytes:
    """
    Lädt das fertige TAR-Archiv eines abgeschlossenen Fiskaly-Exports herunter.
    """
    g      = _geraet_laden(geraet_id)
    status = dsfinvk_export_status(geraet_id, export_id)
    if status['state'] != 'COMPLETED':
        raise RuntimeError(f"Export {export_id} noch nicht bereit: {status['state']}")

    token = _auth_token(g['FISKALY_API_KEY'], g['FISKALY_API_SECRET'])
    url   = (status.get('href') or
             f"{config.FISKALY_MGMT_URL}/tss/{g['FISKALY_TSS_ID']}/export/{export_id}/file")
    resp  = requests.get(url,
                         headers={'Authorization': f'Bearer {token}'},
                         timeout=60)
    resp.raise_for_status()
    return resp.content


def lokale_export_daten(terminal_nr: int,
                         datum_von: str, datum_bis: str) -> dict:
    """
    Erstellt eine lokale Übersicht aller Kassenvorgänge für den Exportzeitraum.
    Ergänzend zum Fiskaly-TAR; nützlich für interne Prüfungen und als
    Grundlage für Swissbit-Transaktionen.

    Trainings-/Demo-Bons (TSE_SERIAL = 'TRAININGSMODUS') werden ausgeschlossen.
    """
    def _serial(obj):
        if hasattr(obj, 'isoformat'):
            return obj.isoformat()
        return str(obj) if obj is not None else None

    with get_db() as cur:
        # Echte Vorgänge (keine Trainings-Bons)
        cur.execute(
            """SELECT v.*,
                      GROUP_CONCAT(z.ZAHLART ORDER BY z.ID SEPARATOR ',') AS ZAHLARTEN
               FROM XT_KASSE_VORGAENGE v
               LEFT JOIN XT_KASSE_ZAHLUNGEN z ON z.VORGANG_ID = v.ID
               WHERE v.TERMINAL_NR = %s
                 AND v.STATUS = 'ABGESCHLOSSEN'
                 AND DATE(v.BON_DATUM) BETWEEN %s AND %s
                 AND COALESCE(v.TSE_SERIAL, '') != 'TRAININGSMODUS'
               GROUP BY v.ID
               ORDER BY v.BON_DATUM""",
            (terminal_nr, datum_von, datum_bis)
        )
        vorgaenge = cur.fetchall()

        # Trainings-Bons separat zählen (zur Information)
        cur.execute(
            """SELECT COUNT(*) AS N FROM XT_KASSE_VORGAENGE
               WHERE TERMINAL_NR = %s
                 AND STATUS = 'ABGESCHLOSSEN'
                 AND DATE(BON_DATUM) BETWEEN %s AND %s
                 AND TSE_SERIAL = 'TRAININGSMODUS'""",
            (terminal_nr, datum_von, datum_bis)
        )
        trainings_bons = cur.fetchone()['N']

        # Tagesabschlüsse
        cur.execute(
            """SELECT DATUM, Z_NR, ZEITPUNKT, UMSATZ_BRUTTO, ANZAHL_BELEGE,
                      TSE_SIGNATUR_ZAEHLER, TSE_SERIAL
               FROM XT_KASSE_TAGESABSCHLUSS
               WHERE TERMINAL_NR = %s AND DATUM BETWEEN %s AND %s
               ORDER BY DATUM""",
            (terminal_nr, datum_von, datum_bis)
        )
        abschluesse = cur.fetchall()

        # TSE-Geräte im Zeitraum (zur Information)
        geraete_info = _geraete_im_zeitraum(datum_von, datum_bis)
        geraete_liste = []
        for typ, geraete in geraete_info.items():
            for g in geraete:
                geraete_liste.append({
                    'geraet_id':    g['REC_ID'],
                    'bezeichnung':  g.get('BEZEICHNUNG'),
                    'typ':          g.get('TYP'),
                    'env':          g.get('FISKALY_ENV'),
                    'seriennummer': g.get('SERIENNUMMER'),
                    'in_betrieb':   _serial(g.get('IN_BETRIEB_SEIT')),
                    'ausser_betrieb': _serial(g.get('AUSSER_BETRIEB')),
                })

    return {
        'terminal_nr':      terminal_nr,
        'datum_von':        datum_von,
        'datum_bis':        datum_bis,
        'anzahl_belege':    len(vorgaenge),
        'trainings_bons':   trainings_bons,
        'vorgaenge':        [{k: _serial(v) for k, v in row.items()}
                             for row in vorgaenge],
        'tagesabschluesse': [{k: _serial(v) for k, v in row.items()}
                             for row in abschluesse],
        'tse_geraete':      geraete_liste,
    }
