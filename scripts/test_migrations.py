"""Fresh DB, legacy adoption, repeatability, integrity and checksum tests.

Only creates/removes uniquely named disposable Docker resources; never uses .env.
"""
from pathlib import Path
import argparse
import shutil
import subprocess
import tempfile
import time
import uuid

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--services', nargs='+', choices=('user', 'match', 'chat'), default=('user', 'match', 'chat'), help='Go service suites to run; migration integrity always runs')
args = parser.parse_args()

ROOT = Path(__file__).resolve().parent.parent
NAME = "rac-migration-test-" + uuid.uuid4().hex[:12]
def run(*args, ok=True, input=None):
    p = subprocess.run(list(args), input=input, text=True, capture_output=True)
    if ok and p.returncode:
        failures = "\n".join(line for line in p.stdout.splitlines() if ".go:" in line or "FAIL" in line or "panic:" in line)
        raise RuntimeError(failures + "\n" + p.stdout[-2000:] + p.stderr[-2000:])
    return p
def sql(db, text):
    return run("docker", "exec", "-i", NAME, "psql", "-v", "ON_ERROR_STOP=1", "-U", "postgres", "-d", db, "-At", input=text).stdout.strip()
def flyway(db, path, command="migrate", ok=True):
    return run("docker", "run", "--rm", "--network", NAME,
        "--mount", f"type=bind,source={path},target=/flyway/sql,readonly",
        "-e", f"FLYWAY_URL=jdbc:postgresql://{NAME}:5432/{db}",
        "-e", "FLYWAY_USER=postgres", "-e", "FLYWAY_PASSWORD=test-only",
        "-e", "FLYWAY_SCHEMAS=meta", "-e", "FLYWAY_DEFAULT_SCHEMA=meta",
        "-e", "FLYWAY_TABLE=schema_history", "-e", "FLYWAY_CLEAN_DISABLED=true",
        "flyway/flyway:11.15.0-alpine", command, ok=ok)
