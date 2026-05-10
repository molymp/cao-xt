"""
Dorfkern Banking — Datenzugriff auf die Hibiscus-Tabellen.

Alle Queries laufen gegen ``cao_XT_DEV`` (= unser Default-Schema) —
die Hibiscus-Tabellen wurden 1:1 dorthin gespiegelt.

Schreibzugriff:
- ``umsatz.flags`` (Bit 0 = "Geprüft", siehe FLAG_GEPRUEFT) und
  ``umsatz.kommentar`` (Notiz) duerfen wir direkt setzen — Hibiscus
  liest beide Felder beim naechsten GUI-Refresh. KEIN
  Optimistic-Locking-Konflikt zu erwarten, da die GUI dieselben
  Spalten nutzt.
- Alle anderen Tabellen (Ueberweisungen, Lastschriften etc.) gehen
  ueber die Hibiscus-XML-RPC-API in Phase E.2.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from common.db import get_db, get_db_transaction


# Bit-Flags von ``umsatz.flags`` (aus de.willuhn.jameica.hbci.rmi.Umsatz)
FLAG_GEPRUEFT  = 1   # User hat den Umsatz "abgehakt" (Bit 0)
FLAG_NOTBOOKED = 2   # Vormerkung der Bank, noch nicht endgueltig (Bit 1)


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
                    suche_regex: bool = False,
                    von_datum: date | None = None,
                    bis_datum: date | None = None,
                    art_filter: str | None = None,
                    umsatztyp_id: int | None = None,
                    nur_ungeprueft: bool = False,
                    limit: int = 200) -> list[dict[str, Any]]:
    """Umsätze-Liste mit Filtern.

    suche: Substring (LIKE) oder regulaerer Ausdruck (REGEXP, wenn
    ``suche_regex=True``) auf empfaenger_name, zweck, zweck2, zweck3,
    primanota, art, kommentar.
    art_filter: exakte ART-Bezeichnung (z.B. 'BASISLASTSCHRIFT').
    umsatztyp_id: Filter auf Hibiscus-Kategorie (umsatztyp.id).
    nur_ungeprueft: nur Umsaetze mit ``flags IS NULL OR flags=0``
    (= nicht "abgehakt") — fuer den Reconcile-Workflow.
    """
    where = ['1=1']
    params: list[Any] = []
    if konto_id is not None:
        where.append('u.konto_id = %s')
        params.append(int(konto_id))
    if suche:
        op = 'REGEXP' if suche_regex else 'LIKE'
        like = suche if suche_regex else f'%{suche}%'
        where.append(
            f'(IFNULL(u.empfaenger_name,"") {op} %s '
            f' OR IFNULL(u.zweck,"") {op} %s '
            f' OR IFNULL(u.zweck2,"") {op} %s '
            f' OR IFNULL(u.zweck3,"") {op} %s '
            f' OR IFNULL(u.primanota,"") {op} %s '
            f' OR IFNULL(u.art,"") {op} %s '
            f' OR IFNULL(u.kommentar,"") {op} %s)'
        )
        params.extend([like] * 7)
    if von_datum:
        where.append('u.datum >= %s')
        params.append(von_datum)
    if bis_datum:
        where.append('u.datum <= %s')
        params.append(bis_datum)
    if art_filter:
        where.append('u.art = %s')
        params.append(art_filter)
    if umsatztyp_id is not None:
        where.append('u.umsatztyp_id = %s')
        params.append(int(umsatztyp_id))
    if nur_ungeprueft:
        # Bit 0 (FLAG_GEPRUEFT) NICHT gesetzt
        where.append('(u.flags IS NULL OR (u.flags & 1) = 0)')
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


def umsatztypen_liste() -> list[dict[str, Any]]:
    """Hibiscus-Kategorien (umsatztyp) — sortiert nach name. Fuer das
    Filter-Dropdown."""
    with get_db() as cur:
        cur.execute(
            """SELECT id, name, umsatztyp, parent_id, color
                 FROM umsatztyp
                ORDER BY parent_id IS NULL DESC, parent_id, name"""
        )
        return list(cur.fetchall() or [])


def umsatz_geprueft_setzen(umsatz_id: int, geprueft: bool) -> None:
    """Setzt/loescht das FLAG_GEPRUEFT-Bit (Bit 0) auf umsatz.flags.

    Wir berechnen das neue flags-Feld atomar via Bit-Operation, damit
    andere Bits (z.B. FLAG_NOTBOOKED=2) nicht verloren gehen.
    """
    with get_db_transaction() as cur:
        if geprueft:
            cur.execute(
                "UPDATE umsatz "
                "SET flags = IFNULL(flags, 0) | %s "
                "WHERE id = %s",
                (FLAG_GEPRUEFT, int(umsatz_id))
            )
        else:
            cur.execute(
                "UPDATE umsatz "
                "SET flags = IFNULL(flags, 0) & ~%s "
                "WHERE id = %s",
                (FLAG_GEPRUEFT, int(umsatz_id))
            )


def umsatz_notiz_setzen(umsatz_id: int, notiz: str) -> None:
    """Setzt umsatz.kommentar (Notiz). Leerer String → NULL."""
    notiz = (notiz or '').strip() or None
    with get_db_transaction() as cur:
        cur.execute(
            "UPDATE umsatz SET kommentar = %s WHERE id = %s",
            (notiz, int(umsatz_id))
        )


def umsatz_kategorie_setzen(umsatz_id: int, umsatztyp_id: int | None) -> None:
    """Setzt umsatz.umsatztyp_id (Hibiscus-Kategorie). None → entfernen."""
    with get_db_transaction() as cur:
        cur.execute(
            "UPDATE umsatz SET umsatztyp_id = %s WHERE id = %s",
            (int(umsatztyp_id) if umsatztyp_id else None,
             int(umsatz_id))
        )


# Zeitraum-Presets fuer das UI-Filter-Dropdown.
# Die Werte werden lazy berechnet relativ zu ``date.today()``.

def zeitraum_presets() -> list[dict[str, Any]]:
    """Liefert eine Liste von Zeitraum-Vorlagen (von, bis, label).

    Nicht aus der DB — Hibiscus speichert keine solche Liste; nur
    BPD-Konfig pro Bank-Schnittstelle. Wir nehmen die uebliche
    Buchhaltungs-Auswahl.
    """
    from datetime import date, timedelta
    heute = date.today()
    j = heute.year
    m = heute.month
    # Hilfen
    def monat_anfang(y, mo): return date(y, mo, 1)
    def monat_ende(y, mo):
        return (monat_anfang(y, mo + 1) - timedelta(days=1)
                if mo < 12 else date(y, 12, 31))
    def quartal_grenzen(y, q):
        # q in 1..4 → Monate (1..3), (4..6), (7..9), (10..12)
        m_start = (q - 1) * 3 + 1
        return monat_anfang(y, m_start), monat_ende(y, m_start + 2)
    aktuelles_q = (m - 1) // 3 + 1
    letztes_q   = aktuelles_q - 1 if aktuelles_q > 1 else 4
    j_letztes_q = j if aktuelles_q > 1 else j - 1

    out = [
        {'key': 'aktueller_monat',
         'label': 'Aktueller Monat',
         'von':   monat_anfang(j, m),
         'bis':   heute},
        {'key': 'letzter_monat',
         'label': 'Letzter Monat',
         'von':   monat_anfang(j, m - 1) if m > 1 else date(j-1, 12, 1),
         'bis':   monat_ende(j, m - 1)   if m > 1 else date(j-1, 12, 31)},
        {'key': 'vorletzter_monat',
         'label': 'Vorletzter Monat',
         'von':   monat_anfang(j, m - 2) if m > 2 else
                  monat_anfang(j-1, 12 + m - 2),
         'bis':   monat_ende(j, m - 2)   if m > 2 else
                  monat_ende(j-1, 12 + m - 2)},
        {'key': 'letzte_30',
         'label': 'Letzte 30 Tage',
         'von':   heute - timedelta(days=30),
         'bis':   heute},
        {'key': 'letzte_90',
         'label': 'Letzte 90 Tage',
         'von':   heute - timedelta(days=90),
         'bis':   heute},
        {'key': 'letzte_365',
         'label': 'Letzte 365 Tage',
         'von':   heute - timedelta(days=365),
         'bis':   heute},
        {'key': 'aktuelles_quartal',
         'label': f'Aktuelles Quartal (Q{aktuelles_q}/{j})',
         'von':   quartal_grenzen(j, aktuelles_q)[0],
         'bis':   heute},
        {'key': 'letztes_quartal',
         'label': f'Letztes Quartal (Q{letztes_q}/{j_letztes_q})',
         'von':   quartal_grenzen(j_letztes_q, letztes_q)[0],
         'bis':   quartal_grenzen(j_letztes_q, letztes_q)[1]},
        {'key': 'dieses_jahr',
         'label': f'Dieses Jahr ({j})',
         'von':   date(j, 1, 1),
         'bis':   heute},
        {'key': 'letztes_jahr',
         'label': f'Letztes Jahr ({j-1})',
         'von':   date(j-1, 1, 1),
         'bis':   date(j-1, 12, 31)},
    ]
    return out


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
