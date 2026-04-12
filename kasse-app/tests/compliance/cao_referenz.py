"""CAO-Kasse Pro Referenzdaten für Compliance-Vergleich.

Basierend auf HAB-331 (Transaktionsmuster-Analyse) und Live-DB cao_2018_001.
Definiert das erwartete DB-Schreibmuster für einen Standard-Kassenbon.
"""

from dataclasses import dataclass, field


@dataclass
class FeldErwartung:
    """Erwartung für ein einzelnes Datenbankfeld."""
    feld: str
    cao_wert: object          # Referenzwert aus CAO-Kasse Pro (oder Beschreibung)
    pflicht: bool = True      # Muss das Feld gesetzt werden?
    exakt: bool = False       # Muss der Wert exakt übereinstimmen?
    beschreibung: str = ''    # Erklärung des Feldes


@dataclass
class TabellenErwartung:
    """Erwartete Schreiboperation(en) für eine Tabelle."""
    tabelle: str
    operation: str  # INSERT, UPDATE, DELETE, INSERT+UPDATE, INSERT+DELETE
    anzahl: str     # '1', 'n', 'n*' (pro Position / pro Lagerartikel)
    felder: list = field(default_factory=list)  # [FeldErwartung, ...]
    beschreibung: str = ''


# ─── Standard-Kassenbon: CAO-Transaktionsmuster (HAB-331 Schritt 1–11) ───

