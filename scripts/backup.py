"""Encrypted, consistent DEV DB + referenced photos backups, and isolated restore verification."""
from pathlib import Path
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time

import boto3
import psycopg
from botocore.config import Config

ROOT=Path("/backups")
STATUS=ROOT/"status.json"
WORK=Path("/work/snapshot")
KEY=re.compile(r"[a-f0-9]{32}\.jpg")
TABLES=("usuario","sesion","reserva_resena")

def command(args,env=None):
    result=subprocess.run(args,env=env,capture_output=True,timeout=600)
    if result.returncode:
        raise RuntimeError("backup command failed: "+args[0]+" (exit "+str(result.returncode)+")")
    return result.stdout

def restic(*args):
    return command(["restic",*args])

def client(endpoint,access,secret):
    return boto3.client("s3",endpoint_url=endpoint,region_name="us-east-1",aws_access_key_id=access,aws_secret_access_key=secret,config=Config(signature_version="s3v4",s3={"addressing_style":"path"},connect_timeout=5,read_timeout=15,retries={"max_attempts":2}))

def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source,"sha256").hexdigest()

def status(**values):
    previous=json.loads(STATUS.read_text()) if STATUS.exists() else {}
    previous.update(values)
    temp=STATUS.with_suffix(".tmp");temp.write_text(json.dumps(previous));os.replace(temp,STATUS)

def backup():
    ROOT.mkdir(parents=True,exist_ok=True)
    with (ROOT/"job.lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if WORK.exists():shutil.rmtree(WORK)
        (WORK/"photos").mkdir(parents=True,mode=0o700)
        started=time.time()
        s3=client(os.environ["BACKUP_S3_ENDPOINT"],os.environ["BACKUP_S3_ACCESS_KEY"],os.environ["BACKUP_S3_SECRET_KEY"])
        bucket=os.environ["BACKUP_S3_BUCKET"]
        # Acquire before beginning the repeatable-read snapshot, so a lock wait
        # cannot accidentally export a view older than a completed photo change.
        with psycopg.connect(autocommit=True) as db:
            db.execute("SET lock_timeout='30s'")
            db.execute("SET idle_in_transaction_session_timeout='120s'")
            db.execute("SELECT pg_advisory_lock(726224,1)")
            try:
                with db.transaction():
                    db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                    snapshot=db.execute("SELECT pg_export_snapshot()").fetchone()[0]
                    command(["pg_dump","--format=custom","--snapshot",snapshot,"--file",str(WORK/"app.dump")])
                    refs=[row[0] for row in db.execute("SELECT foto_clave FROM public.usuario WHERE foto_clave IS NOT NULL")]
                    counts={table:db.execute("SELECT count(*) FROM public."+table).fetchone()[0] for table in TABLES}
                    for key in refs:
                        if not KEY.fullmatch(key):raise RuntimeError("invalid referenced photo")
                        response=s3.get_object(Bucket=bucket,Key=key)
                        try:raw=response["Body"].read(5*1024*1024+1)
                        finally:response["Body"].close()
                        if len(raw)>5*1024*1024:raise RuntimeError("oversized backup object")
                        (WORK/"photos"/key).write_bytes(raw)
            finally:
                db.execute("SELECT pg_advisory_unlock(726224,1)")
        # Keycloak is an independent database: its own internally consistent dump.
        command(["pg_dump","--dbname=keycloak","--format=custom","--file",str(WORK/"keycloak.dump")])
        (WORK/"globals.sql").write_bytes(command(["pg_dumpall","--globals-only"]))
        files={str(path.relative_to(WORK)):digest(path) for path in WORK.rglob("*") if path.is_file()}
        manifest={"version":1,"snapshot_at":started,"bucket":bucket,"database":os.environ["PGDATABASE"],"counts":counts,"files":files,"photos":refs}
        (WORK/"manifest.json").write_text(json.dumps(manifest))
        if not (ROOT/"repository/config").exists():restic("init")
        restic("backup",str(WORK),"--host","rac-dev","--tag","rac-consistent")
        restic("check")
        restic("forget","--host","rac-dev","--tag","rac-consistent","--keep-daily","7","--keep-weekly","4","--keep-monthly","3","--prune")
        restic("check")
        status(last_success=time.time(),snapshot_at=started,last_error=None,photo_count=len(refs))
        shutil.rmtree(WORK)
        print(json.dumps({"event":"backup_success","photos":len(refs)}),flush=True)

def restore_test():
    host=os.environ["RESTORE_PG_HOST"]
    endpoint=os.environ["RESTORE_S3_ENDPOINT"]
    if not re.fullmatch(r"rac-restore-test-db-[a-f0-9]{16}",host) or not re.fullmatch(r"http://rac-restore-test-s3-[a-f0-9]{16}:9000",endpoint):
        raise RuntimeError("Restore allowed only against disposable test hosts")
    dest=Path("/work/restore")
    if dest.exists():shutil.rmtree(dest)
    restic("restore","latest","--host","rac-dev","--tag","rac-consistent","--target",str(dest))
    base=dest/"work/snapshot"
    manifest=json.loads((base/"manifest.json").read_text())
    if manifest["version"]!=1:raise RuntimeError("Unsupported backup manifest")
    if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]{0,62}",manifest["database"]):raise RuntimeError("Invalid restored database name")
    for name,expected in manifest["files"].items():
        path=base/name
        if not path.resolve().is_relative_to(base.resolve()) or digest(path)!=expected:
            raise RuntimeError("Restored file hash mismatch")
    env={**os.environ,"PGHOST":host,"PGUSER":os.environ["RESTORE_PG_USER"],"PGPASSWORD":os.environ["RESTORE_PG_PASSWORD"],"PGDATABASE":"postgres"}
    command(["psql","--set","ON_ERROR_STOP=on","--file",str(base/"globals.sql")],env)
    for name,archive in [(manifest["database"],"app.dump"),("keycloak","keycloak.dump")]:
        command(["createdb",name],env)
        command(["pg_restore","--exit-on-error","--dbname",name,str(base/archive)],env)
    with psycopg.connect(host=host,user=env["PGUSER"],password=env["PGPASSWORD"],dbname=manifest["database"]) as db:
        for table in TABLES:
            if db.execute("SELECT count(*) FROM public."+table).fetchone()[0]!=manifest["counts"][table]:
                raise RuntimeError("Restored database count mismatch")
        refs=[row[0] for row in db.execute("SELECT foto_clave FROM public.usuario WHERE foto_clave IS NOT NULL")]
    if set(refs)!=set(manifest["photos"]):raise RuntimeError("Restored references differ")
    s3=client(endpoint,os.environ["RESTORE_S3_ACCESS_KEY"],os.environ["RESTORE_S3_SECRET_KEY"])
    bucket=manifest["bucket"];s3.create_bucket(Bucket=bucket)
    for key in refs:
        if not KEY.fullmatch(key):raise RuntimeError("Invalid restored key")
        raw=(base/"photos"/key).read_bytes()
        s3.put_object(Bucket=bucket,Key=key,Body=raw,ContentType="image/jpeg")
        response=s3.get_object(Bucket=bucket,Key=key)
        try:actual=response["Body"].read()
        finally:response["Body"].close()
        if hashlib.sha256(actual).hexdigest()!=manifest["files"]["photos/"+key]:raise RuntimeError("Restored object mismatch")
    print(json.dumps({"event":"restore_test_success","photos":len(refs),"databases":2}),flush=True)

