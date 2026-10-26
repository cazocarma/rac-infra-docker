"""Disposable PostgreSQL tests; never reads .env or connects to the DEV stack."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
NAME = 'rac-standing-test-' + uuid.uuid4().hex[:12]
SUBJECT = '10000000-0000-4000-8000-000000000001'
POLICY = '20000000-0000-4000-8000-000000000001'


def run(*args, input=None, ok=True):
    result = subprocess.run(args, input=input, text=True, capture_output=True)
    if ok and result.returncode:
        raise RuntimeError(result.stdout[-3000:] + result.stderr[-3000:])
    return result


def sql(statement, ok=True):
    return run('docker', 'exec', '-i', NAME, 'psql', '-X', '-v',
               'ON_ERROR_STOP=1', '-U', 'postgres', '-d', 'test', '-At',
               input=statement, ok=ok)


def change(event, version, status='suspended', restrictions='[]'):
    return (f"SELECT standing.change_account('{event}','{SUBJECT}',{version},"
            f"'{status}','{restrictions}'::jsonb,'{POLICY}');")


def state():
    return sql(f"SELECT status||':'||version FROM standing.account WHERE subject_id='{SUBJECT}';").stdout.strip()


try:
    run('docker', 'network', 'create', NAME)
    run('docker', 'run', '-d', '--name', NAME, '--network', NAME,
        '--tmpfs', '/var/lib/postgresql/data', '-e', 'POSTGRES_PASSWORD=test-only',
        '-e', 'POSTGRES_DB=test', 'postgis/postgis:16-3.4')
    for _ in range(60):
        if (run('docker', 'exec', NAME, 'pg_isready', '-U', 'postgres', ok=False).returncode == 0
                and 'PostgreSQL init process complete' in run('docker', 'logs', NAME).stdout):
            break
        time.sleep(1)
    else:
        raise RuntimeError('Disposable database did not start')
    run('docker', 'run', '--rm', '--network', NAME,
        '--mount', f'type=bind,source={ROOT / "db/migrations"},target=/flyway/sql,readonly',
        '-e', f'FLYWAY_URL=jdbc:postgresql://{NAME}:5432/test',
        '-e', 'FLYWAY_USER=postgres', '-e', 'FLYWAY_PASSWORD=test-only',
        '-e', 'FLYWAY_SCHEMAS=meta', '-e', 'FLYWAY_DEFAULT_SCHEMA=meta',
        'flyway/flyway:11.15.0-alpine', 'migrate')

    # New users receive exactly one baseline state in their creation transaction.
    sql(f"INSERT INTO usuario(id,nombre,correo,rol,keycloak_id) VALUES ('{SUBJECT}','Fixture','standing@example.test','cliente','standing-fixture');")
    assert state() == 'active:1'
    event = str(uuid.uuid4())
    # Without a provisioned audit principal, changing state is fully rolled back.
    assert sql(change(event, 1), ok=False).returncode
    assert state() == 'active:1'
    assert sql('SELECT count(*) FROM standing.outbox;').stdout.strip() == '0'
    # Test-only principal; runtime applications get no mutation grant.
    sql("INSERT INTO audit.chain_heads(chain_id) VALUES ('30000000-0000-4000-8000-000000000001');"
        "INSERT INTO audit.writer_principals VALUES ('postgres','40000000-0000-4000-8000-000000000001','30000000-0000-4000-8000-000000000001');")
    payload = json.loads(sql(change(event, 1)).stdout)
    assert payload['standing_version'] == 2
    assert payload['status'] == 'suspended'
    protected = {'submit_report', 'appeal', 'access_safety', 'cancel_own_booking',
                 'request_privacy', 'recover_account', 'accept_documents'}
    assert set(payload['effective_capabilities']) == protected
    assert json.loads(sql(change(event, 1)).stdout) == payload
    assert sql(change(event, 1, 'active'), ok=False).returncode
    assert sql(change(str(uuid.uuid4()), 1), ok=False).returncode
    assert state() == 'suspended:2'
    assert sql('SELECT count(*) FROM audit.log;').stdout.strip() == '1'

    # Validation failure cannot clear prior restrictions or partially change state.
    restriction = json.dumps([{'capability': 'send_message', 'starts_at': '2020-01-01T00:00:00Z', 'ends_at': None}])
    result = json.loads(sql(change(str(uuid.uuid4()), 2, 'restricted', restriction)).stdout)
    assert 'send_message' not in result['effective_capabilities']
    assert 'request_booking' in result['effective_capabilities']
    for bad in ['[null]', '[{}]', '[{"capability":"request_privacy","starts_at":"2020-01-01T00:00:00Z","ends_at":null}]',
                '[{"capability":"send_message","starts_at":"infinity","ends_at":null}]']:
        assert sql(change(str(uuid.uuid4()), 3, 'active', bad), ok=False).returncode
        assert state() == 'restricted:3'
        assert sql('SELECT count(*) FROM standing.restriction;').stdout.strip() == '1'

    # Two independent commands racing on one expected version: exactly one wins.
    commands = [change(str(uuid.uuid4()), 3, status) for status in ['active', 'banned']]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda command: sql(command, ok=False), commands))
    assert sum(r.returncode == 0 for r in results) == 1
    assert state().endswith(':4')
    assert sql('SELECT count(*) FROM audit.log;').stdout.strip() == '3'
    # Baseline-only lifecycle follows its user. Enforcement history prevents a
    # hard delete through the outbox FK (not a retention/bypass policy).
    assert sql(f"DELETE FROM usuario WHERE id='{SUBJECT}';", ok=False).returncode
    baseline = str(uuid.uuid4())
    sql(f"INSERT INTO usuario(id,nombre,correo,rol,keycloak_id) VALUES ('{baseline}','Fixture','baseline@example.test','cliente','baseline-fixture');")
    sql(f"DELETE FROM usuario WHERE id='{baseline}';")
    assert sql(f"SELECT count(*) FROM standing.account WHERE subject_id='{baseline}';").stdout.strip() == '0'
    assert sql('SELECT count(*) FROM standing.outbox;').stdout.strip() == '3'
    # Explicit rollback also rolls back audit, version, restrictions and event.
    before = state()
    sql('BEGIN;' + change(str(uuid.uuid4()), 4) + 'ROLLBACK;')
    assert state() == before
    assert sql('SELECT count(*) FROM audit.log;').stdout.strip() == '3'
    for role in ['rac_user', 'rac_match', 'rac_chat', 'rac_alert']:
        assert sql(f"SET ROLE {role}; " + change(str(uuid.uuid4()), 4), ok=False).returncode
    assert sql("SET ROLE rac_user; SELECT count(*) FROM standing.account;").returncode == 0
    assert sql("SET ROLE rac_user; UPDATE standing.account SET status='active';", ok=False).returncode
    assert sql("SET ROLE rac_backup; SELECT count(*) FROM standing.outbox;").returncode == 0
    print('PASS: baseline, audit rollback, idempotence, conflicts, restrictions, concurrency and grants')
finally:
    run('docker', 'rm', '-f', NAME, ok=False)
    run('docker', 'network', 'rm', NAME, ok=False)
