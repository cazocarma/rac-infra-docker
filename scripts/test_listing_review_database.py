import unittest
from listing_review_database import INGRESSES, validate_target, validate_environment
from database_roles import ROLES
from urllib.parse import quote


def environment():
    values = {'RAC_ENV': 'dev', 'POSTGRES_DB': 'rac_test', 'MIGRATION_DB_USER': 'rac_migrator',
              'MIGRATION_DB_PASSWORD': 'migration-secret-' + 'm' * 24, 'PGPASSWORD': 'operator-secret-' + 'p' * 24,
              'DOCUMENT_EDITORIAL_DATABASE_URL': 'postgresql://rac_documents_editorial:editorial-' + 'e' * 32 + '@postgres/rac_test?sslmode=disable'}
    for key, role in ROLES.items():
        values[key] = 'postgresql://' + role + ':' + role + '-secret-' + 'x' * 24 + '@postgres/rac_test?sslmode=disable'
    for role, (variable, _) in INGRESSES.items():
        values[variable] = 'postgresql://' + role + ':' + role + '-' + 'y' * 32 + '@postgres/rac_test?sslmode=disable'
    return values


class ListingReviewDatabaseTarget(unittest.TestCase):
    def test_three_independent_credentials_before_connection(self):
        values = environment()
        targets, database = validate_environment(values)
        self.assertEqual(database, 'rac_test')
        self.assertEqual(set(targets), set(INGRESSES))
        reader = values['LISTING_REVIEW_READER_DATABASE_URL']
        shared = reader.replace('rac_listing_reader:', 'rac_listing_approver:')
        for change in ({'RAC_ENV': 'prd'}, {'LISTING_REVIEW_APPROVER_DATABASE_URL': ''},
                       {'LISTING_REVIEW_APPROVER_DATABASE_URL': shared},
                       {'LISTING_REVIEW_CORRECTOR_DATABASE_URL': reader}):
            with self.assertRaises(RuntimeError):
                validate_environment({**values, **change})
        prefix, suffix = 'postgresql://rac_listing_corrector:', '@postgres/rac_test?sslmode=disable'
        for secret in (values['MIGRATION_DB_PASSWORD'], values['PGPASSWORD'], 'rac_user-secret-' + 'x' * 24, 'editorial-' + 'e' * 32):
            with self.assertRaises(RuntimeError):
                validate_environment({**values, 'LISTING_REVIEW_CORRECTOR_DATABASE_URL': prefix + quote(secret, safe='') + suffix})

    def test_only_exact_separate_dev_target_is_accepted(self):
        dsn = 'postgresql://rac_listing_approver:' + 'x' * 32 + '@postgres:5432/rac_test?sslmode=disable'
        self.assertEqual(validate_target(dsn, 'rac_test', 'rac_listing_approver'), 'x' * 32)
        for changed in (dsn.replace('rac_listing_approver:', 'rac_user:'), dsn.replace('@postgres:', '@foreign:'),
                        dsn.replace('/rac_test?', '/keycloak?'), dsn + '&options=-c%20role%3Dpostgres',
                        dsn + '#fragment', dsn.replace('x' * 32, 'short'), dsn.replace('sslmode=disable', 'sslmode=require')):
            with self.assertRaises(RuntimeError):
                validate_target(changed, 'rac_test', 'rac_listing_approver')
        for role in ('postgres', 'rac_user', 'rac_documents_editorial'):
            with self.assertRaises(RuntimeError):
                validate_target(dsn, 'rac_test', role)

    def test_capabilities_are_disjoint_beyond_readiness(self):
        signatures = {role: set(entry[1]) for role, entry in INGRESSES.items()}
        self.assertTrue(all(len(s) == 3 and 'listing_review.ready()' in s for s in signatures.values()))
        self.assertFalse(any('approve' in s or 'approval' in s for s in signatures['rac_listing_reader'] | signatures['rac_listing_corrector']))
        self.assertFalse(any('queue' in s or 'revision(' in s for s in signatures['rac_listing_approver'] | signatures['rac_listing_corrector']))
        self.assertFalse(any('correct(' in s for s in signatures['rac_listing_approver'] | signatures['rac_listing_reader']))


if __name__ == '__main__':
    unittest.main()
