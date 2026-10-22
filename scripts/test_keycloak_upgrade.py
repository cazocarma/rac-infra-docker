"""Upgrade synthetic Keycloak 24 data to the pinned version on isolated
PostgreSQL. Checks persisted identities/clients/roles and the RAC login theme.
No production/DEV volume is mounted and no database port is published.
"""
from pathlib import Path
import json
import secrets
import subprocess
import time
import urllib.parse
import urllib.request
import uuid
from test_identity_permissions import IMAGE

OLD = 'quay.io/keycloak/keycloak:24.0@sha256:f8ade94c1d0ad2f2fa7734a455fee5392764f402c43ca35e9af6bf63a2541dc9'
ROOT = Path(__file__).resolve().parents[1]


def run(*args, ok=True, input=None):
    result = subprocess.run(args, input=input, capture_output=True, text=True, timeout=240)
    if ok and result.returncode:
        raise RuntimeError('Disposable Keycloak upgrade command failed: ' + args[0])
    return result.stdout.strip()


def main():
    name = 'rac-kc-upgrade-' + uuid.uuid4().hex[:12]
    db, server = name + '-db', name + '-kc'
    password = secrets.token_urlsafe(32)
    try:
        run('docker','network','create',name)
        run('docker','run','-d','--name',db,'--network',name,'--network-alias','database',
            '--tmpfs','/var/lib/postgresql/data','-e','POSTGRES_USER=postgres','-e','POSTGRES_DB=keycloak',
            '-e','POSTGRES_PASSWORD='+password,'postgres:16.11-alpine')
        for _ in range(60):
            if (run('docker','exec',db,'pg_isready','-U','postgres',ok=False).endswith('accepting connections')
                and 'PostgreSQL init process complete' in run('docker','logs',db)):
                break
            time.sleep(1)
        else:
            raise RuntimeError('Disposable upgrade database did not start')
        # Match the stack: a non-superuser owning the separate keycloak DB/kc
        # schema. Password is generated URL-safe test data, never printed.
        run('docker','exec','-i',db,'psql','-U','postgres','-d','keycloak','-v','ON_ERROR_STOP=1',
            input="CREATE ROLE keycloak LOGIN PASSWORD '"+password+"'; ALTER DATABASE keycloak OWNER TO keycloak; CREATE SCHEMA kc AUTHORIZATION keycloak;")
        reference = None
        for image, prefix in ((OLD,'24.0'),(IMAGE,'26.8.1')):
            run('docker','run','-d','--name',server,'--network',name,'-p','127.0.0.1::8080',
                '--mount',f'type=bind,source={ROOT / "keycloak/themes/rac"},target=/opt/keycloak/themes/rac,readonly',
                '-e','KEYCLOAK_ADMIN=operator','-e','KEYCLOAK_ADMIN_PASSWORD='+password,
                '-e','KC_BOOTSTRAP_ADMIN_USERNAME=operator','-e','KC_BOOTSTRAP_ADMIN_PASSWORD='+password,
                '-e','KC_DB=postgres','-e','KC_DB_URL=jdbc:postgresql://database:5432/keycloak',
                '-e','KC_DB_USERNAME=keycloak','-e','KC_DB_PASSWORD='+password,'-e','KC_DB_SCHEMA=kc',image,'start-dev')
            port = run('docker','port',server,'8080/tcp').split(':')[-1]
            base = 'http://127.0.0.1:' + port

            def request(method,path,data=None,token=None,form=False):
                headers={'Content-Type':'application/x-www-form-urlencoded' if form else 'application/json'}
                if token: headers['Authorization']='Bearer '+token
                body=None if data is None else (urllib.parse.urlencode(data).encode() if form else json.dumps(data).encode())
                with urllib.request.urlopen(urllib.request.Request(base+path,data=body,method=method,headers=headers),timeout=15) as response:
                    raw=response.read()
                    return json.loads(raw) if raw else None

            for _ in range(120):
                try:
                    token=request('POST','/realms/master/protocol/openid-connect/token',{'grant_type':'password',
                        'client_id':'admin-cli','username':'operator','password':password},form=True)['access_token']
                    break
                except OSError:
                    time.sleep(1)
            else:
                raise RuntimeError('Disposable upgrade server did not start: '+prefix)
            version=request('GET','/admin/serverinfo',token=token)['systemInfo']['version']
            assert version.startswith(prefix), 'unexpected runtime version'
            if reference is None:
                request('POST','/admin/realms',{'realm':'upgrade-fixture','enabled':True,'loginTheme':'rac','displayName':'Rent-A-Compa'},token)
                request('POST','/admin/realms/upgrade-fixture/roles',{'name':'compa'},token)
                request('POST','/admin/realms/upgrade-fixture/clients',{'clientId':'upgrade-web','enabled':True,'publicClient':True,
                    'standardFlowEnabled':True,'directAccessGrantsEnabled':False,'redirectUris':['http://localhost/redirect.html'],
                    'attributes':{'pkce.code.challenge.method':'S256'}},token)
                request('POST','/admin/realms/upgrade-fixture/users',{'username':'synthetic-user','enabled':True,
                    'email':'fixture@example.test','emailVerified':True,'credentials':[{'type':'password','value':password,'temporary':False}]},token)
                reference=(request('GET','/admin/realms/upgrade-fixture/users?username=synthetic-user',token=token)[0]['id'],
                    request('GET','/admin/realms/upgrade-fixture/roles/compa',token=token)['id'],
                    request('GET','/admin/realms/upgrade-fixture/clients?clientId=upgrade-web',token=token)[0]['id'])
            else:
                current=(request('GET','/admin/realms/upgrade-fixture/users?username=synthetic-user',token=token)[0]['id'],
                    request('GET','/admin/realms/upgrade-fixture/roles/compa',token=token)['id'],
                    request('GET','/admin/realms/upgrade-fixture/clients?clientId=upgrade-web',token=token)[0]['id'])
                assert current==reference, 'upgrade rebound persisted identity or role/client'
                credentials=request('GET','/admin/realms/upgrade-fixture/users/'+reference[0]+'/credentials',token=token)
                assert any(c['type']=='password' for c in credentials)
            query=urllib.parse.urlencode({'client_id':'upgrade-web','response_type':'code','redirect_uri':'http://localhost/redirect.html',
                'code_challenge':'a'*43,'code_challenge_method':'S256','scope':'openid'})
            page=urllib.request.urlopen(base+'/realms/upgrade-fixture/protocol/openid-connect/auth?'+query).read().decode()
            assert 'kc-form-login' in page and 'Rent-A-Compa' in page, 'RAC theme failed after upgrade'
            run('docker','rm','-f',server)
        print('PASS: real PostgreSQL upgrade Keycloak 24 -> 26.8.1, persisted IDs/credentials/client policy and RAC login theme')
    finally:
        run('docker','rm','-f',server,ok=False)
        run('docker','rm','-f',db,ok=False)
        run('docker','network','rm',name,ok=False)


if __name__=='__main__':
    main()
