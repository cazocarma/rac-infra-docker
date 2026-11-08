import unittest
from urllib.parse import quote

from database_roles import ROLES
from ts_database import LOGINS, validate_environment, validate_target


def url(role, secret, database='rac_test'):
    return 'postgresql://' + role + ':' + quote(secret, safe='') + '@postgres/' + database + '?sslmode=disable'


def environment():
    values = {'RAC_ENV': 'dev', 'POSTGRES_DB': 'rac_test', 'MIGRATION_DB_USER': 'rac_migrator',
              'MIGRATION_DB_PASSWORD': 'migration-secret-' + 'm' * 24, 'PGPASSWORD': 'operator-secret-' + 'p' * 24,
              'LISTING_REVIEW_READER_DATABASE_URL': url('rac_listing_reader', 'listing-' + 'l' * 32)}
    for key, role in ROLES.items():
        values[key] = url(role, role + '-secret-' + 'x' * 24)
    for role, (variable, _, _) in LOGINS.items():
        values[variable] = url(role, role + '-' + 'y' * 32)
    return values


class TrustSafetyDatabaseTarget(unittest.TestCase):
    def test_independent_credentials_before_connection(self):
        targets, database = validate_environment(environment())
        self.assertEqual((set(targets), database), (set(LOGINS), 'rac_test'))
        values = environment()
        relay = values['TS_RELAY_DATABASE_URL']
        for change in ({'RAC_ENV': 'prd'}, {'RAC_ENV': ''},
                       {'TS_EFFECTS_DATABASE_URL': relay.replace('rac_ts_relay:', 'rac_ts_effects:')},
                       {'TS_CASES_DATABASE_URL': url('rac_ts_cases', values['PGPASSWORD'])},
                       {'TS_CASES_DATABASE_URL': url('rac_ts_cases', 'rac_user-secret-' + 'x' * 24)},
                       {'TS_RELAY_DATABASE_URL': url('rac_ts_relay', 'listing-' + 'l' * 32)},
                       {'TS_RELAY_DATABASE_URL': url('rac_ts_relay', values['MIGRATION_DB_PASSWORD'])}):
            with self.assertRaises(RuntimeError):
                validate_environment({**values, **change})

    def test_logins_are_requested_independently(self):
        values = environment()
        del values['TS_CASES_DATABASE_URL']
        self.assertEqual(set(validate_environment(values)[0]), {'rac_ts_intake', 'rac_ts_relay', 'rac_ts_effects'})
        for variable in ('TS_INTAKE_DATABASE_URL', 'TS_RELAY_DATABASE_URL', 'TS_EFFECTS_DATABASE_URL'):
            del values[variable]
        with self.assertRaises(RuntimeError):
            validate_environment(values)

    def test_only_exact_internal_dev_target(self):
        dsn = 'postgresql://rac_ts_relay:' + 'x' * 32 + '@postgres:5432/rac_test?sslmode=disable'
        self.assertEqual(validate_target(dsn, 'rac_test', 'rac_ts_relay'), 'x' * 32)
        for changed in (dsn.replace('rac_ts_relay:', 'rac_user:'), dsn.replace('@postgres:', '@foreign:'),
                        dsn.replace('/rac_test?', '/keycloak?'), dsn + '&options=-c%20role%3Dpostgres',
                        dsn + '#fragment', dsn.replace('x' * 32, 'short'), dsn.replace('sslmode=disable', 'sslmode=require')):
            with self.assertRaises(RuntimeError):
                validate_target(changed, 'rac_test', 'rac_ts_relay')
        for role in ('postgres', 'rac_user', 'rac_listing_approver'):
            with self.assertRaises(RuntimeError):
                validate_target(dsn, 'rac_test', role)

    def test_capabilities_match_each_process(self):
        signatures = {role: set(entry[2]) for role, entry in LOGINS.items()}
        # Exactly the sets each worker verifies with CheckRole.
        self.assertEqual(signatures['rac_ts_relay'], {'ts.effect_relay_ready()', 'ts.claim_effect(audit.reference)',
                                                      'ts.confirm_effect(audit.reference)', 'ts.retry_effect(audit.reference)',
                                                      'ts.effect_relay_backlog()'})
        self.assertEqual(signatures['rac_ts_effects'], {'standing.apply_ts_effect(uuid,jsonb,uuid)',
                                                        'standing.refresh_ts_standing(uuid,uuid,uuid)',
                                                        'standing.ts_expiries_due(integer)'})
        self.assertEqual(len(signatures['rac_ts_cases']), 8)
        # Intake holds only the two customer entry points; nobody passes a subject
        # directly (report_submit) or reaches evidence, and no login both decides
        # and delivers.
        ref = 'audit.reference,audit.reference,audit.reference'
        self.assertEqual(signatures['rac_ts_intake'], {f'ts.report_receive({ref},text,uuid,text)', f'ts.appeal_submit({ref},uuid,uuid)'})
        others = signatures['rac_ts_cases'] | signatures['rac_ts_relay'] | signatures['rac_ts_effects']
        self.assertFalse(signatures['rac_ts_intake'] & others)
        self.assertFalse(signatures['rac_ts_cases'] & (signatures['rac_ts_relay'] | signatures['rac_ts_effects']))
        everything = set().union(*signatures.values())
        self.assertFalse(any(s.startswith(('ts.report_submit', 'ts.evidence_')) for s in everything))
        self.assertEqual(LOGINS['rac_ts_effects'][1], ('standing',))


if __name__ == '__main__':
    unittest.main()
