"""Synthetic data and real HTTP assertions for the isolated standing lab only."""
import binascii
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import json
import os
from pathlib import Path
import re
import struct
import sys
import time
import urllib.error
import urllib.request
import uuid
import zlib

import psycopg
from psycopg import sql as sql_builder
from oidc_test_support import login
from standing_measurements import measure_revocation, measure_hot_acquisition

if (os.environ.get('RAC_ENV') != 'dev' or os.environ.get('PGHOST') != 'postgres'
        or os.environ.get('PGDATABASE') != 'rac_standing_e2e'
        or not re.fullmatch(r'rac-standing-e2e-[0-9a-f]{12}', os.environ.get('RAC_DISPOSABLE_PROJECT', ''))):
    raise RuntimeError('Isolated standing lab required')

STATE = Path('/fixture/state.json')
UTC = dt.timezone.utc
DAYS = ['lunes', 'martes', 'miercoles', 'jueves', 'viernes', 'sabado', 'domingo']
AVAILABILITY = {day: ['00:00-23:59'] for day in DAYS}
PROFILE = {'nombre': 'Compa sintético', 'intereses': ['Cine']}
COMPA = {'descripcion': 'Actividad de prueba dentro del laboratorio aislado.',
         'tarifa_hora': 12000, 'zona_horaria': 'UTC', 'habilidades': ['cine'],
         'availability': AVAILABILITY}
LEGACY = {'nombre': 'Compa sintético', 'correo': 'compa1@demo.com',
          'fecha_nacimiento': '1990-01-01', 'telefono': '+56912345678',
          'pais': 'Chile', 'region': 'Fixture', 'ciudad': 'Fixture'}
INSTANCE = 1


def api(method, path, token=None, data=None, expected=200, content_type='application/json',
        instance=None, result_meta=False):
    started_ns = time.monotonic_ns()
    service = path.split('/')[2]
    headers = {'Content-Type': content_type}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    body = data if isinstance(data, bytes) else None if data is None else json.dumps(data).encode()
    host = 'backend-' + service
    if service in ('user', 'match', 'chat'):
        host = os.environ['RAC_DISPOSABLE_PROJECT'] + '-backend-' + service + '-' + str(instance or INSTANCE)
    request = urllib.request.Request('http://' + host + ':8080' + path,
                                     method=method, headers=headers, data=body)
    try:
        response = urllib.request.urlopen(request, timeout=8)
    except urllib.error.HTTPError as error:
        response = error
    raw = response.read()
    finished_ns = time.monotonic_ns()
    allowed_statuses = (expected,) if isinstance(expected, int) else expected
    if response.code not in allowed_statuses:
        # Do not echo tokens, payloads, profile fields or private case metadata.
        code = ''
        try:
            code = json.loads(raw).get('error', '')
        except (ValueError, AttributeError):
            pass
        raise AssertionError(f'{method} {path}: status {response.code}, expected {expected}; code={code}')
    if result_meta:
        return {'status': response.code, 'started_ns': started_ns, 'finished_ns': finished_ns}
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def png():
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', binascii.crc32(kind + data))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 64, 64, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress((b'\0' + b'\x70\x90\xa0' * 64) * 64)) + chunk(b'IEND', b''))


def sql(statement, params=(), fetch=False):
    with psycopg.connect() as db:
        if db.execute('SELECT current_database()').fetchone()[0] != 'rac_standing_e2e':
            raise RuntimeError('Wrong fixture database')
        cursor = db.execute(statement, params)
        return cursor.fetchall() if fetch else None


def change(subject, status, timed=False):
    # Only this disposable owner has the audit principal. Runtime API roles
    # keep their existing denial of the standing mutation entry point.
    with psycopg.connect() as db:
        version = db.execute('SELECT version FROM standing.account WHERE subject_id=%s', (subject,)).fetchone()[0]
        event = db.execute('SELECT standing.change_account(%s,%s,%s,%s,%s::jsonb,%s)',
                           (uuid.uuid4(), subject, version, status, '[]', state['policy'])).fetchone()[0]
        commit_started_ns = time.monotonic_ns()
    commit_finished_ns = time.monotonic_ns()
    return (commit_started_ns, commit_finished_ns) if timed else event


