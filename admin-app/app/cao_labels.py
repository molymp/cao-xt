"""
Generierter Labels-Katalog fuer CAO-Einstellungen.

Quelle: cao_admin.exe (CAO-Faktura 1.5) – aus den eingebetteten
Delphi-Forms (DFM-Ressourcen) extrahiert. Verknuepft
``(MAINKEY, NAME)`` der ``REGISTRY``-Tabelle mit dem deutschen
Anzeige-Titel (Caption der UI-Komponente) und ggf. der Liste
moeglicher Werte (TComboBox.Items / TRadioGroup.Items).

Eintraege: 68 Titel, 4 Enum-Listen.

Diese Datei wird aus /tmp/cao_admin_analysis/emit_catalog.py
regeneriert – nicht von Hand editieren.
"""
from __future__ import annotations

# (MAINKEY, NAME) → {titel, hint, tab}
LABELS_CAO: dict[tuple[str, str], dict[str, str | None]] = {
    ('MAIN', 'LEITWAEHRUNG'): {"titel": 'Land', "hint": None, "tab": 'Allgemein'},
    ('MAIN', 'USE_BROWSER'): {"titel": 'Browser', "hint": None, "tab": 'Allgemein'},
    ('MAIN', 'USE_KFZ'): {"titel": 'KFZ-Verwaltung', "hint": None, "tab": 'Allgemein'},
    ('MAIN\\ADRESSEN', 'KUNNUM1_EDI'): {"titel": 'Kundennummer editierbar', "hint": None, "tab": 'Adressen'},
    ('MAIN\\ARTIKEL', 'ANZPREIS'): {"titel": 'Nachkommastellen', "hint": None, "tab": 'Artikel'},
    ('MAIN\\ARTIKEL', 'ARTNUM_AUTO'): {"titel": 'Artikelnummer autom. vergeben (nur bei normalen, Stücklisten- und Produktionsart.)', "hint": None, "tab": 'Artikel'},
    ('MAIN\\ARTIKEL', 'MWST_WGR'): {"titel": 'Bei Artikelneuanlage den MwSt-Satz der Warengruppe übernehmen', "hint": None, "tab": 'Artikel'},
    ('MAIN\\ARTIKEL', 'USE_F_ARTIKEL'): {"titel": 'Freie Artikel in  den Vorgängen zulassen', "hint": None, "tab": 'Artikel'},
    ('MAIN\\BACKUP', 'BACKUP_CRYPT'): {"titel": 'Backup mit Passwort', "hint": None, "tab": 'Backup'},
    ('MAIN\\BACKUP', 'BACKUP_PWD'): {"titel": 'Passwort wiederholen', "hint": None, "tab": 'Backup'},
    ('MAIN\\BELEGE', 'ADRESSE_IN_FIRMA'): {"titel": 'Adresse', "hint": None, "tab": 'Belegtexte'},
    ('MAIN\\BELEGE', 'ANGEBOTTEXT_IN_FREITEXT'): {"titel": 'Beim Vorgang Angebot', "hint": None, "tab": 'Belegtexte'},
    ('MAIN\\BELEGE', 'ARTIKELPAKETTEXT_IN_FREITEXT'): {"titel": 'Beim Artikelpaket', "hint": None, "tab": 'Belegtexte'},
    ('MAIN\\BELEGE', 'ASP_ADRESSE'): {"titel": 'Adresse des Ansprechpartners übernehmen', "hint": None, "tab": 'Belege -2-'},
    ('MAIN\\BELEGE', 'AUFTRAGTEXT_IN_FREITEXT'): {"titel": 'Beim Vorgang Auftrag', "hint": None, "tab": 'Belegtexte'},
    ('MAIN\\BELEGE', 'AUFTRAG_DATUM_ERSETZEN'): {"titel": 'Auftragsdatum beim Speichern ersetzen', "hint": None, "tab": 'Belege -3-'},
    ('MAIN\\BELEGE', 'BDATENTEILBERECHNUNG'): {"titel": 'Nur aus Vorgang (Positionen) berechnen', "hint": None, "tab": 'Belege -2-'},
    ('MAIN\\BELEGE', 'EKSERIENNUMMER_ERFASSEN'): {"titel": 'Seriennummern beim Einkauf erfassen', "hint": None, "tab": 'Belege -3-'},
    ('MAIN\\BELEGE', 'ER_DATUM_SETZEN'): {"titel": 'Einkauf ER-Datum (Belegdatum) vorausfüllen', "hint": None, "tab": 'Belege -3-'},
    ('MAIN\\BELEGE', 'FIRMAFUSSTEXT_IN_KORREKTURBELEGTEXT'): {"titel": 'Fußtext übernehmen', "hint": None, "tab": 'Belegtexte'},
    ('MAIN\\BELEGE', 'FIRMAFUSSTEXT_IN_RECHNUNGBELEGTEXT'): {"titel": 'Fußtext übernehmen', "hint": None, "tab": 'Belegtexte'},
    ('MAIN\\BELEGE', 'FIRMAKOPFTEXT_IN_KORREKTURBELEGTEXT'): {"titel": 'Kopftext übernehmen', "hint": None, "tab": 'Belegtexte'},
    ('MAIN\\BELEGE', 'FIRMAKOPFTEXT_IN_RECHNUNGBELEGTEXT'): {"titel": 'Kopftext übernehmen', "hint": None, "tab": 'Belegtexte'},
    ('MAIN\\BELEGE', 'FIRMA_IN_BELEGTEXT'): {"titel": 'Firmendaten übernehmen', "hint": None, "tab": 'Belegtexte'},
    ('MAIN\\BELEGE', 'GERICHT_IN_FIRMA'): {"titel": 'Gericht', "hint": None, "tab": 'Belegtexte'},
    ('MAIN\\BELEGE', 'HRA_IN_FIRMA'): {"titel": 'HRA', "hint": None, "tab": 'Belegtexte'},
    ('MAIN\\BELEGE', 'HRB_IN_FIRMA'): {"titel": 'HRB', "hint": None, "tab": 'Belegtexte'},
    ('MAIN\\BELEGE', 'KFZTEXT_IN_RECHNUNGBELEGTEXT'): {"titel": 'Kfz-Daten übernehmen', "hint": None, "tab": 'Belegtexte'},
    ('MAIN\\BELEGE', 'KORREKTURFUSSTEXT_IN_BELEGTEXT'): {"titel": 'Fußtext übernehmen', "hint": None, "tab": 'Belegtexte'},
    ('MAIN\\BELEGE', 'KORREKTURKOPFTEXT_IN_BELEGTEXT'): {"titel": 'Kopftext übernehmen', "hint": None, "tab": 'Belegtexte'},
    ('MAIN\\BELEGE', 'KORREKTURPROJEKTTEXT_IN_BELEGTEXT'): {"titel": 'Projekttext übernehmen', "hint": None, "tab": 'Belegtexte'},
    ('MAIN\\BELEGE', 'KORREKTURTEXT_IN_FREITEXT'): {"titel": 'Beim Vorgang Korrekturrechnung', "hint": None, "tab": 'Belegtexte'},
    ('MAIN\\BELEGE', 'KORREKTURUEBERSCHRIFT_IN_BELEGTEXT'): {"titel": 'Überschriften übernehmen', "hint": None, "tab": 'Belegtexte'},
    ('MAIN\\BELEGE', 'KUNDENPREIS_ABFRAGE'): {"titel": 'Kundenpreis speichern', "hint": None, "tab": 'Belege -1-'},
    ('MAIN\\BELEGE', 'LAGERPRUEFUNG'): {"titel": 'beim Buchen von Lieferschein / Rechnung', "hint": None, "tab": 'Belege -2-'},
    ('MAIN\\BELEGE', 'LIEFERSCHEINTEXT_IN_FREITEXT'): {"titel": 'Beim Vorgang Lieferschein', "hint": None, "tab": 'Belegtexte'},
    ('MAIN\\BELEGE', 'LOHN_STAFFEL'): {"titel": 'Staffelpreise bei Lohnartikel übernehmen', "hint": None, "tab": 'Belege -3-'},
    ('MAIN\\BELEGE', 'MODUL_AOPTION'): {"titel": 'Artikeloptionen nutzen', "hint": None, "tab": 'Allgemein'},
    ('MAIN\\BELEGE', 'MODUL_AUFTRAG'): {"titel": 'Auftragsbearbeitung nutzen', "hint": None, "tab": 'Allgemein'},
    ('MAIN\\BELEGE', 'MODUL_ERECHNUNG'): {"titel": 'ERechnung nutzen', "hint": None, "tab": 'Allgemein'},
    ('MAIN\\BELEGE', 'MODUL_MULTISHOP'): {"titel": 'Multishop nutzen', "hint": None, "tab": 'Allgemein'},
    ('MAIN\\BELEGE', 'MODUL_MWST'): {"titel": 'Abweichende MwSt nutzen', "hint": None, "tab": 'Allgemein'},
    ('MAIN\\BELEGE', 'MODUL_PRODUKTION'): {"titel": 'Produktion nutzen', "hint": None, "tab": 'Allgemein'},
    ('MAIN\\BELEGE', 'MODUL_SPRACHE'): {"titel": 'Mehrsprachigkeit nutzen', "hint": None, "tab": 'Allgemein'},
    ('MAIN\\BELEGE', 'MODUL_STKLISTE'): {"titel": 'Stücklistenerweiterung nutzen', "hint": None, "tab": 'Allgemein'},
    ('MAIN\\BELEGE', 'MODUL_VARIANTEN'): {"titel": 'Artikelvarianten nutzen', "hint": None, "tab": 'Allgemein'},
    ('MAIN\\BELEGE', 'NAME1_IN_FIRMA'): {"titel": 'Name 1', "hint": None, "tab": 'Belegtexte'},
    ('MAIN\\BELEGE', 'NAME2_IN_FIRMA'): {"titel": 'Name 2', "hint": None, "tab": 'Belegtexte'},
    ('MAIN\\BELEGE', 'NAME3_IN_FIRMA'): {"titel": 'Name 3', "hint": None, "tab": 'Belegtexte'},
    ('MAIN\\BELEGE', 'RECHNUNGFUSSTEXT_IN_BELEGTEXT'): {"titel": 'Fußtext übernehmen', "hint": None, "tab": 'Belegtexte'},
    ('MAIN\\BELEGE', 'RECHNUNGKOPFTEXT_IN_BELEGTEXT'): {"titel": 'Kopftext übernehmen', "hint": None, "tab": 'Belegtexte'},
    ('MAIN\\BELEGE', 'RECHNUNGPROJEKTTEXT_IN_BELEGTEXT'): {"titel": 'Projekttext übernehmen', "hint": None, "tab": 'Belegtexte'},
    ('MAIN\\BELEGE', 'RECHNUNGTEXT_IN_FREITEXT'): {"titel": 'Beim Vorgang Rechnung', "hint": None, "tab": 'Belegtexte'},
    ('MAIN\\BELEGE', 'RECHNUNGUEBERSCHRIFT_IN_BELEGTEXT'): {"titel": 'Überschriften übernehmen', "hint": None, "tab": 'Belegtexte'},
    ('MAIN\\BELEGE', 'RESET_ARTIKELMENGE'): {"titel": 'Artikelmenge beim Buchen auf 1 zurücksetzen', "hint": None, "tab": 'Belege -2-'},
    ('MAIN\\BELEGE', 'SCHNELLERFASSUNG_EXAKTE_SUCHE'): {"titel": 'Exakte Suche in den Feldern: Artikelnummer/EAN/Suchbegriff', "hint": None, "tab": 'Belege -3-'},
    ('MAIN\\BELEGE', 'SHOW_Z_WARNING'): {"titel": 'Warnhinweis anzeigen wenn schon Vorgang vorhanden', "hint": None, "tab": 'Belege -3-'},
    ('MAIN\\BELEGE', 'STKARTIKEL_LANGTEXT'): {"titel": 'Artikellangtext beim Hinzufügen von Stücklistenartikel  in den Positionen nutzen', "hint": None, "tab": 'Belege -3-'},
    ('MAIN\\BELEGE', 'UEBERNAHME_TEXT'): {"titel": 'Texte aus Rechnung in Lieferschein übernehmen', "hint": None, "tab": 'Belege -1-'},
    ('MAIN\\BELEGE', 'USE_LIEF_USTID'): {"titel": 'UmsatzsteuerId der Lieferadresse nutzen, wenn vorhanden und abweichend zur Rech.-Adresses', "hint": None, "tab": 'Belege -3-'},
    ('MAIN\\BELEGE', 'VERTRAGTEXT_IN_FREITEXT'): {"titel": 'Beim Vorgang Vertrag', "hint": None, "tab": 'Belegtexte'},
    ('MAIN\\BELEGE', 'VERTRAG_EDI_DEAKTIVIEREN'): {"titel": 'Vertrag bei Änderungen deaktivieren', "hint": None, "tab": 'Belege -3-'},
    ('MAIN\\EMAIL', 'MAPI_SIGNATUR'): {"titel": 'Signatur anhängen', "hint": None, "tab": 'pMAPI'},
    ('MAIN\\FIBU', 'CASHBOOK'): {"titel": 'Kassenbuch exportieren', "hint": None, "tab": 'Allgemeine Einstellung'},
    ('MAIN\\FIBU', 'DATEV_BERATER'): {"titel": 'Mandantennummer:', "hint": None, "tab": 'Datev-Einstellungen'},
    ('MAIN\\FIBU', 'USE_NOCASH'): {"titel": 'Zahlarten deaktivieren', "hint": '|Zahlungsart BAR, EC, Scheck und Kreditkarte  deaktivieren, wenn Kassenrichtlinie für AT zutrifft.\r\nBAR-Rechnungen dann über CAO-Kasse Pro', "tab": None},
    ('MODUL', 'BERECHNEBDATEN'): {"titel": 'Berechne Bewegungsdaten', "hint": None, "tab": 'Belege -2-'},
    ('SHOP', 'VAR_SEPERATOR'): {"titel": 'Trennzeichen für Variantenübermittlung in den Shop', "hint": None, "tab": 'Artikel'},
}

