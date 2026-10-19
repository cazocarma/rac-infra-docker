"""Idempotent Keycloak provisioning; demo users/data only in DEV."""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import psycopg

BASE = os.environ.get("KEYCLOAK_INTERNAL_URL", "http://keycloak:8080")
REALM = "rentacompa"
ENV = os.environ["RAC_ENV"]
def request(method, path, data=None, token=None, form=False):
    headers = {"Content-Type": "application/x-www-form-urlencoded" if form else "application/json"}
    if token: headers["Authorization"] = "Bearer " + token
    body = None if data is None else (urllib.parse.urlencode(data).encode() if form else json.dumps(data).encode())
    with urllib.request.urlopen(urllib.request.Request(BASE + path, data=body, headers=headers, method=method), timeout=10) as r:
        raw = r.read()
        return json.loads(raw) if raw else None

for attempt in range(60):
    try:
        token = request("POST", "/realms/master/protocol/openid-connect/token", {
            "client_id": "admin-cli", "grant_type": "password", "username": os.environ["KEYCLOAK_ADMIN"],
            "password": os.environ["KEYCLOAK_ADMIN_PASSWORD"]}, form=True)["access_token"]
        break
    except (OSError, urllib.error.URLError):
        if attempt == 59: raise RuntimeError("Keycloak did not become ready") from None
        time.sleep(2)

def admin(method, path, data=None): return request(method, "/admin/realms/" + REALM + path, data, token)
try: admin("GET", "")
except urllib.error.HTTPError as e:
    if e.code != 404: raise
    request("POST", "/admin/realms", {"realm": REALM, "enabled": True, "registrationAllowed": True}, token)

for name in ("cliente", "compa", "admin"):
    try: admin("GET", "/roles/" + name)
    except urllib.error.HTTPError as e:
        if e.code != 404: raise
        admin("POST", "/roles", {"name": name})
for name, children in {"compa": ["cliente"], "admin": ["cliente", "compa"], "default-roles-rentacompa": ["cliente"]}.items():
    admin("POST", "/roles/" + name + "/composites", [admin("GET", "/roles/" + child) for child in children])

web_redirect = os.environ["OIDC_WEB_REDIRECT_URI"]
origin = urllib.parse.urlsplit(web_redirect)
origin = origin.scheme + "://" + origin.netloc
for client_id, redirects, origins in [("rac-web", [web_redirect], [origin]), ("rac-mobile", [os.environ.get("OIDC_MOBILE_REDIRECT_URI", "cl.rentacompa.app://oauth2redirect")], [])]:
    payload = {"clientId": client_id, "enabled": True, "protocol": "openid-connect", "publicClient": True,
        "standardFlowEnabled": True, "directAccessGrantsEnabled": False, "implicitFlowEnabled": False,
        "serviceAccountsEnabled": False, "redirectUris": redirects, "webOrigins": origins,
        "attributes": {"pkce.code.challenge.method": "S256", "post.logout.redirect.uris": "+", "access.token.lifespan": "300"},
        "protocolMappers": [
            {"name": "rac-api-audience", "protocol": "openid-connect", "protocolMapper": "oidc-audience-mapper",
             "config": {"included.custom.audience": "rac-api", "access.token.claim": "true", "id.token.claim": "false"}},
            {"name": "realm-roles", "protocol": "openid-connect", "protocolMapper": "oidc-usermodel-realm-role-mapper",
             "config": {"claim.name": "realm_access.roles", "jsonType.label": "String", "multivalued": "true", "access.token.claim": "true", "id.token.claim": "true", "userinfo.token.claim": "true"}}]}
    existing = admin("GET", "/clients?clientId=" + client_id)
    if existing: admin("PUT", "/clients/" + existing[0]["id"], payload)
    else: admin("POST", "/clients", payload)

# Retire the previous password facade client without deleting its history.
for client in admin("GET", "/clients?clientId=frontend"):
    admin("PUT", "/clients/" + client["id"], {"enabled": False, "directAccessGrantsEnabled": False})

