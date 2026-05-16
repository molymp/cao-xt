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


def _fmt_dt(v) -> str:
    return v.strftime('%d.%m.%Y %H:%M') if hasattr(v, 'strftime') else str(v)


def hibiscus_sync_status() -> dict[str, Any]:
    """Letzter Bank-Sync — aus Hibiscus' ``protokoll``-Tabelle (DB,
    SSoT). Bewusst NICHT über den ``synchronizescheduler``-XML-RPC-
    Service: der ist im Leerlauf nicht aufrufbar (Jameica-Lifecycle).
    Die DB ist die verlässliche Quelle ("Saldo/Umsätze abgerufen" je
    Konto mit Timestamp).

    Degradiert sauber: liefert immer ein dict. ``verfuegbar=False`` +
    ``hinweis`` wenn noch kein Sync protokolliert ist.
    """
    try:
        with get_db() as cur:
            cur.execute("SELECT MAX(datum) AS m, COUNT(*) AS n "
                        "FROM protokoll")
            row = cur.fetchone() or {}
            letzter = row.get('m')
            anzahl = int(row.get('n') or 0)
            cur.execute("SELECT konto_id, MAX(datum) AS letzter "
                        "FROM protokoll GROUP BY konto_id")
            pro_konto = {r['konto_id']: _fmt_dt(r['letzter'])
                         for r in (cur.fetchall() or [])}
            kommentar = ''
            if letzter is not None:
                cur.execute("SELECT kommentar FROM protokoll "
                            "WHERE datum = %s ORDER BY id DESC LIMIT 1",
                            (letzter,))
                kr = cur.fetchone()
                kommentar = (kr or {}).get('kommentar', '') if kr else ''
    except Exception as e:
        return {'verfuegbar': False,
                'hinweis': f'protokoll nicht lesbar: {str(e)[:140]}'}
    if letzter is None:
        return {'verfuegbar': False,
                'hinweis': 'Noch kein Bank-Sync protokolliert — läuft '
                           'nach FinTS-Einrichtung beim ersten geplanten '
                           'Lauf (S-pushTAN am Handy bestätigen).'}
    return {
        'verfuegbar':  True,
        'letzter':     _fmt_dt(letzter),
        'status_text': kommentar or 'protokolliert',
        'eintraege':   anzahl,
        'pro_konto':   pro_konto,
    }


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


# Zeitraum-Presets fuer das UI-Filter-Dropdown — uebernommen aus dem
# Hibiscus-Standard (Settings → Zeitraeume), reine Wert-Berechnung in
# Python (Hibiscus speichert die Liste zwar in einer cfg-Datei aber
# die Werte sind ja immer dynamisch relativ zu "heute").

