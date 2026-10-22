"""DEV real OIDC aggregate dashboard; no private data or tokens in artifacts."""
from pathlib import Path
import os
from playwright.sync_api import sync_playwright, expect
BASE=os.environ.get('RAC_BROWSER_URL','http://localhost').rstrip('/')
ARTIFACTS=Path('.local/admin-ui');ARTIFACTS.mkdir(parents=True,exist_ok=True)
def semantics(page):
 enable=page.locator('flt-semantics-placeholder')
 if enable.count():enable.evaluate('element=>element.click()')
def login(page,user):
 page.goto(BASE,wait_until='networkidle');semantics(page)
 page.get_by_role('button',name='Ingresar o crear cuenta').click()
 page.locator('#username').fill(user);page.locator('#password').fill('123456');page.locator('#kc-login').click()
 page.wait_for_url(BASE+'/#/home',timeout=60000);semantics(page)
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True)
 admin=browser.new_context(viewport={'width':1366,'height':1000},locale='es-CL',timezone_id='America/Santiago')
 page=admin.new_page();login(page,'admin1')
 with page.expect_response(lambda r:r.url.endswith('/api/admin/overview')) as loaded:
  page.goto(BASE+'/#/admin',wait_until='networkidle');semantics(page)
 response=loaded.value;assert response.status==200
 result=response.json();assert set(result)=={'usuarios','reservas','reportes','consultado_en'}
 assert response.headers.get('cache-control')=='no-store'
 headers={'Authorization':response.request.headers['authorization']}
 for name,url,keys in [('usuarios','/api/user/admin/summary',{'total','compas'}),('reservas','/api/match/admin/summary',{'pendiente','activa','finalizada','cancelada','expirada'}),('reportes','/api/chat/moderation/summary',{'abierto','atendido','desestimado'})]:
  source=admin.request.get(BASE+url,headers=headers);assert source.status==200 and source.json()==result[name]
  assert set(result[name])==keys and all(type(n)==int and n>=0 for n in result[name].values())
  assert admin.request.get(BASE+url).status==401
 expect(page.get_by_text('El pulso de RAC',exact=True)).to_be_visible()
 page.screenshot(path=str(ARTIFACTS/'dashboard-desktop.png'))
 page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(ARTIFACTS/'dashboard-mobile.png'))
 page.mouse.move(180,400);page.mouse.wheel(0,2400)
 expect(page.get_by_role('button',name='Revisar reportes')).to_be_visible()
 page.get_by_role('button',name='Revisar reportes').click()
 expect(page.get_by_text('Moderación de reportes',exact=True)).to_be_visible()
 assert admin.request.get(BASE+'/api/admin/overview').status==401
 client=browser.new_context(locale='es-CL');buyer=client.new_page();login(buyer,'cliente1')
 with buyer.expect_response(lambda r:r.url.endswith('/api/admin/overview')) as denied:
  buyer.goto(BASE+'/#/admin',wait_until='networkidle');semantics(buyer)
 assert denied.value.status==403
 expect(buyer.get_by_text('Acceso reservado a administradores',exact=True)).to_be_visible()
 buyer_headers={'Authorization':denied.value.request.headers['authorization']}
 for url in ['/api/user/admin/summary','/api/match/admin/summary','/api/chat/moderation/summary']:
  assert client.request.get(BASE+url,headers=buyer_headers).status==403
 browser.close()
print('PASS: OIDC admin-only dashboard, owner aggregates, no-store, mobile/web and moderation navigation')
