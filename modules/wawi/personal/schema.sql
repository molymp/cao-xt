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


-- ============================================================
-- P1b – Lohnart, Arbeitszeitmodelle, Lohnkonstanten
-- ============================================================


-- ── Lohnart (Stammdaten-Lookup) ──────────────────────────────────────────────
--
-- Beschaeftigungsarten, verwendet im Arbeitszeitmodell. MINIJOB_FLAG schaltet
-- die Live-Warnung gegen MINIJOB_GRENZE_CT frei (siehe XT_PERSONAL_LOHNKONSTANTEN).
--
CREATE TABLE IF NOT EXISTS XT_PERSONAL_LOHNART (
    LOHNART_ID         TINYINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    BEZEICHNUNG        VARCHAR(50)  NOT NULL,
    MINIJOB_FLAG       TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '1 = unterliegt Minijob-Grenze',
    SV_PFLICHTIG_FLAG  TINYINT(1)   NOT NULL DEFAULT 1 COMMENT '1 = sozialversicherungspflichtig',
    AKTIV              TINYINT(1)   NOT NULL DEFAULT 1,
    SORT               SMALLINT     NOT NULL DEFAULT 0,

    UNIQUE KEY uq_bezeichnung (BEZEICHNUNG)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Lohnarten / Beschaeftigungsarten';

INSERT IGNORE INTO XT_PERSONAL_LOHNART
  (LOHNART_ID, BEZEICHNUNG, MINIJOB_FLAG, SV_PFLICHTIG_FLAG, SORT) VALUES
  (1, 'Minijob',     1, 0, 10),
  (2, 'Teilzeit',    0, 1, 20),
  (3, 'Vollzeit',    0, 1, 30),
  (4, 'Werkstudent', 0, 0, 40),
  (5, 'Aushilfe',    0, 1, 50),
  (6, 'Azubi',       0, 1, 60);


-- ── Arbeitszeitmodell (versioniert pro MA) ───────────────────────────────────
--
-- Jeder Eintrag ist append-only zu betrachten, ausser dass GUELTIG_BIS
-- automatisch gesetzt wird, wenn ein neues Modell mit spaeterem GUELTIG_AB
-- eingefuegt wird ("rolling close": Vorgaenger bekommt GUELTIG_BIS = neu.AB - 1).
--
-- TYP='WOCHE': STUNDEN_SOLL = vereinbarte Wochenstunden.
-- TYP='MONAT': STUNDEN_SOLL = vereinbarte Monatsstunden. Rechnen via Faktor 4,33.
--
-- STD_MO..STD_SO sind optional: falls gepflegt, bilden sie die Wochentags-
-- verteilung ab (fuer Schichtplanung und Urlaubsberechnung). Die Summe kann,
-- muss aber nicht mit STUNDEN_SOLL uebereinstimmen (z.B. 20 Monatsstunden +
-- "flexibel" ohne feste Wochentage).
--
CREATE TABLE IF NOT EXISTS XT_PERSONAL_AZ_MODELL (
    REC_ID           INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    PERS_ID          INT UNSIGNED NOT NULL,
    GUELTIG_AB       DATE         NOT NULL,
    GUELTIG_BIS      DATE         NULL,
    LOHNART_ID       TINYINT UNSIGNED NOT NULL,
    TYP              ENUM('WOCHE','MONAT') NOT NULL DEFAULT 'WOCHE',
    STUNDEN_SOLL     DECIMAL(5,2) NOT NULL COMMENT 'Gesamt pro Woche oder Monat (je TYP)',
    STD_MO           DECIMAL(4,2) NULL,
    STD_DI           DECIMAL(4,2) NULL,
    STD_MI           DECIMAL(4,2) NULL,
    STD_DO           DECIMAL(4,2) NULL,
    STD_FR           DECIMAL(4,2) NULL,
    STD_SA           DECIMAL(4,2) NULL,
    STD_SO           DECIMAL(4,2) NULL,
    URLAUB_JAHR_TAGE DECIMAL(4,1) NULL COMMENT 'Vertraglicher Jahresurlaub in Arbeitstagen',
    BEMERKUNG        VARCHAR(500) NULL,
    ERSTELLT_AT      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ERSTELLT_VON     INT UNSIGNED NOT NULL,
    GEAEND_AT        DATETIME     NULL,
    GEAEND_VON       INT UNSIGNED NULL,

    INDEX idx_pers_gueltig (PERS_ID, GUELTIG_AB)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Versionierte Arbeitszeit-/Vertragsmodelle pro Mitarbeiter';


-- ── Lohnkonstanten (Mindestlohn, Minijob-Grenze, versioniert) ────────────────
--
-- Jahresweise (oder unterjaehrig) gueltig ab GUELTIG_AB. Cent-Betraege:
--   MINDESTLOHN_CT      = Bundesmindestlohn pro Stunde
--   MINIJOB_GRENZE_CT   = Monatliches Brutto-Limit fuer geringfuegige Beschaeftigung
--                         (Formel: Mindestlohn × 130 / 3, rund auf volle Euro)
--
CREATE TABLE IF NOT EXISTS XT_PERSONAL_LOHNKONSTANTEN (
    REC_ID             INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    GUELTIG_AB         DATE         NOT NULL,
    MINDESTLOHN_CT     INT          NULL,
    MINIJOB_GRENZE_CT  INT          NULL,
    KOMMENTAR          VARCHAR(255) NULL,
    ERSTELLT_AT        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ERSTELLT_VON       INT UNSIGNED NOT NULL,

    UNIQUE KEY uq_gueltig_ab (GUELTIG_AB)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Gesetzliche Lohnkonstanten (versioniert)';

INSERT IGNORE INTO XT_PERSONAL_LOHNKONSTANTEN
  (GUELTIG_AB, MINDESTLOHN_CT, MINIJOB_GRENZE_CT, KOMMENTAR, ERSTELLT_VON) VALUES
  ('2025-01-01', 1282, 55600, 'Mindestlohn 12,82 EUR, Minijob-Grenze 556 EUR', 0),
  ('2026-01-01', 1390, 60300, 'Mindestlohn 13,90 EUR, Minijob-Grenze 603 EUR', 0);


-- ============================================================
-- P1c – Urlaubskorrekturen und Urlaubsantraege
-- ============================================================


-- ── Urlaubs-Korrekturbuchungen (pro Jahr, beliebig viele) ────────────────────
--
-- Korrekturen gegen den aus dem AZ-Modell berechneten Basis-Anspruch:
--   - Uebertrag aus Vorjahr (positiv)
--   - Unterjaehriger Vertragswechsel (positiv oder negativ)
--   - Ausgleichs-/Strafbuchungen
-- Append-only: keine UPDATE/DELETE-Routen. Korrekturen werden durch neue
-- Gegenbuchungen rueckgaengig gemacht, damit die Historie erhalten bleibt.
--
CREATE TABLE IF NOT EXISTS XT_PERSONAL_URLAUB_KORREKTUR (
    REC_ID           INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    PERS_ID          INT UNSIGNED NOT NULL,
    JAHR             SMALLINT     NOT NULL COMMENT 'Kalenderjahr fuer die Korrektur',
    TAGE             DECIMAL(5,1) NOT NULL COMMENT 'Arbeitstage, positiv oder negativ',
    GRUND            VARCHAR(100) NOT NULL,
    KOMMENTAR        VARCHAR(500) NULL,
    ERSTELLT_AT      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ERSTELLT_VON     INT UNSIGNED NOT NULL,

    INDEX idx_pers_jahr (PERS_ID, JAHR)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Urlaubs-Korrekturbuchungen (Uebertrag, Anpassungen)';


-- ── Urlaubsantraege mit Workflow-Status ──────────────────────────────────────
--
-- STATUS-Fluss: geplant → genehmigt → genommen.
-- abgelehnt / storniert sind terminale Status.
-- ARBEITSTAGE wird beim Anlegen vom Server aus dem AZ-Modell berechnet
-- (Anzahl Arbeitstage zwischen VON und BIS inklusive, nach Wochenverteilung
-- des jeweils gueltigen Modells).
--
CREATE TABLE IF NOT EXISTS XT_PERSONAL_URLAUB_ANTRAG (
    REC_ID            INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    PERS_ID           INT UNSIGNED NOT NULL,
    VON               DATE         NOT NULL,
    BIS               DATE         NOT NULL,
    ARBEITSTAGE       DECIMAL(4,1) NOT NULL COMMENT 'Nutzbare Urlaubstage gemaess AZ-Modell',
    STATUS            ENUM('geplant','genehmigt','genommen','abgelehnt','storniert')
                      NOT NULL DEFAULT 'geplant',
    KOMMENTAR         VARCHAR(500) NULL,
    STATUS_GEAEND_AT  DATETIME     NULL,
    STATUS_GEAEND_VON INT UNSIGNED NULL,
    ERSTELLT_AT       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ERSTELLT_VON      INT UNSIGNED NOT NULL,

    INDEX idx_pers_von (PERS_ID, VON),
    INDEX idx_pers_status (PERS_ID, STATUS)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Urlaubsantraege mit Workflow-Status';


-- ── Hinweise fuer spaetere Erweiterungen ─────────────────────────────────────
-- Neue Spalten werden per separatem ALTER TABLE hinzugefuegt (analog WaWi).
-- Tabellen, die auf weitere Phasen folgen:
--   P2 : XT_PERSONAL_SCHICHT, XT_PERSONAL_SCHICHT_ZUORDNUNG
--   P3 : XT_PERSONAL_STEMPEL, XT_PERSONAL_STEMPEL_KORREKTUR
--   P4 : XT_PERSONAL_ABWESENHEIT (Krankheit etc., ergaenzend zu URLAUB_ANTRAG)
