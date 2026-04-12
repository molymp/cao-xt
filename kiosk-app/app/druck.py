"""
Bäckerei Kiosk – Bondruck und Bon-Datengenerierung
Nur Standard-ESC/POS-Befehle die alle Thermal-Drucker unterstützen.
"""

import config
from db import get_db, cent_zu_euro_str
from common.druck.escpos import tcp_send
from datetime import datetime

# ── Zeichensatz-Tabelle: Umlaute → CP437 ─────────────────────
_UMLAUT_MAP = str.maketrans({
    'ä': 'ae', 'ö': 'oe', 'ü': 'ue',
    'Ä': 'Ae', 'Ö': 'Oe', 'Ü': 'Ue',
    'ß': 'ss',
    '€': 'EUR',
    '–': '-', '—': '-',
    '„': '"', '"': '"', '"': '"',
    '…': '...',
})

def _ascii(text: str) -> str:
    return text.translate(_UMLAUT_MAP)


def _bon_bytes(warenkorb_id, positionen, gesamtbetrag_cent,
               ean_barcode, terminal_nr, ist_kopie, zeitpunkt,
               bestell_nr=None, notiz=None) -> bytes:
    """
    Baut den kompletten Bon als einen Byte-Buffer.
    warenkorb_id = die Nummer die der Kunde auf dem Bildschirm gesehen hat.
    Wird EINMAL per socket.sendall() gesendet.
    """
    b = bytearray()

    def raw(data: bytes):
        b.extend(data)

    def text(s: str):
        b.extend(_ascii(s).encode('cp437', errors='replace'))

    # ── Reset ────────────────────────────────────────────────
    raw(b'\x1b\x40')              # ESC @ – Drucker zurücksetzen

    # ── Kopf ─────────────────────────────────────────────────
    raw(b'\x1b\x61\x01')          # ESC a 1 = zentriert
    raw(b'\x1b\x45\x01')          # ESC E 1 = Fettschrift an
    raw(b'\x1b\x21\x30')          # ESC ! 0x30 = doppelte Breite + Höhe
    text("Habacher Dorfladen\n")
    raw(b'\x1b\x21\x00')          # ESC ! 0x00 = Normalgröße
    raw(b'\x1b\x45\x00')          # ESC E 0 = Fettschrift aus

    text("------------------------------------------------\n")

    if ist_kopie:
        raw(b'\x1b\x45\x01')
        text("*** KOPIE ***\n")
        raw(b'\x1b\x45\x00')

    if bestell_nr:
        # Bestellnummer groß + fett (für Kassierbon einer Bestellung)
        raw(b'\x1b\x45\x01')          # Fett an
        raw(b'\x1b\x21\x30')          # doppelte Breite + Höhe
        text(f"{bestell_nr}\n")
        raw(b'\x1b\x21\x00')          # Normalgröße
        raw(b'\x1b\x45\x00')          # Fett aus
    else:
        # Bonnummer: Prefix normal, letzte 2 Ziffern fett + groß
        bon_str = str(warenkorb_id)
        prefix  = "Bon Nr: " + bon_str[:-2] if len(bon_str) > 2 else "Bon Nr: "
        suffix  = bon_str[-2:]
        text(prefix)
        raw(b'\x1b\x45\x01')          # Fett an
        raw(b'\x1b\x21\x30')          # doppelte Breite + Höhe
        text(suffix)
        raw(b'\x1b\x21\x00')          # Normalgröße
        raw(b'\x1b\x45\x00')          # Fett aus
        raw(b'\n')

    text(f"{zeitpunkt.strftime('%d.%m.%Y  %H:%M')}\n")
    text(f"Terminal: {terminal_nr}\n")
    text("------------------------------------------------\n")

    # ── Positionen ───────────────────────────────────────────
    raw(b'\x1b\x61\x00')          # ESC a 0 = linksbündig

    for pos in positionen:
        name  = _ascii(pos["name_snapshot"])
        menge = pos["menge"]
        ep    = _ascii(cent_zu_euro_str(pos["preis_snapshot_cent"]))
        gp    = _ascii(cent_zu_euro_str(pos["zeilen_betrag_cent"]))

        if menge > 1:
            b.extend(f"{name[:48]}\n".encode('cp437', errors='replace'))
            zeile2 = f"  {menge} x EP {ep}"
            b.extend(f"{zeile2:<38} {gp:>9}\n".encode('cp437', errors='replace'))
        else:
            b.extend(f"{name[:38]:<38} {gp:>9}\n".encode('cp437', errors='replace'))
            b.extend(f"  EP {ep}\n".encode('cp437', errors='replace'))

    # ── Gesamt ───────────────────────────────────────────────
    text("================================================\n")
    raw(b'\x1b\x61\x02')          # ESC a 2 = rechtsbündig
    raw(b'\x1b\x45\x01')          # Fett an
    text(f"Gesamt: {cent_zu_euro_str(gesamtbetrag_cent)}\n")
    raw(b'\x1b\x45\x00')          # Fett aus
    raw(b'\x1b\x61\x00')          # linksbündig
    raw(b'\n')

    # ── Notiz ────────────────────────────────────────────────
    if notiz:
        text("------------------------------------------------\n")
        raw(b'\x1b\x45\x01')
        text("Notiz:\n")
        raw(b'\x1b\x45\x00')
        text(f"{_ascii(notiz[:80])}\n")

    # ── Barcode ──────────────────────────────────────────────
    raw(b'\x1b\x61\x01')          # zentriert
    text("Bitte an der Kasse scannen:\n")

    ean_str  = ean_barcode[:13].ljust(13, '0')
    ean_data = ean_str.encode('ascii')

    raw(b'\x1d\x68\x50')          # GS h 80  – Barcode-Höhe 80 Punkte
    raw(b'\x1d\x77\x02')          # GS w 2   – Modulbreite
    raw(b'\x1d\x48\x02')          # GS H 2   – Ziffern unterhalb
    raw(b'\x1d\x6b\x43')          # GS k 0x43 – EAN-13, neues Format
    raw(bytes([len(ean_data)]))
    raw(ean_data)
    raw(b'\n')                     # Puffer leeren

    raw(b'\n\n\n\n\n\n')            # 6 Leerzeilen vor Schnitt

    # ── Schnitt ──────────────────────────────────────────────
    raw(b'\x1d\x56\x01')          # GS V 1 = Teilschnitt

    return bytes(b)


