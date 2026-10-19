"""Real Keycloak Authorization Code + S256 PKCE and API permissions (DEV only)."""
import base64
import datetime as dt
import hashlib
import http.cookiejar
from html.parser import HTMLParser
import json
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request
import psycopg

if os.environ["RAC_ENV"] != "dev": raise RuntimeError("Demo integration tests are DEV-only")
KC = os.environ.get("KEYCLOAK_INTERNAL_URL", "http://keycloak:8080")
API = os.environ.get("API_INTERNAL_URL", "http://nginx")
REDIRECT = os.environ["OIDC_WEB_REDIRECT_URI"]
TOKENS = []
class Form(HTMLParser):
    action = None
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form" and attrs.get("id") == "kc-form-login": self.action = attrs["action"]
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl): return None

def login(username, bad_verifier=False):
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    params = {"client_id": "rac-web", "response_type": "code", "redirect_uri": REDIRECT,
        "scope": "openid profile email", "state": state, "nonce": nonce, "code_challenge": challenge, "code_challenge_method": "S256"}
    cookies = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies))
    page = opener.open(KC + "/realms/rentacompa/protocol/openid-connect/auth?" + urllib.parse.urlencode(params)).read().decode()
    form = Form(); form.feed(page)
    assert form.action, "Login form not returned"
    action = urllib.parse.urlsplit(form.action)
    action = KC + action.path + "?" + action.query
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies), NoRedirect())
    req = urllib.request.Request(action, data=urllib.parse.urlencode({"username": username, "password": "123456", "credentialId": ""}).encode())
    try: opener.open(req)
    except urllib.error.HTTPError as e:
        assert e.code in (302, 303), "Provider rejected credentials"
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(e.headers["Location"]).query)
    else: raise AssertionError("Expected authorization redirect")
    assert query["state"][0] == state
    payload = {"grant_type": "authorization_code", "client_id": "rac-web", "redirect_uri": REDIRECT,
        "code": query["code"][0], "code_verifier": secrets.token_urlsafe(48) if bad_verifier else verifier}
    req = urllib.request.Request(KC + "/realms/rentacompa/protocol/openid-connect/token", data=urllib.parse.urlencode(payload).encode())
    if bad_verifier:
        try: urllib.request.urlopen(req)
        except urllib.error.HTTPError as e: assert e.code == 400; return None
        raise AssertionError("PKCE verifier mismatch accepted")
    token = json.load(urllib.request.urlopen(req))
    claims = json.loads(base64.urlsafe_b64decode(token["id_token"].split(".")[1] + "=="))
    assert claims["nonce"] == nonce and claims["iss"] == os.environ["OIDC_ISSUER"]
    TOKENS.append(token)
    return token["access_token"]

def api(method, path, token=None, data=None, expected=200):
    headers = {"Content-Type": "application/json"}
    if token: headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(API + path, method=method, data=None if data is None else json.dumps(data).encode(), headers=headers)
    try: res = urllib.request.urlopen(req)
    except urllib.error.HTTPError as e: res = e
    body = res.read()
    assert res.code == expected, f"{method} {path}: {res.code}, expected {expected}: {body[:120]!r}"
    if not body: return None
    try: return json.loads(body)
    except json.JSONDecodeError: return body.decode()
