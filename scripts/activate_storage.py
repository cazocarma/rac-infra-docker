"""DEV-only, explicit copy/verify and storage cutover. Never removes source."""
from pathlib import Path
import os
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE = ["docker","compose","--env-file","envs/.env.dev","-p","rac-dev","-f","compose.yaml","-f","docker-compose.dev.yaml","-f","compose.observability.yaml","-f","compose.tests.yaml"]
STORAGE = ["docker","compose","--env-file","envs/.env.storage","-p","rac-dev-storage","-f","compose.storage.yaml"]
dev = dict(line.split("=",1) for line in (ROOT/"envs/.env.dev").read_text(encoding="utf-8").splitlines() if "=" in line and not line.startswith("#"))
if dev.get("RAC_ENV") != "dev":
    raise RuntimeError("Storage activation requires RAC_ENV=dev")
active = ROOT/"envs/.env.photos-s3"
pending = ROOT/"envs/.env.photos-s3.pending"

def run(command):
    subprocess.run(command,cwd=ROOT,check=True)

run(STORAGE+["up","-d","--wait","--wait-timeout","180","rustfs"])
run(STORAGE+["run","--rm","--build","storage-config"])
values = dict(line.split("=",1) for line in (ROOT/"envs/.env.storage").read_text(encoding="utf-8").splitlines() if "=" in line and not line.startswith("#"))
config = {"PROFILE_PHOTO_STORAGE":"s3","PROFILE_S3_ENDPOINT":"http://rustfs:9000","PROFILE_S3_REGION":"us-east-1"}
for key in ("PROFILE_S3_ACCESS_KEY","PROFILE_S3_SECRET_KEY","PROFILE_S3_BUCKET"):
    config[key] = values[key]
if active.exists():
    current = dict(line.split("=",1) for line in active.read_text(encoding="utf-8").splitlines() if "=" in line)
    if current != config:
        raise RuntimeError("Existing activation differs; explicit credential rotation required")
    run(BASE+["-f","compose.photos-s3.yaml","up","-d","--no-deps","--wait","--wait-timeout","120","backend-user"])
    print("S3 already activated; existing objects preserved.")
else:
    descriptor = os.open(pending,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(descriptor,"w",encoding="utf-8") as output:
        output.write("".join(key+"="+value+"\n" for key,value in config.items()))
    run(BASE+["build","backend-user"])
    run(BASE+["stop","backend-user"])
    try:
        run(BASE+["-f","compose.photo-migration.yaml","run","--rm","migrate-photos"])
    except subprocess.CalledProcessError:
        run(BASE+["up","-d","--no-deps","backend-user"])
        raise RuntimeError("Migration failed; original local storage retained") from None
    os.replace(pending,active)
    # After cutover, never silently fall back to a stale local copy.
    run(BASE+["-f","compose.photos-s3.yaml","up","-d","--no-deps","--wait","--wait-timeout","120","backend-user"])
    print("PASS profile photos activated on private S3; original volume preserved.")
