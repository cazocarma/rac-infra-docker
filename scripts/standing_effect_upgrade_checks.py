"""Synthetic V056 command-receipt adoption; no history is manufactured."""
import json
import uuid


def check(create, migrate, sql):
    for mode in ('valid', 'missing', 'conflicting'):
        db = 'effect_receipt_' + mode
        create(db)
        migrate(db, 56)
        subject, action, case, event = [str(uuid.uuid4()) for _ in range(4)]
        payload = dict(action_id=action, case_id=case, subject=subject, kind='warning',
                       reason_code='fixture_reason', policy_version='fixture-1', duration_hours=None,
                       notice_key='fixtureNotice', revokes=None, effective_at='2026-01-01T00:00:00.000000Z')
        sql(db, f"INSERT INTO usuario(id,nombre,correo,rol,keycloak_id) VALUES('{subject}','Fixture','{mode}@example.test','cliente','{subject}');"
            f"INSERT INTO standing.ts_effects(action_id,received_event,subject_id,case_id,kind,policy_version,starts_at) "
            f"VALUES('{action}','{event}','{subject}','{case}','warning','fixture-1','2026-01-01T00:00:00Z');")
        if mode != 'missing':
            original = {**payload, 'case_id': str(uuid.uuid4())} if mode == 'conflicting' else payload
            encoded = json.dumps(original).replace("'", "''")
            sql(db, f"INSERT INTO ts.outbox(event_id,event_type,payload) VALUES('{event}','ts.action.effective.v1','{encoded}');")
        result = migrate(db, None, ok=mode == 'valid')
        if mode != 'valid':
            assert result.returncode != 0
            assert 'ts_effect_receipt_reconciliation_required' in result.stdout + result.stderr
            assert sql(db, "SELECT to_regclass('standing.ts_effect_receipts') IS NULL;") == 't'
            assert sql(db, 'SELECT count(*) FROM standing.ts_effects;') == '1'
            continue
        assert json.loads(sql(db, 'SELECT payload FROM standing.ts_effect_receipts;')) == payload
        assert sql(db, 'SELECT origin FROM standing.ts_effect_receipts;') == 'source_outbox_backfill'
        assert sql(db, 'SELECT subject_namespace FROM standing.ts_effect_receipts;') == 'user_id'
        principal = str(uuid.uuid4())
        sql(db, f"UPDATE usuario SET keycloak_id='{principal}' WHERE id='{subject}';")
        encoded = json.dumps(payload).replace("'", "''")
        assert json.loads(sql(db, f"SELECT standing.apply_ts_effect('{event}','{encoded}',gen_random_uuid());"))['duplicate'] is True
        assert sql(db, 'SELECT count(*) FROM standing.ts_effects;') == '1'
        altered = json.dumps({**payload, 'notice_key': 'alteredNotice'}).replace("'", "''")
        sql(db, f"DO $$ BEGIN PERFORM standing.apply_ts_effect('{event}','{altered}',gen_random_uuid()); "
            "RAISE EXCEPTION 'altered replay accepted'; EXCEPTION WHEN unique_violation THEN NULL; END $$;")
        internal = json.dumps({**payload, 'action_id': str(uuid.uuid4())}).replace("'", "''")
        sql(db, f"DO $$ BEGIN PERFORM standing.apply_ts_effect(gen_random_uuid(),'{internal}',gen_random_uuid()); "
            "RAISE EXCEPTION 'legacy ID accepted for new action'; EXCEPTION WHEN no_data_found THEN NULL; END $$;")
        canonical = {**payload, 'action_id': str(uuid.uuid4()), 'subject': principal}
        encoded = json.dumps(canonical).replace("'", "''")
        sql(db, f"SELECT standing.apply_ts_effect(gen_random_uuid(),'{encoded}',gen_random_uuid());")
        assert sql(db, f"SELECT subject_id::text FROM standing.ts_effects WHERE action_id='{canonical['action_id']}';") == subject
        assert sql(db, f"SELECT subject_namespace FROM standing.ts_effect_receipts WHERE action_id='{canonical['action_id']}';") == 'keycloak_sub'
        assert sql(db, 'SELECT count(*) FROM standing.ts_effects;') == '2'
        migrate(db, None)
    print('PASS: V056 receipt upgrade preserves source commands and namespace history; missing/conflicting provenance aborts atomically; historical replay acknowledges without reinterpreting identity; new actions resolve only realm principals')
