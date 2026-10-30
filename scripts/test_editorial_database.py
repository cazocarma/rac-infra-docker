import unittest
from editorial_database import SIGNATURES, validate_target, validate_environment
from database_roles import ROLES
from urllib.parse import quote


class EditorialDatabaseTarget(unittest.TestCase):
    def test_environment_requires_complete_independent_credentials_before_connection(self):
        values = {'RAC_ENV':'dev', 'POSTGRES_DB':'rac_test', 'MIGRATION_DB_USER':'rac_migrator',
                  'MIGRATION_DB_PASSWORD':'migration-secret-' + 'm' * 24, 'PGPASSWORD':'operator-secret-' + 'p' * 24}
        for key, role in ROLES.items():
            values[key] = 'postgresql://' + role + ':' + role + '-secret-' + 'x' * 24 + '@postgres/rac_test?sslmode=disable'
        prefix = 'postgresql://rac_documents_editorial:'
        suffix = '@postgres/rac_test?sslmode=disable'
        values['DOCUMENT_EDITORIAL_DATABASE_URL'] = prefix + 'editorial-' + 'y' * 32 + suffix
        self.assertEqual(validate_environment(values), (values['DOCUMENT_EDITORIAL_DATABASE_URL'], 'rac_test'))
        for secret in (values['MIGRATION_DB_PASSWORD'], values['PGPASSWORD'], 'rac_user-secret-' + 'x' * 24):
            with self.assertRaises(RuntimeError):
                validate_environment({**values, 'DOCUMENT_EDITORIAL_DATABASE_URL':prefix + quote(secret, safe='') + suffix})
        for change in ({'RAC_ENV':'prd'}, {'USER_DB_URL':''}):
            with self.assertRaises(RuntimeError):
                validate_environment({**values, **change})
        special = quote('private:special@value/with space0123456789', safe='')
        with self.assertRaises(RuntimeError):
            validate_environment({**values,
                'USER_DB_URL':'postgresql://rac_user:' + special + '@postgres/rac_test?sslmode=disable',
                'DOCUMENT_EDITORIAL_DATABASE_URL':prefix + special + suffix})

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
