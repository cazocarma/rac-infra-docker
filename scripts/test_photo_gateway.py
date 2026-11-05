"""Exercise the deployed Nginx config on an isolated network, without DEV ports.

This is a transport proof. Image validation remains covered by the real API/S3
suite; the echo upstream deliberately accepts any bytes to isolate proxy limits.
"""
from pathlib import Path
import subprocess
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
BACKEND = '''
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib, json
class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
        response = json.dumps(dict(path=self.path, size=len(body),
            sha256=hashlib.sha256(body).hexdigest(),
            authorization=self.headers.get('Authorization'),
            request_id=self.headers.get('Idempotency-Key'))).encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(response)))
        self.end_headers()
        self.wfile.write(response)
    def log_message(self, *args): pass
ThreadingHTTPServer(('0.0.0.0', 8080), Handler).serve_forever()
'''
CLIENT = '''
import hashlib, json, urllib.request, urllib.error
body = b'x' * (2 * 1024 * 1024)
def post(path, data):
    request = urllib.request.Request('http://gateway'+path, data=data,
        headers={'Authorization': 'Bearer synthetic-token',
                 'Idempotency-Key': 'synthetic-request'}, method='POST')
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()
status, result = post('/api/user/me/photo-sources', body)
assert status == 200, status
actual = json.loads(result)
assert actual == dict(path='/api/user/me/photo-sources', size=len(body),
    sha256=hashlib.sha256(body).hexdigest(),
    authorization='Bearer synthetic-token', request_id='synthetic-request'), actual
assert post('/api/user/me/photo-sources', b'x'*(6*1024*1024+1))[0] == 413
assert post('/api/user/me/profile', body)[0] == 413
assert post('/api/user/me/photo', body)[0] == 200
print('PASS deployed Nginx: 2 MiB exact bytes/headers/path; >6 MiB rejected; unrelated routes retain 1 MiB limit')
'''


def run(*args, check=True):
    result = subprocess.run(args, capture_output=True, text=True, timeout=90)
    if check and result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return result


def main():
    name = 'rac-photo-gateway-' + uuid.uuid4().hex[:12]
    backend, gateway = name+'-backend', name+'-proxy'
    try:
        run('docker', 'network', 'create', name)
        run('docker', 'run', '-d', '--name', backend, '--network', name,
            '--network-alias', 'backend-user', 'python:3.13-alpine',
            'python', '-u', '-c', BACKEND)
        run('docker', 'run', '-d', '--name', gateway, '--network', name,
            '--network-alias', 'gateway', '--mount',
            f'type=bind,src={ROOT / "nginx/environments.conf"},dst=/etc/nginx/conf.d/default.conf,readonly',
            'nginx:1.28-alpine')
        for _ in range(30):
            ready = run('docker', 'exec', backend, 'python', '-c',
                        'import socket; socket.create_connection(("gateway",80),1).close();'
                        'socket.create_connection(("localhost",8080),1).close()', check=False)
            if ready.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError('Isolated gateway did not become ready')
        run('docker', 'exec', gateway, 'nginx', '-t')
        print(run('docker', 'exec', backend, 'python', '-c', CLIENT).stdout.strip())
    finally:
        run('docker', 'rm', '-f', gateway, backend, check=False)
        run('docker', 'network', 'rm', name, check=False)


if __name__ == '__main__':
    main()
