"""
Phase E.3 – Reconciler: Bank-Umsatz ↔ SEPA-Vormerkung abgleichen.

Scope = ausschließlich Zeilen in ``XT_HIBISCUS_VORMERKUNG`` mit
``STATUS='vorgemerkt'`` (= von Dorfkern angelegte Aufträge). Manuell
in Jameica erfasste SEPA-Aufträge bleiben unberührt.

Wahrheit = der **echte Bankumsatz** (Hibiscus schreibt seine Tabellen
direkt in cao_XT_DEV — kein XML-RPC nötig), nicht der Auftragsstatus.

Pro Vormerkung:

* ``umsatz.endtoendid = vormerkung.ENDTOENDID`` (deterministisch,
  Belastungskonto, betrag<0) → :func:`einkauf.bankumsatz_uebernehmen`
  bucht ZAHLUNGEN (``ART='UB'``), STADIUM 11→9/7, ``STATUS='bezahlt'``.
* kein Umsatz, Auftrag noch in ``aueberweisung`` → bleibt offen.
* kein Umsatz, Auftrag **nicht mehr** da und Vormerkung älter als die
  Karenz → STADIUM 11→2, ``STATUS='zurueckgesetzt'`` (Auftrag in
  Jameica gelöscht / abgelehnt → Beleg wieder regulär offen).

Bewusst KEIN Fuzzy-Auto-Booking: ohne EndToEndId-Treffer passiert
nichts automatisch — dafür gibt es die manuelle Bankumsatz-Zuordnung
(``bankumsatz_kandidaten_fuer_einkauf``).

Die ``aueberweisung``-Tabelle ist Hibiscus-intern → die Stuck-
Erkennung ist defensiv: schlägt der Zugriff fehl, wird NICHT
zurückgesetzt (lieber ``vorgemerkt`` lassen als einen evtl.
gesendeten Auftrag fälschlich wieder zu öffnen).
"""
from __future__ import annotations

import logging
from typing import Any

from common.db import get_db, get_db_transaction
from common import konfig
from . import einkauf as ek

log = logging.getLogger(__name__)

# Karenz: erst zurücksetzen, wenn die Vormerkung älter als so viele
# Tage ist UND kein Auftrag mehr in Hibiscus liegt (schützt gegen
# Kontoauszug-Import-Verzug). Informativer Hinweis ab _HINWEIS_TAGE.
_RESET_GRACE_TAGE = 3
_HINWEIS_TAGE = 7


def _debit_konto_id() -> int:
    try:
        v = konfig.get('hibiscus.debit_konto_id')
        return int(v) if v not in (None, '') else 0
    except (TypeError, ValueError):
        return 0


def _umsatz_match(cur, endtoendid: str, debit_konto: int):
    """Deterministischer Treffer über die Dorfkern-EndToEndId auf dem
    Belastungskonto (betrag<0 = Geld-Ausgang), noch nicht verbucht."""
    cur.execute(
        "SELECT u.id, u.betrag "
        "  FROM umsatz u "
        " WHERE u.endtoendid = %s AND u.konto_id = %s AND u.betrag < 0 "
        "   AND u.id NOT IN ("
        "        SELECT UW_NUM FROM ZAHLUNGEN "
        "         WHERE QUELLE=5 AND ART='UB' AND UW_NUM > 0) "
        " ORDER BY u.id LIMIT 2",
        (endtoendid, int(debit_konto))
    )
    rows = cur.fetchall() or []
    if len(rows) == 1:
        return rows[0]
    return None  # 0 = noch nicht da; >1 = mehrdeutig → Hände weg


def _auftrag_zustand(cur, auftrag_id: str):
    """Zustand der SEPA-Überweisung in Hibiscus.

    Hibiscus speichert Einzel-SEPA-Überweisungen in der Tabelle
    ``aueberweisung`` (live verifiziert 2026-05-16; NICHT
    ``sepaueberweisung`` — das ist nur der XML-RPC-Service-Name;
    ``sepasueb`` wäre die *Sammel*-Überweisung).

    Returns:
      * ``'weg'``      – keine Zeile mehr (in Jameica gelöscht / nie
                         angelegt) → Reset-Kandidat
      * ``'offen'``    – Zeile da, ``ausgefuehrt=0`` (wartet auf
                         S-pushTAN-Freigabe)
      * ``'gesendet'`` – Zeile da, ``ausgefuehrt=1`` (übertragen,
                         Umsatz folgt) → NICHT zurücksetzen
      * ``None``       – nicht ermittelbar (Schema-Abweichung/Fehler)
                         → defensiv: NICHT zurücksetzen
    """
    if not auftrag_id:
        return None
    try:
        aid = int(str(auftrag_id).strip())
    except (TypeError, ValueError):
        return None
    try:
        cur.execute(
            "SELECT ausgefuehrt FROM aueberweisung WHERE id = %s LIMIT 1",
            (aid,)
        )
        row = cur.fetchone()
        if not row:
            return 'weg'
        return 'gesendet' if int(row.get('ausgefuehrt') or 0) == 1 \
            else 'offen'
    except Exception as e:  # noqa: BLE001 - Schema bewusst defensiv
        log.warning('Stuck-Check nicht möglich (aueberweisung): %s', e)
        return None


