"""Start/stop a frozen, loopback-only browser regression lab; no DEV secrets."""
import argparse
import io
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tarfile
import uuid

from browser_compose import PROJECT, command
from init_database_credentials import initialize

ROOT = Path(__file__).resolve().parents[1]
STATE_ROOT = ROOT.parent / '.local'
APIS = ('backend-auth', 'backend-user', 'backend-match', 'backend-chat', 'backend-alert', 'backend-admin')
WORKERS = ('booking-maintenance', 'booking-events-relay', 'alert-events-consumer')
TOOLS = ('database-config', 'identity-config', 'messaging-config', 'test-integration')
SERVICES = ('postgres', 'migrate', 'keycloak', 'rabbitmq', 'flutter-web', 'nginx') + APIS + WORKERS + TOOLS


def port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        return listener.getsockname()[1]


def private_write(path, value):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w', encoding='utf-8') as output:
        output.write(value)


def validate_model(model, project, web_port, identity_port, sources_root):
    if not PROJECT.fullmatch(project) or model.get('name') != project or set(model['services']) != set(SERVICES):
        raise RuntimeError('Exact disposable browser model required')
    if model['services']['postgres'].get('environment', {}).get('POSTGRES_DB') != 'rac_browser_e2e':
        raise RuntimeError('Dedicated browser fixture database required')
    for name, service in model['services'].items():
        if service.get('environment', {}).get('RAC_ENV', 'dev') != 'dev':
            raise RuntimeError('Browser fixtures are DEV-only')
        if name in ('nginx', 'keycloak') and len(service.get('ports', [])) != 1:
            raise RuntimeError('Exactly one loopback port per browser endpoint required')
        if any(service.get(key) for key in ('network_mode', 'container_name', 'privileged', 'devices')):
            raise RuntimeError('Host sharing forbidden')
        for binding in service.get('ports', []):
            expected = {'nginx': (web_port, 80), 'keycloak': (identity_port, 8080)}.get(name)
            if expected is None or binding.get('host_ip') != '127.0.0.1' or str(binding.get('published')) != str(expected[0]) or binding.get('target') != expected[1]:
                raise RuntimeError('Unexpected browser lab published port')
        for mount in service.get('volumes', []):
            if mount['type'] == 'bind' and not mount.get('read_only'):
                raise RuntimeError('Writable host mount forbidden')
            if mount['type'] == 'bind' and not Path(mount['source']).resolve().is_relative_to(Path(sources_root).resolve()):
                raise RuntimeError('Browser lab mounts must remain in frozen sources')
        build = service.get('build', {})
        if build and (not Path(build['context']).resolve().is_relative_to(Path(sources_root).resolve()) or build.get('additional_contexts')):
            raise RuntimeError('Browser lab build context must remain in frozen sources')
        if name in APIS + WORKERS + TOOLS + ('flutter-web',) and not service.get('image', '').startswith(project + '-'):
            raise RuntimeError('Browser lab cannot overwrite existing application images')
        if set(service.get('depends_on', {})) - set(SERVICES):
            raise RuntimeError('Unexpected browser lab dependency')
    for name, target in (('postgres', '/var/lib/postgresql/data'), ('rabbitmq', '/var/lib/rabbitmq')):
        service = model['services'][name]
        if target not in service.get('tmpfs', []) or any(m.get('target') == target for m in service.get('volumes', [])):
            raise RuntimeError('Database and broker must have disposable memory storage')
    for kind in ('volumes', 'networks'):
        for resource in model.get(kind, {}).values():
            if resource.get('external') or resource.get('driver_opts') or not resource.get('name', '').startswith(project + '_'):
                raise RuntimeError('Existing resources forbidden')
    if model.get('secrets') or model.get('configs'):
        raise RuntimeError('External secret/config imports forbidden')


