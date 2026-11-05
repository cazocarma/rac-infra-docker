"""Hermetic photo/S3 proof: disposable RustFS/Postgres and synthetic identities.

Never reads .env, joins a development network, exposes host ports or touches DEV.
"""
from pathlib import Path
import subprocess
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
RUSTFS = 'rustfs/rustfs:1.0.3@sha256:9ca9559533b537d10482fe923288b676ad08f92a7069d9a17327fbae3cab688b'


def run(*args, ok=True):
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                            encoding='utf-8', timeout=300)
    if ok and result.returncode:
        failures = '\n'.join(line for line in result.stdout.splitlines()
                             if '.go:' in line or 'FAIL' in line)
        raise RuntimeError('Disposable photo proof failed\n' + failures + '\n'
                           + result.stdout[-2000:] + result.stderr[-1500:])
    return result


def main():
    name = 'rac-photo-test-' + uuid.uuid4().hex[:12]
    storage, database, tools = name+'-storage', name+'-database', name+'-tools'
    processing_image = name+'-processing'
    # These identities exist only inside the isolated test network/container.
    fixtures = {
        'AWS_ACCESS_KEY_ID': 'synthetic-photo-root',
        'AWS_SECRET_ACCESS_KEY': 'synthetic-photo-root-password-123456',
        'PROFILE_S3_BUCKET': 'rac-photo-fixture',
        'PROFILE_S3_ACCESS_KEY': 'synthetic-photo-app',
        'PROFILE_S3_SECRET_KEY': 'synthetic-photo-app-password-123456',
        'BACKUP_S3_ACCESS_KEY': 'synthetic-photo-backup',
        'BACKUP_S3_SECRET_KEY': 'synthetic-photo-backup-password-123456',
        'S3_ENDPOINT': 'http://photo-storage-fixture:9000',
        'RAC_ENV': 'dev',
        'PHOTO_QUARANTINE_BUCKET': 'rac-photo-quarantine-fixture',
        'PHOTO_STAGING_BUCKET': 'rac-photo-staging-fixture',
        'PHOTO_INGEST_ACCESS_KEY': 'synthetic-photo-ingest',
        'PHOTO_INGEST_SECRET_KEY': 'synthetic-photo-ingest-password-123456',
        'PHOTO_READER_ACCESS_KEY': 'synthetic-photo-reader',
        'PHOTO_READER_SECRET_KEY': 'synthetic-photo-reader-password-123456',
        'PHOTO_STAGING_ACCESS_KEY': 'synthetic-photo-staging',
        'PHOTO_STAGING_SECRET_KEY': 'synthetic-photo-staging-password-123456',
        'PHOTO_PREVIEW_ACCESS_KEY': 'synthetic-photo-preview',
        'PHOTO_PREVIEW_SECRET_KEY': 'synthetic-photo-preview-password-123456',
        'PHOTO_MEDIA_BUCKET': 'rac-photo-approved-fixture',
        'PHOTO_PROMOTER_ACCESS_KEY': 'synthetic-photo-promoter',
        'PHOTO_PROMOTER_SECRET_KEY': 'synthetic-photo-promoter-password-123456',
    }
    flags = [item for key, value in fixtures.items() for item in ('-e', key+'='+value)]
    try:
        run('docker', 'network', 'create', name)
        run('docker', 'run', '-d', '--name', storage, '--network', name,
            '--network-alias', 'photo-storage-fixture',
            '--tmpfs', '/data:rw,mode=1777', '--tmpfs', '/logs:rw,mode=1777',
            '-e', 'RUSTFS_ACCESS_KEY='+fixtures['AWS_ACCESS_KEY_ID'],
            '-e', 'RUSTFS_SECRET_KEY='+fixtures['AWS_SECRET_ACCESS_KEY'],
            '-e', 'RUSTFS_VOLUMES=/data', '-e', 'RUSTFS_OBS_LOG_DIRECTORY=/logs',
            '-e', 'RUSTFS_ADDRESS=:9000', '-e', 'RUSTFS_CONSOLE_ENABLE=true', RUSTFS)
        for _ in range(60):
            health = run('docker', 'exec', storage, 'curl', '--fail', '--silent',
                         '--max-time', '2', 'http://localhost:9000/health', ok=False)
            if health.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError('Disposable RustFS did not become healthy')
        run('docker', 'build', '-q', '-t', tools, '-f', str(ROOT/'tools/storage/Dockerfile'), str(ROOT))
        run('docker', 'build', '-q', '-t', processing_image, '-f', str(ROOT/'tools/photo-processing/Dockerfile'), str(ROOT))
        run('docker', 'run', '--rm', '--network', name, *flags,
            '--entrypoint', 'python', tools, 'configure_storage.py')
        pipeline_iam = run('docker', 'run', '--rm', '--network', name, *flags,
            '--entrypoint', 'python', tools, 'configure_photo_pipeline.py')
        if 'PASS: separate ingest/read-only quarantine/staging IAM' not in pipeline_iam.stdout:
            raise RuntimeError('Pipeline IAM proof did not run')
        media_iam = run('docker', 'run', '--rm', '--network', name, *flags,
                        '--entrypoint', 'python', tools, 'configure_photo_media.py')
        if 'PASS: private versioned media, exact older-version readback' not in media_iam.stdout:
            raise RuntimeError('Versioned media IAM proof did not run')

        run('docker', 'run', '-d', '--name', database, '--network', name,
            '--tmpfs', '/var/lib/postgresql/data', '-e', 'POSTGRES_PASSWORD=test-only',
            '-e', 'POSTGRES_DB=photos', 'postgis/postgis:16-3.4')
        for _ in range(60):
            ready = run('docker', 'exec', database, 'pg_isready', '-U', 'postgres', ok=False)
            if ready.returncode == 0 and 'PostgreSQL init process complete' in run('docker', 'logs', database).stdout:
                break
            time.sleep(1)
        else:
            raise RuntimeError('Disposable photo database did not start')
        run('docker','exec',database,'psql','-X','-v','ON_ERROR_STOP=1','-U','postgres','-d','photos','-c','CREATE DATABASE photo_sources')
        run('docker','exec',database,'psql','-X','-v','ON_ERROR_STOP=1','-U','postgres','-d','photos','-c','CREATE DATABASE photo_migration')
        run('docker','exec',database,'psql','-X','-v','ON_ERROR_STOP=1','-U','postgres','-d','photos','-c','CREATE DATABASE photo_processing')
        run('docker','exec',database,'psql','-X','-v','ON_ERROR_STOP=1','-U','postgres','-d','photos','-c','CREATE DATABASE photo_uploads')
        run('docker','exec',database,'psql','-X','-v','ON_ERROR_STOP=1','-U','postgres','-d','photos','-c','CREATE DATABASE listing_review_http')
        for target in ('photos','photo_sources','photo_migration','photo_processing','photo_uploads','listing_review_http'):
            run('docker', 'run', '--rm', '--network', name,
                '--mount', f'type=bind,source={ROOT/"db/migrations"},target=/flyway/sql,readonly',
                '-e', 'FLYWAY_URL=jdbc:postgresql://'+database+':5432/'+target,
                '-e', 'FLYWAY_USER=postgres', '-e', 'FLYWAY_PASSWORD=test-only',
                '-e', 'FLYWAY_SCHEMAS=meta', '-e', 'FLYWAY_DEFAULT_SCHEMA=meta',
                'flyway/flyway:11.15.0-alpine', 'migrate')
        go_flags = [item for key in ('PROFILE_S3_BUCKET', 'PROFILE_S3_ACCESS_KEY', 'PROFILE_S3_SECRET_KEY')
                    for item in ('-e', key+'='+fixtures[key])]
        go_flags += [item for key,value in fixtures.items() if key.startswith('PHOTO_') for item in ('-e',key+'='+value)]
        result = run('docker', 'run', '--rm', '--network', name,
            '--mount', f'type=bind,source={ROOT.parent/"rac-user-service"},target=/sources,readonly',
            '-v', 'rac-quota-go-cache:/go/pkg/mod', '-v', 'rac-user-go-build:/root/.cache/go-build',
            *go_flags, '-e', 'GIN_MODE=release',
            '-e', 'RAC_PHOTO_TEST_S3_ENDPOINT='+fixtures['S3_ENDPOINT'],
            '-e', 'RAC_PHOTO_CREATE_TEST_ENDPOINT='+fixtures['S3_ENDPOINT'],
            '-e', 'RAC_ONBOARDING_TEST_DATABASE_URL=postgres://postgres:test-only@'+database+':5432/photos?sslmode=disable',
            '-e', 'RAC_PHOTO_ASSET_TEST_DATABASE_URL=postgres://postgres:test-only@'+database+':5432/photo_sources?sslmode=disable',
            '-e', 'RAC_PHOTO_MIGRATION_TEST_DATABASE_URL=postgres://postgres:test-only@'+database+':5432/photo_migration?sslmode=disable',
            '-e', 'RAC_PHOTO_QUEUE_TEST_DATABASE_URL=postgres://postgres:test-only@'+database+':5432/photo_processing?sslmode=disable',
            '-e', 'RAC_PHOTO_UPLOAD_TEST_DATABASE_URL=postgres://postgres:test-only@'+database+':5432/photo_uploads?sslmode=disable',
            '-e', 'RAC_PHOTO_PIPELINE_TEST_ENDPOINT='+fixtures['S3_ENDPOINT'],
            '-e', 'RAC_LISTING_REVIEW_TEST_DATABASE_URL=postgres://postgres:test-only@'+database+':5432/listing_review_http?sslmode=disable',
            processing_image, 'sh', '-c',
            'cp -a /sources /tmp/rac && cd /tmp/rac && go test -race -count=1 -v '
            "-run '^(TestS3CreateOnlyIntegration|TestVersionedMedia.*|TestPhotoSourcePostgres|TestPhotoQueuePostgres|TestPrivatePhotoUploadsPostgresHTTP|TestProfilePhotosOwnershipAndPublication|TestCopyPhotosIntegrityAndRetry|TestReaderPostgresHTTP)$' "
            './internal/photostore ./internal/photoassets ./internal/http ./internal/listingreview ./cmd/migrate-photos')
        for required in ('TestS3CreateOnlyIntegration', 'TestPhotoSourcePostgres/s3', 'TestPhotoQueuePostgres/rustfs-worker', 'TestPhotoQueuePostgres/completed-replay-after-expiry', 'TestProfilePhotosOwnershipAndPublication/s3', 'TestCopyPhotosIntegrityAndRetry'):
            if '--- PASS: '+required not in result.stdout:
                raise RuntimeError('Required photo proof skipped: '+required)
        if '--- PASS: TestPrivatePhotoUploadsPostgresHTTP/s3-upload-worker-and-owner-status' not in result.stdout:
            raise RuntimeError('Owner API to native worker proof skipped')
        if '--- PASS: TestReaderPostgresHTTP/private-photo-preview/rustfs-read-only' not in result.stdout:
            raise RuntimeError('Audited reader to real RustFS preview proof skipped')
        if '--- PASS: TestReaderPostgresHTTP/durable-photo-promotion-intent' not in result.stdout:
            raise RuntimeError('Durable photo promotion preparation proof skipped')
        if '--- PASS: TestReaderPostgresHTTP/durable-photo-promotion-intent/rustfs-copy-readback' not in result.stdout:
            raise RuntimeError('Committed intent to versioned RustFS copy/readback proof skipped')
        if '--- PASS: TestReaderPostgresHTTP/photo-finalization/rustfs-complete-no-recopy' not in result.stdout:
            raise RuntimeError('Atomic photo finalization with real RustFS and no-copy replay proof skipped')
        if '--- PASS: TestReaderPostgresHTTP/photo-finalization/staff-http' not in result.stdout:
            raise RuntimeError('Verified JWT photo approval ingress proof skipped')
        if '--- PASS: TestVersionedMediaS3Integration' not in result.stdout:
            raise RuntimeError('Versioned S3 destination adapter proof skipped')
        print('PASS: real RustFS conditional creation and concurrent single winner; private profile IAM; owner-scoped raw-source readback and atomic analysis intent; photo API and integrity-preserving migration', flush=True)
        print('PASS: four pipeline IAM identities with negative permissions; worker reads quarantine, runs native OCR, writes/verifies staging and commits contact-correction result using function-only PostgreSQL login',flush=True)
        print('PASS: authenticated staff preview of exact pending JPEG from real RustFS with dedicated read-only IAM and two committed SQL access audits',flush=True)
        print('PASS: durable immutable photo promotion intent before I/O, fresh audited retry attempts, event/actor/policy conflicts, concurrency, expiry/fault rollback and closed publication gate',flush=True)
        print('PASS: committed SQL intent to real RustFS staging read, conditional private media copy and exact-version readback; prepared retry reuses the same verified version without publication',flush=True)
        print('PASS: atomic receipt/approval/reference/audit/outbox/pointer with real RustFS; expired commit, policy/standing/catalog change, prerequisites, rollback and concurrent winner; finalized retry performs no S3 I/O',flush=True)
        print('PASS: separate private versioned media destination and promotion IAM; Go adapter conditional creation, non-null VersionId capture, exact-version readback and recovery without overwrite',flush=True)
        print('PASS: authenticated owner HTTP upload and request recovery to real RustFS/SQL/native OCR; contact correction and benign awaiting-review status, no public photo or private signals exposed',flush=True)
        from photo_worker_runtime_fixture import prove
        prove(run, ROOT, name, database, tools, fixtures)
    finally:
        run('docker', 'rm', '-f', database, storage, ok=False)
        run('docker', 'network', 'rm', name, ok=False)
        run('docker', 'image', 'rm', tools, ok=False)
        run('docker', 'image', 'rm', processing_image, ok=False)


if __name__ == '__main__':
    main()
