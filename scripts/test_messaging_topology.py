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
    'standing-alert': ('^$', '^rac[.]alert[.]standing$'),
}
broker.configure()
first = {role: (Path('/credentials') / role / 'url').read_bytes() for role in roles}
broker.configure()
for role, (write, read) in roles.items():
    assert first[role] == (Path('/credentials') / role / 'url').read_bytes()
    permissions = broker.request('GET', 'permissions/rac-dev/rac-dev-' + role)
    assert permissions['configure'] == '^$'
    assert permissions['write'] == write and permissions['read'] == read
for queue in ('rac.match.standing', 'rac.match.standing.failed', 'rac.alert.standing', 'rac.alert.standing.failed'):
    assert broker.request('GET', 'queues/rac-dev/' + queue)['arguments']['x-queue-type'] == 'quorum'
policy = broker.request('GET', 'policies/rac-dev/standing-delivery')['definition']
assert policy['dead-letter-strategy'] == 'at-least-once'
assert policy['overflow'] == 'reject-publish' and policy['delivery-limit'] == 20

# Losing a local volume is not authorization to rotate the deployed account.
lost = Path('/credentials/standing-alert/url')
original = lost.read_bytes()
before = broker.request('GET', 'users/rac-dev-standing-alert')['password_hash']
lost.unlink()
try:
    try:
        broker.configure()
    except RuntimeError as error:
        assert 'restore or rotate explicitly' in str(error)
    else:
        raise AssertionError('Missing volume silently rotated broker credentials')
    assert broker.request('GET', 'users/rac-dev-standing-alert')['password_hash'] == before
finally:
    lost.write_bytes(original)
    lost.chmod(0o600)

policy = broker.request('GET', 'policies/rac-dev/standing-alert-delivery')['definition']
assert policy['dead-letter-strategy'] == 'at-least-once'
assert policy['dead-letter-routing-key'] == 'alert.failed'
assert policy['overflow'] == 'reject-publish' and policy['delivery-limit'] == 20
