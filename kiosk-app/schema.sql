-- ============================================================
-- Bäckerei Kiosk – Datenbankschema
-- Datenbank: MariaDB (gleicher Server wie CAO-Kassendatenbank)
-- Unsere DB:  Backwaren  /  CAO-DB: cao_2018_001
-- Erstellt:   22.03.2026
-- Geändert:   22.03.2026 – produkte.kategorie_id nullable
--             22.03.2026 – REC_ID statt ARTNUM als Join-Schlüssel
--             22.03.2026 – v_kiosk_produkte: LEFT JOIN, aktiv > 0 reicht
--                          (Artikel ohne Kategorie erscheinen als '– Sonstige –')
-- ============================================================

CREATE DATABASE IF NOT EXISTS Backwaren
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE Backwaren;

-- T0: drucker
CREATE TABLE drucker (
    id           INT          NOT NULL AUTO_INCREMENT,
    name         VARCHAR(100) NOT NULL,
    ip_adresse   VARCHAR(45)  NOT NULL,
    port         INT          NOT NULL DEFAULT 9100,
    standard     TINYINT      NOT NULL DEFAULT 0,
    aktiv        TINYINT      NOT NULL DEFAULT 1,
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- T0b: terminal_drucker
CREATE TABLE terminal_drucker (
    terminal_nr  TINYINT NOT NULL,
    drucker_id   INT     NOT NULL,
    PRIMARY KEY (terminal_nr),
    CONSTRAINT fk_td_drucker FOREIGN KEY (drucker_id) REFERENCES drucker (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- T1: kategorien
CREATE TABLE kategorien (
    id         INT          NOT NULL AUTO_INCREMENT,
    name       VARCHAR(100) NOT NULL,
    sort_order INT          NOT NULL DEFAULT 0,
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO kategorien (id, name, sort_order) VALUES
    (1, 'Brot',                   10),
    (2, 'Semmeln',                20),
    (3, 'Baguette / Sonstiges',   30),
    (4, 'Vorbestellbar',          40),
    (5, 'Süßes – Kuchen/Torten',  50),
    (6, 'Süßes – Gebäck',         60);

-- T2: produkte
-- id = REC_ID aus cao_2018_001.ARTIKEL (int, immer vorhanden)
CREATE TABLE produkte (
    id           INT          NOT NULL,
    kategorie_id INT          NULL,
    bild_pfad    VARCHAR(500),
    einheit      ENUM('Stck.', 'kg', '100g', 'Paar') NOT NULL DEFAULT 'Stck.',
    wochentage   VARCHAR(20)  NOT NULL DEFAULT '',
    zutaten      TEXT,
    aktiv        TINYINT      NOT NULL DEFAULT 1,
    hinweis      VARCHAR(200),
    PRIMARY KEY (id),
    CONSTRAINT fk_produkte_kategorie
        FOREIGN KEY (kategorie_id) REFERENCES kategorien (id)
        ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- T3: warenkoerbe
CREATE TABLE warenkoerbe (
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

-- T4: warenkorb_positionen
CREATE TABLE warenkorb_positionen (
    id                   INT          NOT NULL AUTO_INCREMENT,
    warenkorb_id         INT          NOT NULL,
    produkt_id           INT          NOT NULL,
    name_snapshot        VARCHAR(200) NOT NULL,
    preis_snapshot_cent  INT          NOT NULL,
    menge                INT          NOT NULL DEFAULT 1,
    zeilen_betrag_cent   INT          NOT NULL DEFAULT 0,
    PRIMARY KEY (id),
    CONSTRAINT fk_wp_warenkorb FOREIGN KEY (warenkorb_id) REFERENCES warenkoerbe (id),
    CONSTRAINT fk_wp_produkt   FOREIGN KEY (produkt_id)   REFERENCES produkte (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- T5: journal_warenkoerbe
CREATE TABLE journal_warenkoerbe (
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

-- T6: journal_positionen
CREATE TABLE journal_positionen (
    id                   INT          NOT NULL AUTO_INCREMENT,
    journal_id           INT          NOT NULL,
    produkt_id           INT          NOT NULL,
    name_snapshot        VARCHAR(200) NOT NULL,
    preis_snapshot_cent  INT          NOT NULL,
    menge                INT          NOT NULL,
    zeilen_betrag_cent   INT          NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT fk_jp_journal FOREIGN KEY (journal_id) REFERENCES journal_warenkoerbe (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================
-- Views
-- ============================================================

-- Admin-Verwaltung
CREATE OR REPLACE VIEW v_artikel_verwaltung AS
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
    FROM cao_2018_001.ARTIKEL a
    LEFT JOIN Backwaren.produkte p   ON p.id = a.REC_ID
    LEFT JOIN Backwaren.kategorien k ON k.id = p.kategorie_id
    WHERE a.WARENGRUPPE = '101'
    ORDER BY COALESCE(k.sort_order, 999), a.KURZNAME;

-- Kiosk-Hauptansicht: alle aktiven Artikel inkl. ohne Kategorie
-- LEFT JOIN → kategorie_id NULL erlaubt → Fallback '– Sonstige –', sort 999
CREATE OR REPLACE VIEW v_kiosk_produkte AS
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
    FROM cao_2018_001.ARTIKEL a
    JOIN Backwaren.produkte p     ON p.id = a.REC_ID
    LEFT JOIN Backwaren.kategorien k ON k.id = p.kategorie_id
    WHERE a.WARENGRUPPE = '101'
      AND p.aktiv > 0
    ORDER BY COALESCE(k.sort_order, 999), a.KURZNAME;

-- Verwaiste produkte-Einträge
CREATE OR REPLACE VIEW v_verwaiste_produkte AS
    SELECT p.id, p.kategorie_id, p.aktiv, p.hinweis
    FROM Backwaren.produkte p
    LEFT JOIN cao_2018_001.ARTIKEL a ON a.REC_ID = p.id
    WHERE a.REC_ID IS NULL;

-- Parkierte Warenkörbe
CREATE OR REPLACE VIEW v_offene_warenkoerbe AS
    SELECT w.id, w.erstellt_am, w.geaendert_am, w.gesamtbetrag_cent,
           w.erstellt_von,
           COUNT(p.id) AS anzahl_positionen
    FROM warenkoerbe w
    LEFT JOIN warenkorb_positionen p ON p.warenkorb_id = w.id
    WHERE w.status = 'geparkt'
    GROUP BY w.id, w.erstellt_am, w.geaendert_am, w.gesamtbetrag_cent, w.erstellt_von
    ORDER BY w.geaendert_am DESC;

-- Journal-Übersicht
CREATE OR REPLACE VIEW v_journal_uebersicht AS
    SELECT j.id, j.warenkorb_id, j.terminal_nr, j.gebucht_am,
           j.gesamtbetrag_cent, j.ean_barcode, j.status, j.storniert_am,
           COUNT(p.id) AS anzahl_positionen
    FROM journal_warenkoerbe j
    LEFT JOIN journal_positionen p ON p.journal_id = j.id
    GROUP BY j.id, j.warenkorb_id, j.terminal_nr, j.gebucht_am,
             j.gesamtbetrag_cent, j.ean_barcode, j.status, j.storniert_am
    ORDER BY j.gebucht_am DESC;

-- T7: bestellungen
CREATE TABLE bestellungen (
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

-- T8: bestell_positionen
CREATE TABLE bestell_positionen (
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
