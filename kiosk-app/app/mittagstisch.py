"""
Mittagstisch-Admin: Lesen/Schreiben des Google Sheets via gspread.

Sheet-Struktur (je Tab, z.B. "KW13_2026"):
  A1          : "Wochenplan Mittagstisch"
  A3:C7       : Datum | Wochentag | Gericht  (Montag–Freitag)
  A9, C9      : "Außerdem täglich:" | Text
  A10, C10    : "Jetzt neu:"        | Text
  A12         : Telefon (fest)
  A13         : Hinweis (fest)

Konfig-Quellen (erste greift):
  1. DORFKERN_KONFIG (Admin-App -> Stammdaten -> Mittagstisch)
       mittagstisch.spreadsheet_id   STRING
       mittagstisch.credentials_json SECRET (Service-Account-JSON als Text)
  2. config_local.py (MITTAGSTISCH_SPREADSHEET_ID,
                      MITTAGSTISCH_CREDENTIALS_FILE)
"""
import json
import os
from datetime import date, timedelta

import gspread
from google.oauth2.service_account import Credentials

# ── Fallback-Konfiguration ───────────────────────────────────

SPREADSHEET_ID   = "<SPREADSHEET_ID>"   # Google Sheets ID aus der URL
CREDENTIALS_FILE = os.path.join(
    os.path.dirname(__file__),
    "<credentials>.json"                # Service-Account-Key (NICHT in Git!)
)

# Lokale Overrides aus config_local.py (nicht in git)
try:
    from config_local import MITTAGSTISCH_SPREADSHEET_ID as SPREADSHEET_ID        # noqa: F811
    from config_local import MITTAGSTISCH_CREDENTIALS_FILE as CREDENTIALS_FILE    # noqa: F811
except ImportError:
    pass
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _db_konfig():
    """Liest Mittagstisch-Konfig aus DORFKERN_KONFIG.

    Liefert ``(spreadsheet_id, credentials_dict_or_none)``. Fehler
    (DB nicht erreichbar, Modul nicht importierbar) werden in leere
    Werte uebersetzt; Aufrufer faellt dann auf config_local zurueck.
    """
    try:
        from common import konfig as _k
    except Exception:
        return '', None
    sid = _k.get('mittagstisch.spreadsheet_id', default=None) or ''
    raw = _k.get('mittagstisch.credentials_json', default=None)
    cd = None
    if raw:
        try:
            cd = json.loads(raw)
        except (TypeError, ValueError):
            cd = None
    return sid.strip(), cd


def _aktive_spreadsheet_id() -> str:
    """DB zuerst, dann config_local-Wert. '' wenn nichts konfiguriert."""
    db_sid, _ = _db_konfig()
    if db_sid:
        return db_sid
    return SPREADSHEET_ID or ''

# Feste Zeilennummern
_Z_TITEL    = 1
_Z_MO       = 3   # Montag – Freitag: Zeilen 3–7
_Z_FR       = 7
_Z_TAEGLICH = 9
_Z_NEU      = 10
_Z_TEL      = 12
_Z_HINWEIS  = 13

WOCHENTAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag"]
TELEFON    = "Vorbestellungen: 08847 - 69 56 156"
HINWEIS    = "Angebot immer nur solange der Vorrat reicht. Änderungen vorbehalten."


# ── Hilfsfunktionen ───────────────────────────────────────────

class MittagstischNichtKonfiguriert(RuntimeError):
    """Mittagstisch ist (noch) nicht eingerichtet.

    Wird geworfen, wenn Spreadsheet-ID oder Google-Service-Account-
    Credentials fehlen/ungueltig sind. Der Aufrufer (View) faengt das
    ab und zeigt eine freundliche Meldung statt eines 500ers.
    """


def pruefe_konfiguration() -> None:
    """Wirft MittagstischNichtKonfiguriert, wenn etwas Pflichtiges fehlt.

    Zentral aufgerufen, BEVOR auf Google Sheets zugegriffen wird —
    fehlende Konfig soll keinen Internal Server Error verursachen.
    """
    if not _aktive_spreadsheet_id():
        raise MittagstischNichtKonfiguriert(
            "Es ist keine Google-Tabelle (Spreadsheet-ID) hinterlegt. "
            "Eintragen unter Admin → Stammdaten → Mittagstisch "
            "(mittagstisch.spreadsheet_id).")
    _, db_cred = _db_konfig()
    if db_cred is None and not os.path.isfile(CREDENTIALS_FILE):
        raise MittagstischNichtKonfiguriert(
            "Es sind keine Google-Service-Account-Credentials hinterlegt. "
            "Eintragen unter Admin → Stammdaten → Mittagstisch "
            "(mittagstisch.credentials_json).")


