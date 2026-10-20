"""Restore encrypted snapshot to fresh throwaway PostgreSQL and RustFS containers."""
from pathlib import Path
import os
import re
import secrets
import subprocess
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
suffix=secrets.token_hex(8)
pg="rac-restore-test-db-"+suffix
s3="rac-restore-test-s3-"+suffix
user="restore_test_"+suffix
password=secrets.token_urlsafe(32)
access=secrets.token_hex(12)
secret=secrets.token_urlsafe(32)
compose=["docker","compose","--env-file","envs/.env.dev","--env-file","envs/.env.backups","-p","rac-dev","-f","compose.yaml","-f","docker-compose.dev.yaml","-f","compose.photos-s3.yaml","-f","compose.backups.yaml"]
image=re.search(r"image: (rustfs/rustfs:[^\s]+)",(ROOT/"compose.storage.yaml").read_text(encoding="utf-8")).group(1)

def run(*args,ok=True,env=None):
    result=subprocess.run(list(args),cwd=ROOT,capture_output=True,text=True,env=env)
    if ok and result.returncode:raise RuntimeError(result.stdout[-2500:]+result.stderr[-1500:])
    return result

filename=None
try:
    with tempfile.NamedTemporaryFile(mode="w",delete=False,encoding="utf-8") as output:
        filename=output.name
        output.write("POSTGRES_USER="+user+"\nPOSTGRES_PASSWORD="+password+"\nRUSTFS_ACCESS_KEY="+access+"\nRUSTFS_SECRET_KEY="+secret+"\nRUSTFS_CONSOLE_ENABLE=false\n")
    run("docker","run","-d","--name",pg,"--network","rac-dev_default","--tmpfs","/var/lib/postgresql/data","--env-file",filename,"postgis/postgis:16-3.4")
    run("docker","run","-d","--name",s3,"--network","rac-dev_default","--tmpfs","/data:uid=10001,gid=10001,mode=0700","--tmpfs","/logs:uid=10001,gid=10001,mode=0700","--env-file",filename,image)
    for _ in range(90):
        ready="PostgreSQL init process complete" in run("docker","logs",pg).stdout
        if ready and run("docker","exec",pg,"pg_isready","-U",user,ok=False).returncode==0 and run("docker","exec",s3,"curl","-fsS","http://localhost:9000/health",ok=False).returncode==0:break
        time.sleep(1)
    else:raise RuntimeError("Disposable restore services unavailable")
    env={**os.environ,"RESTORE_PG_HOST":pg,"RESTORE_PG_USER":user,"RESTORE_PG_PASSWORD":password,"RESTORE_S3_ENDPOINT":"http://"+s3+":9000","RESTORE_S3_ACCESS_KEY":access,"RESTORE_S3_SECRET_KEY":secret}
    args=compose+["run","--rm","--no-deps"]
    for key in ("RESTORE_PG_HOST","RESTORE_PG_USER","RESTORE_PG_PASSWORD","RESTORE_S3_ENDPOINT","RESTORE_S3_ACCESS_KEY","RESTORE_S3_SECRET_KEY"):args += ["-e",key]
    print(run(*args,"backups","restore-test",env=env).stdout)
    print("PASS encrypted backup restored: roles, both databases, row counts and S3 photo hashes")
finally:
    run("docker","rm","-f",pg,s3,ok=False)
    if filename:os.unlink(filename)
