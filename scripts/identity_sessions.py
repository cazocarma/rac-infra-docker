"""Dedicated session identifier/revocation client; never grants realm-management."""
from pathlib import Path
import secrets
import urllib.error

from identity_standing import write_atomic

AUDIENCE = 'rac-session-control'
CLIENT = 'rac-standing-sessions'


def configure_sessions(admin, directory):
    directory = Path(directory)

    def client(payload):
        found = admin('GET', '/clients?clientId=' + payload['clientId'])
        if found:
            admin('PUT', '/clients/' + found[0]['id'], payload)
        else:
            admin('POST', '/clients', payload)
        return admin('GET', '/clients?clientId=' + payload['clientId'])[0]

    resource = client({'clientId': AUDIENCE, 'enabled': True, 'protocol': 'openid-connect',
        'bearerOnly': True, 'publicClient': False, 'standardFlowEnabled': False,
        'implicitFlowEnabled': False, 'directAccessGrantsEnabled': False,
        'serviceAccountsEnabled': False, 'fullScopeAllowed': False})
    role_path = '/clients/' + resource['id'] + '/roles'
    try:
        role = admin('GET', role_path + '/sessions.revoke')
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
        admin('POST', role_path, {'name': 'sessions.revoke'})
        role = admin('GET', role_path + '/sessions.revoke')
    composites = admin('GET', role_path + '/sessions.revoke/composites')
    if composites:
        admin('DELETE', role_path + '/sessions.revoke/composites', composites)
    role = admin('GET', role_path + '/sessions.revoke')
    file = directory / 'secret'
    if admin('GET', '/clients?clientId=' + CLIENT) and not file.exists():
        raise RuntimeError('Session credential volume missing; restore or rotate explicitly')
    secret = file.read_text(encoding='utf-8').strip() if file.exists() else secrets.token_urlsafe(36)
    if len(secret) < 32 or any(ch.isspace() for ch in secret):
        raise RuntimeError('Invalid session credential file')
    if not file.exists():
        write_atomic(file, secret + '\n', 0o600)
    worker = client({'clientId': CLIENT, 'enabled': True, 'protocol': 'openid-connect',
        'publicClient': False, 'bearerOnly': False, 'clientAuthenticatorType': 'client-secret',
        'secret': secret, 'serviceAccountsEnabled': True, 'standardFlowEnabled': False,
        'directAccessGrantsEnabled': False, 'implicitFlowEnabled': False,
        'fullScopeAllowed': False, 'redirectUris': [], 'webOrigins': [],
        'attributes': {'access.token.lifespan': '60'},
        'protocolMappers': [
            {'name': 'sessions-audience', 'protocol': 'openid-connect', 'protocolMapper': 'oidc-audience-mapper',
             'config': {'included.custom.audience': AUDIENCE, 'access.token.claim': 'true', 'id.token.claim': 'false'}},
            {'name': 'sessions-role', 'protocol': 'openid-connect', 'protocolMapper': 'oidc-usermodel-client-role-mapper',
             'config': {'usermodel.clientRoleMapping.clientId': AUDIENCE,
                'claim.name': 'resource_access.' + AUDIENCE + '.roles', 'jsonType.label': 'String',
                'multivalued': 'true', 'access.token.claim': 'true', 'id.token.claim': 'false'}}]})
    account = admin('GET', '/clients/' + worker['id'] + '/service-account-user')
    for group in admin('GET', '/users/' + account['id'] + '/groups'):
        admin('DELETE', '/users/' + account['id'] + '/groups/' + group['id'])
    for path in ('/users/' + account['id'] + '/role-mappings/realm',
                 '/clients/' + worker['id'] + '/scope-mappings/realm'):
        assigned = admin('GET', path)
        if assigned:
            admin('DELETE', path, assigned)
    for entry in admin('GET', '/clients'):
        for path in ('/users/' + account['id'] + '/role-mappings/clients/' + entry['id'],
                     '/clients/' + worker['id'] + '/scope-mappings/clients/' + entry['id']):
            assigned = admin('GET', path)
            if assigned:
                admin('DELETE', path, assigned)
    admin('POST', '/users/' + account['id'] + '/role-mappings/clients/' + resource['id'], [role])
    admin('POST', '/clients/' + worker['id'] + '/scope-mappings/clients/' + resource['id'], [role])
    return account['id']