# Dedicated realm service account. Never distribute master-admin credentials to APIs.
provisioner = {"clientId": "rac-compa-provisioner", "enabled": True,
    "protocol": "openid-connect", "publicClient": False,
    "clientAuthenticatorType": "client-secret", "secret": os.environ["COMPA_PROVISIONER_SECRET"],
    "serviceAccountsEnabled": True, "standardFlowEnabled": False,
    "directAccessGrantsEnabled": False, "implicitFlowEnabled": False,
    "fullScopeAllowed": False, "redirectUris": [], "webOrigins": []}
existing = admin("GET", "/clients?clientId=rac-compa-provisioner")
if existing: admin("PUT", "/clients/" + existing[0]["id"], provisioner)
else: admin("POST", "/clients", provisioner)
client = admin("GET", "/clients?clientId=rac-compa-provisioner")[0]
account = admin("GET", "/clients/" + client["id"] + "/service-account-user")
management = admin("GET", "/clients?clientId=realm-management")[0]
permissions = [admin("GET", "/clients/" + management["id"] + "/roles/" + name) for name in ("manage-users", "view-realm")]
admin("POST", "/users/" + account["id"] + "/role-mappings/clients/" + management["id"], permissions)
admin("POST", "/clients/" + client["id"] + "/scope-mappings/clients/" + management["id"], permissions)

if ENV == "dev":
    with psycopg.connect(os.environ["DATABASE_URL"]) as db:
        for skill in ("asado", "cine", "karaoke", "running"):
            db.execute("INSERT INTO skill(id,name) VALUES(gen_random_uuid(),%s) ON CONFLICT(name) DO NOTHING", (skill,))
        for username, role in [("cliente1", "cliente"), ("cliente2", "cliente"), ("compa1", "compa"), ("compa2", "compa"), ("admin1", "admin")]:
            users = admin("GET", "/users?exact=true&username=" + username)
            if not users:
                admin("POST", "/users", {"username": username, "enabled": True, "email": username + "@demo.com", "emailVerified": True,
                    "firstName": "Demo", "lastName": username, "requiredActions": [],
                    "credentials": [{"type": "password", "value": "123456", "temporary": False}]})
                users = admin("GET", "/users?exact=true&username=" + username)
            user = users[0]
            if not user.get("firstName") or not user.get("lastName"):
                admin("PUT", "/users/" + user["id"], {"firstName": user.get("firstName") or "Demo", "lastName": user.get("lastName") or username, "requiredActions": []})
            admin("POST", "/users/" + user["id"] + "/role-mappings/realm", [admin("GET", "/roles/" + role)])
            effective = {entry["name"] for entry in admin("GET", "/users/" + user["id"] + "/role-mappings/realm/composite")}
            role = next(name for name in ("admin", "compa", "cliente") if name in effective)
            # Do not rebind real identities or delete existing rows.
            existing = db.execute("SELECT id,keycloak_id FROM usuario WHERE keycloak_id=%s OR correo=%s", (user["id"], user["email"])).fetchall()
            if len(existing) > 1: raise RuntimeError("Conflicting demo identities; reconcile explicitly")
            if existing:
                ident, old_sub = existing[0]
                if old_sub != user["id"] and not old_sub.startswith("kc-"):
                    raise RuntimeError("Refusing to rebind an existing identity")
                db.execute("UPDATE usuario SET keycloak_id=%s,rol=%s,verificado=true WHERE id=%s", (user["id"], role, ident))
            else:
                ident = db.execute("INSERT INTO usuario(id,nombre,correo,rol,keycloak_id,verificado) VALUES(gen_random_uuid(),%s,%s,%s,%s,true) RETURNING id", (username, user["email"], role, user["id"])).fetchone()[0]
            if role == "compa":
                db.execute("INSERT INTO compa_perfil(id,usuario_id,descripcion,tarifa_hora) VALUES(gen_random_uuid(),%s,'Compa de demostración',12000) ON CONFLICT(usuario_id) DO NOTHING", (ident,))
                db.execute("INSERT INTO compa_availability(compa_id,disponibilidad_json) VALUES(%s,%s::jsonb) ON CONFLICT(compa_id) DO NOTHING", (ident, json.dumps({d: ["00:00-23:59"] for d in ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]})))
print("OIDC clients and roles configured; demo data enabled only for DEV.")
