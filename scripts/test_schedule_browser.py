"""Real OIDC time-off view and confirmed deletion using a disposable compa."""
from pathlib import Path
import json
import os
import subprocess
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1]
BASE=os.environ.get('RAC_BROWSER_URL','http://localhost').rstrip('/')
ARTIFACTS=Path('.local/schedule-ui');ARTIFACTS.mkdir(parents=True,exist_ok=True)
COMPOSE=['docker','compose','--env-file','envs/.env.dev','-p','rac-dev','-f','compose.yaml','-f','docker-compose.dev.yaml','-f','compose.tests.yaml']
def fixture(*args):
 result=subprocess.run(COMPOSE+['run','--rm','--no-deps','test-integration','python',*args],cwd=ROOT,capture_output=True,text=True,timeout=180)
 if result.returncode:raise RuntimeError(result.stdout[-1600:]+result.stderr[-1600:])
 return result.stdout.strip()
def semantics(page):
 enable=page.locator('flt-semantics-placeholder')
 if enable.count():enable.evaluate('element=>element.click()')
info=json.loads(fixture('test_schedule_fixture.py','prepare'))
try:
 with sync_playwright() as p:
  browser=p.chromium.launch(headless=True);context=browser.new_context(viewport={'width':390,'height':844},locale='es-CL',timezone_id='America/Santiago');page=context.new_page()
  page.goto(BASE,wait_until='networkidle');semantics(page);page.get_by_role('button',name='Ingresar o crear cuenta').click();page.locator('#username').fill(info['username']);page.locator('#password').fill('123456');page.locator('#kc-login').click();page.wait_for_url(BASE+'/#/home',timeout=60000);semantics(page)
  with page.expect_response(lambda r:r.url.endswith('/time-off')) as loaded:
   page.goto(BASE+'/#/time-off',wait_until='networkidle');semantics(page)
  assert loaded.value.status==200
  expect(page.get_by_text('Una pausa en tu agenda',exact=True)).to_be_visible()
  assert any(item['id']==info['block'] for item in loaded.value.json()['items'])
  rendered=page.locator('body').aria_snapshot();(ARTIFACTS/'time-off.txt').write_text(rendered,encoding='utf-8')
  assert info['date']+' → '+info['date'] in rendered,rendered
  page.screenshot(path=str(ARTIFACTS/'time-off-mobile.png'))
  page.set_viewport_size({'width':1366,'height':1000});page.screenshot(path=str(ARTIFACTS/'time-off-desktop.png'))
  page.get_by_role('button',name='Quitar bloqueo',exact=True).click()
  page.get_by_role('button',name='Conservar',exact=True).click()
  page.get_by_role('button',name='Quitar bloqueo',exact=True).click()
  with page.expect_response(lambda r:r.request.method=='DELETE' and r.url.endswith(info['block'])) as removed:
   page.get_by_role('button',name='Quitar bloqueo',exact=True).click()
  assert removed.value.status==200
  expect(page.get_by_text('No tienes bloqueos vigentes.',exact=False)).to_be_visible()
  browser.close()
 fixture('test_schedule_fixture.py','expiry',info['username'])
 print('PASS: private days off, blocked booking, confirmed removal and asynchronous expiry')
finally:
 fixture('test_onboarding.py','cleanup',info['username'])
