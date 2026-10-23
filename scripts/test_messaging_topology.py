"""Invoked only inside test_messaging.py's disposable broker network."""
import os
from pathlib import Path
import configure_messaging as broker

if os.environ.get('RAC_DISPOSABLE_MESSAGING') != '1' or os.environ.get('RABBITMQ_USER') != 'test':
    raise RuntimeError('Disposable broker fixture required')

roles = {
    'publisher': ('^rac[.]bookings$', '^$'),
    'consumer': ('^$', '^rac[.]alert[.]bookings$'),
    'standing-publisher': ('^rac[.]standing$', '^$'),
    'standing-match': ('^$', '^rac[.]match[.]standing$'),
}
broker.configure()
first = {role: (Path('/credentials') / role / 'url').read_bytes() for role in roles}
broker.configure()
for role, (write, read) in roles.items():
    assert first[role] == (Path('/credentials') / role / 'url').read_bytes()
    permissions = broker.request('GET', 'permissions/rac-dev/rac-dev-' + role)
    assert permissions['configure'] == '^$'
    assert permissions['write'] == write and permissions['read'] == read
for queue in ('rac.match.standing', 'rac.match.standing.failed'):
    assert broker.request('GET', 'queues/rac-dev/' + queue)['arguments']['x-queue-type'] == 'quorum'
policy = broker.request('GET', 'policies/rac-dev/standing-delivery')['definition']
assert policy['dead-letter-strategy'] == 'at-least-once'
assert policy['overflow'] == 'reject-publish' and policy['delivery-limit'] == 20
