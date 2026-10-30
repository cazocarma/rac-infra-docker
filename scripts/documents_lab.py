"""Create a loopback-only, disposable P04 browser stack without reading DEV secrets."""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import uuid

from init_database_credentials import initialize

ROOT = Path(__file__).resolve().parents[1]
STATE_ROOT = ROOT.parent / '.local'
PROJECT = re.compile(r'rac-documents-e2e-[0-9a-f]{12}')
FILES = ('compose.yaml', 'compose.standing.yaml', 'compose.documents-lab.yaml')


def validate_model(model, project, web_port, identity_port, staff=False):
    if not PROJECT.fullmatch(project) or model.get('name') != project:
        raise RuntimeError('Disposable document lab required')
    database = model['services'].get('postgres', {})
    if '/var/lib/postgresql/data' not in database.get('tmpfs', []):
        raise RuntimeError('Document lab database must use temporary memory storage')
    if any(mount.get('target') == '/var/lib/postgresql/data' for mount in database.get('volumes', [])):
        raise RuntimeError('Document lab cannot import a PostgreSQL data volume')
    for name, service in model['services'].items():
        if service.get('network_mode') or service.get('container_name') or service.get('privileged') or service.get('devices'):
            raise RuntimeError('Host sharing is forbidden in document lab')
        for port in service.get('ports', []):
            expected = {'nginx': (web_port, 80), 'keycloak': (identity_port, 8080)}.get(name)
            if (expected is None or port.get('host_ip') != '127.0.0.1' or
                    str(port.get('published')) != str(expected[0]) or port.get('target') != expected[1]):
                raise RuntimeError('Unexpected published document lab port')
        for mount in service.get('volumes', []):
            if mount['type'] == 'bind' and not mount.get('read_only'):
                raise RuntimeError('Document lab cannot write host files')
    for category in ('volumes', 'networks'):
        for resource in model.get(category, {}).values():
            if resource.get('external') or resource.get('driver_opts') or not resource['name'].startswith(project + '_'):
                raise RuntimeError('Document lab cannot reuse existing resources')
    if model.get('secrets') or model.get('configs'):
        raise RuntimeError('Document lab cannot import external secrets/configs')
    owned_services = ('database-config', 'identity-config', 'keycloak', 'backend-auth', 'backend-user', 'flutter-web', 'test-documents')
    if staff:
        owned_services += ('backend-admin', 'backend-match', 'backend-chat', 'staff-fixture')
    for service in owned_services:
        if not model['services'].get(service, {}).get('image', '').startswith(project + '-'):
            raise RuntimeError('Document lab cannot overwrite DEV images')


