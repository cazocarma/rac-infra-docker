"""Exercise V018 in disposable PostgreSQL: permissions, rollback, concurrency,
idempotence and independent canonical hash verification. Never reads .env or
connects to the development database. Optional Go CLI cross-check uses a sibling
rac-platform checkout, but CI SQL verification has no private-repo dependency.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
ZERO = '0' * 64
CHAIN = '11111111-1111-4111-8111-111111111111'
ACTOR = '33333333-3333-4333-8333-333333333333'
RESOURCE = '44444444-4444-4444-8444-444444444444'
POLICY = '55555555-5555-4555-8555-555555555555'
WRITER = 'rac_audit_test_writer'
READER = 'rac_audit_test_reader'


def run(*args, input=None, ok=True):
    p = subprocess.run(args, input=input, text=True, capture_output=True, timeout=240)
    if ok and p.returncode:
        # Test environment only, but never print the SQL/input/export body.
        raise RuntimeError(f'command failed: {args[0]} (exit {p.returncode})\n{p.stderr[-1500:]}')
    return p


def canonical(record):
    keys = ('chain_id', 'sequence', 'event_id', 'occurred_at', 'actor_id',
            'action', 'resource_id', 'purpose', 'policy_version', 'case_id', 'previous_hash')
    return json.dumps(['rac.audit.v1'] + [str(record[k]) for k in keys], separators=(',', ':')).encode()


def verify(records, head):
    sequence, previous = 0, ZERO
    for record in records:
        if record['chain_id'] != CHAIN or record['sequence'] != sequence + 1 or record['previous_hash'] != previous:
            return False
        if record['hash'] != hashlib.sha256(canonical(record)).hexdigest():
            return False
        sequence, previous = record['sequence'], record['hash']
    return {'chain_id': CHAIN, 'sequence': sequence, 'hash': previous} == head


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--go-check', action='store_true', help='also verify export using sibling rac-platform CLI')
    args = parser.parse_args()
    name = 'rac-audit-test-' + uuid.uuid4().hex[:12]

    def sql(statement, user='postgres', ok=True):
        return run('docker', 'exec', '-i', name, 'psql', '-X', '-v', 'ON_ERROR_STOP=1',
                   '-U', user, '-d', 'audit_test', '-Atq', input=statement, ok=ok)

    def append(event, purpose='operational', ok=True):
        return sql(f"SELECT (audit.append('{event}','policy.published','{RESOURCE}','{purpose}','{POLICY}')).sequence;", WRITER, ok)

    try:
        run('docker', 'run', '-d', '--name', name, '--tmpfs', '/var/lib/postgresql/data',
            '-e', 'POSTGRES_PASSWORD=test-only', '-e', 'POSTGRES_DB=audit_test', 'postgres:16.11-alpine')
        for _ in range(60):
            if sql('SELECT 1;', ok=False).returncode == 0 and 'PostgreSQL init process complete' in run('docker', 'logs', name).stdout:
                break
            time.sleep(1)
        else:
            raise RuntimeError('disposable PostgreSQL did not start')
        sql('CREATE EXTENSION pgcrypto;')
        sql((ROOT / 'db/migrations/V018__audit_foundation.sql').read_text(encoding='utf-8'))
        # Local trust authentication exists only inside the disposable container;
        # these logins are never created in a shared cluster or exposed port.
        sql(f"""
            CREATE ROLE {WRITER} LOGIN IN ROLE rac_audit_writer;
            CREATE ROLE {READER} LOGIN IN ROLE rac_audit_reader;
            CREATE ROLE rac_audit_unmapped LOGIN IN ROLE rac_audit_writer;
            INSERT INTO audit.chain_heads(chain_id) VALUES('{CHAIN}');
            INSERT INTO audit.writer_principals VALUES('{WRITER}','{ACTOR}','{CHAIN}');
        """)
        event = str(uuid.uuid4())
        assert append(event).stdout.strip() == '1'
        assert append(event).stdout.strip() == '1', 'idempotent retry appended twice'
        assert append(event, 'security', ok=False).returncode != 0, 'conflicting retry accepted'
        assert sql('SELECT count(*) FROM audit.log;', READER).stdout.strip() == '1'
        assert sql('SELECT count(*) FROM audit.log;', WRITER, ok=False).returncode != 0
        for user in (WRITER, READER):
            for statement in (
                "UPDATE audit.log SET purpose='security';", 'DELETE FROM audit.log;', 'TRUNCATE audit.log;',
                'DROP TABLE audit.log;', 'INSERT INTO audit.log SELECT * FROM audit.log;',
                f"UPDATE audit.chain_heads SET hash='{ZERO}';",
                f"INSERT INTO audit.writer_principals VALUES('spoof','{ACTOR}','{CHAIN}');",
                'CREATE TABLE audit.bypass(id integer);',
            ):
                assert sql(statement, user, ok=False).returncode != 0, 'audit privileges too broad'
        for user in (READER, 'rac_audit_unmapped'):
            assert sql(f"SELECT audit.append('{uuid.uuid4()}','policy.published','{RESOURCE}','operational','{POLICY}');", user, ok=False).returncode != 0
        assert append(str(uuid.uuid4()), 'canary@example.test', ok=False).returncode != 0
        assert sql(f"SELECT audit.append('{uuid.uuid4()}','policy.published',NULL,'operational','{POLICY}');", WRITER, ok=False).returncode != 0
        rollback_id = str(uuid.uuid4())
        sql(f"BEGIN; SELECT audit.append('{rollback_id}','policy.published','{RESOURCE}','operational','{POLICY}'); ROLLBACK;", WRITER)
        assert sql('SELECT sequence FROM audit.chain_heads;').stdout.strip() == '1', 'rollback moved head'
        assert append(rollback_id).stdout.strip() == '2', 'rollback left a sequence gap'
        events = [str(uuid.uuid4()) for _ in range(16)]
        with ThreadPoolExecutor(max_workers=8) as pool:
            sequences = list(pool.map(lambda eid: int(append(eid).stdout.strip()), events))
        assert sorted(sequences) == list(range(3, 19)), 'concurrent append lost sequence'
        duplicate = str(uuid.uuid4())
        with ThreadPoolExecutor(max_workers=8) as pool:
            retries = list(pool.map(lambda _: append(duplicate).stdout.strip(), range(8)))
        assert retries == ['19'] * 8, 'concurrent retry not idempotent'

        def export():
            rows = sql("""SELECT json_build_object('version',version,'chain_id',chain_id,'sequence',sequence,
                'event_id',event_id,'occurred_at',to_char(occurred_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
                'actor_id',actor_id,'action',action,'resource_id',resource_id,'purpose',purpose,
                'policy_version',policy_version,'case_id',coalesce(case_id::text,''),
                'previous_hash',previous_hash,'hash',hash) FROM audit.log ORDER BY sequence;""", READER).stdout
            return [json.loads(line) for line in rows.splitlines()]

        records = export()
        head = json.loads(sql('SELECT row_to_json(h) FROM audit.chain_heads h;', READER).stdout)
        assert verify(records, head), 'SQL canonicalization differs from independent verifier'
        # Canonical SQL/Go golden vector, including exact timestamp precision.
        expected = '["rac.audit.v1","11111111-1111-4111-8111-111111111111","1","22222222-2222-4222-8222-222222222222","2026-10-22T12:00:00.123456Z","33333333-3333-4333-8333-333333333333","policy.published","44444444-4444-4444-8444-444444444444","operational","55555555-5555-4555-8555-555555555555","","' + ZERO + '"]'
        actual = sql(f"SELECT audit.canonical_v1('{CHAIN}',1,'22222222-2222-4222-8222-222222222222','2026-10-22T12:00:00.123456Z','{ACTOR}','policy.published','{RESOURCE}','operational','{POLICY}','00000000-0000-0000-0000-000000000000','{ZERO}');").stdout.strip()
        assert actual == expected, 'SQL golden bytes differ'
        assert not verify(records[:-1], head), 'truncated final record accepted'
        assert not verify(list(reversed(records)), head), 'reordered records accepted'
        sql("UPDATE audit.log SET purpose='security' WHERE sequence=1;")  # simulate compromised DBA
        assert not verify(export(), head), 'DBA edit undetected'
        sql("UPDATE audit.log SET purpose='operational' WHERE sequence=1;")
        sql('DELETE FROM audit.log WHERE sequence=19;')
        assert not verify(export(), head), 'DBA tail deletion undetected against trusted head'

        if args.go_check:
            module = ROOT.parent / 'rac-platform'
            if not (module / 'go.mod').exists():
                raise RuntimeError('rac-platform checkout required for --go-check')
            # Head files and export contain synthetic metadata only. They live
            # in the disposable container; no production signing key is used.
            from_head = {'chain_id': CHAIN, 'sequence': 0, 'hash': ZERO}
            import tempfile
            with tempfile.TemporaryDirectory(prefix='rac-audit-export-') as temp:
                path = Path(temp)
                (path / 'from.json').write_text(json.dumps(from_head))
                (path / 'to.json').write_text(json.dumps(head))
                command = ('docker', 'run', '--rm', '-i', '--mount', f'type=bind,source={module},target=/src,readonly',
                           '--mount', f'type=bind,source={path},target=/bounds,readonly', '-w', '/src',
                           'golang:1.27.2', 'go', 'run', './cmd/rac-audit', 'verify', '--from', '/bounds/from.json', '--to', '/bounds/to.json')
                run(*command, input='\n'.join(json.dumps(r) for r in records))
                assert run(*command, input='\n'.join(json.dumps(r) for r in records[:-1]), ok=False).returncode != 0
        print('PASS: append permissions, authenticated service identity, idempotence, rollback, concurrent chain, canonical parity, tampering and truncation')
    finally:
        run('docker', 'rm', '-f', name, ok=False)


if __name__ == '__main__':
    main()
