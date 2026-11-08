"""P11 customer report intake: subject resolved by the owner, never the caller.

Synthetic data only. Uses a function-only intake login with exactly the two
customer entry points, as provisioned by ts_database.py.
"""
import json
import uuid

ROLE = 'rac_ts_customer_fixture'
REF = 'audit.reference,audit.reference,audit.reference'
FUNCTIONS = (f'ts.report_receive({REF},text,uuid,text)', f'ts.appeal_submit({REF},uuid,uuid)')


def verify(sql, database):
    def execute(statement, role='postgres', ok=True):
        return sql(database, statement, role, ok=ok)

    execute(f"DO $$BEGIN IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname='{ROLE}') THEN CREATE ROLE {ROLE} LOGIN; END IF; END$$;"
            f"DO $$BEGIN EXECUTE format('GRANT CONNECT ON DATABASE %I TO {ROLE}',current_database()); END$$;"
            f"GRANT USAGE ON SCHEMA ts,audit TO {ROLE};" + ''.join(f'GRANT EXECUTE ON FUNCTION {f} TO {ROLE};' for f in FUNCTIONS)
            + f"DO $$DECLARE c uuid; BEGIN IF NOT EXISTS(SELECT FROM audit.writer_principals WHERE database_role='{ROLE}') THEN"
            " c:=gen_random_uuid(); INSERT INTO audit.chain_heads(chain_id) VALUES(c);"
            f" INSERT INTO audit.writer_principals(database_role,actor_id,chain_id) VALUES('{ROLE}',gen_random_uuid(),c); END IF; END$$;")
    policy = str(uuid.uuid4())

    def compa(principal=None, publish=True):
        account, principal = str(uuid.uuid4()), principal or str(uuid.uuid4())
        execute(f"INSERT INTO usuario(id,nombre,correo,rol,keycloak_id) VALUES('{account}','Fixture','{account}@example.test','compa','{principal}');", 'rac_user')
        profile = execute(f"INSERT INTO compa_perfil(id,usuario_id,descripcion,tarifa_hora) VALUES(gen_random_uuid(),'{account}','Intake fixture',12000) RETURNING id;", 'rac_user').stdout.strip()
        listing = execute(f"INSERT INTO listings(compa_id) VALUES('{profile}') RETURNING id;", 'rac_user').stdout.strip()
        payload = json.dumps({'display_name': 'Synthetic', 'description': 'Intake fixture'}, separators=(',', ':'))
        revision = execute(f"INSERT INTO listing_revisions(listing_id,revision_no,payload_canonical,assessment,risk_score,policy_version) VALUES('{listing}',1,'{payload}','{{\"unevaluated\":[\"minors\"]}}',0,'fixture-1') RETURNING id;", 'rac_user').stdout.strip()
        execute(f"UPDATE listings SET pending_revision_id='{revision}',version=version+1 WHERE id='{listing}';", 'rac_user')
        if publish:
            execute(f"BEGIN;INSERT INTO listing_revision_decisions(revision_id,action,reviewer_subject,reason_code,note_to_user_key) VALUES('{revision}','approved','staff-fixture','fixture_reason','listingApproved');"
                    f"UPDATE listings SET state='published',published_revision_id='{revision}',pending_revision_id=NULL,version=version+1 WHERE id='{listing}';COMMIT;", 'rac_migrator')
        return principal, profile, revision

    def report(reporter, target_type, target, category='harassment', ok=True):
        result = execute(f"SELECT ts.report_receive(gen_random_uuid(),'{reporter}','{policy}','{target_type}','{target}','{category}');", ROLE, ok)
        return json.loads(result.stdout) if ok else result

    owner, profile, revision = compa()
    reporter = str(uuid.uuid4())
    first = report(reporter, 'account', profile)
    assert first['duplicate'] is False and 'case_id' not in first, 'Reporter learned the case'
    assert report(reporter, 'account', profile) == {**first, 'duplicate': True}, 'Open report duplicated'
    recorded = execute(f"SELECT subject||':'||target_type FROM ts.reports WHERE id='{first['report_id']}';").stdout.strip()
    assert recorded == owner + ':account', 'Subject not resolved from the owner: ' + recorded
    assert report(reporter, 'listing_revision', revision)['duplicate'] is False

    # Unknown, unpublished and unsupported targets are indistinguishable.
    _, _, pending = compa(publish=False)
    legacy_owner, legacy_profile, _ = compa(principal='kc-legacy-' + uuid.uuid4().hex[:8])
    for target_type, target in (('account', str(uuid.uuid4())), ('listing_revision', pending), ('listing_revision', str(uuid.uuid4())),
                                ('booking', str(uuid.uuid4())), ('account', legacy_profile), ('account', revision)):
        refused = report(reporter, target_type, target, ok=False)
        assert refused.returncode != 0 and 'report_target_unavailable' in refused.stderr, (target_type, refused.stderr[-200:])
    for bad in (('account', profile, 'unknown_category'),):
        assert report(reporter, *bad, ok=False).returncode != 0
    self_report = report(owner, 'account', profile, ok=False)
    assert self_report.returncode != 0 and 'report_self_target' in self_report.stderr, 'Self report accepted'

    # A daily cap per reporter; grouped duplicates never count against it.
    limit = int(execute('SELECT ts.report_daily_limit();').stdout.strip())
    busy = str(uuid.uuid4())
    targets = [compa()[1] for _ in range(limit)]
    for target in targets:
        report(busy, 'account', target)
    limited = report(busy, 'account', profile, ok=False)
    assert limited.returncode != 0 and 'report_rate_limited' in limited.stderr, 'Daily report cap not enforced'
    assert report(busy, 'account', targets[0])['duplicate'] is True, 'Duplicate refused by the cap'

    # The intake login holds exactly its two entry points.
    for statement in (f"SELECT ts.report_submit(gen_random_uuid(),'{reporter}','{policy}','account','{profile}','{owner}','harassment',NULL);",
                      f"SELECT public.ts_report_subject('account','{profile}');", 'SELECT * FROM ts.reports;',
                      f"SELECT ts.case_queue(gen_random_uuid(),'{reporter}','{policy}',10);"):
        assert execute(statement, ROLE, ok=False).returncode != 0, 'Intake login exceeded its authority: ' + statement
    for role in ('rac_user', 'rac_match', 'rac_chat', 'rac_alert'):
        assert execute(f"SELECT public.ts_report_subject('account','{profile}');", role, ok=False).returncode != 0, role + ' resolved a subject'
    print('PASS: customer intake resolves the subject from the owner (public compa profile, published listing revision), hides '
          'unknown/unpublished/unsupported/legacy targets alike, groups duplicates, refuses self reports and caps new reports per day', flush=True)