def port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        return listener.getsockname()[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('start', 'stop', 'status', 'seed', 'refresh-web', 'material-change'))
    parser.add_argument('--state', type=Path)
    parser.add_argument('--staff', action='store_true', help='Enable editorial fixtures in a fresh disposable lab only')
    args = parser.parse_args()
    if args.staff and args.action != 'start':
        parser.error('--staff is only valid when creating a fresh lab')
    if args.action == 'start':
        project = 'rac-documents-e2e-' + uuid.uuid4().hex[:12]
        directory = STATE_ROOT / project
        directory.mkdir(parents=True, exist_ok=False)
        state_path = directory / 'state.json'
        web_port, identity_port = port(), port()
        while web_port == identity_port:
            identity_port = port()
        state = {'project': project, 'web_port': web_port, 'identity_port': identity_port,
                 'state': 'preparing', 'staff': args.staff, 'web_url': f'http://localhost:{web_port}',
                 'identity_url': f'http://localhost:{identity_port}'}
        values = dict(line.split('=', 1) for line in (ROOT / 'envs/.env.dev.example').read_text(encoding='utf-8').splitlines()
                      if '=' in line and not line.startswith('#'))
        values.update(POSTGRES_DB='rac_documents_e2e', HTTP_PORT=str(web_port), KEYCLOAK_PORT=str(identity_port),
                      API_BASE_URL=state['web_url'], KEYCLOAK_PUBLIC_URL=state['identity_url'],
                      OIDC_ISSUER=state['identity_url'] + '/realms/rentacompa',
                      OIDC_WEB_REDIRECT_URI=state['web_url'] + '/redirect.html', DOCUMENTS_TEST_PROJECT=project)
        for key in ('POSTGRES_PASSWORD', 'KEYCLOAK_ADMIN_PASSWORD', 'KEYCLOAK_DB_PASSWORD', 'RABBITMQ_PASSWORD', 'COMPA_PROVISIONER_SECRET'):
            values[key] = secrets.token_urlsafe(36)
        if args.staff:
            values['DOCUMENT_EDITORIAL_POLICY_VERSION'] = str(uuid.uuid4())
            values['DOCUMENT_EDITORIAL_DATABASE_URL'] = 'postgresql://rac_editorial_lab:' + secrets.token_urlsafe(36) + '@postgres:5432/rac_documents_e2e?sslmode=disable'
        env_file = directory / 'fixture.env'
        with os.fdopen(os.open(env_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w', encoding='utf-8') as output:
            output.write(''.join(key + '=' + value + '\n' for key, value in values.items()))
        initialize(env_file)
    else:
        if args.state is None:
            parser.error('--state required')
        state_path = args.state.resolve()
        if state_path.name != 'state.json' or state_path.parent.parent != STATE_ROOT.resolve() or not PROJECT.fullmatch(state_path.parent.name):
            raise RuntimeError('Owned local document lab state required')
        state = json.loads(state_path.read_text(encoding='utf-8'))
        project = state_path.parent.name
        if state['project'] != project:
            raise RuntimeError('Document lab identity mismatch')
        env_file = state_path.parent / 'fixture.env'
        web_port, identity_port = state['web_port'], state['identity_port']
    if state.get('staff') and args.action in ('seed', 'material-change'):
        raise RuntimeError('Editorial lab changes must use the authenticated owner workflow')
    values = dict(line.split('=', 1) for line in env_file.read_text(encoding='utf-8').splitlines() if '=' in line)
    if values.get('POSTGRES_DB') != 'rac_documents_e2e' or values.get('DOCUMENTS_TEST_PROJECT') != project:
        raise RuntimeError('Disposable database environment required')
    environment = {key: value for key, value in os.environ.items() if key not in values}
    compose = ['docker', 'compose', '--env-file', str(env_file), '-p', project, '--profile', 'tools', '--profile', 'tests']
    for file in FILES + (('compose.editorial-lab.yaml',) if state.get('staff') else ()):
        compose += ['-f', file]

    def run(*arguments, check=True, timeout=900, input=None):
        result = subprocess.run(compose + list(arguments), cwd=ROOT, env=environment,
                                text=True, encoding='utf-8', capture_output=True, timeout=timeout, input=input)
        if check and result.returncode:
            message = result.stderr[-1800:]
            for value in values.values():
                if len(value) >= 12:
                    message = message.replace(value, '[redacted]')
            raise RuntimeError('Document lab phase failed: ' + arguments[0] + '\n' + message)
        return result

    model = json.loads(run('config', '--format', 'json').stdout)
    validate_model(model, project, web_port, identity_port, staff=state.get('staff', False))
    def save():
        state_path.write_text(json.dumps(state, indent=2) + '\n', encoding='utf-8')
    if args.action == 'start':
        save()
        try:
            services = ('database-config', 'keycloak', 'backend-auth', 'backend-user', 'flutter-web')
            if state.get('staff'):
                services += ('backend-match', 'backend-chat', 'backend-admin')
            for service in services:
                print('BUILD: ' + service, flush=True)
                run('build', service)
            run('up', '-d', '--no-deps', '--wait', '--wait-timeout', '120', 'postgres')
            run('run', '--rm', '--no-deps', 'database-config')
            run('run', '--rm', '--no-deps', 'migrate')
            run('up', '-d', '--no-deps', 'keycloak')
            run('run', '--rm', '--no-deps', 'identity-config')
            if state.get('staff'):
                fixture = json.loads(run('run', '--rm', '--no-deps', 'staff-fixture').stdout)
                if len(fixture.get('accounts', [])) != 2:
                    raise RuntimeError('Synthetic two-person staff fixture required')
                fixture_path = state_path.parent / 'staff-fixture.json'
                with os.fdopen(os.open(fixture_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w', encoding='utf-8') as output:
                    json.dump(fixture, output)
            else:
                run('run', '--rm', '--no-deps', 'test-documents')
            run('up', '-d', '--no-deps', '--wait', '--wait-timeout', '180', 'backend-auth', 'backend-user', 'flutter-web')
            if state.get('staff'):
                run('up', '-d', '--no-deps', '--wait', '--wait-timeout', '180', 'backend-match', 'backend-chat', 'backend-admin')
            run('up', '-d', '--no-deps', 'nginx')
            state['state'] = 'ready'
            save()
            print('READY: ' + state['web_url'] + ' state=' + str(state_path), flush=True)
        except Exception:
            diagnostic = run('logs', '--no-color', '--tail', '60', 'backend-user', 'backend-admin', 'backend-chat', 'backend-match', check=False)
            diagnostic_text = diagnostic.stdout + diagnostic.stderr
            for value in values.values():
                if len(value) >= 12:
                    diagnostic_text = diagnostic_text.replace(value, '[redacted]')
            diagnostic_path = state_path.parent / 'startup-diagnostic.log'
            diagnostic_path.write_text(diagnostic_text, encoding='utf-8')
            print('DIAGNOSTIC: ' + str(diagnostic_path), flush=True)
            run('down', '--volumes', '--remove-orphans', check=False)
            state['state'] = 'failed'
            save()
            raise
    elif args.action == 'stop':
        run('down', '--volumes', '--remove-orphans')
        state['state'] = 'stopped'
        save()
        print('STOPPED: ' + project)
    elif args.action == 'material-change':
        run('exec', '-T', 'postgres', 'psql', '-X', '-v', 'ON_ERROR_STOP=1', '-U', values['POSTGRES_USER'], '-d', values['POSTGRES_DB'], input=(ROOT / 'scripts/documents_e2e_material_change.sql').read_text(encoding='utf-8'))
        print('PASS: synthetic material document change activated in disposable lab')
    elif args.action == 'refresh-web':
        run('build', 'flutter-web')
        run('up', '-d', '--no-deps', '--force-recreate', '--wait', '--wait-timeout', '180', 'flutter-web')
        print('REFRESHED: ' + state['web_url'])
    elif args.action == 'seed':
        run('run', '--rm', '--no-deps', 'test-documents')
    else:
        result = run('ps', '--format', 'json')
        print(result.stdout)


if __name__ == '__main__':
    main()
