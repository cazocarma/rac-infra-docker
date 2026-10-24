"""Full standing Compose lab. Never reads .env or targets an existing project."""
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import time
import uuid

from init_database_credentials import initialize

ROOT = Path(__file__).resolve().parents[1]
APIS = ('backend-user', 'backend-match', 'backend-chat', 'backend-alert')
WORKERS = ('standing-events-relay', 'standing-match-consumer',
           'standing-alert-consumer', 'booking-events-relay', 'alert-events-consumer')


def validate_model(model, project):
    """Fail before builds/start/cleanup if a lab can touch existing resources."""
    if not re.fullmatch(r'rac-standing-e2e-[0-9a-f]{12}', project) or model.get('name') != project:
        raise RuntimeError('Disposable project isolation required')
    for service in model['services'].values():
        if service.get('ports') or service.get('network_mode') or service.get('container_name') or service.get('privileged'):
            raise RuntimeError('Standing lab cannot publish or share host resources')
        if any(mount['type'] == 'bind' and not mount.get('read_only') for mount in service.get('volumes', [])):
            raise RuntimeError('Standing lab cannot write host files')
    for volume in model['volumes'].values():
        if volume.get('external') or volume.get('driver_opts') or not volume['name'].startswith(project + '_'):
            raise RuntimeError('Standing lab cannot use an existing volume')
    for network in model.get('networks', {}).values():
        if network.get('external') or not network['name'].startswith(project + '_'):
            raise RuntimeError('Standing lab cannot join an existing network')
    if model.get('secrets') or model.get('configs'):
        raise RuntimeError('Standing lab cannot import external configuration')


def main():
    project = 'rac-standing-e2e-' + uuid.uuid4().hex[:12]
    with tempfile.TemporaryDirectory(prefix=project) as directory:
        env_file = Path(directory) / 'fixture.env'
        values = dict(line.split('=', 1) for line in
                      (ROOT / 'envs/.env.dev.example').read_text(encoding='utf-8').splitlines()
                      if '=' in line and not line.startswith('#'))
        values.update(POSTGRES_DB='rac_standing_e2e', HTTP_PORT='0', KEYCLOAK_PORT='0',
                      KEYCLOAK_PUBLIC_URL='http://keycloak:8080',
                      OIDC_ISSUER='http://keycloak:8080/realms/rentacompa',
                      OIDC_WEB_REDIRECT_URI='http://fixture.invalid/redirect.html',
                      STANDING_TEST_IMAGE_PREFIX=project)
        for key in ('POSTGRES_PASSWORD', 'KEYCLOAK_ADMIN_PASSWORD', 'KEYCLOAK_DB_PASSWORD',
                    'RABBITMQ_PASSWORD', 'COMPA_PROVISIONER_SECRET'):
            values[key] = secrets.token_urlsafe(36)
        with os.fdopen(os.open(env_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600),
                       'w', encoding='utf-8') as output:
            output.write('\n'.join(key + '=' + value for key, value in values.items()) + '\n')
        initialize(env_file)
        fixture_keys = {line.split('=', 1)[0] for line in env_file.read_text(encoding='utf-8').splitlines() if '=' in line}
        # A shell variable must not override the generated disposable credentials.
        lab_environment = {key: value for key, value in os.environ.items() if key not in fixture_keys}
        compose = ['docker', 'compose', '--env-file', str(env_file), '-p', project,
                   '-f', 'compose.yaml', '-f', 'compose.standing.yaml',
                   '-f', 'compose.standing-tests.yaml']

        def run(*args, check=True, timeout=900):
            result = subprocess.run(compose + list(args), cwd=ROOT, capture_output=True,
                                    text=True, encoding='utf-8', timeout=timeout, env=lab_environment)
            if check and result.returncode:
                # Never dump rendered environments, commands or fixture secrets.
                raise RuntimeError('Standing lab command failed: ' + args[0] + '\n' +
                                   result.stdout[-2000:] + result.stderr[-1200:])
            return result

        def fixture(phase):
            result = run('run', '--rm', '--no-deps', 'test-standing',
                         'python', 'standing_e2e_fixture.py', phase)
            print(result.stdout, end='', flush=True)

        # Validate the effective model before ANY mutation, including cleanup.
        model = json.loads(run('--profile', 'tests', 'config', '--format', 'json').stdout)
        validate_model(model, project)
        try:
            for service in ('database-config',) + APIS:
                print('BUILD: ' + service, flush=True)
                run('build', service)
            run('up', '-d', '--wait', '--wait-timeout', '180', 'postgres', 'rabbitmq')
            run('run', '--rm', '--no-deps', 'database-config')
            run('run', '--rm', '--no-deps', 'migrate')
            run('up', '-d', '--no-deps', 'keycloak')
            run('run', '--rm', '--no-deps', 'identity-config')
            run('run', '--rm', '--no-deps', 'messaging-config')
            run('up', '-d', '--no-deps', '--wait', '--wait-timeout', '180',
                '--scale', 'backend-user=2', '--scale', 'backend-match=2',
                '--scale', 'backend-chat=2', *APIS, *WORKERS)
            fixture('seed')
            # Freeze derived booking effects while exercising authority guards,
            # so cancellation does not mask authorization with a state conflict.
            run('stop', 'standing-match-consumer')
            fixture('writers')
            fixture('races')
            run('up', '-d', '--no-deps', '--wait', 'standing-match-consumer')
            fixture('prepare-outages')
            run('stop', 'rabbitmq')
            fixture('broker-offline')
            run('up', '-d', '--no-deps', '--wait', '--wait-timeout', '180', 'rabbitmq')
            run('restart', 'standing-match-consumer', 'standing-alert-consumer')
            fixture('outbox-drained')
            deadline = time.monotonic() + 45
            while True:
                queues = json.loads(run('exec', '-T', 'rabbitmq', 'gosu', 'rabbitmq',
                    'rabbitmqctl', '-q', 'list_queues', '-p', 'rac-dev',
                    'name', 'messages', '--formatter', 'json', timeout=30).stdout)
                expected_queues = {'rac.alert.bookings', 'rac.alert.bookings.failed',
                    'rac.match.standing', 'rac.match.standing.failed',
                    'rac.alert.standing', 'rac.alert.standing.failed'}
                if {q['name'] for q in queues} != expected_queues:
                    raise RuntimeError('Unexpected isolated messaging topology')
                if all(q['messages'] == 0 for q in queues):
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError('Messaging queues did not drain after recovery')
                time.sleep(0.5)
            fixture('recovered')
            run('stop', 'backend-user')
            fixture('authority-offline')
            run('up', '-d', '--no-deps', '--wait', '--scale', 'backend-user=2', 'backend-user')
            fixture('finished')
            print('PASS: isolated Compose standing writer/JWT, broker and authority fault matrix', flush=True)
        finally:
            # Only the randomly named model validated above. Never docker prune.
            run('down', '--volumes', '--remove-orphans', check=False)


if __name__ == '__main__':
    main()
