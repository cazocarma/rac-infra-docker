"""Synthetic staff + least-privilege database principal in the disposable lab."""
import json
import os
import re
import secrets
import urllib.parse
import urllib.request
import uuid

import psycopg
from psycopg import sql
from oauth_token import TokenLease


def main():
    if (os.environ.get('RAC_ENV') != 'dev' or os.environ.get('PGHOST') != 'postgres' or
            os.environ.get('PGDATABASE') != 'rac_documents_e2e' or
            not re.fullmatch(r'rac-documents-e2e-[0-9a-f]{12}', os.environ.get('RAC_DISPOSABLE_PROJECT', ''))):
        raise RuntimeError('Owned disposable editorial lab required')
    credential = urllib.parse.urlsplit(os.environ['DOCUMENT_EDITORIAL_DATABASE_URL'])
    if (credential.hostname != 'postgres' or credential.path != '/rac_documents_e2e' or
            credential.username != 'rac_editorial_lab' or not credential.password or len(credential.password) < 24):
        raise RuntimeError('Separate synthetic editorial credential required')
    functions = ('draft_document', 'review_document', 'publish_document', 'read_editorial_document',
                 'editorial_ready', 'draft_assessment', 'review_assessment', 'publish_assessment',
                 'read_editorial_assessment', 'activate_editorial_bundle', 'read_editorial_registry')
    with psycopg.connect() as db:
        if db.execute('SELECT sum(version) FROM documents.head').fetchone()[0] != 0:
            raise RuntimeError('Empty editorial lab required')
        db.execute(sql.SQL('CREATE ROLE rac_editorial_lab LOGIN PASSWORD {}').format(sql.Literal(urllib.parse.unquote(credential.password))))
        db.execute('GRANT USAGE ON SCHEMA public,documents,audit TO rac_editorial_lab')
        signatures = db.execute("SELECT oid::regprocedure::text FROM pg_proc WHERE pronamespace='documents'::regnamespace AND proname=ANY(%s)", (list(functions),)).fetchall()
        if len(signatures) != 11:
            raise RuntimeError('Reviewed editorial function set required')
        for (signature,) in signatures:
            # regprocedure text comes from the owned schema, not user input.
            db.execute(sql.SQL('GRANT EXECUTE ON FUNCTION {} TO rac_editorial_lab').format(sql.SQL(signature)))
        chain, service = uuid.uuid4(), uuid.uuid4()
        db.execute('INSERT INTO audit.chain_heads(chain_id) VALUES(%s)', (chain,))
        db.execute("INSERT INTO audit.writer_principals VALUES('rac_editorial_lab',%s,%s)", (service, chain))

    def request(method, path, data=None, token=None, form=False):
        headers = {'Content-Type': 'application/x-www-form-urlencoded' if form else 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        body = None if data is None else (urllib.parse.urlencode(data).encode() if form else json.dumps(data).encode())
        with urllib.request.urlopen(urllib.request.Request('http://keycloak:8080' + path, data=body, headers=headers, method=method), timeout=10) as result:
            raw = result.read()
            return json.loads(raw) if raw else None

    operator = TokenLease(lambda: request('POST', '/realms/master/protocol/openid-connect/token', {
        'client_id': 'admin-cli', 'grant_type': 'password', 'username': os.environ['KEYCLOAK_ADMIN'],
        'password': os.environ['KEYCLOAK_ADMIN_PASSWORD']}, form=True))

    def admin(method, path, data=None):
        return request(method, '/admin/realms/rentacompa' + path, data, operator.get())

    client = admin('GET', '/clients?clientId=rac-staff')[0]
    if client['enabled'] or client['directAccessGrantsEnabled'] or client['fullScopeAllowed']:
        raise RuntimeError('Disabled least-privilege staff client expected before fixture')
    admin('PUT', '/clients/' + client['id'], {'enabled': True})
    legal = admin('GET', '/clients/' + client['id'] + '/roles/legal')
    accounts = []
    for username in ('editor-author', 'editor-reviewer'):
        password, otp = secrets.token_urlsafe(36), secrets.token_hex(20)
        admin('POST', '/users', {'username': username, 'enabled': True, 'emailVerified': True,
            'firstName': 'Synthetic', 'lastName': 'Editorial', 'email': username + '@example.test',
            'credentials': [{'type': 'password', 'value': password, 'temporary': False},
                {'type': 'otp', 'secretData': json.dumps({'value': otp}), 'credentialData': json.dumps({
                    'subType': 'totp', 'digits': 6, 'counter': 0, 'period': 30, 'algorithm': 'HmacSHA1'})}]})
        user = admin('GET', '/users?username=' + username + '&exact=true')[0]
        admin('POST', '/users/' + user['id'] + '/role-mappings/clients/' + client['id'], [legal])
        accounts.append({'username': username, 'subject': user['id'], 'password': password, 'otp_secret': otp})
    # Captured directly into an ignored private fixture file by the host harness.
    # Never log this output, tokens or environment contents to the console.
    print(json.dumps({'accounts': accounts}))


if __name__ == '__main__':
    main()
