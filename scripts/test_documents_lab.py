import copy
import unittest
from documents_lab import validate_model


class DocumentLabIsolation(unittest.TestCase):
    def model(self):
        project = 'rac-documents-e2e-' + 'a' * 12
        services = {name: {'image': project + '-fixture'} for name in (
            'database-config', 'identity-config', 'keycloak', 'backend-auth', 'backend-user', 'flutter-web', 'test-documents')}
        services['postgres'] = {'tmpfs': ['/var/lib/postgresql/data']}
        services['nginx'] = {'ports': [{'host_ip': '127.0.0.1', 'published': '12345', 'target': 80}]}
        return {'name': project, 'services': services, 'volumes': {'test': {'name': project + '_test'}},
                'networks': {'default': {'name': project + '_default'}}}

    def test_accepts_only_owned_loopback_lab_and_rejects_persistent_resources(self):
        model = self.model()
        validate_model(model, model['name'], 12345, 12346)
        mutations = [
            lambda m: m['services']['postgres'].update(tmpfs=[]),
            lambda m: m['services']['postgres'].update(volumes=[{'target': '/var/lib/postgresql/data', 'type': 'volume'}]),
            lambda m: m['services'].pop('identity-config'),
            lambda m: m.update(name='rac-dev'),
            lambda m: m['services']['nginx']['ports'][0].update(host_ip='0.0.0.0'),
            lambda m: m['volumes']['test'].update(name='rac-dev_pgdata'),
            lambda m: m['volumes']['test'].update(external=True),
            lambda m: m['networks']['default'].update(name='rac-dev_default'),
            lambda m: m['services']['backend-user'].update(privileged=True),
            lambda m: m['services']['backend-user'].update(volumes=[{'type': 'bind', 'read_only': False}]),
            lambda m: m['services']['flutter-web'].update(image='rac-dev-frontend:local'),
        ]
        for mutate in mutations:
            bad = copy.deepcopy(model); mutate(bad)
            with self.assertRaises(RuntimeError):
                validate_model(bad, model['name'], 12345, 12346)

    def test_editorial_lab_requires_owned_images_for_every_extra_service(self):
        model = self.model()
        for name in ('backend-admin', 'backend-match', 'backend-chat', 'staff-fixture'):
            model['services'][name] = {'image': model['name'] + '-fixture'}
        validate_model(model, model['name'], 12345, 12346, staff=True)
        for name in ('backend-admin', 'backend-match', 'backend-chat', 'staff-fixture'):
            missing = copy.deepcopy(model)
            missing['services'].pop(name)
            with self.assertRaises(RuntimeError):
                validate_model(missing, model['name'], 12345, 12346, staff=True)
            shared = copy.deepcopy(model)
            shared['services'][name]['image'] = 'rac-dev-' + name + ':local'
            with self.assertRaises(RuntimeError):
                validate_model(shared, model['name'], 12345, 12346, staff=True)
        exposed = copy.deepcopy(model)
        exposed['services']['backend-user']['ports'] = [{'host_ip': '127.0.0.1', 'published': '8083', 'target': 8083}]
        with self.assertRaises(RuntimeError):
            validate_model(exposed, model['name'], 12345, 12346, staff=True)