def _gc():
    """gspread-Client. Credentials-Prioritaet: DB > Datei (config_local).

    Aus der DB kommt ein dict (Service-Account-JSON parsed), verwendet
    per ``from_service_account_info``. Sonst Fallback auf
    ``from_service_account_file`` wie frueher.

    Fehlende/ungueltige Credentials werden in
    ``MittagstischNichtKonfiguriert`` uebersetzt — KEIN roher
    FileNotFoundError/ValueError nach aussen.
    """
    _, db_cred = _db_konfig()
    try:
        if db_cred is not None:
            creds = Credentials.from_service_account_info(
                db_cred, scopes=SCOPES)
        else:
            creds = Credentials.from_service_account_file(
                CREDENTIALS_FILE, scopes=SCOPES)
    except (FileNotFoundError, ValueError, KeyError) as exc:
        raise MittagstischNichtKonfiguriert(
            f"Google-Credentials fehlen oder sind ungueltig: {exc}") from exc
    return gspread.authorize(creds)


def kw_name(montag: date) -> str:
    """Tab-Name für eine Woche: 'KW13_2026'."""
    kw = montag.isocalendar()[1]
    return f"KW{kw:02d}_{montag.year}"


def montag_der_woche(d: date | None = None) -> date:
    """Montag der Woche von d (Standard: heute)."""
    if d is None:
        d = date.today()
    return d - timedelta(days=d.weekday())


def _datum_str(d: date) -> str:
    """Formatiert ein Datum als '23.03.' (kein führende Null beim Tag)."""
    return f"{d.day}.{d.month:02d}."


def _lesen(ws) -> dict:
    """Liest alle relevanten Zellen eines Wochenblatts in einem Aufruf."""
    alle = ws.get_all_values()

    def z(zeile, spalte):   # 1-basiert → 0-basiert
        r, c = zeile - 1, spalte - 1
        if r < len(alle) and c < len(alle[r]):
            return alle[r][c].strip()
        return ""

    tage = [
        {"datum": z(_Z_MO + i, 1), "tag": z(_Z_MO + i, 2), "gericht": z(_Z_MO + i, 3)}
        for i in range(5)
    ]
    return {
        "tage":      tage,
        "taeglich":  z(_Z_TAEGLICH, 3),
        "jetzt_neu": z(_Z_NEU, 3),
    }


def _schreiben(ws, montag: date, daten: dict):
    """Schreibt alle Wochendaten per Batch-Update (2 API-Aufrufe)."""
    tage_werte = []
    for i in range(5):
        tag_datum = montag + timedelta(days=i)
        gericht   = ""
        if i < len(daten.get("tage", [])):
            gericht = daten["tage"][i].get("gericht", "")
        tage_werte.append([_datum_str(tag_datum), WOCHENTAGE[i], gericht])

    ws.batch_update([
        {"range": f"A{_Z_TITEL}",                    "values": [["Wochenplan Mittagstisch"]]},
        {"range": f"A{_Z_MO}:C{_Z_FR}",             "values": tage_werte},
        {"range": f"A{_Z_TAEGLICH}:C{_Z_TAEGLICH}", "values": [["Außerdem täglich:", "", daten.get("taeglich", "")]]},
        {"range": f"A{_Z_NEU}:C{_Z_NEU}",           "values": [["Jetzt neu:", "",        daten.get("jetzt_neu", "")]]},
        {"range": f"A{_Z_TEL}",                      "values": [[TELEFON]]},
        {"range": f"A{_Z_HINWEIS}",                  "values": [[HINWEIS]]},
    ])


# ── Öffentliche API ───────────────────────────────────────────

def woche_laden(montag: date) -> dict | None:
    """Lädt eine Woche. Gibt None zurück wenn der Tab nicht existiert."""
    gc = _gc()
    ss = gc.open_by_key(_aktive_spreadsheet_id())
    try:
        ws = ss.worksheet(kw_name(montag))
        return _lesen(ws)
    except gspread.WorksheetNotFound:
        return None


def woche_laden_oder_anlegen(montag: date) -> dict:
    """
    Lädt eine Woche oder legt sie neu an.
    Beim Anlegen werden die Inhalte der Vorwoche als Vorlage kopiert.
    """
    gc = _gc()
    ss = gc.open_by_key(_aktive_spreadsheet_id())
    name = kw_name(montag)

    try:
        return _lesen(ss.worksheet(name))
    except gspread.WorksheetNotFound:
        pass

    # Vorwoche als Vorlage laden
    vorwoche = montag - timedelta(weeks=1)
    try:
        vorlage = _lesen(ss.worksheet(kw_name(vorwoche)))
    except gspread.WorksheetNotFound:
        vorlage = {
            "tage":      [{"gericht": ""} for _ in range(5)],
            "taeglich":  "",
            "jetzt_neu": "",
        }

    ws = ss.add_worksheet(title=name, rows=20, cols=5)
    _schreiben(ws, montag, vorlage)
    return _lesen(ws)


def woche_speichern(montag: date, daten: dict):
    """Speichert eine Woche in Sheets. Legt den Tab an falls er nicht existiert."""
    gc = _gc()
    ss = gc.open_by_key(_aktive_spreadsheet_id())
    name = kw_name(montag)

    try:
        ws = ss.worksheet(name)
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title=name, rows=20, cols=5)

    _schreiben(ws, montag, daten)
