"""DEV-only acceptance for the branded native Keycloak forms."""
import os
from pathlib import Path
import re
from playwright.sync_api import sync_playwright, expect

if os.environ.get('RAC_ENV', 'dev') != 'dev':
    raise RuntimeError('Identity UI fixtures are DEV-only')
BASE = os.environ.get('RAC_BROWSER_URL', 'http://localhost').rstrip('/')
ARTIFACTS = Path(os.environ.get('RAC_BROWSER_ARTIFACTS', '.local/ui-review'))
ARTIFACTS.mkdir(parents=True, exist_ok=True)
VIEWPORTS = [
    ('light', 1366, 1000), ('dark', 1366, 1000),
    ('light', 390, 844), ('dark', 390, 844),
    ('light', 320, 700), ('light', 811, 900),
]

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    for mode, width, height in VIEWPORTS:
        context = browser.new_context(
            viewport={'width': width, 'height': height}, locale='es-CL',
            timezone_id='America/Santiago', color_scheme=mode,
        )
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(BASE, wait_until='networkidle')
        placeholder = page.locator('flt-semantics-placeholder')
        placeholder.wait_for(state='attached', timeout=60000)
        placeholder.evaluate('element => element.click()')
        login = page.get_by_role('button', name='Ingresar o crear cuenta')
        expect(login).to_be_visible(timeout=60000)
        page.screenshot(path=str(ARTIFACTS / f'app-login-{mode}-{width}.png'))
        login.click()
        expect(page.locator('#username')).to_be_visible(timeout=30000)
        login_url = page.url
        page.screenshot(path=str(ARTIFACTS / f'keycloak-login-{mode}-{width}.png'), full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Login horizontal overflow'

        # A nonexistent identity avoids changing or locking a real/demo account.
        page.locator('#username').fill('rac-ui-negative-test-no-account')
        page.locator('#password').fill('invalid-test-password')
        page.locator('#kc-login').click()
        expect(page.locator('#input-error')).to_be_visible(timeout=15000)
        page.screenshot(path=str(ARTIFACTS / f'keycloak-error-{mode}-{width}.png'), full_page=True)

        # Inspect forms without submitting registration or sending reset emails.
        page.locator('#kc-registration a').click()
        expect(page.locator('#kc-register-form')).to_be_visible(timeout=15000)
        page.screenshot(path=str(ARTIFACTS / f'keycloak-register-{mode}-{width}.png'), full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Registration horizontal overflow'
        page.goto(login_url)
        page.get_by_role('link', name=re.compile('olvidado')).click()
        expect(page.locator('#kc-reset-password-form')).to_be_visible(timeout=15000)
        page.screenshot(path=str(ARTIFACTS / f'keycloak-recovery-{mode}-{width}.png'), full_page=True)
        assert not errors, '; '.join(errors)
        print(f'PASS: branded app/login, invalid credentials, registration and recovery {mode} {width}', flush=True)
        context.close()
    browser.close()
