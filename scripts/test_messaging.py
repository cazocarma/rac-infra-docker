"""Isolated real PostgreSQL/RabbitMQ tests; never reads a deployed environment.

Only removes containers and a network with this invocation's random name.
"""
from pathlib import Path
import subprocess
import shutil
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parent.parent
NAME = 'rac-events-test-' + uuid.uuid4().hex[:12]
BROKER = 'rabbitmq:4.3.6-management@sha256:54cb013d76cd1fd6c0a0708f34062ad61c452bb6f016b434c6c33f1a765d2b58'


def run(*args, check=True):
    result = subprocess.run(args, capture_output=True, text=True, encoding='utf-8')
    if check and result.returncode:
        raise RuntimeError(result.stdout[-3000:] + result.stderr[-3000:])
    return result


def ready(command, seconds=120):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if run(*command, check=False).returncode == 0:
            return
        time.sleep(1)
    raise RuntimeError('Disposable messaging dependency did not become ready')


try:
    run('docker', 'network', 'create', NAME)
    run('docker', 'run', '-d', '--name', NAME + '-pg', '--network', NAME,
        '--tmpfs', '/var/lib/postgresql/data', '-e', 'POSTGRES_PASSWORD=test-only',
        '-e', 'POSTGRES_DB=rac_events_test', 'postgis/postgis:16-3.4')
    run('docker', 'run', '-d', '--name', NAME + '-mq', '--network', NAME, '--network-alias', 'rabbitmq',
        '--hostname', 'events-test', '-e', 'RABBITMQ_DEFAULT_USER=test',
        '-e', 'RABBITMQ_DEFAULT_PASS=test-only', BROKER)
    ready(['docker', 'exec', '--user', 'rabbitmq', NAME + '-mq', 'rabbitmq-diagnostics', '-q', 'ping'])
    for port in ('5672', '15672'):
        ready(['docker', 'exec', '--user', 'rabbitmq', NAME + '-mq', 'rabbitmq-diagnostics', '-q', 'check_port_listener', port])
    ready(['docker', 'exec', NAME + '-pg', 'pg_isready', '-U', 'postgres'])
    run('docker', 'run', '--rm', '--network', NAME, '--tmpfs', '/credentials',
        '--mount', f'type=bind,source={ROOT / "scripts"},target=/tools,readonly',
        '-e', 'RAC_DISPOSABLE_MESSAGING=1', '-e', 'RAC_ENV=dev',
        '-e', 'RABBITMQ_USER=test', '-e', 'RABBITMQ_PASSWORD=test-only',
        'python:3.13-slim', 'python', '/tools/test_messaging_topology.py')
    print('PASS: idempotent real broker topology, scoped role permissions and quorum dead-letter policies', flush=True)
    def migrate(directory):
        run('docker', 'run', '--rm', '--network', NAME,
            '--mount', f'type=bind,source={directory},target=/flyway/sql,readonly',
            '-e', f'FLYWAY_URL=jdbc:postgresql://{NAME}-pg:5432/rac_events_test',
            '-e', 'FLYWAY_USER=postgres', '-e', 'FLYWAY_PASSWORD=test-only',
            '-e', 'FLYWAY_SCHEMAS=meta', '-e', 'FLYWAY_DEFAULT_SCHEMA=meta',
            '-e', 'FLYWAY_TABLE=schema_history', '-e', 'FLYWAY_CONNECT_RETRIES=30',
            'flyway/flyway:11.15.0-alpine', 'migrate')
    def sql(statement):
        return run('docker','exec',NAME+'-pg','psql','-v','ON_ERROR_STOP=1','-U','postgres','-d','rac_events_test','-At','-c',statement).stdout.strip()
    with tempfile.TemporaryDirectory() as folder:
        for path in (ROOT / 'db/migrations').glob('V*.sql'):
            if int(path.name.split('__')[0][1:]) < 13:
                shutil.copyfile(path, Path(folder) / path.name)
        migrate(folder)
        sql("""INSERT INTO usuario(id,nombre,correo,rol,keycloak_id) VALUES
        ('00000000-0000-0000-0000-000000000001','Test','upgrade-one@example.test','cliente','upgrade-one'),
        ('00000000-0000-0000-0000-000000000002','Test','upgrade-two@example.test','compa','upgrade-two');
        INSERT INTO sesion(id,cliente_id,compa_id,fecha_inicio,fecha_fin,estado) VALUES
        (gen_random_uuid(),'00000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000002',now()+interval '30 days',now()+interval '30 days 1 hour','pendiente');
        UPDATE notificacion SET leido_en=now();""")
        before = sql('SELECT jsonb_agg(to_jsonb(n) ORDER BY id) FROM notificacion n')
        migrate(ROOT / 'db/migrations')
        after = sql("SELECT jsonb_agg(to_jsonb(n)-'evento_id'-'template_key'-'template_version'-'template_locale'-'template_legal_review' ORDER BY id) FROM notificacion n")
        assert before == after, 'Cutover changed historical notifications'
        assert sql('SELECT count(*) FROM notificacion WHERE num_nonnulls(template_key,template_version,template_locale,template_legal_review)<>0') == '0', 'Historical provenance was invented'
        for assignment in (
            "template_key='account.updated'",
            "template_key='account.updated',template_version='1',template_locale='fr',template_legal_review='pending'",
            "template_key='account.updated',template_version='1',template_locale='es',template_legal_review='unknown'",
            "template_key='INVALID KEY',template_version='1',template_locale='es',template_legal_review='pending'",
        ):
            try:
                sql('UPDATE notificacion SET ' + assignment)
            except RuntimeError as error:
                if 'notification_template_provenance_complete' not in str(error):
                    raise
            else:
                raise RuntimeError('Invalid notification template provenance was accepted')
        assert sql('SELECT count(*) FROM booking_outbox') == '0', 'Historical events were backfilled'
    print('PASS: V012 to V013 preserves notifications, read timestamps and creates no historical events', flush=True)
    for service in ('match', 'alert'):
        source = ROOT.parent / f'rac-{service}-service'
        result = run('docker', 'run', '--rm', '--network', NAME,
            '--mount', f'type=bind,source={source},target=/sources,readonly',
            '-v', 'rac-quota-go-cache:/go/pkg/mod', '-v', f'rac-{service}-go-build:/root/.cache/go-build',
            '-e', f'RAC_EVENTS_TEST_DATABASE_URL=postgres://postgres:test-only@{NAME}-pg:5432/rac_events_test?sslmode=disable',
            '-e', f'RAC_EVENTS_TEST_AMQP_URL=amqp://test:test-only@{NAME}-mq:5672/',
            'golang:1.27.2', 'sh', '-c', 'cp -a /sources /tmp/rac && cd /tmp/rac && go test -race -count=1 -v ./internal/events')
        if service == 'alert':
            for name in ('TestStandingNoticesPostgres', 'TestStandingNoticeRecoveryPostgresHTTP', 'TestStandingDiscoveryPagesPostgres', 'TestStandingNoticeBrokerRedelivery'):
                assert '--- PASS: ' + name in result.stdout, 'Required standing notification test did not run: ' + name
        print(result.stdout)
    print('PASS: transactional rollback, ordered concurrent relay, mandatory confirms, durable deduplication and ACK boundary')
finally:
    for suffix in ('-mq', '-pg'):
        run('docker', 'rm', '-f', '-v', NAME + suffix, check=False)
    run('docker', 'network', 'rm', NAME, check=False)
