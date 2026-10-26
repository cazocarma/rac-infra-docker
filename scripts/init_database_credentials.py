"""Generate missing independent DEV database credentials; never print values."""
from pathlib import Path
import argparse
import os
import secrets
from urllib.parse import quote
from database_roles import ROLES, validate_credentials


def initialize(path):
    if path.name.endswith('.example'):
        raise RuntimeError('Refusing to write credentials into a versioned example')
    lines = path.read_text(encoding='utf-8').splitlines()
    values = dict(line.split('=', 1) for line in lines if '=' in line and not line.lstrip().startswith('#'))
    if values.get('RAC_ENV') != 'dev':
        raise RuntimeError('Credential generation is DEV only')
    values['MIGRATION_DB_USER'] = 'rac_migrator'
    # Never silently retain the old shared/admin migration secret.
    original = dict(line.split('=', 1) for line in lines if '=' in line and not line.lstrip().startswith('#'))
    if original.get('MIGRATION_DB_USER') != 'rac_migrator' or len(values.get('MIGRATION_DB_PASSWORD', '')) < 24:
        values['MIGRATION_DB_PASSWORD'] = secrets.token_urlsafe(36)
    for key, role in ROLES.items():
        if not values.get(key):
            secret = secrets.token_urlsafe(36)
            values[key] = f'postgresql://{role}:{quote(secret, safe="")}@postgres:5432/{values["POSTGRES_DB"]}?sslmode=disable'
    validate_credentials(values)
    # Retire shared app URL; tools get their own explicit operator credentials.
    values.pop('DATABASE_URL', None)
    rendered, seen = [], set()
    for line in lines:
        if '=' in line and not line.lstrip().startswith('#'):
            key = line.split('=', 1)[0]
            if key == 'DATABASE_URL':
                continue
            line = key + '=' + values[key]
            seen.add(key)
        rendered.append(line)
    rendered += [key + '=' + value for key, value in values.items() if key not in seen]
    temporary = path.with_suffix(path.suffix + '.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as output:
        output.write('\n'.join(rendered) + '\n')
    os.replace(temporary, path)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path, default=Path(__file__).resolve().parents[1] / 'envs/.env.dev')
    initialize(parser.parse_args().env_file)
    print('DEV database credentials ready; no values printed.')
