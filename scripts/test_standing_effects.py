"""Focused identity/effect and populated-upgrade proof, disposable PostgreSQL only.

No .env, existing volumes or published ports. The broader permission suite still
proves non-superuser operator provisioning and dump/restore.
"""
from pathlib import Path
import shutil
import tempfile
import time
import uuid

from test_database_permissions import run
from standing_effects_fixture import verify
from standing_effect_upgrade_checks import check
from case_fixture import verify as verify_cases
from ts_effect_relay_fixture import verify as verify_relay

ROOT = Path(__file__).resolve().parents[1]


def main():
    name = 'rac-effect-identity-' + uuid.uuid4().hex[:12]

    def sql(database, statement, role='postgres', ok=True):
        return run('docker', 'exec', '-i', name, 'psql', '-X', '-v', 'ON_ERROR_STOP=1',
                   '-U', role, '-d', database, '-Atq', input=statement, ok=ok)

    def migrate(database, maximum=None, ok=True):
        with tempfile.TemporaryDirectory(prefix=name) as directory:
            for source in (ROOT / 'db/migrations').glob('V*.sql'):
                if maximum is None or int(source.name.split('__')[0][1:]) <= maximum:
                    shutil.copy2(source, Path(directory) / source.name)
            return run('docker', 'run', '--rm', '--network', name,
                       '--mount', f'type=bind,source={directory},target=/flyway/sql,readonly',
                       '-e', f'FLYWAY_URL=jdbc:postgresql://{name}:5432/{database}',
                       '-e', 'FLYWAY_USER=postgres', '-e', 'FLYWAY_PASSWORD=test-only',
                       '-e', 'FLYWAY_SCHEMAS=meta', '-e', 'FLYWAY_DEFAULT_SCHEMA=meta',
                       '-e', 'FLYWAY_TABLE=schema_history', '-e', 'FLYWAY_CLEAN_DISABLED=true',
                       'flyway/flyway:11.15.0-alpine', 'migrate', ok=ok)

    try:
        run('docker', 'network', 'create', name)
        run('docker', 'run', '-d', '--name', name, '--network', name,
            '--tmpfs', '/var/lib/postgresql/data', '-e', 'POSTGRES_PASSWORD=test-only',
            '-e', 'POSTGRES_DB=fresh', 'postgis/postgis:16-3.4')
        for _ in range(90):
            if (run('docker', 'exec', name, 'pg_isready', '-U', 'postgres', ok=False).returncode == 0
                    and 'PostgreSQL init process complete' in run('docker', 'logs', name).stdout):
                break
            time.sleep(1)
        else:
            raise RuntimeError('Disposable identity database did not become ready')
        migrate('fresh')
        for role in ('rac_user', 'rac_match', 'rac_chat', 'rac_alert'):
            sql('fresh', f'ALTER ROLE {role} LOGIN;')
            assert sql('fresh', 'SELECT 1;', role).stdout.strip() == '1', 'Negative role cannot connect'
        verify_cases(sql, 'fresh')
        verify_relay(sql, 'fresh')
        verify(sql, 'fresh')
        check(lambda database: sql('fresh', 'CREATE DATABASE ' + database + ';'), migrate,
              lambda database, statement: sql(database, statement).stdout.strip())
        print('PASS: canonical principal resolution, distinct and colliding namespaces, revocation isolation, exact replay, concurrent delivery and populated upgrades', flush=True)
    finally:
        run('docker', 'rm', '-f', name, ok=False)
        run('docker', 'network', 'rm', name, ok=False)


if __name__ == '__main__':
    main()
