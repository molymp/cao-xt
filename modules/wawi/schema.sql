-- ============================================================
-- CAO-XT WaWi-Modul – Datenbankschema Phase 1
-- Tabellenpräfix: XT_WAWI_
--
-- CAO-Faktura-Tabellen (ohne Präfix) werden read-only genutzt:
--   ARTIKEL, WARENGRUPPEN, MENGENEINHEIT, ARTIKEL_PREIS
--
-- GoBD §146 Abs. 4 AO:
--   Buchungsrelevante Tabellen tragen created_at / created_by.
--   Abgeschlossene Einträge werden NICHT geändert oder gelöscht
--   (append-only; soft-close via GUELTIG_BIS).
--
-- Beträge: immer als Integer-Cent (INT), kein DECIMAL für Geld.
-- ============================================================


-- ── Preishistorie (append-only, GoBD-Audit-Trail) ─────────────────────────────
--
-- Zentrale Tabelle für alle WaWi-verwalteten Verkaufspreise.
-- Jeder Preis wird mit Gültigkeitszeitraum gespeichert.
-- Änderungen erzeugen einen neuen Datensatz; der Vorgänger erhält
-- GUELTIG_BIS = gueltig_ab - 1 Tag (kein inhaltliches UPDATE).
--
-- Preisebenen:
--   1 = Großhandel / Wiederverkäufer
--   2 = Stammkunden
--   3 = Mitarbeiter
--   4 = Reserve
--   5 = Standard / Barverkauf (analog CAO VK5B)
--
CREATE TABLE IF NOT EXISTS XT_WAWI_PREISHISTORIE (
    REC_ID           INT          AUTO_INCREMENT PRIMARY KEY,
    ARTNUM           VARCHAR(20)  NOT NULL          COMMENT 'Artikelnummer (FK ARTIKEL.ARTNUM, read via JOIN)',
    PREISEBENE       TINYINT      NOT NULL DEFAULT 5 COMMENT '1–5 analog CAO VK1B–VK5B',
    PREIS_BRUTTO_CT  INT          NOT NULL           COMMENT 'Bruttopreis in Cent (kein DECIMAL)',
    GUELTIG_AB       DATE         NOT NULL           COMMENT 'Preis gültig ab',
    GUELTIG_BIS      DATE         NULL               COMMENT 'Preis gültig bis (NULL = unbefristet)',
    KOMMENTAR        VARCHAR(500) NULL               COMMENT 'Freitext-Begründung der Preisänderung',
    -- GoBD-Pflichtfelder
    CREATED_AT       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'Erfassungszeitpunkt (unveränderlich)',
    CREATED_BY       VARCHAR(100) NOT NULL           COMMENT 'Benutzername (aus MITARBEITER, unveränderlich)',

    INDEX idx_artnum_ebene (ARTNUM, PREISEBENE),
    INDEX idx_gueltig_ab   (GUELTIG_AB),
    INDEX idx_created_at   (CREATED_AT)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='WaWi Preishistorie – append-only, GoBD-konform';


-- ── VK-Preisgruppen ───────────────────────────────────────────────────────────
--
-- Konfigurationstabelle: Beschreibung und Standard-Preisebene je Kundengruppe.
-- Wird von der Kassen-App für die Preisebenenauswahl pro Kunde genutzt.
--
CREATE TABLE IF NOT EXISTS XT_WAWI_PREISGRUPPEN (
    REC_ID       INT          AUTO_INCREMENT PRIMARY KEY,
    EBENE        TINYINT      NOT NULL UNIQUE COMMENT '1–5, analog CAO VK1B–VK5B',
    BEZEICHNUNG  VARCHAR(100) NOT NULL        COMMENT 'z.B. "Stammkunde", "Mitarbeiter", "Standard"',
    AKTIV        TINYINT(1)   NOT NULL DEFAULT 1,
    SORT         INT          NOT NULL DEFAULT 0,
    -- GoBD-Pflichtfelder
    CREATED_AT   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CREATED_BY   VARCHAR(100) NOT NULL DEFAULT 'system'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='VK-Preisgruppen (Stammdaten)';


-- ── Stammdaten-Seed: Standard-Preisgruppen ────────────────────────────────────
INSERT IGNORE INTO XT_WAWI_PREISGRUPPEN (EBENE, BEZEICHNUNG, AKTIV, SORT, CREATED_BY)
VALUES
    (1, 'Großhandel / Wiederverkäufer', 0, 10, 'system'),
    (2, 'Stammkunden',                  0, 20, 'system'),
    (3, 'Mitarbeiter',                  1, 30, 'system'),
    (4, 'Reserve',                      0, 40, 'system'),
    (5, 'Standard / Barverkauf',        1,  0, 'system');


-- ── Hinweise für Schema-Erweiterungen ─────────────────────────────────────────
-- Da dieses Skript nur CREATE TABLE IF NOT EXISTS enthält, werden neue Spalten
-- per separatem ALTER TABLE hinzugefügt (analog kasse-app/DECISIONS.md):
--
--   ALTER TABLE XT_WAWI_PREISHISTORIE ADD COLUMN QUELLE VARCHAR(20) NULL AFTER KOMMENTAR;
--
-- Niemals bestehende Spalten umbenennen oder löschen (GoBD-Pflicht, Audit-Trail).
