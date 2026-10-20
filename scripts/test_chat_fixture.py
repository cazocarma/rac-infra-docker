"""DEV-only chat booking owned by a disposable buyer; never removes demo users."""
import datetime as dt
import json
import os
import re
import subprocess
import sys
import psycopg
from oidc_test_support import api, login

if os.environ.get("RAC_ENV") != "dev":
    raise RuntimeError("Chat fixtures are DEV-only")

if sys.argv[1:] and sys.argv[1] == "cleanup":
    subprocess.run([sys.executable, "test_onboarding.py", "cleanup", sys.argv[2]], check=True)
elif sys.argv[1:] and sys.argv[1] == "cancel":
    if not re.fullmatch(r"rac-onboarding-test-[0-9a-f]{24}",sys.argv[2]): raise RuntimeError("Refusing non-fixture cancellation")
    api("PUT", "/api/match/session/" + sys.argv[3] + "/state", login(sys.argv[2]), {"estado": "cancelada"})
else:
    username = json.loads(subprocess.check_output([sys.executable, "test_onboarding.py", "prepare"], text=True))["username"]
    try:
        buyer = login(username)
        me = api("GET", "/api/user/me", buyer)
        provider_token = login("compa2")
        provider = api("GET", "/api/user/me", provider_token)
        start = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=175)).replace(hour=12, minute=0, second=0, microsecond=0)
        with psycopg.connect(os.environ["DATABASE_URL"]) as db:
            for day in range(60):
                slot = start + dt.timedelta(days=day)
                overlap = db.execute("SELECT EXISTS(SELECT 1 FROM sesion WHERE compa_id=%s AND fecha_inicio<%s AND fecha_fin>%s AND estado IN ('pendiente','activa'))", (provider["id"],slot+dt.timedelta(hours=1),slot)).fetchone()[0]
                if not overlap: break
            else: raise RuntimeError("No disposable chat slot available")
        booking = api("POST", "/api/match/session", buyer, {"compa_id":provider["id"],"fecha_inicio":slot.isoformat(),"fecha_fin":(slot+dt.timedelta(hours=1)).isoformat()}, expected=201)
        api("PUT", "/api/match/session/"+booking["id"]+"/state", provider_token, {"estado":"activa"})
        print(json.dumps({"username":username,"booking":booking["id"],"provider_name":provider["nombre"]}))
    except Exception:
        subprocess.run([sys.executable,"test_onboarding.py","cleanup",username],check=True)
        raise