def _sende_an_drucker(terminal_nr: int, daten: bytes):
    """Sendet alle Bytes in EINEM TCP-Write."""
    with get_db() as cursor:
        cursor.execute(
            """SELECT d.ip_adresse, d.port
               FROM XT_KIOSK_TERMINAL_DRUCKER td
               JOIN XT_KIOSK_DRUCKER d ON d.id = td.drucker_id
               WHERE td.terminal_nr = %s AND d.aktiv = 1""",
            (terminal_nr,)
        )
        row = cursor.fetchone()
        if not row:
            cursor.execute(
                "SELECT ip_adresse, port FROM XT_KIOSK_DRUCKER WHERE standard=1 AND aktiv=1 LIMIT 1"
            )
            row = cursor.fetchone()
        if not row:
            raise RuntimeError("Kein aktiver Drucker konfiguriert.")

    tcp_send(row["ip_adresse"], row["port"], daten, timeout=10)


def generiere_bon_bytes(
    warenkorb_id: int,
    positionen: list,
    gesamtbetrag_cent: int,
    ean_barcode: str,
    terminal_nr: int,
    ist_kopie: bool = False,
    zeitpunkt: datetime = None,
    bestell_nr: str = None,
    notiz: str = None,
) -> bytes:
    if zeitpunkt is None:
        zeitpunkt = datetime.now()
    return _bon_bytes(warenkorb_id, positionen, gesamtbetrag_cent,
                      ean_barcode, terminal_nr, ist_kopie, zeitpunkt,
                      bestell_nr=bestell_nr, notiz=notiz)


def generiere_bon_text(
    warenkorb_id: int,
    positionen: list,
    gesamtbetrag_cent: int,
    ean_barcode: str,
    terminal_nr: int,
    ist_kopie: bool = False,
    zeitpunkt: datetime = None,
) -> str:
    """Lesbare Textvorschau – verwendet warenkorb_id als Bonnummer."""
    if zeitpunkt is None:
        zeitpunkt = datetime.now()

    bon_str = str(warenkorb_id)

    zeilen = ["================================================",
              "            Habacher Dorfladen                ",
              "================================================"]
    if ist_kopie:
        zeilen += ["             *** KOPIE ***              ", "------------------------------------------------"]
    zeilen += [
        f"Bon Nr:   {bon_str}",
        f"Datum:    {zeitpunkt.strftime('%d.%m.%Y  %H:%M')}",
        f"Terminal: {terminal_nr}",
        "------------------------------------------------",
    ]
    for pos in positionen:
        name  = pos["name_snapshot"]
        menge = pos["menge"]
        ep    = cent_zu_euro_str(pos["preis_snapshot_cent"])
        gp    = cent_zu_euro_str(pos["zeilen_betrag_cent"])
        if menge > 1:
            zeilen.append(name[:48])
            zeile2 = f"  {menge} x EP {ep}"
            zeilen.append(f"{zeile2:<38} {gp:>9}")
        else:
            zeilen.append(f"{name[:38]:<38} {gp:>9}")
            zeilen.append(f"  EP {ep}")
    zeilen += [
        "================================================",
        f"Gesamt:  {cent_zu_euro_str(gesamtbetrag_cent):>10}",
        "================================================",
        f"EAN: {ean_barcode}",
        "Bitte an der Kasse scannen",
        "",
    ]
    return "\n".join(zeilen)


