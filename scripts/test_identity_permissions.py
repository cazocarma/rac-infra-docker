"""Real disposable Keycloak tests: fixed compa grant, privilege denials and
prepared staff MFA flow. Never opens or modifies the existing DEV realm.
"""
import json
import base64
import hashlib
import hmac
import http.cookiejar
import struct
from html.parser import HTMLParser
import secrets
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import os
import shutil
import ssl
import tempfile
from pathlib import Path
from identity_permissions import configure_provisioner, configure_staff
from identity_standing import configure_standing

IMAGE = 'quay.io/keycloak/keycloak:26.8.1@sha256:79c623a22abacf3fe6c00a5fb30f5b7843d717b234033b80995891c06116d244'


def command(*args, ok=True):
    result = subprocess.run(args, capture_output=True, text=True, timeout=180)
    if ok and result.returncode:
        # Fixed Go test diagnostics only; never dump arguments or token fixtures.
        details = '\n'.join(line for line in result.stdout.splitlines() if '.go:' in line or line.startswith('FAIL'))
        raise RuntimeError('Disposable identity command failed: ' + args[0] + ('\n' + details if details else ''))
    return result.stdout.strip()


def main():
    name = 'rac-identity-test-' + uuid.uuid4().hex[:12]
    password, secret = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    certificates = tempfile.TemporaryDirectory(prefix='rac-identity-tls-')
    try:
        directory = Path(certificates.name)
        openssl = shutil.which('openssl') or 'C:/Program Files/Git/usr/bin/openssl.exe'
        if not Path(openssl).is_file():
            raise RuntimeError('OpenSSL required for disposable TLS fixture')
        command(openssl, 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
            '-keyout', str(directory/'key.pem'), '-out', str(directory/'cert.pem'),
            '-subj', '/CN=localhost', '-addext', 'subjectAltName=IP:127.0.0.1,DNS:localhost,DNS:identity-fixture')
        # Disposable localhost-only test key, not a deployment certificate.
        os.chmod(directory,0o755);os.chmod(directory/'key.pem',0o644)
        context = ssl.create_default_context(cafile=str(directory/'cert.pem'))
        command('docker', 'network', 'create', name)
        command('docker', 'run', '-d', '--name', name, '--network', name, '--network-alias', 'identity-fixture', '-p', '127.0.0.1::8443',
            '--mount', f'type=bind,source={directory},target=/test-certs,readonly',
            '-e', 'KC_BOOTSTRAP_ADMIN_USERNAME=operator', '-e', 'KC_BOOTSTRAP_ADMIN_PASSWORD=' + password,
            IMAGE, 'start-dev', '--https-certificate-file=/test-certs/cert.pem', '--https-certificate-key-file=/test-certs/key.pem')
        port = command('docker', 'port', name, '8443/tcp').split(':')[-1]
        base = 'https://127.0.0.1:' + port

        def request(method, path, data=None, token=None, form=False, expected=None):
            headers = {'Content-Type': 'application/x-www-form-urlencoded' if form else 'application/json'}
            if token:
                headers['Authorization'] = 'Bearer ' + token
            body = None if data is None else (urllib.parse.urlencode(data).encode() if form else json.dumps(data).encode())
            req = urllib.request.Request(base + path, data=body, method=method, headers=headers)
            try:
                response = urllib.request.urlopen(req, timeout=15, context=context)
            except urllib.error.HTTPError as error:
                if expected is None:
                    raise
                if expected is not None and error.code == expected:
                    return None
                raise RuntimeError('Identity request rejected: ' + method + ' ' + path + ' status=' + str(error.code)) from None
            if expected is not None and response.status != expected:
                raise RuntimeError('Identity permission unexpectedly granted or returned wrong status: ' + method + ' ' + path)
            raw = response.read()
            return json.loads(raw) if raw else None

        for _ in range(90):
            try:
                token = request('POST', '/realms/master/protocol/openid-connect/token', {
                    'client_id': 'admin-cli', 'grant_type': 'password', 'username': 'operator', 'password': password}, form=True)['access_token']
                break
            except (OSError, RuntimeError):
                time.sleep(1)
        else:
            raise RuntimeError('Disposable Keycloak did not become ready')
        request('POST', '/admin/realms', {'realm': 'rentacompa', 'enabled': True}, token)

        def admin(method, path, data=None):
            return request(method, '/admin/realms/rentacompa' + path, data, token)

        for role in ('cliente', 'compa', 'admin'):
            admin('POST', '/roles', {'name': role})
        admin('POST', '/roles/compa/composites', [admin('GET', '/roles/cliente')])
        admin('POST', '/clients', {'clientId': 'rac-compa-provisioner', 'enabled': True, 'protocol': 'openid-connect',
            'publicClient': False, 'secret': secret, 'serviceAccountsEnabled': True,
            'standardFlowEnabled': False, 'directAccessGrantsEnabled': False, 'fullScopeAllowed': False})
        client = admin('GET', '/clients?clientId=rac-compa-provisioner')[0]
        account = admin('GET', '/clients/' + client['id'] + '/service-account-user')
        management = admin('GET', '/clients?clientId=realm-management')[0]
        old_roles = [admin('GET', '/clients/' + management['id'] + '/roles/' + r) for r in ('manage-users', 'view-realm')]
        admin('POST', '/users/' + account['id'] + '/role-mappings/clients/' + management['id'], old_roles)
        admin('POST', '/clients/' + client['id'] + '/scope-mappings/clients/' + management['id'], old_roles)
        for _ in range(2):
            configure_provisioner(admin, client, account)
            configure_staff(admin, 'http://localhost')
        standing_directory = directory / 'standing'
        bindings = configure_standing(admin, standing_directory)
        standing_secret = (standing_directory / 'match/secret').read_text().strip()
        assert configure_standing(admin, standing_directory) == bindings
        assert (standing_directory / 'match/secret').read_text().strip() == standing_secret
        reader = admin('GET', '/clients?clientId=rac-match-standing')[0]
        assert not reader['fullScopeAllowed'] and not reader['standardFlowEnabled'] and not reader['directAccessGrantsEnabled']
        reader_token = request('POST', '/realms/rentacompa/protocol/openid-connect/token', {
            'client_id': 'rac-match-standing', 'client_secret': standing_secret, 'grant_type': 'client_credentials'}, form=True)
        assert 'refresh_token' not in reader_token and reader_token['expires_in'] <= 300
        # Decoding inspects emitted protocol shape only; the Go integration
        # below verifies the real signature/issuer/audience with the real JWKS.
        reader_claims = json.loads(base64.urlsafe_b64decode(reader_token['access_token'].split('.')[1] + '=='))
        assert reader_claims['sub'] == bindings['rac-match-standing']
        assert 'rac-standing' in reader_claims['aud']
        assert reader_claims['resource_access']['rac-standing']['roles'] == ['standing.read']
        assert 'realm-management' not in reader_claims.get('resource_access', {})
        request('GET', '/admin/realms/rentacompa/users', token=reader_token['access_token'], expected=403)
        request('POST', '/realms/rentacompa/protocol/openid-connect/token', {
            'client_id': 'rac-match-standing', 'client_secret': standing_secret, 'grant_type': 'password',
            'username': 'not-a-user', 'password': 'not-a-password'}, form=True, expected=400)
        source = Path(__file__).resolve().parents[2] / 'rac-user-service'
        if source.exists():
            fixture = directory / 'reader-fixture.json'
            fixture.write_text(json.dumps({'issuer': base + '/realms/rentacompa',
                'jwks': 'https://identity-fixture:8443/realms/rentacompa/protocol/openid-connect/certs',
                'runtimeIssuer': 'https://identity-fixture:8443/realms/rentacompa',
                'subjects': bindings, 'token': reader_token['access_token']}), encoding='utf-8')
            os.chmod(fixture, 0o644)
            command('docker', 'run', '--rm', '--network', name,
                '--mount', f'type=bind,source={directory},target=/fixture,readonly',
                '--mount', f'type=bind,source={source},target=/source,readonly',
                '-v', 'rac-user-go-build:/root/.cache/go-build',
                '-e', 'SSL_CERT_FILE=/fixture/cert.pem', '-e', 'RAC_STANDING_IDENTITY_FIXTURE=/fixture/reader-fixture.json',
                '-e', 'GOPROXY=off', '-e', 'GOSUMDB=off', '-w', '/source',
                'golang:1.27.2', 'go', 'test', '-race', '-count=1', './internal/platform', '-run', 'TestProvisionedStandingReaderKeycloak')
        else:
            raise RuntimeError('User checkout required for real standing JWT verification')
        print('PASS: idempotent standing credentials, scoped real client token, no refresh/password/admin access, Go signature verification and real OAuth credentials to authenticated authority HTTP')
        assert admin('GET', '/users/' + account['id'] + '/role-mappings/clients/' + management['id']) == []
        assert admin('GET', '/clients/' + client['id'] + '/scope-mappings/clients/' + management['id']) == []
        admin('POST', '/users', {'username': 'subject', 'enabled': True})
        user = admin('GET', '/users?username=subject&exact=true')[0]
        provisioner_token = request('POST', '/realms/rentacompa/protocol/openid-connect/token', {
            'client_id': 'rac-compa-provisioner', 'client_secret': secret, 'grant_type': 'client_credentials'}, form=True)['access_token']
        role = admin('GET', '/roles/compa')
        request('POST', '/admin/realms/rentacompa/users/' + user['id'] + '/role-mappings/realm', [role], provisioner_token, expected=204)
        assert any(r['name'] == 'compa' for r in admin('GET', '/users/' + user['id'] + '/role-mappings/realm'))
        forbidden_role = admin('GET', '/roles/admin')
        request('POST', '/admin/realms/rentacompa/users/' + user['id'] + '/role-mappings/realm', [forbidden_role], provisioner_token, expected=403)
        for method, path, body in [
            ('PUT', '/users/' + user['id'], {'enabled': False}),
            ('PUT', '/users/' + user['id'] + '/reset-password', {'type': 'password', 'value': 'not-permitted'}),
            ('POST', '/users', {'username': 'unauthorized'}),
            ('GET', '/clients', None),
            ('PUT', '', {'registrationAllowed': False}),
        ]:
            request(method, '/admin/realms/rentacompa' + path, body, provisioner_token, expected=403)
        request('GET', '/admin/realms/master/users', token=provisioner_token, expected=403)
        request('GET', '/admin/realms/rentacompa/roles/compa', token=provisioner_token, expected=403)
        staff = admin('GET', '/clients?clientId=rac-staff')[0]
        assert not staff['enabled'] and not staff['directAccessGrantsEnabled']
        executions = admin('GET', '/authentication/flows/rac-staff-mfa/executions')
        assert [(e['providerId'], e['requirement']) for e in executions] == [('auth-username-password-form','REQUIRED'), ('auth-otp-form','REQUIRED')]
        assert len(admin('GET', '/clients/' + staff['id'] + '/roles')) == 5
        # Prove the required OTP execution is effective, not just a config flag.
        # Enable only in this disposable realm and restore disabled state below.
        admin('PUT', '/clients/' + staff['id'], {'enabled': True})
        otp_secret = secrets.token_hex(20)
        admin('POST', '/users', {'username': 'staff-fixture', 'enabled': True,
            'firstName': 'Synthetic', 'lastName': 'Fixture', 'email': 'staff@example.test', 'emailVerified': True,
            'credentials': [{'type': 'password', 'value': password, 'temporary': False},
                {'type': 'otp', 'secretData': json.dumps({'value': otp_secret}),
                 'credentialData': json.dumps({'subType': 'totp', 'digits': 6, 'counter': 0, 'period': 30, 'algorithm': 'HmacSHA1'})}]})

        class Form(HTMLParser):
            action = None
            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if tag == 'form' and attrs.get('id') in ('kc-form-login','kc-otp-login-form'):
                    self.action = attrs['action']

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args):
                return None

        cookies = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies), urllib.request.HTTPSHandler(context=context), NoRedirect())
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        state = secrets.token_urlsafe(24)
        redirect = 'http://localhost/staff/redirect.html'
        query = urllib.parse.urlencode({'client_id': 'rac-staff', 'response_type': 'code', 'scope': 'openid',
            'redirect_uri': redirect, 'state': state, 'code_challenge': challenge, 'code_challenge_method': 'S256'})
        page = opener.open(base + '/realms/rentacompa/protocol/openid-connect/auth?' + query).read().decode()
        form = Form(); form.feed(page)
        assert form.action
        assert urllib.parse.urlsplit(form.action).netloc == urllib.parse.urlsplit(base).netloc, 'unexpected login origin'
        try:
            page = opener.open(urllib.request.Request(form.action, data=urllib.parse.urlencode({'username':'staff-fixture','password':password,'credentialId':''}).encode())).read().decode()
        except urllib.error.HTTPError as error:
            raise RuntimeError('Synthetic staff password stage rejected: ' + str(error.code)) from None
        assert 'name="otp"' in page, 'password alone bypassed OTP'
        form = Form(); form.feed(page)
        assert form.action
        digest = hmac.new(otp_secret.encode(), struct.pack('>Q', int(time.time()) // 30), hashlib.sha1).digest()
        offset = digest[-1] & 15
        otp = str((struct.unpack('>I',digest[offset:offset+4])[0] & 0x7fffffff) % 1000000).zfill(6)
        try:
            opener.open(urllib.request.Request(form.action, data=urllib.parse.urlencode({'otp':otp}).encode()))
        except urllib.error.HTTPError as error:
            assert error.code in (302,303), 'OTP authentication failed'
            returned = urllib.parse.parse_qs(urllib.parse.urlsplit(error.headers['Location']).query)
        else:
            raise AssertionError('OTP did not complete authorization')
        assert returned['state'] == [state]
        tokens = request('POST', '/realms/rentacompa/protocol/openid-connect/token', {
            'client_id':'rac-staff','grant_type':'authorization_code','redirect_uri':redirect,
            'code_verifier':verifier,'code':returned['code'][0]}, form=True)
        # Decoding is for this protocol test only; production must verify JWT
        # signature/issuer/audience before trusting any AMR/azp/auth_time claim.
        claims = json.loads(base64.urlsafe_b64decode(tokens['access_token'].split('.')[1] + '=='))
        assert set(claims['amr']) == {'pwd','otp'} and claims['azp'] == 'rac-staff'
        assert abs(time.time() - claims['auth_time']) < 30
        admin('PUT', '/clients/' + staff['id'], {'enabled': False})
        print('PASS: real FGAP v2, compa-only grant, privilege denials, password-only cannot enter staff, OTP/PKCE succeeds with actual AMR proof; staff client disabled')
    finally:
        command('docker', 'rm', '-f', name, ok=False)
        command('docker', 'network', 'rm', name, ok=False)
        certificates.cleanup()


if __name__ == '__main__':
    main()
