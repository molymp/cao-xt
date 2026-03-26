-- ============================================================
-- CAO-XT Kassen-App – Datenbankschema
-- Alle Tabellen tragen das Präfix XT_KASSE_
-- CAO-Faktura-Tabellen (ohne Präfix) werden read-only genutzt.
-- Ausnahme: LIEFERSCHEIN / LIEFERSCHEIN_POS werden beim
-- "Bon → Lieferschein" beschrieben.
-- ============================================================

-- ── Terminal-Konfiguration ────────────────────────────────────
CREATE TABLE IF NOT EXISTS XT_KASSE_TERMINALS (
    ID                  INT AUTO_INCREMENT PRIMARY KEY,
    TERMINAL_NR         INT NOT NULL UNIQUE COMMENT 'Eindeutige Terminalnummer 1–9',
    BEZEICHNUNG         VARCHAR(100),
    -- Fiskaly TSE
    FISKALY_API_KEY     VARCHAR(200),
    FISKALY_API_SECRET  VARCHAR(200),
    FISKALY_TSS_ID      VARCHAR(36)  COMMENT 'UUID der Technical Security System',
    FISKALY_CLIENT_ID   VARCHAR(36)  COMMENT 'UUID des Kassenclients in der TSS',
    FISKALY_ENV         ENUM('test','live') NOT NULL DEFAULT 'test',
    FISKALY_ADMIN_PIN   VARCHAR(100)         COMMENT 'TSS Admin-PIN (wird beim Initialisieren gesetzt)',
    -- Drucker / Kassenlade
    DRUCKER_IP          VARCHAR(50),
    DRUCKER_PORT        INT NOT NULL DEFAULT 9100,
    KASSENLADE          TINYINT NOT NULL DEFAULT 0 COMMENT '0=keine, 1=Pin2, 2=Pin5',
    -- Firma (für Bondruck, falls abweichend vom globalen Default)
    FIRMA_NAME          VARCHAR(100),
    FIRMA_STRASSE       VARCHAR(100),
    FIRMA_ORT           VARCHAR(100),
    FIRMA_UST_ID        VARCHAR(30),
    FIRMA_STEUERNUMMER  VARCHAR(30),
    STANDORT            VARCHAR(100),
    AKTIV               TINYINT NOT NULL DEFAULT 1,
    ERSTELLT            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── Kassenvorgänge (Belege) ───────────────────────────────────
CREATE TABLE IF NOT EXISTS XT_KASSE_VORGAENGE (
    ID                      INT AUTO_INCREMENT PRIMARY KEY,
    TERMINAL_NR             INT NOT NULL,
    BON_NR                  INT NOT NULL COMMENT 'Pro Terminal fortlaufend',
    BON_DATUM               DATETIME NOT NULL,
    MITARBEITER_ID          INT      COMMENT 'FK → MITARBEITER.MA_ID',
    MITARBEITER_NAME        VARCHAR(100) COMMENT 'Snapshot',
    STATUS                  ENUM('OFFEN','ABGESCHLOSSEN','STORNIERT','GEPARKT')
                                NOT NULL DEFAULT 'OFFEN',
    STORNO_VON_ID           INT      COMMENT 'Bei Storno: ID des Original-Vorgangs',
    -- Beträge (immer in Cent)
    BETRAG_BRUTTO           INT NOT NULL DEFAULT 0,
    BETRAG_NETTO            INT NOT NULL DEFAULT 0,
    MWST_BETRAG_1           INT NOT NULL DEFAULT 0 COMMENT 'Normalsteuersatz (i.d.R. 19%)',
    MWST_BETRAG_2           INT NOT NULL DEFAULT 0 COMMENT 'Ermäßigter Satz (i.d.R. 7%)',
    MWST_BETRAG_3           INT NOT NULL DEFAULT 0 COMMENT 'Weiterer Satz / 0%',
    NETTO_BETRAG_1          INT NOT NULL DEFAULT 0,
    NETTO_BETRAG_2          INT NOT NULL DEFAULT 0,
    NETTO_BETRAG_3          INT NOT NULL DEFAULT 0,
    -- TSE-Daten
    TSE_TX_ID               VARCHAR(36)  COMMENT 'Fiskaly Transaction UUID',
    TSE_TX_REVISION         INT,
    TSE_SIGNATUR            TEXT,
    TSE_SIGNATUR_ZAEHLER    BIGINT,
    TSE_ZEITPUNKT_START     DATETIME,
    TSE_ZEITPUNKT_ENDE      DATETIME,
    TSE_SERIAL              VARCHAR(200) COMMENT 'Seriennummer der TSS (hex)',
    TSE_LOG_TIME_FORMAT     VARCHAR(50),
    TSE_PROCESS_TYPE        VARCHAR(50),
    TSE_PROCESS_DATA        TEXT,
    -- DSFinV-K
    VORGANGSNUMMER          VARCHAR(50) COMMENT 'Global eindeutige Belegnummer',
    VORGANG_TYP             VARCHAR(30) NOT NULL DEFAULT 'Beleg',
    NOTIZ                   TEXT,
    ERSTELLT                TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    GEAENDERT               TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                                ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_terminal_bon  (TERMINAL_NR, BON_NR),
    INDEX idx_datum         (BON_DATUM),
    INDEX idx_status        (STATUS),
    UNIQUE KEY uq_vorgangsnr (VORGANGSNUMMER)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── Belegpositionen ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS XT_KASSE_VORGAENGE_POS (
    ID                      INT AUTO_INCREMENT PRIMARY KEY,
    VORGANG_ID              INT NOT NULL,
    POSITION                INT NOT NULL,
    ARTIKEL_ID              INT          COMMENT 'FK → ARTIKEL.REC_ID, NULL bei Freitext',
    ARTNUM                  VARCHAR(50)  COMMENT 'Snapshot',
    BARCODE                 VARCHAR(50)  COMMENT 'Snapshot',
    BEZEICHNUNG             VARCHAR(200) NOT NULL COMMENT 'Snapshot',
    MENGE                   DECIMAL(10,3) NOT NULL DEFAULT 1.000,
    EINZELPREIS_BRUTTO      INT NOT NULL COMMENT 'Cent',
    GESAMTPREIS_BRUTTO      INT NOT NULL COMMENT 'Cent',
    RABATT_PROZENT          DECIMAL(5,2) NOT NULL DEFAULT 0.00,
    STEUER_CODE             TINYINT NOT NULL DEFAULT 1
                                COMMENT '1=Normalsteuersatz, 2=erm., 3=0%',
    MWST_SATZ               DECIMAL(5,2) NOT NULL COMMENT 'Snapshot des Steuersatzes',
    MWST_BETRAG             INT NOT NULL DEFAULT 0 COMMENT 'Cent',
    NETTO_BETRAG            INT NOT NULL DEFAULT 0 COMMENT 'Cent',
    STORNIERT               TINYINT NOT NULL DEFAULT 0,
    -- DSFinV-K Flags
    IST_GUTSCHEIN           TINYINT NOT NULL DEFAULT 0,
    INDEX idx_vorgang       (VORGANG_ID)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── Zahlungsarten je Vorgang ──────────────────────────────────
CREATE TABLE IF NOT EXISTS XT_KASSE_ZAHLUNGEN (
    ID                      INT AUTO_INCREMENT PRIMARY KEY,
    VORGANG_ID              INT NOT NULL,
    ZAHLART                 ENUM('BAR','EC','KUNDENKONTO','GUTSCHEIN','SONSTIGE')
                                NOT NULL,
    BETRAG                  INT NOT NULL COMMENT 'Cent',
    BETRAG_GEGEBEN          INT          COMMENT 'Cent, bei BAR: gegebener Betrag',
    WECHSELGELD             INT          COMMENT 'Cent, bei BAR: Rückgeld',
    REFERENZ                VARCHAR(100) COMMENT 'EC: Referenznummer',
    ADRESSEN_ID             INT          COMMENT 'FK → ADRESSEN.REC_ID bei KUNDENKONTO',
    INDEX idx_vorgang       (VORGANG_ID)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── Kassenbuch ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS XT_KASSE_KASSENBUCH (
    ID                      INT AUTO_INCREMENT PRIMARY KEY,
    TERMINAL_NR             INT NOT NULL,
    BUCHUNGSDATUM           DATETIME NOT NULL,
    TYP                     ENUM('ANFANGSBESTAND','EINLAGE','ENTNAHME',
                                 'UMSATZ_BAR','TAGESABSCHLUSS') NOT NULL,
    BETRAG                  INT NOT NULL COMMENT 'Cent, Einlage positiv / Entnahme negativ',
    NOTIZ                   VARCHAR(255),
    MITARBEITER_ID          INT,
    VORGANG_ID              INT          COMMENT 'FK → XT_KASSE_VORGAENGE bei UMSATZ_BAR',
    TAGESABSCHLUSS_ID       INT          COMMENT 'FK → XT_KASSE_TAGESABSCHLUSS',
    ERSTELLT                TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_terminal_datum (TERMINAL_NR, BUCHUNGSDATUM)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── Tagesabschluss (Z-Bon) ────────────────────────────────────
CREATE TABLE IF NOT EXISTS XT_KASSE_TAGESABSCHLUSS (
    ID                      INT AUTO_INCREMENT PRIMARY KEY,
    TERMINAL_NR             INT NOT NULL,
    DATUM                   DATE NOT NULL,
    ZEITPUNKT               DATETIME NOT NULL,
    Z_NR                    INT NOT NULL COMMENT 'Fortlaufende Z-Bon-Nummer je Terminal',
    MITARBEITER_ID          INT,
    -- Umsätze (Cent)
    ANZAHL_BELEGE           INT NOT NULL DEFAULT 0,
    UMSATZ_BRUTTO           INT NOT NULL DEFAULT 0,
    UMSATZ_NETTO            INT NOT NULL DEFAULT 0,
    MWST_1                  INT NOT NULL DEFAULT 0,
    MWST_2                  INT NOT NULL DEFAULT 0,
    MWST_3                  INT NOT NULL DEFAULT 0,
    NETTO_1                 INT NOT NULL DEFAULT 0,
    NETTO_2                 INT NOT NULL DEFAULT 0,
    NETTO_3                 INT NOT NULL DEFAULT 0,
    -- Zahlarten (Cent)
    UMSATZ_BAR              INT NOT NULL DEFAULT 0,
    UMSATZ_EC               INT NOT NULL DEFAULT 0,
    UMSATZ_KUNDENKONTO      INT NOT NULL DEFAULT 0,
    UMSATZ_SONSTIGE         INT NOT NULL DEFAULT 0,
    -- Kassenbuch (Cent)
    KASSENBESTAND_ANFANG    INT NOT NULL DEFAULT 0,
    EINLAGEN                INT NOT NULL DEFAULT 0,
    ENTNAHMEN               INT NOT NULL DEFAULT 0,
    KASSENBESTAND_ENDE      INT NOT NULL DEFAULT 0,
    -- Stornos
    ANZAHL_STORNOS          INT NOT NULL DEFAULT 0,
    BETRAG_STORNOS          INT NOT NULL DEFAULT 0,
    -- TSE
    TSE_TX_ID               VARCHAR(36),
    TSE_SIGNATUR            TEXT,
    TSE_SIGNATUR_ZAEHLER    BIGINT,
    TSE_SERIAL              VARCHAR(200),
    ERSTELLT                TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_terminal_z (TERMINAL_NR, Z_NR),
    INDEX idx_terminal_datum (TERMINAL_NR, DATUM)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── Bon-Nummern-Zähler ───────────────────────────────────────
-- Separater Zähler damit BON_NR atomisch und ohne Race Condition
-- erhöht werden kann (via SELECT ... FOR UPDATE).
CREATE TABLE IF NOT EXISTS XT_KASSE_ZAEHLER (
    TERMINAL_NR             INT NOT NULL PRIMARY KEY,
    BON_NR_LETZT            INT NOT NULL DEFAULT 0,
    Z_NR_LETZT              INT NOT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── Lieferschein-Zuordnung (Bon → CAO Lieferschein) ──────────
CREATE TABLE IF NOT EXISTS XT_KASSE_LIEFERSCHEINE (
    ID                      INT AUTO_INCREMENT PRIMARY KEY,
    VORGANG_ID              INT NOT NULL UNIQUE,
    LIEFERSCHEIN_ID         INT NOT NULL COMMENT 'FK → LIEFERSCHEIN (CAO)',
    VLSNUM                  VARCHAR(50)  COMMENT 'Lieferscheinnummer (CAO)',
    ERSTELLT                TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_vorgang       (VORGANG_ID),
    INDEX idx_ls            (LIEFERSCHEIN_ID)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── TSE-Transaktionslog (Audit-Trail) ─────────────────────────
CREATE TABLE IF NOT EXISTS XT_KASSE_TSE_LOG (
    ID                      INT AUTO_INCREMENT PRIMARY KEY,
    ZEITPUNKT               TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    TERMINAL_NR             INT NOT NULL,
    VORGANG_ID              INT,
    AKTION                  VARCHAR(50) NOT NULL COMMENT 'start/finish/cancel/tagesabschluss',
    TX_ID                   VARCHAR(36),
    TX_REVISION             INT,
    REQUEST_BODY            TEXT,
    RESPONSE_CODE           INT,
    RESPONSE_BODY           TEXT,
    FEHLER                  TEXT,
    INDEX idx_terminal      (TERMINAL_NR),
    INDEX idx_vorgang       (VORGANG_ID)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── Initial-Zeilen Kassenzähler einfügen ─────────────────────
-- Für Terminal 1–7 (wird durch config.py / Admin angelegt)
INSERT IGNORE INTO XT_KASSE_ZAEHLER (TERMINAL_NR, BON_NR_LETZT, Z_NR_LETZT)
    VALUES (1,0,0),(2,0,0),(3,0,0),(4,0,0),(5,0,0),(6,0,0),(7,0,0);

-- ── Standard-Terminal 1 ───────────────────────────────────────
INSERT IGNORE INTO XT_KASSE_TERMINALS
    (TERMINAL_NR, BEZEICHNUNG, FISKALY_ENV, DRUCKER_IP, DRUCKER_PORT, KASSENLADE, AKTIV)
    VALUES (1, 'Hauptkasse', 'test', '', 9100, 1, 1);
