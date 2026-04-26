"""
Koppelkauf-Analyse: Aktionsprodukte + Co-Purchase-Muster

Für ein Aktionsprodukt analysiert dieses Modul:
  1. Eigenverkauf-Kennzahlen (Bons, Stückzahl, Umsatz)
  2. Welche Artikel wurden im selben Kassenbon gekauft (Koppelkäufe)
  3. Vergleich über 5 Perioden: Aktion / Vorwoche / Folgewoche / Vorjahr /
     Vorjahr gleiche KW
  4. Einfache Einschätzung "War die Aktion merkbar?"

Datenbasis:
  JOURNALPOS × JOURNAL – Kassenbons (QUELLE=3, QUELLE_SUB=2, STADIUM<127)
  ARTIKEL_PREIS (PT2='AP') – Aktionszeiträume aus CAO-Stammdaten
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from db import get_cao_db


# ── Hilfsfunktionen ────────────────────────────────────────────────────────────

def _float(val: Any) -> float:
    try:
        return float(val or 0)
    except (TypeError, ValueError):
        return 0.0


def _pct_diff(neu: float, alt: float) -> float | None:
    """Relative Veränderung in Prozent; None wenn Basis 0."""
    if alt == 0:
        return None
    return round((neu - alt) / alt * 100, 1)


def _vorjahr_selbe_kw(von: date, bis: date) -> tuple[date, date]:
    """
    Gleiche ISO-Kalenderwochen im Vorjahr.

    Strategie: Verschiebt von/bis auf den entsprechenden Montag derselben
    ISO-KW im Vorjahr. Funktioniert auch bei Aktionen über Jahreswechsel.
    """
    iso_von = von.isocalendar()
    iso_bis = bis.isocalendar()
    # Montag der jeweiligen ISO-KW im Vorjahr
    vj_von = date.fromisocalendar(iso_von[0] - 1, iso_von[1], iso_von[2])
    vj_bis = date.fromisocalendar(iso_bis[0] - 1, iso_bis[1], iso_bis[2])
    return vj_von, vj_bis


# ── Aktionsliste ───────────────────────────────────────────────────────────────

def aktionsartikel_liste(stichtag: date | None = None, limit: int = 80) -> list[dict]:
    """
    Artikel mit Aktionspreis – aktuell oder in den letzten 180 Tagen.

    Wird auf der Auswahlseite angezeigt. Neueste Aktionen zuerst.
    """
    ref = stichtag or date.today()
    grenze = ref - timedelta(days=180)

    # CAO-Schema: ARTIKEL_PREIS verlinkt ueber ARTIKEL_ID auf ARTIKEL.REC_ID;
    # die ARTNUM holen wir aus ARTIKEL. Aktionspreise haben PT2='AP' und
    # nutzen GUELTIG_VON / GUELTIG_BIS als Aktionszeitraum, PREIS1 als
    # Aktionspreis. Normalpreis = ARTIKEL.VK5 (Kassenpreis-Ebene).
    sql = """
        SELECT
            a.ARTNUM                                        AS ARTNUM,
            COALESCE(a.KAS_NAME, a.KURZNAME, a.MATCHCODE)   AS bezeichnung,
            ap.PREIS                                       AS aktions_preis,
            a.VK5                                           AS normal_preis,
            ap.GUELTIG_VON                                  AS DATUM_AB,
            ap.GUELTIG_BIS                                  AS DATUM_BIS,
            CASE
                WHEN ap.GUELTIG_VON <= %s
                     AND (ap.GUELTIG_BIS IS NULL OR ap.GUELTIG_BIS >= %s)
                THEN 1 ELSE 0
            END                                             AS aktiv
        FROM ARTIKEL_PREIS ap
        JOIN ARTIKEL a ON a.REC_ID = ap.ARTIKEL_ID
        WHERE ap.PT2 = 'AP'
          AND ap.GUELTIG_VON >= %s
          AND a.ARTNUM IS NOT NULL
          AND a.ARTNUM != ''
        ORDER BY aktiv DESC, ap.GUELTIG_VON DESC
        LIMIT %s
    """
    with get_cao_db() as cur:
        cur.execute(sql, (ref, ref, grenze, limit))
        rows = cur.fetchall()

    result = []
    for r in rows:
        normal = _float(r['normal_preis'])
        aktion = _float(r['aktions_preis'])
        rabatt = round((normal - aktion) / normal * 100, 1) if normal > 0 else None
        result.append({
            'artnum':        r['ARTNUM'],
            'bezeichnung':   r['bezeichnung'] or r['ARTNUM'],
            'aktions_preis': aktion,
            'normal_preis':  normal,
            'rabatt_pct':    rabatt,
            'datum_ab':      r['DATUM_AB'],
            'datum_bis':     r['DATUM_BIS'],
            'aktiv':         bool(r['aktiv']),
        })
    return result


def aktionszeitraum_holen(artnum: str, stichtag: date | None = None) -> dict | None:
    """
    Liefert den relevantesten Aktionszeitraum für einen Artikel.

    Priorität:
      1. Zum Stichtag aktive Aktion
      2. Letzte abgeschlossene Aktion (DATUM_BIS < heute, neueste zuerst)
    """
    ref = stichtag or date.today()

    with get_cao_db() as cur:
        # Aktiv zum Stichtag
        cur.execute(
            """
            SELECT a.ARTNUM,
                   ap.PREIS AS aktions_preis, a.VK5 AS normal_preis,
                   ap.GUELTIG_VON AS DATUM_AB, ap.GUELTIG_BIS AS DATUM_BIS,
                   COALESCE(a.KAS_NAME, a.KURZNAME, a.MATCHCODE) AS bezeichnung
              FROM ARTIKEL_PREIS ap
              JOIN ARTIKEL a ON a.REC_ID = ap.ARTIKEL_ID
             WHERE a.ARTNUM = %s
               AND ap.PT2 = 'AP'
               AND ap.GUELTIG_VON <= %s
               AND (ap.GUELTIG_BIS IS NULL OR ap.GUELTIG_BIS >= %s)
             ORDER BY ap.GUELTIG_VON DESC
             LIMIT 1
            """,
            (artnum, ref, ref),
        )
        row = cur.fetchone()
        if not row:
            # Letzte abgeschlossene Aktion
            cur.execute(
                """
                SELECT a.ARTNUM,
                       ap.PREIS AS aktions_preis, a.VK5 AS normal_preis,
                       ap.GUELTIG_VON AS DATUM_AB, ap.GUELTIG_BIS AS DATUM_BIS,
                       COALESCE(a.KAS_NAME, a.KURZNAME, a.MATCHCODE) AS bezeichnung
                  FROM ARTIKEL_PREIS ap
                  JOIN ARTIKEL a ON a.REC_ID = ap.ARTIKEL_ID
                 WHERE a.ARTNUM = %s
                   AND ap.PT2 = 'AP'
                   AND ap.GUELTIG_BIS IS NOT NULL
                 ORDER BY ap.GUELTIG_BIS DESC
                 LIMIT 1
                """,
                (artnum,),
            )
            row = cur.fetchone()

    if not row:
        return None

    normal = _float(row['normal_preis'])
    aktion = _float(row['aktions_preis'])
    rabatt = round((normal - aktion) / normal * 100, 1) if normal > 0 else None
    return {
        'artnum':        row['ARTNUM'],
        'bezeichnung':   row['bezeichnung'] or row['ARTNUM'],
        'aktions_preis': aktion,
        'normal_preis':  normal,
        'rabatt_pct':    rabatt,
        'datum_ab':      row['DATUM_AB'],
        'datum_bis':     row['DATUM_BIS'],
    }


# ── Eigenverkauf ────────────────────────────────────────────────────────────────

def periode_umsatz(artnum: str, von: date, bis: date) -> dict:
    """Eigenverkauf-Kennzahlen für einen Artikel in einem Zeitraum."""
    sql = """
        SELECT
            COUNT(DISTINCT j.REC_ID)       AS anzahl_bons,
            COALESCE(SUM(jp.MENGE), 0)     AS stueckzahl,
            COALESCE(SUM(jp.GPREIS), 0)    AS brutto_umsatz
        FROM JOURNALPOS jp
        JOIN JOURNAL j ON j.REC_ID = jp.JOURNAL_ID
        WHERE jp.ARTNUM = %s
          AND j.QUELLE = 3
          AND j.QUELLE_SUB = 2
          AND j.STADIUM < 127
          AND DATE(j.RDATUM) BETWEEN %s AND %s
    """
    with get_cao_db() as cur:
        cur.execute(sql, (artnum, von, bis))
        row = cur.fetchone() or {}
    tage = (bis - von).days + 1
    bons  = int(row.get('anzahl_bons')  or 0)
    stk   = _float(row.get('stueckzahl'))
    um    = _float(row.get('brutto_umsatz'))
    return {
        'anzahl_bons':    bons,
        'stueckzahl':     round(stk, 2),
        'brutto_umsatz':  round(um, 2),
        'tage':           tage,
        'bons_pro_tag':   round(bons / tage, 2) if tage else 0,
    }


# ── Koppelkauf ─────────────────────────────────────────────────────────────────

def koppelkauf_top(artnum: str, von: date, bis: date,
                   anzahl_bons_gesamt: int = 0,
                   top_n: int = 20) -> list[dict]:
    """
    Top-N Artikel, die im selben Kassenbon wie das Aktionsprodukt gekauft wurden.

    Subquery findet alle JOURNAL_IDs mit dem Zielartikel, äußere Query
    aggregiert alle anderen Positionen aus denselben Bons.
    """
    sql = """
        SELECT
            jp2.ARTNUM,
            MAX(COALESCE(a.KAS_NAME, a.KURZNAME, jp2.BEZEICHNUNG)) AS bezeichnung,
            COUNT(DISTINCT jp2.JOURNAL_ID)                          AS anzahl_bons,
            COALESCE(SUM(jp2.MENGE), 0)                             AS stueckzahl,
            COALESCE(SUM(jp2.GPREIS), 0)                            AS brutto_umsatz
        FROM JOURNALPOS jp2
        JOIN (
            SELECT DISTINCT jp1.JOURNAL_ID
            FROM JOURNALPOS jp1
            JOIN JOURNAL j ON j.REC_ID = jp1.JOURNAL_ID
            WHERE jp1.ARTNUM = %s
              AND j.QUELLE = 3
              AND j.QUELLE_SUB = 2
              AND j.STADIUM < 127
              AND DATE(j.RDATUM) BETWEEN %s AND %s
        ) bons ON bons.JOURNAL_ID = jp2.JOURNAL_ID
        LEFT JOIN ARTIKEL a ON a.ARTNUM = jp2.ARTNUM
        WHERE jp2.ARTNUM != %s
          AND jp2.ARTNUM IS NOT NULL
          AND jp2.ARTNUM != ''
        GROUP BY jp2.ARTNUM
        ORDER BY anzahl_bons DESC
        LIMIT %s
    """
    with get_cao_db() as cur:
        cur.execute(sql, (artnum, von, bis, artnum, top_n))
        rows = cur.fetchall()

    basis = anzahl_bons_gesamt or 1
    result = []
    for r in rows:
        bons = int(r['anzahl_bons'] or 0)
        result.append({
            'artnum':        r['ARTNUM'],
            'bezeichnung':   r['bezeichnung'] or r['ARTNUM'],
            'anzahl_bons':   bons,
            'stueckzahl':    round(_float(r['stueckzahl']), 2),
            'brutto_umsatz': round(_float(r['brutto_umsatz']), 2),
            'kopplungsrate': round(bons / basis * 100, 1),
        })
    return result


# ── Perioden-Berechnung ────────────────────────────────────────────────────────

def vergleichsperioden(von: date, bis: date) -> dict[str, dict]:
    """
    Berechnet die 4 Vergleichsperioden zur Aktionsperiode.

    Folgewoche: nur wenn bis < heute (zukünftige Aktionen ausgeblendet).
    Vorjahr-KW: gleiche ISO-Woche(n) im Vorjahr.
    """
    heute = date.today()
    laenge = (bis - von).days  # Aktionsdauer in Tagen

    perioden: dict[str, dict] = {}

    # Vorwoche (gleiche Anzahl Tage, direkt vor Aktionsbeginn)
    vw_bis = von - timedelta(days=1)
    vw_von = vw_bis - timedelta(days=laenge)
    perioden['vorwoche'] = {
        'label': 'Vorwoche/-zeitraum',
        'von':   vw_von,
        'bis':   vw_bis,
    }

    # Folgewoche (gleiche Anzahl Tage nach Aktionsende) – nur bei abgeschlossener Aktion
    if bis < heute:
        fw_von = bis + timedelta(days=1)
        fw_bis = fw_von + timedelta(days=laenge)
        perioden['folgewoche'] = {
            'label': 'Folgewoche/-zeitraum',
            'von':   fw_von,
            'bis':   fw_bis,
        }
    else:
        perioden['folgewoche'] = None

    # Vorjahr exakt gleicher Zeitraum
    vj_von = von.replace(year=von.year - 1)
    vj_bis = bis.replace(year=bis.year - 1)
    perioden['vorjahr'] = {
        'label': 'Vorjahr (gleiche Daten)',
        'von':   vj_von,
        'bis':   vj_bis,
    }

    # Vorjahr gleiche ISO-Kalenderwoche(n)
    vj_kw_von, vj_kw_bis = _vorjahr_selbe_kw(von, bis)
    perioden['vorjahr_kw'] = {
        'label': f'Vorjahr KW {von.isocalendar()[1]}',
        'von':   vj_kw_von,
        'bis':   vj_kw_bis,
    }

    return perioden


# ── Interpretation ─────────────────────────────────────────────────────────────

def _uplift_einschaetzen(aktion_bons: int, vergleich_bons: list[int]) -> dict:
    """
    Bewertet ob die Aktion zu mehr Verkäufen geführt hat.

    Vergleichsbasis: Durchschnitt der vorhandenen Vergleichsperioden.
    Gibt dict zurück: {'klasse': 'gut'|'mittel'|'gering'|'keine_daten', 'text': ...}
    """
    basis_werte = [v for v in vergleich_bons if v > 0]
    if not basis_werte:
        return {
            'klasse': 'keine_daten',
            'text': 'Keine Vergleichsdaten vorhanden – Einschätzung nicht möglich.',
        }
    basis_avg = sum(basis_werte) / len(basis_werte)
    if basis_avg == 0:
        return {
            'klasse': 'keine_daten',
            'text': 'Artikel hatte in Vergleichsperioden keinen Umsatz.',
        }
    uplift = (aktion_bons - basis_avg) / basis_avg * 100

    if uplift >= 25:
        return {
            'klasse': 'gut',
            'uplift': round(uplift, 1),
            'text': (
                f'Die Aktion war klar merkbar: +{uplift:.0f} % mehr Käufe '
                f'als im Durchschnitt der Vergleichsperioden. '
                f'Der Aktionspreis hat deutlich mehr Kunden angesprochen.'
            ),
        }
    if uplift >= 8:
        return {
            'klasse': 'mittel',
            'uplift': round(uplift, 1),
            'text': (
                f'Die Aktion hatte einen spürbaren Effekt: +{uplift:.0f} % '
                f'gegenüber dem Vergleichszeitraum. '
                f'Sichtbarkeit der Aktion im Laden prüfen – mehr Aufmerksamkeit '
                f'könnte den Effekt verstärken.'
            ),
        }
    if uplift >= -5:
        return {
            'klasse': 'gering',
            'uplift': round(uplift, 1),
            'text': (
                f'Die Aktion war kaum merkbar ({uplift:+.0f} % vs. Vergleich). '
                f'Mögliche Ursachen: Artikel wenig bekannt, Platzierung, '
                f'Aktionskommunikation oder Preissignal zu schwach.'
            ),
        }
    return {
        'klasse': 'rueckgang',
        'uplift': round(uplift, 1),
        'text': (
            f'Aktionszeitraum zeigt Rückgang ({uplift:.0f} % vs. Vergleich). '
            f'Saisonale Effekte oder Verfügbarkeitsprobleme prüfen.'
        ),
    }


# ── Margen-/Rabatt-Analyse ─────────────────────────────────────────────────────

def margen_analyse(normalpreis: float, aktionspreis: float,
                    stueckzahl: float) -> dict:
    """Aktionsrabatt-Volumen und Bruttowerte pro Stueck.

    Rabatt-Volumen = (Normalpreis - Aktionspreis) × Stueckzahl. Bei
    Aktionspreisen ist das per Definition der entgangene Bruttoumsatz
    gegenueber Normalpreis – wir nennen ihn im UI 'Aktionsrabatt' bzw.
    'Margenverlust' (umgangssprachlich, auch wenn er strenggenommen
    Bruttoumsatz-Verlust ist; die *Marge* haengt zusaetzlich am EK).
    """
    rabatt_pro_stk = max(normalpreis - aktionspreis, 0.0)
    return {
        'normal_pro_stk':     round(normalpreis,       4),
        'aktion_pro_stk':     round(aktionspreis,      4),
        'rabatt_pro_stk':     round(rabatt_pro_stk,    4),
        'stueckzahl':         round(stueckzahl,        2),
        'normal_brutto':      round(normalpreis * stueckzahl,   2),
        'aktion_brutto':      round(aktionspreis * stueckzahl,  2),
        'rabatt_volumen':     round(rabatt_pro_stk * stueckzahl, 2),
    }


# ── Bon-Wert-Analyse ───────────────────────────────────────────────────────────

def bon_wert_vergleich(artnum: str, von: date, bis: date) -> dict:
    """Durchschnittlicher Bon-Wert mit/ohne Aktionsartikel im Zeitraum.

    Liefert:
      mit_aktion:    Mittelwert NSUMME aller Bons, in denen artnum
                     mindestens einmal vorkommt.
      ohne_aktion:   Mittelwert NSUMME aller anderen Bons im Zeitraum.
      delta_pct:     Prozentualer Aufschlag mit-vs-ohne. None wenn
                     ohne_aktion = 0.
    """
    sql_mit = """
        SELECT AVG(j.NSUMME) AS avg_summe, COUNT(*) AS anzahl
        FROM JOURNAL j
        WHERE j.QUELLE = 3 AND j.QUELLE_SUB = 2 AND j.STADIUM < 127
          AND DATE(j.RDATUM) BETWEEN %s AND %s
          AND j.REC_ID IN (
              SELECT DISTINCT JOURNAL_ID FROM JOURNALPOS WHERE ARTNUM = %s
          )
    """
    sql_ohne = """
        SELECT AVG(j.NSUMME) AS avg_summe, COUNT(*) AS anzahl
        FROM JOURNAL j
        WHERE j.QUELLE = 3 AND j.QUELLE_SUB = 2 AND j.STADIUM < 127
          AND DATE(j.RDATUM) BETWEEN %s AND %s
          AND j.REC_ID NOT IN (
              SELECT DISTINCT JOURNAL_ID FROM JOURNALPOS WHERE ARTNUM = %s
          )
    """
    with get_cao_db() as cur:
        cur.execute(sql_mit, (von, bis, artnum))
        mit = cur.fetchone() or {}
        cur.execute(sql_ohne, (von, bis, artnum))
        ohne = cur.fetchone() or {}
    avg_mit  = _float(mit.get('avg_summe'))
    avg_ohne = _float(ohne.get('avg_summe'))
    delta = _pct_diff(avg_mit, avg_ohne)
    return {
        'mit_aktion_avg':   round(avg_mit, 2),
        'mit_aktion_anz':   int(mit.get('anzahl') or 0),
        'ohne_aktion_avg':  round(avg_ohne, 2),
        'ohne_aktion_anz':  int(ohne.get('anzahl') or 0),
        'delta_pct':        delta,
    }


# ── Insight-Generator (regelbasiert) ───────────────────────────────────────────

def insights_generieren(analyse: dict) -> list[dict]:
    """Erzeugt aus den Roh-Kennzahlen 3–5 textuelle Erkenntnisse.

    Rein regelbasiert (kein LLM, kein externes Wissen). Jedes Insight
    ist ein dict mit ``typ`` ('positiv'|'warn'|'info'), ``titel`` (kurz)
    und ``text`` (1-2 Saetze).

    Heuristiken (siehe Mockup):
      1. Top-1 Koppel-Quote ≥ 50 %  -> 'X+Y-Buendel funktioniert'
      2. Im Top-5 ein Hochpreis-Artikel mit absolut hohem Umsatz aber
         relativ niedriger Quote -> 'X zieht den Bon-Wert hoch'
      3. Folgewoche-Umsatz > Vorwoche-Umsatz, Aktion abgeschlossen
         -> 'Nachzieheffekt erkennbar'
      4. Vorjahr-KW-Bons + Aktion-Bons > 50 % Uplift  -> 'Vorjahr lag
         deutlich darunter'
      5. Rabatt-Volumen >= 100 EUR -> Warn-Insight
      6. Bon-Wert mit-vs-ohne >= +20 %  -> 'Aktion hebt den Bon-Wert'
    """
    insights: list[dict] = []
    aktion_um   = analyse.get('aktion_umsatz', {}) or {}
    koppel      = analyse.get('koppel_aktion', []) or []
    perioden    = analyse.get('perioden', {}) or {}
    margen      = analyse.get('margen', {}) or {}
    bon_wert    = analyse.get('bon_wert', {}) or {}

    # 1. Top-1 Koppel-Quote
    if koppel:
        top1 = koppel[0]
        quote = float(top1.get('kopplungsrate') or 0)
        if quote >= 70:
            insights.append({
                'typ': 'positiv',
                'titel': f"{top1['bezeichnung']} ist ein fest etabliertes "
                          f"Begleitprodukt.",
                'text':  f"In {quote:.0f} % der Bons mit dem Aktionsartikel "
                          f"war auch {top1['bezeichnung']} dabei. "
                          f"Beim naechsten Mal als kombinierte Display-"
                          f"Aktion kommunizieren.",
            })
        elif quote >= 50:
            insights.append({
                'typ': 'positiv',
                'titel': f"{top1['bezeichnung']}-Buendel funktioniert.",
                'text':  f"{quote:.0f} % der Bons mit dem Aktionsartikel "
                          f"enthalten {top1['bezeichnung']} – ein klares "
                          f"Buendel-Muster.",
            })

    # 2. Hochpreis-Begleiter: ein Artikel im Top-5, der NICHT Top-1 ist,
    #    aber trotzdem viel Umsatz beisteuert obwohl seine Quote
    #    deutlich niedriger ist als die von Top-1. Solche Artikel ziehen
    #    erfahrungsgemaess den Bon-Wert hoch.
    if len(koppel) >= 3:
        top5 = koppel[:5]
        top1 = koppel[0]
        # Top-1 ausschliessen (wird schon in Regel 1 gewuerdigt).
        kandidaten = [k for k in top5
                       if k is not top1
                       and float(k.get('brutto_umsatz') or 0) >= 100]
        if kandidaten:
            kand = max(kandidaten,
                        key=lambda x: float(x.get('brutto_umsatz') or 0))
            kand_quote  = float(kand.get('kopplungsrate') or 0)
            kand_umsatz = float(kand.get('brutto_umsatz') or 0)
            top1_quote  = float(top1.get('kopplungsrate') or 0)
            if kand_quote < top1_quote * 0.6:
                insights.append({
                    'typ': 'info',
                    'titel': f"{kand['bezeichnung']} zieht den Bon-Wert hoch.",
                    'text':  f"Nur {kand_quote:.0f} % der Aktions-Bons enthalten "
                              f"{kand['bezeichnung']}, der Artikel traegt aber "
                              f"{kand_umsatz:.0f} € zum Begleitumsatz bei – ein "
                              f"hochpreisiges Komplementaerprodukt.",
                })

    # 3. Nachzieheffekt: Folgewoche > Vorwoche
    vw = perioden.get('vorwoche')
    fw = perioden.get('folgewoche')
    if vw and fw:
        vw_bons = (vw.get('umsatz') or {}).get('anzahl_bons', 0)
        fw_bons = (fw.get('umsatz') or {}).get('anzahl_bons', 0)
        if fw_bons > vw_bons * 1.3 and vw_bons > 0:
            uplift = (fw_bons - vw_bons) / vw_bons * 100
            insights.append({
                'typ': 'positiv',
                'titel': "Folgewoche profitiert nach.",
                'text':  f"Auch nach Aktionsende liegt der Verkauf um "
                          f"{uplift:.0f} % ueber der Vorwoche – die Aktion "
                          f"hat offenbar Stammkunden angezogen, die "
                          f"erstmal weiterkaufen. Reaktivierung in 4 "
                          f"Wochen pruefen.",
            })

    # 4. Vorjahr-KW deutlich darunter
    vj_kw = perioden.get('vorjahr_kw')
    if vj_kw:
        vjk_bons   = (vj_kw.get('umsatz') or {}).get('anzahl_bons', 0)
        aktion_bons = aktion_um.get('anzahl_bons', 0)
        if aktion_bons > vjk_bons * 1.5 and vjk_bons > 0:
            up = (aktion_bons - vjk_bons) / vjk_bons * 100
            insights.append({
                'typ': 'info',
                'titel': "Vorjahr lag deutlich darunter.",
                'text':  f"Gegenueber der gleichen KW im Vorjahr liegt der "
                          f"Verkauf um +{up:.0f} %. Der Effekt ist also "
                          f"echter Aktionsantrieb, kein reiner "
                          f"Saisoneffekt.",
            })

    # 5. Rabatt-Volumen-Warnung
    rab_vol = float(margen.get('rabatt_volumen') or 0)
    if rab_vol >= 100:
        insights.append({
            'typ':   'warn',
            'titel': "Aktionsrabatt im Auge behalten.",
            'text':  f"Bei {margen.get('stueckzahl', 0):.0f} verkauften "
                      f"Stueck wurden {rab_vol:.0f} € Bruttoumsatz gegenueber "
                      f"Normalpreis nicht erloest. Mehrumsatz aus Koppel-"
                      f"kaeufen sollte das mehr als ausgleichen.",
        })

    # 6. Bon-Wert mit-vs-ohne
    delta = bon_wert.get('delta_pct')
    if delta is not None and delta >= 20:
        insights.append({
            'typ': 'positiv',
            'titel': "Aktion hebt den Bon-Wert.",
            'text':  f"Bons mit Aktionsartikel sind im Schnitt "
                      f"{bon_wert.get('mit_aktion_avg', 0):.2f} € wert – "
                      f"+{delta:.0f} % gegenueber Bons ohne diesen Artikel "
                      f"({bon_wert.get('ohne_aktion_avg', 0):.2f} €). Die "
                      f"Aktion zieht hoehere Warenkoerbe an.",
        })

    return insights


# ── Hauptfunktion ──────────────────────────────────────────────────────────────

def analyse_komplett(
    artnum: str,
    aktions_von: date,
    aktions_bis: date,
    top_n: int = 15,
    aktionspreis: float | None = None,
    normalpreis: float | None = None,
) -> dict:
    """
    Vollständige Koppelkauf-Analyse für einen Artikel und Aktionszeitraum.

    Rückgabe:
    {
        'aktion_umsatz': {...},
        'koppel_aktion': [...],
        'perioden': {...},
        'interpretation': {...},
        'margen': {...} | None,    # nur wenn Preise vorhanden
        'bon_wert': {...},
        'insights': [...],
        'aktions_von': date,
        'aktions_bis': date,
    }
    """
    # Eigenverkauf im Aktionszeitraum
    aktion_um = periode_umsatz(artnum, aktions_von, aktions_bis)
    aktion_bons = aktion_um['anzahl_bons']

    # Koppelkäufe im Aktionszeitraum
    koppel_aktion = koppelkauf_top(artnum, aktions_von, aktions_bis,
                                   anzahl_bons_gesamt=aktion_bons, top_n=top_n)

    # Vergleichsperioden
    vp = vergleichsperioden(aktions_von, aktions_bis)

    perioden: dict[str, Any] = {}
    vergleich_bons: list[int] = []

    for key, info in vp.items():
        if info is None:
            perioden[key] = None
            continue
        um = periode_umsatz(artnum, info['von'], info['bis'])
        kp = koppelkauf_top(artnum, info['von'], info['bis'],
                            anzahl_bons_gesamt=um['anzahl_bons'], top_n=top_n)
        perioden[key] = {
            'label':  info['label'],
            'von':    info['von'],
            'bis':    info['bis'],
            'umsatz': um,
            'koppel': kp,
        }
        vergleich_bons.append(um['anzahl_bons'])

    interpretation = _uplift_einschaetzen(aktion_bons, vergleich_bons)

    # Margen-/Rabatt-Analyse: nur wenn beide Preise bekannt + Verkauf > 0
    margen = None
    if (normalpreis is not None and aktionspreis is not None
            and aktion_um.get('stueckzahl', 0) > 0
            and normalpreis > aktionspreis):
        margen = margen_analyse(float(normalpreis), float(aktionspreis),
                                 float(aktion_um['stueckzahl']))

    # Bon-Wert-Vergleich mit-vs-ohne Aktionsartikel
    try:
        bon_wert = bon_wert_vergleich(artnum, aktions_von, aktions_bis)
    except Exception:
        bon_wert = None

    ergebnis = {
        'aktions_von':    aktions_von,
        'aktions_bis':    aktions_bis,
        'aktion_umsatz':  aktion_um,
        'koppel_aktion':  koppel_aktion,
        'perioden':       perioden,
        'interpretation': interpretation,
        'margen':         margen,
        'bon_wert':       bon_wert,
    }
    ergebnis['insights'] = insights_generieren(ergebnis)
    return ergebnis
