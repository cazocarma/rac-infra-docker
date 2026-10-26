"""Disposable DEV identity only; create time off and verify real expiry delivery."""
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
import psycopg
from oidc_test_support import api,login,wait_booking_notifications
if os.environ.get('RAC_ENV')!='dev':raise RuntimeError('DEV-only fixture')
if len(sys.argv)>1 and sys.argv[1]=='prepare':
 username=json.loads(subprocess.check_output([sys.executable,'test_onboarding.py','prepare'],text=True))['username']
 try:
  token=login(username);me=api('GET','/api/user/me',token)
  profile={'descripcion':'Agenda sintética para pruebas de días libres.','tarifa_hora':12000,'zona_horaria':'America/Santiago','habilidades':['cine'],'availability':{day:['00:00-23:59'] for day in ['lunes','martes','miercoles','jueves','viernes','sabado','domingo']}}
  api('PUT','/api/user/me/compa',token,profile);token=login(username)
  date=(dt.datetime.now(dt.timezone.utc)+dt.timedelta(days=40)).date().isoformat()
  block=api('POST',f"/api/match/availability/{me['id']}/time-off",token,{'desde':date,'hasta':date},expected=201)
  buyer=login('cliente1');start=dt.datetime.combine(dt.date.fromisoformat(date),dt.time(15),tzinfo=dt.timezone.utc)
  denied=api('POST','/api/match/session',buyer,{'compa_id':me['id'],'fecha_inicio':start.isoformat(),'fecha_fin':(start+dt.timedelta(hours=1)).isoformat()},expected=400)
  assert denied['error']=='colision_horaria'
  api('GET',f"/api/match/availability/{me['id']}/time-off",buyer,expected=403)
  print(json.dumps({'username':username,'compa':me['id'],'block':block['id'],'date':date}))
 except BaseException:
  subprocess.run([sys.executable,'test_onboarding.py','cleanup',username],check=True);raise
elif len(sys.argv)>1 and sys.argv[1]=='expiry':
 username=sys.argv[2]
 if not re.fullmatch(r'rac-onboarding-test-[0-9a-f]{24}',username):raise RuntimeError('Refusing non-fixture change')
 provider_token=login(username);provider=api('GET','/api/user/me',provider_token)
 buyer_token=login('cliente1');start=(dt.datetime.now(dt.timezone.utc)+dt.timedelta(days=50)).replace(hour=15,minute=0,second=0,microsecond=0)
 booking=api('POST','/api/match/session',buyer_token,{'compa_id':provider['id'],'fecha_inicio':start.isoformat(),'fecha_fin':(start+dt.timedelta(hours=1)).isoformat()},expected=201)
 with psycopg.connect() as db:
  changed=db.execute("UPDATE sesion SET fecha_inicio=now()-interval '2 minutes',fecha_fin=now()+interval '58 minutes' WHERE id=%s AND compa_id=%s AND estado='pendiente'",(booking['id'],provider['id'])).rowcount
  assert changed==1
 for _ in range(30):
  state=api('GET','/api/match/session/'+booking['id'],buyer_token)
  if state['estado']=='expirada':break
  time.sleep(1)
 else:raise AssertionError('Worker did not expire fixture')
 wait_booking_notifications(buyer_token,booking['id'],['expirada'])
 wait_booking_notifications(provider_token,booking['id'],['expirada'])
 api('PUT','/api/match/session/'+booking['id']+'/state',provider_token,{'estado':'activa'},expected=400)
 print('PASS: automatic expiry, immutable expired state and real RabbitMQ notification to both parties')
else:raise RuntimeError('Unknown fixture operation')
