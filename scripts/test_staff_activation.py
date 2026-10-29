import unittest
from identity_permissions import staff_client_enabled, configure_staff


class StaffActivation(unittest.TestCase):
    def test_disabled_default_and_strict_coordinated_dev_opt_in(self):
        self.assertFalse(staff_client_enabled({}))
        valid = {'RAC_ENV':'dev', 'STAFF_CLIENT_ENABLED':'true',
                 'DOCUMENTS_ENFORCEMENT_ENABLED':'true', 'STANDING_ENFORCEMENT_ENABLED':'true'}
        self.assertTrue(staff_client_enabled(valid))
        for change in ({'RAC_ENV':'prd'}, {'RAC_ENV':'qa'},
                       {'STAFF_CLIENT_ENABLED':'TRUE'}, {'STAFF_CLIENT_ENABLED':'1'},
                       {'DOCUMENTS_ENFORCEMENT_ENABLED':'false'}, {'STANDING_ENFORCEMENT_ENABLED':''}):
            with self.assertRaises(RuntimeError):
                staff_client_enabled({**valid, **change})
        self.assertFalse(staff_client_enabled({'RAC_ENV':'prd','STAFF_CLIENT_ENABLED':'false'}))

    def test_non_boolean_cannot_reach_any_admin_mutation(self):
        def forbidden(*args):
            self.fail('Invalid flag reached Keycloak')
        for value in ('false', 'true', 0, 1, None):
            with self.assertRaises(RuntimeError):
                configure_staff(forbidden, 'http://localhost', enabled=value)
