"""
Dorfkern Banking — Datenzugriff auf die Hibiscus-Tabellen.

Alle Queries laufen gegen ``cao_XT_DEV`` (= unser Default-Schema) —
die Hibiscus-Tabellen wurden 1:1 dorthin gespiegelt. Schreibzugriff
auf diese Tabellen vermeiden wir bewusst (Phase E.2 nutzt die
Hibiscus-XML-RPC-API).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from common.db import get_db


def konten_liste() -> list[dict[str, Any]]:
    """Alle Bank-Konten + Saldo + 30-Tage-Umsatz-Statistik.

    Liefert pro Konto:
      id, kontonummer, blz, name, bezeichnung (= Anzeige-Name),
      kategorie, iban, bic, waehrung, saldo, saldo_datum,
      anzahl_umsaetze_30t, eingang_30t, ausgang_30t.
    """
    seit = date.today() - timedelta(days=30)
    with get_db() as cur:
        cur.execute(
            """SELECT k.id, k.kontonummer, k.blz, k.name, k.bezeichnung,
                      k.kategorie, k.iban, k.bic, k.waehrung,
                      k.saldo, k.saldo_datum, k.kommentar,
                      (SELECT COUNT(*) FROM umsatz u
                        WHERE u.konto_id = k.id AND u.datum >= %s
                      )                                AS umsaetze_30t,
                      (SELECT COALESCE(SUM(betrag),0) FROM umsatz u
                        WHERE u.konto_id = k.id AND u.datum >= %s
                          AND u.betrag > 0
                      )                                AS eingang_30t,
                      (SELECT COALESCE(SUM(betrag),0) FROM umsatz u
                        WHERE u.konto_id = k.id AND u.datum >= %s
                          AND u.betrag < 0
                      )                                AS ausgang_30t
                 FROM konto k
                ORDER BY k.id""",
            (seit, seit, seit),
        )
        return list(cur.fetchall() or [])


def konto_holen(konto_id: int) -> dict[str, Any] | None:
    """Header-Daten eines einzelnen Konto-Datensatzes."""
    with get_db() as cur:
        cur.execute(
            """SELECT id, kontonummer, blz, name, bezeichnung,
                      kategorie, iban, bic, waehrung,
                      saldo, saldo_datum, kommentar
                 FROM konto WHERE id = %s""",
            (int(konto_id),),
        )
        return cur.fetchone()


def umsaetze_liste(*, konto_id: int | None = None,
                    suche: str = '',
                    von_datum: date | None = None,
                    bis_datum: date | None = None,
                    art_filter: str | None = None,
                    nur_storniert: bool = False,
                    limit: int = 200) -> list[dict[str, Any]]:
    """Umsätze-Liste mit Filtern.

    Suche: Substring auf empfaenger_name, zweck, zweck2, zweck3,
    primanota, art.
    art_filter: exakte ART-Bezeichnung (z.B. 'BASISLASTSCHRIFT').
    """
    where = ['1=1']
    params: list[Any] = []
    if konto_id is not None:
        where.append('u.konto_id = %s')
        params.append(int(konto_id))
    if suche:
        where.append(
            '(u.empfaenger_name LIKE %s OR u.zweck LIKE %s '
            ' OR u.zweck2 LIKE %s OR u.zweck3 LIKE %s '
            ' OR u.primanota LIKE %s OR u.art LIKE %s)'
        )
        like = f'%{suche}%'
        params.extend([like] * 6)
    if von_datum:
        where.append('u.datum >= %s')
        params.append(von_datum)
    if bis_datum:
        where.append('u.datum <= %s')
        params.append(bis_datum)
    if art_filter:
        where.append('u.art = %s')
        params.append(art_filter)
    params.append(int(limit))

    sql = f"""
        SELECT u.id, u.konto_id, u.datum, u.valuta, u.betrag, u.saldo,
               u.empfaenger_name, u.empfaenger_name2,
               u.empfaenger_konto, u.empfaenger_blz,
               u.zweck, u.zweck2, u.zweck3,
               u.art, u.primanota, u.gvcode, u.purposecode,
               u.endtoendid, u.mandateid, u.creditorid, u.customerref,
               u.umsatztyp_id, ut.name AS umsatztyp_name,
               u.flags, u.kommentar,
               k.bezeichnung AS konto_bez
          FROM umsatz u
     LEFT JOIN umsatztyp ut ON ut.id = u.umsatztyp_id
     LEFT JOIN konto k      ON k.id  = u.konto_id
         WHERE {' AND '.join(where)}
         ORDER BY u.datum DESC, u.id DESC
         LIMIT %s
    """
    with get_db() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall() or [])


def umsatz_arten() -> list[dict[str, Any]]:
    """Distinct-ART-Werte mit Anzahl, für Filter-Dropdown."""
    with get_db() as cur:
        cur.execute(
            """SELECT art, COUNT(*) AS n FROM umsatz
                WHERE art IS NOT NULL AND art <> ''
                GROUP BY art ORDER BY n DESC LIMIT 30"""
        )
        return list(cur.fetchall() or [])


def sepa_ueberweisungen_liste(*, konto_id: int | None = None,
                                limit: int = 50) -> list[dict[str, Any]]:
    """SEPA-Sammler-Übersicht: Header + aggregierte Buchungen."""
    where = ['1=1']
    params: list[Any] = []
    if konto_id is not None:
        where.append('s.konto_id = %s')
        params.append(int(konto_id))
    params.append(int(limit))
    sql = f"""
        SELECT s.id, s.konto_id, s.bezeichnung, s.termin,
               s.ausgefuehrt, s.ausgefuehrt_am, s.pmtinfid,
               COUNT(b.id) AS buchungen_n,
               COALESCE(SUM(b.betrag), 0) AS summe,
               k.bezeichnung AS konto_bez
          FROM sepasueb s
     LEFT JOIN sepasuebbuchung b ON b.sepasueb_id = s.id
     LEFT JOIN konto k ON k.id = s.konto_id
         WHERE {' AND '.join(where)}
         GROUP BY s.id
         ORDER BY s.termin DESC, s.id DESC
         LIMIT %s
    """
    with get_db() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall() or [])


def sepa_ueberweisung_detail(rec_id: int) -> dict[str, Any] | None:
    """Header + alle Buchungen einer SEPA-Sammelüberweisung."""
    with get_db() as cur:
        cur.execute(
            """SELECT s.*, k.bezeichnung AS konto_bez, k.iban AS konto_iban
                 FROM sepasueb s
            LEFT JOIN konto k ON k.id = s.konto_id
                WHERE s.id = %s""",
            (int(rec_id),),
        )
        kopf = cur.fetchone()
        if not kopf:
            return None
        cur.execute(
            """SELECT id, empfaenger_name, empfaenger_konto, empfaenger_bic,
                      betrag, zweck, endtoendid, purposecode
                 FROM sepasuebbuchung
                WHERE sepasueb_id = %s
                ORDER BY id""",
            (int(rec_id),),
        )
        kopf['buchungen'] = list(cur.fetchall() or [])
        kopf['summe'] = sum(float(b['betrag'] or 0)
                            for b in kopf['buchungen'])
    return kopf