# (MAINKEY, NAME) → Liste moeglicher Werte (z.B. ComboBox-Items)
ENUM_WERTE: dict[tuple[str, str], list[str]] = {
    ('MAIN\\ARTIKEL', 'ANZPREIS'): ['2', '3', '4', '5'],
    ('MAIN\\BELEGE', 'LAGERPRUEFUNG'): ['ohne Prüfung', 'Prüfung mit Hinweis', 'strenge Prüfung'],
    ('MAIN\\FIBU', 'TRENNZEICHEN'): [';', ',', 'TAB'],
    ('SHOP', 'VAR_SEPERATOR'): [',', ';', '@'],
}

# MAINKEY → haeufigster Tab-Name aus cao_admin.exe 
# (nur fuer MAINKEYs, die ueberhaupt einen Titel-Treffer haben).
TAB_FUER_MAINKEY: dict[str, str] = {
    'MAIN': 'Allgemein',
    'MAIN\\ADRESSEN': 'Adressen',
    'MAIN\\ARTIKEL': 'Artikel',
    'MAIN\\BACKUP': 'Backup',
    'MAIN\\BELEGE': 'Belegtexte',
    'MAIN\\EMAIL': 'Email-Einstellungen',
    'MAIN\\FIBU': 'Kontenzuweisung',
    'MODUL': 'Belege -2-',
    'SHOP': 'Artikel',
}
