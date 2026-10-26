"""Database credential topology shared by provisioning and environment checks."""
from urllib.parse import urlsplit, unquote

ROLES = {
    'USER_DB_URL': 'rac_user', 'MATCH_DB_URL': 'rac_match',
    'CHAT_DB_URL': 'rac_chat', 'ALERT_DB_URL': 'rac_alert',
    'MAINTENANCE_DB_URL': 'rac_maintenance', 'RELAY_DB_URL': 'rac_relay',
    'ALERT_CONSUMER_DB_URL': 'rac_alert_consumer',
    'STANDING_RELAY_DB_URL': 'rac_standing_relay', 'STANDING_MATCH_DB_URL': 'rac_standing_match',
    'STANDING_ALERT_DB_URL': 'rac_standing_alert',
    'STANDING_SESSION_DB_URL': 'rac_standing_sessions',
    'IDENTITY_DB_URL': 'rac_seed', 'BACKUP_DB_URL': 'rac_backup',
}


def validate_credentials(values):
    database = values.get('POSTGRES_DB')
    if not database or values.get('MIGRATION_DB_USER') != 'rac_migrator':
        raise RuntimeError('Dedicated migration identity required')
    credentials = {}
    for key, role in ROLES.items():
        parsed = urlsplit(values.get(key, ''))
        if (parsed.scheme not in ('postgres', 'postgresql') or parsed.hostname != 'postgres'
                or parsed.port not in (None, 5432) or parsed.path != '/' + database
                or unquote(parsed.username or '') != role or not parsed.password
                or parsed.fragment):
            raise RuntimeError('Invalid scoped database configuration: ' + key)
        credentials[role] = unquote(parsed.password)
    credentials['rac_migrator'] = values.get('MIGRATION_DB_PASSWORD', '')
    if any(len(p) < 24 for p in credentials.values()) or len(set(credentials.values())) != len(credentials):
        raise RuntimeError('Independent database secrets of at least 24 characters required')
    return credentials
