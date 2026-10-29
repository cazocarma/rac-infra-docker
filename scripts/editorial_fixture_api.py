"""Reproducible synthetic document setup through real MFA and editorial APIs.

No SQL writes, unsigned claims, direct grants, raw activation or token files.
Only accepts the owned disposable browser laboratory and its generated users.
"""
import argparse
import base64
import hashlib
import hmac
from html.parser import HTMLParser
import http.cookiejar
import json
import os
from pathlib import Path
import re
import secrets
import struct
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
KINDS = ('terms_client', 'terms_compa', 'community_rules', 'privacy', 'safety_rules')


def load_lab(path):
    path = path.resolve()
    if (path.name != 'state.json' or path.parent.parent != (ROOT.parent / '.local').resolve()
            or not re.fullmatch(r'rac-documents-e2e-[0-9a-f]{12}', path.parent.name)):
        raise RuntimeError('Owned disposable laboratory state required')
    state = json.loads(path.read_text(encoding='utf-8'))
    if state.get('project') != path.parent.name or state.get('state') != 'ready' or state.get('staff') is not True:
        raise RuntimeError('Ready editorial laboratory required')
    for key, port_key in (('web_url', 'web_port'), ('identity_url', 'identity_port')):
        if state[key] != 'http://localhost:' + str(state[port_key]):
            raise RuntimeError('Expected loopback fixture origin required')
    for service in ('keycloak', 'nginx'):
        result = subprocess.run(['docker', 'inspect', '--format',
            '{{.State.Running}} {{index .Config.Labels "com.docker.compose.project"}}',
            state['project'] + '-' + service + '-1'], capture_output=True, text=True, check=True)
        if result.stdout.strip() != 'true ' + state['project']:
            raise RuntimeError('Owned live fixture containers required')
    accounts = json.loads((path.parent / 'staff-fixture.json').read_text(encoding='utf-8'))['accounts']
    if [a['username'] for a in accounts] != ['editor-author', 'editor-reviewer']:
        raise RuntimeError('Synthetic two-person fixture required')
    return state, accounts


class Form(HTMLParser):
    action = None

    def handle_starttag(self, tag, attributes):
        attributes = dict(attributes)
        if tag == 'form' and attributes.get('id') in ('kc-form-login', 'kc-otp-login-form'):
            self.action = attributes.get('action')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


class FixtureLocalhostCookies(http.cookiejar.DefaultCookiePolicy):
    """Match browser Secure-cookie handling on this exact owned localhost port.

    The stdlib does not implement the browser localhost secure-origin exception.
    No remote HTTP host, alternate loopback spelling or other port is permitted.
    """
    def __init__(self, origin):
        super().__init__()
        parsed = urllib.parse.urlsplit(origin)
        if parsed.scheme != 'http' or parsed.hostname != 'localhost' or not parsed.port or parsed.path:
            raise RuntimeError('Exact fixture localhost origin required')
        self.fixture_netloc = parsed.netloc

    def return_ok_secure(self, cookie, request):
        target = urllib.parse.urlsplit(request.get_full_url())
        if cookie.secure and target.scheme == 'http' and target.netloc == self.fixture_netloc:
            return True
        return super().return_ok_secure(cookie, request)


