from pathlib import Path
import tempfile
import unittest
from check_local_revisions import mismatches, CONSUMERS, MODULE
from check_ci_access import REPOSITORIES


class LocalRevisions(unittest.TestCase):
    def test_candidate_rejects_dirty_heads_vendor_and_tag_mismatch(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            refs = {name:'a' * 40 for name in REPOSITORIES}
            for name in CONSUMERS:
                path = root / name
                (path / 'vendor').mkdir(parents=True)
                # go.mod permits both single-line require and a require block.
                (path / 'go.mod').write_text(('require ' + MODULE + ' v0.13.0\n') if name == CONSUMERS[0]
                                            else ('require (\n' + MODULE + ' v0.13.0\n)\n'))
                (path / 'vendor/modules.txt').write_text('# ' + MODULE + ' v0.13.0\n')
            state = {'dirty':False, 'stale':False, 'tag':False}
            def reader(path, *arguments):
                if arguments[0] == 'status':
                    return ' M modified' if state['dirty'] else ''
                if arguments[-1].endswith('^{commit}'):
                    return ('b' if state['tag'] else 'a') * 40
                return ('b' if state['stale'] else 'a') * 40
            self.assertEqual(mismatches(refs, root, reader), [])
            for field in state:
                state[field] = True
                self.assertTrue(mismatches(refs, root, reader), field)
                state[field] = False
            vendor = root / CONSUMERS[0] / 'vendor/modules.txt'
            vendor.write_text('# ' + MODULE + ' v0.12.0\n')
            self.assertTrue(mismatches(refs, root, reader))
            vendor.write_text('# ' + MODULE + ' v0.13.0\n')
            module = root / CONSUMERS[0] / 'go.mod'
            original = module.read_text()
            module.write_text(original + 'replace ' + MODULE + ' => ../platform\n')
            self.assertTrue(mismatches(refs, root, reader))
            module.write_text(original.replace('v0.13.0', 'v0.12.0'))
            self.assertTrue(mismatches(refs, root, reader))
