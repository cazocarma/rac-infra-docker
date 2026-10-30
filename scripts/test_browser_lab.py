import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from browser_compose import command
from browser_app_labels import app_label
from browser_lab import APIS, SERVICES, TOOLS, WORKERS, validate_model


class BrowserLabIsolation(unittest.TestCase):
    def test_model_rejects_existing_resources_and_host_mounts_before_mutation(self):
        project = 'rac-browser-e2e-0123456789ab'
        with tempfile.TemporaryDirectory() as temp:
            sources = Path(temp).resolve()
            model = {'name': project, 'services': {name: {} for name in SERVICES},
                     'volumes': {'photos': {'name': project + '_photos'}},
                     'networks': {'default': {'name': project + '_default'}}}
            for name in APIS + WORKERS + TOOLS + ('flutter-web',):
                model['services'][name]['image'] = project + '-' + name
            model['services']['postgres']['tmpfs'] = ['/var/lib/postgresql/data']
            model['services']['postgres']['environment'] = {'POSTGRES_DB': 'rac_browser_e2e'}
            model['services']['rabbitmq']['tmpfs'] = ['/var/lib/rabbitmq']
            model['services']['nginx']['ports'] = [{'host_ip': '127.0.0.1', 'published': '51690', 'target': 80}]
            model['services']['keycloak']['ports'] = [{'host_ip': '127.0.0.1', 'published': '51691', 'target': 8080}]
            validate_model(model, project, 51690, 51691, sources)
            variants = []
            def case():
                value = copy.deepcopy(model)
                variants.append(value)
                return value
            case()['name'] = 'rac-dev'
            case()['volumes']['photos']['name'] = 'rac-dev_profile-photos'
            case()['volumes']['photos']['external'] = True
            case()['networks']['default']['driver_opts'] = {'parent': 'host'}
            case()['services']['nginx']['ports'][0]['host_ip'] = '0.0.0.0'
            case()['services']['backend-user']['image'] = 'rac-dev-user:local'
            case()['services']['postgres']['volumes'] = [{'type': 'volume', 'target': '/var/lib/postgresql/data'}]
            case()['services']['rabbitmq']['tmpfs'] = []
            case()['services']['postgres']['environment']['POSTGRES_DB'] = 'rentacompa'
            case()['services']['backend-chat']['privileged'] = True
            case()['services']['backend-user']['build'] = {'context': str(sources.parent)}
            case()['services']['nginx']['volumes'] = [{'type': 'bind', 'source': str(sources / 'config'), 'read_only': False}]
            case()['services']['nginx']['volumes'] = [{'type': 'bind', 'source': str(sources.parent / 'secret'), 'read_only': True}]
            case()['secrets'] = {'operator': {'file': '/private'}}
            for variant in variants:
                with self.subTest(variant=variants.index(variant)), self.assertRaises(RuntimeError):
                    validate_model(variant, project, 51690, 51691, sources)

    def test_explicit_lab_never_falls_back_to_dev(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / 'rac-browser-e2e-0123456789ab'
            root = directory / 'sources' / 'rac-infra-docker'
            root.mkdir(parents=True)
            state = directory / 'state.json'
            metadata = {'project': directory.name, 'source_root': str(root.resolve()),
                        'web_port': 51690, 'web_url': 'http://localhost:51690',
                        'identity_port': 51691, 'identity_url': 'http://localhost:51691'}
            state.write_text(json.dumps(metadata))
            with self.assertRaises(RuntimeError):
                command(root, state)
            (directory / 'fixture.env').write_text('RAC_ENV=dev\n')
            (directory / 'compose.json').write_text('{}')
            args = command(root, state)
            self.assertIn(directory.name, args)
            self.assertNotIn('rac-dev', args)
            metadata['web_url'] = 'https://external.example'
            state.write_text(json.dumps(metadata))
            with self.assertRaises(RuntimeError):
                command(root, state)
            with self.assertRaises(RuntimeError):
                command(root.parent, state)
            with patch.dict(os.environ, {'RAC_BROWSER_LAB_STATE': ''}):
                with self.assertRaises(RuntimeError):
                    command(root)

    def test_app_copy_uses_explicit_catalogue_with_review_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'rac-infra-docker'
            root.mkdir()
            catalogue = root.parent / 'rac-frontend-flutter/lib/l10n'
            catalogue.mkdir(parents=True)
            (catalogue / 'app_es.arb').write_text(json.dumps({'publish': 'Publicar', '@publish': {'legal_review': 'pending'}}))
            self.assertEqual(app_label(root, 'publish', 'es-CL'), 'Publicar')
            for key, locale in (('missing', 'es'), ('@publish', 'es'), ('publish', 'es-AR')):
                with self.assertRaises(ValueError):
                    app_label(root, key, locale)


if __name__ == '__main__':
    unittest.main()