CAO_STANDARD_KASSENBON = [
    TabellenErwartung(
        tabelle='SATZSPERRE',
        operation='INSERT+DELETE',
        anzahl='1',
        beschreibung='Row-Lock während der Buchung (30s Timeout), wird am Ende gelöscht.',
        felder=[
            FeldErwartung('MODUL_ID', 'Kassenmodul-ID', pflicht=True, exakt=False,
                          beschreibung='Identifiziert das Kassenmodul'),
            FeldErwartung('SATZ_ID', 'JOURNAL.REC_ID', pflicht=True, exakt=False,
                          beschreibung='ID des gesperrten Datensatzes'),
            FeldErwartung('GUID', 'UUID', pflicht=True, exakt=False,
                          beschreibung='Eindeutige Lock-ID'),
            FeldErwartung('ABLAUFDATUM', 'NOW()+30s', pflicht=True, exakt=False,
                          beschreibung='Lock-Ablauf nach 30 Sekunden'),
        ],
    ),

    TabellenErwartung(
        tabelle='TSE_LOG',
        operation='INSERT+UPDATE',
        anzahl='1',
        beschreibung='TSE-Transaktion: Start-Eintrag (TYP_FLAG=S), dann Update auf Ende (TYP_FLAG=E).',
        felder=[
            FeldErwartung('QUELLE', 32, pflicht=True, exakt=True,
                          beschreibung='32 = XT-Kasse (auch bei CAO: QUELLE=0/3/5 für legacy)'),
            FeldErwartung('TYP_FLAG', 'S→E', pflicht=True, exakt=False,
                          beschreibung='S=Start, E=Ende'),
            FeldErwartung('JOURNAL_ID', 'JOURNAL.REC_ID', pflicht=True, exakt=False,
                          beschreibung='Referenz auf JOURNAL-Eintrag'),
            FeldErwartung('KASSEN_ID', 'terminal_nr', pflicht=True, exakt=True,
                          beschreibung='Terminal-Nummer'),
            FeldErwartung('TSE_TANR', 'TX-Nummer', pflicht=True, exakt=False,
                          beschreibung='TSE-Transaktionsnummer'),
            FeldErwartung('BON_TYP', 'Beleg', pflicht=True, exakt=True,
                          beschreibung='Belegtyp für DSFinV-K'),
            FeldErwartung('TSE_TA_VORGANGSART', 'Kassenbeleg-V1', pflicht=True, exakt=True,
                          beschreibung='Vorgangsart für DSFinV-K'),
            FeldErwartung('TSE_TA_SIGZ', 'Signatur-Zähler', pflicht=True, exakt=False,
                          beschreibung='Monoton steigender Signatur-Zähler'),
            FeldErwartung('TSE_TA_SIG', 'Base64-Signatur', pflicht=True, exakt=False,
                          beschreibung='TSE-Signatur (Base64-kodiert)'),
            FeldErwartung('BON_START', 'Timestamp', pflicht=True, exakt=False,
                          beschreibung='Zeitpunkt Transaktionsstart'),
            FeldErwartung('BON_ENDE', 'Timestamp', pflicht=True, exakt=False,
                          beschreibung='Zeitpunkt Transaktionsende'),
        ],
    ),

    TabellenErwartung(
        tabelle='JOURNAL',
        operation='INSERT+UPDATE',
        anzahl='1',
        beschreibung='Hauptbuchung: INSERT mit HASHSUM="$$", dann UPDATE mit berechneter HASHSUM.',
        felder=[
            FeldErwartung('QUELLE', 3, pflicht=True, exakt=True,
                          beschreibung='3 = Kassenbon (POS)'),
            FeldErwartung('QUELLE_SUB', 2, pflicht=True, exakt=True,
                          beschreibung='2 = Sub-Typ'),
            FeldErwartung('KASSEN_ID', 'terminal_nr', pflicht=True, exakt=True,
                          beschreibung='Terminal-Nummer (1-9)'),
            FeldErwartung('STADIUM', 9, pflicht=True, exakt=True,
                          beschreibung='9 = Standard-Kassenbuchung abgeschlossen'),
            FeldErwartung('VRENUM', 'Bonnummer', pflicht=True, exakt=False,
                          beschreibung='Vorgangsnummer / Bonnummer (z.B. "727061")'),
            FeldErwartung('ADDR_ID', -2, pflicht=True, exakt=True,
                          beschreibung='-2 = anonymer Barverkauf'),
            FeldErwartung('KUN_NAME1', 'Barverkauf', pflicht=True, exakt=True,
                          beschreibung='Kundenname bei Barverkauf'),
            FeldErwartung('KUN_NUM', 0, pflicht=True, exakt=True,
                          beschreibung='Kundennummer = 0 bei Barverkauf'),
            FeldErwartung('ZAHLART', 'ZAHLUNGSARTEN.REC_ID', pflicht=True, exakt=False,
                          beschreibung='FK auf ZAHLUNGSARTEN (1=Bar, 6=EC)'),
            FeldErwartung('ZAHLART_NAME', 'Bar|EC-KARTE', pflicht=True, exakt=False,
                          beschreibung='Name der Zahlungsart'),
            FeldErwartung('BRUTTO_FLAG', 'Y', pflicht=True, exakt=True,
                          beschreibung='Y = Preise sind Brutto-Basis (XT); CAO nutzt N (Netto-Basis)'),
            FeldErwartung('PR_EBENE', 5, pflicht=True, exakt=True,
                          beschreibung='Preisebene 5'),
            FeldErwartung('WAEHRUNG', '€', pflicht=True, exakt=True,
                          beschreibung='Währungskennzeichen'),
            FeldErwartung('KURS', 1.0, pflicht=True, exakt=True,
                          beschreibung='Wechselkurs = 1.0 für EUR'),
            FeldErwartung('BSUMME', 'Brutto-Gesamt', pflicht=True, exakt=True,
                          beschreibung='Bruttosumme (Euro, 4 Dezimalen)'),
            FeldErwartung('NSUMME', 'Netto-Gesamt', pflicht=True, exakt=True,
                          beschreibung='Nettosumme (Euro, 4 Dezimalen)'),
            FeldErwartung('MSUMME', 'MwSt-Gesamt', pflicht=True, exakt=True,
                          beschreibung='MwSt-Summe (Euro, 4 Dezimalen)'),
            FeldErwartung('BSUMME_0', 'Brutto steuerfrei', pflicht=True, exakt=True,
                          beschreibung='Bruttosumme Steuersatz 0%'),
            FeldErwartung('BSUMME_1', 'Brutto 19%', pflicht=True, exakt=True,
                          beschreibung='Bruttosumme Steuersatz 19%'),
            FeldErwartung('BSUMME_2', 'Brutto 7%', pflicht=True, exakt=True,
                          beschreibung='Bruttosumme Steuersatz 7%'),
            FeldErwartung('NSUMME_0', 'Netto steuerfrei', pflicht=True, exakt=True,
                          beschreibung='Nettosumme Steuersatz 0%'),
            FeldErwartung('NSUMME_1', 'Netto 19%', pflicht=True, exakt=True,
                          beschreibung='Nettosumme Steuersatz 19%'),
            FeldErwartung('NSUMME_2', 'Netto 7%', pflicht=True, exakt=True,
                          beschreibung='Nettosumme Steuersatz 7%'),
            FeldErwartung('MSUMME_1', 'MwSt 19%', pflicht=True, exakt=True,
                          beschreibung='MwSt-Betrag 19%'),
            FeldErwartung('MSUMME_2', 'MwSt 7%', pflicht=True, exakt=True,
                          beschreibung='MwSt-Betrag 7%'),
            FeldErwartung('MWST_1', 19.0, pflicht=True, exakt=True,
                          beschreibung='MwSt-Satz 1 in %'),
            FeldErwartung('MWST_2', 7.0, pflicht=True, exakt=True,
                          beschreibung='MwSt-Satz 2 in %'),
            FeldErwartung('GEGEBEN', 'Betrag gegeben', pflicht=True, exakt=False,
                          beschreibung='Vom Kunden gegebener Betrag'),
            FeldErwartung('RDATUM', 'ABSCHLUSS_DATUM', pflicht=True, exakt=False,
                          beschreibung='Rechnungsdatum = Zahlungszeitpunkt'),
            FeldErwartung('KBDATUM', 'ABSCHLUSS_DATUM', pflicht=True, exakt=False,
                          beschreibung='Kassenbuchdatum = Zahlungszeitpunkt'),
            FeldErwartung('GEGENKONTO', -1, pflicht=True, exakt=True,
                          beschreibung='-1 = Barverkauf (kein Debitor)'),
            FeldErwartung('FIRMA_ID', 'FIRMA.REC_ID', pflicht=True, exakt=False,
                          beschreibung='FK auf FIRMA-Tabelle'),
            FeldErwartung('ERSTELLT', 'Timestamp', pflicht=True, exakt=False,
                          beschreibung='Erstellzeitpunkt'),
            FeldErwartung('ERST_NAME', 'Kasse', pflicht=True, exakt=True,
                          beschreibung='Ersteller-Kennung'),
            FeldErwartung('HASHSUM', 'MD5 32-Hex uppercase', pflicht=True, exakt=False,
                          beschreibung='MD5-Hash (Salt + Feldkonkatenation), 32 Zeichen HEX'),
            FeldErwartung('MA_ID', 'MITARBEITER.REC_ID', pflicht=True, exakt=False,
                          beschreibung='FK auf MITARBEITER'),
            FeldErwartung('POS_TA_ID', 'Tagesabschluss-ID', pflicht=True, exakt=False,
                          beschreibung='FK auf aktuellen Tagesabschluss'),
            FeldErwartung('SPRACH_ID', 2, pflicht=True, exakt=True,
                          beschreibung='Sprach-ID (2=Deutsch)'),
            FeldErwartung('TERM_ID', 1, pflicht=True, exakt=False,
                          beschreibung='Terminal-ID'),
        ],
    ),

    TabellenErwartung(
        tabelle='JOURNALPOS',
        operation='INSERT',
        anzahl='n',
        beschreibung='Eine Zeile pro Bonposition (nicht-storniert).',
        felder=[
            FeldErwartung('QUELLE', 3, pflicht=True, exakt=True,
                          beschreibung='3 = Kassenbon'),
            FeldErwartung('QUELLE_SUB', 2, pflicht=True, exakt=True,
                          beschreibung='2 = Sub-Typ'),
            FeldErwartung('JOURNAL_ID', 'JOURNAL.REC_ID', pflicht=True, exakt=True,
                          beschreibung='FK auf JOURNAL'),
            FeldErwartung('POSITION', 'laufend', pflicht=True, exakt=True,
                          beschreibung='Position (0-basiert bei CAO, 1-basiert bei XT)'),
            FeldErwartung('ARTIKELTYP', 'S|F', pflicht=True, exakt=True,
                          beschreibung='S=Standard, F=Freiartikel (ArtID<=0)'),
            FeldErwartung('ARTIKEL_ID', 'ARTIKEL.REC_ID|-99', pflicht=True, exakt=True,
                          beschreibung='FK auf ARTIKEL oder -99 für Freiartikel'),
            FeldErwartung('ARTNUM', 'Artikelnummer', pflicht=True, exakt=True,
                          beschreibung='Artikelnummer (Snapshot)'),
            FeldErwartung('BARCODE', 'EAN', pflicht=True, exakt=True,
                          beschreibung='EAN/Barcode (Snapshot)'),
            FeldErwartung('MATCHCODE', 'ARTIKEL.MATCHCODE', pflicht=True, exakt=False,
                          beschreibung='Matchcode aus Artikelstamm'),
            FeldErwartung('BEZEICHNUNG', 'Text', pflicht=True, exakt=True,
                          beschreibung='Artikelbezeichnung'),
            FeldErwartung('KURZBEZEICHNUNG', 'max 30 Zeichen', pflicht=True, exakt=False,
                          beschreibung='Kurzbezeichnung (KURZNAME oder abgeschnitten)'),
            FeldErwartung('MENGE', 'Verkaufsmenge', pflicht=True, exakt=True,
                          beschreibung='Verkaufsmenge'),
            FeldErwartung('EPREIS', 'Einzelpreis', pflicht=True, exakt=True,
                          beschreibung='Einzelpreis (Euro, 4 Dezimalen)'),
            FeldErwartung('GPREIS', 'Gesamtpreis', pflicht=True, exakt=True,
                          beschreibung='Gesamtpreis (Euro, 4 Dezimalen)'),
            FeldErwartung('EK_PREIS', 0, pflicht=True, exakt=False,
                          beschreibung='EK-Preis (XT setzt 0, CAO berechnet aus Stamm)'),
            FeldErwartung('STEUER_CODE', '0|1|2', pflicht=True, exakt=True,
                          beschreibung='0=steuerfrei, 1=19%, 2=7%'),
            FeldErwartung('BRUTTO_FLAG', 'Y', pflicht=True, exakt=True,
                          beschreibung='Y = Bruttopreise'),
            FeldErwartung('GEBUCHT', 'Y', pflicht=True, exakt=True,
                          beschreibung='Y = Position gebucht'),
            FeldErwartung('GEGENKONTO', 0, pflicht=True, exakt=True,
                          beschreibung='Gegenkonto auf Positionsebene'),
            FeldErwartung('LAGER_ID', -2, pflicht=True, exakt=True,
                          beschreibung='-2 = Standardlager'),
            FeldErwartung('ADDR_ID', -2, pflicht=True, exakt=True,
                          beschreibung='-2 = Barverkauf'),
            FeldErwartung('VRENUM', 'Bonnummer', pflicht=True, exakt=True,
                          beschreibung='Bonnummer (Kopie aus JOURNAL)'),
            FeldErwartung('CALC_FAKTOR', 1, pflicht=True, exakt=True,
                          beschreibung='Umrechnungsfaktor'),
            FeldErwartung('ME_EINHEIT', 'Stk', pflicht=True, exakt=False,
                          beschreibung='Mengeneinheit'),
            FeldErwartung('ME_CODE', 'H87', pflicht=True, exakt=False,
                          beschreibung='UN/ECE-Code für Mengeneinheit'),
            FeldErwartung('WARENGRUPPE', 0, pflicht=True, exakt=False,
                          beschreibung='Warengruppen-ID'),
        ],
    ),

    TabellenErwartung(
        tabelle='ARTIKEL_HISTORIE',
        operation='INSERT',
        anzahl='n*',
        beschreibung='Lagerabbuchung pro Position mit ARTIKEL_ID >= 0 (keine Freiartikel).',
        felder=[
            FeldErwartung('QUELLE', 25, pflicht=True, exakt=True,
                          beschreibung='25 = Kassenbon-Lagerabbuchung'),
            FeldErwartung('QUELLE_STR', 'Kassebon {BONNUMMER}', pflicht=True, exakt=False,
                          beschreibung='Textuelle Quellbeschreibung'),
            FeldErwartung('JID', 'JOURNAL.REC_ID', pflicht=True, exakt=True,
                          beschreibung='FK auf JOURNAL'),
            FeldErwartung('ARTIKEL_ID', 'ARTIKEL.REC_ID', pflicht=True, exakt=True,
                          beschreibung='FK auf ARTIKEL'),
            FeldErwartung('MENGE_GEBUCHT', '-MENGE (negativ)', pflicht=True, exakt=True,
                          beschreibung='Negativ = Lagerabgang'),
            FeldErwartung('MENGE_LAGER', 'aktueller Lagerbestand', pflicht=True, exakt=False,
                          beschreibung='Bestand zum Buchungszeitpunkt'),
            FeldErwartung('LAGER_ID', -2, pflicht=True, exakt=True,
                          beschreibung='-2 = Standardlager'),
        ],
    ),

    TabellenErwartung(
        tabelle='NUMMERN_LOG',
        operation='INSERT',
        anzahl='1',
        beschreibung='Bonnummer-Protokollierung.',
        felder=[
            FeldErwartung('QUELLE', 22, pflicht=True, exakt=True,
                          beschreibung='22 = Kassenbonnummer'),
            FeldErwartung('JOURNAL_ID', 'JOURNAL.REC_ID', pflicht=True, exakt=True,
                          beschreibung='FK auf JOURNAL'),
            FeldErwartung('NUMMER', 'Bonnummer (String)', pflicht=True, exakt=False,
                          beschreibung='Die vergebene Bonnummer'),
            FeldErwartung('ANGELEGT_NAME', 'Kasse', pflicht=True, exakt=True,
                          beschreibung='Ersteller-Kennung'),
        ],
    ),

    TabellenErwartung(
        tabelle='KASSE_LOG',
        operation='INSERT',
        anzahl='1',
        beschreibung='Kassenlade-Öffnungs-Protokoll.',
        felder=[
            FeldErwartung('QUELLE', 1, pflicht=True, exakt=True,
                          beschreibung='1 = Kassenlade geöffnet'),
            FeldErwartung('BEMERKUNG', 'Kassenlade geöffnet', pflicht=True, exakt=False,
                          beschreibung='Beschreibung der Aktion'),
        ],
    ),

    TabellenErwartung(
        tabelle='ARTIKEL',
        operation='UPDATE',
        anzahl='n*',
        beschreibung='Lagerbestandsreduzierung pro Artikel (nur Lagerartikel, ArtID >= 0).',
        felder=[
            FeldErwartung('MENGE_AKT', 'MENGE_AKT -= Verkaufsmenge', pflicht=True, exakt=True,
                          beschreibung='Lagerbestand wird um Verkaufsmenge reduziert'),
        ],
    ),
]


