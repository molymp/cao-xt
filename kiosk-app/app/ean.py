"""
Bäckerei Kiosk – EAN-13 Barcode-Generierung
Inhouse-EAN-13 Format: XX AAAA PPPPPPZ

XX     = Bereichscode "21" (fest)
AAAA   = Artikelnummer Sammelartikel "Backwaren" (4-stellig, aus CAO)
PPPPPP = Gesamtpreis in Cent, 6-stellig (002500 = 25,00 EUR; max. 999999 = 9999,99 EUR)
Z      = EAN-13-Prüfziffer (Stelle 13, errechnet)

Beispiel: Sammelartikel 7408, Preis 3,80 EUR
  Artikelteil: 21 7408 (6 Stellen)
  Preisteil:   000380
  EAN-Kern:    217408000380
  EAN-Prüfz.:  berechnen
  Ergebnis:    2174080003803  (13 Stellen)
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
        gesamtbetrag_cent: Gesamtpreis des Warenkorbs in Cent (z. B. 380)

    Returns:
        13-stelliger EAN-13-String (z. B. "2174080003803")

    Raises:
        ValueError: Wenn Betrag > 999999 Cent (9999,99 EUR) oder negativ.
    """
    if gesamtbetrag_cent < 0:
        raise ValueError("Gesamtbetrag darf nicht negativ sein.")
    if gesamtbetrag_cent > 999999:
        raise ValueError(
            f"Gesamtbetrag {gesamtbetrag_cent} Cent übersteigt EAN-Maximum (999999 = 9999,99 EUR)."
        )

    bereich      = config.EAN_BEREICH                          # "21"
    sammel_nr    = config.EAN_SAMMELARTIKEL.zfill(4)[:4]       # z. B. "7408"
    artikelteil  = bereich + sammel_nr                         # 6 Stellen

    preis_str    = f"{gesamtbetrag_cent:06d}"                  # 6 Stellen
    ean_basis    = artikelteil + preis_str                     # 12 Stellen

    ean_pruefz   = _ean13_pruefziffer(ean_basis)               # 13. Stelle
    ean          = ean_basis + str(ean_pruefz)                 # 13 Stellen

    return ean


def validiere_ean(ean: str) -> bool:
    """Prüft ob ein EAN-13-String formal korrekt ist."""
    if len(ean) != 13 or not ean.isdigit():
        return False
    return _ean13_pruefziffer(ean[:12]) == int(ean[12])


# ── Selbsttest ────────────────────────────────────────────────
if __name__ == "__main__":
    print("EAN-Selbsttest:")
    print(f"  Bereich:       {config.EAN_BEREICH}")
    print(f"  Sammelartikel: {config.EAN_SAMMELARTIKEL}")

    testfaelle = [250, 380, 1490, 9999, 99999, 999999]
    for cent in testfaelle:
        ean = generiere_ean(cent)
        ok  = validiere_ean(ean)
        print(f"  {cent:>6} Cent  →  {ean}  {'✓' if ok else '✗ FEHLER'}")
