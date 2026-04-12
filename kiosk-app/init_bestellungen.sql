-- Bestellungs-Modul – Migration für bestehende Installationen
-- Einmalig ausführen gegen die konfigurierte CAO-Hauptdatenbank.
-- Tabellen liegen in derselben DB wie alle XT_KIOSK_*-Tabellen.

CREATE TABLE IF NOT EXISTS XT_KIOSK_BESTELLUNGEN (
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
    kontakt_id      INT          DEFAULT NULL,
    pausiert        TINYINT(1)   NOT NULL DEFAULT 0,
    pause_bis       DATE         DEFAULT NULL,
    PRIMARY KEY (id),
    INDEX idx_abhol_datum (abhol_datum),
    INDEX idx_wochentag (wochentag),
    INDEX idx_status (status),
    INDEX idx_pausiert (pausiert)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS XT_KIOSK_BESTELL_POS (
    id              INT          NOT NULL AUTO_INCREMENT,
    bestell_id      INT          NOT NULL,
    produkt_id      INT          NOT NULL,
    name_snapshot   VARCHAR(200) NOT NULL,
    preis_cent      INT          NOT NULL,
    menge           INT          NOT NULL DEFAULT 1,
    PRIMARY KEY (id),
    CONSTRAINT fk_kiosk_bp_bestellung FOREIGN KEY (bestell_id) REFERENCES XT_KIOSK_BESTELLUNGEN(id) ON DELETE CASCADE,
    INDEX idx_kiosk_bp_bestell_id (bestell_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Kontakte-Tabelle (überlebt Aufräumen der Bestellungen)
CREATE TABLE IF NOT EXISTS XT_KIOSK_KONTAKTE (
    id          INT          NOT NULL AUTO_INCREMENT,
    name        VARCHAR(100) NOT NULL,
    telefon     VARCHAR(30)  NOT NULL DEFAULT '',
    erstellt_am DATETIME     NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id),
    UNIQUE KEY uq_kiosk_kontakt (name, telefon)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- FK nur anlegen wenn noch nicht vorhanden
SET @fk_exists = (
    SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME   = 'XT_KIOSK_BESTELLUNGEN'
      AND CONSTRAINT_NAME = 'fk_kiosk_bestellung_kontakt'
);
SET @sql = IF(@fk_exists = 0,
    'ALTER TABLE XT_KIOSK_BESTELLUNGEN ADD CONSTRAINT fk_kiosk_bestellung_kontakt
     FOREIGN KEY (kontakt_id) REFERENCES XT_KIOSK_KONTAKTE(id) ON DELETE SET NULL ON UPDATE CASCADE',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Bestehende Kontaktdaten migrieren (idempotent)
INSERT IGNORE INTO XT_KIOSK_KONTAKTE (name, telefon)
    SELECT DISTINCT name, COALESCE(telefon, '') FROM XT_KIOSK_BESTELLUNGEN
    WHERE kontakt_id IS NULL AND name != '';
UPDATE XT_KIOSK_BESTELLUNGEN b
    JOIN XT_KIOSK_KONTAKTE k ON k.name = b.name AND k.telefon = COALESCE(b.telefon, '')
    SET b.kontakt_id = k.id
    WHERE b.kontakt_id IS NULL;
