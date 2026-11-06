"""P10 evidence registry boundary in a disposable database. Synthetic data only."""
import base64
import json
import uuid

CAPTURE = ('ts.evidence_ready()',
           'ts.evidence_prepare(audit.reference,audit.reference,audit.reference,jsonb)',
           'ts.evidence_commit(audit.reference,audit.reference,audit.reference,uuid,text,text,text)')
READ = ('ts.evidence_ready()', 'ts.evidence_open(audit.reference,audit.reference,audit.reference,uuid,text)')


def verify(sql, database):
    def execute(statement, role='postgres', ok=True):
        return sql(database, statement, role, ok=ok)

    for role, functions in (('rac_evidence_capture_fixture', CAPTURE), ('rac_evidence_reader_fixture', READ)):
        execute(f"DO $$BEGIN IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname='{role}') THEN CREATE ROLE {role} LOGIN; END IF; END$$;"
                f"GRANT USAGE ON SCHEMA ts,audit TO {role};"
                f"DO $$BEGIN EXECUTE format('GRANT CONNECT ON DATABASE %I TO {role}',current_database()); END$$;"
                + ''.join(f'GRANT EXECUTE ON FUNCTION {f} TO {role};' for f in functions)
                + "DO $$DECLARE c uuid; BEGIN IF NOT EXISTS(SELECT FROM audit.writer_principals WHERE database_role='"
                + role + "') THEN c:=gen_random_uuid(); INSERT INTO audit.chain_heads(chain_id) VALUES(c);"
                " INSERT INTO audit.writer_principals(database_role,actor_id,chain_id) VALUES('"
                + role + "',gen_random_uuid(),c); END IF; END$$;")

    capture, reader = 'rac_evidence_capture_fixture', 'rac_evidence_reader_fixture'
    actor, case, policy = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())

    def manifest(identifier, **changes):
        value = {'id': identifier, 'purpose': 'case_review', 'case_id': case, 'actor': actor,
                 'provenance': 'report_description', 'policy_version': 'evidence-fixture-1', 'media_type': 'text/plain',
                 'size': 21, 'sha256': 'a' * 64, 'key_id': 'fixture-kek-1',
                 'wrapped_key': base64.b64encode(b'w' * 60).decode(), 'cipher_sha256': 'b' * 64, 'cipher_size': 49,
                 'captured_at': '2099-01-01T00:00:00Z', 'retain_until': '2099-01-02T00:00:00Z'}
        value.update(changes)
        return json.dumps(value).replace("'", "''")

    def prepare(body, role=capture, ok=True):
        return execute(f"SELECT ts.evidence_prepare(gen_random_uuid(),'{actor}','{policy}','{body}');", role, ok)

    evidence = str(uuid.uuid4())
    now = execute("SELECT to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"');").stdout.strip()
    later = execute("SELECT to_char((clock_timestamp()+interval '2 days') AT TIME ZONE 'UTC','YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"');").stdout.strip()
    body = manifest(evidence, captured_at=now, retain_until=later)
    # Fail-closed: no policy is seeded, so nothing can be captured.
    assert prepare(body, ok=False).returncode != 0, 'Evidence captured without a registered retention policy'
    execute(f"INSERT INTO ts.evidence_retention_policies(version,purpose,max_days,registered_by) VALUES('evidence-fixture-1','case_review',7,'{actor}');")
    for role in ('rac_user', 'rac_match', 'rac_chat', 'rac_alert', reader):
        assert prepare(body, role, ok=False).returncode != 0, f'{role} could register evidence'
        assert execute('SELECT count(*) FROM ts.evidence_manifests;', role, ok=False).returncode != 0, f'{role} read raw manifests'
    for invalid in (manifest(evidence, captured_at=now, retain_until=later, purpose='appeal'),
                    manifest(evidence, captured_at=now, retain_until='2099-12-31T00:00:00Z'),
                    manifest(evidence, captured_at='2001-01-01T00:00:00Z', retain_until=later),
                    manifest(evidence, captured_at=now, retain_until=later, actor=str(uuid.uuid4())),
                    manifest(evidence, captured_at=now, retain_until=later, provenance='full_chat_export'),
                    json.dumps({'id': evidence})):
        assert prepare(invalid, ok=False).returncode != 0, 'Invalid manifest accepted'
    assert 'prepared' in prepare(body).stdout
    assert 'prepared' in prepare(body).stdout, 'Identical prepare replay rejected'
    assert prepare(manifest(evidence, captured_at=now, retain_until=later, sha256='c' * 64), ok=False).returncode != 0, 'Divergent prepare replay accepted'

    key = f'evidence/{evidence[:2]}/{evidence}.bin'

    def open_(role=reader, justification='case_review', ok=True):
        return execute(f"SELECT ts.evidence_open(gen_random_uuid(),'{actor}','{policy}','{evidence}','{justification}');", role, ok)

    # P11 AccessGuard: an unassigned reader is refused before any access row.
    assert open_(ok=False).returncode != 0, 'Unassigned reader opened evidence'
    execute(f"INSERT INTO ts.cases(id,subject,severity) VALUES('{case}',gen_random_uuid(),'P2');"
            f"INSERT INTO ts.case_assignments(case_id,assignee,assigned_by) VALUES('{case}','{actor}',gen_random_uuid());")
    assert open_().stdout.strip() == '', 'Prepared evidence returned a location'
    assert open_(justification='curiosity', ok=False).returncode != 0
    assert open_(capture, ok=False).returncode != 0, 'Capture login opened evidence'

    def commit(object_key=key, version='v1', who=actor, ok=True):
        return execute(f"SELECT ts.evidence_commit(gen_random_uuid(),'{who}','{policy}','{evidence}','rac-evidence-fixture','{object_key}','{version}');", capture, ok)

    assert commit(who=str(uuid.uuid4()), ok=False).returncode != 0, 'Another actor completed the capture'
    assert commit(object_key='evidence/xx/other.bin', ok=False).returncode != 0, 'Unbound object key accepted'
    assert 'stored' in commit().stdout
    assert 'stored' in commit().stdout, 'Exact commit replay rejected'
    assert commit(version='v2', ok=False).returncode != 0, 'Stored evidence re-pointed to another version'
    opened = json.loads(open_().stdout)
    assert opened['location'] == {'bucket': 'rac-evidence-fixture', 'key': key, 'version_id': 'v1'}
    assert base64.b64decode(opened['wrapped_key']) == b'w' * 60 and opened['sha256'] == 'a' * 64
    # History is append-only even for the schema owner.
    for statement in (f"UPDATE ts.evidence_manifests SET retain_until=retain_until-interval '1 day' WHERE id='{evidence}';",
                      f"DELETE FROM ts.evidence_manifests WHERE id='{evidence}';",
                      'DELETE FROM ts.evidence_access_events;',
                      "UPDATE ts.evidence_retention_policies SET max_days=3650;"):
        assert execute(statement, ok=False).returncode != 0, 'Evidence history mutated: ' + statement
    counts = execute(f"SELECT (SELECT count(*) FROM ts.evidence_access_events WHERE evidence_id='{evidence}')||':'||"
                     f"(SELECT count(*) FROM audit.log WHERE resource_id='{evidence}' AND action='evidence.accessed')||':'||"
                     f"(SELECT count(*) FROM audit.log WHERE resource_id='{evidence}' AND action='evidence.captured' AND case_id='{case}');").stdout.strip()
    assert counts == '2:2:2', 'Access/capture not audited exactly: ' + counts
    execute(f"UPDATE ts.evidence_retention_policies SET retired_at=clock_timestamp() WHERE version='evidence-fixture-1';")
    assert prepare(manifest(str(uuid.uuid4()), captured_at=now, retain_until=later), ok=False).returncode != 0, 'Retired policy accepted'
    print('PASS: P10 evidence registry fails closed without policy, owner-only function capture, exact-version commit, '
          'append-only history, audited access before reveal and no customer-service authority', flush=True)
