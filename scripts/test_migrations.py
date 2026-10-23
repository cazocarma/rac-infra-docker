"""Fresh DB, legacy adoption, repeatability, integrity and checksum tests.

Only creates/removes uniquely named disposable Docker resources; never uses .env.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import uuid

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
    if quota_source.exists():
        run("docker", "run", "--rm", "--network", NAME,
            "--mount", f"type=bind,source={quota_source},target=/sources,readonly",
            "-v", "rac-quota-go-cache:/go/pkg/mod",
            "-e", f"RAC_QUOTA_TEST_DATABASE_URL=postgres://postgres:test-only@{NAME}:5432/fresh?sslmode=disable",
            "golang:1.27.2", "sh", "-c", "cp -a /sources /tmp/rac && cd /tmp/rac && go test -race -count=1 -v ./internal/repo")
        print("PASS: concurrent weekly allowance, refund, week boundary and subscription entitlement")
        if (quota_source / "internal/repo/standing_test.go").exists():
            print("PASS: standing booking effects, counterpart refund, rollback, duplicate concurrency and stale events")
    chat_source = ROOT.parent / "rac-chat-service"
    if (chat_source / "internal/http/router_test.go").exists():
        run("docker", "run", "--rm", "--network", NAME,
            "--mount", f"type=bind,source={chat_source},target=/sources,readonly",
            "-v", "rac-quota-go-cache:/go/pkg/mod", "-v", "rac-chat-go-build:/root/.cache/go-build",
            "-e", f"RAC_CHAT_TEST_DATABASE_URL=postgres://postgres:test-only@{NAME}:5432/fresh?sslmode=disable",
            "-e", "RAC_CHAT_MIGRATED=1",
            "golang:1.27.2", "sh", "-c", "cp -a /sources /tmp/rac && cd /tmp/rac && go test -race -count=1 -v ./internal/http")
        print("PASS: private booking chat, idempotent concurrent messages, cursor pages and DB cancellation guard")
    sql("fresh", "CREATE DATABASE legacy;")
    onboarding_source = ROOT.parent / "rac-user-service"
    if onboarding_source.exists():
        run("docker", "run", "--rm", "--network", NAME,
            "--mount", f"type=bind,source={onboarding_source},target=/sources,readonly",
            "-v", "rac-quota-go-cache:/go/pkg/mod", "-v", "rac-user-go-build:/root/.cache/go-build",
            "-e", f"RAC_ONBOARDING_TEST_DATABASE_URL=postgres://postgres:test-only@{NAME}:5432/fresh?sslmode=disable",
            "golang:1.27.2", "sh", "-c", "cp -a /sources /tmp/rac && cd /tmp/rac && go test -race -count=1 -v ./internal/http")
        print("PASS: free compa activation transaction, failure rollback, retry and input validation")
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
    with tempfile.TemporaryDirectory(prefix=NAME) as temp:
        for src in migration_dir.glob("*.sql"): shutil.copy2(src, Path(temp)/src.name)
        with (Path(temp)/"V003__identity_indexes.sql").open("a") as f: f.write("\n-- drift must be rejected\n")
        assert flyway("fresh", Path(temp), "validate", ok=False).returncode != 0
    print("PASS: fresh, legacy adoption, data preservation, repeatability, checksum drift")
finally:
    run("docker", "rm", "-f", NAME, ok=False)
    run("docker", "network", "rm", NAME, ok=False)
