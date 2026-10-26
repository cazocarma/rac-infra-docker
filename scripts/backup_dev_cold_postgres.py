"""Encrypt a stopped DEV PostgreSQL volume, then boot an isolated restored copy.

This precedes credential bootstrap/migrations. Never starts or modifies the
source database. The normal logical DB+S3 backup remains a separate gate.
"""
from pathlib import Path
import json
import os
import secrets
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
RESTIC = 'restic/restic:0.19.1@sha256:136600b6ff6843d61d355f7f71f460a166429f35de6fd11b568fece3c9a4d510'


def run(*args, check=True, timeout=600):
    result = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', timeout=timeout)
    if check and result.returncode:
        # Output can contain private paths/database names. Keep diagnostics fixed.
        raise RuntimeError('Cold backup operation failed: ' + args[0])
    return result


def main():
    source = json.loads(run('docker', 'inspect', 'rac-dev-postgres-1').stdout)[0]
    if source['State']['Running'] or source['Config']['Labels'].get('com.docker.compose.project') != 'rac-dev':
        raise RuntimeError('Stopped rac-dev PostgreSQL source required')
    mounts = [m for m in source['Mounts'] if m['Destination'] == '/var/lib/postgresql/data']
    if len(mounts) != 1 or mounts[0]['Type'] != 'volume':
        raise RuntimeError('Exactly one named PostgreSQL data volume required')
    volume = mounts[0]['Name']
    if run('docker', 'ps', '--filter', 'volume=' + volume, '--format', '{{.ID}}').stdout.strip():
        raise RuntimeError('Source volume is mounted by a running container')
    values = dict(line.split('=', 1) for line in (ROOT / 'envs/.env.backups').read_text(encoding='utf-8').splitlines()
                  if '=' in line and not line.startswith('#'))
    if not values.get('RESTIC_PASSWORD') or not values.get('BACKUP_DIRECTORY'):
        raise RuntimeError('Existing private backup configuration required')
    backup_root = Path(values['BACKUP_DIRECTORY']).resolve()
    repository = (backup_root / 'cold-postgres' / 'repository').resolve()
    if not repository.is_relative_to(backup_root):
        raise RuntimeError('Cold repository must remain inside the configured backup directory')
    repository.mkdir(parents=True, exist_ok=True)
    fixture = 'rac-cold-restore-' + secrets.token_hex(8)
    restored_volume = fixture + '-data'
    original_user = next((v.split('=', 1)[1] for v in source['Config']['Env'] if v.startswith('POSTGRES_USER=')), 'postgres')
    with tempfile.TemporaryDirectory(prefix='rac-cold-key-') as directory:
        keyfile = Path(directory) / 'private.env'
        with os.fdopen(os.open(keyfile, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'w', encoding='utf-8') as out:
            out.write('RESTIC_PASSWORD=' + values['RESTIC_PASSWORD'] + '\n')
        base = ['docker', 'run', '--rm', '--network', 'none', '--env-file', str(keyfile),
                '--mount', f'type=bind,source={repository},target=/repository']

        def restic(*args, mounts=()):
            return run(*base, *mounts, RESTIC, '--repo', '/repository', '--cache-dir', '/tmp/cache', *args)

        if not (repository / 'config').exists():
            restic('init')
        result = restic('backup', '/source', '--tag', 'rac-dev-pre-p03-cold', '--json',
                        mounts=('--mount', f'type=volume,source={volume},target=/source,readonly'))
        if (json.loads(run('docker', 'inspect', 'rac-dev-postgres-1').stdout)[0]['State']['Running'] or
                run('docker', 'ps', '--filter', 'volume=' + volume, '--format', '{{.ID}}').stdout.strip()):
            raise RuntimeError('Source was started during the cold backup; consistency is not proven')
        summary = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
        summary = next(item for item in summary if item.get('message_type') == 'summary')
        snapshot = summary['snapshot_id']
        restic('check', '--read-data')
        run('docker', 'volume', 'create', '--label', 'rac.purpose=cold-restore-proof', restored_volume)
        try:
            restic('restore', snapshot, '--target', '/restore', '--verify',
                   mounts=('--mount', f'type=volume,source={restored_volume},target=/restore/source'))
            run('docker', 'run', '-d', '--name', fixture, '--network', 'none',
                '--label', 'rac.purpose=cold-restore-proof',
                '--mount', f'type=volume,source={restored_volume},target=/var/lib/postgresql/data', source['Image'])
            deadline = time.monotonic() + 90
            while run('docker', 'exec', fixture, 'pg_isready', '-U', original_user, check=False).returncode:
                if time.monotonic() >= deadline:
                    raise RuntimeError('Restored PostgreSQL did not become ready')
                time.sleep(1)
            databases = run('docker', 'exec', fixture, 'psql', '-XAt', '-U', original_user, '-d', 'postgres',
                            '-c', 'SELECT datname FROM pg_database WHERE NOT datistemplate ORDER BY datname').stdout.splitlines()
            for database in databases:
                run('docker', 'exec', fixture, 'psql', '-XAt', '-v', 'ON_ERROR_STOP=1', '-U', original_user, '-d', database,
                    '-c', 'SELECT count(*) FROM pg_catalog.pg_class')
            evidence = {'schema_version': 1, 'kind': 'dev_cold_postgres_restore', 'snapshot_id': snapshot,
                        'source_unchanged': True, 'encrypted_repository_checked': True, 'restore_verified': True,
                        'restored_databases_opened': len(databases), 'source_image_id': source['Image'],
                        'verified_at_unix': int(time.time())}
            proof = backup_root / 'cold-postgres' / 'verified-restore.json'
            proof.write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf-8')
            print('PASS: encrypted cold PostgreSQL backup, full repository check, verified restore and isolated database boot')
        finally:
            # Only names generated in this invocation; never source/DEV/prune.
            run('docker', 'rm', '-f', fixture, check=False)
            run('docker', 'volume', 'rm', restored_volume, check=False)


if __name__ == '__main__':
    main()
