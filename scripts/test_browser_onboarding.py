"""Real free onboarding with an isolated, automatically removed DEV identity."""
from pathlib import Path
import json
import os
import re
import subprocess
from playwright.sync_api import sync_playwright, expect

if os.environ.get('RAC_ENV', 'dev') != 'dev':
    raise RuntimeError('Onboarding browser fixtures are DEV-only')
ROOT = Path(__file__).resolve().parent.parent
BASE = os.environ.get('RAC_BROWSER_URL', 'http://localhost').rstrip('/')
ARTIFACTS = Path(os.environ.get('RAC_BROWSER_ARTIFACTS', '.local/ui-review'))
ARTIFACTS.mkdir(parents=True, exist_ok=True)
COMPOSE = ['docker','compose','--env-file','envs/.env.dev','-p','rac-dev','-f','compose.yaml',
    '-f','docker-compose.dev.yaml','-f','compose.observability.yaml','-f','compose.tests.yaml']

def fixture(*args):
    result = subprocess.run(COMPOSE+['run','--rm','test-integration','python','test_onboarding.py',*args],
        cwd=ROOT, text=True, capture_output=True, timeout=60)
    if result.returncode:
        raise RuntimeError('Onboarding fixture failed: '+result.stderr[-1000:])
    return result.stdout.strip()

username = json.loads(fixture('prepare'))['username']
try:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width':1280,'height':900},timezone_id='America/Santiago')
        page = context.new_page()
        errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        def semantics():
            placeholder=page.locator('flt-semantics-placeholder')
            if placeholder.count(): placeholder.evaluate('element => element.click()')
        def find(role, name):
            locator=page.get_by_role(role,name=re.compile(re.escape(name)))
            page.mouse.move(page.viewport_size['width']*.6,page.viewport_size['height']*.7)
            for _ in range(40):
                if locator.count() and locator.first.is_visible(): return locator.first
                page.mouse.wheel(0,220)
                page.wait_for_timeout(100)
            (ARTIFACTS/'onboarding-failure.txt').write_text(page.locator('body').aria_snapshot(),encoding='utf-8')
            page.screenshot(path=str(ARTIFACTS/'onboarding-failure.png'))
            raise AssertionError('Missing form control: '+name)
        def fill(name,value):
            control=find('textbox',name)
            control.click()
            page.wait_for_timeout(150)
            page.keyboard.press('ControlOrMeta+A')
            page.keyboard.type(value,delay=15)
            page.wait_for_timeout(150)
            expect(control).to_have_value(value)
            page.keyboard.press('Tab')
            page.wait_for_timeout(100)
        page.goto(BASE,wait_until='networkidle')
        semantics()
        page.get_by_role('button',name='Ingresar o crear cuenta').click()
        page.locator('#username').fill(username)
        page.locator('#password').fill('123456')
        page.locator('#kc-login').click()
        page.wait_for_url(BASE+'/#/home',timeout=60000)
        semantics()
        page.get_by_role('button',name='Sé Compa',exact=True).click()
        expect(page.get_by_text('Comparte lo que te gusta hacer',exact=True)).to_be_visible(timeout=30000)
        page.set_viewport_size({'width':320,'height':568})
        page.screenshot(path=str(ARTIFACTS/'mobile-onboarding.png'))
        page.set_viewport_size({'width':1280,'height':900})
        fill('Cuéntanos sobre ti','Compartamos cine y actividades entretenidas juntos.')
        fill('Tarifa por hora (CLP)','12000')
        fill('Habilidades','asado, cine')
        for day in ['Lunes','Martes','Miércoles','Jueves','Viernes','Sábado','Domingo']:
            fill(day,'12:00-22:00')
        try:
            with page.expect_response(lambda r:r.url.endswith('/api/user/me/compa') and r.request.method=='PUT') as saved:
                find('button','Activar mi perfil gratis').click()
        except Exception:
            (ARTIFACTS/'onboarding-submit-failure.txt').write_text(page.locator('body').aria_snapshot(),encoding='utf-8')
            page.screenshot(path=str(ARTIFACTS/'onboarding-submit-failure.png'))
            raise
        assert saved.value.status==200, 'Free activation failed'
        initial_auth=saved.value.request.headers['authorization']
        initial_profile=context.request.get(BASE+'/api/user/me/compa',headers={'Authorization':initial_auth}).json()
        assert initial_profile['zona_horaria']=='America/Santiago'
        assert initial_profile['availability']=={day:['12:00-22:00'] for day in ['lunes','martes','miercoles','jueves','viernes','sabado','domingo']}, 'A weekly availability input was not saved'
        expect(page.get_by_role('button',name='Ir a mi agenda',exact=True)).to_be_visible(timeout=30000)
        page.mouse.move(900,600);page.mouse.wheel(0,100000);page.wait_for_timeout(250)
        page.screenshot(path=str(ARTIFACTS/'onboarding-published.png'))
        page.get_by_role('button',name='Ir a mi agenda',exact=True).click()
        expect(page.get_by_role('tab',name='Solicitudes recibidas',exact=True)).to_be_visible(timeout=30000)
        page.get_by_role('tab',name='Solicitudes recibidas',exact=True).click()
        expect(page.get_by_role('group',name=re.compile('3 de 3 cupos gratuitos disponibles'))).to_be_visible(timeout=30000)
        page.get_by_role('button',name='Back',exact=True).click()
        page.mouse.move(900,600);page.mouse.wheel(0,-100000);page.wait_for_timeout(200)
        fill('Habilidades','cine')
        with page.expect_response(lambda r:r.url.endswith('/api/user/me/compa') and r.request.method=='PUT') as edited:
            find('button','Guardar cambios').click()
        assert edited.value.status==200
        expect(page.get_by_role('button',name='Ir a mi agenda',exact=True)).to_be_enabled(timeout=30000)
        auth=edited.value.request.headers['authorization']
        response=context.request.get(BASE+'/api/user/me/compa',headers={'Authorization':auth})
        assert response.status==200 and response.json()['profile']['habilidades']==['cine']
        assert not errors, '; '.join(errors)
        browser.close()
    print('PASS: desktop/mobile free compa form, real role refresh, provider agenda and persistent profile edits')
finally:
    fixture('cleanup',username)
