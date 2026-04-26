"""
Tests fuer ``orga-app/app/koppelkauf.py`` – die regelbasierten
Insights und die Margen-Berechnung. Nutzt Fixture-Daten ohne DB.
"""
import os
import sys
import unittest

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
_ORGA_APP  = os.path.join(_REPO_ROOT, 'orga-app', 'app')
for p in (_REPO_ROOT, _ORGA_APP):
    if p not in sys.path:
        sys.path.insert(0, p)

import koppelkauf as kk


def _basis_analyse(**overrides):
    """Minimale Analyse-Struktur ohne DB-Hits, mit sinnvollen Defaults."""
    base = {
        'aktion_umsatz': {'anzahl_bons': 142, 'stueckzahl': 187,
                          'brutto_umsatz': 933.0, 'tage': 7,
                          'bons_pro_tag': 20.3},
        'koppel_aktion': [],
        'perioden':      {},
        'interpretation': {'klasse': 'gut', 'uplift': 286.0, 'text': '...'},
        'margen':        None,
        'bon_wert':      None,
    }
    base.update(overrides)
    return base


class TestMargenAnalyse(unittest.TestCase):

    def test_rabatt_volumen_bei_normalem_aktionspreis(self):
        m = kk.margen_analyse(normalpreis=6.29, aktionspreis=4.99,
                                stueckzahl=187)
        self.assertAlmostEqual(m['rabatt_pro_stk'], 1.30, places=2)
        self.assertAlmostEqual(m['rabatt_volumen'], 243.10, places=2)
        self.assertAlmostEqual(m['aktion_brutto'], 933.13, places=2)

    def test_rabatt_volumen_zero_bei_gleichem_preis(self):
        m = kk.margen_analyse(normalpreis=5.0, aktionspreis=5.0,
                                stueckzahl=10)
        self.assertEqual(m['rabatt_pro_stk'], 0.0)
        self.assertEqual(m['rabatt_volumen'], 0.0)


class TestInsightsTop1Kopplung(unittest.TestCase):

    def test_etablierter_partner_ab_70_prozent(self):
        analyse = _basis_analyse(koppel_aktion=[
            {'bezeichnung': 'Bauernbrot Kruste', 'kopplungsrate': 72.0,
             'brutto_umsatz': 357.0, 'anzahl_bons': 102, 'stueckzahl': 102},
        ])
        ins = kk.insights_generieren(analyse)
        ll = next((i for i in ins if 'Bauernbrot' in i['titel']), None)
        self.assertIsNotNone(ll)
        self.assertEqual(ll['typ'], 'positiv')
        self.assertIn('etabliert', ll['titel'].lower())

    def test_buendel_zwischen_50_und_70_prozent(self):
        analyse = _basis_analyse(koppel_aktion=[
            {'bezeichnung': 'Brot', 'kopplungsrate': 55.0,
             'brutto_umsatz': 200.0, 'anzahl_bons': 78, 'stueckzahl': 78},
        ])
        ins = kk.insights_generieren(analyse)
        titel = ' '.join(i['titel'] for i in ins)
        self.assertIn('Brot', titel)
        self.assertIn('Buendel', titel)

    def test_keine_aussage_bei_unter_50_prozent(self):
        analyse = _basis_analyse(koppel_aktion=[
            {'bezeichnung': 'Was', 'kopplungsrate': 22.0,
             'brutto_umsatz': 50.0, 'anzahl_bons': 31, 'stueckzahl': 31},
        ])
        ins = kk.insights_generieren(analyse)
        self.assertFalse(any('Was' in i['titel'] for i in ins))


