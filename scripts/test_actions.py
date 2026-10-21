import tempfile
import unittest
from pathlib import Path
from check_actions import validate

class ActionsPolicyTests(unittest.TestCase):
    def test_rejects_regressions_in_action_runtime_and_runner(self):
        sha='a'*40
        pins={'actions/checkout':sha}
        runtimes={'actions/checkout':{'sha':sha,'runtime':'node24'}}
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);workflow=root/'.github/workflows/ci.yml'
            workflow.parent.mkdir(parents=True)
            valid='jobs:\n  test:\n    runs-on: ubuntu-24.04\n    steps:\n      - uses: actions/checkout@'+sha+'\n'
            workflow.write_text(valid)
            self.assertEqual(validate(root,pins,runtimes),[])
            for bad in (valid.replace(sha,'v7'),valid.replace('ubuntu-24.04','ubuntu-latest'),valid+'env:\n  FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true\n'):
                workflow.write_text(bad)
                self.assertTrue(validate(root,pins,runtimes))
            workflow.write_text(valid)
            self.assertTrue(validate(root,pins,{'actions/checkout':{'sha':sha,'runtime':'node20'}}))
            self.assertTrue(validate(root,pins,{}))
