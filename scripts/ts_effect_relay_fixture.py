"""Function-only T&S delivery protocol. Does not simulate broker acceptance."""
import json
import uuid

FUNCTIONS = ('ts.effect_relay_ready()', 'ts.claim_effect(audit.reference)',
             'ts.confirm_effect(audit.reference)', 'ts.retry_effect(audit.reference)',
             'ts.effect_relay_backlog()')


def verify(sql, database):
    def execute(statement, role='postgres', ok=True):
        return sql(database, statement, role, ok=ok)

    role = 'rac_ts_effect_relay_fixture'
    execute(f"DO $$BEGIN IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname='{role}') THEN CREATE ROLE {role} LOGIN; END IF; END$$;"
            f"DO $$BEGIN EXECUTE format('GRANT CONNECT ON DATABASE %I TO {role}',current_database()); END$$;"
            f"GRANT USAGE ON SCHEMA ts,audit TO {role};"
            + ''.join(f'GRANT EXECUTE ON FUNCTION {function} TO {role};' for function in FUNCTIONS))
    assert execute('SELECT ts.effect_relay_ready();', role).stdout.strip() == 't'
    original = execute("SELECT jsonb_agg(jsonb_build_object('event_id',event_id,'payload',payload) ORDER BY id) FROM ts.outbox;").stdout.strip()
    pending = json.loads(execute('SELECT ts.effect_relay_backlog();', role).stdout)
    assert 0 < int(pending['pending']) < 50
    assert pending['oldest_seconds'] >= 0

    abandoned = str(uuid.uuid4())
    claim = json.loads(execute(f"SELECT ts.claim_effect('{abandoned}');", role).stdout)
    assert claim['event_type'] == 'ts.action.effective.v1' and claim['claim_token'] == abandoned
    assert execute(f"SELECT ts.confirm_effect('{abandoned}');", role).stdout.strip() == 'f', 'New transaction confirmed an abandoned claim'
    recovered = str(uuid.uuid4())
    output = execute(f"BEGIN; SELECT ts.claim_effect('{recovered}'); SELECT ts.confirm_effect('{recovered}'); SELECT ts.confirm_effect('{recovered}'); COMMIT;", role).stdout.splitlines()
    assert json.loads(output[0])['event_id'] == claim['event_id'] and output[1:] == ['t', 't']
    assert execute(f"SELECT ts.retry_effect('{abandoned}');", role).stdout.strip() == 'f', 'Stale transaction reset newer publication'
    for _ in range(50):
        token = str(uuid.uuid4())
        output = execute(f"BEGIN; SELECT ts.claim_effect('{token}'); SELECT ts.confirm_effect('{token}'); COMMIT;", role).stdout.splitlines()
        if output == ['', 'f']:
            break
        assert len(output) == 2 and output[-1] == 't', 'SQL claim/confirmation protocol inconsistent'
    else:
        raise AssertionError('Delivery drain did not converge')
    assert json.loads(execute('SELECT ts.effect_relay_backlog();', role).stdout)['pending'] == '0'
    assert execute("SELECT jsonb_agg(jsonb_build_object('event_id',event_id,'payload',payload) ORDER BY id) FROM ts.outbox;").stdout.strip() == original
    for statement in ('SELECT * FROM ts.outbox;', 'SELECT * FROM ts.effect_delivery_state;',
                      'SELECT * FROM ts.cases;', 'SELECT * FROM ts.evidence_manifests;',
                      'UPDATE ts.effect_delivery_state SET confirmed_at=NULL;'):
        assert execute(statement, role, ok=False).returncode != 0, 'Relay obtained raw application authority'
    for statement in ('UPDATE ts.outbox SET payload=payload;', 'DELETE FROM ts.outbox;',
                      'UPDATE ts.effect_delivery_state SET confirmed_at=NULL;', 'DELETE FROM ts.effect_delivery_state;'):
        assert execute(statement, ok=False).returncode != 0, 'Immutable command or confirmed delivery mutated'
    for other in ('rac_user', 'rac_match', 'rac_chat', 'rac_alert'):
        assert execute(f"SELECT ts.claim_effect('{uuid.uuid4()}');", other, ok=False).returncode != 0, 'Business service claimed T&S publication'
    print('PASS: function-only T&S delivery protocol, transaction fencing, abandoned claim recovery, exact source preservation, immutable confirmation and no business-service authority', flush=True)
