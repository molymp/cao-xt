"""
CAO-XT WaWi-Modul – Warenwirtschaft.

Registrierung:

    from modules.wawi import create_blueprint
    app.register_blueprint(create_blueprint(), url_prefix='/wawi')

Hinweis: Der Blueprint wird lazy geladen, damit der Import von
``modules.wawi.personal`` (oder anderer Sub-Pakete) nicht davon abhaengt,
dass ``modules/wawi/`` selbst auf ``sys.path`` liegt.
"""


def create_blueprint():
    from .routes import bp
    return bp
