from pathlib import Path
import tempfile
import unittest
from database_roles import ROLES, validate_credentials
from init_database_credentials import initialize


class DatabaseCredentials(unittest.TestCase):
    def test_versioned_examples_are_never_secret_targets(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'.env.dev.example'
            content='RAC_ENV=dev\nPOSTGRES_DB=fixture\n'
            path.write_text(content)
            with self.assertRaises(RuntimeError): initialize(path)
            self.assertEqual(path.read_text(),content)

    def test_dev_initialization_is_idempotent_and_preserves_other_settings(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'dev.env'
            path.write_text('# preserve comment\nRAC_ENV=dev\nPOSTGRES_DB=rentacompa\nDATABASE_URL=postgres://old\nMIGRATION_DB_USER=postgres\nMIGRATION_DB_PASSWORD=old\nCUSTOM=keep\n')
            initialize(path)
            first = path.read_text()
            initialize(path)
            self.assertEqual(first, path.read_text())
            self.assertIn('# preserve comment', first)
            self.assertIn('CUSTOM=keep', first)
            self.assertNotIn('\nDATABASE_URL=', first)
            values = dict(line.split('=', 1) for line in first.splitlines() if '=' in line and not line.startswith('#'))
            credentials = validate_credentials(values)
            self.assertEqual(len(set(credentials.values())), len(ROLES) + 1)
            for key, value in [('USER_DB_URL', values['CHAT_DB_URL']), ('MIGRATION_DB_USER','postgres'), ('MIGRATION_DB_PASSWORD','short')]:
                with self.assertRaises(RuntimeError):
                    validate_credentials({**values, key: value})
            for key in ROLES:
                bad = values[key].replace('@postgres:', '@foreign:')
                with self.assertRaises(RuntimeError):
                    validate_credentials({**values, key: bad})

    def test_qa_generation_is_rejected_without_writing(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'qa.env'
            content='RAC_ENV=qa\nPOSTGRES_DB=rac_qa\n'
            path.write_text(content)
            with self.assertRaises(RuntimeError):
                initialize(path)
            self.assertEqual(content, path.read_text())
