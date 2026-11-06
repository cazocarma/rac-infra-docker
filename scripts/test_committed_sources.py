import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from committed_sources import archive


class CommittedSourcesTest(unittest.TestCase):
    def test_frozen_archive_rejects_tampering_and_wrong_pin(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'sources/rac-admin-service'
            source.mkdir(parents=True)
            (root / 'archives').mkdir()
            path = root / 'archives/rac-admin-service.tar'
            data = b'synthetic source transport'
            path.write_bytes(data)
            revision = 'a' * 40
            (root / 'archive-manifest.json').write_text(json.dumps({source.name: {
                'revision': revision, 'sha256': hashlib.sha256(data).hexdigest()}}), encoding='utf-8')
            self.assertEqual(archive(source, revision), data)
            with self.assertRaises(ValueError):
                archive(source, 'b' * 40)
            path.write_bytes(data + b'tamper')
            with self.assertRaises(ValueError):
                archive(source, revision)

    def test_unproven_tree_and_placeholder_pin_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            for revision in ('0' * 40, 'not-a-revision', 'a' * 40):
                with self.assertRaises(ValueError):
                    archive(Path(temp) / 'rac-admin-service', revision)


if __name__ == '__main__':
    unittest.main()
