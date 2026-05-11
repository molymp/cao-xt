"""
Dorfkern Banking — Phase E.1 (Read-only Konten + Umsätze).

Liest direkt aus den Hibiscus-Tabellen, die im gleichen MariaDB-Schema
``cao_XT_DEV`` liegen (siehe project_zahlungsmanagement_hibiscus.md).
Tabellen-Konvention: lowercase ``konto``, ``umsatz``, ``sepasueb``,
``sepasuebbuchung``, ``empfaenger`` etc. — kollidieren nicht mit den
ALLCAPS-CAO-Tabellen.

Schreibvorgänge (SEPA-Anweisung, Auto-Match) folgen in Phase E.2/E.3
und gehen über Hibiscus' XML-RPC-API, nicht direkt per SQL — damit
HBCI-Übertragungen sauber durch die Hibiscus-Pipeline laufen.

Registrierung::

    from modules.orga.banking import create_blueprint
    app.register_blueprint(create_blueprint(), url_prefix='/orga/banking')
"""
from .routes import bp, create_blueprint  # noqa: F401
