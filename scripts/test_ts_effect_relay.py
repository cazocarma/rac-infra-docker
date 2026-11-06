"""T&S relay transaction/authority proof, disposable PostgreSQL and fake publisher.

No .env, existing data volume or published port. This is not an AMQP proof.
Go sources must be clean committed input and stream from Git into Linux, avoiding
the slow Windows bind-copy path and excluding untracked files or credentials.
"""
from pathlib import Path
import json
import subprocess
import time
import uuid

from test_database_permissions import run
from committed_sources import archive as committed_archive

ROOT = Path(__file__).resolve().parents[1]
FUNCTIONS = ('ts.effect_relay_ready()', 'ts.claim_effect(audit.reference)',
             'ts.confirm_effect(audit.reference)', 'ts.retry_effect(audit.reference)',
             'ts.effect_relay_backlog()')


def main():
    source = ROOT.parent / 'rac-admin-service'
    revision = json.loads((ROOT / 'ci/companion-revisions.json').read_text(encoding='utf-8'))['rac-admin-service']
    archive = committed_archive(source, revision)
    print('ADMIN SOURCE ' + revision, flush=True)
    name = 'rac-ts-relay-' + uuid.uuid4().hex[:12]
    password = 'synthetic-relay-' + uuid.uuid4().hex
    try:
        run('docker', 'network', 'create', name)
        run('docker', 'run', '-d', '--name', name, '--network', name,
            '--tmpfs', '/var/lib/postgresql/data', '-e', 'POSTGRES_PASSWORD=test-only',
            '-e', 'POSTGRES_DB=relay', 'postgis/postgis:16-3.4')
        for _ in range(90):
            if (run('docker', 'exec', name, 'pg_isready', '-U', 'postgres', ok=False).returncode == 0
                    and 'PostgreSQL init process complete' in run('docker', 'logs', name).stdout):
                break
            time.sleep(1)
        else:
            raise RuntimeError('Disposable relay database did not become ready')
        run('docker', 'run', '--rm', '--network', name,
            '--mount', f'type=bind,source={ROOT / "db/migrations"},target=/flyway/sql,readonly',
            '-e', f'FLYWAY_URL=jdbc:postgresql://{name}:5432/relay',
            '-e', 'FLYWAY_USER=postgres', '-e', 'FLYWAY_PASSWORD=test-only',
            '-e', 'FLYWAY_SCHEMAS=meta', '-e', 'FLYWAY_DEFAULT_SCHEMA=meta',
            '-e', 'FLYWAY_TABLE=schema_history', 'flyway/flyway:11.15.0-alpine', 'migrate')
        grants = f"CREATE ROLE rac_ts_effect_relay_lab LOGIN PASSWORD '{password}'; GRANT USAGE ON SCHEMA ts,audit TO rac_ts_effect_relay_lab;"
        grants += ''.join('GRANT EXECUTE ON FUNCTION ' + function + ' TO rac_ts_effect_relay_lab;' for function in FUNCTIONS)
        run('docker', 'exec', '-i', name, 'psql', '-X', '-v', 'ON_ERROR_STOP=1', '-U', 'postgres', '-d', 'relay', input=grants)
        command = ['docker', 'run', '--rm', '-i', '--name', name + '-go', '--network', name,
                   '-v', 'rac-quota-go-cache:/go/pkg/mod', '-v', 'rac-quota-go-build:/root/.cache/go-build',
                   '-e', 'RAC_DISPOSABLE_TS_RELAY=1',
                   '-e', f'RAC_TS_RELAY_ROOT_DATABASE_URL=postgres://postgres:test-only@{name}:5432/relay?sslmode=disable',
                   '-e', f'RAC_TS_RELAY_TEST_DATABASE_URL=postgres://rac_ts_effect_relay_lab:{password}@{name}:5432/relay?sslmode=disable',
                   'golang:1.27.3', 'sh', '-c',
                   'mkdir /app && tar -xf - -C /app && cd /app && go test -mod=vendor -race -count=1 -v ./internal/tsrelay && go vet -mod=vendor ./internal/tsrelay']
        result = subprocess.run(command, input=archive, capture_output=True, timeout=300)
        output = (result.stdout + result.stderr).decode('utf-8', errors='replace')
        if result.returncode:
            raise RuntimeError('Relay proof failed\n' + output[-6000:].replace(password, '[synthetic-password]'))
        for test in ('TestRelayPostgres', 'TestRelayPostgres/ordering-retry-and-independent-subject',
                     'TestRelayPostgres/transaction-fence-and-abandoned-claim',
                     'TestRelayPostgres/confirmation-followed-by-database-cancellation',
                     'TestRelayPostgres/producer-order-across-cases-before-commit',
                     'TestRelayPostgres/source-and-authority-boundary'):
            assert '--- PASS: ' + test in output, 'Mandatory relay case did not execute: ' + test
        print('PASS: function-only Go relay, per-subject order, independent progress, exact retry, backoff, transaction fencing, abandoned claim recovery, cancellation and immutable source; race/vet clean', flush=True)
        print('Fake publisher only; AMQP confirmation, scoped broker credentials and runtime activation remain separate gates', flush=True)
    finally:
        run('docker', 'rm', '-f', name + '-go', name, ok=False)
        run('docker', 'network', 'rm', name, ok=False)


if __name__ == '__main__':
    main()
