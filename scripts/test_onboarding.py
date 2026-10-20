"""DEV-only disposable Keycloak identities for API and browser onboarding tests."""
import datetime as dt
import json
import os
import re
import secrets
import sys
import urllib.parse
import urllib.request
import psycopg
from oidc_test_support import api, login, TOKENS, KC

def request(method, path, token=None, data=None, form=False):
    headers = {"Content-Type": "application/x-www-form-urlencoded" if form else "application/json"}
    if token: headers['Authorization'] = 'Bearer ' + token
    raw = None if data is None else (urllib.parse.urlencode(data).encode() if form else json.dumps(data).encode())
    with urllib.request.urlopen(urllib.request.Request(KC+path, method=method, data=raw, headers=headers), timeout=15) as response:
        raw = response.read()
        return json.loads(raw) if raw else None

admin_token = request('POST', '/realms/master/protocol/openid-connect/token', data={
    'client_id':'admin-cli','grant_type':'password', 'username':os.environ['KEYCLOAK_ADMIN'], 'password':os.environ['KEYCLOAK_ADMIN_PASSWORD']}, form=True)['access_token']

def admin(method, path, data=None):
    return request(method, '/admin/realms/rentacompa'+path, admin_token, data)

def prepare():
    username = 'rac-onboarding-test-' + secrets.token_hex(12)
    admin('POST','/users',{'username':username,'email':username+'@fixture.test','emailVerified':True,
        'enabled':True,'firstName':'Prueba','lastName':'Compa',
        'credentials':[{'type':'password','value':'123456','temporary':False}]})
    return username

def cleanup(username):
    if not re.fullmatch(r'rac-onboarding-test-[0-9a-f]{24}', username):
        raise RuntimeError('Refusing to remove a non-test identity')
    users = admin('GET','/users?exact=true&username='+username)
    if not users: return
    user = admin('GET','/users/'+users[0]['id'])
    if user.get('email') != username+'@fixture.test' or user.get('firstName') != 'Prueba' or user.get('lastName') != 'Compa':
        raise RuntimeError('Identity lacks fixture ownership markers')
    with psycopg.connect(os.environ['DATABASE_URL']) as db:
        row = db.execute('SELECT id,foto_clave FROM usuario WHERE keycloak_id=%s',(user['id'],)).fetchone()
        if row:
            if row[1]:
                api('DELETE','/api/user/me/photo',login(username))
            db.execute('DELETE FROM sesion WHERE cliente_id=%s OR compa_id=%s',(row[0],row[0]))
            db.execute('DELETE FROM compa_availability WHERE compa_id=%s',(row[0],))
            db.execute('DELETE FROM usuario WHERE id=%s',(row[0],))
    admin('DELETE','/users/'+user['id'])

if len(sys.argv)>1 and sys.argv[1]=='prepare':
    print(json.dumps({'username':prepare()}))
elif len(sys.argv)>2 and sys.argv[1]=='cleanup':
    cleanup(sys.argv[2]);print('Disposable onboarding identity removed')
else:
    username=prepare()
    try:
        token=login(username)
        me=api('GET','/api/user/me',token)
        assert me['role']=='cliente'
        personal={'nombre':'Cris de prueba','telefono':'+56 9 1234 5678','pais':'Chile','region':'Metropolitana','ciudad':'Santiago','intereses':['Cine','cine','Running']}
        api('PUT','/api/user/me',expected=401)
        for extra in ({'role':'admin'},{'correo':'foreign@fixture.test'},{'usuario_id':me['id']}):
            api('PUT','/api/user/me',token,{**personal,**extra},expected=400)
        other=api('GET','/api/user/me',login('cliente1'))
        api('PUT','/api/user/me',token,personal)
        saved=api('GET','/api/user/me',token)
        assert saved['nombre']==personal['nombre'] and saved['intereses']==['Cine','Running']
        assert saved['correo']==me['correo'] and saved['role']=='cliente'
        again=api('GET','/api/user/me',login(username))
        assert again['nombre']==personal['nombre'] and again['telefono']==personal['telefono']
        assert api('GET','/api/user/me',login('cliente1'))==other
        # Keep TOKENS[-1] associated with the test identity for the role refresh below.
        token=login(username)
        print('PASS: personal profile persists across login, rejects identity/role assignment and isolates owners')
        path='/api/user/me/compa'
        api('GET',path,token,expected=404)
        api('PUT',path,expected=401)
        profile={'descripcion':'Compartamos cine y actividades entretenidas juntos.','tarifa_hora':12000,
            'zona_horaria':'America/Santiago','habilidades':['cine','running'], 'availability':{day:['00:00-23:59'] for day in ['lunes','martes','miercoles','jueves','viernes','sabado','domingo']}}
        api('PUT',path,token,{**profile,'role':'admin'},expected=400)
        api('PUT',path,token,{**profile,'usuario_id':me['id']},expected=400)
        api('PUT',path,token,{**profile,'availability':{'lunes':['21:00-20:00']}},expected=400)
        api('PUT',path,token,{**profile,'zona_horaria':'Local'},expected=400)
        api('PUT',path,token,profile)
        # Old JWTs do not gain privileges; only refreshed, signed tokens may authorize.
        api('GET',f"/api/match/compa/{me['id']}/allowance",token,expected=403)
        renewed=request('POST','/realms/rentacompa/protocol/openid-connect/token', data={
            'grant_type':'refresh_token','client_id':'rac-web','refresh_token':TOKENS[-1]['refresh_token']},form=True)
        token=renewed['access_token']
        assert api('GET','/api/user/me',token)['role']=='compa'
        allowance=api('GET',f"/api/match/compa/{me['id']}/allowance",token)
        assert allowance['disponibles']==3 and not allowance['suscripcion_activa']
        profile['habilidades']=['cine']
        api('PUT',path,token,profile)
        own=api('GET',path,token)
        assert own['profile']['habilidades']==['cine']
        public=api('GET','/api/user/compas/'+own['profile']['id'])
        assert public['usuario_id']==me['id']
        buyer=login('cliente1')
        start=dt.datetime.now(dt.timezone.utc).replace(hour=12,minute=0,second=0,microsecond=0)+dt.timedelta(days=14)
        profile['availability']={day:['09:00-10:00'] for day in profile['availability']}
        api('PUT',path,token,profile)
        legacy={k:v for k,v in profile.items() if k!='zona_horaria'}
        api('PUT',path,token,legacy)
        assert api('GET',path,token)['zona_horaria']=='America/Santiago'
        begin=start.replace(hour=0)
        query=urllib.parse.urlencode({'inicio':begin.isoformat(),'fin':(begin+dt.timedelta(days=1)).isoformat(),'minutos':'60'})
        slots_path=f"/api/match/availability/{me['id']}/slots?"+query
        offer=api('GET',slots_path,buyer)
        assert offer['zona_horaria']=='America/Santiago' and len(offer['slots'])==1
        start=dt.datetime.fromisoformat(offer['slots'][0])
        booking=api('POST','/api/match/session',buyer,{'compa_id':own['profile']['id'], 'fecha_inicio':start.isoformat(),'fecha_fin':(start+dt.timedelta(hours=1)).isoformat()},expected=201)
        api('PUT',f"/api/match/session/{booking['id']}/state",token,{'estado':'activa'})
        assert api('GET',slots_path,buyer)['slots']==[]
        assert any(n['sesion_id']==booking['id'] for n in api('GET','/api/user/notifications',token)['items'])
        print('PASS: base account activates for free, refreshes signed role, edits skills, publishes availability and receives/accepts reservation')
    finally:
        cleanup(username)
