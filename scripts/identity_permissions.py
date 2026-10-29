"""Reconcile least privilege using Keycloak 26.8 FGAP v2; never grant
manage-users/view-realm or use the deprecated preview permission model.
"""
import urllib.error
import urllib.parse


def upsert(admin, path, payload):
    existing = admin('GET', path + '?name=' + urllib.parse.quote(payload['name']))
    existing = [item for item in existing if item.get('name') == payload['name']]
    if existing:
        admin('PUT', path + '/' + existing[0]['id'], {**payload, 'id': existing[0]['id']})
        return existing[0]['id']
    created = admin('POST', path, payload)
    if created and created.get('id'):
        return created['id']
    return next(item['id'] for item in admin('GET', path + '?name=' + urllib.parse.quote(payload['name'])) if item['name'] == payload['name'])


def configure_provisioner(admin, client, account):
    management = admin('GET', '/clients?clientId=realm-management')[0]
    for path in ('/users/' + account['id'] + '/role-mappings/clients/' + management['id'],
                 '/clients/' + client['id'] + '/scope-mappings/clients/' + management['id']):
        old = admin('GET', path)
        if old:
            admin('DELETE', path, old)
    admin('PUT', '', {'adminPermissionsEnabled': True})
    permission_client = admin('GET', '/clients?clientId=admin-permissions')[0]
    base = '/clients/' + permission_client['id'] + '/authz/resource-server'
    policy = upsert(admin, base + '/policy/user', {
        'name': 'rac-compa-service-only', 'logic': 'POSITIVE', 'users': [account['id']]})
    role = admin('GET', '/roles/compa')
    upsert(admin, base + '/permission/scope', {
        'name': 'rac-compa-map-users', 'resourceType': 'Users',
        'scopes': ['map-roles'], 'policies': [policy], 'decisionStrategy': 'UNANIMOUS'})
    upsert(admin, base + '/permission/scope', {
        'name': 'rac-compa-map-role-only', 'resourceType': 'Roles', 'resources': [role['id']],
        'scopes': ['map-role'], 'policies': [policy], 'decisionStrategy': 'UNANIMOUS'})


def staff_client_enabled(values):
    flag = values.get('STAFF_CLIENT_ENABLED', 'false')
    if flag not in ('true', 'false'):
        raise RuntimeError('Invalid staff client activation flag')
    if flag == 'true' and (values.get('RAC_ENV') != 'dev' or
            values.get('DOCUMENTS_ENFORCEMENT_ENABLED') != 'true' or
            values.get('STANDING_ENFORCEMENT_ENABLED') != 'true'):
        raise RuntimeError('Staff client activation requires explicit coordinated DEV rollout')
    return flag == 'true'


def configure_staff(admin, origin, *, enabled=False):
    """Prepared dedicated console client, disabled unless explicitly requested.
    No user gets a staff role. A commercial admin is not a T&S staff member.
    """
    if type(enabled) is not bool:
        raise RuntimeError('Explicit boolean staff client state required')
    alias = 'rac-staff-mfa'
    flows = admin('GET', '/authentication/flows')
    flow = next((f for f in flows if f['alias'] == alias), None)
    if not flow:
        admin('POST', '/authentication/flows', {'alias': alias, 'providerId': 'basic-flow', 'topLevel': True, 'builtIn': False})
        flow = next(f for f in admin('GET', '/authentication/flows') if f['alias'] == alias)
    executions_path = '/authentication/flows/' + alias + '/executions'
    for provider, reference in [('auth-username-password-form', 'pwd'), ('auth-otp-form', 'otp')]:
        executions = admin('GET', executions_path)
        execution = next((e for e in executions if e.get('providerId') == provider), None)
        if not execution:
            admin('POST', executions_path + '/execution', {'provider': provider})
            execution = next(e for e in admin('GET', executions_path) if e.get('providerId') == provider)
        admin('PUT', executions_path, {**execution, 'requirement': 'REQUIRED'})
        config = {'alias': 'rac-staff-' + reference, 'config': {
            'default.reference.value': reference, 'default.reference.maxAge': '300'}}
        if execution.get('authenticationConfig'):
            admin('PUT', '/authentication/config/' + execution['authenticationConfig'], config)
        else:
            admin('POST', '/authentication/executions/' + execution['id'] + '/config', config)
    payload = {'clientId': 'rac-staff', 'enabled': enabled, 'protocol': 'openid-connect', 'fullScopeAllowed': False,
        'publicClient': True, 'standardFlowEnabled': True, 'directAccessGrantsEnabled': False,
        'implicitFlowEnabled': False, 'serviceAccountsEnabled': False,
        'redirectUris': [origin + '/staff/redirect.html'], 'webOrigins': [origin],
        'authenticationFlowBindingOverrides': {'browser': flow['id']},
        'attributes': {'pkce.code.challenge.method': 'S256', 'access.token.lifespan': '300',
                       'post.logout.redirect.uris': '+'},
        'protocolMappers': [{'name': 'rac-staff-amr', 'protocol': 'openid-connect',
            'protocolMapper': 'oidc-amr-mapper', 'config': {'access.token.claim': 'true', 'id.token.claim': 'true'}},
            {'name': 'rac-staff-api-audience', 'protocol': 'openid-connect', 'protocolMapper': 'oidc-audience-mapper',
             'config': {'included.custom.audience': 'rac-admin-staff', 'access.token.claim': 'true', 'id.token.claim': 'false'}},
            {'name': 'rac-staff-document-owner-audience', 'protocol': 'openid-connect', 'protocolMapper': 'oidc-audience-mapper',
             'config': {'included.custom.audience': 'rac-user-documents', 'access.token.claim': 'true', 'id.token.claim': 'false'}}]}
    existing = admin('GET', '/clients?clientId=rac-staff')
    if existing:
        admin('PUT', '/clients/' + existing[0]['id'], payload)
    else:
        admin('POST', '/clients', payload)
    ident = admin('GET', '/clients?clientId=rac-staff')[0]['id']
    for name in ('ts_agent', 'ts_lead', 'legal', 'support', 'business_admin'):
        try:
            admin('GET', '/clients/' + ident + '/roles/' + name)
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
            admin('POST', '/clients/' + ident + '/roles', {'name': name})
    roles = admin('GET', '/clients/' + ident + '/roles')
    admin('POST', '/clients/' + ident + '/scope-mappings/clients/' + ident,
          [role for role in roles if role['name'] in ('ts_agent', 'ts_lead', 'legal', 'support', 'business_admin')])
