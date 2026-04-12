"""DB-Snapshot-Utility: Tabellenzustand vor/nach einer Buchung erfassen.

Erfasst den Zustand aller buchungsrelevanten Tabellen (JOURNAL, JOURNALPOS,
ARTIKEL_HISTORIE, NUMMERN_LOG, TSE_LOG, SATZSPERRE, KASSE_LOG, ARTIKEL.MENGE_AKT)
und berechnet das Delta (neu eingefügte / geänderte Datensätze).
"""

from dataclasses import dataclass, field

# Tabellen und ihre Primärschlüssel, die bei einer Kassenbuchung betroffen sind.
# Reihenfolge entspricht dem CAO-Transaktionsmuster aus HAB-331.
BUCHUNGS_TABELLEN = {
    'SATZSPERRE':       {'pk': 'REC_ID',    'sql': 'SELECT * FROM SATZSPERRE ORDER BY REC_ID'},
    'TSE_LOG':          {'pk': 'REC_ID',    'sql': 'SELECT * FROM TSE_LOG ORDER BY REC_ID'},
    'JOURNAL':          {'pk': 'REC_ID',    'sql': 'SELECT * FROM JOURNAL ORDER BY REC_ID DESC LIMIT 50'},
    'JOURNALPOS':       {'pk': 'REC_ID',    'sql': 'SELECT * FROM JOURNALPOS ORDER BY REC_ID DESC LIMIT 200'},
    'ARTIKEL_HISTORIE': {'pk': 'REC_ID',    'sql': 'SELECT * FROM ARTIKEL_HISTORIE ORDER BY REC_ID DESC LIMIT 200'},
    'NUMMERN_LOG':      {'pk': 'REC_ID',    'sql': 'SELECT * FROM NUMMERN_LOG ORDER BY REC_ID DESC LIMIT 50'},
    'KASSE_LOG':        {'pk': 'REC_ID',    'sql': 'SELECT * FROM KASSE_LOG ORDER BY REC_ID DESC LIMIT 50'},
    'ARTIKEL_BESTAND':  {'pk': 'REC_ID',    'sql': 'SELECT REC_ID, ARTNUM, MENGE_AKT FROM ARTIKEL WHERE REC_ID IN ({artikel_ids})'},
}


@dataclass
class TabellenSnapshot:
    """Snapshot einer einzelnen Tabelle: PK → Row-Dict."""
    tabelle: str
    rows: dict = field(default_factory=dict)  # {pk_value: {col: val, ...}}


@dataclass
class BuchungsSnapshot:
    """Snapshot aller buchungsrelevanten Tabellen zu einem Zeitpunkt."""
    tabellen: dict = field(default_factory=dict)  # {tabelle_name: TabellenSnapshot}


@dataclass
class TabellenDelta:
    """Differenz einer Tabelle zwischen zwei Snapshots."""
    tabelle: str
    neue_rows: list = field(default_factory=list)      # rows die nur in 'nachher' existieren
    geaenderte_rows: list = field(default_factory=list) # rows mit geänderten Feldern
    geloeschte_pks: list = field(default_factory=list)  # PKs die nur in 'vorher' existieren

    @property
    def hat_aenderungen(self) -> bool:
        return bool(self.neue_rows or self.geaenderte_rows or self.geloeschte_pks)


@dataclass
class BuchungsDelta:
    """Gesamt-Delta einer Buchung über alle Tabellen."""
    deltas: dict = field(default_factory=dict)  # {tabelle_name: TabellenDelta}

    @property
    def betroffene_tabellen(self) -> list:
        return [name for name, d in self.deltas.items() if d.hat_aenderungen]


def snapshot_erstellen(cursor, artikel_ids: list | None = None) -> BuchungsSnapshot:
    """Erstellt einen Snapshot aller buchungsrelevanten Tabellen.

    Args:
        cursor: DB-Cursor (dict-Cursor).
        artikel_ids: Liste von ARTIKEL.REC_IDs für Bestandsprüfung.
                     Wenn None, wird ARTIKEL_BESTAND übersprungen.
    """
    snap = BuchungsSnapshot()

    for tabelle, info in BUCHUNGS_TABELLEN.items():
        ts = TabellenSnapshot(tabelle=tabelle)
        sql = info['sql']

        if tabelle == 'ARTIKEL_BESTAND':
            if not artikel_ids:
                snap.tabellen[tabelle] = ts
                continue
            placeholders = ','.join(['%s'] * len(artikel_ids))
            sql = sql.format(artikel_ids=placeholders)
            cursor.execute(sql, tuple(artikel_ids))
        else:
            cursor.execute(sql)

        pk_col = info['pk']
        for row in cursor.fetchall():
            pk_val = row[pk_col]
            ts.rows[pk_val] = dict(row)

        snap.tabellen[tabelle] = ts

    return snap


def delta_berechnen(vorher: BuchungsSnapshot, nachher: BuchungsSnapshot) -> BuchungsDelta:
    """Berechnet das Delta zwischen zwei Snapshots."""
    delta = BuchungsDelta()

    for tabelle in BUCHUNGS_TABELLEN:
        ts_vor = vorher.tabellen.get(tabelle, TabellenSnapshot(tabelle=tabelle))
        ts_nach = nachher.tabellen.get(tabelle, TabellenSnapshot(tabelle=tabelle))

        td = TabellenDelta(tabelle=tabelle)

        # Neue Rows (in nachher, nicht in vorher)
        for pk, row in ts_nach.rows.items():
            if pk not in ts_vor.rows:
                td.neue_rows.append(row)

        # Geänderte Rows (in beiden, aber unterschiedliche Werte)
        for pk in set(ts_vor.rows) & set(ts_nach.rows):
            row_vor = ts_vor.rows[pk]
            row_nach = ts_nach.rows[pk]
            aenderungen = {}
            for col in set(row_vor) | set(row_nach):
                v_vor = row_vor.get(col)
                v_nach = row_nach.get(col)
                if str(v_vor) != str(v_nach):
                    aenderungen[col] = {'vorher': v_vor, 'nachher': v_nach}
            if aenderungen:
                td.geaenderte_rows.append({
                    'pk': pk,
                    'aenderungen': aenderungen,
                })

        # Gelöschte Rows (in vorher, nicht in nachher)
        for pk in ts_vor.rows:
            if pk not in ts_nach.rows:
                td.geloeschte_pks.append(pk)

        delta.deltas[tabelle] = td

    return delta