def zeitraum_presets() -> list[dict[str, Any]]:
    """Liefert die Hibiscus-Standard-Zeitraeume als Liste von dicts
    ``{key, label, von, bis}``. ``Alles`` hat ``von/bis=None`` (= kein
    Datums-Filter).
    """
    from datetime import date, timedelta
    heute = date.today()
    j = heute.year
    m = heute.month
    # Hilfen
    def monat_anfang(y, mo):
        # mo kann negativ/>12 sein — wir korrigieren
        while mo < 1: mo += 12; y -= 1
        while mo > 12: mo -= 12; y += 1
        return date(y, mo, 1)
    def monat_ende(y, mo):
        ma = monat_anfang(y, mo + 1)
        return ma - timedelta(days=1)
    def quartal_grenzen(y, q):
        m_start = (q - 1) * 3 + 1
        return monat_anfang(y, m_start), monat_ende(y, m_start + 2)
    # ISO-Wochen-Helfer: Montag der Woche, in der `d` liegt
    def woche_montag(d):
        return d - timedelta(days=d.weekday())
    def woche_sonntag(d):
        return woche_montag(d) + timedelta(days=6)

    aktuelles_q = (m - 1) // 3 + 1
    letztes_q   = aktuelles_q - 1 if aktuelles_q > 1 else 4
    j_letztes_q = j if aktuelles_q > 1 else j - 1
    vorletztes_q   = letztes_q - 1 if letztes_q > 1 else 4
    j_vorletztes_q = j_letztes_q if letztes_q > 1 else j_letztes_q - 1

    diese_woche_mo = woche_montag(heute)
    letzte_woche_mo = diese_woche_mo - timedelta(days=7)
    vorletzte_woche_mo = diese_woche_mo - timedelta(days=14)

    out = [
        # ── Tage ─────────────────────────────────────────
        {'key': 'letzte_7',   'label': 'Letzte 7 Tage',
         'von': heute - timedelta(days=7),  'bis': heute},
        {'key': 'letzte_30',  'label': 'Letzte 30 Tage',
         'von': heute - timedelta(days=30), 'bis': heute},
        {'key': 'letzte_90',  'label': 'Letzte 90 Tage',
         'von': heute - timedelta(days=90), 'bis': heute},
        {'key': 'letzte_365', 'label': 'Letzte 365 Tage',
         'von': heute - timedelta(days=365),'bis': heute},
        {'key': 'letzte_3j',  'label': 'Letzte 3 Jahre',
         'von': date(j-3, m, min(heute.day, 28)), 'bis': heute},
        {'key': 'letzte_5j',  'label': 'Letzte 5 Jahre',
         'von': date(j-5, m, min(heute.day, 28)), 'bis': heute},
        {'key': 'letzte_10j', 'label': 'Letzte 10 Jahre',
         'von': date(j-10, m, min(heute.day, 28)),'bis': heute},
        # ── Woche ────────────────────────────────────────
        {'key': 'woche_diese',     'label': 'Woche: Diese',
         'von': diese_woche_mo,         'bis': woche_sonntag(heute)},
        {'key': 'woche_letzte',    'label': 'Woche: Letzte',
         'von': letzte_woche_mo,        'bis': letzte_woche_mo + timedelta(days=6)},
        {'key': 'woche_vorletzte', 'label': 'Woche: Vorletzte',
         'von': vorletzte_woche_mo,     'bis': vorletzte_woche_mo + timedelta(days=6)},
        # ── Monat ────────────────────────────────────────
        {'key': 'monat_dieser',     'label': 'Monat: Dieser',
         'von': monat_anfang(j, m),     'bis': monat_ende(j, m)},
        {'key': 'monat_letzter',    'label': 'Monat: Letzter',
         'von': monat_anfang(j, m - 1), 'bis': monat_ende(j, m - 1)},
        {'key': 'monat_vorletzter', 'label': 'Monat: Vorletzter',
         'von': monat_anfang(j, m - 2), 'bis': monat_ende(j, m - 2)},
        {'key': 'monat_letzte_12',  'label': 'Monat: Letzte 12',
         'von': monat_anfang(j, m - 11),'bis': monat_ende(j, m)},
        # ── Quartal ─────────────────────────────────────
        {'key': 'quartal_dieses',
         'label': f'Quartal: Dieses (Q{aktuelles_q}/{j})',
         'von': quartal_grenzen(j, aktuelles_q)[0],
         'bis': quartal_grenzen(j, aktuelles_q)[1]},
        {'key': 'quartal_letztes',
         'label': f'Quartal: Letztes (Q{letztes_q}/{j_letztes_q})',
         'von': quartal_grenzen(j_letztes_q, letztes_q)[0],
         'bis': quartal_grenzen(j_letztes_q, letztes_q)[1]},
        {'key': 'quartal_vorletztes',
         'label': f'Quartal: Vorletztes (Q{vorletztes_q}/{j_vorletztes_q})',
         'von': quartal_grenzen(j_vorletztes_q, vorletztes_q)[0],
         'bis': quartal_grenzen(j_vorletztes_q, vorletztes_q)[1]},
        # ── Jahr ─────────────────────────────────────────
        {'key': 'jahr_dieses',     'label': f'Jahr: Dieses ({j})',
         'von': date(j, 1, 1),     'bis': date(j, 12, 31)},
        {'key': 'jahr_letztes',    'label': f'Jahr: Letztes ({j-1})',
         'von': date(j-1, 1, 1),   'bis': date(j-1, 12, 31)},
        {'key': 'jahr_vorletztes', 'label': f'Jahr: Vorletztes ({j-2})',
         'von': date(j-2, 1, 1),   'bis': date(j-2, 12, 31)},
        # ── Alles ────────────────────────────────────────
        {'key': 'alles', 'label': 'Alles', 'von': None, 'bis': None},
    ]
    return out


