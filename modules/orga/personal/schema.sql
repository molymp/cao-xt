-- ============================================================
-- CAO-XT Orga-Personal – Datenbankschema P1 (Stammdaten + Audit)
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
  COMMENT='Orga-Personal: Mitarbeiter-Stammdaten (entkoppelt von CAO.MITARBEITER)';


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
    IN_ZEITERFASSUNG   TINYINT(1)   NOT NULL DEFAULT 1 COMMENT '1 = nimmt an Zeiterfassung/Stempeluhr teil, 0 = nicht (z.B. Leitende Angestellte/GF)',
    AKTIV              TINYINT(1)   NOT NULL DEFAULT 1,
    SORT               SMALLINT     NOT NULL DEFAULT 0,

    UNIQUE KEY uq_bezeichnung (BEZEICHNUNG)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Lohnarten / Beschaeftigungsarten';

INSERT IGNORE INTO XT_PERSONAL_LOHNART
  (LOHNART_ID, BEZEICHNUNG, MINIJOB_FLAG, SV_PFLICHTIG_FLAG, IN_ZEITERFASSUNG, SORT) VALUES
  (1, 'Minijob',                      1, 0, 1, 10),
  (2, 'Teilzeit',                     0, 1, 1, 20),
  (3, 'Vollzeit',                     0, 1, 1, 30),
  (4, 'Werkstudent',                  0, 0, 1, 40),
  (5, 'Aushilfe',                     0, 1, 1, 50),
  (6, 'Azubi',                        0, 1, 1, 60),
  (7, 'Leitende Angestellte / GF',    0, 1, 0, 70);

-- Nachruesten, falls LOHNART bereits ohne IN_ZEITERFASSUNG angelegt wurde
-- (und ggf. den neuen Seed-Eintrag nachtragen).
ALTER TABLE XT_PERSONAL_LOHNART
    ADD COLUMN IF NOT EXISTS IN_ZEITERFASSUNG TINYINT(1) NOT NULL DEFAULT 1
        COMMENT '1 = nimmt an Zeiterfassung/Stempeluhr teil, 0 = nicht (z.B. Leitende Angestellte/GF)'
        AFTER SV_PFLICHTIG_FLAG;
INSERT IGNORE INTO XT_PERSONAL_LOHNART
  (LOHNART_ID, BEZEICHNUNG, MINIJOB_FLAG, SV_PFLICHTIG_FLAG, IN_ZEITERFASSUNG, SORT)
  VALUES (7, 'Leitende Angestellte / GF', 0, 1, 0, 70);


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