def staff_token(state, account):
    """Protocol fixture; API owners independently verify both signed audiences."""
    base = state['identity_url']
    redirect = state['web_url'] + '/staff/redirect.html'
    cookies = http.cookiejar.CookieJar(policy=FixtureLocalhostCookies(base))
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(cookies), NoRedirect())
    def protocol(request, phase):
        try:
            return opener.open(request, timeout=15)
        except urllib.error.HTTPError as error:
            raise RuntimeError('Synthetic staff ' + phase + ' rejected: HTTP ' + str(error.code)) from None
        except urllib.error.URLError:
            raise RuntimeError('Synthetic staff ' + phase + ' unavailable') from None
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    nonce = secrets.token_urlsafe(24)
    query = urllib.parse.urlencode({'client_id': 'rac-staff', 'response_type': 'code', 'scope': 'openid',
        'redirect_uri': redirect, 'state': nonce, 'prompt': 'login', 'max_age': '0',
        'code_challenge': challenge, 'code_challenge_method': 'S256'})
    page = protocol(base + '/realms/rentacompa/protocol/openid-connect/auth?' + query, 'authorization').read().decode()

    def action(html):
        form = Form(); form.feed(html)
        if not form.action or urllib.parse.urlsplit(form.action).netloc != urllib.parse.urlsplit(base).netloc:
            raise RuntimeError('Unexpected fixture authentication origin')
        return form.action

    page = protocol(urllib.request.Request(action(page), data=urllib.parse.urlencode({
        'username': account['username'], 'password': account['password'], 'credentialId': ''}).encode()), 'password').read().decode()
    if 'name="otp"' not in page:
        raise RuntimeError('Fixture must require a second factor')
    digest = hmac.new(account['otp_secret'].encode(), struct.pack('>Q', int(time.time()) // 30), hashlib.sha1).digest()
    offset = digest[-1] & 15
    otp = str((struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7fffffff) % 1000000).zfill(6)
    try:
        opener.open(urllib.request.Request(action(page), data=urllib.parse.urlencode({'otp': otp}).encode()), timeout=15)
    except urllib.error.HTTPError as error:
        if error.code not in (302, 303):
            raise RuntimeError('Fixture second factor rejected') from None
        returned = urllib.parse.urlsplit(error.headers['Location'])
        expected = urllib.parse.urlsplit(redirect)
        if (returned.scheme, returned.netloc, returned.path) != (expected.scheme, expected.netloc, expected.path):
            raise RuntimeError('Unexpected fixture callback')
        parameters = urllib.parse.parse_qs(returned.query)
    else:
        raise RuntimeError('Expected authorization callback')
    if parameters.get('state') != [nonce] or len(parameters.get('code', [])) != 1:
        raise RuntimeError('Fixture authorization state mismatch')
    request = urllib.request.Request(base + '/realms/rentacompa/protocol/openid-connect/token', data=urllib.parse.urlencode({
        'client_id': 'rac-staff', 'grant_type': 'authorization_code', 'redirect_uri': redirect,
        'code_verifier': verifier, 'code': parameters['code'][0]}).encode())
    with protocol(request, 'token exchange') as response:
        token = json.load(response)['access_token']
    return token


def api(state, token, method, path, body=None, expected=200):
    if not path.startswith('/api/admin/staff/documents/'):
        raise RuntimeError('Editorial document API only')
    request = urllib.request.Request(state['web_url'] + path, method=method,
        data=None if body is None else json.dumps(body, ensure_ascii=False).encode(),
        headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=15) as response:
            status, result = response.status, json.load(response)
    except urllib.error.HTTPError as error:
        status, result = error.code, json.loads(error.read())
    if status != expected:
        raise RuntimeError('Editorial fixture API rejected ' + method + ' ' + path + ': status ' + str(status))
    return result


def new_manifest(project):
    manifest = {'schema': 1, 'project': project, 'documents': []}
    for kind in KINDS:
        text = 'DOCUMENTO SINTÉTICO PARA PRUEBAS REPRODUCIBLES. No son términos jurídicos definitivos. Tipo: ' + kind
        manifest['documents'].append({'event_id': str(uuid.uuid4()), 'document_id': str(uuid.uuid4()),
            'review_event': str(uuid.uuid4()), 'publish_event': str(uuid.uuid4()), 'kind': kind,
            'version': 'reproducible-synthetic-1', 'locale': 'es', 'content': text,
            'material_change': True, 'sha256': hashlib.sha256(text.encode()).hexdigest()})
    return manifest


def validate_manifest(manifest, project):
    if set(manifest) != {'schema', 'project', 'documents'} or manifest['schema'] != 1 or manifest['project'] != project or len(manifest['documents']) != 5:
        raise RuntimeError('Matching synthetic manifest required')
    references = set()
    for document, kind in zip(manifest['documents'], KINDS):
        text = 'DOCUMENTO SINTÉTICO PARA PRUEBAS REPRODUCIBLES. No son términos jurídicos definitivos. Tipo: ' + kind
        if (set(document) != {'event_id', 'document_id', 'review_event', 'publish_event', 'kind', 'version', 'locale', 'content', 'material_change', 'sha256'} or
                document['kind'] != kind or document['version'] != 'reproducible-synthetic-1' or document['locale'] != 'es' or
                document['content'] != text or document['material_change'] is not True or document['sha256'] != hashlib.sha256(text.encode()).hexdigest()):
            raise RuntimeError('Only fixed synthetic document content is permitted')
        for field in ('event_id', 'document_id', 'review_event', 'publish_event'):
            try:
                reference = uuid.UUID(document[field])
            except (ValueError, TypeError, AttributeError):
                raise RuntimeError('Synthetic UUID reference required') from None
            if reference.version != 4 or str(reference) != document[field] or reference in references:
                raise RuntimeError('Unique canonical synthetic UUID references required')
            references.add(reference)


def require_result(actual, expected):
    """Keep protocol assertions active even when Python runs with -O."""
    if actual != expected:
        raise RuntimeError('Unexpected synthetic editorial protocol result')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    args = parser.parse_args()
    state, accounts = load_lab(args.state)
    manifest_path = args.state.resolve().parent / 'api-document-fixture.json'
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        if manifest.get('project') != state['project'] or manifest.get('schema') != 1 or len(manifest.get('documents', [])) != 5:
            raise RuntimeError('Matching synthetic manifest required')
    else:
        manifest = new_manifest(state['project'])
        with os.fdopen(os.open(manifest_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w', encoding='utf-8') as output:
            json.dump(manifest, output, ensure_ascii=False, indent=2)
    validate_manifest(manifest, state['project'])
    author, reviewer = [staff_token(state, account) for account in accounts]
    if api(state, author, 'GET', '/api/admin/staff/documents/registry/es') != {'registry_version': 0}:
        raise RuntimeError('Fixture must not alter an already activated registry')
    for document in manifest['documents']:
        draft = {k: v for k, v in document.items() if k not in ('review_event', 'publish_event')}
        ref = {'document_id': document['document_id'], 'sha256': document['sha256']}
        if api(state, author, 'POST', '/api/admin/staff/documents/drafts', draft) != {'document_id': ref['document_id']}:
            raise RuntimeError('Unexpected draft receipt')
        view = api(state, reviewer, 'GET', '/api/admin/staff/documents/' + ref['document_id'])
        if view['author_id'] != accounts[0]['subject'] or view['content'] != document['content'] or view['sha256'] != ref['sha256']:
            raise RuntimeError('Exact reviewed draft mismatch')
        if view['decision'] is None:
            require_result(api(state, author, 'POST', '/api/admin/staff/documents/reviews', {**ref, 'event_id': str(uuid.uuid4()), 'decision': 'approved'}, expected=403), {'error': 'editorial_self_review'})
            require_result(api(state, reviewer, 'POST', '/api/admin/staff/documents/publications', {**ref, 'event_id': document['publish_event']}, expected=409), {'error': 'editorial_revision_conflict'})
        api(state, reviewer, 'POST', '/api/admin/staff/documents/reviews', {**ref, 'event_id': document['review_event'], 'decision': 'approved'})
        api(state, reviewer, 'POST', '/api/admin/staff/documents/publications', {**ref, 'event_id': document['publish_event']})
        view = api(state, reviewer, 'GET', '/api/admin/staff/documents/' + ref['document_id'])
        if view['reviewer_id'] != accounts[1]['subject'] or view['published_at'] is None:
            raise RuntimeError('Independent publication missing')
        print('PUBLISHED: ' + document['kind'], flush=True)
    require_result(api(state, reviewer, 'GET', '/api/admin/staff/documents/registry/es'), {'registry_version': 0})
    print('PASS: five synthetic documents drafted, independently reviewed and published through real MFA/proxy/owner APIs; registry remains inactive')


if __name__ == '__main__':
    try:
        main()
    except (urllib.error.URLError, json.JSONDecodeError, KeyError):
        raise SystemExit('Synthetic editorial protocol fixture failed; no credentials or protocol payloads logged') from None
