"""Two real OIDC sessions, responsive chat, lost network and read-only booking."""
from pathlib import Path
import json
import os
import re
import subprocess
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]
BASE=os.environ.get("RAC_BROWSER_URL","http://localhost").rstrip("/")
ARTIFACTS=Path(os.environ.get("RAC_BROWSER_ARTIFACTS",".local/chat-ui"));ARTIFACTS.mkdir(parents=True,exist_ok=True)
COMPOSE=["docker","compose","--env-file","envs/.env.dev","-p","rac-dev","-f","compose.yaml","-f","docker-compose.dev.yaml","-f","compose.observability.yaml","-f","compose.tests.yaml"]
if (ROOT/"envs/.env.photos-s3").exists(): COMPOSE += ["-f","compose.photos-s3.yaml"]
if (ROOT/"envs/.env.backups").exists(): COMPOSE += ["--env-file","envs/.env.backups","-f","compose.backups.yaml"]

def fixture(*args):
    result=subprocess.run(COMPOSE+["run","--rm","--no-deps","test-integration","python","test_chat_fixture.py",*args],cwd=ROOT,capture_output=True,text=True,timeout=120)
    if result.returncode: raise RuntimeError(result.stdout[-1500:]+result.stderr[-1500:])
    return result.stdout.strip()

info=json.loads(fixture())
try:
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        buyer_context=browser.new_context(viewport={"width":390,"height":844},locale="es-CL",timezone_id="America/Santiago")
        provider_context=browser.new_context(viewport={"width":1280,"height":900},locale="es-CL",timezone_id="America/Santiago")
        buyer=buyer_context.new_page();provider=provider_context.new_page()
        def semantics(page):
            locator=page.locator('flt-semantics-placeholder')
            if locator.count(): locator.evaluate('element => element.click()')
        def login(page,username):
            page.goto(BASE,wait_until="networkidle");semantics(page)
            page.get_by_role('button',name='Ingresar o crear cuenta').click()
            page.locator('#username').fill(username);page.locator('#password').fill('123456');page.locator('#kc-login').click()
            page.wait_for_url(BASE+'/#/home',timeout=60000);semantics(page)
        def open_chat(page):
            page.goto(BASE+'/#/chat',wait_until="networkidle");semantics(page)
            tile=page.get_by_role('button',name=re.compile('Reserva '+re.escape(info['booking'][:8])))
            try: expect(tile).to_be_visible(timeout=45000)
            except Exception:
                (ARTIFACTS/'chat-list-aria.txt').write_text(page.locator('body').aria_snapshot(),encoding='utf-8');raise
            tile.click()
            expect(page.get_by_role('textbox',name='Mensaje',exact=True)).to_be_visible(timeout=30000)
        def send(page,text):
            page.get_by_role('textbox',name='Mensaje',exact=True).fill(text)
            with page.expect_response(lambda r:'/api/chat/bookings/' in r.url and r.request.method=='POST') as response:
                page.get_by_role('button',name='Enviar mensaje',exact=True).click()
            assert response.value.status in (200,201), response.value.text()
        login(buyer,info['username']);login(provider,'compa2')
        open_chat(buyer);open_chat(provider)
        first='Hola 👋 coordinemos nuestro plan de prueba.'
        second='Perfecto, te responderé aunque se corte tu conexión.'
        send(buyer,first)
        try: expect(provider.get_by_text(first,exact=True)).to_be_visible(timeout=15000)
        except Exception:
            (ARTIFACTS/'chat-provider-aria.txt').write_text(provider.locator('body').aria_snapshot(),encoding='utf-8');provider.screenshot(path=str(ARTIFACTS/'chat-provider-failure.png'));raise
        send(provider,second);expect(buyer.get_by_text(second,exact=True)).to_be_visible(timeout=15000)
        buyer_context.set_offline(True)
        recovered='Este mensaje se recupera después de volver a conectarte.'
        send(provider,recovered)
        buyer_context.set_offline(False)
        expect(buyer.get_by_text(recovered,exact=True)).to_be_visible(timeout=45000)
        expect(buyer.get_by_text(recovered,exact=True)).to_have_count(1)
        buyer.mouse.move(1,1);provider.mouse.move(1,1);buyer.wait_for_timeout(500)
        buyer.screenshot(path=str(ARTIFACTS/'chat-mobile.png'),full_page=True)
        provider.screenshot(path=str(ARTIFACTS/'chat-desktop.png'),full_page=True)
        # Reopening from the list restores the persisted messages through OIDC.
        open_chat(buyer);expect(buyer.get_by_text(first,exact=True)).to_be_visible(timeout=30000)
        expect(buyer.get_by_text(recovered,exact=True)).to_be_visible(timeout=30000)
        fixture('cancel',info['username'],info['booking'])
        expect(buyer.get_by_role('checkbox',name='Solo lectura',exact=True)).to_be_visible(timeout=15000)
        expect(provider.get_by_role('checkbox',name='Solo lectura',exact=True)).to_be_visible(timeout=15000)
        expect(buyer.get_by_role('textbox',name='Mensaje',exact=True)).to_have_count(0)
        buyer.screenshot(path=str(ARTIFACTS/'chat-readonly-mobile.png'),full_page=True)
        browser.close()
        print('PASS: two real OIDC identities, mobile/desktop chat, bidirectional delivery, offline replay, persisted history and cancellation')
finally:
    fixture('cleanup',info['username'])
