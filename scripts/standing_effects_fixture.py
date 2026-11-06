"""P11 effects consumer boundary on the user-owned standing. Synthetic data only."""
import json
import uuid

FUNCTIONS = ('standing.apply_ts_effect(uuid,jsonb,uuid)', 'standing.refresh_ts_standing(uuid,uuid,uuid)')


def verify(sql, database, subject):
    def execute(statement, role='postgres', ok=True):
        return sql(database, statement, role, ok=ok)

    role = 'rac_standing_effects_fixture'
    execute(f"DO $$BEGIN IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname='{role}') THEN CREATE ROLE {role} LOGIN; END IF; END$$;"
            f"DO $$BEGIN EXECUTE format('GRANT CONNECT ON DATABASE %I TO {role}',current_database()); END$$;"
            f"GRANT USAGE ON SCHEMA standing,audit TO {role};"
            + ''.join(f'GRANT EXECUTE ON FUNCTION {f} TO {role};' for f in FUNCTIONS)
            + "DO $$DECLARE c uuid; BEGIN IF NOT EXISTS(SELECT FROM audit.writer_principals WHERE database_role='"
            + role + "') THEN c:=gen_random_uuid(); INSERT INTO audit.chain_heads(chain_id) VALUES(c);"
            " INSERT INTO audit.writer_principals(database_role,actor_id,chain_id) VALUES('"
            + role + "',gen_random_uuid(),c); END IF; END$$;")
    policy, case = str(uuid.uuid4()), str(uuid.uuid4())

    def effect(kind, action=None, revokes=None, hours=None):
        return {'action_id': action or str(uuid.uuid4()), 'case_id': case, 'subject': subject, 'kind': kind,
                'reason_code': 'fixture_reason', 'policy_version': 'actions-fixture-1', 'duration_hours': hours,
                'notice_key': 'actionFixture', 'revokes': revokes, 'effective_at': '2026-01-01T00:00:00Z'}

    def apply(payload, event=None, who=role, ok=True):
        event = event or str(uuid.uuid4())
        body = json.dumps(payload).replace("'", "''")
        result = execute(f"SELECT standing.apply_ts_effect('{event}','{body}','{policy}');", who, ok)
        return json.loads(result.stdout) if ok else result

    def status():
        return execute(f"SELECT status||':'||coalesce((SELECT string_agg(capability,',' ORDER BY capability) FROM standing.restriction r "
                       f"WHERE r.subject_id=a.subject_id AND (ends_at IS NULL OR ends_at>now())),'') FROM standing.account a WHERE subject_id='{subject}';").stdout.strip()

    restrict = effect('restrict_publish', hours=24 * 365 * 20)
    event = str(uuid.uuid4())
    assert apply(restrict, event)['status'] == 'restricted' and status() == 'restricted:publish_listing'
    assert apply(restrict, event)['duplicate'] is True, 'Replay applied twice'
    assert apply(restrict)['duplicate'] is True, 'Redelivery under another event applied twice'
    assert apply({**restrict, 'kind': 'ban'}, ok=False).returncode != 0, 'Conflicting redelivery accepted'
    for invalid in ({**restrict, 'extra': 1}, {k: v for k, v in restrict.items() if k != 'revokes'}, {**effect('delete_account')}):
        assert apply(invalid, ok=False).returncode != 0, 'Invalid effect accepted'
    early = effect('revocation', revokes=str(uuid.uuid4()))
    assert apply(early, ok=False).returncode != 0, 'Revocation of an unknown action applied'
    ban = effect('ban')
    assert apply(ban)['status'] == 'banned' and status().startswith('banned')
    assert apply(effect('revocation', revokes=ban['action_id']))['status'] == 'restricted', 'Ban revocation lost the restriction'
    assert apply(effect('warning'))['changed'] is False
    assert apply(effect('revocation', revokes=restrict['action_id']))['status'] == 'active' and status() == 'active:'
    expired = effect('suspend', hours=1)
    assert apply(expired)['status'] == 'active', 'Expired suspension applied'
    assert json.loads(execute(f"SELECT standing.refresh_ts_standing(gen_random_uuid(),'{subject}','{policy}');", role).stdout)['changed'] is False
    counts = execute(f"SELECT (SELECT count(*) FROM standing.ts_effects WHERE subject_id='{subject}')||':'||"
                     f"(SELECT count(*) FROM standing.outbox WHERE subject_id='{subject}' AND payload->>'case_id'='{case}');").stdout.strip()
    assert counts == '6:4', 'Effects or standing events not recorded exactly once: ' + counts
    for statement in (f"UPDATE standing.ts_effects SET kind='warning' WHERE subject_id='{subject}';",
                      f"DELETE FROM standing.ts_effects WHERE subject_id='{subject}';"):
        assert execute(statement, ok=False).returncode != 0, 'Effect history mutated'
    for other in ('rac_user', 'rac_match', 'rac_chat', 'rac_alert'):
        assert apply(effect('ban'), who=other, ok=False).returncode != 0, f'{other} applied a T&S effect'
    print('PASS: T&S effects ledger applies once per action, derives standing through the single standing path, '
          'handles revocation order and expiry, is append-only and denies other services', flush=True)
