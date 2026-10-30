"""Real OIDC inbox, legacy routing, bulk-read and future notification; disposable buyer only."""
from browser_compose import command as browser_compose
from pathlib import Path
import json
import os
import re
import subprocess
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]
BASE=os.environ.get('RAC_BROWSER_URL','http://localhost').rstrip('/')
ARTIFACTS=Path(os.environ.get('RAC_BROWSER_ARTIFACTS','.local/alert-ui'));ARTIFACTS.mkdir(parents=True,exist_ok=True)
COMPOSE = browser_compose(ROOT)

def fixture(*args):
    result=subprocess.run(COMPOSE+['run','--rm','--no-deps','test-integration','python','test_chat_fixture.py',*args],cwd=ROOT,capture_output=True,text=True,timeout=120)
    if result.returncode:raise RuntimeError(result.stdout[-1500:]+result.stderr[-1500:])
    return result.stdout.strip()
def semantics(page):
    enable=page.locator('flt-semantics-placeholder')
    if enable.count():enable.evaluate('element=>element.click()')
info=json.loads(fixture())
try:
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        context=browser.new_context(viewport={'width':390,'height':844},locale='es-CL',timezone_id='America/Santiago')
        page=context.new_page()
        page.goto(BASE,wait_until='networkidle');semantics(page)
        page.get_by_role('button',name='Ingresar o crear cuenta').click()
        page.locator('#username').fill(info['username']);page.locator('#password').fill('123456');page.locator('#kc-login').click()
        page.wait_for_url(BASE+'/#/home',timeout=60000);semantics(page)
        with page.expect_response(lambda r:'/api/alert/notifications?' in r.url) as loaded:
            page.goto(BASE+'/#/alerts',wait_until='networkidle');semantics(page)
        payload=loaded.value.json();assert loaded.value.status==200 and payload['no_leidas']==2,payload
        expect(page.get_by_text('2 sin leer en tu bandeja',exact=False)).to_be_visible()
        page.mouse.move(1,1);page.screenshot(path=str(ARTIFACTS/'inbox-mobile.png'))
        # Use the same Authorization header observed on this real request; never log/persist it.
        headers={'Authorization':loaded.value.request.headers['authorization']}
        legacy=context.request.get(BASE+'/api/user/notifications',headers=headers)
        assert legacy.status==200 and legacy.json()['items']==payload['items']
        with page.expect_response(lambda r:r.url.endswith('/notifications/read-all') and r.request.method=='PUT') as marked:
            page.get_by_role('button',name='Marcar todas como leídas',exact=True).click()
        assert marked.value.status==200 and marked.value.json()['actualizadas']==2
        expect(page.get_by_text('0 sin leer en tu bandeja',exact=False)).to_be_visible()
        repeat=context.request.put(BASE+'/api/alert/notifications/read-all',headers=headers)
        assert repeat.status==200 and repeat.json()['actualizadas']==0
        fixture('cancel',info['username'],info['booking'])
        page.get_by_role('button',name='Actualizar notificaciones',exact=True).click()
        expect(page.get_by_text('1 sin leer en tu bandeja',exact=False)).to_be_visible()
        expect(page.get_by_role('group',name=re.compile('^Reserva cancelada Reserva '))).to_be_visible()
        page.mouse.move(1,1);page.screenshot(path=str(ARTIFACTS/'new-notification-mobile.png'))
        page.set_viewport_size({'width':1280,'height':900})
        page.screenshot(path=str(ARTIFACTS/'inbox-desktop.png'))
        browser.close()
        print('PASS: OIDC inbox owner, legacy alias, unread count, idempotent bulk read and later notification')
finally:
    fixture('cleanup',info['username'])
