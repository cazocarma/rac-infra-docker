import unittest
from editorial_database import SIGNATURES, validate_target


class EditorialDatabaseTarget(unittest.TestCase):
    def test_only_exact_separate_dev_target_is_accepted(self):
        dsn = 'postgresql://rac_documents_editorial:' + 'x' * 32 + '@postgres:5432/rac_test?sslmode=disable'
        self.assertEqual(validate_target(dsn, 'rac_test', 'rac_documents_editorial'), 'x' * 32)
        self.assertEqual(validate_target(dsn.replace('rac_documents_editorial:', 'rac_editorial_lab:'), 'rac_test', 'rac_editorial_lab'), 'x' * 32)
        for changed in (dsn.replace('rac_documents_editorial:', 'rac_user:'),
                        dsn.replace('@postgres:', '@foreign:'),
                        dsn.replace('/rac_test?', '/keycloak?'),
                        dsn + '&options=-c%20role%3Dpostgres',
                        dsn + '&sslmode=disable', dsn + '#fragment',
                        dsn.replace('x' * 32, 'short'), dsn.replace('sslmode=disable', 'sslmode=require')):
            with self.assertRaises(RuntimeError):
                validate_target(changed, 'rac_test', 'rac_documents_editorial')
        for role in ('postgres', 'rac_user', 'rac_migrator'):
            with self.assertRaises(RuntimeError):
                validate_target(dsn, 'rac_test', role)

    def test_fixed_capabilities_never_include_raw_activation_or_table_dml(self):
        self.assertEqual(len(SIGNATURES), 11)
        self.assertEqual(len(set(SIGNATURES)), 11)
        self.assertTrue(all(s.startswith('documents.') for s in SIGNATURES))
        self.assertFalse(any(s.startswith('documents.activate(') or 'editorial_record(' in s for s in SIGNATURES))
