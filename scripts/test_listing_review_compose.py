"""Render configuration with synthetic example values; never starts services."""
import json
import os
from pathlib import Path
import subprocess
import unittest
import shutil
from database_roles import ROLES
from listing_review_database import INGRESSES

ROOT = Path(__file__).resolve().parents[1]


def gnu_make():
    make = shutil.which('make')
    if not make:
        candidate = Path('C:/Program Files (x86)/GnuWin32/bin/make.exe')
        make = str(candidate) if candidate.exists() else None
    return make


class ListingReviewCompose(unittest.TestCase):
    def test_make_preview_is_explicit_dev_only_and_requires_standing(self):
        make = gnu_make()
        self.assertIsNotNone(make, 'GNU Make required for preview gate verification')
        for arguments in (
            ['ENV=qa', 'LISTING_PREVIEW=1', 'STANDING_PREVIEW=1'],
            ['ENV=dev', 'LISTING_PREVIEW=1', 'STANDING_PREVIEW=0'],
            ['ENV=dev', 'PHOTO_REVIEW_PREVIEW=1', 'LISTING_PREVIEW=0'],
            ['ENV=qa', 'PHOTO_REVIEW_PREVIEW=1'],
            ['ENV=dev', 'PHOTO_REVIEW_PREVIEW=yes'],
            ['ENV=dev', 'PHOTO_PROMOTION_PREVIEW=1', 'PHOTO_REVIEW_PREVIEW=0'],
            ['ENV=prd', 'PHOTO_PROMOTION_PREVIEW=1'],
            ['ENV=dev', 'PHOTO_PROMOTION_PREVIEW=yes'],
        ):
            result = subprocess.run([make, '-n', 'config', *arguments], cwd=ROOT, capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0, 'Invalid preview combination accepted')
        result = subprocess.run([make, '-n', 'listing-review-db-config', 'ENV=qa'], cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0, 'Provisioning outside DEV accepted')
        result = subprocess.run([make, '-n', 'listing-review-db-config', 'ENV=dev', 'STANDING_PREVIEW=1', 'LISTING_PREVIEW=1'],
                                cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0)
        self.assertIn('-f compose.listings.yaml', result.stdout)
        self.assertIn('listing_review_database.py', result.stdout)
        result = subprocess.run([make, '-n', 'config', 'ENV=dev', 'LISTING_PREVIEW=0'], cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertNotIn('-f compose.listings.yaml', result.stdout)
        self.assertNotIn('-f compose.photo-review.yaml', result.stdout)
        self.assertNotIn('-f compose.photo-promotion.yaml', result.stdout)
        result = subprocess.run([make, '-n', 'config', 'ENV=dev', 'STANDING_PREVIEW=1', 'LISTING_PREVIEW=1', 'PHOTO_REVIEW_PREVIEW=1'],
                                cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0)
        self.assertIn('-f compose.photo-review.yaml', result.stdout)
        result = subprocess.run([make, '-n', 'config', 'ENV=dev', 'STANDING_PREVIEW=1', 'LISTING_PREVIEW=1', 'PHOTO_REVIEW_PREVIEW=1', 'PHOTO_PROMOTION_PREVIEW=1'], cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0)
        self.assertIn('-f compose.photo-promotion.yaml', result.stdout)

    def test_opt_in_keeps_listener_private_and_requires_every_value(self):
        values = dict(line.split('=', 1) for line in (ROOT / 'envs/.env.dev.example').read_text(encoding='utf-8').splitlines()
                      if '=' in line and not line.lstrip().startswith('#'))
        values.update({key: 'postgresql://' + role + ':synthetic-' + role + '-123456@postgres/' + values['POSTGRES_DB'] + '?sslmode=disable'
                       for key, role in ROLES.items()})
        values.update({variable: 'postgresql://' + role + ':synthetic-' + role + '-123456@postgres/' + values['POSTGRES_DB'] + '?sslmode=disable'
                       for role, (variable, _) in INGRESSES.items()})
        values.update(MIGRATION_DB_USER='rac_migrator', MIGRATION_DB_PASSWORD='synthetic-migration-only-123456',
                      LISTING_REVIEW_POLICY_VERSION='11111111-1111-4111-8111-111111111111', LISTING_POLICY_VERSION='dev-synthetic-1',
                      LISTING_MIN_PRICE_CLP='5000', LISTING_MAX_PRICE_CLP='50000')
        command = ['docker', 'compose', '--env-file', 'envs/.env.dev.example', '-p', 'rac-listing-config-test', '--profile', 'tools',
                   '-f', 'compose.yaml', '-f', 'docker-compose.dev.yaml', '-f', 'compose.standing.yaml']

        def render(extra, environment):
            result = subprocess.run(command + extra + ['config', '--format', 'json'], cwd=ROOT,
                                    env=environment, capture_output=True, text=True, timeout=30)
            return result.returncode, (json.loads(result.stdout)['services'] if result.returncode == 0 else None)

        environment = {**os.environ, **values}
        status, baseline = render([], environment)
        self.assertEqual(status, 0, 'Synthetic compose rendering failed')
        self.assertNotEqual(baseline['backend-user']['environment'].get('LISTING_REVIEW_ENABLED'), 'true')
        status, services = render(['-f', 'compose.listings.yaml'], environment)
        self.assertEqual(status, 0)
        self.assertEqual(set(services), set(baseline), 'Preview must not add fixture/provisioning services')
        self.assertEqual(services['backend-user']['environment']['LISTING_REVIEW_ENABLED'], 'true')
        self.assertEqual(services['backend-admin']['environment']['LISTING_REVIEW_URL'], 'http://backend-user:8084')
        for name in services:
            self.assertEqual(services[name].get('ports', []), baseline[name].get('ports', []))
            for port in services[name].get('ports', []):
                self.assertNotIn(port['target'], (8082, 8083, 8084), 'Internal ingress port published')
        for variable in ('LISTING_REVIEW_APPROVER_DATABASE_URL', 'LISTING_POLICY_VERSION', 'LISTING_MAX_PRICE_CLP'):
            missing = {key: value for key, value in environment.items() if key != variable}
            self.assertNotEqual(render(['-f', 'compose.listings.yaml'], missing)[0], 0, variable + ' was optional')
        preview = {**environment, 'RAC_PHOTO_S3_ENDPOINT': 'http://rustfs:9000', 'RAC_PHOTO_S3_REGION': 'us-east-1',
                   'RAC_PHOTO_QUARANTINE_BUCKET': 'synthetic-quarantine', 'RAC_PHOTO_STAGING_BUCKET': 'synthetic-staging',
                   'PHOTO_PREVIEW_ACCESS_KEY_PATH': './synthetic-preview-access',
                   'PHOTO_PREVIEW_SECRET_KEY_PATH': './synthetic-preview-secret'}
        overlays = ['-f', 'compose.listings.yaml', '-f', 'compose.photo-review.yaml']
        status, photo_services = render(overlays, preview)
        self.assertEqual(status, 0, 'Explicit photo preview config failed')
        self.assertEqual(photo_services['backend-user']['environment']['RAC_PHOTO_PREVIEW_ENABLED'], 'true')
        self.assertNotIn('RAC_PHOTO_PREVIEW_ACCESS_KEY', photo_services['backend-user']['environment'])
        self.assertEqual({item['source'] for item in photo_services['backend-user']['secrets']},
                         {'rac_photo_preview_access_key', 'rac_photo_preview_secret_key'})
        for name in photo_services:
            self.assertEqual(photo_services[name].get('ports', []), services[name].get('ports', []))
            if name != 'backend-user':
                self.assertEqual(photo_services[name].get('secrets', []), services[name].get('secrets', []))
        for variable in ('RAC_PHOTO_STAGING_BUCKET', 'RAC_PHOTO_S3_ENDPOINT', 'PHOTO_PREVIEW_SECRET_KEY_PATH'):
            missing = {key: value for key, value in preview.items() if key != variable}
            self.assertNotEqual(render(overlays, missing)[0], 0, variable + ' was optional')
        promotion = {**preview, 'LISTING_REVIEW_PHOTO_APPROVER_DATABASE_URL': 'postgresql://rac_listing_photo_approver:synthetic-independent-photo-secret@postgres/'+values['POSTGRES_DB']+'?sslmode=disable',
                     'RAC_PHOTO_PIPELINE_VERSION': 'synthetic-pipeline-1', 'RAC_PHOTO_MEDIA_TARGET_ID': '22222222-2222-4222-8222-222222222222',
                     'RAC_PHOTO_MEDIA_BUCKET': 'synthetic-approved-media', 'PHOTO_PROMOTER_ACCESS_KEY_PATH': './synthetic-promoter-access',
                     'PHOTO_PROMOTER_SECRET_KEY_PATH': './synthetic-promoter-secret'}
        promoted_overlays = [*overlays, '-f', 'compose.photo-promotion.yaml']
        status, promotion_services = render(promoted_overlays, promotion)
        self.assertEqual(status, 0)
        self.assertEqual(promotion_services['backend-user']['environment']['RAC_PHOTO_PROMOTION_ENABLED'], 'true')
        self.assertNotIn('RAC_PHOTO_PROMOTER_SECRET_KEY', promotion_services['backend-user']['environment'])
        self.assertEqual({item['source'] for item in promotion_services['backend-user']['secrets']},
                         {'rac_photo_preview_access_key','rac_photo_preview_secret_key','rac_photo_promoter_access_key','rac_photo_promoter_secret_key'})
        self.assertEqual(promotion_services['database-config']['environment']['RAC_PHOTO_PROMOTION_ENABLED'], 'true')
        for name in promotion_services:
            self.assertEqual(promotion_services[name].get('ports', []), photo_services[name].get('ports', []))
            if name != 'backend-user':
                self.assertEqual(promotion_services[name].get('secrets', []), photo_services[name].get('secrets', []))
        for variable in ('LISTING_REVIEW_PHOTO_APPROVER_DATABASE_URL','RAC_PHOTO_MEDIA_TARGET_ID','PHOTO_PROMOTER_SECRET_KEY_PATH'):
            missing = {key: value for key,value in promotion.items() if key != variable}
            self.assertNotEqual(render(promoted_overlays, missing)[0], 0, variable+' was optional')


if __name__ == '__main__':
    unittest.main()
