"""Idempotent broker bootstrap. Only this one-shot process has admin credentials.

Role credentials live in separate Docker volumes, never in an image or CI log.
"""
import base64
import json
import os
from pathlib import Path
import secrets
import urllib.error
import urllib.parse
import urllib.request


def request(method, path, data=None):
    token = base64.b64encode((os.environ['RABBITMQ_USER'] + ':' + os.environ['RABBITMQ_PASSWORD']).encode()).decode()
    req = urllib.request.Request('http://rabbitmq:15672/api/' + path,
        data=None if data is None else json.dumps(data).encode(), method=method,
        headers={'Authorization': 'Basic ' + token, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=10) as response:
        raw = response.read()
        return json.loads(raw) if raw else None


def configure():
    environment = os.environ['RAC_ENV']
    if environment not in ('dev', 'qa', 'prd'):
        raise ValueError('invalid environment')
    if os.environ['RABBITMQ_USER'] == 'guest':
        raise ValueError('guest is loopback-only; provision a named broker administrator')
    vhost = 'rac-' + environment
    encoded = urllib.parse.quote(vhost, safe='')
    request('PUT', 'vhosts/' + encoded, {})
    request('PUT', f'exchanges/{encoded}/rac.bookings', {'type': 'topic', 'durable': True, 'auto_delete': False, 'arguments': {}})
    request('PUT', f'queues/{encoded}/rac.alert.bookings', {'durable': True, 'auto_delete': False,
        'arguments': {'x-queue-type': 'quorum'}})
    request('PUT', f'exchanges/{encoded}/rac.bookings.failed', {'type': 'direct', 'durable': True, 'auto_delete': False, 'arguments': {}})
    request('PUT', f'queues/{encoded}/rac.alert.bookings.failed', {'durable': True, 'auto_delete': False,
        'arguments': {'x-queue-type': 'quorum'}})
    failed_bindings = request('GET', f'bindings/{encoded}/e/rac.bookings.failed/q/rac.alert.bookings.failed')
    if not any(b['routing_key'] == 'failed' for b in failed_bindings):
        request('POST', f'bindings/{encoded}/e/rac.bookings.failed/q/rac.alert.bookings.failed',
            {'routing_key': 'failed', 'arguments': {}})
    # Confirmed quorum dead lettering retains exhausted deliveries, even when
    # the failed queue is unavailable. No lossy default DLX forwarding.
    request('PUT', f'policies/{encoded}/booking-delivery', {'pattern': '^rac[.]alert[.]bookings$',
        'definition': {'delivery-limit': 20, 'dead-letter-exchange': 'rac.bookings.failed',
            'dead-letter-routing-key': 'failed', 'dead-letter-strategy': 'at-least-once',
            'overflow': 'reject-publish'}, 'priority': 10, 'apply-to': 'quorum_queues'})
    bindings = request('GET', f'bindings/{encoded}/e/rac.bookings/q/rac.alert.bookings')
    if not any(b['routing_key'] == 'booking.state_changed.v1' for b in bindings):
        request('POST', f'bindings/{encoded}/e/rac.bookings/q/rac.alert.bookings',
            {'routing_key': 'booking.state_changed.v1', 'arguments': {}})
    for role, write, read in [('publisher', '^rac[.]bookings$', '^$'), ('consumer', '^$', '^rac[.]alert[.]bookings$')]:
        file = Path('/credentials/' + role + '/url')
        user = vhost + '-' + role
        if file.exists():
            existing = urllib.parse.urlsplit(file.read_text(encoding='utf-8').strip())
            if existing.username != user or existing.path != '/' + vhost:
                raise ValueError('credential volume belongs to a different environment')
            password = urllib.parse.unquote(existing.password)
        else:
            password = secrets.token_urlsafe(36)
        request('PUT', 'users/' + user, {'password': password, 'tags': ''})
        request('PUT', f'permissions/{encoded}/{user}', {'configure': '^$', 'write': write, 'read': read})
        temporary = file.with_suffix('.tmp')
        temporary.write_text(f'amqp://{user}:{password}@rabbitmq:5672/{vhost}\n', encoding='utf-8')
        temporary.chmod(0o600)
        temporary.replace(file)


if __name__ == '__main__':
    try:
        configure()
    except Exception:
        # HTTP diagnostics can contain generated credentials. Never echo them.
        raise SystemExit('Messaging configuration failed; inspect broker health and permissions') from None
    print('Messaging topology and scoped credentials configured')
