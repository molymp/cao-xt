"""
Bäckerei Kiosk – Datenbankverbindung (thin wrapper um common.db)

Initialisiert den gemeinsamen Connection Pool mit der Kiosk-Konfiguration
und re-exportiert alle benoetigten Symbole.
"""
import config  # setzt sys.path und laedt DB-Konfiguration

from common.db import (
    init_pool,
    get_db,
    get_db_transaction,
    cent_zu_euro_str,
    euro_zu_cent,
    test_verbindung,
)
from common.auth import mitarbeiter_login

init_pool("kiosk_pool", db_config={
    'host':     config.DB_HOST,
    'port':     config.DB_PORT,
    'name':     config.DB_NAME,
    'user':     config.DB_USER,
    'password': config.DB_PASSWORD,
})
