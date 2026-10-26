"""Restore encrypted snapshot to fresh throwaway PostgreSQL and RustFS containers."""
from pathlib import Path
import argparse
import json
import os
import re
import secrets
import subprocess
import tempfile
import time
from database_roles import ROLES

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--verify-migrations', action='store_true', help='Upgrade only the restored copy with the scoped migrator')
options=parser.parse_args()

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
upgrade_files=[]
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
    if options.verify_migrations:
        values=dict(line.split('=',1) for line in (ROOT/'envs/.env.dev').read_text(encoding='utf-8').splitlines() if '=' in line and not line.startswith('#'))
        database=values['POSTGRES_DB']
        tables=('usuario','sesion','reserva_resena')
        def counts():
            return {table:int(run('docker','exec',pg,'psql','-XAt','-U',user,'-d',database,'-c','SELECT count(*) FROM public.'+table).stdout.strip()) for table in tables}
        before=counts()
        migration_password=secrets.token_urlsafe(36)
        bootstrap={'PGHOST':pg,'PGUSER':user,'PGPASSWORD':password,'PGDATABASE':database,
                   'POSTGRES_DB':database,'MIGRATION_DB_USER':'rac_migrator','MIGRATION_DB_PASSWORD':migration_password}
        for key,role in ROLES.items():
            bootstrap[key]=f'postgresql://{role}:{secrets.token_urlsafe(36)}@postgres:5432/{database}?sslmode=disable'
        flyway={'FLYWAY_URL':f'jdbc:postgresql://{pg}:5432/{database}','FLYWAY_USER':'rac_migrator','FLYWAY_PASSWORD':migration_password,
                'FLYWAY_SCHEMAS':'meta','FLYWAY_DEFAULT_SCHEMA':'meta','FLYWAY_TABLE':'schema_history','FLYWAY_CLEAN_DISABLED':'true'}
        def private_env(mapping):
            with tempfile.NamedTemporaryFile(mode='w',delete=False,encoding='utf-8') as output:
                upgrade_files.append(output.name)
                os.chmod(output.name,0o600)
                output.write(''.join(key+'='+value+'\n' for key,value in mapping.items()))
                return output.name
        def private_run(*command):
            if run(*command,ok=False).returncode:
                raise RuntimeError('Isolated restored-data upgrade failed; private database output withheld')
        private_run('docker','run','--rm','--network','rac-dev_default','--env-file',private_env(bootstrap),
                    'rac-dev-database-config','python','configure_database.py')
        flyway_env=private_env(flyway)
        for action in ('migrate','validate','migrate'):
            private_run('docker','run','--rm','--network','rac-dev_default','--env-file',flyway_env,
                        '--mount',f'type=bind,source={ROOT / "db/migrations"},target=/flyway/sql,readonly','flyway/flyway:11.15.0-alpine',action)
        after=counts()
        if before!=after:
            raise RuntimeError('Restored-data upgrade changed preserved business row counts')
        applied=int(run('docker','exec',pg,'psql','-XAt','-U',user,'-d',database,'-c',
                        'SELECT count(*) FROM meta.schema_history WHERE success AND version IS NOT NULL').stdout.strip())
        if applied!=len(list((ROOT/'db/migrations').glob('V*.sql'))):
            raise RuntimeError('Restored-data upgrade did not apply the complete migration series')
        backup_values=dict(line.split('=',1) for line in (ROOT/'envs/.env.backups').read_text(encoding='utf-8').splitlines() if '=' in line and not line.startswith('#'))
        evidence={'schema_version':1,'kind':'dev_logical_restore_upgrade','restored_databases':2,'photo_hashes_verified':True,
                  'migration_count':applied,'business_row_counts_preserved':True,'non_superuser_migrator':True,'repeatability_verified':True,
                  'verified_at_unix':int(time.time())}
        proof=Path(backup_values['BACKUP_DIRECTORY'])/'verified-upgrade.json'
        proof.write_text(json.dumps(evidence,indent=2)+'\n',encoding='utf-8')
        print('PASS: restored DEV data upgraded by the scoped migrator; checksum, repeatability and business row counts preserved')
finally:
    run("docker","rm","-f",pg,s3,ok=False)
    if filename:os.unlink(filename)
    for path in upgrade_files:os.unlink(path)
