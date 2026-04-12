-- ============================================================
-- Migration: Backwaren-DB → XT_KIOSK_* in CAO-Hauptdatenbank
-- ============================================================
--
-- Voraussetzungen:
--   1. schema.sql wurde in der Ziel-DB ausgeführt (leere XT_KIOSK_*-Tabellen existieren)
--   2. Die Ziel-DB ist per USE oder Verbindung aktiv
--   3. Die alte Backwaren-DB ist auf demselben Server erreichbar
--
-- Ausführung:
--   mysql -h <HOST> -P <PORT> -u <USER> -p <ZIEL_DB> < migrate_backwaren.sql
--
-- Nach erfolgreicher Migration und 2 Wochen Produktivbetrieb:
--   DROP DATABASE Backwaren;
-- ============================================================

-- FK-Checks deaktivieren für Cross-DB-INSERT
SET FOREIGN_KEY_CHECKS = 0;

-- ── Stammdaten (FK-freie Tabellen zuerst) ─────────────────────

-- T9: Kontakte
INSERT INTO XT_KIOSK_KONTAKTE (id, name, telefon, erstellt_am)
    SELECT id, name, telefon, erstellt_am
    FROM Backwaren.kontakte
    ON DUPLICATE KEY UPDATE name = VALUES(name);

-- T0: Drucker
INSERT INTO XT_KIOSK_DRUCKER (id, name, ip_adresse, port, standard, aktiv)
    SELECT id, name, ip_adresse, port, standard, aktiv
    FROM Backwaren.drucker
    ON DUPLICATE KEY UPDATE name = VALUES(name);

-- T1: Kategorien
INSERT INTO XT_KIOSK_KATEGORIEN (id, name, sort_order)
    SELECT id, name, sort_order
    FROM Backwaren.kategorien
    ON DUPLICATE KEY UPDATE name = VALUES(name);

-- ── Zuordnungen und abhängige Stammdaten ──────────────────────

-- T0b: Terminal-Drucker
INSERT INTO XT_KIOSK_TERMINAL_DRUCKER (terminal_nr, drucker_id)
    SELECT terminal_nr, drucker_id
    FROM Backwaren.terminal_drucker
    ON DUPLICATE KEY UPDATE drucker_id = VALUES(drucker_id);

-- T2: Produkte
INSERT INTO XT_KIOSK_PRODUKTE (id, kategorie_id, bild_pfad, einheit, wochentage, zutaten, aktiv, hinweis)
    SELECT id, kategorie_id, bild_pfad, einheit, wochentage, zutaten, aktiv, hinweis
    FROM Backwaren.produkte
    ON DUPLICATE KEY UPDATE kategorie_id = VALUES(kategorie_id);

-- ── Transaktionsdaten ─────────────────────────────────────────

-- T3: Warenkörbe
INSERT INTO XT_KIOSK_WARENKOERBE (id, erstellt_am, geaendert_am, status, gesamtbetrag_cent,
                                   gesperrt_von, gesperrt_am, erstellt_von)
    SELECT id, erstellt_am, geaendert_am, status, gesamtbetrag_cent,
           gesperrt_von, gesperrt_am, erstellt_von
    FROM Backwaren.warenkoerbe
    ON DUPLICATE KEY UPDATE status = VALUES(status);

-- T4: Warenkorb-Positionen
INSERT INTO XT_KIOSK_WARENKORB_POS (id, warenkorb_id, produkt_id, name_snapshot,
                                     preis_snapshot_cent, menge, zeilen_betrag_cent)
    SELECT id, warenkorb_id, produkt_id, name_snapshot,
           preis_snapshot_cent, menge, zeilen_betrag_cent
    FROM Backwaren.warenkorb_positionen
    ON DUPLICATE KEY UPDATE menge = VALUES(menge);

-- T5: Journal
INSERT INTO XT_KIOSK_JOURNAL (id, warenkorb_id, terminal_nr, erstellt_am, gebucht_am,
                               gesamtbetrag_cent, ean_barcode, bon_text, bon_data,
                               status, storniert_am)
    SELECT id, warenkorb_id, terminal_nr, erstellt_am, gebucht_am,
           gesamtbetrag_cent, ean_barcode, bon_text, bon_data,
           status, storniert_am
    FROM Backwaren.journal_warenkoerbe
    ON DUPLICATE KEY UPDATE status = VALUES(status);

-- T6: Journal-Positionen
INSERT INTO XT_KIOSK_JOURNAL_POS (id, journal_id, produkt_id, name_snapshot,
                                   preis_snapshot_cent, menge, zeilen_betrag_cent)
    SELECT id, journal_id, produkt_id, name_snapshot,
           preis_snapshot_cent, menge, zeilen_betrag_cent
    FROM Backwaren.journal_positionen
    ON DUPLICATE KEY UPDATE menge = VALUES(menge);

-- ── Bestellungen ──────────────────────────────────────────────

