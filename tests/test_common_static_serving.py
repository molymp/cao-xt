"""
Tests fuer common/static_serving.py – /common-static/<datei>-Route.
"""
import os
import sys
import unittest

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, _REPO_ROOT)


class TestCommonStatic(unittest.TestCase):

    def _app(self, url_prefix='/common-static'):
        from flask import Flask
        from common.static_serving import register_common_static
        app = Flask(__name__)
        app.secret_key = 'test'
        register_common_static(app, url_prefix=url_prefix)
        return app

    def test_dorfkern_css_wird_geliefert(self):
        app = self._app()
        with app.test_client() as c:
            r = c.get('/common-static/dorfkern.css')
            self.assertEqual(r.status_code, 200)
            # Content sollte CSS-Variablen enthalten
            body = r.data.decode('utf-8')
            self.assertIn('--bg-dunkel', body)
            self.assertIn('.card', body)

    def test_dorfkern_admin_css(self):
        app = self._app()
        with app.test_client() as c:
            r = c.get('/common-static/dorfkern-admin.css')
            self.assertEqual(r.status_code, 200)
            body = r.data.decode('utf-8')
            # Admin-spezifische Layout-Werte. Themes selbst liegen in
            # dorfkern.css; Admin hat KEIN eigenes Farbschema mehr.
            self.assertIn('--schatten-stark', body)
            self.assertIn('--bg-karte', body)
            self.assertIn('--radius-klein', body)

    def test_dorfkern_css_hat_alle_drei_themes(self):
        app = self._app()
        with app.test_client() as c:
            body = c.get('/common-static/dorfkern.css').data.decode('utf-8')
        for theme in ['dorfkern-light', 'dorfkern-dark', 'dorfkern-gruen']:
            self.assertIn(f'[data-theme="{theme}"]', body,
                          f'Theme {theme} fehlt in dorfkern.css')

    def test_dorfkern_css_nutzt_offizielle_brand_tokens(self):
        """Sanity: die shared CSS enthaelt die offiziellen Dorfkern-Farben
        (aus common/brand/dorfkern-logo.js / dk-brand.jsx)."""
        app = self._app()
        with app.test_client() as c:
            body = c.get('/common-static/dorfkern.css').data.decode('utf-8')
        for hex_wert in ['#141414', '#f2ede3', '#b65c3a', '#d9dcc9']:
            self.assertIn(hex_wert, body,
                          f'Offizielles Brand-Token {hex_wert} fehlt')

    def test_fehlende_datei_gibt_404(self):
        app = self._app()
        with app.test_client() as c:
            r = c.get('/common-static/gibts-nicht.css')
            self.assertEqual(r.status_code, 404)

    def test_anderer_url_prefix(self):
        app = self._app(url_prefix='/shared')
        with app.test_client() as c:
            self.assertEqual(c.get('/shared/dorfkern.css').status_code, 200)
            self.assertEqual(c.get('/common-static/dorfkern.css').status_code,
                             404)

    def test_doppelte_registrierung_ist_safe(self):
        """Zweites register_common_static() auf der selben App wirft nicht."""
        from flask import Flask
        from common.static_serving import register_common_static
        app = Flask(__name__)
        app.secret_key = 'test'
        register_common_static(app)
        register_common_static(app)   # darf nicht werfen
        with app.test_client() as c:
            self.assertEqual(c.get('/common-static/dorfkern.css').status_code,
                             200)


if __name__ == '__main__':
    unittest.main()
