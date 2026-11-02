"""Real free onboarding with an isolated, automatically removed DEV identity."""
from flutter_material_labels import FlutterMaterialLabels
from browser_compose import command as browser_compose
from browser_app_labels import app_label
from pathlib import Path
import json
import os
import re
import subprocess
import struct
import zlib
import time
from playwright.sync_api import sync_playwright, expect
MATERIAL = FlutterMaterialLabels('es-CL')

if os.environ.get('RAC_ENV', 'dev') != 'dev':
    raise RuntimeError('Onboarding browser fixtures are DEV-only')
ROOT = Path(__file__).resolve().parent.parent
BASE = os.environ.get('RAC_BROWSER_URL', 'http://localhost').rstrip('/')
ARTIFACTS = Path(os.environ.get('RAC_BROWSER_ARTIFACTS', '.local/ui-review'))
ARTIFACTS.mkdir(parents=True, exist_ok=True)
# Synthetic image fixture; never uses a person's photo or an external download.
def png_fixture(noisy=False):
    def chunk(kind, data):
        return struct.pack('!I',len(data))+kind+data+struct.pack('!I',zlib.crc32(kind+data)&0xffffffff)
    width,height=(768,768) if noisy else (640,320)
    pixels=b''.join(b'\0'+(os.urandom(width*3) if noisy else b''.join(bytes((23+(x//80)%2*60,107+(y//80)%2*40,88)) for x in range(width))) for y in range(height))
    raw=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!2I5B',width,height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(pixels))+chunk(b'IEND',b'')
    path=(ARTIFACTS/('profile-upload-noise.png' if noisy else 'profile-upload-fixture.png')).resolve()
    path.write_bytes(raw)
    return path
COMPOSE = browser_compose(ROOT)

def fixture(*args):
    result = subprocess.run(COMPOSE+['run','--rm','--no-deps','test-integration','python','test_onboarding.py',*args],
        cwd=ROOT, text=True, capture_output=True, timeout=60)
    if result.returncode:
        raise RuntimeError('Onboarding fixture failed: '+result.stderr[-1000:])
    return result.stdout.strip()

username = json.loads(fixture('prepare'))['username']
try:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width':1280,'height':900},locale=MATERIAL.locale,timezone_id='America/Santiago')
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
        def activity(key):
            # Catalog chips: Flutter exposes FilterChip as checkbox or button.
            name=app_label(ROOT, key, MATERIAL.locale)
            page.mouse.move(page.viewport_size['width']*.6,page.viewport_size['height']*.7)
            for _ in range(40):
                for role in ('checkbox','button'):
                    # The accessible name is "<description>. <name>".
                    locator=page.get_by_role(role,name=re.compile(re.escape(name)+'$'))
                    if locator.count() and locator.first.is_visible(): return locator.first
                page.mouse.wheel(0,220)
                page.wait_for_timeout(100)
            (ARTIFACTS/'onboarding-failure.txt').write_text(page.locator('body').aria_snapshot(),encoding='utf-8')
            raise AssertionError('Missing catalog activity: '+key)
        page.goto(BASE,wait_until='networkidle')
        semantics()
        page.get_by_role('button',name='Ingresar o crear cuenta').click()
        page.locator('#username').fill(username)
        page.locator('#password').fill('123456')
        page.locator('#kc-login').click()
        page.wait_for_url(BASE+'/#/home',timeout=60000)
        semantics()
        page.goto(BASE+'/#/profile',wait_until='networkidle')
        semantics()
        expect(page.get_by_text('Hagamos tu perfil más tuyo',exact=True)).to_be_visible(timeout=60000)
        fill('Nombre visible','Cris perfil de prueba')
        fill('Biografía pública (opcional)','Me gusta compartir películas, caminatas y buenos momentos.')
        fill('Teléfono (opcional)','+56 9 1234 5678')
        fill('País (opcional)','Chile')
        fill('Ciudad (opcional)','Santiago')
        fill('Tus intereses (opcionales)','Cine, Running')
        failure_route='**/api/user/me'
        page.route(failure_route,lambda route: route.fulfill(status=503,content_type='application/json',body='{"error":"profile_unavailable"}') if route.request.method=='PUT' else route.continue_())
        with page.expect_response(lambda r:r.url.endswith('/api/user/me') and r.request.method=='PUT') as failed_save:
            find('button','Guardar cambios').click()
        assert failed_save.value.status==503
        try:
            expect(page.get_by_role('group',name=re.compile('Se conservan en el formulario'))).to_be_visible(timeout=5000)
        except Exception:
            (ARTIFACTS/'profile-error-aria.txt').write_text(page.locator('body').aria_snapshot(),encoding='utf-8')
            page.screenshot(path=str(ARTIFACTS/'profile-error.png'))
            raise
        page.unroute(failure_route)
        with page.expect_response(lambda r:r.url.endswith('/api/user/me') and r.request.method=='PUT') as personal_saved:
            find('button','Guardar cambios').click()
        assert personal_saved.value.status==200
        expect(page.get_by_text('Tu perfil se guardó correctamente',exact=True)).to_be_visible(timeout=30000)
        auth=personal_saved.value.request.headers['authorization']
        personal=context.request.get(BASE+'/api/user/me',headers={'Authorization':auth}).json()
        assert personal['nombre']=='Cris perfil de prueba' and personal['intereses']==['Cine','Running']
        assert personal['biografia']=='Me gusta compartir películas, caminatas y buenos momentos.'
        # Real owner-role DB: forbidden public edits leave the saved profile and
        # private phone unchanged. Public failures must not echo submitted text.
        personal_payload={key:personal.get(key,'') for key in ['nombre','biografia','telefono','pais','region','ciudad','intereses']}
        for field, value in [('nombre','@compa_test'),('biografia','hola arroba ejemplo punto com'),('intereses',['https://example.com'])]:
            rejected=context.request.put(BASE+'/api/user/me',headers={'Authorization':auth},data={**personal_payload,field:value})
            assert rejected.status==400 and rejected.json()=={'error':'public_contact_not_allowed','field':field}
            unchanged=context.request.get(BASE+'/api/user/me',headers={'Authorization':auth}).json()
            assert all(unchanged[key]==personal[key] for key in personal_payload)
        fill('Biografía pública (opcional)','Escríbeme a hola@example.com')
        with page.expect_response(lambda r:r.url.endswith('/api/user/me') and r.request.method=='PUT') as contact_save:
            find('button','Guardar cambios').click()
        assert contact_save.value.status==400
        # Flutter merges the notice into the surrounding group's accessible
        # name. Require the complete localized notice within that group.
        try:
            expect(page.get_by_role('group',name=re.compile(re.escape(app_label(ROOT,'publicContactNotAllowed','es'))))).to_be_visible(timeout=30000)
        except Exception:
            (ARTIFACTS/'public-contact-error-aria.txt').write_text(page.locator('body').aria_snapshot(),encoding='utf-8')
            page.screenshot(path=str(ARTIFACTS/'public-contact-error.png'))
            raise
        fill('Biografía pública (opcional)',personal['biografia'])
        with page.expect_response(lambda r:r.url.endswith('/api/user/me') and r.request.method=='PUT') as corrected_save:
            find('button','Guardar cambios').click()
        assert corrected_save.value.status==200
        print('PASS: public contacts rejected before persistence, explicit UI correction, private phone preserved',flush=True)
        page.mouse.wheel(0,-100000);page.wait_for_timeout(250)
        find('button','Vista previa pública').click()
        expect(page.get_by_text(personal['biografia'],exact=True)).to_be_visible(timeout=30000)
        assert page.get_by_role('textbox',name='Correo de acceso').count()==0
        page.screenshot(path=str(ARTIFACTS/'public-profile-preview.png'))
        page.get_by_role('button',name=MATERIAL.back,exact=True).click()
        page.mouse.wheel(0,-100000);page.wait_for_timeout(250)
        with page.expect_file_chooser() as chooser:
            find('button','Cambiar foto').click()
        chooser.value.set_files(str(png_fixture()))
        expect(page.get_by_text('Confirma tu foto',exact=True)).to_be_visible(timeout=30000)
        with page.expect_response(lambda r:r.url.endswith('/api/user/me/photo') and r.request.method=='PUT') as uploaded:
            page.get_by_role('button',name='Guardar foto',exact=True).click()
        assert uploaded.value.status==200, 'Photo upload failed'
        photo_key=uploaded.value.json()['foto_version']
        photo_path='/api/user/media/profile/'+photo_key
        assert context.request.get(BASE+photo_path).status==404, 'Base photo leaked before publication'
        own_photo=context.request.get(BASE+'/api/user/me/photo',headers={'Authorization':auth})
        assert own_photo.status==200 and own_photo.headers['content-type'].startswith('image/jpeg')
        normalized=own_photo.body()
        restart=subprocess.run(COMPOSE+['up','-d','--no-build','--no-deps','--force-recreate','backend-user'],cwd=ROOT,capture_output=True,text=True,timeout=60)
        assert restart.returncode==0, 'Could not recreate DEV user service'
        for attempt in range(40):
            restored=context.request.get(BASE+'/api/user/me/photo',headers={'Authorization':auth})
            if restored.status==200: break
            time.sleep(.5)
        assert restored.status==200 and restored.body()==normalized, 'Photo did not survive container recreation'
        page.reload(wait_until='networkidle');semantics()
        expect(page.get_by_text('Hagamos tu perfil más tuyo',exact=True)).to_be_visible(timeout=60000)
        restored_name=find('textbox','Nombre visible')
        restored_name.click()
        expect(restored_name).to_have_value('Cris perfil de prueba')
        page.keyboard.press('Tab')
        page.mouse.wheel(0,-100000);page.wait_for_timeout(250)
        page.screenshot(path=str(ARTIFACTS/'personal-profile-desktop.png'))
        page.set_viewport_size({'width':390,'height':844})
        page.emulate_media(color_scheme='dark')
        page.wait_for_timeout(500)
        page.screenshot(path=str(ARTIFACTS/'personal-profile-mobile.png'))
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Profile overflows mobile width'
        page.set_viewport_size({'width':1280,'height':900})
        page.goto(BASE+'/#/home',wait_until='networkidle');semantics()
        expect(page.get_by_text('Encuentra tu compa',exact=True)).to_be_visible(timeout=60000)
        print('PASS: personal profile real save/reload, retry after outage and mobile layout',flush=True)
        page.get_by_role('button',name='Sé Compa',exact=True).click()
        expect(page.get_by_text('Comparte lo que te gusta hacer',exact=True)).to_be_visible(timeout=30000)
        page.set_viewport_size({'width':320,'height':568})
        page.screenshot(path=str(ARTIFACTS/'mobile-onboarding.png'))
        page.set_viewport_size({'width':1280,'height':900})
        fill('Cuéntanos sobre ti','Compartamos cine y actividades entretenidas juntos.')
        fill('Tarifa por hora (CLP)','12000')
        # Only the closed catalog is offered: no free-text skills (P06).
        assert page.get_by_role('textbox',name=re.compile('Habilidades')).count()==0
        activity('activityCinema').click()
        activity('activityKaraoke').click()
        for day in ['Lunes','Martes','Miércoles','Jueves','Viernes','Sábado','Domingo']:
            fill(day,'12:00-22:00')
        try:
            with page.expect_response(lambda r:r.url.endswith('/api/user/me/compa') and r.request.method=='PUT') as saved:
                find('button',app_label(ROOT, 'compaActivateProfile', MATERIAL.locale)).click()
        except Exception:
            (ARTIFACTS/'onboarding-submit-failure.txt').write_text(page.locator('body').aria_snapshot(),encoding='utf-8')
            page.screenshot(path=str(ARTIFACTS/'onboarding-submit-failure.png'))
            raise
        assert saved.value.status==200, 'Compa profile publication failed'
        initial_auth=saved.value.request.headers['authorization']
        initial_profile=context.request.get(BASE+'/api/user/me/compa',headers={'Authorization':initial_auth}).json()
        assert initial_profile['zona_horaria']=='America/Santiago'
        assert [a['slug'] for a in initial_profile['profile']['actividades']]==['cine','karaoke']
        compa_payload={'descripcion':initial_profile['profile']['descripcion'],'tarifa_hora':12000,
                       'actividades':[{'slug':a['slug']} for a in initial_profile['profile']['actividades']],
                       'availability':initial_profile['availability'],'zona_horaria':initial_profile['zona_horaria']}
        for field, change in [('descripcion',{'descripcion':'Conversemos por WhatsApp antes de reservar'}),
                              ('actividades.nota',{'actividades':[{'slug':'cine','nota':'hola arroba ejemplo punto com'}]})]:
            rejected=context.request.put(BASE+'/api/user/me/compa',headers={'Authorization':initial_auth},data={**compa_payload,**change})
            assert rejected.status==400 and rejected.json()=={'error':'public_contact_not_allowed','field':field}
            unchanged=context.request.get(BASE+'/api/user/me/compa',headers={'Authorization':initial_auth}).json()
            assert unchanged==initial_profile
        print('PASS: compa description and activity notes reject public contacts without altering saved publication',flush=True)
        assert context.request.get(BASE+photo_path).status==200, 'Published compa photo unavailable'
        published=context.request.get(BASE+'/api/user/compas/'+initial_profile['profile']['id']).json()
        assert published['biografia']==personal['biografia'] and published['foto_url']==photo_path
        assert not {'telefono','correo','direccion','pais','region','ciudad'} & set(published)
        assert initial_profile['availability']=={day:['12:00-22:00'] for day in ['lunes','martes','miercoles','jueves','viernes','sabado','domingo']}, 'A weekly availability input was not saved'
        expect(page.get_by_role('button',name='Ir a mi agenda',exact=True)).to_be_visible(timeout=30000)
        page.mouse.move(900,600);page.mouse.wheel(0,100000);page.wait_for_timeout(250)
        page.screenshot(path=str(ARTIFACTS/'onboarding-published.png'))
        page.get_by_role('button',name='Ir a mi agenda',exact=True).click()
        expect(page.get_by_role('tab',name='Solicitudes recibidas',exact=True)).to_be_visible(timeout=30000)
        page.get_by_role('tab',name='Solicitudes recibidas',exact=True).click()
        expect(page.get_by_role('group',name=re.compile('3 de 3 cupos gratuitos disponibles'))).to_be_visible(timeout=30000)
        page.get_by_role('button',name=MATERIAL.back,exact=True).click()
        page.mouse.move(900,600);page.mouse.wheel(0,-100000);page.wait_for_timeout(200)
        activity('activityKaraoke').click()
        with page.expect_response(lambda r:r.url.endswith('/api/user/me/compa') and r.request.method=='PUT') as edited:
            find('button','Guardar cambios').click()
        assert edited.value.status==200
        expect(page.get_by_role('button',name='Ir a mi agenda',exact=True)).to_be_enabled(timeout=30000)
        auth=edited.value.request.headers['authorization']
        response=context.request.get(BASE+'/api/user/me/compa',headers={'Authorization':auth})
        assert response.status==200 and [a['slug'] for a in response.json()['profile']['actividades']]==['cine']
        page.goto(BASE+'/#/home',wait_until='networkidle');semantics()
        find('button','Cris perfil de prueba').click()
        expect(page.get_by_role('button',name='Reservar',exact=True)).to_be_visible(timeout=30000)
        public_aria=page.locator('body').aria_snapshot()
        assert personal['biografia'] in public_aria and 'Foto de Cris perfil de prueba' in public_aria
        assert personal['correo'] not in public_aria and personal['telefono'] not in public_aria
        page.mouse.wheel(0,-100000);page.wait_for_timeout(250)
        page.screenshot(path=str(ARTIFACTS/'published-public-profile-desktop.png'))
        page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(300)
        page.screenshot(path=str(ARTIFACTS/'published-public-profile-mobile.png'))
        proxy_payload=png_fixture(noisy=True).read_bytes()
        assert 1024*1024<len(proxy_payload)<5*1024*1024
        proxy_upload=context.request.put(BASE+'/api/user/me/photo',headers={'Authorization':auth,'Content-Type':'image/png'},data=proxy_payload)
        assert proxy_upload.status==200, 'Valid photo over 1 MiB rejected by proxy'
        assert context.request.get(BASE+photo_path).status==404, 'Replaced photo still public'
        photo_path='/api/user/media/profile/'+proxy_upload.json()['foto_version']
        oversized=context.request.put(BASE+'/api/user/me/photo',headers={'Authorization':auth,'Content-Type':'image/png'},data=b'0'*(5*1024*1024+1))
        assert oversized.status==413, 'Photo size limit bypassed'
        assert context.request.delete(BASE+'/api/user/me/photo',headers={'Authorization':auth}).status==200
        assert context.request.get(BASE+photo_path).status==404, 'Deleted photo still publicly accessible'
        assert not errors, '; '.join(errors)
        browser.close()
    print('PASS: desktop/mobile free compa form, real role refresh, provider agenda and persistent profile edits')
    print('PASS: photo upload, private/public ownership, persistence after recreation, public biography and deletion')
finally:
    fixture('cleanup',username)
