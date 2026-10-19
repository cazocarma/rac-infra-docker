"""Real OIDC and API permissions, DEV only."""
import datetime as dt
import os
import urllib.error
import urllib.request
import urllib.parse
import psycopg
from oidc_test_support import api, login, TOKENS, KC

created = []
try:
    login("cliente1", bad_verifier=True)
    base, compa, admin = login("cliente1"), login("compa1"), login("admin1")
    stranger, second_compa = login("cliente2"), login("compa2")
    buyer = api("GET", "/api/user/me", base)
    provider = api("GET", "/api/user/me", compa)
    api("GET", "/api/user/me", admin)
    api("GET", "/api/user/me", stranger)
    provider2 = api("GET", "/api/user/me", second_compa)
    quota_path = f"/api/match/compa/{provider['id']}/allowance"
    quota = api("GET", quota_path, compa)
    assert quota['limite_gratuito'] == 3 and quota['zona_horaria'] == 'America/Santiago'
    api("GET", quota_path, admin)
    api("GET", quota_path, expected=401)
    api("GET", quota_path, base, expected=403)
    api("GET", quota_path, second_compa, expected=403)
    api("GET", quota_path+"?fecha=invalid", compa, expected=400)
    # Real HTTP paywall: only bookings created by this test are modified/removed.
    anchor = dt.datetime.now(dt.timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
    quota2_path = f"/api/match/compa/{provider2['id']}/allowance"
    for delta in [49, 56, 63, 70, 77, 84]:
        week = anchor + dt.timedelta(days=delta)
        week -= dt.timedelta(days=week.weekday())
        allowance = api("GET", quota2_path+"?fecha="+week.date().isoformat(), second_compa)
        if allowance['usados'] == 0 and not allowance['suscripcion_activa']:
            break
    else:
        raise RuntimeError('No unused fixture week for quota acceptance test')
    quota_bookings = []
    for index in range(4):
        slot = week + dt.timedelta(days=index)
        booking = api("POST", "/api/match/session", base,
            {"compa_id":provider2['id'], "fecha_inicio":slot.isoformat(), "fecha_fin":(slot+dt.timedelta(hours=1)).isoformat()}, expected=201)
        created.append(booking['id'])
        quota_bookings.append(booking['id'])
    for booking_id in quota_bookings[:3]:
        api("PUT", f"/api/match/session/{booking_id}/state", second_compa, {"estado":"activa"})
    denied = api("PUT", f"/api/match/session/{quota_bookings[3]}/state", second_compa, {"estado":"activa"}, expected=402)
    assert denied['error'] == 'subscription_required' and denied['cupo']['disponibles'] == 0
    assert api("GET", f"/api/match/session/{quota_bookings[3]}", base)['estado'] == 'pendiente'
    api("PUT", f"/api/match/session/{quota_bookings[0]}/state", base, {"estado":"cancelada"})
    api("PUT", f"/api/match/session/{quota_bookings[3]}/state", second_compa, {"estado":"activa"})
    print('PASS: real HTTP three free accepts, fourth remains pending, early cancellation restores allowance')


    api("GET", "/api/auth/userinfo", "malformed", expected=401)
    api("POST", "/api/auth/login", data={"username": "cliente1", "password": "123456"}, expected=404)
    api("POST", "/api/user/compas", base, {}, expected=403)
    profile = api("POST", "/api/user/compas", compa, {"descripcion": "Compa de demostración", "tarifa_hora": 12000})
    api("POST", f"/api/user/compas/{profile['id']}/skills", base, {"skills": ["asado"]}, expected=403)
    api("POST", f"/api/user/compas/{profile['id']}/skills", second_compa, {"skills": ["asado"]}, expected=403)
    api("POST", f"/api/user/compas/{profile['id']}/skills", compa, {"skills": ["asado"]})
    api("GET", f"/api/match/compa/{provider['id']}/sessions", base, expected=403)
    api("GET", f"/api/match/availability/{profile['id']}", expected=401)
    availability = {d: ["00:00-23:59"] for d in ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]}
    api("POST", f"/api/match/availability/{profile['id']}", compa, {"availability": availability})
    api("GET", f"/api/match/availability/{profile['id']}", base)
    start = dt.datetime.now(dt.timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0) + dt.timedelta(days=30)
    session = api("POST", "/api/match/session", base, {"compa_id": profile["id"], "fecha_inicio": start.isoformat(), "fecha_fin": (start + dt.timedelta(hours=1)).isoformat()}, expected=201)
    created.append(session["id"])
    assert session["cliente_id"] == buyer["id"] and session["compa_id"] == provider["id"]
    # Durable alerts are private to each participant; read operations are idempotent.
    api("GET", "/api/user/notifications", expected=401)
    api("GET", "/api/user/notifications?limit=101", base, expected=400)
    alerts = api("GET", "/api/user/notifications?limit=100", base)['items']
    notice = next(n for n in alerts if n['sesion_id'] == session['id'])
    assert notice['tipo'] == 'pendiente' and notice['leido_en'] is None
    api("PUT", f"/api/user/notifications/{notice['id']}/read", stranger, expected=404)
    api("PUT", f"/api/user/notifications/{notice['id']}/read", admin, expected=404)
    api("PUT", f"/api/user/notifications/{notice['id']}/read", base)
    api("PUT", f"/api/user/notifications/{notice['id']}/read", base)
    alerts = api("GET", "/api/user/notifications?limit=100", base)['items']
    assert next(n for n in alerts if n['id'] == notice['id'])['leido_en'] is not None
    provider_alerts = api("GET", "/api/user/notifications?limit=100", compa)['items']
    assert any(n['sesion_id'] == session['id'] for n in provider_alerts)
    api("GET", "/api/match/session/" + session["id"], base)
    api("GET", "/api/match/session/" + session["id"], stranger, expected=403)
    api("PUT", "/api/match/session/" + session["id"] + "/state", base, {"estado": "cancelada"})
    cancelled = [n for n in api("GET", "/api/user/notifications?limit=100", base)['items'] if n['sesion_id'] == session['id'] and n['tipo'] == 'cancelada']
    assert len(cancelled) == 1
    api("PUT", "/api/match/session/" + session["id"] + "/state", base, {"estado": "cancelada"})
    cancelled = [n for n in api("GET", "/api/user/notifications?limit=100", base)['items'] if n['sesion_id'] == session['id'] and n['tipo'] == 'cancelada']
    assert len(cancelled) == 1
    print('PASS: durable booking notifications, ownership, read idempotence and no duplicate state alerts')
    api("GET", f"/api/match/client/{buyer['id']}/sessions", compa, expected=403)
    api("GET", f"/api/match/client/{buyer['id']}/sessions", admin)
    # A compa is also a buyer and may hire another compa.
    own_booking = api("POST", "/api/match/session", second_compa, {"compa_id": profile["id"], "fecha_inicio": start.isoformat(), "fecha_fin": (start + dt.timedelta(hours=1)).isoformat()}, expected=201)
    created.append(own_booking["id"])
    api("PUT", "/api/match/session/" + own_booking["id"] + "/state", second_compa, {"estado": "cancelada"})
    # Provider logout revokes the refresh token; APIs use short-lived JWTs.
    refresh = TOKENS[0]["refresh_token"]
    urllib.request.urlopen(urllib.request.Request(KC + "/realms/rentacompa/protocol/openid-connect/revoke", data=urllib.parse.urlencode({"client_id": "rac-web", "token": refresh, "token_type_hint": "refresh_token"}).encode())).read()
    try: urllib.request.urlopen(urllib.request.Request(KC + "/realms/rentacompa/protocol/openid-connect/token", data=urllib.parse.urlencode({"client_id": "rac-web", "grant_type": "refresh_token", "refresh_token": refresh}).encode()))
    except urllib.error.HTTPError as e: assert e.code == 400
    else: raise AssertionError("Revoked refresh token accepted")
    print("PASS: real OIDC code/PKCE, rejected wrong verifier, identity, inherited roles, publication, booking, IDOR and logout")
finally:
    # Only records created by this test; never delete customer or seed data.
    with psycopg.connect(os.environ["DATABASE_URL"]) as db:
        for identity in created: db.execute("DELETE FROM sesion WHERE id=%s", (identity,))