def drucke_bon(
    warenkorb_id: int,
    positionen: list,
    gesamtbetrag_cent: int,
    ean_barcode: str,
    terminal_nr: int,
    ist_kopie: bool = False,
    zeitpunkt: datetime = None,
):
    if zeitpunkt is None:
        zeitpunkt = datetime.now()
    daten = _bon_bytes(warenkorb_id, positionen, gesamtbetrag_cent,
                       ean_barcode, terminal_nr, ist_kopie, zeitpunkt)
    _sende_an_drucker(terminal_nr, daten)


def drucke_pickliste(
    bestellung: dict,
    positionen: list,
    terminal_nr: int,
    mit_preisen: bool = False,
    ean_barcode: str = None,
    bereits_bezahlt: bool = False,
    gesamt_hinweis: int = None,
    pause_hinweis: str = None,
    titel_ueberschrift: str = None,
    aenderung_cent: int = None,
) -> None:
    """
    Druckt eine Bestell-Pickliste.
    mit_preisen=True:      Einzelpreise + Gesamtbetrag werden ausgegeben
    ean_barcode:           EAN-13-Barcode am Ende (Zahlung bei Abholung)
    bereits_bezahlt:       Statt Barcode steht 'Bereits bezahlt' (Sofort-Zahler)
    gesamt_hinweis:        Betrag in Cent → zeigt 'Zahlung bei Abholung' + Betrag
    pause_hinweis:         Text → zeigt Pause-Hinweis (überschreibt alles andere)
    titel_ueberschrift:    Überschreibt den automatischen Titel
    aenderung_cent:        Zahlungsdifferenz-Block:
                             > 0 → 'Nachzahlung: €X' + Barcode
                             = 0 → 'Keine Nachzahlung'
                             < 0 → 'Auszuzahlender Betrag: €X' (kein Barcode)
    """
    b = bytearray()

    def raw(data: bytes):
        b.extend(data)

    def text(s: str):
        b.extend(_ascii(s).encode('cp437', errors='replace'))

    # ── Reset ────────────────────────────────────────────────
    raw(b'\x1b\x40')

    # ── Kopf ─────────────────────────────────────────────────
    raw(b'\x1b\x61\x01')          # zentriert
    raw(b'\x1b\x45\x01')          # Fett an
    raw(b'\x1b\x21\x30')          # doppelte Breite+Höhe
    text("Habacher Dorfladen\n")
    raw(b'\x1b\x21\x00')
    raw(b'\x1b\x45\x00')
    raw(b'\x1b\x45\x01')
    if pause_hinweis is not None:
        text("*** Bestellung pausiert ***\n")
    elif titel_ueberschrift:
        text(f"*** {_ascii(titel_ueberschrift)} ***\n")
    elif gesamt_hinweis is not None:
        text("*** Bestellbestaetigung ***\n")
    else:
        text("*** Pickliste fuer Bestellung ***\n")
    raw(b'\x1b\x45\x00')

    # Bestell-Nr (groß)
    raw(b'\x1b\x45\x01')
    raw(b'\x1b\x21\x30')
    text(f"{bestellung['bestell_nr']}\n")
    raw(b'\x1b\x21\x00')
    raw(b'\x1b\x45\x00')

    text("------------------------------------------------\n")

    # ── Kundendaten ──────────────────────────────────────────
    raw(b'\x1b\x61\x00')          # linksbündig
    text(f"Name:  {bestellung['name']}\n")
    if bestellung.get('telefon'):
        text(f"Tel:   {bestellung['telefon']}\n")

    # Datum / Wochentag
    if bestellung['typ'] == 'einmalig' and bestellung.get('abhol_datum'):
        d = bestellung['abhol_datum']
        datum_str = d.strftime('%d.%m.%Y') if hasattr(d, 'strftime') else str(d)
        text(f"Datum: {datum_str}\n")
    elif bestellung['typ'] == 'wiederkehrend' and bestellung.get('wochentag'):
        text(f"Jeden {bestellung['wochentag']}\n")
        if bestellung.get('start_datum'):
            sd = bestellung['start_datum']
            sd_str = sd.strftime('%d.%m.%Y') if hasattr(sd, 'strftime') else str(sd)
            text(f"Von:   {sd_str}\n")
        if bestellung.get('end_datum'):
            ed = bestellung['end_datum']
            ed_str = ed.strftime('%d.%m.%Y') if hasattr(ed, 'strftime') else str(ed)
            text(f"Bis:   {ed_str}\n")

    if bestellung.get('abhol_uhrzeit'):
        ut = bestellung['abhol_uhrzeit']
        if hasattr(ut, 'seconds'):          # timedelta von MariaDB
            h, m = divmod(ut.seconds // 60, 60)
            uhr_str = f"{h:02d}:{m:02d}"
        elif hasattr(ut, 'strftime'):
            uhr_str = ut.strftime('%H:%M')
        else:
            uhr_str = str(ut)[:5]
        text(f"Uhrzeit: {uhr_str} Uhr\n")

    text("------------------------------------------------\n")

    # ── Artikel ──────────────────────────────────────────────
    raw(b'\x1b\x45\x01')
    text("ARTIKEL:\n")
    raw(b'\x1b\x45\x00')

    gesamt_cent = 0
    for pos in positionen:
        menge     = pos['menge']
        name      = _ascii(pos['name_snapshot'])
        aenderung = pos.get('_aenderung')   # 'neu', 'entfernt' oder None

        if aenderung == 'entfernt':
            # Weggefallener Artikel: Menge 0
            # Negativer Betrag nur bei sofort-Zahlung (bereits bezahlter Betrag = Rückzahlung)
            orig_menge = pos.get('_orig_menge') or menge or 1
            raw(b'\x1b\x21\x10')
            b.extend(f"  0x  {name[:40]}\n".encode('cp437', errors='replace'))
            raw(b'\x1b\x21\x00')
            if mit_preisen and pos.get('_neg_betrag'):
                gp_neg = _ascii("-" + cent_zu_euro_str(orig_menge * pos['preis_cent']))
                b.extend(f"      {gp_neg:>10}\n".encode('cp437', errors='replace'))
        else:
            # Neuer oder unveränderter Artikel
            tag = "  NEU" if aenderung == 'neu' else ""
            raw(b'\x1b\x21\x10')
            b.extend(f"  {menge}x  {name[:40 - len(tag)]}{tag}\n".encode('cp437', errors='replace'))
            raw(b'\x1b\x21\x00')
            if mit_preisen:
                ep = _ascii(cent_zu_euro_str(pos['preis_cent']))
                gp = _ascii(cent_zu_euro_str(menge * pos['preis_cent']))
                gesamt_cent += menge * pos['preis_cent']
                if menge > 1:
                    b.extend(f"      EP {ep:<16} GP {gp:>9}\n".encode('cp437', errors='replace'))
                else:
                    b.extend(f"      {gp:>10}\n".encode('cp437', errors='replace'))

    if mit_preisen and gesamt_cent > 0:
        text("================================================\n")
        raw(b'\x1b\x61\x02')          # rechtsbündig
        raw(b'\x1b\x45\x01')          # Fett an
        text(f"Gesamt: {cent_zu_euro_str(gesamt_cent)}\n")
        raw(b'\x1b\x45\x00')
        raw(b'\x1b\x61\x00')          # linksbündig
    else:
        text("------------------------------------------------\n")

    # ── Notiz ────────────────────────────────────────────────
    if bestellung.get('notiz'):
        raw(b'\x1b\x45\x01')
        text("Notiz:\n")
        raw(b'\x1b\x45\x00')
        text(f"{bestellung['notiz'][:80]}\n")
        text("------------------------------------------------\n")

    # ── Zahlungsblock ─────────────────────────────────────────
    if pause_hinweis is not None:
        # Pause-Hinweis
        text("================================================\n")
        raw(b'\x1b\x61\x01')
        raw(b'\x1b\x45\x01')
        raw(b'\x1b\x21\x10')          # doppelte Höhe
        text(f"{_ascii(pause_hinweis)}\n")
        raw(b'\x1b\x21\x00')
        raw(b'\x1b\x45\x00')
        raw(b'\x1b\x61\x00')

    elif aenderung_cent is not None:
        # Differenz-Block: Nachzahlung / Keine / Auszahlung
        text("================================================\n")
        raw(b'\x1b\x61\x01')          # zentriert
        if aenderung_cent > 0:
            raw(b'\x1b\x45\x01')
            text("Nachzahlung:\n")
            raw(b'\x1b\x21\x30')      # doppelte Breite + Höhe
            text(f"{_ascii(cent_zu_euro_str(aenderung_cent))}\n")
            raw(b'\x1b\x21\x00')
            raw(b'\x1b\x45\x00')
            if ean_barcode:
                text("Bitte an der Kasse scannen:\n")
                ean_str  = ean_barcode[:13].ljust(13, '0')
                ean_data = ean_str.encode('ascii')
                raw(b'\x1d\x68\x50')
                raw(b'\x1d\x77\x02')
                raw(b'\x1d\x48\x02')
                raw(b'\x1d\x6b\x43')
                raw(bytes([len(ean_data)]))
                raw(ean_data)
                raw(b'\n')
        elif aenderung_cent == 0:
            raw(b'\x1b\x45\x01')
            text("Keine Nachzahlung\n")
            raw(b'\x1b\x45\x00')
        else:                          # aenderung_cent < 0 → Rückzahlung
            raw(b'\x1b\x45\x01')
            text("Auszuzahlender Betrag:\n")
            raw(b'\x1b\x21\x30')      # doppelte Breite + Höhe
            text(f"{_ascii(cent_zu_euro_str(-aenderung_cent))}\n")
            raw(b'\x1b\x21\x00')
            raw(b'\x1b\x45\x00')
        raw(b'\x1b\x61\x00')          # linksbündig

    elif gesamt_hinweis is not None:
        # Bestätigungsbon: Zahlung bei Abholung + Betrag
        text("================================================\n")
        raw(b'\x1b\x61\x01')
        raw(b'\x1b\x45\x01')
        text("Zahlung bei Abholung\n")
        raw(b'\x1b\x21\x30')
        text(f"{_ascii(cent_zu_euro_str(gesamt_hinweis))}\n")
        raw(b'\x1b\x21\x00')
        raw(b'\x1b\x45\x00')
        raw(b'\x1b\x61\x00')

    elif bereits_bezahlt:
        # Sofort-Zahler: kein Barcode nötig
        raw(b'\x1b\x61\x01')
        raw(b'\x1b\x45\x01')
        text("Bereits bezahlt\n")
        raw(b'\x1b\x45\x00')
        raw(b'\x1b\x61\x00')

    elif ean_barcode:
        # Normaler Barcode (Zahlung bei Abholung)
        raw(b'\x1b\x61\x01')
        text("Bitte an der Kasse scannen:\n")
        ean_str  = ean_barcode[:13].ljust(13, '0')
        ean_data = ean_str.encode('ascii')
        raw(b'\x1d\x68\x50')
        raw(b'\x1d\x77\x02')
        raw(b'\x1d\x48\x02')
        raw(b'\x1d\x6b\x43')
        raw(bytes([len(ean_data)]))
        raw(ean_data)
        raw(b'\n')
        raw(b'\x1b\x61\x00')

    # ── Footer ───────────────────────────────────────────────
    raw(b'\x1b\x61\x01')          # zentriert
    jetzt = datetime.now()
    text(f"Gedruckt: {jetzt.strftime('%d.%m.%Y %H:%M')}\n")

    raw(b'\n\n\n\n\n\n')            # 6 Leerzeilen vor Schnitt
    raw(b'\x1d\x56\x01')          # Teilschnitt

    _sende_an_drucker(terminal_nr, bytes(b))


def test_drucker(terminal_nr: int = None) -> bool:
    nr = terminal_nr or config.TERMINAL_NR
    with get_db() as cursor:
        cursor.execute(
            """SELECT d.ip_adresse, d.port
               FROM XT_KIOSK_TERMINAL_DRUCKER td
               JOIN XT_KIOSK_DRUCKER d ON d.id = td.drucker_id
               WHERE td.terminal_nr = %s AND d.aktiv = 1""",
            (nr,)
        )
        row = cursor.fetchone()
        if not row:
            cursor.execute(
                "SELECT ip_adresse, port FROM XT_KIOSK_DRUCKER WHERE standard=1 AND aktiv=1 LIMIT 1"
            )
            row = cursor.fetchone()
    if not row:
        return False
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        sock.connect((row["ip_adresse"], row["port"]))
        sock.close()
        return True
    except Exception:
        return False