# ─── Beispiel-Bon: CAO-Kasse Pro Referenzbuchung (HAB-331, Bon 727060) ───

REFERENZ_BON_727060 = {
    'beschreibung': 'Standard-Barverkauf, 1 Position, BSUMME=29.23€',
    'journal': {
        'QUELLE': 3,
        'QUELLE_SUB': 2,
        'KASSEN_ID': 1,
        'STADIUM': 9,
        'VRENUM': '727060',
        'ADDR_ID': -2,
        'KUN_NAME1': 'Barverkauf',
        'KUN_NUM': 0,
        'BSUMME': 29.23,
        'GEGENKONTO': -1,
        'ZAHLART': 1,
        'ZAHLART_NAME': 'Bar',
        'BRUTTO_FLAG': 'N',   # CAO nutzt Netto-Basis!
        'PR_EBENE': 5,
        'WAEHRUNG': '€',
        'KURS': 1.0,
        'HASHSUM': '(32-hex-uppercase)',  # Platzhalter
        'ERST_NAME': 'Kasse',
    },
}


# ─── Bekannte Abweichungen zwischen XT und CAO ───

BEKANNTE_ABWEICHUNGEN = {
    'JOURNAL.BRUTTO_FLAG': {
        'xt_wert': 'Y',
        'cao_wert': 'N',
        'beschreibung': (
            'XT-Kasse setzt BRUTTO_FLAG=Y (Preise sind Brutto-Basis), '
            'CAO-Kasse setzt N (Netto-Basis). Beide rechnen die Summen '
            'korrekt um — der Unterschied liegt in der Berechnungsrichtung.'
        ),
        'risiko': 'mittel',
        'empfehlung': 'Prüfen ob CAO-Reports BRUTTO_FLAG auswerten.',
    },
    'JOURNALPOS.EPREIS_BASIS': {
        'xt_wert': 'Brutto-Einzelpreis',
        'cao_wert': 'Netto-Einzelpreis',
        'beschreibung': (
            'Folgt aus BRUTTO_FLAG: XT speichert Brutto-EP in EPREIS, '
            'CAO speichert Netto-EP. GPREIS und die Summen sind identisch.'
        ),
        'risiko': 'mittel',
        'empfehlung': 'Konsistent mit BRUTTO_FLAG-Entscheidung halten.',
    },
    'ARTIKEL_HISTORIE': {
        'xt_wert': 'FEHLT',
        'cao_wert': 'INSERT pro Lagerartikel (QUELLE=25)',
        'beschreibung': (
            'XT-Kasse schreibt keine ARTIKEL_HISTORIE-Einträge. '
            'CAO protokolliert jede Lagerabbuchung mit QUELLE=25.'
        ),
        'risiko': 'hoch',
        'empfehlung': 'ARTIKEL_HISTORIE-Schreibung in bon_zu_journal ergänzen.',
    },
    'NUMMERN_LOG': {
        'xt_wert': 'FEHLT',
        'cao_wert': 'INSERT (QUELLE=22, Bonnummer)',
        'beschreibung': (
            'XT-Kasse schreibt keinen NUMMERN_LOG-Eintrag. '
            'CAO protokolliert jede Bonnummer-Vergabe.'
        ),
        'risiko': 'hoch',
        'empfehlung': 'NUMMERN_LOG-Schreibung in bon_zu_journal ergänzen.',
    },
    'KASSE_LOG': {
        'xt_wert': 'FEHLT',
        'cao_wert': 'INSERT (QUELLE=1, Kassenlade geöffnet)',
        'beschreibung': (
            'XT-Kasse schreibt keinen KASSE_LOG-Eintrag. '
            'CAO protokolliert Kassenlade-Öffnungen.'
        ),
        'risiko': 'niedrig',
        'empfehlung': 'KASSE_LOG-Schreibung ergänzen (optional, keine Compliance-Pflicht).',
    },
    'ARTIKEL.MENGE_AKT': {
        'xt_wert': 'FEHLT',
        'cao_wert': 'UPDATE MENGE_AKT -= Verkaufsmenge',
        'beschreibung': (
            'XT-Kasse aktualisiert den Lagerbestand nicht. '
            'CAO reduziert ARTIKEL.MENGE_AKT bei jedem Verkauf.'
        ),
        'risiko': 'hoch',
        'empfehlung': 'Lagerbestandsführung in bon_zu_journal ergänzen.',
    },
    'SATZSPERRE': {
        'xt_wert': 'FEHLT',
        'cao_wert': 'INSERT+DELETE (Row-Lock, 30s)',
        'beschreibung': (
            'XT-Kasse nutzt keinen SATZSPERRE-Mechanismus. '
            'CAO setzt einen Row-Lock während der Buchung. '
            'Bei Single-Terminal-Betrieb unkritisch.'
        ),
        'risiko': 'niedrig',
        'empfehlung': 'Erst bei Multi-Terminal-Betrieb implementieren.',
    },
    'TSE_LOG.TABELLE': {
        'xt_wert': 'XT_KASSE_TSE_LOG (eigene Tabelle)',
        'cao_wert': 'TSE_LOG (CAO-Tabelle)',
        'beschreibung': (
            'XT-Kasse nutzt eine eigene TSE-Log-Tabelle (XT_KASSE_TSE_LOG), '
            'CAO schreibt in die gemeinsame TSE_LOG-Tabelle. '
            'Beide mit QUELLE=32 für XT-Buchungen.'
        ),
        'risiko': 'mittel',
        'empfehlung': 'Prüfen ob externe Tools TSE_LOG auslesen.',
    },
}
