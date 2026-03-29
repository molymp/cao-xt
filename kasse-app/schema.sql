-- ============================================================
-- CAO-XT Kassen-App – Datenbankschema
-- Alle Tabellen tragen das Präfix XT_KASSE_
-- CAO-Faktura-Tabellen (ohne Präfix) werden read-only genutzt.
-- Ausnahme: LIEFERSCHEIN / LIEFERSCHEIN_POS werden beim
-- "Bon → Lieferschein" beschrieben.
-- ============================================================

-- ── TSE-Geräteregister ───────────────────────────────────────
-- Alle je genutzten TSEs bleiben gespeichert (Auditpflicht).
-- Dekommissionierte TSEs haben AUSSER_BETRIEB gesetzt.
CREATE TABLE IF NOT EXISTS XT_KASSE_TSE_GERAETE (
    REC_ID              INT AUTO_INCREMENT PRIMARY KEY,
    TYP                 ENUM('FISKALY','SWISSBIT','DEMO') NOT NULL DEFAULT 'FISKALY'
                            COMMENT 'FISKALY=Cloud-TSE, SWISSBIT=USB-TSE, DEMO=Trainings-Modus',
    BEZEICHNUNG         VARCHAR(200) NOT NULL COMMENT 'Frei wählbarer Name, z.B. "Fiskaly Cloud 2024"',
    SERIENNUMMER        VARCHAR(200) COMMENT 'TSE-Seriennummer (hex/base64, von TSE geliefert)',
    BSI_ZERTIFIZIERUNG  VARCHAR(50)  COMMENT 'BSI-Zertifizierungs-ID, z.B. BSI-K-TR-0374-2022',
    ZERTIFIKAT_GUELTIG_BIS DATE      COMMENT 'Ablaufdatum des BSI-Zertifikats (bei Swissbit USB-TSEs)',
    -- Fiskaly Cloud TSE
    FISKALY_ENV         ENUM('test','live') NOT NULL DEFAULT 'test',
    FISKALY_API_KEY     VARCHAR(200),
    FISKALY_API_SECRET  VARCHAR(200),
    FISKALY_TSS_ID      VARCHAR(36)  COMMENT 'UUID der Technical Security System',
    FISKALY_ADMIN_PIN   VARCHAR(100) COMMENT 'TSS Admin-PIN',
    FISKALY_ADMIN_PUK   VARCHAR(100) COMMENT 'TSS Admin-PUK (aus Fiskaly-Dashboard)',
    -- Swissbit USB TSE (libWorm)
    SWISSBIT_PFAD       VARCHAR(200) COMMENT 'Gerätepfad, z.B. /dev/sda1 oder /media/swissbit',
    SWISSBIT_ADMIN_PIN  VARCHAR(100),
    SWISSBIT_ADMIN_PUK  VARCHAR(100),
    -- Verwaltung / Historie
    IN_BETRIEB_SEIT     DATE         COMMENT 'Datum der Erstinbetriebnahme',
    AUSSER_BETRIEB      DATE         COMMENT 'Außerbetriebnahme (NULL = noch aktiv)',
    BEMERKUNG           TEXT         COMMENT 'Freitext: Grund für Wechsel, Ablaufdatum-Hinweis, etc.',
    ERSTELLT            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='TSE-Geräteregister: Alle genutzten TSEs bleiben zur Nachvollziehbarkeit erhalten.';

-- ── Terminal-Konfiguration ────────────────────────────────────
CREATE TABLE IF NOT EXISTS XT_KASSE_TERMINALS (
    ID                  INT AUTO_INCREMENT PRIMARY KEY,
    TERMINAL_NR         INT NOT NULL UNIQUE COMMENT 'Eindeutige Terminalnummer 1–9',
    BEZEICHNUNG         VARCHAR(100),
    -- Aktive TSE (Verweis auf Geräteregister)
    TSE_ID              INT NULL    COMMENT 'FK → XT_KASSE_TSE_GERAETE.REC_ID (aktuell aktive TSE)',
    TRAININGS_MODUS     TINYINT NOT NULL DEFAULT 0
                            COMMENT '1=Trainings-/Demo-Modus: keine echte TSE-Signierung, Bon mit TRAININGSBON-Aufdruck',
    -- Legacy Fiskaly TSE (Backward-Compat; wird durch TSE_ID abgelöst)
    FISKALY_API_KEY     VARCHAR(200),
    FISKALY_API_SECRET  VARCHAR(200),
    FISKALY_TSS_ID      VARCHAR(36)  COMMENT 'UUID der Technical Security System',
    FISKALY_CLIENT_ID   VARCHAR(36)  COMMENT 'UUID des Kassenclients in der TSS (pro Terminal)',
    FISKALY_ENV         ENUM('test','live') NOT NULL DEFAULT 'test',
    FISKALY_ADMIN_PIN   VARCHAR(100) COMMENT 'TSS Admin-PIN',
    FISKALY_ADMIN_PUK   VARCHAR(100) COMMENT 'TSS Admin-PUK (aus Fiskaly-Dashboard)',
    -- Drucker / Kassenlade
    DRUCKER_IP          VARCHAR(50),
    DRUCKER_PORT        INT NOT NULL DEFAULT 9100,
    KASSENLADE          TINYINT NOT NULL DEFAULT 0 COMMENT '0=keine, 1=Pin2, 2=Pin5',
    SOFORT_DRUCKEN      TINYINT NOT NULL DEFAULT 1,
    SCHUBLADE_AUTO_OEFFNEN TINYINT NOT NULL DEFAULT 1,
    QR_CODE             TINYINT NOT NULL DEFAULT 0 COMMENT '1 = QR-Code auf Bon drucken',
    -- Bon-Kopf: Firmenname überschreibt FIRMA.NAME1/2/3; Zusatz ist freier Slogan
    FIRMA_NAME          VARCHAR(100),
    FIRMA_ZUSATZ        VARCHAR(150),
    KONTO_BANK          VARCHAR(30) COMMENT 'Buchungskonto Bank für Transfer',
    KONTO_NEBENKASSE    VARCHAR(30) COMMENT 'Buchungskonto Nebenkasse',
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
-- Migration für bestehende Installationen:
-- ALTER TABLE XT_KASSE_KASSENBUCH MODIFY TYP VARCHAR(40) NOT NULL;
-- ALTER TABLE XT_KASSE_KASSENBUCH ADD COLUMN BUCHUNGSTEXT VARCHAR(255) AFTER NOTIZ, ADD COLUMN GEGENKONTO VARCHAR(50) AFTER BUCHUNGSTEXT, ADD COLUMN MWST_CODE TINYINT AFTER GEGENKONTO, ADD COLUMN BELEGNUMMER VARCHAR(50) AFTER MWST_CODE, ADD COLUMN KASSE VARCHAR(10) NOT NULL DEFAULT 'HAUPT' AFTER BELEGNUMMER;
-- ALTER TABLE XT_KASSE_TERMINALS ADD COLUMN KONTO_BANK VARCHAR(30) AFTER FIRMA_ZUSATZ, ADD COLUMN KONTO_NEBENKASSE VARCHAR(30) AFTER KONTO_BANK;
CREATE TABLE IF NOT EXISTS XT_KASSE_KASSENBUCH (
    ID                      INT AUTO_INCREMENT PRIMARY KEY,
    TERMINAL_NR             INT NOT NULL,
    BUCHUNGSDATUM           DATETIME NOT NULL,
    TYP                     VARCHAR(40) NOT NULL COMMENT 'ANFANGSBESTAND|EINLAGE|ENTNAHME|PRIVATENTNAHME|PRIVATEINLAGE|TRANSFER_KASSE_BANK|TRANSFER_BANK_KASSE|TRANSFER_KASSE_NEBEN|TRANSFER_NEBEN_KASSE|UMSATZ_BAR|TAGESABSCHLUSS',
    BETRAG                  INT NOT NULL COMMENT 'Cent, Einlage positiv / Entnahme negativ',
    NOTIZ                   VARCHAR(255),
    BUCHUNGSTEXT            VARCHAR(255),
    GEGENKONTO              VARCHAR(50),
    MWST_CODE               TINYINT     COMMENT 'NULL = keine MwSt',
    BELEGNUMMER             VARCHAR(50),
    KASSE                   VARCHAR(10) NOT NULL DEFAULT 'HAUPT' COMMENT 'HAUPT oder NEBEN',
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

-- ── Sonder-EAN-Regeln ────────────────────────────────────────
-- Konfiguriert Zeitschriften (977xxx), Inhouse-Preis-EAN (z.B. 2100421)
-- und Inhouse-Gewichts-EAN für die automatische Kassenerkennung.
CREATE TABLE IF NOT EXISTS XT_KASSE_EAN_REGELN (
    REC_ID         INT AUTO_INCREMENT PRIMARY KEY,
    --
    -- Inhouse-EAN Format: XX AAAA Z PPPPP Z  (13 Stellen)
    --   XX    = EAN_BEREICH  (2-stellige Bereichs-ID, z.B. "21"=Preis, "25"=Gewicht)
    --   AAAA  = 4-stellige CAO-Artikelnummer (ARTNUM) → wird per ARTIKEL_LOOKUP nachgeschlagen
    --   Z     = interne Prüfziffer des Artikelteils (Stellen 1-6, GS1-Gewichtung)
    --   PPPPP = 5-stelliger Wert: Preis in Cent (TYP=PREIS) oder Gramm (TYP=GEWICHT)
    --   Z     = EAN-13-Prüfziffer
    --
    -- Zeitschriften-EAN: beliebige Länge ("977"), kein Artikel-Lookup, Preis-Dialog
    --
    EAN_PRAEFIX    VARCHAR(13)  NOT NULL        COMMENT 'Bereichs-Präfix: "21", "25" oder "977"',
    TYP            ENUM('ZEITSCHRIFT','PREIS','GEWICHT','PRESSE') NOT NULL DEFAULT 'PREIS'
                                                COMMENT 'ZEITSCHRIFT=Preis-Dialog; PREIS/GEWICHT=Inhouse EAN; PRESSE=Preis in EAN[8:12] (VDZ)',
    ARTIKEL_LOOKUP TINYINT      NOT NULL DEFAULT 0
                                                COMMENT '1=ARTNUM aus EAN[3-6] in ARTIKEL nachschlagen',
    BEZEICHNUNG    VARCHAR(200) NOT NULL        COMMENT 'Fallback-Text auf dem Bon (wenn ARTIKEL_LOOKUP=0 oder nicht gefunden)',
    WG_ID          INT          NULL            COMMENT 'Fallback-Warengruppe',
    ARTIKEL_ID     INT          NULL            COMMENT 'Fester Sammelartikel (Alternative zu ARTIKEL_LOOKUP)',
    STEUER_CODE    TINYINT      NOT NULL DEFAULT 1 COMMENT 'Fallback-Steuercode 1=19%/2=7%/3=0%',
    PREIS_PRO_KG   INT          NULL            COMMENT 'Nur TYP=GEWICHT: Preis in Cent/kg',
    AKTIV          TINYINT      NOT NULL DEFAULT 1,
    ERSTELLT       TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_praefix (EAN_PRAEFIX)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Sonder-EAN-Regeln: Zeitschriften (977), Inhouse Preis-EAN (21), Gewichts-EAN (25)';

-- ── Initial-Zeilen Kassenzähler einfügen ─────────────────────
-- Für Terminal 1–7 (wird durch config.py / Admin angelegt)
INSERT IGNORE INTO XT_KASSE_ZAEHLER (TERMINAL_NR, BON_NR_LETZT, Z_NR_LETZT)
    VALUES (1,0,0),(2,0,0),(3,0,0),(4,0,0),(5,0,0),(6,0,0),(7,0,0);

-- ── Standard-Terminal 1 ───────────────────────────────────────
INSERT IGNORE INTO XT_KASSE_TERMINALS
    (TERMINAL_NR, BEZEICHNUNG, FISKALY_ENV, DRUCKER_IP, DRUCKER_PORT, KASSENLADE, AKTIV)
    VALUES (1, 'Hauptkasse', 'test', '', 9100, 1, 1);

-- ── Migration: Neue Spalten für bestehende Installationen ─────
-- Idempotent – ignoriert Fehler wenn Spalte bereits existiert.
-- In MariaDB 10.x: ADD COLUMN IF NOT EXISTS
ALTER TABLE XT_KASSE_TERMINALS
    ADD COLUMN IF NOT EXISTS FISKALY_ADMIN_PUK  VARCHAR(100)
        COMMENT 'TSS Admin-PUK (aus Fiskaly-Dashboard)'
        AFTER FISKALY_ADMIN_PIN,
    ADD COLUMN IF NOT EXISTS TSE_ID             INT NULL
        COMMENT 'FK → XT_KASSE_TSE_GERAETE.REC_ID (aktuell aktive TSE)'
        AFTER FISKALY_ADMIN_PUK,
    ADD COLUMN IF NOT EXISTS TRAININGS_MODUS    TINYINT NOT NULL DEFAULT 0
        COMMENT '1=Trainings-/Demo-Modus: keine echte TSE-Signierung'
        AFTER TSE_ID;

-- ── Migration: Bestehende Fiskaly-Konfiguration → TSE-Geräteregister ─────────
-- Legt für jede Terminal-Konfiguration mit vorhandenem API-Key einen
-- TSE-Geräteeintrag an, sofern noch keiner mit gleicher TSS-ID existiert.
INSERT INTO XT_KASSE_TSE_GERAETE
    (TYP, BEZEICHNUNG, FISKALY_ENV, FISKALY_API_KEY, FISKALY_API_SECRET,
     FISKALY_TSS_ID, FISKALY_ADMIN_PIN, FISKALY_ADMIN_PUK, IN_BETRIEB_SEIT)
    SELECT 'FISKALY',
           CONCAT('Fiskaly Cloud TSE (', IFNULL(FISKALY_ENV,'test'), ')'),
           IFNULL(FISKALY_ENV,'test'), FISKALY_API_KEY, FISKALY_API_SECRET,
           FISKALY_TSS_ID, FISKALY_ADMIN_PIN, FISKALY_ADMIN_PUK,
           DATE(ERSTELLT)
      FROM XT_KASSE_TERMINALS
     WHERE FISKALY_API_KEY IS NOT NULL AND FISKALY_API_KEY != ''
       AND NOT EXISTS (
           SELECT 1 FROM XT_KASSE_TSE_GERAETE g
            WHERE g.TYP = 'FISKALY'
              AND g.FISKALY_TSS_ID = XT_KASSE_TERMINALS.FISKALY_TSS_ID
       );

-- TSE_ID für Terminals setzen die noch keine haben aber eine passende TSE im Register haben
UPDATE XT_KASSE_TERMINALS t
   SET t.TSE_ID = (
       SELECT g.REC_ID FROM XT_KASSE_TSE_GERAETE g
        WHERE g.TYP = 'FISKALY'
          AND g.FISKALY_TSS_ID = t.FISKALY_TSS_ID
        LIMIT 1
   )
 WHERE t.TSE_ID IS NULL
   AND t.FISKALY_TSS_ID IS NOT NULL
   AND t.FISKALY_TSS_ID != '';
