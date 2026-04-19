-- ============================================================================
-- HACCP Temperatur-Ueberwachung – Schema (XT_HACCP_*)
-- ----------------------------------------------------------------------------
-- Sensoren liefern Messwerte via TFA Cloud-API, ein separater Poller schreibt
-- MESSWERTE und triggert die Alarm-Engine. Alarme und Sichtkontrollen sind
-- GoBD-/HACCP-konform append-only bzw. abschluss-rigide.
--
-- Idempotent: CREATE TABLE IF NOT EXISTS.
-- ============================================================================

-- Geraete-Stammdaten (ein Zeile pro ueberwachter Sensor/Geraet-Kombination).
-- Ein TFA-Geraet kann mehrere Sensoren haben -> TFA_SENSOR_INDEX unterscheidet.
-- TFA_INTERNAL_ID / TFA_NAME / TFA_MESSINTERVALL_S spiegeln die Felder
-- aus der TFA-Cloud-API (`id`, `name`, `measurementInterval`) zur Diagnose.
CREATE TABLE IF NOT EXISTS XT_HACCP_GERAET (
    GERAET_ID        INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    TFA_DEVICE_ID    VARCHAR(64)  NOT NULL,      -- API-Feld `deviceID` (Hex)
    TFA_SENSOR_INDEX TINYINT UNSIGNED NOT NULL DEFAULT 0,
    TFA_INTERNAL_ID  VARCHAR(64)  NULL,          -- API-Feld `id` (GUID)
    TFA_NAME         VARCHAR(100) NULL,          -- API-Feld `name` (vom User in der TFA-Cloud vergeben)
    TFA_MESSINTERVALL_S INT UNSIGNED NULL,       -- API-Feld `measurementInterval`
    NAME             VARCHAR(100) NOT NULL,      -- unsere Bezeichnung (frei)
    STANDORT         VARCHAR(100) NULL,
    WARENGRUPPE      VARCHAR(80)  NULL,     -- z.B. "Hackfleisch", "TK", "Sahnetorten"
    AKTIV            TINYINT(1)   NOT NULL DEFAULT 1,
    ANGELEGT_AT      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    LETZTE_KALIBRIERUNG DATE      NULL,
    BEMERKUNG        VARCHAR(500) NULL,
    UNIQUE KEY uq_tfa (TFA_DEVICE_ID, TFA_SENSOR_INDEX),
    INDEX idx_aktiv (AKTIV)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Grenzwerte pro Geraet, versioniert (neue Zeile pro Aenderung). Sensor-individuelle
-- Soll-Range + Karenzzeit (Toleranz gegen Tuer-Oeffnen) + optionaler Drift-Check.
CREATE TABLE IF NOT EXISTS XT_HACCP_GRENZWERTE (
    REC_ID          INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    GERAET_ID       INT UNSIGNED NOT NULL,
    TEMP_MIN_C      DECIMAL(5,2) NOT NULL,   -- z.B.  4.00
    TEMP_MAX_C      DECIMAL(5,2) NOT NULL,   -- z.B.  8.00
    KARENZ_MIN      SMALLINT UNSIGNED NOT NULL DEFAULT 15,
                                             -- Minuten dauernder Verstoss bevor Alarm
    DRIFT_AKTIV     TINYINT(1)   NOT NULL DEFAULT 0,
    DRIFT_K         DECIMAL(4,2) NULL,       -- K gegen rolling Median, z.B. 2.00
    DRIFT_FENSTER_H SMALLINT UNSIGNED NULL DEFAULT 24,
                                             -- Rolling-Window fuer Median
    STALE_MIN       SMALLINT UNSIGNED NOT NULL DEFAULT 30,
                                             -- kein Messwert seit N min -> offline-Alarm
    GUELTIG_AB      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ERSTELLT_VON    INT UNSIGNED NOT NULL,   -- CAO MA_ID
    BEMERKUNG       VARCHAR(500) NULL,
    INDEX idx_geraet_ab (GERAET_ID, GUELTIG_AB)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Append-only Zeitreihe. Dedup-Schutz via UNIQUE (Geraet, Zeitpunkt).
-- TRANSMISSION_COUNTER = monoton steigender Counter aus der TFA-API
-- (pro Measurement eindeutig), hilft beim Lueckenerkennen und Audit.
CREATE TABLE IF NOT EXISTS XT_HACCP_MESSWERT (
    REC_ID          BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    GERAET_ID       INT UNSIGNED NOT NULL,
    ZEITPUNKT_UTC   DATETIME     NOT NULL,
    TEMP_C          DECIMAL(5,2) NULL,
    FEUCHTE_PCT     DECIMAL(5,2) NULL,
    BATTERY_LOW     TINYINT(1)   NOT NULL DEFAULT 0,
    NO_CONNECTION   TINYINT(1)   NOT NULL DEFAULT 0,
    TRANSMISSION_COUNTER INT UNSIGNED NULL,  -- API `transmissionCounter`
    EMPFANGEN_AT    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_geraet_zeit (GERAET_ID, ZEITPUNKT_UTC),
    INDEX idx_zeitpunkt (ZEITPUNKT_UTC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Alarm-Events. Offen = ENDE_AT NULL. Korrektur-Abschluss via separatem Update.
CREATE TABLE IF NOT EXISTS XT_HACCP_ALARM (
    ALARM_ID        INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    GERAET_ID       INT UNSIGNED NOT NULL,
    TYP             ENUM('temp_hoch','temp_tief','drift','offline','battery') NOT NULL,
    START_AT        DATETIME     NOT NULL,
    ENDE_AT         DATETIME     NULL,       -- NULL = offen
    MAX_WERT        DECIMAL(6,2) NULL,       -- extremster Wert waehrend des Alarms
    LETZTE_STUFE    TINYINT UNSIGNED NOT NULL DEFAULT 0,
                                             -- 0 = noch keine Mail, 1/2/3 eskaliert
    KORREKTUR_TEXT  VARCHAR(500) NULL,
    KORREKTUR_VON   INT UNSIGNED NULL,       -- CAO MA_ID
    KORREKTUR_AT    DATETIME     NULL,
    INDEX idx_geraet_offen (GERAET_ID, ENDE_AT),
    INDEX idx_start (START_AT)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Eskalations-Log: eine Zeile pro versendeter Mail (fuer Nachvollziehbarkeit).
CREATE TABLE IF NOT EXISTS XT_HACCP_ALARM_ESKALATION (
    REC_ID       INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    ALARM_ID     INT UNSIGNED NOT NULL,
    STUFE        TINYINT UNSIGNED NOT NULL,
    EMPFAENGER   VARCHAR(255) NOT NULL,
    GESENDET_AT  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ERFOLG       TINYINT(1)   NOT NULL DEFAULT 1,
    FEHLERTEXT   VARCHAR(500) NULL,
    INDEX idx_alarm (ALARM_ID)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Empfaenger-Konfiguration pro Stufe. Mehrere Eintraege pro Stufe erlaubt.
CREATE TABLE IF NOT EXISTS XT_HACCP_ALARMKETTE (
    REC_ID       INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    STUFE        TINYINT UNSIGNED NOT NULL,  -- 1 / 2 / 3
    NAME         VARCHAR(100) NOT NULL,
    EMAIL        VARCHAR(255) NOT NULL,
    DELAY_MIN    SMALLINT UNSIGNED NOT NULL DEFAULT 0,
                                             -- Minuten nach Alarm-Start bis Mail
    AKTIV        TINYINT(1)   NOT NULL DEFAULT 1,
    INDEX idx_stufe (STUFE, AKTIV)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Taegliche Sichtkontrolle (Best-Practice ergaenzend zu Sensorik).
CREATE TABLE IF NOT EXISTS XT_HACCP_SICHTKONTROLLE (
    REC_ID          INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    GERAET_ID       INT UNSIGNED NOT NULL,
    DATUM           DATE         NOT NULL,
    QUITTIERT_VON   INT UNSIGNED NOT NULL,   -- CAO MA_ID
    QUITTIERT_AT    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    BEMERKUNG       VARCHAR(500) NULL,
    UNIQUE KEY uq_geraet_datum (GERAET_ID, DATUM)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Poller-Heartbeat: eine Zeile (REC_ID=1). Poller aktualisiert nach jedem Zyklus;
-- Watchdog + Dashboard lesen diese Zeile, um Ausfaelle zu erkennen.
CREATE TABLE IF NOT EXISTS XT_HACCP_POLLER_STATUS (
    REC_ID            TINYINT UNSIGNED NOT NULL PRIMARY KEY,  -- immer 1
    LAST_RUN_AT       DATETIME     NOT NULL,
    LAST_SUCCESS_AT   DATETIME     NULL,        -- letzter Zyklus ohne TFA-Fehler
    TFA_OK            TINYINT(1)   NOT NULL DEFAULT 1,
    LAST_ERROR        VARCHAR(500) NULL,
    ZYKLUS_COUNT      INT UNSIGNED NOT NULL DEFAULT 0,
    NEU_ENTDECKT      INT UNSIGNED NOT NULL DEFAULT 0,
    WATCHDOG_ALARM_AT DATETIME     NULL,        -- letzter Ausfall-Alarm gemailt
    HOSTNAME          VARCHAR(100) NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Hinweis: keine FOREIGN KEYs (konsistent mit anderen XT_*-Modulen, erlaubt
-- weichere Migrationen und entkoppelte Pflege).

-- ── Migrationen fuer bestehende Installationen ──────────────────────────
-- MariaDB >= 10.0.2 unterstuetzt ADD COLUMN IF NOT EXISTS. Die folgenden
-- Statements sind somit idempotent.
ALTER TABLE XT_HACCP_GERAET
    ADD COLUMN IF NOT EXISTS TFA_INTERNAL_ID     VARCHAR(64)  NULL AFTER TFA_SENSOR_INDEX,
    ADD COLUMN IF NOT EXISTS TFA_NAME            VARCHAR(100) NULL AFTER TFA_INTERNAL_ID,
    ADD COLUMN IF NOT EXISTS TFA_MESSINTERVALL_S INT UNSIGNED NULL AFTER TFA_NAME;

ALTER TABLE XT_HACCP_MESSWERT
    ADD COLUMN IF NOT EXISTS TRANSMISSION_COUNTER INT UNSIGNED NULL AFTER NO_CONNECTION;
