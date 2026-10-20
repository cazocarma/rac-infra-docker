"""Actual S3 + disposable Postgres tests; never uses the development database."""
from pathlib import Path
import os
import subprocess
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
name = "rac-photo-test-"+uuid.uuid4().hex[:12]
network = "rac-dev-storage_default"
credentials = dict(line.split("=",1) for line in (ROOT/"envs/.env.storage").read_text(encoding="utf-8").splitlines() if "=" in line and not line.startswith("#"))

def run(*args,ok=True):
    result = subprocess.run(list(args),cwd=ROOT,capture_output=True,text=True)
    if ok and result.returncode:
        # Commands never contain application secrets; SDK errors are not logged by handlers.
        raise RuntimeError(result.stdout[-5000:]+result.stderr[-3000:])
    return result

filename = None
try:
    run("docker","run","-d","--name",name,"--network",network,"--tmpfs","/var/lib/postgresql/data","-e","POSTGRES_PASSWORD=test-only","-e","POSTGRES_DB=photos","postgis/postgis:16-3.4")
    for _ in range(60):
        logs = run("docker","logs",name).stdout
        if "PostgreSQL init process complete" in logs and run("docker","exec",name,"pg_isready","-U","postgres",ok=False).returncode==0:
            break
        time.sleep(1)
    else:
        raise RuntimeError("Disposable photo database did not start")
    run("docker","run","--rm","--network",network,"--mount",f"type=bind,source={ROOT/'db/migrations'},target=/flyway/sql,readonly","-e",f"FLYWAY_URL=jdbc:postgresql://{name}:5432/photos","-e","FLYWAY_USER=postgres","-e","FLYWAY_PASSWORD=test-only","-e","FLYWAY_SCHEMAS=meta","-e","FLYWAY_DEFAULT_SCHEMA=meta","flyway/flyway:11.15.0-alpine","migrate")
    env = {key:credentials[key] for key in ("PROFILE_S3_BUCKET","PROFILE_S3_ACCESS_KEY","PROFILE_S3_SECRET_KEY")}
    env["RAC_PHOTO_TEST_S3_ENDPOINT"] = "http://rustfs:9000"
    env["RAC_ONBOARDING_TEST_DATABASE_URL"] = f"postgres://postgres:test-only@{name}:5432/photos?sslmode=disable"
    with tempfile.NamedTemporaryFile(mode="w",delete=False,encoding="utf-8") as output:
        filename = output.name
        output.write("".join(key+"="+value+"\n" for key,value in env.items()))
    result=run("docker","run","--rm","--network",network,"--mount",f"type=bind,source={ROOT.parent/'rac-user-service'},target=/sources,readonly","--env-file",filename,"-v","rac-quota-go-cache:/go/pkg/mod","-v","rac-user-go-build:/root/.cache/go-build","golang:1.27.2","sh","-c","cp -a /sources /tmp/rac && cd /tmp/rac && go test -race -count=1 -v ./internal/http ./cmd/migrate-photos")
    print(result.stdout[-6000:])
    print("PASS private/public photo API and verified migration against real RustFS + disposable database")
finally:
    run("docker","rm","-f",name,ok=False)
    if filename:
        os.unlink(filename)
