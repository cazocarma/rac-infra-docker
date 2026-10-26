"""Real two-node Keycloak session boundary; synthetic TLS/PG/PKCE only.

Builds the actual provider. Never reads .env, connects to DEV, or grants the
technical client realm-management. Only random test resources are removed.
"""
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
from html.parser import HTMLParser
import http.cookiejar
import json
from pathlib import Path
import secrets
import shutil
import ssl
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from identity_sessions import AUDIENCE, CLIENT, configure_sessions
from identity_standing import configure_standing

ROOT = Path(__file__).resolve().parents[1]


def command(*args, check=True, timeout=180):
    result = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', timeout=timeout)
    if check and result.returncode:
        # Commands can contain disposable credentials. Never include arguments
        # or server logs in failure diagnostics.
        # This build runs before credentials exist and receives only sources.
        details = '\n' + result.stdout[-1800:] + result.stderr[-1800:] if args[:2] == ('docker', 'build') else ''
        raise RuntimeError('Session fixture command failed: ' + args[0] + details)
    return result.stdout.strip()


class Form(HTMLParser):
    action = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'form' and attrs.get('id') == 'kc-form-login':
            self.action = attrs['action']


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def main():
    name = 'rac-session-test-' + uuid.uuid4().hex[:12]
    password = secrets.token_urlsafe(36)
    image = name + ':test'
    nodes, bases = [], []
    with tempfile.TemporaryDirectory(prefix=name) as folder:
        directory = Path(folder)
        try:
            command('docker', 'build', '-f', str(ROOT / 'keycloak/session-control/Dockerfile'),
                    '-t', image, str(ROOT), timeout=900)
            openssl = shutil.which('openssl') or 'C:/Program Files/Git/usr/bin/openssl.exe'
            command(openssl, 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                    '-keyout', str(directory / 'key.pem'), '-out', str(directory / 'cert.pem'),
                    '-subj', '/CN=identity.fixture', '-addext',
                    'subjectAltName=IP:127.0.0.1,DNS:localhost,DNS:identity.fixture')
            directory.chmod(0o755)
            (directory / 'key.pem').chmod(0o644)
            context = ssl.create_default_context(cafile=str(directory / 'cert.pem'))
            command('docker', 'network', 'create', name)
            command('docker', 'run', '-d', '--name', name + '-pg', '--network', name,
                    '--network-alias', 'database', '--tmpfs', '/var/lib/postgresql/data',
                    '-e', 'POSTGRES_PASSWORD=' + password, '-e', 'POSTGRES_DB=keycloak',
                    'postgis/postgis:16-3.4')

            def request(method, path, data=None, token=None, form=False, expected=200, node=0, timeout=15):
                headers = {'Content-Type': 'application/x-www-form-urlencoded' if form else 'application/json'}
                if token:
                    headers['Authorization'] = 'Bearer ' + token
                body = data if isinstance(data, bytes) else None if data is None else (urllib.parse.urlencode(data).encode() if form
                                                  else json.dumps(data).encode())
                req = urllib.request.Request(bases[node] + path, data=body, headers=headers, method=method)
                try:
                    response = urllib.request.urlopen(req, timeout=timeout, context=context)
                except urllib.error.HTTPError as error:
                    if expected is None:
                        raise
                    response = error
                with response:
                    raw = response.read()
                    reason = ''
                    if response.code == 400:
                        try:
                            candidate = json.loads(raw).get('error', '')
                            if candidate in ('invalid_session_payload', 'invalid_session_batch', 'invalid_session_reference'):
                                reason = candidate
                        except (ValueError, AttributeError):
                            pass
                    assert expected is None or response.code == expected, ('Session fixture HTTP status', method, response.code, expected, reason)
                    if response.code != 200 or not raw:
                        return None
                    if '/rac-sessions/' in path:
                        assert response.headers['Cache-Control'] == 'no-store'
                    return json.loads(raw)

            def start(index, active=True):
                node = name + '-' + str(index)
                if node not in nodes:
                    nodes.append(node)
                command('docker', 'run', '-d', '--name', node, '--network', name, '-p', '127.0.0.1::8443',
                        '--mount', f'type=bind,source={directory / "cert.pem"},target=/test-certs/cert.pem,readonly',
                        '--mount', f'type=bind,source={directory / "key.pem"},target=/test-certs/key.pem,readonly',
                        '-e', 'KC_BOOTSTRAP_ADMIN_USERNAME=operator', '-e', 'KC_BOOTSTRAP_ADMIN_PASSWORD=' + password,
                        '-e', 'KC_DB=postgres', '-e', 'KC_DB_URL=jdbc:postgresql://database:5432/keycloak',
                        '-e', 'KC_DB_USERNAME=postgres', '-e', 'KC_DB_PASSWORD=' + password,
                        image, 'start', '--optimized', '--hostname=https://identity.fixture',
                        '--https-certificate-file=/test-certs/cert.pem', '--https-certificate-key-file=/test-certs/key.pem',
                        *(['--spi-realm-restapi-extension--rac-sessions--active=true'] if active else []))
                port = command('docker', 'port', node, '8443/tcp').split(':')[-1]
                base = 'https://127.0.0.1:' + port
                if index == len(bases):
                    bases.append(base)
                else:
                    bases[index] = base
                deadline = time.monotonic() + 180
                while time.monotonic() < deadline:
                    try:
                        return request('POST', '/realms/master/protocol/openid-connect/token', {
                            'client_id': 'admin-cli', 'grant_type': 'password', 'username': 'operator',
                            'password': password}, form=True, node=index, timeout=2)['access_token']
                    except (OSError, AssertionError):
                        time.sleep(1)
                raise RuntimeError('Disposable session-control Keycloak did not become ready')

            operator = start(0)

            def admin(method, path, data=None):
                return request(method, '/admin/realms/rentacompa' + path, data, operator, expected=None)

            request('POST', '/admin/realms', {'realm': 'rentacompa', 'enabled': True}, operator, expected=201)
            # Provisioning callbacks return None for successful writes (201/204).
            configure_sessions(admin, directory / 'sessions')
            configure_sessions(admin, directory / 'sessions')
            credential_file = directory / 'sessions/secret'
            saved = credential_file.with_suffix('.saved')
            credential_file.rename(saved)
            try:
                try:
                    configure_sessions(admin, directory / 'sessions')
                except RuntimeError:
                    pass
                else:
                    raise AssertionError('Missing credential silently rotated a deployed client')
            finally:
                saved.rename(credential_file)
            secret = (directory / 'sessions/secret').read_text(encoding='utf-8').strip()
            worker_client = admin('GET', '/clients?clientId=' + CLIENT)[0]
            account = admin('GET', '/clients/' + worker_client['id'] + '/service-account-user')
            management = admin('GET', '/clients?clientId=realm-management')[0]
            excessive = [admin('GET', '/clients/' + management['id'] + '/roles/manage-users')]
            # Reconciliation must retire an accidental direct grant and scope.
            admin('POST', '/users/' + account['id'] + '/role-mappings/clients/' + management['id'], excessive)
            admin('POST', '/clients/' + worker_client['id'] + '/scope-mappings/clients/' + management['id'], excessive)
            session_resource = admin('GET', '/clients?clientId=' + AUDIENCE)[0]
            admin('POST', '/clients/' + session_resource['id'] + '/roles/sessions.revoke/composites', excessive)
            configure_sessions(admin, directory / 'sessions')
            assert (directory / 'sessions/secret').read_text(encoding='utf-8').strip() == secret

            def worker_token():
                result = request('POST', '/realms/rentacompa/protocol/openid-connect/token', {
                    'client_id': CLIENT, 'client_secret': secret, 'grant_type': 'client_credentials'}, form=True)
                assert 'refresh_token' not in result and result['expires_in'] <= 60
                return result['access_token']

            worker = worker_token()
            claims = json.loads(base64.urlsafe_b64decode(worker.split('.')[1] + '=='))
            assert claims['sub'] == account['id'] and claims['azp'] == CLIENT
            assert claims['resource_access'] == {AUDIENCE: {'roles': ['sessions.revoke']}}
            admin('POST', '/clients', {'clientId': 'rac-web', 'enabled': True, 'publicClient': True,
                'standardFlowEnabled': True, 'directAccessGrantsEnabled': False,
                'redirectUris': ['https://rac.invalid/callback'],
                'attributes': {'pkce.code.challenge.method': 'S256'}})
            subjects = {}
            for username in ('one', 'other'):
                admin('POST', '/users', {'username': username, 'enabled': True,
                    'firstName': 'Synthetic', 'lastName': 'Fixture', 'email': username + '@example.test',
                    'emailVerified': True, 'credentials': [{'type': 'password', 'value': password, 'temporary': False}]})
                subjects[username] = admin('GET', '/users?exact=true&username=' + username)[0]['id']
            web = admin('GET', '/clients?clientId=rac-web')[0]
            offline_scope = next(scope for scope in admin('GET', '/client-scopes') if scope['name'] == 'offline_access')
            admin('PUT', '/clients/' + web['id'] + '/optional-client-scopes/' + offline_scope['id'])
            admin('POST', '/users/' + subjects['one'] + '/role-mappings/realm', [admin('GET', '/roles/offline_access')])

            def login(username, offline=False):
                verifier, state, nonce = secrets.token_urlsafe(48), secrets.token_urlsafe(24), secrets.token_urlsafe(24)
                challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
                params = {'client_id': 'rac-web', 'response_type': 'code', 'redirect_uri': 'https://rac.invalid/callback',
                    'scope': 'openid offline_access' if offline else 'openid', 'state': state, 'nonce': nonce,
                    'code_challenge': challenge, 'code_challenge_method': 'S256'}
                opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
                    urllib.request.HTTPSHandler(context=context), NoRedirect())
                page = opener.open(bases[0] + '/realms/rentacompa/protocol/openid-connect/auth?' + urllib.parse.urlencode(params), timeout=15).read().decode()
                form = Form(); form.feed(page)
                assert form.action and urllib.parse.urlsplit(form.action).hostname == 'identity.fixture'
                action = urllib.parse.urlsplit(form.action)
                try:
                    opener.open(urllib.request.Request(bases[0] + action.path + '?' + action.query,
                        data=urllib.parse.urlencode({'username': username, 'password': password, 'credentialId': ''}).encode()), timeout=15)
                except urllib.error.HTTPError as error:
                    assert error.code in (302, 303), 'Synthetic PKCE authentication failed'
                    returned = urllib.parse.parse_qs(urllib.parse.urlsplit(error.headers['Location']).query)
                else:
                    raise AssertionError('Authorization redirect missing')
                assert returned['state'] == [state]
                result = request('POST', '/realms/rentacompa/protocol/openid-connect/token', {
                    'client_id': 'rac-web', 'grant_type': 'authorization_code', 'redirect_uri': 'https://rac.invalid/callback',
                    'code': returned['code'][0], 'code_verifier': verifier}, form=True)
                decoded = json.loads(base64.urlsafe_b64decode(result['id_token'].split('.')[1] + '=='))
                assert decoded['nonce'] == nonce and decoded['iss'] == 'https://identity.fixture/realms/rentacompa'
                return result

            first, offline, foreign = login('one'), login('one', offline=True), login('other')
            refresh_claims = json.loads(base64.urlsafe_b64decode(offline['refresh_token'].split('.')[1] + '=='))
            assert refresh_claims['typ'] == 'Offline' and 'offline_access' in offline['scope'], 'Offline grant not issued'
            path = '/realms/rentacompa/rac-sessions/users/' + subjects['one'] + '/sessions'
            info = '/realms/rentacompa/protocol/openid-connect/userinfo'
            request('GET', path, expected=401)
            request('GET', path, token=first['access_token'], expected=401)
            corrupted = worker.split('.')
            corrupted[2] = ('A' if corrupted[2][0] != 'A' else 'B') + corrupted[2][1:]
            request('GET', path, token='.'.join(corrupted), expected=401)
            configure_standing(admin, directory / 'standing')
            wrong_secret = (directory / 'standing/match/secret').read_text(encoding='utf-8').strip()
            wrong = request('POST', '/realms/rentacompa/protocol/openid-connect/token', {
                'client_id': 'rac-match-standing', 'client_secret': wrong_secret, 'grant_type': 'client_credentials'}, form=True)
            request('GET', path, token=wrong['access_token'], expected=401)
            resource = admin('GET', '/clients?clientId=' + AUDIENCE)[0]
            session_role = admin('GET', '/clients/' + resource['id'] + '/roles/sessions.revoke')
            admin('POST', '/users/' + subjects['one'] + '/role-mappings/clients/' + resource['id'], [session_role])
            admin('PUT', '/clients/' + web['id'], {'fullScopeAllowed': True, 'protocolMappers': [
                {'name': 'negative-fixture-audience', 'protocol': 'openid-connect', 'protocolMapper': 'oidc-audience-mapper',
                 'config': {'included.custom.audience': AUDIENCE, 'access.token.claim': 'true', 'id.token.claim': 'false'}}]})
            human = login('one')['access_token']
            human_claims = json.loads(base64.urlsafe_b64decode(human.split('.')[1] + '=='))
            assert 'sessions.revoke' in human_claims['resource_access'][AUDIENCE]['roles']
            request('GET', path, token=human, expected=403)
            request('POST', '/realms/rentacompa/protocol/openid-connect/token', {
                'client_id': CLIENT, 'client_secret': secret, 'grant_type': 'password',
                'username': 'one', 'password': password}, form=True, expected=400)
            admin('DELETE', '/users/' + account['id'] + '/role-mappings/clients/' + resource['id'], [session_role])
            request('GET', path, token=worker_token(), expected=403)
            configure_sessions(admin, directory / 'sessions')
            admin('PUT', '/clients/' + worker_client['id'], {'attributes': {'access.token.lifespan': '1'}})
            expired = worker_token()
            exp_claims = json.loads(base64.urlsafe_b64decode(expired.split('.')[1] + '=='))
            assert exp_claims['exp'] - exp_claims['iat'] <= 1
            # Wait a bounded duration from receipt, independent of host UTC.
            time.sleep(2.1)
            request('GET', path, token=expired, expected=401)
            configure_sessions(admin, directory / 'sessions')
            worker = worker_token()
            for method, target, body in (
                ('GET', '/users', None), ('PUT', '/users/' + subjects['one'], {'enabled': False}),
                ('DELETE', '/users/' + subjects['one'], None),
                ('PUT', '/users/' + subjects['one'] + '/reset-password', {'type': 'password', 'value': 'unauthorized'}),
                ('POST', '/users/' + subjects['one'] + '/role-mappings/realm', []),
                ('POST', '/users/' + subjects['one'] + '/logout', None)):
                request(method, '/admin/realms/rentacompa' + target, body, worker, expected=403)
            request('GET', '/admin/realms/master/users', token=worker, expected=403)
            request('GET', '/realms/master/rac-sessions/users/' + subjects['one'] + '/sessions', token=worker, expected=404)
            request('GET', '/realms/rentacompa/rac-sessions/users/' + account['id'] + '/sessions', token=worker, expected=403)
            print('PASS: real signed service token, audience/client/realm separation and user/password/role/admin-logout privilege denials', flush=True)

            start(1)
            captured = request('GET', path, token=worker)
            assert set(captured) == {'sessions', 'complete'} and captured['complete'] is True
            refs = captured['sessions']
            # Since Keycloak 26.4 an initial offline grant can remove the
            # associated online session. Require both kinds, not three records.
            assert len(refs) >= 2 and any(ref['offline'] for ref in refs) and any(not ref['offline'] for ref in refs), ('Snapshot counts', len(refs), sum(ref['offline'] for ref in refs))
            assert all(set(ref) == {'id', 'offline'} for ref in refs)
            foreign_refs = request('GET', path.replace(subjects['one'], subjects['other']), token=worker)['sessions']
            own = next(ref for ref in refs if not ref['offline'])
            request('POST', path + '/revoke', {'sessions': [own, foreign_refs[0]]}, worker, expected=403, node=1)
            for bad in ({'sessions': [own, own]}, {'sessions': [{'id': 'bad\nid', 'offline': False}]},
                        {'sessions': [own], 'all': True}, {'sessions': [{'id': own['id'], 'offline': 'false'}]},
                        {'sessions': [own] * 101}, {'sessions': [], 'padding': 'x' * 17000}):
                request('POST', path + '/revoke', bad, worker, expected=413 if 'padding' in bad else 400)
            for raw in (b'{"sessions":[],"sessions":[]}', b'{"sessions":[]} trailing'):
                request('POST', path + '/revoke', raw, worker, expected=400)
            assert request('POST', path + '/revoke', {'sessions': [{'id': 'opaque-missing~v2', 'offline': False}]}, worker) == {'removed': 0, 'missing': 1}
            request('GET', info, token=first['access_token'])
            request('GET', info, token=foreign['access_token'])
            request('POST', path + '/revoke', {'sessions': [own]}, worker, node=1)
            fresh = login('one')
            # Complete/replay the ORIGINAL snapshot, never a new "logout all".
            request('POST', path + '/revoke', {'sessions': refs}, worker, node=1)
            replay = request('POST', path + '/revoke', {'sessions': refs}, worker)
            assert replay == {'removed': 0, 'missing': len(refs)}
            for old in (first, offline):
                request('POST', '/realms/rentacompa/protocol/openid-connect/token', {
                    'grant_type': 'refresh_token', 'client_id': 'rac-web', 'refresh_token': old['refresh_token']}, form=True, expected=400)
            request('GET', info, token=fresh['access_token'])
            request('GET', info, token=foreign['access_token'])
            with ThreadPoolExecutor(max_workers=6) as pool:
                list(pool.map(lambda i: request('POST', path + '/revoke', {'sessions': refs}, worker, node=i % 2), range(6)))
            request('GET', info, token=fresh['access_token'])
            assert admin('GET', '/users/' + subjects['one'])['enabled'] is True
            print('PASS: two-node exact online/offline revocation, whole-batch ownership validation, bounded input and concurrent replay preserve new/foreign sessions', flush=True)

            for node in nodes:
                command('docker', 'stop', node)
            for node in nodes:
                command('docker', 'start', node)
            # Readiness is observable, not a fixed restart sleep.
            for index in (0, 1):
                # Docker can reassign a randomly published host port on start.
                port = command('docker', 'port', nodes[index], '8443/tcp').split(':')[-1]
                bases[index] = 'https://127.0.0.1:' + port
                deadline = time.monotonic() + 90
                while time.monotonic() < deadline:
                    try:
                        request('GET', '/realms/rentacompa/.well-known/openid-configuration', node=index, timeout=2)
                        break
                    except (OSError, AssertionError):
                        time.sleep(1)
                else:
                    raise RuntimeError('Session-control restart did not become ready')
            worker = worker_token()
            request('POST', path + '/revoke', {'sessions': refs}, worker, node=1)
            request('GET', info, token=fresh['access_token'], node=1)
            refreshed = request('POST', '/realms/rentacompa/protocol/openid-connect/token', {
                'grant_type': 'refresh_token', 'client_id': 'rac-web', 'refresh_token': fresh['refresh_token']}, form=True)
            request('GET', info, token=refreshed['access_token'])
            command('docker', 'rm', '-f', nodes[0])
            start(0, active=False)
            request('GET', path, token=worker, expected=404)
            request('GET', info, token=refreshed['access_token'])
            print('PASS: persisted Keycloak restart retains new login, original snapshot replay is safe, and extension defaults inactive', flush=True)
        finally:
            for node in nodes:
                command('docker', 'rm', '-f', node, check=False)
            command('docker', 'rm', '-f', name + '-pg', check=False)
            command('docker', 'network', 'rm', name, check=False)
            command('docker', 'image', 'rm', image, check=False)


if __name__ == '__main__':
    main()