class TestInsightsHochpreisBegleiter(unittest.TestCase):

    def test_niedrige_quote_aber_hoher_umsatz(self):
        # Top-1 hat 70 % Quote, ein Hochpreis-Artikel im Top-3 hat nur
        # 28 % aber den hoechsten Umsatz – soll als 'zieht Bon-Wert
        # hoch' erkannt werden.
        analyse = _basis_analyse(koppel_aktion=[
            {'bezeichnung': 'Brot', 'kopplungsrate': 70.0,
             'brutto_umsatz': 300.0, 'anzahl_bons': 99, 'stueckzahl': 99},
            {'bezeichnung': 'Trauben', 'kopplungsrate': 41.0,
             'brutto_umsatz': 180.0, 'anzahl_bons': 58, 'stueckzahl': 58},
            {'bezeichnung': 'Riesling', 'kopplungsrate': 28.0,
             'brutto_umsatz': 320.0, 'anzahl_bons': 40, 'stueckzahl': 40},
        ])
        ins = kk.insights_generieren(analyse)
        # Hochpreis-Begleiter-Insight soll genannt sein
        bonwert_ins = [i for i in ins if 'zieht den Bon-Wert' in i['titel']]
        self.assertTrue(bonwert_ins)
        self.assertIn('Riesling', bonwert_ins[0]['titel'])


class TestInsightsNachzieheffekt(unittest.TestCase):

    def test_folgewoche_groesser_als_vorwoche(self):
        analyse = _basis_analyse(perioden={
            'vorwoche':   {'umsatz': {'anzahl_bons': 30}},
            'folgewoche': {'umsatz': {'anzahl_bons': 55}},
        })
        ins = kk.insights_generieren(analyse)
        self.assertTrue(any('profitiert nach' in i['titel'].lower() for i in ins))

    def test_kein_nachzieheffekt_wenn_folgewoche_kleiner(self):
        analyse = _basis_analyse(perioden={
            'vorwoche':   {'umsatz': {'anzahl_bons': 30}},
            'folgewoche': {'umsatz': {'anzahl_bons': 28}},
        })
        ins = kk.insights_generieren(analyse)
        self.assertFalse(any('profitiert nach' in i['titel'].lower() for i in ins))


class TestInsightsVorjahrUplift(unittest.TestCase):

    def test_aktion_deutlich_ueber_vorjahr_kw(self):
        analyse = _basis_analyse(perioden={
            'vorjahr_kw': {'umsatz': {'anzahl_bons': 29}},
        })
        # 142 vs 29 -> ca. +389%
        ins = kk.insights_generieren(analyse)
        self.assertTrue(any('Vorjahr lag deutlich' in i['titel'] for i in ins))


class TestInsightsRabattWarnung(unittest.TestCase):

    def test_warn_bei_hohem_rabatt_volumen(self):
        analyse = _basis_analyse(margen={
            'rabatt_volumen': 243.0, 'stueckzahl': 187,
        })
        ins = kk.insights_generieren(analyse)
        warns = [i for i in ins if i['typ'] == 'warn']
        self.assertTrue(warns)
        self.assertIn('243', warns[0]['text'])

    def test_kein_warn_unter_100_eur(self):
        analyse = _basis_analyse(margen={
            'rabatt_volumen': 30.0, 'stueckzahl': 20,
        })
        ins = kk.insights_generieren(analyse)
        self.assertFalse(any(i['typ'] == 'warn' for i in ins))


class TestInsightsBonWert(unittest.TestCase):

    def test_aktion_hebt_bon_wert(self):
        analyse = _basis_analyse(bon_wert={
            'mit_aktion_avg': 18.60, 'mit_aktion_anz': 142,
            'ohne_aktion_avg': 12.40, 'ohne_aktion_anz': 200,
            'delta_pct': 50.0,
        })
        ins = kk.insights_generieren(analyse)
        self.assertTrue(any('hebt den Bon-Wert' in i['titel'] for i in ins))

    def test_kein_insight_bei_kleinem_delta(self):
        analyse = _basis_analyse(bon_wert={
            'mit_aktion_avg': 14.0, 'mit_aktion_anz': 142,
            'ohne_aktion_avg': 12.4, 'ohne_aktion_anz': 200,
            'delta_pct': 12.9,
        })
        ins = kk.insights_generieren(analyse)
        self.assertFalse(any('hebt den Bon-Wert' in i['titel'] for i in ins))


