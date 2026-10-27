import unittest
import yaml
from check_workflow_context import validate


class WorkflowContexts(unittest.TestCase):
    def fixture(self):
        return yaml.safe_load("""
jobs:
  migrations:
    steps:
      - uses: actions/checkout@fixture
        with:
          path: rac-infra-docker
      - run: python -m unittest discover -s scripts -p test_ci_access.py
""")

    def test_reproduces_actual_missing_working_directory(self):
        workflow = self.fixture()
        self.assertEqual(len(validate(workflow)), 1)
        workflow['jobs']['migrations']['defaults'] = {'run': {'working-directory': 'rac-infra-docker'}}
        self.assertEqual(validate(workflow), [])
        # A future step inherits the same directory without copying metadata.
        workflow['jobs']['migrations']['steps'].append({'run': 'python scripts/check_actions.py'})
        self.assertEqual(validate(workflow), [])

    def test_step_override_wins_over_job_and_global_defaults(self):
        workflow = self.fixture()
        workflow['defaults'] = {'run': {'working-directory': 'rac-infra-docker'}}
        self.assertEqual(validate(workflow), [])
        job = workflow['jobs']['migrations']
        job['defaults'] = {'run': {'working-directory': 'wrong'}}
        self.assertTrue(validate(workflow))
        job['steps'][-1]['working-directory'] = 'rac-infra-docker'
        self.assertEqual(validate(workflow), [])
        job['steps'][-1]['working-directory'] = '.'
        self.assertTrue(validate(workflow))

    def test_root_checkout_and_nonlocal_steps(self):
        workflow = self.fixture()
        del workflow['jobs']['migrations']['steps'][0]['with']['path']
        self.assertEqual(validate(workflow), [])
        workflow['jobs']['migrations']['steps'].append({'run': 'docker version', 'working-directory': 'other'})
        self.assertEqual(validate(workflow), [])

    def test_script_before_checkout_is_rejected(self):
        workflow = self.fixture()
        workflow['jobs']['migrations']['steps'].reverse()
        self.assertTrue(validate(workflow))