def snapshot(directory):
    pins = json.loads((ROOT / 'ci/p04-companion-candidate.json').read_text(encoding='utf-8'))
    revisions = {}
    for name in (*pins, ROOT.name):
        checkout = ROOT.parent / name
        revision = subprocess.check_output(['git', '-C', str(checkout), 'rev-parse', 'HEAD'], text=True).strip()
        dirty = subprocess.check_output(['git', '-C', str(checkout), 'status', '--porcelain', '--untracked-files=no'], text=True).strip()
        if dirty or (name in pins and revision != pins[name]):
            raise RuntimeError('Clean candidate snapshot required: ' + name)
        target = directory / 'sources' / name
        target.mkdir(parents=True)
        archive = subprocess.check_output(['git', '-C', str(checkout), 'archive', '--format=tar', revision])
        with tarfile.open(fileobj=io.BytesIO(archive)) as source:
            source.extractall(target, filter='data')
        revisions[name] = revision
    return revisions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('start', 'stop', 'status', 'test'))
    parser.add_argument('--state', type=Path)
    parser.add_argument('--suite', choices=('chat', 'booking', 'onboarding', 'reviews', 'notifications', 'admin', 'schedule', 'all'), default='chat')
    args = parser.parse_args()
    if args.action == 'start':
        project = 'rac-browser-e2e-' + uuid.uuid4().hex[:12]
        directory = STATE_ROOT / project
        directory.mkdir(parents=True, exist_ok=False)
        revisions = snapshot(directory)
        root = directory / 'sources' / ROOT.name
        web_port, identity_port = port(), port()
        while identity_port == web_port:
            identity_port = port()
        state = {'project': project, 'source_root': str(root.resolve()), 'web_port': web_port,
                 'identity_port': identity_port, 'web_url': f'http://localhost:{web_port}',
                 'identity_url': f'http://localhost:{identity_port}', 'state': 'preparing', 'revisions': revisions}
        state_path = directory / 'state.json'
        values = dict(line.split('=', 1) for line in (root / 'envs/.env.dev.example').read_text(encoding='utf-8').splitlines() if '=' in line and not line.startswith('#'))
        values.update(POSTGRES_DB='rac_browser_e2e', HTTP_PORT=str(web_port), KEYCLOAK_PORT=str(identity_port),
                      API_BASE_URL=state['web_url'], KEYCLOAK_PUBLIC_URL=state['identity_url'],
                      OIDC_ISSUER=state['identity_url'] + '/realms/rentacompa',
                      OIDC_WEB_REDIRECT_URI=state['web_url'] + '/redirect.html')
        for key in ('POSTGRES_PASSWORD', 'KEYCLOAK_ADMIN_PASSWORD', 'KEYCLOAK_DB_PASSWORD', 'RABBITMQ_PASSWORD', 'COMPA_PROVISIONER_SECRET'):
            values[key] = secrets.token_urlsafe(36)
        env_file = directory / 'fixture.env'
        private_write(env_file, ''.join(key + '=' + value + '\n' for key, value in values.items()))
        initialize(env_file)
        values = dict(line.split('=', 1) for line in env_file.read_text(encoding='utf-8').splitlines() if '=' in line)
        environment = {key: value for key, value in os.environ.items() if key not in values}
        base = ['docker', 'compose', '--env-file', str(env_file), '-p', project, '--profile', 'tools', '--profile', 'tests', '-f', 'compose.yaml', '-f', 'compose.tests.yaml']
        resolved = subprocess.run(base + ['config', '--format', 'json'], cwd=root, env=environment, capture_output=True, text=True, check=True)
        model = json.loads(resolved.stdout)
        model['services'] = {key: value for key, value in model['services'].items() if key in SERVICES}
        for name, service in model['services'].items():
            service['restart'] = 'no'
            if name in TOOLS:
                service['image'] = project + '-tools'
            if name in APIS:
                service['image'] = project + '-' + name
                service['build'] = {'context': str(root.parent / ('rac-' + name.removeprefix('backend-') + '-service'))}
            if name in WORKERS:
                service['image'] = project + ('-backend-alert' if name == 'alert-events-consumer' else '-backend-match')
        model['services']['flutter-web'].update(image=project + '-frontend', build={'context': str(root.parent / 'rac-frontend-flutter')})
        for name, target in (('postgres', '/var/lib/postgresql/data'), ('rabbitmq', '/var/lib/rabbitmq')):
            service = model['services'][name]
            service['volumes'] = [m for m in service.get('volumes', []) if m.get('target') != target]
            service['tmpfs'] = [target]
        model['services']['keycloak']['command'] = ['start-dev', '--import-realm']
        model['services']['keycloak']['volumes'] = [
            {'type': 'bind', 'source': str(root / 'keycloak/themes/rac'), 'target': '/opt/keycloak/themes/rac', 'read_only': True},
            {'type': 'bind', 'source': str(root / 'envs/realm.dev.example.json'), 'target': '/opt/keycloak/data/import/realm-rentacompa.json', 'read_only': True}]
        validate_model(model, project, web_port, identity_port, root.parent)
        private_write(directory / 'compose.json', json.dumps(model))
        state_path.write_text(json.dumps(state, indent=2), encoding='utf-8')
    else:
        if args.state is None:
            parser.error('--state required')
        state_path = args.state.resolve()
        directory = state_path.parent
        if directory.parent != STATE_ROOT.resolve() or not PROJECT.fullmatch(directory.name):
            raise RuntimeError('Owned local browser lab required')
        state = json.loads(state_path.read_text(encoding='utf-8'))
        root = Path(state['source_root'])
        values = dict(line.split('=', 1) for line in (directory / 'fixture.env').read_text(encoding='utf-8').splitlines() if '=' in line)
        environment = {key: value for key, value in os.environ.items() if key not in values}
    compose = command(root, state_path)
    def run(*arguments, timeout=900):
        result = subprocess.run(compose + list(arguments), cwd=root, env=environment, capture_output=True, text=True, encoding='utf-8', timeout=timeout)
        if result.returncode:
            # Resolved Compose and process errors can contain credentials.
            diagnostic = result.stderr[-2400:]
            for value in values.values():
                if len(value) >= 12:
                    diagnostic = diagnostic.replace(value, '[redacted]')
            raise RuntimeError('Browser lab phase failed: ' + arguments[0] + '\n' + diagnostic)
        return result
    model = json.loads(run('config', '--format', 'json').stdout)
    validate_model(model, state['project'], state['web_port'], state['identity_port'], root.parent)
    if args.action == 'start':
        try:
            for service in ('database-config',) + APIS + ('flutter-web',):
                print('BUILD: ' + service, flush=True)
                run('build', service)
            run('up', '-d', '--no-deps', '--wait', '--wait-timeout', '180', 'postgres', 'rabbitmq')
            run('run', '--rm', '--no-deps', 'database-config')
            run('run', '--rm', '--no-deps', 'migrate')
            run('up', '-d', '--no-deps', 'keycloak')
            run('run', '--rm', '--no-deps', 'identity-config')
            run('run', '--rm', '--no-deps', 'messaging-config')
            run('up', '-d', '--no-deps', '--wait', '--wait-timeout', '180', *APIS, 'flutter-web', *WORKERS)
            run('up', '-d', '--no-deps', 'nginx')
            state['state'] = 'ready'
        except Exception:
            state['state'] = 'failed'
            raise
        finally:
            state_path.write_text(json.dumps(state, indent=2), encoding='utf-8')
        print('READY: ' + state['web_url'] + ' state=' + str(state_path), flush=True)
    elif args.action == 'test':
        if state.get('state') != 'ready':
            raise RuntimeError('Browser lab must be ready before testing')
        # The fixture resolver validates this state against its frozen source root.
        environment.update(RAC_ENV='dev', RAC_BROWSER_LAB_STATE=str(state_path), RAC_BROWSER_URL=state['web_url'])
        # Same browser scripts as the CI integration job, resolved against this lab.
        suites = {'chat': 'test_chat_browser.py', 'booking': 'test_browser.py',
                  'onboarding': 'test_browser_onboarding.py', 'reviews': 'test_reviews_browser.py',
                  'notifications': 'test_notifications_browser.py', 'admin': 'test_admin_browser.py',
                  'schedule': 'test_schedule_browser.py'}
        for name in (suites if args.suite == 'all' else (args.suite,)):
            artifacts = directory / 'artifacts' / name
            artifacts.mkdir(parents=True, exist_ok=True)
            environment['RAC_BROWSER_ARTIFACTS'] = str(artifacts)
            state.setdefault('tests', {})[name] = 'running'
            state_path.write_text(json.dumps(state, indent=2), encoding='utf-8')
            try:
                result = subprocess.run([sys.executable, str(root / 'scripts' / suites[name])],
                                        cwd=root, env=environment, capture_output=True,
                                        text=True, encoding='utf-8', timeout=900)
                output = result.stdout + result.stderr
                for value in values.values():
                    if len(value) >= 12:
                        output = output.replace(value, '[redacted]')
                (artifacts / 'result.log').write_text(output, encoding='utf-8')
                state['tests'][name] = 'passed' if result.returncode == 0 else 'failed'
                if result.returncode:
                    raise RuntimeError('Browser suite failed: ' + name + '; see ' + str(artifacts / 'result.log'))
                print('PASS: browser suite ' + name, flush=True)
            except subprocess.TimeoutExpired:
                state['tests'][name] = 'timeout'
                raise RuntimeError('Browser suite timed out: ' + name)
            finally:
                state_path.write_text(json.dumps(state, indent=2), encoding='utf-8')
    elif args.action == 'stop':
        run('down', '--volumes', '--remove-orphans')
        state['state'] = 'stopped'
        state_path.write_text(json.dumps(state, indent=2), encoding='utf-8')
    else:
        print(run('ps').stdout)


if __name__ == '__main__':
    main()
