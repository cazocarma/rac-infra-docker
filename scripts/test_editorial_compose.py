"""Render configuration with synthetic example values; never starts services."""
import json
import os
from pathlib import Path
import subprocess
import unittest
import shutil
from database_roles import ROLES

ROOT = Path(__file__).resolve().parents[1]


class EditorialCompose(unittest.TestCase):
    def test_make_preview_is_explicit_dev_only_and_requires_standing(self):
        make = shutil.which('make')
        if not make:
            candidate = Path('C:/Program Files (x86)/GnuWin32/bin/make.exe')
            make = str(candidate) if candidate.exists() else None
        self.assertIsNotNone(make, 'GNU Make required for preview gate verification')
        for arguments in (
            ['ENV=qa', 'EDITORIAL_PREVIEW=1', 'STANDING_PREVIEW=1'],
            ['ENV=dev', 'EDITORIAL_PREVIEW=1', 'STANDING_PREVIEW=0'],
            ['ENV=dev', 'EDITORIAL_PREVIEW=2'],
            ['ENV=dev', 'EDITORIAL_PREVIEW=1 0'],
        ):
            result = subprocess.run([make, '-n', 'editorial-db-config', *arguments], cwd=ROOT,
                                    capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0, 'Invalid preview combination accepted')
        result = subprocess.run([make, '-n', 'editorial-db-config', 'ENV=dev', 'STANDING_PREVIEW=1', 'EDITORIAL_PREVIEW=1'],
                                cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0)
        self.assertIn('-f compose.editorial.yaml', result.stdout)
        result = subprocess.run([make, '-n', 'editorial-db-config', 'ENV=dev', 'EDITORIAL_PREVIEW=0'],
                                cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn('-f compose.editorial.yaml', result.stdout)

    def test_opt_in_merge_keeps_ingress_private_and_all_document_writers_enabled(self):
        values = dict(line.split('=', 1) for line in (ROOT / 'envs/.env.dev.example').read_text(encoding='utf-8').splitlines()
                      if '=' in line and not line.lstrip().startswith('#'))
        values.update(DOCUMENT_EDITORIAL_DATABASE_URL='postgresql://rac_documents_editorial:synthetic-only-credential-123456@postgres/rac_test?sslmode=disable',
                      DOCUMENT_EDITORIAL_POLICY_VERSION='11111111-1111-4111-8111-111111111111')
        values.update({key:'postgresql://' + role + ':synthetic-' + role + '-123456@postgres/' + values['POSTGRES_DB'] + '?sslmode=disable'
                       for key, role in ROLES.items()})
        values.update(MIGRATION_DB_USER='rac_migrator', MIGRATION_DB_PASSWORD='synthetic-migration-only-123456', STAFF_CLIENT_ENABLED='false')
        environment = {**os.environ, **values}
        command = ['docker', 'compose', '--env-file', 'envs/.env.dev.example', '-p', 'rac-editorial-config-test', '--profile', 'tools',
                   '-f', 'compose.yaml', '-f', 'docker-compose.dev.yaml', '-f', 'compose.standing.yaml']
        def render(extra):
            result = subprocess.run(command + extra + ['config', '--format', 'json'], cwd=ROOT,
                                    env=environment, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, 'Synthetic compose rendering failed')
            return json.loads(result.stdout)['services']
        baseline = render([])
        self.assertNotEqual(baseline['backend-user']['environment'].get('DOCUMENT_EDITORIAL_ENABLED'), 'true')
        self.assertNotEqual(baseline['backend-admin']['environment'].get('STAFF_ACCESS_ENABLED'), 'true')
        services = render(['-f', 'compose.editorial.yaml'])
        self.assertEqual(set(services), set(baseline), 'Preview must not add fixture/provisioning services')
        for name in ('backend-user', 'backend-admin', 'backend-match', 'backend-chat'):
            self.assertEqual(services[name].get('ports', []), baseline[name].get('ports', []))
        for name in ('identity-config', 'backend-user', 'backend-match', 'backend-chat'):
            self.assertEqual(services[name]['environment']['DOCUMENTS_ENFORCEMENT_ENABLED'], 'true')
        self.assertEqual(services['backend-admin']['environment']['DOCUMENT_EDITORIAL_URL'], 'http://backend-user:8083')
        self.assertEqual(services['identity-config']['environment']['STAFF_CLIENT_ENABLED'], 'false')
        for name in ('backend-match', 'backend-chat'):
            self.assertEqual(services[name]['environment']['DOCUMENTS_AUTHORITY_URL'], 'http://backend-user:8082/internal/documents')
        for name in services:
            for port in services[name].get('ports', []):
                self.assertNotIn(port['target'], (8082, 8083), 'Internal authority/editorial port published')
        environment['STAFF_CLIENT_ENABLED'] = 'true'
        opted_in = render(['-f', 'compose.editorial.yaml'])
        self.assertEqual(opted_in['identity-config']['environment']['STAFF_CLIENT_ENABLED'], 'true')
        self.assertEqual(set(opted_in), set(baseline))
