"""Konfiguration: Datenbankverbindung und Kontenplan (SKR03)."""

import configparser
from dataclasses import dataclass


@dataclass
class DatabaseConfig:
    host: str
    port: int
    database: str
    user: str
    password: str


@dataclass
class Kontenplan:
    # Wareneingangsskonten
    WE0:   int = 3200
    WE7:   int = 3300
    WE19:  int = 3400
    WE107: int = 3540
    # Warenausgangsskonten (Erlöskonten)
    WA0:  int = 8200
    WA7:  int = 8300
    WA19: int = 8400
    # Bilanzkonten
    Forderungen:       int = 1400
    Verbindlichkeiten: int = 1600
    Bank:        int = 1200
    Kasse:       int = 1000
    Geldtransit: int = 1360
    ECTransit:   int = 1361
    Gutscheine:  int = 1362
    # DATEV-Festschreibungskennzeichen (0 = nicht festgeschrieben)
    Festschreibungskennzeichen: int = 0


def load_db_config(path: str) -> DatabaseConfig:
    """Liest Datenbankverbindungsdaten aus einer INI-Datei (Format wie caoxt.ini)."""
    cfg = configparser.ConfigParser()
    cfg.read(path, encoding='utf-8')
    db = cfg['Datenbank']
    return DatabaseConfig(
        host=db['db_loc'],
        port=int(db.get('db_port', '3306')),
        database=db['db_name'],
        user=db['db_user'],
        password=db['db_pass'],
    )
