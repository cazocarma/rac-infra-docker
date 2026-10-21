import json
from types import SimpleNamespace
import unittest
from build_dev import build


class WorkstationBuilds(unittest.TestCase):
    def test_serial_builds_exclude_tools_and_never_build_release(self):
        model = {'name': 'rac-dev', 'services': {'api': {'build': '.'}, 'web': {'build': '.'},
            'postgres': {'image': 'postgres'}, 'fixture': {'profiles': ['tests'], 'build': '.'}}}
        calls = []
        def run(command, **kwargs):
            calls.append(command)
            return SimpleNamespace(stdout=json.dumps(model))
        build(['docker', 'compose'], run)
        self.assertEqual(calls[1:], [['docker','compose','build','api'], ['docker','compose','build','web']])
        model['name'] = 'rac-prd'; calls.clear()
        with self.assertRaisesRegex(RuntimeError, 'DEV-only'):
            build(['docker','compose'],run)
        self.assertEqual(len(calls), 1)
