"""Real AMQP relay proof; isolated broker, synthetic scoped account, no ports."""
from pathlib import Path
import json
import subprocess
import time
import uuid

from committed_sources import archive
from test_database_permissions import run

ROOT = Path(__file__).resolve().parents[1]
BROKER = 'rabbitmq:4.3.6-management@sha256:54cb013d76cd1fd6c0a0708f34062ad61c452bb6f016b434c6c33f1a765d2b58'


def main():
    revision = json.loads((ROOT / 'ci/companion-revisions.json').read_text())['rac-admin-service']
    source = archive(ROOT.parent / 'rac-admin-service', revision)
    name = 'rac-ts-broker-' + uuid.uuid4().hex[:12]
    password = 'synthetic-' + uuid.uuid4().hex
    try:
        run('docker', 'network', 'create', name)
        run('docker', 'run', '-d', '--name', name, '--network', name,
            '--tmpfs', '/var/lib/rabbitmq:uid=999,gid=999,mode=0700', '-e', 'RABBITMQ_DEFAULT_USER=lab',
            '-e', 'RABBITMQ_DEFAULT_PASS=' + password, BROKER)
        for _ in range(60):
            if run('docker', 'inspect', '--format', '{{.State.Running}}', name).stdout.strip() != 'true':
                raise RuntimeError('Disposable broker exited before readiness')
            if run('docker', 'exec', '--user', 'rabbitmq', name, 'rabbitmq-diagnostics', '-q', 'check_port_connectivity', ok=False).returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError('Disposable broker did not become ready')
        for _ in range(30):
            declared = run('docker', 'exec', name, 'rabbitmqadmin', '-u', 'lab', '-p', password,
                           '--timeout', '3', 'exchanges', 'declare', '--name', 'rac.trust_safety',
                           '--type', 'topic', '--durable', 'true', '--auto-delete', 'false', ok=False)
            if declared.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError('Disposable broker management API did not become ready')
        run('docker', 'exec', '--user', 'rabbitmq', name, 'rabbitmqctl', 'add_user', 'relay', password)
        run('docker', 'exec', '--user', 'rabbitmq', name, 'rabbitmqctl', 'set_permissions', '-p', '/', 'relay',
            '^$', '^rac[.]trust_safety$', '^$')
        run('docker', 'exec', '--user', 'rabbitmq', name, 'rabbitmqctl', 'set_topic_permissions', '-p', '/', 'relay',
            'rac.trust_safety', '^ts[.]action[.]effective[.]v1$', '^$')
        command = ['docker', 'run', '--rm', '-i', '--name', name + '-go', '--network', name,
                   '-v', 'rac-quota-go-build:/root/.cache/go-build',
                   '-e', 'RAC_DISPOSABLE_TS_BROKER=1',
                   '-e', f'RAC_TS_RELAY_BROKER_TEST_URL=amqp://lab:{password}@{name}:5672/',
                   '-e', f'RAC_TS_RELAY_PUBLISHER_TEST_URL=amqp://relay:{password}@{name}:5672/',
                   'golang:1.27.3', 'sh', '-c',
                   'mkdir /app && tar -xf - -C /app && cd /app && '
                   'test -z "$(gofmt -l internal/tsrelay/rabbit*.go)" && '
                   'go test -mod=vendor -race -count=1 -v ./internal/tsrelay -run TestRabbit && '
                   'go vet -mod=vendor ./internal/tsrelay']
        result = subprocess.run(command, input=source, capture_output=True, timeout=300)
        output = (result.stdout + result.stderr).decode(errors='replace').replace(password, '[synthetic]')
        if result.returncode:
            raise RuntimeError(f'Real broker proof failed (exit {result.returncode})\n' + output[-6000:])
        for case in ('TestRabbitHandshakeCancellation', 'TestRabbitRealBroker'):
            assert '--- PASS: ' + case in output, 'Mandatory case missing: ' + case
        print(output, flush=True)
        print('PASS: real quorum queue, mandatory return rejection, persistent confirmed messages, stable duplicate identity, scoped publisher and bounded handshake cancellation; admin ' + revision, flush=True)
    finally:
        run('docker', 'rm', '-f', name + '-go', name, ok=False)
        run('docker', 'network', 'rm', name, ok=False)


if __name__ == '__main__':
    main()
