"""
CAO-XT Orga-Modul – Warenwirtschaft.

Registrierung:

    from modules.orga import create_blueprint
    app.register_blueprint(create_blueprint(), url_prefix='/orga')

Hinweis: Der Blueprint wird lazy geladen, damit der Import von
``modules.orga.personal`` (oder anderer Sub-Pakete) nicht davon abhaengt,
dass ``modules/orga/`` selbst auf ``sys.path`` liegt.
"""


def create_blueprint():
    from .routes import bp
    return bp
