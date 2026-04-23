-- ============================================================
-- Bäckerei Kiosk – Datenbankschema (XT_KIOSK_*)
-- Die Tabellen liegen in der CAO-Hauptdatenbank (db_name aus caoxt.ini).
-- Kein separates CREATE DATABASE / USE – die Verbindung erfolgt direkt
-- auf die konfigurierte Datenbank.
-- Erstellt:   22.03.2026
-- Geändert:   22.03.2026 – produkte.kategorie_id nullable
--             22.03.2026 – REC_ID statt ARTNUM als Join-Schlüssel
--             22.03.2026 – v_kiosk_produkte: LEFT JOIN, aktiv > 0 reicht
--                          (Artikel ohne Kategorie erscheinen als '– Sonstige –')
--             12.04.2026 – Migration: Backwaren.* → XT_KIOSK_* in Haupt-DB
-- ============================================================

-- T0: XT_KIOSK_DRUCKER
CREATE TABLE IF NOT EXISTS XT_KIOSK_DRUCKER (
    id           INT          NOT NULL AUTO_INCREMENT,
    name         VARCHAR(100) NOT NULL,
    ip_adresse   VARCHAR(45)  NOT NULL,
    port         INT          NOT NULL DEFAULT 9100,
    standard     TINYINT      NOT NULL DEFAULT 0,
    aktiv        TINYINT      NOT NULL DEFAULT 1,
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- T0b: XT_KIOSK_TERMINAL_DRUCKER
CREATE TABLE IF NOT EXISTS XT_KIOSK_TERMINAL_DRUCKER (
    terminal_nr  TINYINT NOT NULL,
    drucker_id   INT     NOT NULL,
    PRIMARY KEY (terminal_nr),
    CONSTRAINT fk_kiosk_td_drucker FOREIGN KEY (drucker_id) REFERENCES XT_KIOSK_DRUCKER (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- T1: XT_KIOSK_KATEGORIEN
CREATE TABLE IF NOT EXISTS XT_KIOSK_KATEGORIEN (
    id         INT          NOT NULL AUTO_INCREMENT,
    name       VARCHAR(100) NOT NULL,
    sort_order INT          NOT NULL DEFAULT 0,
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT IGNORE INTO XT_KIOSK_KATEGORIEN (id, name, sort_order) VALUES
    (1, 'Brot',                   10),
    (2, 'Semmeln',                20),
    (3, 'Baguette / Sonstiges',   30),
    (4, 'Vorbestellbar',          40),
    (5, 'Süßes – Kuchen/Torten',  50),
    (6, 'Süßes – Gebäck',         60);

-- T2: XT_KIOSK_PRODUKTE
-- id = REC_ID aus ARTIKEL (int, immer vorhanden)
CREATE TABLE IF NOT EXISTS XT_KIOSK_PRODUKTE (
    id           INT          NOT NULL,
    kategorie_id INT          NULL,
    bild_pfad    VARCHAR(500),
    einheit      ENUM('Stck.', 'kg', '100g', 'Paar') NOT NULL DEFAULT 'Stck.',
    wochentage   VARCHAR(20)  NOT NULL DEFAULT '',
    zutaten      TEXT,
    aktiv        TINYINT      NOT NULL DEFAULT 1,
    hinweis      VARCHAR(200),
    PRIMARY KEY (id),
    CONSTRAINT fk_kiosk_produkte_kategorie
        FOREIGN KEY (kategorie_id) REFERENCES XT_KIOSK_KATEGORIEN (id)
        ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- T3: XT_KIOSK_WARENKOERBE
CREATE TABLE IF NOT EXISTS XT_KIOSK_WARENKOERBE (
    id                INT      NOT NULL AUTO_INCREMENT,
    erstellt_am       DATETIME NOT NULL DEFAULT NOW(),
    geaendert_am      DATETIME,
    status            ENUM('offen','geparkt','abgebrochen') NOT NULL DEFAULT 'offen',
    gesamtbetrag_cent INT      NOT NULL DEFAULT 0,
    gesperrt_von      TINYINT           DEFAULT NULL,
    gesperrt_am       DATETIME          DEFAULT NULL,
    erstellt_von      TINYINT           DEFAULT NULL,
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- T4: XT_KIOSK_WARENKORB_POS
CREATE TABLE IF NOT EXISTS XT_KIOSK_WARENKORB_POS (
    id                   INT          NOT NULL AUTO_INCREMENT,
    warenkorb_id         INT          NOT NULL,
    produkt_id           INT          NOT NULL,
    name_snapshot        VARCHAR(200) NOT NULL,
    preis_snapshot_cent  INT          NOT NULL,
    menge                INT          NOT NULL DEFAULT 1,
    zeilen_betrag_cent   INT          NOT NULL DEFAULT 0,
    PRIMARY KEY (id),
    CONSTRAINT fk_kiosk_wp_warenkorb FOREIGN KEY (warenkorb_id) REFERENCES XT_KIOSK_WARENKOERBE (id),
    CONSTRAINT fk_kiosk_wp_produkt   FOREIGN KEY (produkt_id)   REFERENCES XT_KIOSK_PRODUKTE (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- T5: XT_KIOSK_JOURNAL
CREATE TABLE IF NOT EXISTS XT_KIOSK_JOURNAL (
    id                INT         NOT NULL AUTO_INCREMENT,
    warenkorb_id      INT         NOT NULL,
    terminal_nr       TINYINT     NOT NULL,
    erstellt_am       DATETIME    NOT NULL,
    gebucht_am        DATETIME    NOT NULL DEFAULT NOW(),
    gesamtbetrag_cent INT         NOT NULL,
    ean_barcode       VARCHAR(13) NOT NULL,
    bon_text          TEXT        DEFAULT NULL,
    bon_data          LONGBLOB    DEFAULT NULL,
    status            ENUM('gebucht','storniert') NOT NULL DEFAULT 'gebucht',
    storniert_am      DATETIME             DEFAULT NULL,
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- T6: XT_KIOSK_JOURNAL_POS
CREATE TABLE IF NOT EXISTS XT_KIOSK_JOURNAL_POS (
    id                   INT          NOT NULL AUTO_INCREMENT,
    journal_id           INT          NOT NULL,
    produkt_id           INT          NOT NULL,
    name_snapshot        VARCHAR(200) NOT NULL,
    preis_snapshot_cent  INT          NOT NULL,
    menge                INT          NOT NULL,
    zeilen_betrag_cent   INT          NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT fk_kiosk_jp_journal FOREIGN KEY (journal_id) REFERENCES XT_KIOSK_JOURNAL (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- T7: XT_KIOSK_BESTELLUNGEN
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

-- T8: XT_KIOSK_BESTELL_POS
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

-- T9: XT_KIOSK_KONTAKTE
CREATE TABLE IF NOT EXISTS XT_KIOSK_KONTAKTE (
    id          INT          NOT NULL AUTO_INCREMENT,
    name        VARCHAR(100) NOT NULL,
    telefon     VARCHAR(30)  NOT NULL DEFAULT '',
    adr_id      INT          DEFAULT NULL,
    erstellt_am DATETIME     NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id),
    UNIQUE KEY uq_kiosk_kontakt (name, telefon),
    INDEX idx_kiosk_kontakt_adr (adr_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- FK bestellungen → kontakte
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

-- ============================================================
-- Views (alle in derselben DB – kein Cross-DB-Prefix nötig)
-- ============================================================

-- Admin-Admin
CREATE OR REPLACE VIEW XT_KIOSK_V_ARTIKEL_VERWALTUNG AS
    SELECT
        a.REC_ID                                    AS id,
        a.ARTNUM                                    AS artnum,
        a.KURZNAME                                  AS name,
        ROUND(a.VK5B * 100)                         AS preis_cent,
        COALESCE(p.kategorie_id, 0)                 AS kategorie_id,
        COALESCE(k.name, '– nicht zugeordnet –')    AS kategorie_name,
        COALESCE(p.einheit,    'Stck.')              AS einheit,
        COALESCE(p.wochentage, '')                  AS wochentage,
        p.zutaten,
        COALESCE(p.aktiv, 1)                        AS aktiv,
        p.hinweis,
        p.bild_pfad,
        CASE WHEN p.id IS NULL THEN 'fehlt' ELSE 'vorhanden' END AS kiosk_eintrag
    FROM ARTIKEL a
    LEFT JOIN XT_KIOSK_PRODUKTE p   ON p.id = a.REC_ID
    LEFT JOIN XT_KIOSK_KATEGORIEN k ON k.id = p.kategorie_id
    WHERE a.WARENGRUPPE = '101'
    ORDER BY COALESCE(k.sort_order, 999), a.KURZNAME;

-- Kiosk-Hauptansicht
CREATE OR REPLACE VIEW XT_KIOSK_V_PRODUKTE AS
    SELECT
        a.REC_ID                                    AS id,
        a.ARTNUM                                    AS artnum,
        a.KURZNAME                                  AS name,
        ROUND(a.VK5B * 100)                         AS preis_cent,
        p.kategorie_id,
        COALESCE(k.name, '– Sonstige –')            AS kategorie_name,
        COALESCE(k.sort_order, 999)                 AS kategorie_sort,
        p.einheit,
        COALESCE(p.wochentage, '')                  AS wochentage,
        p.zutaten,
        p.aktiv,
        p.hinweis,
        p.bild_pfad
    FROM ARTIKEL a
    JOIN XT_KIOSK_PRODUKTE p     ON p.id = a.REC_ID
    LEFT JOIN XT_KIOSK_KATEGORIEN k ON k.id = p.kategorie_id
    WHERE a.WARENGRUPPE = '101'
      AND p.aktiv > 0
    ORDER BY COALESCE(k.sort_order, 999), a.KURZNAME;

-- Verwaiste Produkte-Einträge
CREATE OR REPLACE VIEW XT_KIOSK_V_VERWAISTE AS
    SELECT p.id, p.kategorie_id, p.aktiv, p.hinweis
    FROM XT_KIOSK_PRODUKTE p
    LEFT JOIN ARTIKEL a ON a.REC_ID = p.id
    WHERE a.REC_ID IS NULL;

-- Parkierte Warenkörbe
CREATE OR REPLACE VIEW XT_KIOSK_V_OFFENE_WK AS
    SELECT w.id, w.erstellt_am, w.geaendert_am, w.gesamtbetrag_cent,
           w.erstellt_von,
           COUNT(p.id) AS anzahl_positionen
    FROM XT_KIOSK_WARENKOERBE w
    LEFT JOIN XT_KIOSK_WARENKORB_POS p ON p.warenkorb_id = w.id
    WHERE w.status = 'geparkt'
    GROUP BY w.id, w.erstellt_am, w.geaendert_am, w.gesamtbetrag_cent, w.erstellt_von
    ORDER BY w.geaendert_am DESC;

-- Journal-Übersicht
CREATE OR REPLACE VIEW XT_KIOSK_V_JOURNAL AS
    SELECT j.id, j.warenkorb_id, j.terminal_nr, j.gebucht_am,
           j.gesamtbetrag_cent, j.ean_barcode, j.status, j.storniert_am,
           COUNT(p.id) AS anzahl_positionen
    FROM XT_KIOSK_JOURNAL j
    LEFT JOIN XT_KIOSK_JOURNAL_POS p ON p.journal_id = j.id
    GROUP BY j.id, j.warenkorb_id, j.terminal_nr, j.gebucht_am,
             j.gesamtbetrag_cent, j.ean_barcode, j.status, j.storniert_am
    ORDER BY j.gebucht_am DESC;

-- ============================================================
-- Migrationen (idempotent – können mehrfach ausgeführt werden)
-- ============================================================

-- M1: adr_id zu XT_KIOSK_KONTAKTE (Verknüpfung mit CAO ADRESSEN)
SET @col_exists = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME   = 'XT_KIOSK_KONTAKTE'
      AND COLUMN_NAME  = 'adr_id'
);
SET @sql = IF(@col_exists = 0,
    'ALTER TABLE XT_KIOSK_KONTAKTE ADD COLUMN adr_id INT DEFAULT NULL AFTER telefon, ADD INDEX idx_kiosk_kontakt_adr (adr_id)',
    'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