def reconcile_vormerkungen(*, max_n: int = 300,
                            ma_name: str = 'Reconciler') -> dict[str, Any]:
    """Gleicht offene Vormerkungen gegen Bankumsätze ab.

    Returns Zusammenfassung
    ``{ok, geprueft, gebucht, zurueckgesetzt, offen, fehler, details}``.
    Idempotent: arbeitet nur auf ``STATUS='vorgemerkt'``; ein bereits
    gebuchter Umsatz ist über den ``UW_NUM``-Filter ausgeschlossen.
    """
    ek._hibiscus_vormerkung_schema()
    debit = _debit_konto_id()

    with get_db() as cur:
        cur.execute(
            "SELECT REC_ID, REFERENZ_ID, ENDTOENDID, HIBISCUS_AUFTRAG_ID, "
            "       BETRAG, "
            "       TIMESTAMPDIFF(DAY, ANGELEGT_AM, NOW()) AS alter_tage "
            "  FROM XT_HIBISCUS_VORMERKUNG "
            " WHERE MODUL='einkauf' AND STATUS='vorgemerkt' "
            " ORDER BY REC_ID LIMIT %s",
            (int(max_n),)
        )
        offene = list(cur.fetchall() or [])

    summary = {'ok': True, 'geprueft': len(offene), 'gebucht': 0,
               'zurueckgesetzt': 0, 'offen': 0, 'fehler': 0,
               'details': []}

    if offene and debit <= 0:
        summary['ok'] = False
        summary['details'].append(
            'Kein Belastungskonto konfiguriert — Abgleich übersprungen.')
        summary['offen'] = len(offene)
        return summary

    for vm in offene:
        vm_id = int(vm['REC_ID'])
        rec_id = int(vm['REFERENZ_ID'])
        e2e = (vm.get('ENDTOENDID') or '').strip()
        auftrag = (vm.get('HIBISCUS_AUFTRAG_ID') or '').strip()
        alter_tage = int(vm.get('alter_tage') or 0)

        try:
            with get_db() as cur:
                treffer = _umsatz_match(cur, e2e, debit) if e2e else None

            if treffer:
                umsatz_id = int(treffer['id'])
                try:
                    ek.bankumsatz_uebernehmen(
                        rec_id, umsatz_id, ma_id=None, ma_name=ma_name)
                    _vm_status(vm_id, 'bezahlt',
                               f'auto-gebucht (umsatz {umsatz_id})')
                    summary['gebucht'] += 1
                    summary['details'].append(
                        f'Beleg {rec_id}: gebucht (umsatz {umsatz_id})')
                except PermissionError as pe:
                    # Beleg z.B. schon anderweitig bezahlt → Vormerkung
                    # ist erledigt, nur Status nachziehen.
                    _vm_status(vm_id, 'bezahlt',
                               f'bereits bezahlt ({pe})')
                    summary['gebucht'] += 1
                continue

            # Kein Umsatz → Stuck-Erkennung (defensiv).
            with get_db() as cur:
                zustand = _auftrag_zustand(cur, auftrag)

            if zustand == 'weg' and alter_tage >= _RESET_GRACE_TAGE:
                _reset_vormerkung(vm_id, rec_id, ma_name)
                summary['zurueckgesetzt'] += 1
                summary['details'].append(
                    f'Beleg {rec_id}: Auftrag in Hibiscus weg → '
                    f'STADIUM 11→2')
            else:
                summary['offen'] += 1
                if zustand == 'offen' and alter_tage >= _HINWEIS_TAGE:
                    summary['details'].append(
                        f'Beleg {rec_id}: seit {alter_tage} T nicht '
                        f'freigegeben — in Jameica mit S-pushTAN senden?')
        except Exception as e:  # noqa: BLE001 - eine Zeile darf nicht alles killen
            log.exception('Reconcile Vormerkung %s (Beleg %s)',
                          vm_id, rec_id)
            summary['fehler'] += 1
            summary['details'].append(f'Beleg {rec_id}: Fehler {e}')

    log.info('Reconcile: %s geprüft, %s gebucht, %s zurückgesetzt, '
             '%s offen, %s Fehler', summary['geprueft'],
             summary['gebucht'], summary['zurueckgesetzt'],
             summary['offen'], summary['fehler'])
    return summary


def _vm_status(vm_id: int, status: str, notiz: str) -> None:
    with get_db_transaction() as cur:
        cur.execute(
            "UPDATE XT_HIBISCUS_VORMERKUNG "
            "   SET STATUS=%s, "
            "       NOTIZ=CONCAT_WS(' | ', NOTIZ, %s) "
            " WHERE REC_ID=%s AND STATUS='vorgemerkt'",
            (status, notiz, int(vm_id))
        )


def _reset_vormerkung(vm_id: int, rec_id: int, ma_name: str) -> None:
    """Auftrag in Hibiscus weg + kein Umsatz → Beleg wieder offen."""
    with get_db_transaction() as cur:
        cur.execute(
            "UPDATE XT_HIBISCUS_VORMERKUNG "
            "   SET STATUS='zurueckgesetzt', "
            "       NOTIZ=CONCAT_WS(' | ', NOTIZ, %s) "
            " WHERE REC_ID=%s AND STATUS='vorgemerkt'",
            (f'auto-zurückgesetzt ({ma_name}): Auftrag in Hibiscus '
             f'entfernt, kein Umsatz', int(vm_id))
        )
        cur.execute(
            "UPDATE JOURNAL SET STADIUM=2 "
            " WHERE REC_ID=%s AND QUELLE=5 AND STADIUM=11",
            (int(rec_id),)
        )
        ek._journal_op_rebuild_qu5(cur)
