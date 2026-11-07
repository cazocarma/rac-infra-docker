"""Render the T&S effect overlay with synthetic values; never starts services."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from database_roles import ROLES
from test_listing_review_compose import gnu_make

ROOT = Path(__file__).resolve().parents[1]
WORKERS = {'ts-effect-relay': ('rac-dev-admin:local', '/app/ts-relay', 'messaging-ts-publisher', 'rac_ts_relay_database_url'),
           'ts-effect-consumer': ('rac-dev-user:local', '/app/ts-effects', 'messaging-ts-user', 'rac_ts_effects_database_url')}


class TrustSafetyEffectsCompose(unittest.TestCase):
    def test_make_preview_is_explicit_and_dev_only(self):
        make = gnu_make()
        self.assertIsNotNone(make, 'GNU Make required for preview gate verification')
        for arguments in (['ENV=qa', 'TS_EFFECTS_PREVIEW=1'], ['ENV=prd', 'TS_EFFECTS_PREVIEW=1'],
                          ['ENV=dev', 'TS_EFFECTS_PREVIEW=yes'], ['ENV=dev', 'TS_EFFECTS_PREVIEW=1 1']):
            result = subprocess.run([make, '-n', 'config', *arguments], cwd=ROOT, capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0, 'Invalid T&S preview accepted: ' + ' '.join(arguments))
        result = subprocess.run([make, '-n', 'config', 'ENV=dev'], cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertNotIn('compose.ts-effects.yaml', result.stdout)
        result = subprocess.run([make, '-n', 'config', 'ENV=dev', 'TS_EFFECTS_PREVIEW=1'], cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0)
        self.assertIn('-f compose.ts-effects.yaml', result.stdout)
        result = subprocess.run([make, '-n', 'ts-db-config', 'ENV=qa'], cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0, 'T&S provisioning outside DEV accepted')
        result = subprocess.run([make, '-n', 'ts-db-config', 'ENV=dev'], cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0)
        self.assertIn('ts_database.py', result.stdout)
        self.assertIn('-e RAC_ENV=dev', result.stdout)

    def test_overlay_adds_only_hardened_workers_with_file_secrets(self):
        values = dict(line.split('=', 1) for line in (ROOT / 'envs/.env.dev.example').read_text(encoding='utf-8').splitlines()
                      if '=' in line and not line.lstrip().startswith('#'))
        values.update({key: 'postgresql://' + role + ':synthetic-' + role + '-123456@postgres/' + values['POSTGRES_DB'] + '?sslmode=disable'
                       for key, role in ROLES.items()})
        values.update(MIGRATION_DB_USER='rac_migrator', MIGRATION_DB_PASSWORD='synthetic-migration-only-123456', RAC_ENV='dev')
        command = ['docker', 'compose', '--env-file', 'envs/.env.dev.example', '-p', 'rac-ts-config-test', '--profile', 'tools',
                   '-f', 'compose.yaml', '-f', 'docker-compose.dev.yaml']

        def render(extra, environment):
            result = subprocess.run(command + extra + ['config', '--format', 'json'], cwd=ROOT,
                                    env=environment, capture_output=True, text=True, timeout=30)
            return result.returncode, (json.loads(result.stdout) if result.returncode == 0 else None)

        with tempfile.TemporaryDirectory() as folder:
            relay, consumer = Path(folder) / 'relay', Path(folder) / 'consumer'
            relay.write_text('synthetic', encoding='utf-8')
            consumer.write_text('synthetic', encoding='utf-8')
            preview = {**os.environ, **values, 'TS_RELAY_DATABASE_URL_PATH': str(relay),
                       'TS_EFFECTS_DATABASE_URL_PATH': str(consumer),
                       'TS_EFFECTS_POLICY_VERSION': '33333333-3333-4333-8333-333333333333'}
            status, baseline = render([], preview)
            self.assertEqual(status, 0, 'Synthetic baseline rendering failed')
            self.assertNotIn('RAC_TS_MESSAGING', baseline['services']['messaging-config'].get('environment', {}))
            status, rendered = render(['-f', 'compose.ts-effects.yaml'], preview)
            self.assertEqual(status, 0, 'Explicit T&S overlay rendering failed')
            services = rendered['services']
            self.assertEqual(set(services) - set(baseline['services']), set(WORKERS))
            self.assertEqual(services['messaging-config']['environment']['RAC_TS_MESSAGING'], '1')
            targets = {item['target'] for item in services['messaging-config']['volumes']}
            self.assertTrue({'/credentials/ts-publisher', '/credentials/ts-user'} <= targets)
            for name, (image, entrypoint, credentials, secret) in WORKERS.items():
                worker = services[name]
                self.assertEqual((worker['image'], worker['entrypoint']), (image, [entrypoint]))
                self.assertTrue(worker['read_only'])
                self.assertEqual(worker['cap_drop'], ['ALL'])
                self.assertIn('no-new-privileges:true', worker['security_opt'])
                self.assertEqual(worker['environment']['RAC_ENV'], 'dev')
                self.assertEqual([item['source'] for item in worker['secrets']], [secret])
                self.assertFalse(any('postgres' in str(value) for value in worker['environment'].values()),
                                 'Database URL must arrive only as a secret file')
                mounts = {item['source']: item for item in worker['volumes']}
                self.assertTrue(mounts[credentials]['read_only'])
                self.assertNotIn('ports', worker)
            for name in baseline['services']:
                self.assertEqual(services[name].get('ports', []), baseline['services'][name].get('ports', []))
                if name not in WORKERS:
                    self.assertEqual(services[name].get('secrets', []), baseline['services'][name].get('secrets', []))
            for variable in ('TS_RELAY_DATABASE_URL_PATH', 'TS_EFFECTS_DATABASE_URL_PATH', 'TS_EFFECTS_POLICY_VERSION'):
                missing = {key: value for key, value in preview.items() if key != variable}
                self.assertNotEqual(render(['-f', 'compose.ts-effects.yaml'], missing)[0], 0, variable + ' was optional')


if __name__ == '__main__':
    unittest.main()
