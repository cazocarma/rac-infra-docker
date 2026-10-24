"""Guard the destructive cleanup boundary without starting any containers."""
import copy
import unittest

from test_standing_e2e import validate_model


class StandingLabIsolation(unittest.TestCase):
    def test_rejects_persistent_targets_before_mutation(self):
        project = 'rac-standing-e2e-0123456789ab'
        valid = {'name': project, 'services': {'postgres': {'volumes': [
            {'type': 'volume', 'source': 'pgdata', 'target': '/var/lib/postgresql/data'},
            {'type': 'bind', 'source': './bootstrap.sql', 'target': '/bootstrap.sql', 'read_only': True}]}},
            'volumes': {'pgdata': {'name': project + '_pgdata'}},
            'networks': {'default': {'name': project + '_default'}}}
        validate_model(valid, project)
        variants = []
        def case():
            model = copy.deepcopy(valid)
            variants.append(model)
            return model
        case()['name'] = 'rac-dev'
        case()['volumes']['pgdata']['name'] = 'rac-dev_pgdata'
        case()['volumes']['pgdata']['external'] = True
        case()['volumes']['pgdata']['driver_opts'] = {'device': '/existing/data'}
        case()['networks']['default']['external'] = True
        case()['networks']['default']['name'] = 'rac-dev_default'
        case()['services']['postgres']['ports'] = ['5432:5432']
        case()['services']['postgres']['network_mode'] = 'host'
        case()['services']['postgres']['container_name'] = 'rac-dev-postgres-1'
        case()['services']['postgres']['privileged'] = True
        case()['services']['postgres']['volumes'][1]['read_only'] = False
        case()['secrets'] = {'operator': {'file': '/existing/secret'}}
        for model in variants:
            with self.subTest(model=model), self.assertRaises(RuntimeError):
                validate_model(model, project)
        with self.assertRaises(RuntimeError):
            validate_model(valid, 'rac-standing-e2e-production')


if __name__ == '__main__':
    unittest.main()
