from pathlib import Path
import tempfile
import unittest

from check_python_syntax import check


class PythonSyntaxGate(unittest.TestCase):
    def test_gate_detects_nested_indent_before_any_tool_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'scripts').mkdir()
            (root / 'tools/fixture').mkdir(parents=True)
            # compile() must not run imports or top-level actions.
            (root / 'tools/fixture/valid.py').write_text('raise RuntimeError("must not run")\n', encoding='utf-8')
            bad = root / 'scripts/migrations.py'
            bad.write_text('if True:\n    pass\n      assert True\n', encoding='utf-8')
            count, errors = check(root)
            self.assertEqual(count, 2)
            self.assertEqual(errors, ['scripts/migrations.py:3: invalid Python syntax'])
            bad.write_text('if True:\n    pass\n    assert True\n', encoding='utf-8')
            self.assertEqual(check(root), (2, []))

    def test_empty_checkout_does_not_claim_success(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(check(Path(directory)), (0, ['No repository Python tools found']))


if __name__ == '__main__':
    unittest.main()
