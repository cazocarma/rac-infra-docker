"""Real review UI, encrypted backup and restoration; all identities/photos disposable."""
from pathlib import Path
import json
import os
import re
import subprocess
import sys

from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1]
BASE=os.environ.get("RAC_BROWSER_URL","http://localhost").rstrip("/")
ARTIFACTS=Path(os.environ.get("RAC_BROWSER_ARTIFACTS",".local/review-ui"));ARTIFACTS.mkdir(parents=True,exist_ok=True)
COMPOSE=["docker","compose","--env-file","envs/.env.dev","-p","rac-dev","-f","compose.yaml","-f","docker-compose.dev.yaml","-f","compose.observability.yaml","-f","compose.tests.yaml"]
if (ROOT/"envs/.env.photos-s3").exists():COMPOSE += ["-f","compose.photos-s3.yaml"]
if (ROOT/"envs/.env.backups").exists():COMPOSE += ["--env-file","envs/.env.backups","-f","compose.backups.yaml"]

def fixture(*args):
    result=subprocess.run(COMPOSE+["run","--rm","--no-deps","test-integration","python","test_reviews_fixture.py",*args],cwd=ROOT,capture_output=True,text=True,timeout=90)
    if result.returncode:raise RuntimeError(result.stdout[-1000:]+result.stderr[-1000:])
    return result.stdout.strip()

info=json.loads(fixture())
try:
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        context=browser.new_context(viewport={"width":390,"height":844},locale="es-CL",timezone_id="America/Santiago")
        page=context.new_page()
        def semantics():
            locator=page.locator('flt-semantics-placeholder')
            if locator.count():locator.evaluate('element => element.click()')
        page.goto(BASE,wait_until="networkidle");semantics()
        page.get_by_role('button',name='Ingresar o crear cuenta').click()
        page.locator('#username').fill(info['username']);page.locator('#password').fill('123456');page.locator('#kc-login').click()
        page.wait_for_url(BASE+'/#/home',timeout=60000);semantics()
        page.goto(BASE+'/#/match',wait_until="networkidle");semantics()
        button=page.get_by_role('button',name='Dejar una reseña')
        expect(button).to_be_visible(timeout=60000);button.click()
        page.wait_for_timeout(300)
        (ARTIFACTS/'review-dialog-aria.txt').write_text(page.locator('body').aria_snapshot(),encoding='utf-8')
        page.get_by_role('checkbox',name=re.compile(r'^5 de 5 estrellas')).click()
        page.get_by_role('textbox',name='Comentario (opcional)').fill('Una experiencia excelente y muy buena compañía.')
        with page.expect_response(lambda response:'/api/user/bookings/' in response.url and response.request.method=='POST') as sent:
            page.get_by_role('button',name='Publicar reseña',exact=True).click()
        assert sent.value.status in (200,201), 'Review submission failed: '+sent.value.text()
        page.wait_for_timeout(600)
        (ARTIFACTS/'review-saved-aria.txt').write_text(page.locator('body').aria_snapshot(),encoding='utf-8')
        page.screenshot(path=str(ARTIFACTS/'review-saved-debug.png'))
        expect(page.get_by_role('group',name=re.compile('Reserva '+re.escape(info['booking'][:8])+'.*Reseña verificada'))).to_be_visible(timeout=30000)
        page.reload(wait_until="networkidle");semantics()
        expect(page.get_by_role('group',name=re.compile('Reserva '+re.escape(info['booking'][:8])+'.*Reseña verificada'))).to_be_visible(timeout=30000)
        expect(page.get_by_role('button',name='Dejar una reseña')).to_have_count(0)
        page.screenshot(path=str(ARTIFACTS/'review-booking-mobile.png'),full_page=True)
        # Public detail through actual application route, then both viewport sizes.
        page.goto(BASE+'/#/home',wait_until="networkidle");semantics()
        card=page.get_by_role('button',name=re.compile('Ver perfil de '+re.escape(info['provider_name'])))
        for _ in range(60):
            if card.count() and card.first.is_visible():break
            page.mouse.wheel(0,280);page.wait_for_timeout(100)
        card.first.click()
        for _ in range(60):
            if 'Una experiencia excelente y muy buena compañía.' in page.locator('body').aria_snapshot():break
            page.mouse.wheel(0,260);page.wait_for_timeout(100)
        assert 'Una experiencia excelente y muy buena compañía.' in page.locator('body').aria_snapshot()
        page.mouse.wheel(0,480);page.wait_for_timeout(300)
        page.screenshot(path=str(ARTIFACTS/'review-public-mobile.png'),full_page=True)
        page.set_viewport_size({"width":1280,"height":1000});page.screenshot(path=str(ARTIFACTS/'review-public-desktop.png'),full_page=True)
        context.close();browser.close()
    print('PASS review submission, persistence, no second review and public mobile/desktop display')
    if (ROOT/"envs/.env.backups").exists():
        subprocess.run(["make","backup-now"],cwd=ROOT,check=True)
        subprocess.run([sys.executable,"scripts/test_backup_restore.py"],cwd=ROOT,check=True)
        print('PASS encrypted restore includes a real referenced synthetic profile photo and verified review')
finally:
    fixture("cleanup",info["username"])
