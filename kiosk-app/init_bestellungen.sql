-- Bestellungs-Modul – Migration für bestehende Installationen
-- Einmalig ausführen: mysql -h <HOST> -P 3333 -u cao -pfaktura Backwaren < init_bestellungen.sql

USE Backwaren;

CREATE TABLE IF NOT EXISTS bestellungen (
    id              INT          NOT NULL AUTO_INCREMENT,
    bestell_nr      VARCHAR(20)  NOT NULL DEFAULT '',
    name            VARCHAR(100) NOT NULL,
    telefon         VARCHAR(30)  DEFAULT NULL,
    typ             ENUM('einmalig','wiederkehrend') NOT NULL DEFAULT 'einmalig',
    abhol_datum     DATE         DEFAULT NULL,
    wochentag       VARCHAR(2)   DEFAULT NULL,
    start_datum     DATE         DEFAULT NULL,
    end_datum       DATE         DEFAULT NULL,
    abhol_uhrzeit   TIME         DEFAULT NULL,
    status          ENUM('offen','gedruckt','storniert') NOT NULL DEFAULT 'offen',
    gedruckt_datum  DATE         DEFAULT NULL,
    kanal           VARCHAR(30)  NOT NULL DEFAULT 'kiosk',
    notiz           TEXT         DEFAULT NULL,
    zahlungsart     ENUM('sofort','abholung') NOT NULL DEFAULT 'abholung',
    ean_barcode     VARCHAR(13)  DEFAULT NULL,
    bon_data        LONGBLOB     DEFAULT NULL,
    erstellt_am     DATETIME     NOT NULL DEFAULT NOW(),
    geaendert_am    DATETIME     DEFAULT NULL ON UPDATE NOW(),
    PRIMARY KEY (id),
    INDEX idx_abhol_datum (abhol_datum),
    INDEX idx_wochentag (wochentag),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS bestell_positionen (
    id              INT          NOT NULL AUTO_INCREMENT,
    bestell_id      INT          NOT NULL,
    produkt_id      INT          NOT NULL,
    name_snapshot   VARCHAR(200) NOT NULL,
    preis_cent      INT          NOT NULL,
    menge           INT          NOT NULL DEFAULT 1,
    PRIMARY KEY (id),
    CONSTRAINT fk_bp_bestellung FOREIGN KEY (bestell_id) REFERENCES bestellungen(id) ON DELETE CASCADE,
    INDEX idx_bp_bestell_id (bestell_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Falls Tabelle bereits ohne neue Spalten existiert (idempotent):
ALTER TABLE bestellungen
    ADD COLUMN IF NOT EXISTS zahlungsart  ENUM('sofort','abholung') NOT NULL DEFAULT 'abholung' AFTER notiz,
    ADD COLUMN IF NOT EXISTS ean_barcode  VARCHAR(13)  DEFAULT NULL AFTER zahlungsart,
    ADD COLUMN IF NOT EXISTS bon_data     LONGBLOB     DEFAULT NULL AFTER ean_barcode;