class TestInsightsAktionUnterVorwoche(unittest.TestCase):
    """Aktion bringt weniger Bons als die Vorwoche."""

    def test_warn_wenn_aktion_unter_vorwoche(self):
        analyse = _basis_analyse(
            aktion_umsatz={'anzahl_bons': 18, 'stueckzahl': 22,
                           'brutto_umsatz': 77.0, 'tage': 7,
                           'bons_pro_tag': 2.6},
            perioden={
                'vorwoche': {'umsatz': {'anzahl_bons': 21}},
            },
        )
        ins = kk.insights_generieren(analyse)
        warns = [i for i in ins if i['typ'] == 'warn'
                                  and 'hinter der Vorwoche' in i['titel']]
        self.assertTrue(warns)
        self.assertIn('14', warns[0]['text'])  # ~14% Rueckgang

    def test_kein_warn_wenn_aktion_groesser(self):
        analyse = _basis_analyse(
            aktion_umsatz={'anzahl_bons': 30, 'stueckzahl': 35,
                           'brutto_umsatz': 150, 'tage': 7, 'bons_pro_tag': 4.3},
            perioden={'vorwoche': {'umsatz': {'anzahl_bons': 21}}},
        )
        ins = kk.insights_generieren(analyse)
        self.assertFalse(any('hinter der Vorwoche' in i['titel'] for i in ins))


class TestInsightsFolgewocheEinbruch(unittest.TestCase):

    def test_einbruch_unter_70_prozent(self):
        # Vorwoche 21, Folgewoche 12 -> 12 < 21*0.7=14.7 -> Einbruch
        analyse = _basis_analyse(perioden={
            'vorwoche':   {'umsatz': {'anzahl_bons': 21}},
            'folgewoche': {'umsatz': {'anzahl_bons': 12}},
        })
        ins = kk.insights_generieren(analyse)
        self.assertTrue(any('Folgewoche-Einbruch' in i['titel'] for i in ins))

    def test_kein_einbruch_bei_stabiler_folgewoche(self):
        analyse = _basis_analyse(perioden={
            'vorwoche':   {'umsatz': {'anzahl_bons': 21}},
            'folgewoche': {'umsatz': {'anzahl_bons': 18}},
        })
        ins = kk.insights_generieren(analyse)
        self.assertFalse(any('Folgewoche-Einbruch' in i['titel'] for i in ins))


class TestInsightsRabattOhneWirkung(unittest.TestCase):

    def test_warn_bei_hohem_rabatt_und_geringem_uplift(self):
        # 19% Rabatt, Aktion 18 vs Schnitt (21+12+23+25)/4=20.25 -> -11%
        analyse = _basis_analyse(
            aktion_umsatz={'anzahl_bons': 18, 'stueckzahl': 22,
                           'brutto_umsatz': 77.0, 'tage': 7, 'bons_pro_tag': 2.6},
            margen={'normal_pro_stk': 4.29, 'aktion_pro_stk': 3.49,
                    'rabatt_pro_stk': 0.80, 'stueckzahl': 22.0,
                    'rabatt_volumen': 17.6, 'normal_brutto': 94.4,
                    'aktion_brutto': 76.8},
            perioden={
                'vorwoche':   {'umsatz': {'anzahl_bons': 21}},
                'folgewoche': {'umsatz': {'anzahl_bons': 12}},
                'vorjahr':    {'umsatz': {'anzahl_bons': 23}},
                'vorjahr_kw': {'umsatz': {'anzahl_bons': 25}},
            },
        )
        ins = kk.insights_generieren(analyse)
        treffer = [i for i in ins if 'nicht gezuendet' in i['titel']]
        self.assertTrue(treffer)

    def test_kein_warn_wenn_uplift_da(self):
        # 19% Rabatt aber +30% Uplift -> kein Insight
        analyse = _basis_analyse(
            aktion_umsatz={'anzahl_bons': 30, 'stueckzahl': 35,
                           'brutto_umsatz': 150, 'tage': 7, 'bons_pro_tag': 4.3},
            margen={'normal_pro_stk': 4.29, 'aktion_pro_stk': 3.49,
                    'rabatt_pro_stk': 0.80, 'stueckzahl': 35.0,
                    'rabatt_volumen': 28.0, 'normal_brutto': 150,
                    'aktion_brutto': 122},
            perioden={
                'vorwoche':   {'umsatz': {'anzahl_bons': 22}},
                'vorjahr_kw': {'umsatz': {'anzahl_bons': 24}},
            },
        )
        ins = kk.insights_generieren(analyse)
        self.assertFalse(any('nicht gezuendet' in i['titel'] for i in ins))


if __name__ == '__main__':
    unittest.main()
