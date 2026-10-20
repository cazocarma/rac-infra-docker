"""DEV-only completed booking with a disposable buyer and synthetic photo."""
import datetime as dt
import json
import os
import struct
import subprocess
import sys
import zlib
import urllib.request

import psycopg
from oidc_test_support import api,login

if os.environ.get("RAC_ENV")!="dev":raise RuntimeError("Review fixtures are DEV-only")
if len(sys.argv)>2 and sys.argv[1]=="cleanup":
    subprocess.run([sys.executable,"test_onboarding.py","cleanup",sys.argv[2]],check=True)
else:
    username=json.loads(subprocess.check_output([sys.executable,"test_onboarding.py","prepare"],text=True))["username"]
    try:
        buyer=login(username);me=api("GET","/api/user/me",buyer)
        provider_token=login("compa2");provider=api("GET","/api/user/me",provider_token)
        start=(dt.datetime.now(dt.timezone.utc)+dt.timedelta(days=135)).replace(hour=12,minute=0,second=0,microsecond=0)
        with psycopg.connect(os.environ["DATABASE_URL"]) as db:
            # Offset deterministically away from existing fixture bookings.
            for day in range(20):
                slot=start+dt.timedelta(days=day)
                exists=db.execute("SELECT EXISTS(SELECT 1 FROM sesion WHERE compa_id=%s AND fecha_inicio<%s AND fecha_fin>%s)",(provider["id"],slot+dt.timedelta(hours=1),slot)).fetchone()[0]
                if not exists:break
            else:raise RuntimeError("No free review fixture slot")
        booking=api("POST","/api/match/session",buyer,{"compa_id":provider["id"],"fecha_inicio":slot.isoformat(),"fecha_fin":(slot+dt.timedelta(hours=1)).isoformat()},expected=201)
        api("PUT","/api/match/session/"+booking["id"]+"/state",provider_token,{"estado":"activa"})
        with psycopg.connect(os.environ["DATABASE_URL"]) as db:
            # This row was created above and belongs exclusively to this fixture.
            db.execute("UPDATE sesion SET fecha_inicio=now()-interval '3 hours',fecha_fin=now()-interval '2 hours' WHERE id=%s AND cliente_id=%s",(booking["id"],me["id"]))
        api("PUT","/api/match/session/"+booking["id"]+"/state",provider_token,{"estado":"finalizada"})
        def chunk(kind,data):return struct.pack('!I',len(data))+kind+data+struct.pack('!I',zlib.crc32(kind+data)&0xffffffff)
        photo=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!2I5B',64,64,8,2,0,0,0))+chunk(b'IDAT',zlib.compress((b'\0'+bytes((40,140,100))*64)*64))+chunk(b'IEND',b'')
        url=os.environ.get("API_INTERNAL_URL","http://nginx")+"/api/user/me/photo"
        with urllib.request.urlopen(urllib.request.Request(url,data=photo,method="PUT",headers={"Authorization":"Bearer "+buyer,"Content-Type":"image/png"}),timeout=30) as response:
            assert response.status==200
        print(json.dumps({"username":username,"booking":booking["id"],"compa":provider["id"],"provider_name":provider["nombre"]}))
    except Exception:
        subprocess.run([sys.executable,"test_onboarding.py","cleanup",username],check=True)
        raise
