"""
Bäckerei Kiosk – EAN-13 Barcode-Generierung
Inhouse-EAN-13 Format (CAO-konform):  XX AAAA Z PPPPP Z

XX    = Bereichscode "21" (fest)
AAAA  = Artikelnummer Sammelartikel "Backwaren" (4-stellig, aus CAO)
Z     = interne Artikelteil-Prüfziffer (Stelle 7, aus Stellen 1–6 berechnet)
PPPPP = Gesamtpreis in Cent, 5-stellig (00250 = 2,50 EUR;
        max. 99999 = 999,99 EUR)
Z     = EAN-13-Prüfziffer (Stelle 13, aus Stellen 1–12 berechnet)

Beispiel: Sammelartikel 7408, Preis 8,00 EUR
  Artikelbasis: 21 7408            (6 Stellen)
  Artikel-PZ:   2  (Stelle 7)
  Artikelteil:  217408 2           (7 Stellen)
  Preisteil:    00800              (5 Stellen)
  EAN-Basis:    217408200800       (12 Stellen)
  EAN-Prüfz.:   6
  Ergebnis:     2174082008006      (13 Stellen)
"""

import config


def _ean13_pruefziffer(zwolf_stellen: str) -> int:
    """
    Berechnet die EAN-13-Prüfziffer aus den ersten 12 Stellen.
    Gewichtung: ungerade Positionen ×1, gerade Positionen ×3.
    """
    if len(zwolf_stellen) != 12 or not zwolf_stellen.isdigit():
        raise ValueError(f"EAN-Basis muss genau 12 Ziffern sein: '{zwolf_stellen}'")
    summe = sum(
        int(z) * (3 if i % 2 == 1 else 1)
        for i, z in enumerate(zwolf_stellen)
    )
    return (10 - (summe % 10)) % 10


def _artikelteil_pruefziffer(sechs_stellen: str) -> int:
    """
    Berechnet die interne Prüfziffer für den Artikelteil (Stellen 1–6).
    Verwendet dieselbe EAN-Gewichtung auf die ersten 6 Stellen.
    (Per Praxistest an der CAO-Kasse verifiziert.)
    """
    if len(sechs_stellen) != 6 or not sechs_stellen.isdigit():
        raise ValueError(f"Artikelteil muss genau 6 Ziffern sein: '{sechs_stellen}'")
    summe = sum(
        int(z) * (3 if i % 2 == 1 else 1)
        for i, z in enumerate(sechs_stellen)
    )
    return (10 - (summe % 10)) % 10


def generiere_ean(gesamtbetrag_cent: int) -> str:
    """
    Generiert einen vollständigen Inhouse-EAN-13-Code für den Gesamtbetrag.

    Args:
        gesamtbetrag_cent: Gesamtpreis des Warenkorbs in Cent (z. B. 800).

    Returns:
        13-stelliger EAN-13-String (z. B. "2174082008006").

    Raises:
        ValueError: Wenn Betrag > 99999 Cent (999,99 EUR) oder negativ.
    """
    if gesamtbetrag_cent < 0:
        raise ValueError("Gesamtbetrag darf nicht negativ sein.")
    if gesamtbetrag_cent > 99999:
        raise ValueError(
            f"Gesamtbetrag {gesamtbetrag_cent} Cent übersteigt EAN-Maximum "
            f"(99999 = 999,99 EUR)."
        )

    bereich      = config.EAN_BEREICH                          # "21"
    sammel_nr    = config.EAN_SAMMELARTIKEL.zfill(4)[:4]       # z. B. "7408"
    artikelbasis = bereich + sammel_nr                         # 6 Stellen

    artikel_pruefz = _artikelteil_pruefziffer(artikelbasis)    # 7. Stelle
    artikelteil    = artikelbasis + str(artikel_pruefz)        # 7 Stellen

    preis_str    = f"{gesamtbetrag_cent:05d}"                  # 5 Stellen
    ean_basis    = artikelteil + preis_str                     # 12 Stellen

    ean_pruefz   = _ean13_pruefziffer(ean_basis)               # 13. Stelle
    ean          = ean_basis + str(ean_pruefz)                 # 13 Stellen

    return ean


def validiere_ean(ean: str) -> bool:
    """Prüft ob ein EAN-13-String formal korrekt ist (EAN-13-PZ + Artikelteil-PZ)."""
    if len(ean) != 13 or not ean.isdigit():
        return False
    if _ean13_pruefziffer(ean[:12]) != int(ean[12]):
        return False
    return _artikelteil_pruefziffer(ean[:6]) == int(ean[6])


# ── Selbsttest ────────────────────────────────────────────────
if __name__ == "__main__":
    print("EAN-Selbsttest:")
    print(f"  Bereich:       {config.EAN_BEREICH}")
    print(f"  Sammelartikel: {config.EAN_SAMMELARTIKEL}")

    testfaelle = [250, 380, 800, 1490, 9999, 99999]
    for cent in testfaelle:
        ean = generiere_ean(cent)
        ok  = validiere_ean(ean)
        print(f"  {cent:>6} Cent  →  {ean}  {'✓' if ok else '✗ FEHLER'}")
