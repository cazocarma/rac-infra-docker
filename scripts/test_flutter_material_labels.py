import unittest
import json
from flutter_material_labels import FlutterMaterialLabels
from check_flutter_material_contract import check


class MaterialLabelsTest(unittest.TestCase):
    def test_contract_rejects_absent_duplicate_or_drifted_observations(self):
        records = []
        for language in ('es', 'en'):
            labels = FlutterMaterialLabels(language)
            records.append({'locale': language, 'back': labels.back,
                            'open_navigation': labels.open_navigation,
                            'remaining': {str(n): labels.remaining(n) for n in (0, 1, 1995, 2000)}})
        def output(items):
            return '\n'.join('MATERIAL_LABELS_JSON:' + json.dumps(item) for item in items)
        check(output(records))
        for items in ([], records[:1], records + records[:1]):
            with self.assertRaises(ValueError):
                check(output(items))
        records[0]['remaining']['2000'] = '2000 characters remaining'
        with self.assertRaises(ValueError):
            check(output(records))

    def test_explicit_browser_locale_does_not_fall_back_to_english(self):
        spanish = FlutterMaterialLabels('es-CL')
        english = FlutterMaterialLabels('en-US')
        self.assertEqual(spanish.back, 'Atrás')
        self.assertEqual(spanish.open_navigation, 'Abrir el menú de navegación')
        self.assertEqual(spanish.remaining(2000), 'Quedan 2.000 caracteres')
        self.assertEqual(spanish.remaining(1), 'Queda 1 carácter.')
        self.assertEqual(spanish.remaining(0), 'Quedan 0 caracteres')
        self.assertEqual(english.remaining(1), '1 character remaining')
        self.assertEqual(english.remaining(2000), '2,000 characters remaining')
        self.assertEqual(english.remaining(0), 'No characters remaining')
        for value in ('es-AR', 'en-US@posix', '', None):
            with self.assertRaises(ValueError):
                FlutterMaterialLabels(value)
        for value in (-1, True, 1.2, '1'):
            with self.assertRaises(ValueError):
                spanish.remaining(value)


if __name__ == '__main__':
    unittest.main()
