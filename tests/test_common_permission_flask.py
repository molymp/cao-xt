"""
Tests fuer common/permission.py :: flask_helpers().

Nutzt eine Wegwerf-Flask-App im Speicher, stubbt hat_recht().
"""
import os
import sys
import types
import unittest

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, _REPO_ROOT)


def _lade_permission_mit_stub_hat_recht(hat_recht_impl):
    """Laedt common.permission mit einer gestubbten hat_recht-Funktion."""
    # Echtes common.db muss nicht importieren – permission greift nur in
    # hat_recht/set/loesche drauf zu. Wir stubben common.db als Modul.
    fake_db = types.ModuleType('common.db')
    fake_db.get_db = lambda: None
    fake_db.get_db_transaction = lambda: None
    sys.modules.pop('common.db', None)
    sys.modules['common.db'] = fake_db

    # Jetzt permission echt laden und dann hat_recht monkeypatchen
    sys.modules.pop('common.permission', None)
    from common import permission as perm  # noqa: E402
    perm.hat_recht = hat_recht_impl  # type: ignore[attr-defined]
    return perm


class TestFlaskHelpers(unittest.TestCase):

    def setUp(self):
        # Kontrollierbare hat_recht-Stub
        self.aufrufe = []

        def stub(ma_id, key, recht='BEIDES'):
            self.aufrufe.append((ma_id, key, recht))
            # Testspezifische Regel: ma_id=1 darf alles;
            # ma_id=2 nur 'kasse.zugriff';
            # ma_id=3 nur 'orga.schichtplan' mit LESEN
            if ma_id == 1:
                return True
            if ma_id == 2:
                return key == 'kasse.zugriff'
            if ma_id == 3:
                return key == 'orga.schichtplan' and recht == 'LESEN'
            return False

        self.perm = _lade_permission_mit_stub_hat_recht(stub)

    def _make_app(self):
        from flask import Flask
        app = Flask(__name__)
        app.secret_key = 'test'
        require_permission, ctx = self.perm.flask_helpers()
        app.context_processor(ctx)

        @app.route('/')
        def index():
            return 'home'

        @app.route('/kasse/storno')
        @require_permission('kasse.storno')
        def storno():
            return 'storno-ok'

        @app.route('/kasse/zugriff')
        @require_permission('kasse.zugriff')
        def zugriff():
            return 'zugriff-ok'

        @app.route('/schicht-lesen')
        @require_permission('orga.schichtplan', 'LESEN')
        def schicht_lesen():
            return 'schicht-lesen-ok'

        @app.route('/schicht-pflegen')
        @require_permission('orga.schichtplan', 'PFLEGEN')
        def schicht_pflegen():
            return 'schicht-pflegen-ok'

        @app.route('/api/sensitive')
        @require_permission('kasse.storno')
        def api_sensitive():
            return {'ok': True}

        @app.route('/template-test')
        def tmpl():
            # Rendert Template inline, damit hat_recht im Context ist
            from flask import render_template_string
            return render_template_string(
                "{% if hat_recht('kasse.zugriff') %}ZUG{% endif %}"
                "{% if hat_recht('orga.schichtplan','PFLEGEN') %}PFL{% endif %}")

        return app

    def test_ohne_session_ma_id_redirect(self):
        app = self._make_app()
        with app.test_client() as c:
            r = c.get('/kasse/storno')
            self.assertEqual(r.status_code, 302)
            self.assertEqual(r.headers['Location'], '/')

    def test_ma_darf_route(self):
        app = self._make_app()
        with app.test_client() as c:
            with c.session_transaction() as s:
                s['ma_id'] = 1
            r = c.get('/kasse/storno')
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.data, b'storno-ok')

    def test_ma_darf_nicht_redirect(self):
        app = self._make_app()
        with app.test_client() as c:
            with c.session_transaction() as s:
                s['ma_id'] = 2     # hat nur kasse.zugriff
            r = c.get('/kasse/storno')   # braucht kasse.storno
            self.assertEqual(r.status_code, 302)
            r2 = c.get('/kasse/zugriff')
            self.assertEqual(r2.status_code, 200)

    def test_api_route_gibt_json_403(self):
        """/api/* bekommt JSON statt Redirect."""
        app = self._make_app()
        with app.test_client() as c:
            with c.session_transaction() as s:
                s['ma_id'] = 2    # darf nicht storno
            r = c.get('/api/sensitive')
            self.assertEqual(r.status_code, 403)
            self.assertEqual(r.content_type, 'application/json')
            self.assertIn(b'kasse.storno', r.data)

    def test_lese_pflege_unterscheidung(self):
        app = self._make_app()
        with app.test_client() as c:
            with c.session_transaction() as s:
                s['ma_id'] = 3    # nur schichtplan mit LESEN
            self.assertEqual(c.get('/schicht-lesen').status_code,   200)
            self.assertEqual(c.get('/schicht-pflegen').status_code, 302)

    def test_jinja_hat_recht(self):
        app = self._make_app()
        with app.test_client() as c:
            with c.session_transaction() as s:
                s['ma_id'] = 2
            r = c.get('/template-test')
            # ma_id=2 darf nur kasse.zugriff -> 'ZUG', kein 'PFL'
            self.assertEqual(r.data, b'ZUG')

    def test_jinja_ohne_session(self):
        app = self._make_app()
        with app.test_client() as c:
            # Keine ma_id in Session
            r = c.get('/template-test')
            self.assertEqual(r.data, b'')


if __name__ == '__main__':
    unittest.main()
