-- ============================================================
-- CAO-XT WaWi-Personal – Datenbankschema P1 (Stammdaten + Audit)
-- Tabellenpraefix: XT_PERSONAL_
--
-- Vollstaendig entkoppelt von CAO.MITARBEITER (siehe DECISIONS.md):
--   Keine INSERT/UPDATE auf CAO-Tabellen aus diesem Modul.
--   CAO wird nur fuer Login (MITARBEITER) und Zugriffsrollen (BENUTZERRECHTE)
--   read-only abgefragt.
--
-- Beträge: Integer-Cent (kein DECIMAL fuer Geld).
-- Datumsspalten: DATE (kein DATETIME) fuer GEBDATUM/EINTRITT/AUSTRITT/GUELTIG_AB.
-- ============================================================


-- ── Mitarbeiter-Stammdaten ────────────────────────────────────────────────────
--
-- PERS_ID ist unser interner Primaerschluessel (nicht CAO.MA_ID).
-- CAO_MA_ID ist optional und verknuepft MAs, die zusaetzlich einen CAO-Login
-- haben – fuer spaetere Karten-Zuordnung (KARTEN.ID = CAO_MA_ID) und
-- Stempeluhr (P3). Nicht jeder Personal-Eintrag braucht einen CAO-Login.
--
CREATE TABLE IF NOT EXISTS XT_PERSONAL_MA (
    PERS_ID          INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    PERSONALNUMMER   VARCHAR(10)  NOT NULL            COMMENT 'Frei vergebbar, fachliche Kennung',
    VNAME            VARCHAR(100) NOT NULL,
    NAME             VARCHAR(100) NOT NULL,
    KUERZEL          VARCHAR(10)  NULL                COMMENT 'z.B. ALB, KAN – fuer Schichtplan-Anzeige',
    GEBDATUM         DATE         NULL,
    EMAIL            VARCHAR(150) NULL                COMMENT 'Dienstliche Hauptadresse',
    EMAIL_ALT        VARCHAR(150) NULL                COMMENT 'Private/alternative Adresse (aus Import, UI-Anzeige optional)',
    STRASSE          VARCHAR(100) NULL,
    PLZ              VARCHAR(10)  NULL,
    ORT              VARCHAR(100) NULL,
    TELEFON          VARCHAR(50)  NULL,
    MOBIL            VARCHAR(50)  NULL,
    EINTRITT         DATE         NULL,
    AUSTRITT         DATE         NULL                COMMENT 'NULL = aktiv, Datum = ausgetreten',
    BEMERKUNG        TEXT         NULL,
    CAO_MA_ID        INT UNSIGNED NULL                COMMENT 'Optional: Verknuepfung mit CAO.MITARBEITER.MA_ID',
    -- Audit (Eigenfelder, unabhaengig von CAO-LOG-Mechanik)
    ERSTELLT_AT      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ERSTELLT_VON     INT UNSIGNED NOT NULL            COMMENT 'CAO MA_ID des anlegenden Backoffice-Users',
    GEAEND_AT        DATETIME     NULL,
    GEAEND_VON       INT UNSIGNED NULL,

    UNIQUE KEY uq_personalnummer (PERSONALNUMMER),
    UNIQUE KEY uq_kuerzel        (KUERZEL),
    UNIQUE KEY uq_cao_ma_id      (CAO_MA_ID),
    INDEX idx_austritt (AUSTRITT),
    INDEX idx_name     (NAME, VNAME)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='WaWi-Personal: Mitarbeiter-Stammdaten (entkoppelt von CAO.MITARBEITER)';


-- ── Aenderungsprotokoll (eigener Audit-Trail, GoBD) ──────────────────────────
--
-- Pro INSERT/UPDATE/DELETE auf XT_PERSONAL_MA wird hier ein Snapshot abgelegt.
-- Append-only: weder UPDATE noch DELETE auf dieser Tabelle. Ersetzt aus
-- Architekturgruenden das CAO-eigene MITARBEITER_LOG (das wegen unbekanntem
-- Signatur-Format nicht befuellt werden kann – siehe DECISIONS.md).
--
CREATE TABLE IF NOT EXISTS XT_PERSONAL_MA_LOG (
    REC_ID           INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    PERS_ID          INT UNSIGNED NOT NULL,
    OPERATION        ENUM('INSERT','UPDATE','DELETE') NOT NULL,
    FELDER_ALT_JSON  JSON         NULL                COMMENT 'Werte vor der Aenderung (nur geaenderte Felder)',
    FELDER_NEU_JSON  JSON         NULL                COMMENT 'Werte nach der Aenderung (nur geaenderte Felder)',
    GEAEND_AT        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    GEAEND_VON       INT UNSIGNED NOT NULL            COMMENT 'CAO MA_ID des ausfuehrenden Backoffice-Users',

    INDEX idx_pers_id   (PERS_ID),
    INDEX idx_geaend_at (GEAEND_AT)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Append-only Aenderungsprotokoll fuer XT_PERSONAL_MA';


-- ── Stundensatz-Historie (append-only) ───────────────────────────────────────
--
-- CAO.MITARBEITER.STUNDENSATZ ist nicht im CAO-eigenen MITARBEITER_LOG
-- enthalten – fuer lohn-/buchhaltungsrelevante Nachvollziehbarkeit fuehren wir
-- hier eine eigene Historie mit Gueltigkeits-ab-Datum.
--
CREATE TABLE IF NOT EXISTS XT_PERSONAL_STUNDENSATZ_HIST (
    REC_ID           INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    PERS_ID          INT UNSIGNED NOT NULL,
    GUELTIG_AB       DATE         NOT NULL,
    STUNDENSATZ_CT   INT          NOT NULL            COMMENT 'Brutto-Stundensatz in Cent (13,90 € = 1390)',
    KOMMENTAR        VARCHAR(255) NULL,
    ERSTELLT_AT      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ERSTELLT_VON     INT UNSIGNED NOT NULL,

    INDEX idx_pers_gueltig (PERS_ID, GUELTIG_AB)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Append-only Historie der vereinbarten Stundensaetze';


-- ── Hinweise fuer spaetere Erweiterungen ─────────────────────────────────────
-- Neue Spalten werden per separatem ALTER TABLE hinzugefuegt (analog WaWi).
-- Tabellen, die auf weitere Phasen folgen:
--   P1b: XT_PERSONAL_LOHNART, XT_PERSONAL_AZ_MODELL, XT_PERSONAL_LOHNKONSTANTEN
--   P1c: XT_PERSONAL_URLAUBSANSPRUCH, XT_PERSONAL_URLAUBSKORREKTUR
--   P2 : XT_PERSONAL_SCHICHT, XT_PERSONAL_SCHICHT_ZUORDNUNG
--   P3 : XT_PERSONAL_STEMPEL, XT_PERSONAL_STEMPEL_KORREKTUR
--   P4 : XT_PERSONAL_ABWESENHEIT