def health():
    data=json.loads(STATUS.read_text())
    if data.get("last_error") or time.time()-data.get("last_success",0)>93600:raise RuntimeError("No healthy recent backup")

def schedule():
    while True:
        try:
            data=json.loads(STATUS.read_text()) if STATUS.exists() else {}
            due=data.get("last_success",0)+86400
            if data.get("last_error") or time.time()>=due:
                backup()
            time.sleep(60)
        except Exception as error:
            if isinstance(error,BlockingIOError):
                print('{"event":"backup_already_running"}',flush=True)
                time.sleep(60)
                continue
            reason=str(error) if isinstance(error,RuntimeError) else type(error).__name__
            status(last_error=reason,last_attempt=time.time())
            print(json.dumps({"event":"backup_failed","reason":reason}),flush=True)
            time.sleep(300)

if __name__=="__main__":
    try:
        {"once":backup,"schedule":schedule,"health":health,"restore-test":restore_test}[sys.argv[1] if len(sys.argv)>1 else "schedule"]()
    except Exception as error:
        if len(sys.argv)>1 and sys.argv[1]=="once" and not isinstance(error,BlockingIOError):
            status(last_error="backup_failed",last_attempt=time.time())
        print(json.dumps({"event":"backup_command_failed","type":type(error).__name__,"reason":str(error) if isinstance(error,RuntimeError) else "operation failed"}),flush=True)
        sys.exit(1)