def stamp(days):
    return (dt.datetime.now(UTC) + dt.timedelta(days=days)).replace(hour=12, minute=0, second=0, microsecond=0)


def booking(days, accepted=False):
    start = stamp(days)
    item = api('POST', '/api/match/session', state['buyer_token'],
               {'compa_id': state['compa'], 'fecha_inicio': start.isoformat(),
                'fecha_fin': (start + dt.timedelta(hours=1)).isoformat()}, expected=201)
    if accepted:
        api('PUT', f"/api/match/session/{item['id']}/state", state['compa_token'], {'estado': 'activa'})
    return item['id']


def message(booking_id, expected=201):
    return api('POST', f'/api/chat/bookings/{booking_id}/messages', state['compa_token'],
               {'envio_id': str(uuid.uuid4()), 'contenido': 'Mensaje sintético de seguridad.'}, expected=expected)


def wait(check, description, seconds=45):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.2)
    raise AssertionError('Timeout: ' + description)


def save():
    with os.fdopen(os.open(STATE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w', encoding='utf-8') as output:
        json.dump(state, output)


def commit_races():
    """Pause actual SQL writes after authorization, without application hooks."""
    sql("""CREATE FUNCTION public.rac_fixture_pause() RETURNS trigger LANGUAGE plpgsql
 SET search_path=pg_catalog AS $$ BEGIN
 IF to_jsonb(NEW)->>TG_ARGV[0]=TG_ARGV[1] THEN
   PERFORM pg_advisory_xact_lock(1988833027);
 END IF; RETURN NEW; END; $$""")
    availability_path = f"/api/match/availability/{state['compa']}"
    message_path = f"/api/chat/bookings/{state['active']}/messages"
    cases = [
        ('usuario', 'UPDATE', 'id', 'rac_user', 'PUT', '/api/user/me',
         {**PROFILE, 'nombre': 'Este cambio debe revertirse'},
         'SELECT nombre FROM usuario WHERE id=%s', (state['compa'],)),
        ('compa_availability', 'UPDATE', 'compa_id', 'rac_match', 'POST', availability_path,
         {'availability': {**AVAILABILITY, 'lunes': ['00:00-22:00']}},
         'SELECT disponibilidad_json FROM compa_availability WHERE compa_id=%s', (state['compa'],)),
        ('mensaje', 'INSERT', 'remitente_id', 'rac_chat', 'POST', message_path,
         {'envio_id': str(uuid.uuid4()), 'contenido': 'No debe confirmarse'},
         '''SELECT (SELECT count(*) FROM mensaje WHERE sesion_id=%s),
          (SELECT count(*) FROM chat_outbox WHERE sesion_id=%s),
          (SELECT version FROM chat_cursor WHERE sesion_id=%s)''', (state['active'],) * 3),
    ]
    try:
        for instance in (1, 2):
            global INSTANCE
            INSTANCE = instance
            for table, operation, column, role, method, path, data, query, params in cases:
                before = sql(query, params, True)
                sql(sql_builder.SQL('CREATE TRIGGER rac_fixture_pause BEFORE {} ON {} FOR EACH ROW '
                                    'EXECUTE FUNCTION public.rac_fixture_pause({},{})').format(
                    sql_builder.SQL(operation), sql_builder.Identifier(table),
                    sql_builder.Literal(column), sql_builder.Literal(state['compa'])))
                with psycopg.connect(autocommit=True) as lock, ThreadPoolExecutor(max_workers=1) as pool:
                    lock.execute('SELECT pg_advisory_lock(1988833027)')
                    request = pool.submit(api, method, path, state['compa_token'], data, 403)
                    try:
                        wait(lambda: sql('''SELECT EXISTS(SELECT 1 FROM pg_locks l
                         JOIN pg_stat_activity a ON a.pid=l.pid WHERE a.datname=current_database()
                         AND a.usename=%s AND l.locktype='advisory' AND NOT l.granted)''', (role,), True)[0][0],
                             'commercial SQL reached race barrier', seconds=1.5)
                        change(state['compa'], 'suspended')
                    finally:
                        lock.execute('SELECT pg_advisory_unlock(1988833027)')
                    request.result(timeout=8)
                try:
                    assert sql(query, params, True) == before, 'Revoked write or outbox survived rollback'
                finally:
                    sql(sql_builder.SQL('DROP TRIGGER rac_fixture_pause ON {}').format(sql_builder.Identifier(table)))
                    change(state['compa'], 'active')
    finally:
        sql('DROP FUNCTION public.rac_fixture_pause() CASCADE')
    print('PASS: real pre-commit sanctions roll back user, match and chat/outbox writes on two instances each')


phase = sys.argv[1]
state = json.loads(STATE.read_text(encoding='utf-8')) if STATE.exists() else {}
if phase == 'seed':
    if state:
        raise RuntimeError('Fixture already initialized')
    state = {'policy': str(uuid.uuid4())}
    # All user tokens are acquired before any sanction and reused across phases.
    for prefix, username in [('buyer', 'cliente1'), ('compa', 'compa1'), ('stranger', 'cliente2')]:
        token = login(username)
        state[prefix + '_token'] = token
        state[prefix] = api('GET', '/api/user/me', token)['id']
    state['profile'] = sql('SELECT id::text FROM compa_perfil WHERE usuario_id=%s', (state['compa'],), True)[0][0]
    chain = uuid.uuid4()
    sql('INSERT INTO audit.chain_heads(chain_id) VALUES(%s)', (chain,))
    sql('INSERT INTO audit.writer_principals VALUES(%s,%s,%s)', ('postgres', uuid.uuid4(), chain))
    api('PUT', '/api/user/me', state['compa_token'], PROFILE)
    api('POST', '/api/user/profile', state['compa_token'], LEGACY)
    api('PUT', '/api/user/me/compa', state['compa_token'], COMPA)
    api('POST', '/api/user/compas', state['compa_token'], {'descripcion': COMPA['descripcion'], 'tarifa_hora': 12000})
    api('POST', f"/api/user/compas/{state['profile']}/skills", state['compa_token'], {'skills': ['cine']})
    api('PUT', '/api/user/me/photo', state['compa_token'], png(), content_type='image/png')
    api('POST', f"/api/match/availability/{state['compa']}", state['compa_token'], {'availability': AVAILABILITY})
    off = stamp(120).date().isoformat()
    state['time_off'] = api('POST', f"/api/match/availability/{state['compa']}/time-off", state['compa_token'], {'desde': off, 'hasta': off}, expected=201)['id']
    state['active'], state['pending'] = booking(30, True), booking(40)
    api('POST', f"/api/match/session/{state['active']}/extend", state['buyer_token'], {'minutos': 15})
    message(state['active'])
    state['started'] = str(uuid.uuid4())
    sql("INSERT INTO sesion(id,cliente_id,compa_id,fecha_inicio,fecha_fin,estado) VALUES(%s,%s,%s,now()-interval '30 minutes',now()+interval '30 minutes','activa')",
        (state['started'], state['buyer'], state['compa']))
    state['review'] = str(uuid.uuid4())
    sql("INSERT INTO sesion(id,cliente_id,compa_id,fecha_inicio,fecha_fin,estado) VALUES(%s,%s,%s,now()-interval '2 days',now()-interval '1 day','finalizada')",
        (state['review'], state['buyer'], state['compa']))
    api('POST', f"/api/user/bookings/{state['review']}/review", state['buyer_token'], {'puntuacion': 5, 'comentario': 'Actividad de prueba.'}, expected=201)
    save()
    print('PASS: real OIDC/PKCE tokens, scoped services and positive commercial writer controls')
elif phase == 'writers':
    event = change(state['compa'], 'suspended')
    for INSTANCE in (1, 2):
        token = state['compa_token']
        api('PUT', '/api/user/me', token, PROFILE, expected=403)
        api('POST', '/api/user/profile', token, LEGACY, expected=403)
        api('PUT', '/api/user/me/compa', token, COMPA, expected=403)
        api('POST', '/api/user/compas', token, {'descripcion': COMPA['descripcion'], 'tarifa_hora': 12000}, expected=403)
        api('POST', f"/api/user/compas/{state['profile']}/skills", token, {'skills': ['cine']}, expected=403)
        api('PUT', '/api/user/me/photo', token, png(), expected=403, content_type='image/png')
        api('POST', f"/api/match/availability/{state['compa']}", token, {'availability': AVAILABILITY}, expected=403)
        off = stamp(125).date().isoformat()
        api('POST', f"/api/match/availability/{state['compa']}/time-off", token, {'desde': off, 'hasta': off}, expected=403)
        api('DELETE', f"/api/match/availability/{state['compa']}/time-off/{state['time_off']}", token, expected=403)
        api('PUT', f"/api/match/session/{state['pending']}/state", token, {'estado': 'activa'}, expected=403)
        api('POST', f"/api/match/session/{state['active']}/extend", state['buyer_token'], {'minutos': 15}, expected=403)
        message(state['active'], 403)
        api('POST', f"/api/user/bookings/{state['review']}/review", state['buyer_token'], {'puntuacion': 5, 'comentario': 'Actividad de prueba.'}, expected=403)
        view = api('GET', '/api/user/me/standing', token)
        assert view['status'] == 'suspended' and view['capabilities']['access_safety'] and not view['capabilities']['publish_listing']
        api('GET', '/api/user/me', token)
        api('GET', f"/api/chat/bookings/{state['active']}/messages", token)
        api('GET', f"/api/chat/bookings/{state['active']}/safety", token)
        api('POST', f"/api/chat/bookings/{state['active']}/reports", token,
            {'motivo': 'otro', 'detalle': 'Reporte sintético durante sanción.'}, expected=201 if INSTANCE == 1 else 200)
        api('POST', f"/api/chat/bookings/{state['active']}/block", token, {'bloqueado': True})
        api('POST', f"/api/chat/bookings/{state['active']}/block", token, {'bloqueado': False})
        api('GET', f"/api/chat/bookings/{state['active']}/messages", state['stranger_token'], expected=404)
        api('GET', '/api/alert/notifications', token)
        api('PUT', '/api/alert/notifications/read-all', token)
        api('DELETE', '/api/user/me/photo', token)
        api('GET', f"/api/user/compas/{state['profile']}", expected=404)
    change(state['compa'], 'active')
    change(state['buyer'], 'banned')
    future = stamp(60)
    for INSTANCE in (1, 2):
        api('POST', '/api/match/session', state['buyer_token'], {'compa_id': state['compa'],
            'fecha_inicio': future.isoformat(), 'fecha_fin': (future+dt.timedelta(hours=1)).isoformat()}, expected=403)
        api('POST', f"/api/user/bookings/{state['review']}/review", state['buyer_token'], {'puntuacion': 5, 'comentario': 'Actividad de prueba.'}, expected=403)
        api('POST', f"/api/chat/bookings/{state['active']}/reports", state['buyer_token'],
            {'motivo': 'otro', 'detalle': 'Reporte sintético con cuenta baneada.'}, expected=201 if INSTANCE == 1 else 200)
    api('PUT', f"/api/match/session/{state['pending']}/state", state['buyer_token'], {'estado': 'cancelada'})
    change(state['buyer'], 'active')
    print('PASS: old real JWT denied on profile/listing/skills/photo/review/agenda/time-off/create/accept/extend/send; protective reads retained')
elif phase == 'races':
    commit_races()
elif phase == 'measure':
    def measured_call(operation, instance):
        method, path, data = {
            'user.profile': ('PUT', '/api/user/me', PROFILE),
            'match.availability': ('POST', f"/api/match/availability/{state['compa']}", {'availability': AVAILABILITY}),
            'chat.send': ('POST', f"/api/chat/bookings/{state['active']}/messages",
                          {'envio_id': str(uuid.uuid4()), 'contenido': 'Carga sintética de revocación.'}),
        }[operation]
        return api(method, path, state['compa_token'], data, expected=(200, 201, 403),
                   instance=instance, result_meta=True)
    result = measure_revocation(measured_call, lambda status: change(state['compa'], status, timed=True))
    def scrape(operation, instance):
        service = operation.split('.')[0]
        host = os.environ['RAC_DISPOSABLE_PROJECT'] + '-backend-' + service + '-' + str(instance)
        request = urllib.request.Request('http://' + host + ':8080/metrics', headers={'Accept-Encoding': 'gzip'})
        with urllib.request.urlopen(request, timeout=5) as response:
            if response.headers.get('Content-Encoding'):
                raise AssertionError('Appended SDK metrics require a coherent uncompressed response')
            return response.read().decode('utf-8')
    result['hot_acquisition'] = measure_hot_acquisition(measured_call, scrape)
    print('MEASUREMENT_JSON:' + json.dumps(result), flush=True)
    if not result['hot_acquisition']['gate_passed']:
        raise AssertionError('Hot acquisition p99 exceeds 2ms; report must be retained')
    print('PASS: 100 audited revocation trials across six concurrent old-JWT writer probes', flush=True)
elif phase == 'prepare-outages':
    # Historical sanctions must repair the old bookings before creating new ones.
    wait(lambda: sql("SELECT count(*),count(*) FILTER(WHERE estado='cancelada') FROM sesion WHERE id IN(%s,%s)",
                     (state['active'], state['pending']), True) == [(2, 2)], 'historical sanction reconciliation')
    wait(lambda: bool(sql("SELECT 1 FROM match_standing_effect WHERE sesion_id=%s AND effect='safety_review'", (state['started'],), True)), 'started activity safety review')
    assert sql('SELECT estado::text FROM sesion WHERE id=%s', (state['started'],), True)[0][0] == 'activa'
    state['broker_booking'] = booking(70, True)
    state['outage_booking'] = booking(80, True)
    save()
elif phase == 'broker-offline':
    state['broker_event'] = change(state['buyer'], 'suspended')['event_id']
    save()
    api('PUT', '/api/user/me', state['buyer_token'], PROFILE, expected=403)
    api('PUT', '/api/user/me', state['buyer_token'], PROFILE, expected=403)
    # Independent authority recovery must work without any AMQP connection.
    wait(lambda: sql('SELECT estado::text FROM sesion WHERE id=%s', (state['broker_booking'],), True)[0][0] == 'cancelada', 'broker-independent cancellation')
    wait(lambda: bool(sql("SELECT 1 FROM notificacion WHERE evento_id=%s AND tipo='estado_cuenta'", (state['broker_event'],), True)), 'broker-independent account notice')
    state['notice_id'] = sql('SELECT id::text FROM notificacion WHERE evento_id=%s', (state['broker_event'],), True)[0][0]
    api('PUT', f"/api/alert/notifications/{state['notice_id']}/read", state['buyer_token'])
    state['notice_read_at'] = str(sql('SELECT leido_en FROM notificacion WHERE id=%s', (state['notice_id'],), True)[0][0])
    save()
    change(state['buyer'], 'active')
    print('PASS: broker outage preserves authority denial and independently recovers cancellation and original account notice')
elif phase == 'outbox-drained':
    wait(lambda: sql('''SELECT NOT EXISTS(SELECT 1 FROM standing.outbox WHERE published_at IS NULL)
       AND NOT EXISTS(SELECT 1 FROM booking_outbox WHERE published_at IS NULL)''', fetch=True)[0][0], 'confirmed original outbox publication')
elif phase == 'recovered':
    wait(lambda: len(sql("SELECT id FROM notificacion WHERE evento_id=%s AND tipo='estado_cuenta'", (state['broker_event'],), True)) == 1, 'notice deduplication after restart')
    assert str(sql('SELECT leido_en FROM notificacion WHERE id=%s', (state['notice_id'],), True)[0][0]) == state['notice_read_at'], 'Redelivery reset read timestamp'
    # New authorization must survive delayed delivery of a historical sanction.
    state['outage_booking'] = booking(90, True)
    save()
    print('PASS: worker restart and broker recovery preserve deduplication and newer authorizations')
elif phase == 'authority-offline':
    for INSTANCE in (1, 2):
        message(state['outage_booking'], 503)
        api('POST', f"/api/match/availability/{state['compa']}", state['compa_token'], {'availability': AVAILABILITY}, expected=503)
        api('GET', f"/api/chat/bookings/{state['outage_booking']}/messages", state['buyer_token'])
        api('GET', f"/api/chat/bookings/{state['outage_booking']}/safety", state['buyer_token'])
    api('PUT', f"/api/match/session/{state['outage_booking']}/state", state['buyer_token'], {'estado': 'cancelada'})
    print('PASS: authority outage denies commercial writes without blocking history, safety or own cancellation')
elif phase == 'finished':
    for INSTANCE in (1, 2):
        api('GET', '/api/user/me/standing', state['buyer_token'])
        api('PUT', '/api/user/me', state['compa_token'], PROFILE)
    print('PASS: authority restart restores permitted writes with the original tokens')
else:
    raise RuntimeError('Unknown fixture phase')
