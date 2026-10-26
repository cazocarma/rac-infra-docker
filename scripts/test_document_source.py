"""Exercise the exact platform document SQL on a uniquely named disposable DB.
Requires the platform source checkout; never reads .env or the DEV database.
"""
from pathlib import Path
import json
import subprocess
import time
import uuid
from document_registry_checks import check

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT.parent / 'rac-platform/documents/postgres/source.go'
source = SOURCE.read_text(encoding='utf-8')
query = source.split('const snapshotSQL = `', 1)[1].split('`', 1)[0]
name = 'rac-doc-source-' + uuid.uuid4().hex[:12]

def run(*args, input=None, ok=True):
    result = subprocess.run(args, input=input, capture_output=True, text=True, timeout=300)
    if ok and result.returncode:
        raise RuntimeError(result.stderr[-2000:] + result.stdout[-2000:])
    return result

def execute(statement, ok=True):
    return run('docker','exec','-i',name,'psql','-X','-v','ON_ERROR_STOP=1',
               '-U','postgres','-d','fixture','-Atq',input=statement,ok=ok)

try:
    run('docker','network','create',name)
    run('docker','run','-d','--name',name,'--network',name,'--network-alias','postgres',
        '--tmpfs','/var/lib/postgresql/data','-e','POSTGRES_PASSWORD=test-only',
        '-e','POSTGRES_DB=fixture','postgis/postgis:16-3.4')
    for _ in range(60):
        if execute('SELECT 1;',ok=False).returncode == 0 and 'PostgreSQL init process complete' in run('docker','logs',name).stdout:
            break
        time.sleep(1)
    else:
        raise RuntimeError('Disposable database not ready')
    run('docker','run','--rm','--network',name,'--mount',
        f'type=bind,source={ROOT / "db/migrations"},target=/flyway/sql,readonly',
        '-e','FLYWAY_URL=jdbc:postgresql://postgres:5432/fixture',
        '-e','FLYWAY_USER=postgres','-e','FLYWAY_PASSWORD=test-only',
        '-e','FLYWAY_SCHEMAS=meta','-e','FLYWAY_DEFAULT_SCHEMA=meta',
        '-e','FLYWAY_TABLE=schema_history','flyway/flyway:11.15.0-alpine','migrate')
    check(lambda sql: execute(sql).stdout.strip(), lambda sql: execute(sql,ok=False).returncode != 0)
    subject, user = str(uuid.uuid4()), str(uuid.uuid4())
    execute(f"INSERT INTO usuario(id,nombre,correo,rol,keycloak_id) VALUES('{user}','Synthetic','source@example.test','cliente','{subject}');")
    def read(account, locale='es'):
        # Synthetic UUIDs and fixed locale only; PREPARE preserves the SQL's
        # parameter binding exactly rather than rewriting the tested statement.
        statement = 'SET ROLE rac_user; PREPARE snapshot(text,text) AS ' + query + '; '
        statement += f"EXECUTE snapshot('{account}','{locale}');"
        return execute(statement).stdout.strip()
    assert read(str(uuid.uuid4())) == ''
    result = read(subject).split('|', 6)
    assert result[0] == '3'
    docs, accepted = json.loads(result[5]), json.loads(result[6])
    assert len(docs) == 5 and accepted == []
    assert len({d['kind'] for d in docs}) == 5
    assert all(d['approved'] and len(d['hash']) == 64 and d['material'] for d in docs)
    doc = docs[0]
    execute(f"SET ROLE rac_user; INSERT INTO document_acceptances(user_id,document_id,context) VALUES('{user}','{doc['id']}','account');")
    accepted = json.loads(read(subject).split('|',6)[6])
    assert len(accepted) == 1 and accepted[0]['id'] == doc['id']
    assert accepted[0]['hash'] == doc['hash'] and accepted[0]['material'] == doc['material']
    terms = next(d for d in docs if d['kind'] == 'terms_client')
    assert terms['material'] != terms['id']
    execute(f"SET ROLE rac_user; INSERT INTO document_acceptances(user_id,document_id,context) VALUES('{user}','{terms['material']}','account');")
    accepted = json.loads(read(subject).split('|',6)[6])
    assert len(accepted) == 2 and any(a['id'] == terms['material'] for a in accepted)
    # Even several accepted nonmaterial revisions collapse to one proof per
    # active kind; an obsolete material lineage cannot authorize the new one.
    all_terms = execute("SELECT id FROM legal_documents WHERE kind='terms_client' AND locale='es' AND legal_review='approved' AND published_at<=now();").stdout.splitlines()
    for ident in all_terms:
        execute(f"SET ROLE rac_user; INSERT INTO document_acceptances(user_id,document_id,context) VALUES('{user}','{ident}','account') ON CONFLICT DO NOTHING;")
    assert len(json.loads(read(subject).split('|',6)[6])) == 2
    other = str(uuid.uuid4())
    execute(f"INSERT INTO usuario(id,nombre,correo,rol,keycloak_id) VALUES(gen_random_uuid(),'Synthetic other','other-source@example.test','cliente','{other}');")
    assert json.loads(read(other).split('|',6)[6]) == []
    assert len(json.loads(read(subject,'en').split('|',6)[5])) == 4
    print('PASS: exact owner SQL, active registry only, scoped role, subject isolation, hashes and material lineage')
finally:
    run('docker','rm','-f',name,ok=False)
    run('docker','network','rm',name,ok=False)
