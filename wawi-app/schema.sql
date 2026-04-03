-- ============================================================
-- CAO-XT WaWi-App – Datenbankschema (cao_wawi)
-- GoBD-konform: WAWI_PREISHISTORIE ist append-only (kein UPDATE/DELETE)
-- Ausführen: mysql -u <user> -p cao_wawi < schema.sql
-- ============================================================

CREATE DATABASE IF NOT EXISTS cao_wawi
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE cao_wawi;

-- ------------------------------------------------------------
-- Preisgruppen-Definition
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS WAWI_PREISGRUPPEN (
  id           INT AUTO_INCREMENT PRIMARY KEY,
  name         VARCHAR(100) NOT NULL,
  beschreibung TEXT,
  aktiv        TINYINT(1) DEFAULT 1,
  erstellt_am  DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ------------------------------------------------------------
-- GoBD-konforme Preishistorie – NIEMALS UPDATE/DELETE
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS WAWI_PREISHISTORIE (
  id              BIGINT AUTO_INCREMENT PRIMARY KEY,
  artikel_id      INT NOT NULL,           -- CAO ARTIKEL.REC_ID (read-only-Referenz)
  preisgruppe_id  INT NOT NULL,
  ek_preis        DECIMAL(10,4),          -- Einkaufspreis netto
  vk_preis        DECIMAL(10,4) NOT NULL, -- Verkaufspreis brutto
  marge_prozent   DECIMAL(6,2),
  mwst_satz       DECIMAL(5,2) NOT NULL DEFAULT 19.00,
  erstellt_am     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  erstellt_von    VARCHAR(100) NOT NULL,
  aenderungsgrund VARCHAR(255),
  import_ref      VARCHAR(100),           -- CSV-Import Batch-UUID
  CONSTRAINT fk_preisgruppe
    FOREIGN KEY (preisgruppe_id) REFERENCES WAWI_PREISGRUPPEN(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE INDEX IF NOT EXISTS idx_artikel_gruppe_am
  ON WAWI_PREISHISTORIE(artikel_id, preisgruppe_id, erstellt_am DESC);

-- ------------------------------------------------------------
-- CSV-Import-Log
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS WAWI_IMPORT_LOG (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  batch_id      VARCHAR(100) NOT NULL,
  dateiname     VARCHAR(255),
  zeilen_total  INT,
  zeilen_ok     INT,
  zeilen_fehler INT,
  fehler_detail JSON,
  erstellt_am   DATETIME DEFAULT CURRENT_TIMESTAMP,
  erstellt_von  VARCHAR(100)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ------------------------------------------------------------
-- View: jeweils neuester Preis pro Artikel + Preisgruppe
-- ------------------------------------------------------------
CREATE OR REPLACE VIEW v_aktuelle_preise AS
SELECT ph.*
FROM WAWI_PREISHISTORIE ph
INNER JOIN (
  SELECT artikel_id, preisgruppe_id, MAX(erstellt_am) AS max_am
  FROM WAWI_PREISHISTORIE
  GROUP BY artikel_id, preisgruppe_id
) latest
  ON  ph.artikel_id     = latest.artikel_id
  AND ph.preisgruppe_id = latest.preisgruppe_id
  AND ph.erstellt_am    = latest.max_am;

-- ------------------------------------------------------------
-- Initial-Daten: Standard-Preisgruppen
-- ------------------------------------------------------------
INSERT IGNORE INTO WAWI_PREISGRUPPEN (id, name, beschreibung, aktiv)
VALUES
  (1, 'Normalpreis',     'Standard-Verkaufspreis für alle Kunden', 1),
  (2, 'Mitgliederpreis', 'Vergünstigter Preis für Vereinsmitglieder', 1);
