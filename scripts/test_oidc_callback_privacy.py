"""Disposable real Nginx proxy/static checks: OAuth queries never enter access logs."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]


def command(*args, check=True):
    result = subprocess.run(args, text=True, encoding='utf-8', capture_output=True, timeout=120)
    if check and result.returncode:
        raise RuntimeError('Callback privacy test command failed: ' + args[0] + '\n' + result.stderr[-800:])
    return result


def main():
    name = 'rac-callback-privacy-' + uuid.uuid4().hex[:12]
    frontend, proxy = name + '-frontend', name + '-proxy'
    source = ROOT.parent / 'rac-frontend-flutter'
    with tempfile.TemporaryDirectory(prefix=name) as directory:
        web = Path(directory)
        (web / 'staff').mkdir()
        for path in ('redirect.html', 'staff/redirect.html', 'oidc_callback.js'):
            shutil.copyfile(source / 'web' / path, web / path)
        (web / 'index.html').write_text('SYNTHETIC_CALLBACK_TEST', encoding='utf-8')
        try:
            command('docker', 'network', 'create', name)
            for container, config, extra in (
                (frontend, source / 'docker/nginx.conf', ['--network-alias', 'flutter-web', '--mount', f'type=bind,source={web},target=/usr/share/nginx/html,readonly']),
                (proxy, ROOT / 'nginx/environments.conf', []),
            ):
                command('docker', 'run', '-d', '--name', container, '--network', name,
                        '--mount', f'type=bind,source={config},target=/etc/nginx/conf.d/default.conf,readonly',
                        *extra, 'nginx:1.28-alpine')
            for container in (frontend, proxy):
                for _ in range(30):
                    result = command('docker', 'exec', container, 'wget', '-q', '-O', '/dev/null', 'http://127.0.0.1/index.html', check=False)
                    if result.returncode == 0:
                        break
                    time.sleep(.2)
                else:
                    raise RuntimeError('Callback test Nginx did not become ready')
                for path in ('/redirect.html', '/staff/redirect.html'):
                    result = command('docker', 'exec', container, 'wget', '-S', '-O', '/dev/null',
                        'http://127.0.0.1' + path + '?code=SYNTHETIC_CALLBACK_SECRET&state=SYNTHETIC_STATE_SECRET')
                    headers = result.stderr.lower()
                    assert '200 ok' in headers and 'cache-control: no-store' in headers
                    assert 'referrer-policy: no-referrer' in headers
            for container in (frontend, proxy):
                logs = command('docker', 'logs', container)
                output = logs.stdout + logs.stderr
                assert 'SYNTHETIC_CALLBACK_SECRET' not in output and 'SYNTHETIC_STATE_SECRET' not in output
                assert 'GET /index.html HTTP' in output, 'Normal request logging was disabled'
            print('PASS: both OAuth callbacks are no-store/no-referrer and absent from proxy/static access logs; normal request logging remains active')
        finally:
            command('docker', 'rm', '-f', frontend, proxy, check=False)
            command('docker', 'network', 'rm', name, check=False)


if __name__ == '__main__':
    main()
