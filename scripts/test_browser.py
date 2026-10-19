"""RAC UI acceptance: login, booking, provider acceptance, cancellation, mobile."""
from pathlib import Path
import os
import re
import json
from playwright.sync_api import sync_playwright, expect
if os.environ.get('RAC_ENV', 'dev') != 'dev':
    raise RuntimeError('Browser fixtures are allowed only in DEV')
BASE = os.environ.get('RAC_BROWSER_URL', 'http://localhost')
ARTIFACTS = Path(os.environ.get('RAC_BROWSER_ARTIFACTS', '.local/ui-review'))
ARTIFACTS.mkdir(parents=True, exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    errors = []
    def login(username, width=1366, height=1000):
        # Linux can inherit en-US@posix, which is not a valid browser BCP 47 locale.
        context = browser.new_context(viewport={'width': width, 'height': height}, locale='es-CL', timezone_id='America/Santiago')
        page = context.new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(BASE, wait_until='networkidle')
        placeholder = page.locator('flt-semantics-placeholder')
        if placeholder.count(): placeholder.evaluate("element => element.click()")
        button = page.get_by_role('button', name='Ingresar o crear cuenta')
        try:
            expect(button).to_be_visible(timeout=60000)
        except AssertionError as error:
            raise AssertionError('Login did not start. Browser errors: ' + '; '.join(errors)) from error
        button.click()
        page.locator('#username').fill(username)
        page.locator('#password').fill('123456')
        page.locator('#kc-login').click()
        page.wait_for_url(BASE.rstrip('/')+'/#/home', timeout=60000)
        placeholder = page.locator('flt-semantics-placeholder')
        if placeholder.count(): placeholder.evaluate("element => element.click()")
        expect(page.get_by_text('Encuentra tu compa', exact=True)).to_be_visible(timeout=60000)
        return context, page
    def booking_card(page, booking_id, state=None, action=None):
        card = page.get_by_role('group', name=re.compile('Reserva '+booking_id[:8]))
        page.mouse.move(page.viewport_size['width'] / 2, page.viewport_size['height'] * .75)
        page.mouse.wheel(0, -100000)
        page.wait_for_timeout(250)
        for _ in range(100):
            if card.count():
                ready_state = state is None or card.get_by_role('checkbox', name=state, exact=True).count()
                ready_action = action is None or card.get_by_role('button', name=action, exact=True).count()
                if ready_state and ready_action:
                    return card
                if not ready_action:
                    page.mouse.wheel(0, 150)
                elif not ready_state:
                    page.mouse.wheel(0, -150)
                page.wait_for_timeout(100)
                continue
            page.mouse.wheel(0, 250)
            page.wait_for_timeout(100)
        (ARTIFACTS/'agenda-failure.txt').write_text(page.locator('body').aria_snapshot(), encoding='utf-8')
        page.screenshot(path=str(ARTIFACTS/'agenda-failure.png'))
        raise AssertionError('Created booking not found in agenda')
    customer, page = login('cliente1')
    assert len(customer.pages) == 1, 'Login must stay in the same tab'
    page.reload(wait_until='networkidle')
    placeholder = page.locator('flt-semantics-placeholder')
    if placeholder.count(): placeholder.evaluate("element => element.click()")
    expect(page.get_by_text('Encuentra tu compa', exact=True)).to_be_visible(timeout=60000)
    plaintext_jwt = page.evaluate("() => [localStorage, sessionStorage].some(s => Object.values(s).some(v => /eyJ[A-Za-z0-9_-]+\\.eyJ[A-Za-z0-9_-]+\\./.test(v)))")
    assert not plaintext_jwt, 'Plaintext JWT found in browser storage'
    # Reopening an already consumed/expired callback must never strand the user.
    page.goto(BASE.rstrip('/')+'/redirect.html?state=already-consumed-test&code=invalid-test-code', wait_until='networkidle')
    page.wait_for_url(BASE.rstrip('/')+'/#/home', timeout=60000)
    placeholder = page.locator('flt-semantics-placeholder')
    if placeholder.count(): placeholder.evaluate("element => element.click()")
    expect(page.get_by_text('Encuentra tu compa', exact=True)).to_be_visible(timeout=60000)
    page.screenshot(path=str(ARTIFACTS/'desktop-home.png'))
    (ARTIFACTS/'home-aria.txt').write_text(page.locator('body').aria_snapshot(), encoding='utf-8')
    page.get_by_role('button', name=re.compile(r'compa2')).click()
    page.get_by_role('button', name='Reservar', exact=True).click()
    (ARTIFACTS/'booking-aria.txt').write_text(page.locator('body').aria_snapshot(), encoding='utf-8')
    page.screenshot(path=str(ARTIFACTS/'booking-initial.png'))
    expect(page.get_by_role('group', name=re.compile('2. Hora de inicio'))).to_be_visible(timeout=30000)
    # Choose a future slot provided by the availability API, never the current time.
    slots = page.get_by_role('checkbox', name=re.compile(r'^\d{2}:\d{2} '))
    if slots.count() == 0:
        slots = page.get_by_role('radio').filter(has_text=re.compile(r'^\d{2}:\d{2} '))
    if slots.count() == 0:
        slots = page.get_by_text(re.compile(r'^\d{2}:\d{2} '))
    expect(slots.first).to_be_visible(timeout=30000)
    slots.nth(20).click()
    page.screenshot(path=str(ARTIFACTS/'desktop-booking.png'))
    with page.expect_response(lambda r: r.url.endswith('/api/match/session') and r.request.method == 'POST') as response_info:
        page.get_by_role('button', name='Solicitar reserva', exact=True).click()
    response = response_info.value
    assert response.status == 201, response.text()
    booking_id = response.json()['id']
    (ARTIFACTS/'last-booking-id.txt').write_text(booking_id)
    print('Created test booking: '+booking_id, flush=True)
    try:
        expect(page.get_by_text('Mis reservas', exact=True)).to_be_visible(timeout=30000)
        expect(booking_card(page, booking_id)).to_be_visible(timeout=30000)
        provider, provider_page = login('compa2')
        provider_page.get_by_text('Mis reservas', exact=True).click()
        (ARTIFACTS/'provider-aria.txt').write_text(provider_page.locator('body').aria_snapshot(), encoding='utf-8')
        provider_page.screenshot(path=str(ARTIFACTS/'provider-initial.png'))
        provider_page.get_by_role('tab', name=re.compile('Solicitudes recibidas')).click()
        # The fresh test booking is the latest request; target the exact card by its visible identifier.
        card = booking_card(provider_page, booking_id, action='Aceptar')
        # Exercise the paywall UI without altering fixture subscriptions or charging anything.
        cap_route = '**/api/match/session/'+booking_id+'/state'
        provider.route(cap_route, lambda route: route.fulfill(status=402, content_type='application/json',
            body=json.dumps({'error':'subscription_required','cupo':{'usados':3,'disponibles':0,'semana_inicio':'2026-10-12'}})))
        card.get_by_role('button', name='Aceptar', exact=True).click()
        expect(provider_page.get_by_role('button', name='Ver planes', exact=True)).to_be_visible()
        assert 'Alcanzaste tus 3 reservas gratis' in provider_page.locator('body').aria_snapshot()
        provider_page.get_by_role('button', name='Ver planes', exact=True).click()
        expect(provider_page.get_by_role('heading', name='Planes y suscripción', exact=True)).to_be_visible()
        expect(provider_page.get_by_role('group', name=re.compile(r'cupos gratuitos disponibles'))).to_be_visible()
        provider_page.screenshot(path=str(ARTIFACTS/'plans-allowance.png'))
        provider.unroute(cap_route)
        provider_page.get_by_role('button', name='Back', exact=True).click()
        provider_page.mouse.move(900,750)
        provider_page.mouse.wheel(0,-20000)
        provider_page.wait_for_timeout(250)
        card = booking_card(provider_page, booking_id, action='Aceptar')
        card.get_by_role('button', name='Aceptar', exact=True).click()
        card = booking_card(provider_page, booking_id, 'Confirmada')
        expect(card.get_by_role('checkbox', name='Confirmada', exact=True)).to_be_visible(timeout=30000)
        provider_page.screenshot(path=str(ARTIFACTS/'provider-agenda.png'))
        page.get_by_role('button', name='Actualizar reservas').click()
        card = booking_card(page, booking_id, 'Confirmada', action='Cancelar')
        expect(card.get_by_role('checkbox', name='Confirmada', exact=True)).to_be_visible(timeout=30000)
        card.get_by_role('button', name='Cancelar', exact=True).click()
        page.get_by_role('button', name='Cancelar reserva', exact=True).click()
        card = booking_card(page, booking_id, 'Cancelada')
        expect(card.get_by_role('checkbox', name='Cancelada', exact=True)).to_be_visible(timeout=30000)
        page.get_by_role('button', name='Back', exact=True).click()
        page.get_by_text('Notificaciones', exact=True).click()
        expect(page.get_by_text(re.compile('Novedades de tus reservas'))).to_be_visible(timeout=30000)
        expect(page.get_by_role('group', name=re.compile('Reserva '+booking_id[:8])).first).to_be_visible(timeout=30000)
        before_read = page.get_by_role('button', name='Marcar como leída', exact=True).count()
        with page.expect_response(lambda r: '/api/user/notifications/' in r.url and r.url.endswith('/read') and r.request.method == 'PUT') as marked:
            page.get_by_role('button', name='Marcar como leída', exact=True).first.click()
        assert marked.value.status == 200
        expect(page.get_by_role('button', name='Marcar como leída', exact=True)).to_have_count(before_read-1)
        page.set_viewport_size({'width':320,'height':568})
        page.screenshot(path=str(ARTIFACTS/'mobile-notifications.png'))
        page.set_viewport_size({'width':1366,'height':1000})
        page.get_by_role('button', name='Back', exact=True).click()
        page.get_by_text('Mis reservas', exact=True).click()
        mobile, mobile_page = login('cliente2', 390, 844)
        mobile_page.screenshot(path=str(ARTIFACTS/'mobile-home.png'))
        mobile_page.set_viewport_size({'width': 320, 'height': 568})
        mobile_page.screenshot(path=str(ARTIFACTS/'mobile-small.png'))
        mobile_page.set_viewport_size({'width': 390, 'height': 844})
        mobile_page.get_by_role('button', name=re.compile(r'compa2')).click()
        mobile_page.get_by_role('button', name='Reservar', exact=True).click()
        expect(mobile_page.get_by_role('group', name=re.compile('2. Hora de inicio'))).to_be_visible(timeout=30000)
        mobile_page.screenshot(path=str(ARTIFACTS/'mobile-booking.png'))
        mobile_page.get_by_role('button', name='Back', exact=True).click()
        mobile_page.get_by_role('button', name='Back', exact=True).click()
        mobile_page.get_by_role('button', name='Open navigation menu').click()
        mobile_page.get_by_role('button', name='Mensajes', exact=True).click()
        expect(mobile_page.get_by_role('heading', name='Mensajes', exact=True)).to_be_visible()
        assert 'En construcción' in mobile_page.locator('body').aria_snapshot()
        page.get_by_role('button', name='Back', exact=True).click()
        with page.expect_response(lambda r: r.url.startswith(BASE.rstrip('/')+'/redirect.html') and r.request.method == 'GET', timeout=60000):
            page.get_by_text('Salir', exact=True).click()
        page.wait_for_load_state('networkidle')
        page.wait_for_url(BASE.rstrip('/')+'/#/login', timeout=60000)
        placeholder = page.locator('flt-semantics-placeholder')
        placeholder.wait_for(state='attached', timeout=30000)
        placeholder.evaluate("element => element.click()")
        expect(page.get_by_role('button', name='Ingresar o crear cuenta')).to_be_visible(timeout=60000)
        old_tokens = page.evaluate("() => Object.keys(localStorage).filter(k => /access_token|refresh_token|internal_token/.test(k))")
        assert not old_tokens, 'Legacy plaintext tokens persisted'
        plaintext_jwt = page.evaluate("() => [localStorage, sessionStorage].some(s => Object.values(s).some(v => /eyJ[A-Za-z0-9_-]+\\.eyJ[A-Za-z0-9_-]+\\./.test(v)))")
        assert not plaintext_jwt, 'Plaintext JWT found in browser storage'
        assert not errors, '; '.join(errors)
    finally:
        # Only cancel the exact booking created by this run, even if a UI assertion fails.
        cleanup = customer.request.put(BASE+'/api/match/session/'+booking_id+'/state',
            headers={'Authorization': response.request.headers['authorization']},
            data={'estado': 'cancelada'})
        assert cleanup.status == 200, "Unable to cancel this run's test booking"
    browser.close()
print('PASS: same-tab desktop/mobile login, reload persistence, real booking, provider acceptance, cancellation, construction and logout')
