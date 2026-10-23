"""Exercise the real backup credential boundary without storage SDKs or I/O."""
from pathlib import Path
import os
import runpy
import sys
import unittest
from unittest.mock import MagicMock, patch


class BackupIdentity(unittest.TestCase):
    def test_backup_never_falls_back_to_operator_credentials(self):
        # Only third-party adapters/Unix lock import are mocked. The actual
        # configure_backup_identity function runs unchanged on Windows and CI.
        adapters = {name: MagicMock() for name in ('fcntl','boto3','psycopg','botocore','botocore.config')}
        with patch.dict(sys.modules, adapters):
            module = runpy.run_path(str(Path(__file__).with_name('backup.py')))
        configure = module['configure_backup_identity']
        with patch.dict(os.environ, {'PGDATABASE':'fixture','PGUSER':'operator','PGPASSWORD':'operator-canary'}, clear=True):
            for url in ('', 'postgres://postgres:secret@postgres/fixture',
                        'postgres://rac_backup:secret@foreign/fixture',
                        'postgres://rac_backup@postgres/fixture',
                        'postgres://rac_backup:secret@postgres/other'):
                os.environ['BACKUP_DB_URL'] = url
                with self.assertRaises(RuntimeError) as caught:
                    configure()
                self.assertNotIn('secret', str(caught.exception))
                self.assertNotIn('operator-canary', str(caught.exception))
            os.environ['BACKUP_DB_URL']='postgresql://rac_backup:synthetic-backup-password@postgres:5432/fixture?sslmode=disable'
            configure()
            self.assertEqual(os.environ['PGUSER'],'rac_backup')
            self.assertEqual(os.environ['PGPASSWORD'],'synthetic-backup-password')
