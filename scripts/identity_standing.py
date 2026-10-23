"""Provision dedicated standing readers; no realm-management privileges.

Secrets stay in per-client volumes, while the authority receives only public
client-to-service-subject bindings. Reconciliation never silently rotates keys.
"""
import json
from pathlib import Path
import secrets
import urllib.error

AUDIENCE = 'rac-standing'
READERS = {'match': 'rac-match-standing'}


def write_atomic(file, value, mode):
    file.parent.mkdir(parents=True, exist_ok=True)
    temporary = file.with_suffix('.tmp')
    temporary.write_text(value, encoding='utf-8')
    temporary.chmod(mode)
    temporary.replace(file)


def configure_standing(admin, directory):
    directory = Path(directory)
    payload = {'clientId': AUDIENCE, 'enabled': True, 'protocol': 'openid-connect',
        'bearerOnly': True, 'publicClient': False, 'standardFlowEnabled': False,
        'implicitFlowEnabled': False, 'directAccessGrantsEnabled': False,
        'serviceAccountsEnabled': False, 'fullScopeAllowed': False}

    def client(payload):
        existing = admin('GET', '/clients?clientId=' + payload['clientId'])
        if existing:
            admin('PUT', '/clients/' + existing[0]['id'], payload)
        else:
            admin('POST', '/clients', payload)
        return admin('GET', '/clients?clientId=' + payload['clientId'])[0]

    resource = client(payload)
    base = '/clients/' + resource['id']
    try:
        role = admin('GET', base + '/roles/standing.read')
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
        admin('POST', base + '/roles', {'name': 'standing.read'})
        role = admin('GET', base + '/roles/standing.read')
    subjects = {}
    for name, client_id in READERS.items():
        file = directory / name / 'secret'
        # Losing the volume must not rotate an existing deployed identity.
        existing = admin('GET', '/clients?clientId=' + client_id)
        if existing and not file.exists():
            raise RuntimeError('Standing credential volume missing; restore or rotate explicitly')
        secret = file.read_text(encoding='utf-8').strip() if file.exists() else secrets.token_urlsafe(36)
        if len(secret) < 32 or any(ch.isspace() for ch in secret):
            raise RuntimeError('Invalid standing credential file')
        # Persist before the first remote mutation so an interrupted bootstrap
        # can resume with the same secret rather than stranding a new client.
        if not file.exists():
            write_atomic(file, secret + '\n', 0o600)
        reader = client({'clientId': client_id, 'enabled': True, 'protocol': 'openid-connect',
            'publicClient': False, 'bearerOnly': False, 'clientAuthenticatorType': 'client-secret',
            'secret': secret, 'serviceAccountsEnabled': True, 'standardFlowEnabled': False,
            'directAccessGrantsEnabled': False, 'implicitFlowEnabled': False,
            'fullScopeAllowed': False, 'redirectUris': [], 'webOrigins': [],
            'attributes': {'access.token.lifespan': '300'},
            'protocolMappers': [
                {'name': 'standing-audience', 'protocol': 'openid-connect', 'protocolMapper': 'oidc-audience-mapper',
                 'config': {'included.custom.audience': AUDIENCE, 'access.token.claim': 'true', 'id.token.claim': 'false'}},
                {'name': 'standing-role', 'protocol': 'openid-connect', 'protocolMapper': 'oidc-usermodel-client-role-mapper',
                 'config': {'usermodel.clientRoleMapping.clientId': AUDIENCE,
                    'claim.name': 'resource_access.' + AUDIENCE + '.roles', 'jsonType.label': 'String',
                    'multivalued': 'true', 'access.token.claim': 'true', 'id.token.claim': 'false'}}]})
        account = admin('GET', '/clients/' + reader['id'] + '/service-account-user')
        # Remove existing direct realm/client assignments and client role scopes,
        # including privileges accidentally granted by a previous configuration.
        realm = '/users/' + account['id'] + '/role-mappings/realm'
        assigned = admin('GET', realm)
        if assigned:
            admin('DELETE', realm, assigned)
        realm_scope = '/clients/' + reader['id'] + '/scope-mappings/realm'
        assigned = admin('GET', realm_scope)
        if assigned:
            admin('DELETE', realm_scope, assigned)
        for entry in admin('GET', '/clients'):
            for path in ('/users/' + account['id'] + '/role-mappings/clients/' + entry['id'],
                         '/clients/' + reader['id'] + '/scope-mappings/clients/' + entry['id']):
                assigned = admin('GET', path)
                if assigned:
                    admin('DELETE', path, assigned)
        admin('POST', '/users/' + account['id'] + '/role-mappings/clients/' + resource['id'], [role])
        admin('POST', '/clients/' + reader['id'] + '/scope-mappings/clients/' + resource['id'], [role])
        write_atomic(file, secret + '\n', 0o600)
        subjects[client_id] = account['id']
    write_atomic(directory / 'readers' / 'subjects.json', json.dumps(subjects, sort_keys=True) + '\n', 0o644)
    return subjects
