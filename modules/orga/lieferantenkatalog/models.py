"""
Lieferantenkatalog – Speicher (stehendes Sortiment je Lieferant).

Eine Tabelle ``XT_LIEFERANTENKATALOG`` (InnoDB), eindeutig je
(LIEFERANT_KUERZEL, MARKE, LIEF_ART_NR). Re-Import ist ein UPSERT der
Datenfelder; die Benutzer-Markierungen (FLAG_BESTELLEN / FLAG_IN_STAMM)
und der STATUS bleiben dabei erhalten. Artikel, die nicht mehr in der
Datei vorkommen, werden auf STATUS='entfallen' gesetzt (nicht
gelöscht – Markierungen/Historie bleiben).
"""
from __future__ import annotations

from typing import Any

from common.db import get_db, get_db_transaction

from .parser_kramer import parse_kramer_xlsx


def schema_sicherstellen() -> None:
    """Legt ``XT_LIEFERANTENKATALOG`` an. Idempotent."""
    with get_db() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS XT_LIEFERANTENKATALOG (
              REC_ID            BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
              LIEFERANT_KUERZEL VARCHAR(20)   NOT NULL,
              CAO_LIEF_ID       INT           NULL,
              MARKE             VARCHAR(120)  NOT NULL DEFAULT '',
              LIEF_ART_NR       VARCHAR(60)   NOT NULL,
              KATEGORIE         VARCHAR(255)  NULL,
              KURZBESCHREIBUNG  VARCHAR(255)  NULL,
              ARTIKELNAME       VARCHAR(255)  NULL,
              NAME_LANG         VARCHAR(255)  NULL,
              GEBINDE           VARCHAR(120)  NULL,
              EK_NETTO          DECIMAL(12,4) NULL,
              UST_SATZ          DECIMAL(6,2)  NULL,
              VK_EMPF           DECIMAL(12,4) NULL,
              EAN               VARCHAR(20)   NULL,
              MENGE_MIN         DECIMAL(12,3) NULL,
              BESCHREIBUNG      TEXT          NULL,
              BILD_URL          VARCHAR(500)  NULL,
              FLAG_BESTELLEN    TINYINT(1)    NOT NULL DEFAULT 0,
              FLAG_IN_STAMM     TINYINT(1)    NOT NULL DEFAULT 0,
              STATUS            ENUM('aktiv','entfallen')
                                NOT NULL DEFAULT 'aktiv',
              DATEINAME         VARCHAR(255)  NULL,
              IMPORTIERT_AM     DATETIME      NULL,
              IMPORTIERT_VON    VARCHAR(50)   NULL,
              AKTUALISIERT_AM   DATETIME      NOT NULL
                                DEFAULT CURRENT_TIMESTAMP
                                ON UPDATE CURRENT_TIMESTAMP,
              UNIQUE KEY uq_lief_marke_art
                         (LIEFERANT_KUERZEL, MARKE, LIEF_ART_NR),
              KEY idx_lief (LIEFERANT_KUERZEL),
              KEY idx_flags (FLAG_BESTELLEN, FLAG_IN_STAMM)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
              COMMENT='Lieferantenkataloge: stehendes Sortiment je Lieferant'
        """)


_UPSERT = """
    INSERT INTO XT_LIEFERANTENKATALOG
      (LIEFERANT_KUERZEL, CAO_LIEF_ID, MARKE, LIEF_ART_NR,
       KATEGORIE, KURZBESCHREIBUNG, ARTIKELNAME, NAME_LANG, GEBINDE,
       EK_NETTO, UST_SATZ, VK_EMPF, EAN, MENGE_MIN, BESCHREIBUNG,
       BILD_URL, STATUS, DATEINAME, IMPORTIERT_AM, IMPORTIERT_VON)
    VALUES (%s,%s,%s,%s, %s,%s,%s,%s,%s, %s,%s,%s,%s,%s,%s,
            %s,'aktiv',%s,NOW(),%s)
    ON DUPLICATE KEY UPDATE
      CAO_LIEF_ID=VALUES(CAO_LIEF_ID),
      KATEGORIE=VALUES(KATEGORIE),
      KURZBESCHREIBUNG=VALUES(KURZBESCHREIBUNG),
      ARTIKELNAME=VALUES(ARTIKELNAME),
      NAME_LANG=VALUES(NAME_LANG),
      GEBINDE=VALUES(GEBINDE),
      EK_NETTO=VALUES(EK_NETTO),
      UST_SATZ=VALUES(UST_SATZ),
      VK_EMPF=VALUES(VK_EMPF),
      EAN=VALUES(EAN),
      MENGE_MIN=VALUES(MENGE_MIN),
      BESCHREIBUNG=VALUES(BESCHREIBUNG),
      BILD_URL=VALUES(BILD_URL),
      STATUS='aktiv',
      DATEINAME=VALUES(DATEINAME),
      IMPORTIERT_AM=VALUES(IMPORTIERT_AM),
      IMPORTIERT_VON=VALUES(IMPORTIERT_VON)
"""


def katalog_importieren(*, path: str, lieferant_kuerzel: str,
                         cao_lief_id: int | None = None,
                         dateiname: str = '',
                         ma_name: str = 'CAO-XT') -> dict[str, Any]:
    """Importiert ein Kramer-Excel als stehendes Sortiment (UPSERT;
    Benutzer-Flags bleiben). Returns Zusammenfassung."""
    schema_sicherstellen()
    blaetter = parse_kramer_xlsx(path)
    lk = (lieferant_kuerzel or '').strip()[:20]
    ma = (ma_name or 'CAO-XT')[:50]
    dn = (dateiname or '')[:255]

    gesamt = 0
    marken: list[str] = []
    art_keys: set[tuple[str, str]] = set()
    with get_db_transaction() as cur:
        for blatt in blaetter:
            marke = (blatt['marke'] or '')[:120]
            marken.append(marke)
            for p in blatt['positionen']:
                cur.execute(_UPSERT, (
                    lk, cao_lief_id, marke,
                    (p.get('lief_art_nr') or '')[:60],
                    (p.get('kategorie') or '')[:255],
                    (p.get('kurzbeschreibung') or '')[:255],
                    (p.get('artikelname') or '')[:255],
                    (p.get('name_lang') or '')[:255],
                    (p.get('gebinde') or '')[:120],
                    p.get('ek_netto'), p.get('ust_satz'),
                    p.get('vk_empf'),
                    (p.get('ean') or '')[:20],
                    p.get('menge_min'),
                    (p.get('beschreibung') or '') or None,
                    (p.get('bild_url') or '')[:500],
                    dn, ma,
                ))
                gesamt += 1
                art_keys.add((marke, (p.get('lief_art_nr') or '')[:60]))
        # In der Datei nicht mehr enthaltene Artikel = entfallen.
        entfallen = 0
        if art_keys:
            cur.execute(
                "SELECT REC_ID, MARKE, LIEF_ART_NR "
                "  FROM XT_LIEFERANTENKATALOG "
                " WHERE LIEFERANT_KUERZEL=%s AND STATUS='aktiv'",
                (lk,)
            )
            for r in cur.fetchall() or []:
                if (r['MARKE'], r['LIEF_ART_NR']) not in art_keys:
                    cur.execute(
                        "UPDATE XT_LIEFERANTENKATALOG "
                        "   SET STATUS='entfallen' WHERE REC_ID=%s",
                        (r['REC_ID'],)
                    )
                    entfallen += 1
    return {'ok': True, 'marken': sorted(set(marken)),
            'positionen': gesamt, 'entfallen': entfallen}


def lieferanten_mit_katalog() -> list[dict[str, Any]]:
    """Gruppierte Übersicht: je Lieferant Anzahl Artikel + Marken."""
    schema_sicherstellen()
    with get_db() as cur:
        cur.execute("""
            SELECT LIEFERANT_KUERZEL,
                   COUNT(*)                          AS n,
                   SUM(STATUS='aktiv')               AS aktiv,
                   SUM(FLAG_BESTELLEN=1)             AS markiert_best,
                   SUM(FLAG_IN_STAMM=1)              AS markiert_stamm,
                   MAX(IMPORTIERT_AM)                AS letzter_import
              FROM XT_LIEFERANTENKATALOG
             GROUP BY LIEFERANT_KUERZEL
             ORDER BY LIEFERANT_KUERZEL
        """)
        return list(cur.fetchall() or [])
