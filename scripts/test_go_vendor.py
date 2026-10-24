from pathlib import Path
import tempfile
import unittest
from check_go_vendor import check, MODULE


class VendorIntegrityTests(unittest.TestCase):
    def test_pinned_sources_and_tampering(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            platform = root / 'rac-platform'
            (platform / 'standing').mkdir(parents=True)
            (platform / 'go.mod').write_text('module ' + MODULE + '\n')
            (platform / 'standing/rules.go').write_text('package standing\nconst Deny = true\n')
            for name in ('rac-user-service', 'rac-match-service', 'rac-chat-service', 'rac-alert-service'):
                service = root / name
                generated = service / 'vendor' / MODULE / 'standing'
                generated.mkdir(parents=True)
                (service / 'go.mod').write_text('require (\n' + MODULE + ' v0.3.0\n)\n')
                (service / 'vendor/modules.txt').write_text('# ' + MODULE + ' v0.3.0\n')
                (generated / 'rules.go').write_text('package standing\nconst Deny = true\n')
            check(root)
            file = root / 'rac-user-service/vendor' / MODULE / 'standing/rules.go'
            file.write_text('package standing\nconst Deny = false\n')
            with self.assertRaisesRegex(ValueError, 'differs'):
                check(root)
            file.write_text('package standing\nconst Deny = true\n')
            (platform / 'standing/new_rule.go').write_text('package standing\n')
            with self.assertRaisesRegex(ValueError, 'source set'):
                check(root)


if __name__ == '__main__':
    unittest.main()