try:
    run("docker", "network", "create", NAME)
    run("docker", "run", "-d", "--name", NAME, "--network", NAME,
        "--tmpfs", "/var/lib/postgresql/data", "-e", "POSTGRES_PASSWORD=test-only",
        "-e", "POSTGRES_DB=fresh", "postgis/postgis:16-3.4")
    for attempt in range(60):
        if run("docker", "exec", NAME, "pg_isready", "-U", "postgres", ok=False).returncode == 0:
            # Wait for the final server, not the temporary initdb server.
            logs = run("docker", "logs", NAME).stdout
            if "PostgreSQL init process complete" in logs: break
        time.sleep(1)
    else: raise RuntimeError("Postgres test DB did not start")
    migration_dir = ROOT / "db/migrations"
    flyway("fresh", migration_dir)
    flyway("fresh", migration_dir)
    flyway("fresh", migration_dir, "validate")
    assert sql("fresh", "SELECT count(*) FROM meta.schema_history WHERE success AND version IS NOT NULL;") == str(len(list(migration_dir.glob("V*.sql"))))
    assert sql("fresh", "SELECT count(*) FROM information_schema.columns WHERE table_name='sesion' AND column_name IN ('creado_en','actualizado_en');") == "2"
    # Exercise the weekly quota against this disposable DB, including concurrent acceptance.
    quota_source = ROOT.parent / "rac-match-service"
    if quota_source.exists() and "match" in args.services:
        quota_tests = run("docker", "run", "--rm", "--network", NAME,
            "--mount", f"type=bind,source={quota_source},target=/sources,readonly",
            "-v", "rac-quota-go-cache:/go/pkg/mod", "-v", "rac-match-go-build:/root/.cache/go-build",
            "-e", f"RAC_QUOTA_TEST_DATABASE_URL=postgres://postgres:test-only@{NAME}:5432/fresh?sslmode=disable",
            "golang:1.27.2", "sh", "-c", "cp -a /sources /tmp/rac && cd /tmp/rac && go test -race -count=1 -v ./internal/repo ./internal/http")
        print("PASS: concurrent weekly allowance, refund, week boundary and subscription entitlement")
        if (quota_source / 'internal/http/standing_test.go').exists():
            assert '--- PASS: TestOldJWTBookingStandingPostgres' in quota_tests.stdout
            assert '--- PASS: TestBookingStandingPostgresHTTP' in quota_tests.stdout
            assert '--- PASS: TestBookingStandingPostgresHTTP/schedule-writers' in quota_tests.stdout
            assert '--- PASS: TestStandingReconciliationPostgres' in quota_tests.stdout
            print('PASS: old signed JWT denied on two API instances, participant restrictions, pre-commit rollback, quota rollback, expired lock wait and protective cancellation during outage')
            print('PASS: post-event commit reconciliation, newer authorization survives delayed sanction, concurrent repairs, rollback/retry and bounded batches')
        if (quota_source / "internal/repo/standing_test.go").exists():
            print("PASS: standing booking effects, counterpart refund, rollback, duplicate concurrency and stale events")
    if quota_source.exists() and "match" in args.services:
        sql("fresh", "CREATE DATABASE standing_recovery;")
        flyway("standing_recovery", migration_dir)
        recovery_tests = run("docker", "run", "--rm", "--network", NAME,
            "--mount", f"type=bind,source={quota_source},target=/sources,readonly",
            "-v", "rac-quota-go-cache:/go/pkg/mod", "-v", "rac-match-go-build:/root/.cache/go-build",
            "-e", f"RAC_STANDING_RECOVERY_DATABASE_URL=postgres://postgres:test-only@{NAME}:5432/standing_recovery?sslmode=disable",
            "golang:1.27.2", "sh", "-c", "cp -a /sources /tmp/rac && cd /tmp/rac && go test -race -count=1 -v -run '^TestStandingRecoveryPostgresHTTP$' ./internal/events")
        assert '--- PASS: TestStandingRecoveryPostgresHTTP' in recovery_tests.stdout
        print('PASS: original-event recovery without broker, missed sanction followed by reversal, fresh authorization preserved, counterpart quota, outages, claim expiry/fencing and event gaps')
    chat_source = ROOT.parent / "rac-chat-service"
    if (chat_source / "internal/http/router_test.go").exists() and "chat" in args.services:
        run("docker", "run", "--rm", "--network", NAME,
            "--mount", f"type=bind,source={chat_source},target=/sources,readonly",
            "-v", "rac-quota-go-cache:/go/pkg/mod", "-v", "rac-chat-go-build:/root/.cache/go-build",
            "-e", f"RAC_CHAT_TEST_DATABASE_URL=postgres://postgres:test-only@{NAME}:5432/fresh?sslmode=disable",
            "-e", "RAC_CHAT_MIGRATED=1",
            "golang:1.27.2", "sh", "-c", "cp -a /sources /tmp/rac && cd /tmp/rac && go test -race -count=1 -v ./internal/http")
        print("PASS: private booking chat, idempotent concurrent messages, cursor pages and DB cancellation guard")
    sql("fresh", "CREATE DATABASE legacy;")
    onboarding_source = ROOT.parent / "rac-user-service"
    if onboarding_source.exists() and "user" in args.services:
        sql("fresh", "CREATE DATABASE session_effects;")
        flyway("session_effects", migration_dir)
        user_tests = run("docker", "run", "--rm", "--network", NAME,
            "--mount", f"type=bind,source={onboarding_source},target=/sources,readonly",
            "-v", "rac-quota-go-cache:/go/pkg/mod", "-v", "rac-user-go-build:/root/.cache/go-build",
            "-e", f"RAC_ONBOARDING_TEST_DATABASE_URL=postgres://postgres:test-only@{NAME}:5432/fresh?sslmode=disable",
            "-e", f"RAC_SESSION_TEST_DATABASE_URL=postgres://postgres:test-only@{NAME}:5432/session_effects?sslmode=disable",
            "-e", "RAC_SESSION_TEST_ISOLATED=1",
            "golang:1.27.2", "sh", "-c", "cp -a /sources /tmp/rac && cd /tmp/rac && go test -race -count=1 -v ./internal/http ./internal/sessioncontrol")
        assert '--- PASS: TestStandingSessionsPostgres' in user_tests.stdout
        print('PASS: durable session captures, ACK loss, reversal races, claim fencing and least-privilege journal')
        assert '--- PASS: TestCompaOnboardingTransaction' in user_tests.stdout
        assert '--- PASS: TestVerifiedReviews' in user_tests.stdout
        assert '--- PASS: TestProfileStandingProvisioning' in user_tests.stdout
        print("PASS: scoped user writes, standing guards, concurrent rollback, public visibility, reviews and protected reads")
    sql("legacy", (ROOT / "db/migrations/V001__initial_schema.sql").read_text())
    sql("legacy", "INSERT INTO usuario(id,nombre,correo,rol,keycloak_id) VALUES('00000000-0000-0000-0000-000000000001','Preservar','legacy@example.test','cliente','kc-legacy');")
    sql("legacy", "INSERT INTO compa_availability(compa_id,disponibilidad_json) VALUES('00000000-0000-0000-0000-000000000001','{\"lunes\":[\"18:00-20:00\"]}');")
    # Preserve and backfill real pre-outbox history, including text that exceeds
    # the new-message limit; V009 deliberately does not rewrite old content.
    sql("legacy", "INSERT INTO usuario(id,nombre,correo,rol,keycloak_id) VALUES('00000000-0000-0000-0000-000000000002','Companion','compa-legacy@example.test','compa','kc-legacy-compa');")
    sql("legacy", "INSERT INTO sesion(id,cliente_id,compa_id,fecha_inicio,fecha_fin,estado) VALUES('00000000-0000-0000-0000-000000000003','00000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000002',now(),now()+interval '1 hour','activa');")
    sql("legacy", "INSERT INTO mensaje(id,sesion_id,remitente_id,contenido) VALUES('00000000-0000-0000-0000-000000000004','00000000-0000-0000-0000-000000000003','00000000-0000-0000-0000-000000000001',repeat('x',2001));")
    flyway("legacy", migration_dir)
    assert sql("legacy", "SELECT char_length(contenido) FROM mensaje WHERE id='00000000-0000-0000-0000-000000000004';") == "2001"
    assert sql("legacy", "SELECT version FROM chat_outbox WHERE mensaje_id='00000000-0000-0000-0000-000000000004';") == "1"
    assert sql("legacy", "SELECT version FROM chat_cursor WHERE sesion_id='00000000-0000-0000-0000-000000000003';") == "1"
    assert sql("legacy", "SELECT nombre FROM usuario WHERE keycloak_id='kc-legacy';") == "Preservar"
    assert sql("legacy", "SELECT status||':'||version FROM standing.account WHERE subject_id='00000000-0000-0000-0000-000000000001';") == "active:1"
    assert sql("legacy", "SELECT zona_horaria FROM compa_availability;") == "UTC"
    assert sql("legacy", "SELECT disponibilidad_json->'lunes'->>0 FROM compa_availability;") == "18:00-20:00"
    assert sql("legacy", "SELECT count(*) FROM meta.schema_history WHERE success AND version IS NOT NULL;") == str(len(list(migration_dir.glob("V*.sql"))))
    # Upgrade actual V023 consumer data: preserve its event provenance instead
    # of manufacturing a reconciliation identity or losing the standing version.
    sql('fresh', 'CREATE DATABASE standing_upgrade;')
    with tempfile.TemporaryDirectory(prefix=NAME) as previous:
        for source in migration_dir.glob('V*.sql'):
            if int(source.name.split('__')[0][1:]) <= 23:
                shutil.copy2(source, Path(previous) / source.name)
        flyway('standing_upgrade', Path(previous))
    subject, event = str(uuid.uuid4()), str(uuid.uuid4())
    sql('standing_upgrade', f"INSERT INTO usuario(id,nombre,correo,rol,keycloak_id) VALUES('{subject}','Fixture','upgrade-standing@example.test','cliente','upgrade-standing');"
        f"INSERT INTO match_standing_inbox(event_id,subject_id,version,payload_hash) VALUES('{event}','{subject}',2,decode(repeat('00',32),'hex'));"
        f"INSERT INTO match_standing_projection(subject_id,version,status) VALUES('{subject}',2,'suspended');")
    flyway('standing_upgrade', migration_dir)
    assert sql('standing_upgrade', f"SELECT source_event_id::text||':'||version||':'||status FROM match_standing_projection WHERE subject_id='{subject}';") == event + ':2:suspended'
    assert sql('standing_upgrade', "SELECT reconciled_at='-infinity'::timestamptz FROM match_standing_projection;") == 't'
    assert sql('standing_upgrade', f"SELECT event_id::text||':'||version||':'||status FROM match_standing_sanction WHERE subject_id='{subject}';") == event + ':2:suspended'
    print('PASS: V023 projection upgrade retains authenticated event provenance and schedules repair')
    with tempfile.TemporaryDirectory(prefix=NAME) as temp:
        for src in migration_dir.glob("*.sql"): shutil.copy2(src, Path(temp)/src.name)
        with (Path(temp)/"V003__identity_indexes.sql").open("a") as f: f.write("\n-- drift must be rejected\n")
        assert flyway("fresh", Path(temp), "validate", ok=False).returncode != 0
    print("PASS: fresh, legacy adoption, data preservation, repeatability, checksum drift")
finally:
    run("docker", "rm", "-f", NAME, ok=False)
    run("docker", "network", "rm", NAME, ok=False)