def reconcile_offene_ek_mit_matches(*, min_score: int = 50,
                                      limit: int = 200
                                      ) -> dict[str, Any]:
    """Reconcile-Workflow: liefert alle offenen EK-Belege (JOURNAL.QUELLE=5,
    STADIUM in 2/7/11) mit ihrem besten Hibiscus-Bankumsatz-Match.

    Performance: pro Beleg wird ``bankumsatz_kandidaten_fuer_einkauf``
    aufgerufen (= 1 SQL pro Beleg + Pool-Overhead). Bei ~50 offenen
    Belegen ~3s. Akzeptabel fuer eine Seite, die der User bewusst
    aufruft ("offene Belege durchgehen").

    Returns:
      {
        'mit_top':     [{kopf, top_kandidat}, ...],   # Score >= 80
        'mit_match':   [{kopf, top_kandidat}, ...],   # Score 50-79
        'ohne_match':  [{kopf}, ...],                 # keine Kandidaten
        'gesamt': int,
      }
    """
    # Lazy-import um Zirkular-Imports zu vermeiden
    from modules.orga.bestellwesen.einkauf import (
        bankumsatz_kandidaten_fuer_einkauf,
    )
    with get_db() as cur:
        cur.execute(
            """SELECT j.REC_ID, j.VRENUM, j.ORGNUM, j.RDATUM, j.BSUMME,
                      j.STADIUM, j.ADDR_ID,
                      COALESCE(a.NAME1, j.KUN_NAME1, '–') AS lief_name,
                      a.IBAN AS lief_iban,
                      (SELECT COALESCE(SUM(ABS(BETRAG))+SUM(ABS(SKONTO_BETRAG)),0)
                         FROM ZAHLUNGEN z
                        WHERE z.JOURNAL_ID = j.REC_ID AND z.QUELLE=5
                          AND z.STORNO=0 AND z.GEBUCHT='Y'
                      ) AS bezahlt
                 FROM JOURNAL j
            LEFT JOIN ADRESSEN a ON a.REC_ID = j.ADDR_ID
                WHERE j.QUELLE = 5 AND j.STADIUM IN (2, 7, 11)
                ORDER BY j.RDATUM DESC, j.REC_ID DESC
                LIMIT %s""",
            (int(limit),)
        )
        belege = list(cur.fetchall() or [])

    mit_top: list[dict] = []
    mit_match: list[dict] = []
    ohne_match: list[dict] = []
    for b in belege:
        b['offen'] = abs(float(b['BSUMME'] or 0)) - float(b['bezahlt'] or 0)
        try:
            ks = bankumsatz_kandidaten_fuer_einkauf(int(b['REC_ID']))
        except Exception:
            ks = []
        if ks and ks[0]['score'] >= 80:
            mit_top.append({'kopf': b, 'top': ks[0],
                             'weitere': ks[1:3]})
        elif ks and ks[0]['score'] >= min_score:
            mit_match.append({'kopf': b, 'top': ks[0],
                               'weitere': ks[1:3]})
        else:
            ohne_match.append({'kopf': b})
    return {
        'mit_top':    mit_top,
        'mit_match':  mit_match,
        'ohne_match': ohne_match,
        'gesamt':     len(belege),
    }


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
