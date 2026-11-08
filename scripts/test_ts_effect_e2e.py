"""P11 end-to-end effect transport in disposable containers. Synthetic data only.

Case action -> ts.outbox -> admin ts-relay worker -> RabbitMQ (topology from
configure_messaging.py with RAC_TS_MESSAGING=1) -> user ts-effects consumer ->
standing.change_account. Creates its own network, volumes, PostgreSQL and
broker; reads no .env, publishes no port and touches no existing volume.
Companion sources are the committed HEADs of the sibling checkouts unless
pinned revisions are given through RAC_TS_E2E_ADMIN / RAC_TS_E2E_USER.
"""
import json
import os
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from committed_sources import archive
from test_database_permissions import run

ROOT = Path(__file__).resolve().parents[1]
BROKER = 'rabbitmq:4.3.6-management@sha256:54cb013d76cd1fd6c0a0708f34062ad61c452bb6f016b434c6c33f1a765d2b58'
GO = 'golang:1.27.3'
REF = 'audit.reference,audit.reference,audit.reference'
# Customer intake has no provisioning adapter yet; the staff console, relay and
# consumer logins come from the real DEV provisioning code (ts_database.py).
LOGINS = {
    'rac_ts_intake_e2e': [f'ts.report_submit({REF},text,uuid,audit.reference,text,uuid)'],
}
PROVISIONED = ('rac_ts_cases', 'rac_ts_intake', 'rac_ts_relay', 'rac_ts_effects')
PROVISION = (
    'import os, psycopg, ts_database as t\n'
    'with psycopg.connect() as db:\n'
    '    for role, (variable, _, _) in t.LOGINS.items():\n'
    '        t.provision(db, os.environ[variable], "rac", role)\n'
    'for role, (variable, _, _) in t.LOGINS.items():\n'
    '    with psycopg.connect(os.environ[variable]) as login:\n'
    '        t.verify(login, role)\n'
)


def head(repository):
    return subprocess.check_output(['git', '-C', str(repository), 'rev-parse', 'HEAD'], text=True).strip()


