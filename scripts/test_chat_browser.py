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
            page.bring_to_front()
            editor=page.get_by_role('textbox',name='Mensaje',exact=True)
            # Focus before resolving Flutter's live editor; its accessible name
            # changes on focus. Wait for Flutter to consume the input event.
            editor.click()
            native_editor=page.locator('textarea[data-semantics-role="text-field"]')
            expect(native_editor).to_be_visible()
            expect(native_editor).to_have_attribute('aria-label','Mensaje\nEscribe un mensaje…')
            native_editor.fill(text)
            expect(native_editor).to_have_value(text)
            expect(page.locator('flt-semantics-host span').filter(has_text=re.compile('^2000 characters remaining$'))).to_have_count(0)
            try:
                with page.expect_response(lambda r:'/api/chat/bookings/' in r.url and r.request.method=='POST') as response:
                    page.get_by_role('button',name='Enviar mensaje',exact=True).click()
            except Exception:
                (ARTIFACTS/'chat-send-failure.txt').write_text(page.locator('body').aria_snapshot(),encoding='utf-8')
                page.screenshot(path=str(ARTIFACTS/'chat-send-failure.png'))
                raise
            assert response.value.status in (200,201), response.value.text()
            expect(page.locator('flt-semantics-host span').filter(has_text=re.compile('^2000 characters remaining$'))).to_be_visible()
            expect(page.get_by_role('button',name='Enviar mensaje',exact=True)).to_be_enabled()
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
        # Safety controls use real authenticated APIs, not intercepted responses.
        buyer.get_by_role('button',name='Seguridad de la conversación',exact=True).click()
        expect(buyer.get_by_text('Tu tranquilidad importa',exact=True)).to_be_visible()
        def reveal(page,locator):
            page.mouse.move(page.viewport_size['width']*.75,page.viewport_size['height']*.75)
            page.mouse.wheel(0,-10000)
            for _ in range(70):
                if locator.count() and locator.is_visible():return
                page.mouse.wheel(0,140);page.wait_for_timeout(100)
            (ARTIFACTS/'chat-safety-failure.txt').write_text(page.locator('body').aria_snapshot(),encoding='utf-8')
            page.screenshot(path=str(ARTIFACTS/'chat-safety-failure.png'))
            raise AssertionError('Safety control is not visible: '+str(locator))
        def fill_flutter(page,label,value,limit):
            page.bring_to_front()
            field=page.get_by_role('textbox',name=label,exact=True)
            reveal(page,field);field.click()
            editor=page.locator('textarea[data-semantics-role="text-field"]')
            expect(editor).to_have_attribute('autocorrect','on')
            editor.fill(value)
            expect(editor).to_have_value(value)
            expect(page.locator('flt-semantics-host span').filter(has_text=re.compile(f'^{limit-len(value)} characters remaining$'))).to_be_visible()
        fill_flutter(buyer,'Describe qué ocurrió','Incidente sintético para verificar el flujo de moderación.',1000)
        reveal(buyer,buyer.get_by_role('button',name='Enviar reporte',exact=True))
        with buyer.expect_response(lambda r:r.url.endswith('/reports') and r.request.method=='POST') as reported:
            buyer.get_by_role('button',name='Enviar reporte',exact=True).click()
        assert reported.value.status==201,reported.value.text()
        report_id=reported.value.json()['id']
        expect(buyer.get_by_text('Reporte recibido.',exact=False)).to_be_visible()
        reveal(buyer,buyer.get_by_role('button',name='Bloquear conversación',exact=True))
        buyer.get_by_role('button',name='Bloquear conversación',exact=True).click()
        buyer.get_by_role('button',name='Confirmar bloqueo',exact=True).click()
        expect(buyer.get_by_role('button',name='Retirar mi bloqueo',exact=True)).to_be_visible()
        expect(provider.get_by_role('checkbox',name='Solo lectura',exact=True)).to_be_visible(timeout=15000)
        buyer.mouse.move(1,1);buyer.screenshot(path=str(ARTIFACTS/'chat-safety-mobile.png'))
        buyer.get_by_role('button',name='Retirar mi bloqueo',exact=True).click()
        buyer.get_by_role('button',name='Retirar bloqueo',exact=True).click()
        expect(buyer.get_by_role('button',name='Bloquear conversación',exact=True)).to_be_visible()
        buyer.get_by_role('button',name='Back',exact=True).click()
        provider.get_by_role('button',name='Actualizar conversación',exact=True).click()
        expect(buyer.get_by_role('textbox',name='Mensaje',exact=True)).to_be_visible()
        later='Mensaje posterior al reporte, fuera del contexto autorizado.'
        send(provider,later)
        expect(buyer.get_by_text(later,exact=True)).to_be_visible(timeout=15000)
        moderator_context=browser.new_context(viewport={"width":1280,"height":900},locale="es-CL",timezone_id="America/Santiago")
        moderator=moderator_context.new_page();login(moderator,'admin1')
        moderator.goto(BASE+'/#/chat',wait_until='networkidle');semantics(moderator)
        moderator.get_by_role('button',name='Moderación de reportes',exact=True).click()
        moderator.get_by_role('button',name=re.compile('Caso '+re.escape(report_id[:8]))).click()
        expect(moderator.get_by_text(first,exact=True)).to_have_count(0)
        fill_flutter(moderator,'Justificación de la consulta o resolución','Verificación autorizada del caso sintético de prueba.',500)
        with moderator.expect_response(lambda r:r.url.endswith('/access') and r.request.method=='POST') as accessed:
            moderator.get_by_role('button',name='Consultar y registrar acceso',exact=True).click()
        assert accessed.value.status==200,accessed.value.text()
        assert all(item['contenido']!=later for item in accessed.value.json()['items']), 'Moderator accessed messages after the report cutoff'
        reveal(moderator,moderator.get_by_text(first,exact=True))
        expect(moderator.get_by_text(first,exact=True)).to_be_visible()
        moderator.mouse.move(1,1);moderator.screenshot(path=str(ARTIFACTS/'chat-moderation-desktop.png'),full_page=True)
        close_case=moderator.get_by_role('button',name='Marcar atendido',exact=True)
        moderator.mouse.move(900,700)
        for _ in range(25):
            if close_case.count() and close_case.is_visible():break
            moderator.mouse.wheel(0,250);moderator.wait_for_timeout(100)
        close_case.click();moderator.get_by_role('button',name='Confirmar cierre',exact=True).click()
        expect(moderator.get_by_text('Casos pendientes',exact=True)).to_be_visible()
        fixture('cancel',info['username'],info['booking'])
        expect(buyer.get_by_role('checkbox',name='Solo lectura',exact=True)).to_be_visible(timeout=15000)
        expect(provider.get_by_role('checkbox',name='Solo lectura',exact=True)).to_be_visible(timeout=15000)
        expect(buyer.get_by_role('textbox',name='Mensaje',exact=True)).to_have_count(0)
        buyer.screenshot(path=str(ARTIFACTS/'chat-readonly-mobile.png'),full_page=True)
        browser.close()
        print('PASS: real OIDC chat, offline replay, history, block/unblock, report, justified moderation, resolution and cancellation')
finally:
    fixture('cleanup',info['username'])
