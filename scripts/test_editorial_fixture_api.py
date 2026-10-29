import copy
from pathlib import Path
import unittest
from types import SimpleNamespace
from urllib.request import Request
from editorial_fixture_api import FixtureLocalhostCookies, load_lab, new_manifest, validate_manifest, require_result


class EditorialFixtureSafety(unittest.TestCase):
    def test_protocol_mismatch_is_an_explicit_failure(self):
        require_result({'registry_version': 0}, {'registry_version': 0})
        for actual in ({'registry_version': 1}, {}, {'error': 'different_error'}):
            with self.assertRaises(RuntimeError):
                require_result(actual, {'registry_version': 0})

    def test_secure_cookie_exception_is_only_the_exact_fixture_localhost_port(self):
        policy = FixtureLocalhostCookies('http://localhost:12345')
        cookie = SimpleNamespace(secure=True)
        self.assertTrue(policy.return_ok_secure(cookie, Request('http://localhost:12345/realms/rentacompa')))
        for url in ('http://localhost:12346/', 'http://127.0.0.1:12345/', 'http://example.test:12345/'):
            self.assertFalse(policy.return_ok_secure(cookie, Request(url)))
        self.assertTrue(policy.return_ok_secure(cookie, Request('https://example.test/')))
    def test_manifest_cannot_smuggle_non_synthetic_text_authority_or_reused_events(self):
        project = 'rac-documents-e2e-' + 'a' * 12
        manifest = new_manifest(project)
        validate_manifest(manifest, project)
        mutations = [
            lambda m: m.update(project='rac-dev'),
            lambda m: m['documents'][0].update(content='Non-fixture text'),
            lambda m: m['documents'][0].update(actor='caller-authority'),
            lambda m: m['documents'][0].update(locale='en'),
            lambda m: m['documents'][0].update(sha256='0' * 64),
            lambda m: m['documents'][1].update(event_id=m['documents'][0]['event_id']),
            lambda m: m['documents'][0].update(material_change=False),
            lambda m: m['documents'].pop(),
        ]
        for mutate in mutations:
            changed = copy.deepcopy(manifest)
            mutate(changed)
            with self.assertRaises(RuntimeError):
                validate_manifest(changed, project)

    def test_non_lab_state_is_rejected_before_reading_files_or_contacting_services(self):
        for path in (Path('/tmp/state.json'), Path('state.json'), Path('rac-dev/state.json')):
            with self.assertRaises(RuntimeError):
                load_lab(path)