def main():
    name = 'rac-ts-e2e-' + uuid.uuid4().hex[:12]
    database, broker = name + '-db', name + '-mq'
    volumes = {key: name + '-' + key for key in ('credentials', 'admin', 'user')}
    tools = name + '-tools'
    passwords = {role: 'synthetic-' + uuid.uuid4().hex for role in (*LOGINS, *PROVISIONED, 'broker')}
    admin_dir, user_dir = ROOT.parent / 'rac-admin-service', ROOT.parent / 'rac-user-service'
    revisions = {'admin': os.environ.get('RAC_TS_E2E_ADMIN') or head(admin_dir),
                 'user': os.environ.get('RAC_TS_E2E_USER') or head(user_dir)}
    workers = []
    try:
        run('docker', 'network', 'create', name)
        for volume in volumes.values():
            run('docker', 'volume', 'create', volume)
        run('docker', 'run', '-d', '--name', database, '--network', name, '--network-alias', 'postgres',
            '--tmpfs', '/var/lib/postgresql/data', '-e', 'POSTGRES_PASSWORD=test-only', '-e', 'POSTGRES_DB=rac',
            'postgis/postgis:16-3.4')
        run('docker', 'run', '-d', '--name', broker, '--network', name, '--network-alias', 'rabbitmq',
            '--tmpfs', '/var/lib/rabbitmq:uid=999,gid=999,mode=0700', '-e', 'RABBITMQ_DEFAULT_USER=e2e-admin',
            '-e', 'RABBITMQ_DEFAULT_PASS=' + passwords['broker'], BROKER)
        for _ in range(90):
            if (run('docker', 'exec', database, 'pg_isready', '-U', 'postgres', ok=False).returncode == 0
                    and 'PostgreSQL init process complete' in run('docker', 'logs', database).stdout):
                break
            time.sleep(1)
        else:
            raise RuntimeError('Disposable database did not start')
        time.sleep(2)
        run('docker', 'run', '--rm', '--network', name,
            '--mount', f'type=bind,source={ROOT / "db/migrations"},target=/flyway/sql,readonly',
            '-e', 'FLYWAY_URL=jdbc:postgresql://postgres:5432/rac', '-e', 'FLYWAY_USER=postgres',
            '-e', 'FLYWAY_PASSWORD=test-only', '-e', 'FLYWAY_SCHEMAS=meta', '-e', 'FLYWAY_DEFAULT_SCHEMA=meta',
            '-e', 'FLYWAY_TABLE=schema_history', 'flyway/flyway:11.15.0-alpine', 'migrate')

        def sql(statement, role='postgres'):
            result = subprocess.run(['docker', 'exec', '-i', database, 'psql', '-X', '-q', '-At', '-v', 'ON_ERROR_STOP=1',
                                     '-U', role, '-d', 'rac'], input=statement, text=True, capture_output=True, timeout=120)
            if result.returncode:
                raise RuntimeError('Disposable SQL failed: ' + result.stderr[-1500:])
            return result.stdout.strip()

        statements = []
        for role, functions in LOGINS.items():
            statements.append(f"CREATE ROLE {role} LOGIN PASSWORD '{passwords[role]}';GRANT CONNECT ON DATABASE rac TO {role};"
                              f"GRANT USAGE ON SCHEMA ts,standing,audit TO {role};")
            statements += [f'GRANT EXECUTE ON FUNCTION {f} TO {role};' for f in functions]
            statements.append("DO $$DECLARE c uuid:=gen_random_uuid(); BEGIN INSERT INTO audit.chain_heads(chain_id) VALUES(c);"
                              f" INSERT INTO audit.writer_principals(database_role,actor_id,chain_id) VALUES('{role}',gen_random_uuid(),c); END$$;")
        sql(''.join(statements))
        run('docker', 'build', '-q', '-t', tools, '-f', str(ROOT / 'tools/Dockerfile'), str(ROOT))
        urls = []
        from ts_database import LOGINS as TS_LOGINS
        for role, (variable, _, _) in TS_LOGINS.items():
            urls += ['-e', f'{variable}=postgresql://{role}:{passwords[role]}@postgres:5432/rac?sslmode=disable']
        for _ in range(2):  # Idempotent: the second run reconciles without new principals.
            run('docker', 'run', '--rm', '--network', name, '-e', 'PGHOST=postgres', '-e', 'PGUSER=postgres',
                '-e', 'PGPASSWORD=test-only', '-e', 'PGDATABASE=rac', *urls, tools, 'python', '-c', PROVISION)
        assert sql("SELECT count(*) FROM audit.writer_principals WHERE database_role IN('rac_ts_cases','rac_ts_intake','rac_ts_relay','rac_ts_effects');") == '4'

        # Broker topology and scoped credentials come from the real bootstrap.
        for _ in range(90):
            if run('docker', 'exec', '--user', 'rabbitmq', broker, 'rabbitmq-diagnostics', '-q', 'check_port_listener', '15672', ok=False).returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError('Disposable broker did not start')
        run('docker', 'run', '--rm', '--network', name, '-v', volumes['credentials'] + ':/credentials',
            '--mount', f'type=bind,source={ROOT / "scripts"},target=/tools,readonly',
            '-e', 'RAC_ENV=dev', '-e', 'RAC_TS_MESSAGING=1', '-e', 'RABBITMQ_USER=e2e-admin',
            '-e', 'RABBITMQ_PASSWORD=' + passwords['broker'], 'python:3.13-slim', 'python', '/tools/configure_messaging.py')

        subject, reporter, lead, agent, policy = (str(uuid.uuid4()) for _ in range(5))
        account = sql(f"INSERT INTO usuario(id,nombre,correo,rol,keycloak_id) VALUES(gen_random_uuid(),'E2E fixture','{subject}@example.test','compa','{subject}') RETURNING id;")
        sql(f"SELECT ts.report_submit(gen_random_uuid(),'{reporter}','{policy}','account','{subject}','{subject}','harassment',NULL);", 'rac_ts_intake_e2e')
        case = sql(f"SELECT case_id FROM ts.reports WHERE reporter='{reporter}';")
        sql(f"SELECT ts.case_assign(gen_random_uuid(),'{lead}','{policy}','{case}','{agent}');", 'rac_ts_cases')
        action = json.loads(sql(f"SELECT ts.action_propose(gen_random_uuid(),'{agent}','{policy}','{case}','restrict_publish','harassment_repeat','actions-e2e-1',NULL,'actionRestrict');", 'rac_ts_cases'))['action_id']

        for key, directory in (('admin', admin_dir), ('user', user_dir)):
            source = archive(directory, revisions[key])
            subprocess.run(['docker', 'run', '--rm', '-i', '-v', volumes[key] + ':/app', GO, 'tar', '-xf', '-', '-C', '/app'],
                           input=source, check=True, capture_output=True, timeout=300)
        with tempfile.TemporaryDirectory(prefix='rac-ts-e2e-') as secrets:
            folder = Path(secrets)
            files = {
                'relay-db': f'postgres://rac_ts_relay:{passwords["rac_ts_relay"]}@postgres:5432/rac?sslmode=disable',
                'effects-db': f'postgres://rac_ts_effects:{passwords["rac_ts_effects"]}@postgres:5432/rac?sslmode=disable',
            }
            for file, value in files.items():
                (folder / file).write_text(value, encoding='utf-8')
                (folder / file).chmod(0o444)
            folder.chmod(0o755)
            common = ['--network', name, '-v', 'rac-quota-go-build:/root/.cache/go-build',
                      '--mount', f'type=bind,source={folder},target=/secrets,readonly',
                      '-v', volumes['credentials'] + ':/credentials:ro', '-e', 'RAC_ENV=dev']
            run('docker', 'run', '-d', '--name', name + '-relay', *common, '-v', volumes['admin'] + ':/app', '-w', '/app',
                '-e', 'TS_RELAY_ENABLED=true', '-e', 'TS_RELAY_DATABASE_URL_FILE=/secrets/relay-db',
                '-e', 'TS_RELAY_AMQP_URL_FILE=/credentials/ts-publisher/url', GO, 'go', 'run', '-mod=vendor', './cmd/ts-relay')
            workers.append(name + '-relay')
            run('docker', 'run', '-d', '--name', name + '-effects', *common, '-v', volumes['user'] + ':/app', '-w', '/app',
                '-e', 'TS_EFFECTS_ENABLED=true', '-e', 'TS_EFFECTS_POLICY_VERSION=' + policy,
                '-e', 'TS_EFFECTS_DATABASE_URL_FILE=/secrets/effects-db',
                '-e', 'TS_EFFECTS_AMQP_URL_FILE=/credentials/ts-user/url', '-e', 'TS_EFFECTS_REFRESH_SECONDS=5',
                GO, 'go', 'run', '-mod=vendor', './cmd/ts-effects')
            workers.append(name + '-effects')

            def wait(expected, budget=420):
                for _ in range(budget // 2):
                    status = sql(f"SELECT status FROM standing.account WHERE subject_id='{account}';")
                    if status == expected:
                        return
                    for worker in workers:
                        if run('docker', 'inspect', '--format', '{{.State.Running}}', worker).stdout.strip() != 'true':
                            tail = run('docker', 'logs', '--tail', '20', worker, ok=False)
                            raise RuntimeError(worker + ' exited: ' + ' | '.join((tail.stdout + tail.stderr).splitlines()[-20:]))
                    time.sleep(2)
                raise RuntimeError(f'Standing did not reach {expected}; last {status}')

            wait('restricted')
            restricted = sql(f"SELECT string_agg(capability,',') FROM standing.restriction WHERE subject_id='{account}';")
            assert restricted == 'publish_listing', restricted
            sql(f"SELECT ts.action_revoke(gen_random_uuid(),'{agent}','{policy}','{action}','restriction_withdrawn');", 'rac_ts_cases')
            wait('active', budget=120)
            # A timed restriction that runs out is lifted by the worker's expiry
            # sweep, with no further event. Age it instead of waiting an hour.
            timed = json.loads(sql(f"SELECT ts.action_propose(gen_random_uuid(),'{agent}','{policy}','{case}','restrict_booking','harassment_repeat','actions-e2e-1',1,'actionRestrict');", 'rac_ts_cases'))['action_id']
            wait('restricted')
            sql(f"SET session_replication_role=replica; UPDATE standing.ts_effects SET starts_at=starts_at-interval '2 hours',"
                f"ends_at=ends_at-interval '2 hours' WHERE action_id='{timed}';")
            wait('active', budget=120)
        pending = sql('SELECT count(*) FROM ts.effect_delivery_state WHERE confirmed_at IS NULL;')
        effects = sql(f"SELECT count(*) FROM standing.ts_effects WHERE subject_id='{account}';")
        failed = run('docker', 'exec', '--user', 'rabbitmq', broker, 'rabbitmqctl', '-q', '-p', 'rac-dev', 'list_queues', 'name', 'messages').stdout
        assert pending == '0' and effects == '3', (pending, effects)
        assert any(line.split() == ['rac.user.ts_effects.failed', '0'] for line in failed.splitlines()), failed
        for worker in workers:
            logs = run('docker', 'logs', worker, ok=False)
            text = logs.stdout + logs.stderr
            for secret in [subject, account, *passwords.values()]:
                assert secret not in text, 'Worker log exposed a subject or credential'
        print('PASS: case action -> ts.outbox -> relay worker -> RabbitMQ quorum queue -> effects consumer -> standing '
              f'restricted then active after revocation, timed restriction lifted by the expiry sweep, no pending delivery, empty failed queue, no subjects or credentials '
              f'in worker logs; admin {revisions["admin"]} user {revisions["user"]}', flush=True)
    finally:
        run('docker', 'rm', '-f', *workers, database, broker, ok=False)
        run('docker', 'image', 'rm', '-f', tools, ok=False)
        run('docker', 'network', 'rm', name, ok=False)
        for volume in volumes.values():
            # Only the exact per-run volumes created above.
            run('docker', 'volume', 'rm', volume, ok=False)


if __name__ == '__main__':
    main()
