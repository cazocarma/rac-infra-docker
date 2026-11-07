import json
import os
import tempfile
import unittest
from unittest import mock

import ci_scope

SHA = 'a' * 40


class CiScope(unittest.TestCase):
    def test_docs_only_is_markdown_outside_workflows(self):
        self.assertTrue(ci_scope.docs_only(['docs/trust-safety/P11-cases.md', 'README.md']))
        for paths in ([], ['docs/action-pins.json'], ['docs/a.md', 'scripts/x.py'], ['.github/workflows/notes.md'],
                      ['db/migrations/V061__x.sql']):
            self.assertFalse(ci_scope.docs_only(paths), paths)

    def test_pull_request_scope(self):
        with mock.patch.object(ci_scope, 'pull_request_files', return_value=['docs/a.md']):
            self.assertEqual(ci_scope.decide('pull_request', {'pull_request': {'number': 1}}, SHA, 't', 'o/r')[:2], (False, False))
        with mock.patch.object(ci_scope, 'pull_request_files', return_value=['docs/a.md', 'Makefile']):
            self.assertEqual(ci_scope.decide('pull_request', {'pull_request': {'number': 1}}, SHA, 't', 'o/r')[:2], (True, False))
        with mock.patch.object(ci_scope, 'pull_request_files', return_value=None):
            self.assertTrue(ci_scope.decide('pull_request', {'pull_request': {'number': 1}}, SHA, 't', 'o/r')[0])

    def test_push_skips_only_an_identical_verified_commit(self):
        event = {'before': 'b' * 40}
        with mock.patch.object(ci_scope, 'verified_in_pull_request', return_value=True):
            self.assertFalse(ci_scope.decide('push', event, SHA, 't', 'o/r')[0])
        with mock.patch.object(ci_scope, 'verified_in_pull_request', return_value=False), \
             mock.patch.object(ci_scope, 'compare_files', return_value=['scripts/x.py']):
            self.assertTrue(ci_scope.decide('push', event, SHA, 't', 'o/r')[0])
        with mock.patch.object(ci_scope, 'verified_in_pull_request', return_value=False), \
             mock.patch.object(ci_scope, 'compare_files', return_value=None):
            self.assertTrue(ci_scope.decide('push', event, SHA, 't', 'o/r')[0])

    def test_verified_run_must_match_workflow_sha_and_success(self):
        good = {'path': ci_scope.WORKFLOW, 'head_sha': SHA, 'conclusion': 'success'}
        for runs, expected in (([good], True), ([{**good, 'path': '.github/workflows/deploy.yml'}], False),
                               ([{**good, 'head_sha': 'c' * 40}], False), ([{**good, 'conclusion': 'failure'}], False), ([], False)):
            with mock.patch.object(ci_scope, 'api', return_value={'workflow_runs': runs}):
                self.assertEqual(ci_scope.verified_in_pull_request(SHA, 't', 'o/r'), expected)

    def test_compare_refuses_new_branches_and_truncation(self):
        self.assertIsNone(ci_scope.compare_files('0' * 40, SHA, 't', 'o/r'))
        self.assertIsNone(ci_scope.compare_files('', SHA, 't', 'o/r'))
        with mock.patch.object(ci_scope, 'api', return_value={'files': [{'filename': 'x.md'}] * 300}):
            self.assertIsNone(ci_scope.compare_files('b' * 40, SHA, 't', 'o/r'))

    def test_schedule_measures_and_failures_run_everything(self):
        self.assertEqual(ci_scope.decide('schedule', {}, SHA, 't', 'o/r')[:2], (True, True))
        self.assertEqual(ci_scope.decide('workflow_dispatch', {}, SHA, 't', 'o/r')[:2], (True, True))
        with tempfile.TemporaryDirectory() as folder:
            output, event = os.path.join(folder, 'out'), os.path.join(folder, 'event.json')
            with open(event, 'w', encoding='utf-8') as file:
                json.dump({'pull_request': {'number': 1}}, file)
            environment = {'GITHUB_EVENT_PATH': event, 'GITHUB_EVENT_NAME': 'pull_request', 'GITHUB_SHA': SHA,
                           'GITHUB_TOKEN': 't', 'GITHUB_REPOSITORY': 'o/r', 'GITHUB_OUTPUT': output}
            with mock.patch.dict(os.environ, environment), \
                 mock.patch.object(ci_scope, 'api', side_effect=OSError('network')):
                ci_scope.main()
            with open(output, encoding='utf-8') as file:
                self.assertEqual(file.read(), 'full=true\nmeasure=false\n')


if __name__ == '__main__':
    unittest.main()
