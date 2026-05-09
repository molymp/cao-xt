"""
CAO-XT Orga-App – Datenbankverbindung (thin wrapper um common.db)

Initialisiert den gemeinsamen Connection Pool mit der Orga-Konfiguration
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

# Pool-Size 15: das Dashboard fuehrt pro Request 5 sequentielle Queries
# (Monatsumsatz, Tageseinnahmen, Vorgaenge, HACCP, Personal). Bei waitress
# Default 4 Threads + parallelen Tabs / Geraeten reicht der frueher genutzte
# Default 5 nicht — der Pool lief unter Last regelmaessig leer und
# Requests stauten sich in der waitress-Queue.
init_pool("orga_app_pool", pool_size=15, db_config={
    'host':     config.DB_HOST,
    'port':     config.DB_PORT,
    'name':     config.DB_NAME,
    'user':     config.DB_USER,
    'password': config.DB_PASSWORD,
})

# Alias: CFO-Berichte lesen aus derselben CAO-DB wie der Orga-Pool
get_cao_db = get_db
