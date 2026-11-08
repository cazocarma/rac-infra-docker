"""P11 effects consumer boundary on the user-owned standing. Synthetic data only."""
import json
import uuid
from concurrent.futures import ThreadPoolExecutor

FUNCTIONS = ('standing.apply_ts_effect(uuid,jsonb,uuid)', 'standing.refresh_ts_standing(uuid,uuid,uuid)',
             'standing.ts_expiries_due(integer)')


def verify(sql, database):
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
    started = execute("SELECT to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"');").stdout.strip()
    subject, principal, other_subject = (str(uuid.uuid4()) for _ in range(3))
    # Deliberate namespace collision: A's internal ID is B's Keycloak sub.
    other_principal = subject
    execute(f"INSERT INTO usuario(id,nombre,correo,rol,keycloak_id) VALUES"
            f"('{subject}','Fixture','{subject}@example.test','cliente','{principal}'),"
            f"('{other_subject}','Fixture','{other_subject}@example.test','cliente','{other_principal}');")

    def effect(kind, action=None, revokes=None, hours=None):
        return {'action_id': action or str(uuid.uuid4()), 'case_id': case, 'subject': principal, 'kind': kind,
                'reason_code': 'fixture_reason', 'policy_version': 'actions-fixture-1', 'duration_hours': hours,
                'notice_key': 'actionFixture', 'revokes': revokes, 'effective_at': started}

    def apply(payload, event=None, who=role, ok=True):
        event = event or str(uuid.uuid4())
        body = json.dumps(payload).replace("'", "''")
        result = execute(f"SELECT standing.apply_ts_effect('{event}','{body}','{policy}');", who, ok)
        return json.loads(result.stdout) if ok else result

    def status(account=subject):
        return execute(f"SELECT status||':'||coalesce((SELECT string_agg(capability,',' ORDER BY capability) FROM standing.restriction r "
                       f"WHERE r.subject_id=a.subject_id AND (ends_at IS NULL OR ends_at>now())),'') FROM standing.account a WHERE subject_id='{account}';").stdout.strip()

    assert apply({**effect('ban'), 'subject': other_subject}, ok=False).returncode != 0, 'Internal ID fallback accepted'
    assert apply({**effect('ban'), 'subject': str(uuid.uuid4())}, ok=False).returncode != 0, 'Unknown principal accepted'
    for field, value in (
        ('duration_hours', 0), ('duration_hours', 87601), ('duration_hours', '24'),
        ('duration_hours', True), ('reason_code', 'private text'),
        ('notice_key', True), ('notice_key', 'private text'), ('policy_version', True),
        ('subject', '00000000-0000-0000-0000-000000000000'),
        ('case_id', 'AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA'),
        ('effective_at', '2026-11-06T12:00:00+00:00'), ('namespace', 'user_id'),
    ):
        assert apply({**effect('warning'), field: value}, ok=False).returncode != 0, 'Noncanonical new command accepted: ' + field
    shadow = {**effect('restrict_booking', hours=24), 'subject': other_principal}
    assert apply(shadow)['subject_id'] == other_subject, 'Canonical principal resolved to the wrong internal account'
    assert status() == 'active:' and status(other_subject) == 'restricted:accept_booking,request_booking'
    assert apply({**effect('revocation', revokes=shadow['action_id']), 'subject': other_principal})['status'] == 'active'

    restrict = effect('restrict_publish', hours=24)
    event = str(uuid.uuid4())
    assert apply(restrict, event)['status'] == 'restricted' and status() == 'restricted:publish_listing'
    assert apply({**effect('revocation', revokes=restrict['action_id']), 'subject': other_principal}, ok=False).returncode != 0, 'Cross-principal revocation accepted'
    assert apply(restrict, event)['duplicate'] is True, 'Replay applied twice'
    alias_event = str(uuid.uuid4())
    assert apply(restrict, alias_event)['duplicate'] is True, 'Redelivery under another event applied twice'
    assert apply({**restrict, 'kind': 'ban'}, ok=False).returncode != 0, 'Conflicting redelivery accepted'
    for field, value in (
        ('case_id', str(uuid.uuid4())), ('policy_version', 'different-policy'),
        ('effective_at', '2026-02-01T00:00:00Z'), ('duration_hours', 48),
        ('reason_code', 'different_reason'), ('notice_key', 'differentNotice'),
        ('revokes', str(uuid.uuid4())),
    ):
        altered = {**restrict, field: value}
        assert apply(altered, event, ok=False).returncode != 0, 'Altered event acknowledged: ' + field
        assert apply(altered, ok=False).returncode != 0, 'Altered action acknowledged: ' + field
    for invalid in ({**restrict, 'extra': 1}, {k: v for k, v in restrict.items() if k != 'revokes'}, {**effect('delete_account')}):
        assert apply(invalid, ok=False).returncode != 0, 'Invalid effect accepted'
    early = effect('revocation', revokes=str(uuid.uuid4()))
    assert apply(early, ok=False).returncode != 0, 'Revocation of an unknown action applied'
    ban = effect('ban')
    ban_event = str(uuid.uuid4())
    assert apply(ban, ban_event)['status'] == 'banned' and status().startswith('banned')
    assert apply(restrict, ban_event, ok=False).returncode != 0, 'Event ID reused for another recorded action'
    assert apply(ban, alias_event, ok=False).returncode != 0, 'Acknowledged alias reused for another action'
    assert apply(effect('revocation', revokes=ban['action_id']))['status'] == 'restricted', 'Ban revocation lost the restriction'
    assert apply(effect('warning'))['changed'] is False
    assert apply(effect('revocation', revokes=restrict['action_id']))['status'] == 'active' and status() == 'active:'
    expired = effect('suspend', hours=1)
    expired['effective_at'] = execute("SELECT to_char((clock_timestamp()-interval '2 hours') AT TIME ZONE 'UTC','YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"');").stdout.strip()
    assert apply(expired)['status'] == 'active', 'Expired suspension applied'
    assert apply({**effect('ban'), 'notice_key': 'x' * 5000}, ok=False).returncode != 0, 'Oversized command accepted'
    assert json.loads(execute(f"SELECT standing.refresh_ts_standing(gen_random_uuid(),'{subject}','{policy}');", role).stdout)['changed'] is False
    counts = execute(f"SELECT (SELECT count(*) FROM standing.ts_effects WHERE subject_id='{subject}')||':'||"
                     f"(SELECT count(*) FROM standing.outbox WHERE subject_id='{subject}' AND payload->>'case_id'='{case}');").stdout.strip()
    assert counts == '6:4', 'Effects or standing events not recorded exactly once: ' + counts
    for statement in (f"UPDATE standing.ts_effects SET kind='warning' WHERE subject_id='{subject}';",
                      f"DELETE FROM standing.ts_effects WHERE subject_id='{subject}';"):
        assert execute(statement, ok=False).returncode != 0, 'Effect history mutated'
    assert execute('SELECT count(*) FROM standing.ts_effect_receipts;').stdout.strip() == '8'
    assert execute('SELECT count(*) FROM standing.ts_effect_deliveries;').stdout.strip() == '9'
    collision = str(uuid.uuid4())
    commands = [effect('warning'), {**effect('warning'), 'subject': other_principal}]
    with ThreadPoolExecutor(max_workers=2) as pool:
        delivered = list(pool.map(lambda body: apply(body, collision, ok=False), commands))
    assert sum(result.returncode == 0 for result in delivered) == 1, 'Concurrent event collision has no unique winner'
    assert execute('SELECT count(*) FROM standing.ts_effect_receipts;').stdout.strip() == '9'
    assert execute("SELECT bool_and(subject_namespace='keycloak_sub') FROM standing.ts_effect_receipts;").stdout.strip() == 't'
    assert execute("SELECT bool_and(origin='received') FROM standing.ts_effect_receipts;").stdout.strip() == 't'
    assert execute('SELECT count(*) FROM standing.ts_effect_deliveries;').stdout.strip() == '10'
    for operation in ('UPDATE standing.ts_effect_receipts SET payload=payload;', 'DELETE FROM standing.ts_effect_receipts;',
                      'UPDATE standing.ts_effect_deliveries SET action_id=action_id;', 'DELETE FROM standing.ts_effect_deliveries;'):
        assert execute(operation, ok=False).returncode != 0, 'Command receipt history mutated'
    for other in ('rac_user', 'rac_match', 'rac_chat', 'rac_alert'):
        assert apply(effect('ban'), who=other, ok=False).returncode != 0, f'{other} applied a T&S effect'
        assert execute('SELECT * FROM standing.ts_effect_receipts;', other, ok=False).returncode != 0, 'Service read private receipts'
        assert execute('SELECT * FROM standing.ts_effect_deliveries;', other, ok=False).returncode != 0, 'Service read private deliveries'
    for other in (role, 'rac_user', 'rac_match', 'rac_chat', 'rac_alert'):
        assert execute(f"SELECT has_function_privilege('{other}','standing.record_ts_effect_delivery(uuid,uuid)','EXECUTE');").stdout.strip() == 'f', 'Private helper callable directly'
    for table in ('ts_effect_receipts', 'ts_effect_deliveries'):
        assert execute('SELECT * FROM standing.' + table + ';', role, ok=False).returncode != 0, 'Consumer read raw receipts'
    # Expiry: a timed effect that has run out is listed once until refreshed.
    timed, timed_principal = str(uuid.uuid4()), str(uuid.uuid4())
    execute(f"INSERT INTO usuario(id,nombre,correo,rol,keycloak_id) VALUES('{timed}','Fixture','{timed}@example.test','cliente','{timed_principal}');")

    def due():
        return execute('SELECT standing.ts_expiries_due(100);', role).stdout.strip().strip('{}').split(',')

    suspension = {**effect('suspend', hours=1), 'subject': timed_principal}
    assert apply(suspension)['status'] == 'suspended' and timed not in due(), 'Live suspension listed as expired'
    execute(f"SET session_replication_role=replica; UPDATE standing.ts_effects SET starts_at=starts_at-interval '2 hours',"
            f"ends_at=ends_at-interval '2 hours' WHERE action_id='{suspension['action_id']}';")
    assert timed in due() and status(timed) == 'suspended:', 'Expired suspension not listed'
    refreshed = json.loads(execute(f"SELECT standing.refresh_ts_standing(gen_random_uuid(),'{timed}','{policy}');", role).stdout)
    assert refreshed['changed'] is True and status(timed) == 'active:' and timed not in due(), 'Refresh did not settle the expiry'
    assert execute('SELECT standing.ts_expiries_due(100);', 'rac_user', ok=False).returncode != 0, 'Expiry list exposed to user service'
    print('PASS: T&S effects ledger applies once per action, derives standing through the single standing path, '
          'resolves distinct realm/internal identities without fallback, rejects altered commands and event/alias reuse with one concurrent winner, handles revocation order and expiry, lists expired timed effects until refreshed, is append-only and denies other services', flush=True)