-- ── Aenderungsprotokoll fuer Arbeitszeitmodelle (append-only, GoBD) ─────────
--
-- Analog XT_PERSONAL_MA_LOG: pro INSERT/UPDATE auf XT_PERSONAL_AZ_MODELL wird
-- hier ein Snapshot der geaenderten Felder abgelegt. REF_REC_ID verweist auf
-- den jeweiligen AZ-Modell-Datensatz, PERS_ID erlaubt die Anzeige im
-- gemeinsamen Aenderungsprotokoll am Mitarbeiter.
--
CREATE TABLE IF NOT EXISTS XT_PERSONAL_AZ_MODELL_LOG (
    REC_ID           INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    PERS_ID          INT UNSIGNED NOT NULL,
    REF_REC_ID       INT UNSIGNED NOT NULL            COMMENT 'REC_ID aus XT_PERSONAL_AZ_MODELL',
    OPERATION        ENUM('INSERT','UPDATE','DELETE') NOT NULL,
    FELDER_ALT_JSON  JSON         NULL                COMMENT 'Werte vor der Aenderung (nur geaenderte Felder)',
    FELDER_NEU_JSON  JSON         NULL                COMMENT 'Werte nach der Aenderung',
    GEAEND_AT        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    GEAEND_VON       INT UNSIGNED NULL                COMMENT 'CAO MA_ID, NULL = System-Uebergang',

    INDEX idx_pers_id   (PERS_ID),
    INDEX idx_geaend_at (GEAEND_AT)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Append-only Aenderungsprotokoll fuer XT_PERSONAL_AZ_MODELL';


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


-- ── Aenderungsprotokoll fuer Urlaubsantraege (append-only, GoBD) ────────────
--
-- Analog XT_PERSONAL_MA_LOG / XT_PERSONAL_AZ_MODELL_LOG. Deckt INSERT (neuer
-- Antrag) und UPDATE (Statusuebergang geplant → genehmigt / genommen /
-- abgelehnt / storniert) ab. System-Auto-Abschluss (urlaub_antraege_abschliessen)
-- wird mit GEAEND_VON = NULL geloggt.
--
CREATE TABLE IF NOT EXISTS XT_PERSONAL_URLAUB_ANTRAG_LOG (
    REC_ID           INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    PERS_ID          INT UNSIGNED NOT NULL,
    REF_REC_ID       INT UNSIGNED NOT NULL            COMMENT 'REC_ID aus XT_PERSONAL_URLAUB_ANTRAG',
    OPERATION        ENUM('INSERT','UPDATE','DELETE') NOT NULL,
    FELDER_ALT_JSON  JSON         NULL,
    FELDER_NEU_JSON  JSON         NULL,
    GEAEND_AT        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    GEAEND_VON       INT UNSIGNED NULL                COMMENT 'NULL = System (Auto-Abschluss)',

    INDEX idx_pers_id   (PERS_ID),
    INDEX idx_geaend_at (GEAEND_AT)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Append-only Aenderungsprotokoll fuer XT_PERSONAL_URLAUB_ANTRAG';


-- ============================================================
-- P2 – Schichtplanung (Stammdaten + Zuordnungen)
-- ============================================================


-- ── Schicht-/Aufgaben-Stammdaten (Lookup) ───────────────────────────────────
--
-- TYP:
--   'fix'     – Schicht mit festen Start-/Endzeiten (z.B. Frueh 06:00-12:00)
--   'flex'    – Flexible Schicht ohne feste Zeiten, aber mit vorgebbarer Dauer
--               bei der Zuordnung (Bsp.: Buchhaltung 3h, Reinigung 2h).
--               STARTZEIT/ENDZEIT bleiben NULL.
--   'aufgabe' – Aufgabe ohne Zeitbezug (Bsp.: Kassenabschluss, Bestellung).
--               STARTZEIT/ENDZEIT bleiben NULL, keine Arbeitszeit-Wirkung.
--
-- Pausen werden NICHT pro Schicht hinterlegt, sondern tagesweise je MA auf
-- Basis der Gesamt-Arbeitszeit ermittelt (siehe XT_PERSONAL_PAUSE_REGELUNG).
--
CREATE TABLE IF NOT EXISTS XT_PERSONAL_SCHICHT (
    SCHICHT_ID       INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    BEZEICHNUNG      VARCHAR(50)  NOT NULL,
    KUERZEL          VARCHAR(10)  NOT NULL            COMMENT 'Kompakte Kalenderdarstellung, z.B. F, BH, KA',
    TYP              ENUM('fix','flex','aufgabe') NOT NULL DEFAULT 'fix',
    STARTZEIT        TIME         NULL                COMMENT 'Nur bei TYP=fix Pflicht',
    ENDZEIT          TIME         NULL                COMMENT 'Ende vor Start = Nachtschicht (+1 Tag)',
    FARBE            VARCHAR(7)   NOT NULL DEFAULT '#4A7C3A' COMMENT 'Hex-Code fuer Kalender',
    AKTIV            TINYINT(1)   NOT NULL DEFAULT 1,
    SORT             SMALLINT     NOT NULL DEFAULT 0,
    ERSTELLT_AT      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ERSTELLT_VON     INT UNSIGNED NOT NULL,
    GEAEND_AT        DATETIME     NULL,
    GEAEND_VON       INT UNSIGNED NULL,

    UNIQUE KEY uq_bezeichnung (BEZEICHNUNG),
    UNIQUE KEY uq_kuerzel     (KUERZEL)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Schicht-/Aufgaben-Stammdaten';


-- ── Schichtplan-Zuordnungen ──────────────────────────────────────────────────
--
-- DAUER_MIN: nur bei TYP='flex' relevant (individuelle Laenge pro Zuordnung).
-- Bei TYP='fix'     wird die Dauer aus STARTZEIT/ENDZEIT abgeleitet.
-- Bei TYP='aufgabe' bleibt DAUER_MIN NULL (keine Wirkung auf Arbeitszeit).
--
CREATE TABLE IF NOT EXISTS XT_PERSONAL_SCHICHT_ZUORDNUNG (
    REC_ID           INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    PERS_ID          INT UNSIGNED NOT NULL,
    DATUM            DATE         NOT NULL,
    SCHICHT_ID       INT UNSIGNED NOT NULL,
    DAUER_MIN        SMALLINT UNSIGNED NULL           COMMENT 'Nur bei TYP=flex',
    KOMMENTAR        VARCHAR(255) NULL,
    ERSTELLT_AT      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ERSTELLT_VON     INT UNSIGNED NOT NULL,
    GEAEND_AT        DATETIME     NULL,
    GEAEND_VON       INT UNSIGNED NULL,

    INDEX idx_pers_datum (PERS_ID, DATUM),
    INDEX idx_datum      (DATUM)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Zuordnung Mitarbeiter ↔ Schicht/Aufgabe an einem Datum';


-- Seed-Daten: gaengige Schichten und Aufgaben fuer den Dorfladen
INSERT IGNORE INTO XT_PERSONAL_SCHICHT
  (SCHICHT_ID, BEZEICHNUNG, KUERZEL, TYP, STARTZEIT, ENDZEIT,
   FARBE, SORT, ERSTELLT_VON) VALUES
  (1, 'Frueh',          'F',   'fix',     '06:00', '12:00', '#4A7C3A', 10, 0),
  (2, 'Mittag',         'M',   'fix',     '10:00', '14:00', '#7BA84A', 20, 0),
  (3, 'Spaet',          'S',   'fix',     '14:00', '18:30', '#9BC55A', 30, 0),
  (4, 'Ganztag',        'GT',  'fix',     '08:00', '18:00', '#2E5A2E', 40, 0),
  (5, 'Backshift',      'BS',  'fix',     '05:00', '13:00', '#D4A73A', 50, 0),
  (6, 'Buchhaltung',    'BH',  'flex',    NULL,    NULL,    '#5B7BA8', 60, 0),
  (7, 'Reinigung',      'RE',  'flex',    NULL,    NULL,    '#A87B5B', 70, 0),
  (8, 'Kassenabschluss','KA',  'aufgabe', NULL,    NULL,    '#8E5BA8', 80, 0),
  (9, 'Bestellung',     'BE',  'aufgabe', NULL,    NULL,    '#5BA89E', 90, 0);


-- ── Pausenregelung (versioniert, tagesbezogen) ──────────────────────────────
--
-- ArbZG §4: bei Arbeitszeit > 6h → 30 min Pause, bei > 9h → 45 min.
-- Je Betriebsvereinbarung kann die Regelung abweichen. Pausen werden pro
-- Mitarbeiter und Tag auf Basis der gesamten gebuchten Arbeitszeit bestimmt –
-- nicht pro Einzelschicht.
--
-- PAUSE_BEZAHLT_FLAG: 1 = Pause ist bezahlt, 0 = Pause wird von Arbeitszeit abgezogen
--
CREATE TABLE IF NOT EXISTS XT_PERSONAL_PAUSE_REGELUNG (
    REC_ID              INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    GUELTIG_AB          DATE         NOT NULL,
    SCHWELLE1_MIN       SMALLINT     NOT NULL         COMMENT 'ab dieser Tagesarbeitszeit greift PAUSE1_MIN',
    PAUSE1_MIN          SMALLINT     NOT NULL,
    SCHWELLE2_MIN       SMALLINT     NOT NULL,
    PAUSE2_MIN          SMALLINT     NOT NULL,
    PAUSE_BEZAHLT_FLAG  TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '1=bezahlt, 0=Abzug',
    KOMMENTAR           VARCHAR(255) NULL,
    ERSTELLT_AT         DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ERSTELLT_VON        INT UNSIGNED NOT NULL,

    UNIQUE KEY uq_gueltig_ab (GUELTIG_AB)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Tagesbezogene Pausenregelung (versioniert)';

INSERT IGNORE INTO XT_PERSONAL_PAUSE_REGELUNG
  (GUELTIG_AB, SCHWELLE1_MIN, PAUSE1_MIN, SCHWELLE2_MIN, PAUSE2_MIN,
   PAUSE_BEZAHLT_FLAG, KOMMENTAR, ERSTELLT_VON) VALUES
  ('2025-01-01', 360, 30, 540, 45, 0,
   'Gesetzlich ArbZG §4: >6h→30min, >9h→45min, Abzug', 0);


-- ── P2b: Wochen-Status (offen / freigegeben) ────────────────────────────────
--
-- Pro KW ein Status-Container. Solange STATUS='offen', koennen Zuordnungen
-- frei angelegt und geloescht werden. 'freigegeben' sperrt saemtliches
-- Bearbeiten der Zuordnungen dieser KW; "entsperren" setzt zurueck auf 'offen'.
-- Kein Versionszaehler – die aktuelle Freigabe ist die einzige; frueheren
-- Status rekonstruiert man ueber das Log.
--
CREATE TABLE IF NOT EXISTS XT_PERSONAL_SCHICHTPLAN_WOCHE (
    JAHR             SMALLINT UNSIGNED NOT NULL,
    KW               TINYINT  UNSIGNED NOT NULL COMMENT 'ISO-Wochennummer 1..53',
    STATUS           ENUM('offen','freigegeben') NOT NULL DEFAULT 'offen',
    FREIGEGEBEN_AT   DATETIME NULL,
    FREIGEGEBEN_VON  INT UNSIGNED NULL COMMENT 'CAO MA_ID',
    KOMMENTAR        VARCHAR(500) NULL,
    GEAEND_AT        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                                              ON UPDATE CURRENT_TIMESTAMP,
    GEAEND_VON       INT UNSIGNED NULL,
    PRIMARY KEY (JAHR, KW)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Pro KW: Status offen/freigegeben, Freigabe-Metadaten';


-- ── Log fuer Wochen-Status-Aenderungen ───────────────────────────────────────
--
-- Append-only Log der Workflow-Ereignisse pro KW.
-- EREIGNIS-Werte (Strings, kein ENUM weil kuenftige Werte frei erweiterbar):
--   'freigegeben' – STATUS offen→freigegeben
--   'entsperrt'   – STATUS freigegeben→offen
--   'kopiert-nach' – Zuordnungen dieser KW wurden in DETAIL-KW kopiert
--   'vorlage-angewendet' – Vorlage DETAIL-Name wurde angewendet
--
CREATE TABLE IF NOT EXISTS XT_PERSONAL_SCHICHTPLAN_WOCHE_LOG (
    REC_ID      INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    JAHR        SMALLINT UNSIGNED NOT NULL,
    KW          TINYINT  UNSIGNED NOT NULL,
    EREIGNIS    VARCHAR(50)  NOT NULL,
    DETAIL      VARCHAR(500) NULL,
    GEAEND_AT   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    GEAEND_VON  INT UNSIGNED NULL COMMENT 'CAO MA_ID; NULL = System',
    INDEX idx_jahr_kw (JAHR, KW),
    INDEX idx_geaend_at (GEAEND_AT)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Append-only Log fuer Wochen-Workflow (freigeben/entsperren/kopieren)';


-- ── Freigabe-Snapshot (Iteration 4: Delta-Versand) ──────────────────────────
--
-- Beim Freigeben einer KW wird ein flacher Snapshot aller Zuordnungen
-- persistiert. Beim erneuten Freigeben (nach Entsperren + Aenderungen) wird
-- Pro-MA gegen den Snapshot verglichen – nur betroffene Mitarbeiter erhalten
-- eine Aenderungs-Mail. Entsperren loescht den Snapshot NICHT; er bleibt der
-- Referenzstand fuer die naechste Freigabe.
--
CREATE TABLE IF NOT EXISTS XT_PERSONAL_SCHICHTPLAN_WOCHE_SNAPSHOT (
    REC_ID        INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    JAHR          SMALLINT UNSIGNED NOT NULL,
    KW            TINYINT  UNSIGNED NOT NULL,
    PERS_ID       INT UNSIGNED NOT NULL,
    DATUM         DATE NOT NULL,
    SCHICHT_ID    INT UNSIGNED NOT NULL,
    BEZEICHNUNG   VARCHAR(80) NOT NULL,
    TYP           ENUM('fix','flex','aufgabe') NOT NULL,
    STARTZEIT     TIME NULL,
    ENDZEIT       TIME NULL,
    DAUER_MIN     SMALLINT UNSIGNED NULL,
    SNAPSHOT_AT   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_jahr_kw      (JAHR, KW),
    INDEX idx_jahr_kw_pers (JAHR, KW, PERS_ID)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Letzter Freigabe-Stand pro KW – Basis fuer Delta-Versand bei Re-Freigabe';


-- ── P2c: Schichtplan-Vorlagen (Iteration 3) ─────────────────────────────────
--
-- Eine Vorlage ist ein abgespeicherter 7-Tage-Plan (Wochentage 0=Mo..6=So),
-- unabhaengig von einer konkreten KW. Beim Anwenden werden die Zuordnungen
-- in die Ziel-KW uebernommen (DATUM = Montag + WOCHENTAG).
--
-- Anwenden setzt voraus, dass die Ziel-KW leer und nicht freigegeben ist
-- (gleiche Praeflight-Pruefung wie beim Kopieren).
--
CREATE TABLE IF NOT EXISTS XT_PERSONAL_SCHICHTPLAN_VORLAGE (
    REC_ID           INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    NAME             VARCHAR(100) NOT NULL,
    BESCHREIBUNG     VARCHAR(500) NULL,
    ERSTELLT_AT      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ERSTELLT_VON     INT UNSIGNED NOT NULL COMMENT 'CAO MA_ID',

    UNIQUE KEY uq_name (NAME)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Schichtplan-Vorlagen (abgespeicherter Wochen-Plan, KW-unabhaengig)';


CREATE TABLE IF NOT EXISTS XT_PERSONAL_SCHICHTPLAN_VORLAGE_ZUORDNUNG (
    REC_ID           INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    VORLAGE_REC_ID   INT UNSIGNED NOT NULL,
    WOCHENTAG        TINYINT UNSIGNED NOT NULL COMMENT '0=Mo .. 6=So',
    PERS_ID          INT UNSIGNED NOT NULL,
    SCHICHT_ID       INT UNSIGNED NOT NULL,
    DAUER_MIN        SMALLINT UNSIGNED NULL COMMENT 'Nur bei TYP=flex',
    KOMMENTAR        VARCHAR(255) NULL,

    INDEX idx_vorlage (VORLAGE_REC_ID),
    INDEX idx_vorlage_wtag (VORLAGE_REC_ID, WOCHENTAG)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Zuordnungen innerhalb einer Vorlage (je Wochentag)';


-- ============================================================
-- P4 – Abwesenheiten (Krankheit, Kind-Krank, Schulung, Sonstiges)
-- ============================================================
--
-- Ergaenzend zu XT_PERSONAL_URLAUB_ANTRAG (Teil 1c): Abwesenheiten, die
-- nicht auf den Urlaubssaldo gebucht werden. URLAUB ist eigene Tabelle und
-- hat eigenen Genehmigungs-Workflow – Abwesenheiten haben nur einen
-- Erfassungsvorgang ("eingetragen"), optional mit AU-Nachweis (Krankschein).
--
-- TYP:
--   'krank'       – Krankheit (ggf. mit AU; AU_VORGELEGT-Flag)
--   'kind_krank'  – Kind krank / Pflege
--   'schulung'    – Fortbildung (bezahlte Freistellung)
--   'unbezahlt'   – unbezahlter Urlaub
--   'sonstiges'   – sonstige bezahlte/unbezahlte Freistellung
--
-- GANZTAGS=1: kompletter Tag abwesend (Default).
-- GANZTAGS=0: teilweise – dann ist STUNDEN (DECIMAL 4,1) gepflegt; im
--             Schichtplan-Konflikt-Check wird der ganze Tag als tangiert
--             markiert (einfache Heuristik, reicht fuer Dorfladen-Scope).
--
CREATE TABLE IF NOT EXISTS XT_PERSONAL_ABWESENHEIT (
    REC_ID            INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    PERS_ID           INT UNSIGNED NOT NULL,
    TYP               ENUM('krank','kind_krank','schulung',
                           'unbezahlt','sonstiges') NOT NULL,
    VON               DATE         NOT NULL,
    BIS               DATE         NOT NULL,
    GANZTAGS          TINYINT UNSIGNED NOT NULL DEFAULT 1,
    STUNDEN           DECIMAL(4,1) NULL COMMENT 'nur wenn GANZTAGS=0',
    AU_VORGELEGT      TINYINT UNSIGNED NOT NULL DEFAULT 0
                      COMMENT 'fuer TYP=krank: AU/Krankenschein eingegangen?',
    BEZAHLT           TINYINT UNSIGNED NOT NULL DEFAULT 1
                      COMMENT 'Bezahlte Abwesenheit? (Lohnfortzahlung) – krank/kind_krank/schulung standardm. 1, unbezahlt standardm. 0',
    BEMERKUNG         VARCHAR(500) NULL,
    ERSTELLT_AT       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ERSTELLT_VON      INT UNSIGNED NOT NULL,
    GEAEND_AT         DATETIME     NULL,
    GEAEND_VON        INT UNSIGNED NULL,
    STORNIERT         TINYINT UNSIGNED NOT NULL DEFAULT 0
                      COMMENT 'Soft-Delete: 1 = nicht mehr gueltig',

    INDEX idx_pers_von (PERS_ID, VON),
    INDEX idx_pers_typ (PERS_ID, TYP),
    INDEX idx_zeitraum (VON, BIS)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Abwesenheiten (Krankheit etc.), ergaenzend zu URLAUB_ANTRAG';


-- ── Aenderungsprotokoll fuer Abwesenheiten (append-only, GoBD) ──────────────
--
-- Analog XT_PERSONAL_URLAUB_ANTRAG_LOG. Erfasst INSERT (anlegen), UPDATE
-- (Bearbeitung, AU-Nachreichung, Stornierung) und DELETE (echte Loeschung
-- nur falls wirklich Fehleingabe – im Normalfall wird STORNIERT=1 gesetzt).
--
CREATE TABLE IF NOT EXISTS XT_PERSONAL_ABWESENHEIT_LOG (
    REC_ID           INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    PERS_ID          INT UNSIGNED NOT NULL,
    REF_REC_ID       INT UNSIGNED NOT NULL            COMMENT 'REC_ID aus XT_PERSONAL_ABWESENHEIT',
    OPERATION        ENUM('INSERT','UPDATE','DELETE') NOT NULL,
    FELDER_ALT_JSON  JSON         NULL,
    FELDER_NEU_JSON  JSON         NULL,
    GEAEND_AT        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    GEAEND_VON       INT UNSIGNED NULL,

    INDEX idx_pers_id   (PERS_ID),
    INDEX idx_geaend_at (GEAEND_AT)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Append-only Aenderungsprotokoll fuer XT_PERSONAL_ABWESENHEIT';


-- ============================================================
-- P4b – Feiertage (gesetzlich + manuell, pro Bundesland)
-- ============================================================
--
-- Hybrid-Design: gesetzliche Feiertage werden einmal pro Jahr aus dem
-- Python-Paket `holidays` gesynct (QUELLE='paket') und liegen dann lokal
-- in der DB. Das erlaubt:
--   1. Konsistente Ergebnisse, auch wenn sich das Paket spaeter aendert.
--   2. Manuelle Ergaenzungen (Betriebsferien, regionale Sonderfeiertage)
--      per QUELLE='manuell' in derselben Tabelle.
--   3. Eine einzige Abfrage bei Urlaubs-/Schichtplan-Logik.
--
-- BUNDESLAND ist der ISO-Kurzcode (BY, BW, HE, ...) oder 'BUND' fuer
-- bundesweit gueltige Tage. Im Regelbetrieb wird nur ein Bundesland
-- vorgehalten (konfiguriert in XT_EINSTELLUNGEN.personal_bundesland),
-- aber die Tabelle laesst Mischbetrieb zu.
--
-- UNIQUE(DATUM, NAME, BUNDESLAND) statt (DATUM, BUNDESLAND), damit
-- manuell ein zweiter Eintrag fuer denselben Tag moeglich ist
-- (z.B. 'Betriebsversammlung' zusaetzlich zum gesetzlichen Feiertag).
--
CREATE TABLE IF NOT EXISTS XT_PERSONAL_FEIERTAG (
    REC_ID           INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    DATUM            DATE         NOT NULL,
    NAME             VARCHAR(100) NOT NULL,
    BUNDESLAND       VARCHAR(4)   NOT NULL            COMMENT 'BY, BW, ... oder BUND',
    QUELLE           ENUM('paket','manuell') NOT NULL DEFAULT 'paket',
    ERSTELLT_AT      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ERSTELLT_VON     INT UNSIGNED NULL                COMMENT 'CAO MA_ID, NULL = System-Sync',

    UNIQUE KEY uq_datum_name_bl (DATUM, NAME, BUNDESLAND),
    INDEX idx_datum      (DATUM),
    INDEX idx_datum_bl   (DATUM, BUNDESLAND)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Feiertage (gesetzlich via holidays-Paket + manuelle Betriebsfeiertage)';


-- ============================================================
-- P3 – Stempeluhr (Kommen/Gehen im Kiosk)
-- ============================================================
--
-- Entkopplung von CAO.ZEITEN_* (wie in DECISIONS.md festgehalten): dort liegt
-- eine projekt-/aufgabenbasierte Zeiterfassung (TYP='P'/'A'), die nicht zum
-- Kommen/Gehen-Modell der Stempeluhr passt. Wir fuehren eine eigene Tabelle
-- mit einer Zeile pro Stempel-Ereignis.
--
-- Authentifizierung laeuft ueber CAO.KARTEN (TYP='M'), aufgeloest auf
-- XT_PERSONAL_MA.CAO_MA_ID. Keine Schemaaenderung an KARTEN; RFID-Karten sind
-- einfach weitere KARTEN-Eintraege mit TYP='M' und zusaetzlicher GUID.
--
-- RICHTUNG wird NICHT vom Benutzer gewaehlt, sondern aus dem letzten Stempel
-- hergeleitet: gab es heute bereits ein 'kommen', ist die naechste Aktion
-- 'gehen' und umgekehrt. Nach Mitternacht startet der Tag mit 'kommen'.
--
-- TERMINAL_NR ist das Kiosk-Terminal (1..9), auf dem gestempelt wurde –
-- dokumentarisch, nicht funktional.
--
CREATE TABLE IF NOT EXISTS XT_PERSONAL_STEMPEL (
    REC_ID           INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    PERS_ID          INT UNSIGNED NOT NULL,
    RICHTUNG         ENUM('kommen','gehen') NOT NULL,
    ZEITPUNKT        DATETIME     NOT NULL            COMMENT 'Tatsaechlicher Zeitpunkt des Ereignisses',
    QUELLE           ENUM('kiosk','korrektur') NOT NULL DEFAULT 'kiosk',
    TERMINAL_NR      TINYINT UNSIGNED NULL            COMMENT 'Kiosk-Terminal-Nr, NULL bei Korrektur',
    KOMMENTAR        VARCHAR(255) NULL                COMMENT 'Bei QUELLE=korrektur Pflicht (siehe KORREKTUR-Tabelle fuer Details)',
    ERSTELLT_AT      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ERSTELLT_VON     INT UNSIGNED NULL                COMMENT 'CAO MA_ID des Backoffice-Users bei QUELLE=korrektur, NULL bei Selbst-Stempel',

    INDEX idx_pers_zeit (PERS_ID, ZEITPUNKT),
    INDEX idx_zeitpunkt (ZEITPUNKT)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Stempeluhr-Ereignisse (Kommen/Gehen), eine Zeile pro Ereignis';


-- ── Aenderungsprotokoll fuer Stempel (append-only, GoBD) ────────────────────
--
-- Stempel sind lohnrelevant – jede manuelle Korrektur (INSERT eines neuen
-- Stempels durch Admin, UPDATE Zeitkorrektur, DELETE Fehl-Stempel) wird hier
-- protokolliert. GRUND ist Pflicht, damit nachtraeglich die Korrektur
-- begruendbar ist.
--
CREATE TABLE IF NOT EXISTS XT_PERSONAL_STEMPEL_KORREKTUR (
    REC_ID           INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    PERS_ID          INT UNSIGNED NOT NULL,
    REF_REC_ID       INT UNSIGNED NULL                COMMENT 'REC_ID aus XT_PERSONAL_STEMPEL, NULL wenn Original-Zeile schon geloescht',
    OPERATION        ENUM('INSERT','UPDATE','DELETE') NOT NULL,
    FELDER_ALT_JSON  JSON         NULL                COMMENT 'Werte vor der Aenderung (nur geaenderte Felder)',
    FELDER_NEU_JSON  JSON         NULL                COMMENT 'Werte nach der Aenderung',
    GRUND            VARCHAR(500) NOT NULL            COMMENT 'Warum wurde korrigiert? (Pflicht)',
    GEAEND_AT        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    GEAEND_VON       INT UNSIGNED NOT NULL            COMMENT 'CAO MA_ID des Backoffice-Users',

    INDEX idx_pers_id   (PERS_ID),
    INDEX idx_geaend_at (GEAEND_AT)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Append-only Aenderungsprotokoll fuer XT_PERSONAL_STEMPEL';


-- ── Hinweise fuer spaetere Erweiterungen ─────────────────────────────────────
-- Neue Spalten werden per separatem ALTER TABLE hinzugefuegt (analog Orga).
-- Tabellen, die auf weitere Phasen folgen:
--   P5 : evtl. XT_PERSONAL_REPORT_CACHE (falls Auswertungs-Performance es erzwingt)


-- ── Erweiterungen: PIN fuer Kiosk-Stempeluhr ────────────────────────────────
-- 4-stellige PIN als Alternative zum Kartenscan am Kiosk-Terminal.
-- Gespeichert wird NUR der Hash (pbkdf2-sha256) — Klartext existiert nur
-- kurzzeitig bei der Eingabe. Kein Revert moeglich, nur Zuruecksetzen.
-- MariaDB >= 10.0.2 unterstuetzt ADD COLUMN IF NOT EXISTS.
ALTER TABLE XT_PERSONAL_MA
    ADD COLUMN IF NOT EXISTS PIN_HASH       VARCHAR(128) NULL AFTER BEMERKUNG,
    ADD COLUMN IF NOT EXISTS PIN_GEAEND_AT  DATETIME     NULL AFTER PIN_HASH;


-- ── Erweiterung: Genehmigungs-Workflow fuer Abwesenheiten ───────────────────
-- Self-Service (Kiosk) legt Abwesenheiten mit STATUS='beantragt' an; das
-- Backoffice genehmigt/lehnt ab. Backoffice-direkt-Anlagen starten bereits
-- mit STATUS='genehmigt' (typisch retroaktive Erfassung nach telefonischer
-- Krankmeldung). 'storniert' bleibt am STORNIERT-Flag haengen (Soft-Delete),
-- ist also kein STATUS-Wert hier.
ALTER TABLE XT_PERSONAL_ABWESENHEIT
    ADD COLUMN IF NOT EXISTS STATUS ENUM('beantragt','genehmigt','abgelehnt')
        NOT NULL DEFAULT 'genehmigt' AFTER BEMERKUNG,
    ADD COLUMN IF NOT EXISTS STATUS_GEAEND_AT DATETIME NULL AFTER STATUS,
    ADD COLUMN IF NOT EXISTS STATUS_GEAEND_VON INT UNSIGNED NULL
        AFTER STATUS_GEAEND_AT;


-- ── Erweiterung: Stempel-QUELLE um 'import' ergaenzen ──────────────────────
-- CSV-Import (z.B. ShiftJuggler Attendance-Export) erzeugt Kommen/Gehen-
-- Events mit QUELLE='import'. Damit bleiben Kiosk-Selbststempel und
-- Backoffice-Korrekturen klar trennbar und der Importer kann idempotent
-- eine Ziel-Range "wegfegen und neu befuellen" (nur QUELLE='import'!).
ALTER TABLE XT_PERSONAL_STEMPEL
    MODIFY COLUMN QUELLE ENUM('kiosk','korrektur','import')
        NOT NULL DEFAULT 'kiosk';


-- ── Stunden-Korrekturen (Tages-Delta, vorzeichenbehaftet) ──────────────────
-- Manuelle Korrekturen (z.B. "Catch-up" aus Altsystem oder nachtraegliche
-- Anpassung aus der Lohnbuchhaltung) werden hier als Delta in Minuten
-- abgelegt. Die Arbeitszeitkonten-Aggregation addiert diese in der Spalte
-- "Korrektur". Positive Werte = Gutschrift, negative = Abzug.
--
-- QUELLE='import' kennzeichnet aus der ShiftJuggler-Attendance-CSV
-- importierte "Korrektur Arbeitszeit"-Zeilen und erlaubt idempotentes
-- Re-Importieren (erst alle import-Zeilen im Range loeschen, dann neu
-- einspielen). 'manuell' bleibt unangetastet.
CREATE TABLE IF NOT EXISTS XT_PERSONAL_STUNDEN_KORREKTUR (
    REC_ID       INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    PERS_ID      INT UNSIGNED NOT NULL,
    DATUM        DATE         NOT NULL,
    MINUTEN      INT          NOT NULL
                 COMMENT 'Vorzeichenbehaftet: + Gutschrift, - Abzug',
    GRUND        VARCHAR(255) NULL,
    QUELLE       ENUM('manuell','import') NOT NULL DEFAULT 'manuell',
    STORNIERT    TINYINT UNSIGNED NOT NULL DEFAULT 0,
    ERSTELLT_AT  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ERSTELLT_VON INT UNSIGNED NULL,

    INDEX idx_pers_datum (PERS_ID, DATUM),
    INDEX idx_pers_quelle (PERS_ID, QUELLE)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Manuelle/importierte Stunden-Korrekturen (Delta in Minuten)';


-- ── Benachrichtigungs-Empfaenger (Abwesenheiten, Urlaubsantraege, ...) ─────
-- Mehrere Empfaenger pro "Bereich" sind moeglich. Wird bei Self-Service-
-- Antraegen (Kiosk) best-effort per Mail benachrichtigt. Gepflegt ueber die
-- Admin-App.
CREATE TABLE IF NOT EXISTS XT_BENACHRICHTIGUNG_EMPFAENGER (
    REC_ID       INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    BEREICH      VARCHAR(40)  NOT NULL
                 COMMENT 'z.B. ''abwesenheit_antrag'', ''urlaubsantrag''',
    EMAIL        VARCHAR(150) NOT NULL,
    NAME         VARCHAR(100) NULL,
    AKTIV        TINYINT UNSIGNED NOT NULL DEFAULT 1,
    ERSTELLT_AT  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ERSTELLT_VON INT UNSIGNED NULL,

    UNIQUE KEY uq_bereich_email (BEREICH, EMAIL),
    INDEX idx_bereich_aktiv (BEREICH, AKTIV)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='E-Mail-Empfaenger fuer Benachrichtigungen (Abwesenheiten etc.)';


-- ── Aenderungsprotokoll fuer Stunden-Korrekturen (append-only, GoBD) ───────
--
-- Stunden-Korrekturen sind lohnrelevant: Anlage, Stornierung und Re-Imports
-- werden hier protokolliert. Storno geschieht fachlich ueber eine neue
-- Gegenbuchung (Delta mit umgekehrtem Vorzeichen), nicht ueber UPDATE –
-- daher gibt es hier nur INSERT und DELETE (letzteres praktisch nur aus
-- :func:`stundenkorrektur_import_loeschen` beim Re-Import).
--
CREATE TABLE IF NOT EXISTS XT_PERSONAL_STUNDEN_KORREKTUR_LOG (
    REC_ID           INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    PERS_ID          INT UNSIGNED NOT NULL,
    REF_REC_ID       INT UNSIGNED NOT NULL            COMMENT 'REC_ID aus XT_PERSONAL_STUNDEN_KORREKTUR',
    OPERATION        ENUM('INSERT','UPDATE','DELETE') NOT NULL,
    FELDER_ALT_JSON  JSON         NULL,
    FELDER_NEU_JSON  JSON         NULL,
    GEAEND_AT        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    GEAEND_VON       INT UNSIGNED NULL                COMMENT 'NULL = System (z.B. Re-Import-Loeschung)',

    INDEX idx_pers_id   (PERS_ID),
    INDEX idx_geaend_at (GEAEND_AT)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Append-only Aenderungsprotokoll fuer XT_PERSONAL_STUNDEN_KORREKTUR';


-- ── Erweiterung: Verfallsdatum fuer Urlaubskorrektur ────────────────────────
-- Typischer Anwendungsfall: Uebertrag aus Vorjahr muss bis zu einem Stichtag
-- (meist 31.03. des Folgejahres, konfigurierbar in XT_EINSTELLUNGEN unter
-- dem Schluessel 'personal_urlaub_uebertrag_verfall') genommen werden, sonst
-- verfaellt er ersatzlos. VERFAELLT_AM = NULL bedeutet "kein Verfall"
-- (Default fuer alle sonstigen Korrekturen).
ALTER TABLE XT_PERSONAL_URLAUB_KORREKTUR
    ADD COLUMN IF NOT EXISTS VERFAELLT_AM DATE NULL
        COMMENT 'Stichtag, bis zu dem diese Korrektur verbraucht sein muss'
        AFTER KOMMENTAR;
