"""P10 EvidenceStore proof against a disposable RustFS. Synthetic data only.

Creates its own network, volume, RustFS and PostgreSQL; reads no .env, mounts no
existing volume and publishes no port. The admin-service source is the pinned
sibling checkout. RAC_EVIDENCE_PLATFORM_SOURCE (local development only) points
at an unreleased rac-platform checkout instead of the vendored module.
"""
import os
import subprocess
import time
import uuid
from pathlib import Path

from test_photo_storage import ROOT, RUSTFS, run

GO = 'golang:1.27.3'


def main():
    name = 'rac-evidence-store-' + uuid.uuid4().hex[:12]
    storage, volume, database = name + '-storage', name + '-data', name + '-db'
    capture_password = 'synthetic-evidence-capture-' + uuid.uuid4().hex
    reader_password = 'synthetic-evidence-reader-' + uuid.uuid4().hex
    staff_password = 'synthetic-cases-staff-' + uuid.uuid4().hex
    intake_password = 'synthetic-cases-intake-' + uuid.uuid4().hex
    ref = 'audit.reference,audit.reference,audit.reference'
    access, secret = 'synthetic-evidence-root', 'synthetic-evidence-root-password-123456'
    admin = ROOT.parent / 'rac-admin-service'
    platform = os.environ.get('RAC_EVIDENCE_PLATFORM_SOURCE', '')
    try:
        run('docker', 'network', 'create', name)
        run('docker', 'volume', 'create', volume)
        run('docker', 'run', '-d', '--name', storage, '--network', name, '--network-alias', 'evidence-store-fixture',
            '--mount', f'type=volume,source={volume},target=/data', '--tmpfs', '/logs:rw,mode=1777', '-e', 'RUSTFS_ACCESS_KEY=' + access,
            '-e', 'RUSTFS_SECRET_KEY=' + secret, '-e', 'RUSTFS_VOLUMES=/data', '-e', 'RUSTFS_OBS_LOG_DIRECTORY=/logs',
            '-e', 'RUSTFS_ADDRESS=:9000', RUSTFS)
        for _ in range(60):
            if run('docker', 'exec', storage, 'curl', '--silent', '--fail', '--max-time', '2',
                   'http://localhost:9000/health', ok=False).returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError('Disposable evidence storage did not become healthy')
        run('docker', 'run', '-d', '--name', database, '--network', name, '--network-alias', 'evidence-db-fixture',
            '--tmpfs', '/var/lib/postgresql/data', '-e', 'POSTGRES_PASSWORD=test-only', '-e', 'POSTGRES_DB=evidence',
            'postgis/postgis:16-3.4')
        for _ in range(90):
            if (run('docker', 'exec', database, 'pg_isready', '-U', 'postgres', ok=False).returncode == 0
                    and 'PostgreSQL init process complete' in run('docker', 'logs', database).stdout):
                break
            time.sleep(1)
        else:
            raise RuntimeError('Disposable evidence database did not become ready')
        time.sleep(2)
        run('docker', 'run', '--rm', '--network', name,
            '--mount', f'type=bind,source={ROOT / "db/migrations"},target=/flyway/sql,readonly',
            '-e', 'FLYWAY_URL=jdbc:postgresql://evidence-db-fixture:5432/evidence', '-e', 'FLYWAY_USER=postgres',
            '-e', 'FLYWAY_PASSWORD=test-only', '-e', 'FLYWAY_SCHEMAS=meta', '-e', 'FLYWAY_DEFAULT_SCHEMA=meta',
            '-e', 'FLYWAY_TABLE=schema_history', 'flyway/flyway:11.15.0-alpine', 'migrate')
        grants = {
            'rac_evidence_capture_lab': (capture_password, ['ts.evidence_ready()',
                'ts.evidence_prepare(audit.reference,audit.reference,audit.reference,jsonb)',
                'ts.evidence_commit(audit.reference,audit.reference,audit.reference,uuid,text,text,text)']),
            'rac_evidence_reader_lab': (reader_password, ['ts.evidence_ready()',
                'ts.evidence_open(audit.reference,audit.reference,audit.reference,uuid,text)']),
            'rac_ts_staff_lab': (staff_password, [f'ts.case_queue({ref},integer)', f'ts.case_assign({ref},uuid,audit.reference)',
                f'ts.case_detail({ref},uuid)', f'ts.action_propose({ref},uuid,text,text,text,integer,text)',
                f'ts.listing_hide_propose({ref},uuid,uuid,text,text,text)',
                f'ts.action_approve({ref},uuid)', f'ts.action_revoke({ref},uuid,text)', f'ts.appeal_decide({ref},uuid,text)']),
            'rac_ts_intake_lab': (intake_password, [f'ts.report_submit({ref},text,uuid,audit.reference,text,uuid)',
                f'ts.appeal_submit({ref},uuid,uuid)']),
        }
        statements = []
        for role, (password, functions) in grants.items():
            statements.append(f"CREATE ROLE {role} LOGIN PASSWORD '{password}';GRANT USAGE ON SCHEMA ts,audit TO {role};")
            statements += [f'GRANT EXECUTE ON FUNCTION {f} TO {role};' for f in functions]
            statements.append("DO $$DECLARE c uuid:=gen_random_uuid(); BEGIN INSERT INTO audit.chain_heads(chain_id) VALUES(c);"
                              f" INSERT INTO audit.writer_principals(database_role,actor_id,chain_id) VALUES('{role}',gen_random_uuid(),c); END$$;")
        # Synthetic lab policy only; real retention ceilings are D08/D14.
        statements.append("INSERT INTO ts.evidence_retention_policies(version,purpose,max_days,registered_by) "
                          "VALUES('evidence-lab-1','case_review',1,'44444444-4444-4444-8444-444444444444');")
        # The legal reader in the Go proof is assigned to the synthetic case.
        statements.append("INSERT INTO ts.cases(id,subject,severity) VALUES('77777777-7777-4777-8777-777777777777',"
                          "'99999999-9999-4999-8999-999999999999','P2');INSERT INTO ts.case_assignments(case_id,assignee,assigned_by) "
                          "VALUES('77777777-7777-4777-8777-777777777777','55555555-5555-4555-8555-555555555555',"
                          "'44444444-4444-4444-8444-444444444444');")
        subprocess.run(['docker', 'exec', '-i', database, 'psql', '-X', '-q', '-v', 'ON_ERROR_STOP=1', '-U', 'postgres',
                        '-d', 'evidence'], input=''.join(statements), text=True, capture_output=True, check=True, timeout=120)
        mounts = ['--mount', f'type=bind,source={admin},target=/sources,readonly']
        prepare = 'cp -a /sources /tmp/rac && cd /tmp/rac'
        mode = '-mod=vendor'
        if platform:
            mounts += ['--mount', f'type=bind,source={Path(platform).resolve()},target=/platform,readonly']
            prepare += (' && cp -a /platform /tmp/platform'
                        ' && go mod edit -replace github.com/cazocarma/rac-platform=/tmp/platform'
                        ' && GOFLAGS=-mod=mod go mod tidy >/dev/null')
            mode = '-mod=mod'
        result = run('docker', 'run', '--rm', '--network', name, *mounts,
                     '-v', 'rac-quota-go-cache:/go/pkg/mod',
                     '-e', 'RAC_EVIDENCE_TEST_ENDPOINT=http://evidence-store-fixture:9000',
                     '-e', 'RAC_EVIDENCE_TEST_ACCESS_KEY=' + access, '-e', 'RAC_EVIDENCE_TEST_SECRET_KEY=' + secret,
                     '-e', f'RAC_EVIDENCE_CAPTURE_DSN=postgres://rac_evidence_capture_lab:{capture_password}@evidence-db-fixture:5432/evidence?sslmode=disable',
                     '-e', f'RAC_CASES_STAFF_DSN=postgres://rac_ts_staff_lab:{staff_password}@evidence-db-fixture:5432/evidence?sslmode=disable',
                     '-e', f'RAC_CASES_INTAKE_DSN=postgres://rac_ts_intake_lab:{intake_password}@evidence-db-fixture:5432/evidence?sslmode=disable',
                     '-e', f'RAC_EVIDENCE_READER_DSN=postgres://rac_evidence_reader_lab:{reader_password}@evidence-db-fixture:5432/evidence?sslmode=disable',
                     GO, 'sh', '-c', prepare + f' && go test {mode} -race -count=1 -v ./internal/evidencestore ./internal/cases')
        if '--- PASS: TestRustFSCompliance' not in result.stdout or '--- PASS: TestServicePostgresRustFS' not in result.stdout                 or '--- PASS: TestCasesPostgres' not in result.stdout:
            raise RuntimeError('RustFS evidence proof did not run\n' + result.stdout[-2000:])
        print('PASS: sealed COMPLIANCE capture, exact-version open, create-only, delete/shorten denial, '
              'delete-marker isolation and no plaintext in the object store', flush=True)
        print('PASS: migrated registry with separate function-only capture/reader logins, permission split, '
              'justification, MFA expiry during read and audited access before reveal', flush=True)
        print('PASS: staff case HTTP over function-only logins: queue/detail without identities, conflict refusal, '
              'replay-safe proposal, four eyes and independent appeal', flush=True)
        print('PASS: synthetic EvidenceStore proof only; not key custody, retention approval or off-PC durability',
              flush=True)
    finally:
        run('docker', 'rm', '-f', storage, database, ok=False)
        run('docker', 'network', 'rm', name, ok=False)
        # Only the exact UUID volume created above.
        run('docker', 'volume', 'rm', volume, ok=False)


if __name__ == '__main__':
    main()