-- T7: Bestellungen
INSERT INTO XT_KIOSK_BESTELLUNGEN (id, bestell_nr, name, telefon, typ, abhol_datum,
                                    wochentag, start_datum, end_datum, abhol_uhrzeit,
                                    status, gedruckt_datum, kanal, notiz, zahlungsart,
                                    ean_barcode, bon_data, erstellt_am, geaendert_am,
                                    kontakt_id, pausiert, pause_bis)
    SELECT id, bestell_nr, name, telefon, typ, abhol_datum,
           wochentag, start_datum, end_datum, abhol_uhrzeit,
           status, gedruckt_datum, kanal, notiz, zahlungsart,
           ean_barcode, bon_data, erstellt_am, geaendert_am,
           kontakt_id, COALESCE(pausiert, 0), pause_bis
    FROM Backwaren.bestellungen
    ON DUPLICATE KEY UPDATE status = VALUES(status);

-- T8: Bestell-Positionen
INSERT INTO XT_KIOSK_BESTELL_POS (id, bestell_id, produkt_id, name_snapshot, preis_cent, menge)
    SELECT id, bestell_id, produkt_id, name_snapshot, preis_cent, menge
    FROM Backwaren.bestell_positionen
    ON DUPLICATE KEY UPDATE menge = VALUES(menge);

-- FK-Checks wieder aktivieren
SET FOREIGN_KEY_CHECKS = 1;

-- ── AUTO_INCREMENT-Werte übernehmen ───────────────────────────

ALTER TABLE XT_KIOSK_KONTAKTE
    AUTO_INCREMENT = (SELECT COALESCE(MAX(id), 0) + 1 FROM XT_KIOSK_KONTAKTE);
ALTER TABLE XT_KIOSK_DRUCKER
    AUTO_INCREMENT = (SELECT COALESCE(MAX(id), 0) + 1 FROM XT_KIOSK_DRUCKER);
ALTER TABLE XT_KIOSK_KATEGORIEN
    AUTO_INCREMENT = (SELECT COALESCE(MAX(id), 0) + 1 FROM XT_KIOSK_KATEGORIEN);
ALTER TABLE XT_KIOSK_WARENKOERBE
    AUTO_INCREMENT = (SELECT COALESCE(MAX(id), 0) + 1 FROM XT_KIOSK_WARENKOERBE);
ALTER TABLE XT_KIOSK_WARENKORB_POS
    AUTO_INCREMENT = (SELECT COALESCE(MAX(id), 0) + 1 FROM XT_KIOSK_WARENKORB_POS);
ALTER TABLE XT_KIOSK_JOURNAL
    AUTO_INCREMENT = (SELECT COALESCE(MAX(id), 0) + 1 FROM XT_KIOSK_JOURNAL);
ALTER TABLE XT_KIOSK_JOURNAL_POS
    AUTO_INCREMENT = (SELECT COALESCE(MAX(id), 0) + 1 FROM XT_KIOSK_JOURNAL_POS);
ALTER TABLE XT_KIOSK_BESTELLUNGEN
    AUTO_INCREMENT = (SELECT COALESCE(MAX(id), 0) + 1 FROM XT_KIOSK_BESTELLUNGEN);
ALTER TABLE XT_KIOSK_BESTELL_POS
    AUTO_INCREMENT = (SELECT COALESCE(MAX(id), 0) + 1 FROM XT_KIOSK_BESTELL_POS);

-- ============================================================
-- Rauchtest: Zähle migrierte Datensätze
-- ============================================================
SELECT 'XT_KIOSK_KONTAKTE' AS tabelle, COUNT(*) AS anzahl FROM XT_KIOSK_KONTAKTE
UNION ALL SELECT 'XT_KIOSK_DRUCKER', COUNT(*) FROM XT_KIOSK_DRUCKER
UNION ALL SELECT 'XT_KIOSK_KATEGORIEN', COUNT(*) FROM XT_KIOSK_KATEGORIEN
UNION ALL SELECT 'XT_KIOSK_TERMINAL_DRUCKER', COUNT(*) FROM XT_KIOSK_TERMINAL_DRUCKER
UNION ALL SELECT 'XT_KIOSK_PRODUKTE', COUNT(*) FROM XT_KIOSK_PRODUKTE
UNION ALL SELECT 'XT_KIOSK_WARENKOERBE', COUNT(*) FROM XT_KIOSK_WARENKOERBE
UNION ALL SELECT 'XT_KIOSK_WARENKORB_POS', COUNT(*) FROM XT_KIOSK_WARENKORB_POS
UNION ALL SELECT 'XT_KIOSK_JOURNAL', COUNT(*) FROM XT_KIOSK_JOURNAL
UNION ALL SELECT 'XT_KIOSK_JOURNAL_POS', COUNT(*) FROM XT_KIOSK_JOURNAL_POS
UNION ALL SELECT 'XT_KIOSK_BESTELLUNGEN', COUNT(*) FROM XT_KIOSK_BESTELLUNGEN
UNION ALL SELECT 'XT_KIOSK_BESTELL_POS', COUNT(*) FROM XT_KIOSK_BESTELL_POS;
