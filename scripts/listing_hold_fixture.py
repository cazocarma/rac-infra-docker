"""P11 hide_listing on the user-owned listings. Synthetic data only.

Runs after standing_effects_fixture, reusing its function-only consumer role.
A hold suspends the exact listing of the subject, survives replays, stacks with
other holds and is released only by the revocation that names the same target.
"""
import json
import uuid

ROLE = 'rac_standing_effects_fixture'


def verify(sql, database):
    def execute(statement, role='postgres', ok=True):
        return sql(database, statement, role, ok=ok)

    policy, case = str(uuid.uuid4()), str(uuid.uuid4())
    started = execute("SELECT to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"');").stdout.strip()

    def owner():
        account, principal = str(uuid.uuid4()), str(uuid.uuid4())
        execute(f"INSERT INTO usuario(id,nombre,correo,rol,keycloak_id) VALUES('{account}','Fixture','{account}@example.test','compa','{principal}');", 'rac_user')
        profile = execute(f"INSERT INTO compa_perfil(id,usuario_id,descripcion,tarifa_hora) VALUES(gen_random_uuid(),'{account}','Synthetic hold fixture',12000) RETURNING id;", 'rac_user').stdout.strip()
        listing = execute(f"INSERT INTO listings(compa_id) VALUES('{profile}') RETURNING id;", 'rac_user').stdout.strip()
        payload = json.dumps({'display_name': 'Synthetic', 'description': 'Hold fixture'}, separators=(',', ':'))
        revision = execute(f"INSERT INTO listing_revisions(listing_id,revision_no,payload_canonical,assessment,risk_score,policy_version) VALUES('{listing}',1,'{payload}','{{\"unevaluated\":[\"minors\"]}}',0,'fixture-1') RETURNING id;", 'rac_user').stdout.strip()
        execute(f"UPDATE listings SET pending_revision_id='{revision}',version=version+1 WHERE id='{listing}';", 'rac_user')
        # Schema-level seed of an approved publication; the HTTP approver is tested elsewhere.
        execute(f"BEGIN;INSERT INTO listing_revision_decisions(revision_id,action,reviewer_subject,reason_code,note_to_user_key) VALUES('{revision}','approved','staff-fixture','fixture_reason','listingApproved');"
                f"UPDATE listings SET state='published',published_revision_id='{revision}',pending_revision_id=NULL,version=version+1 WHERE id='{listing}';COMMIT;", 'rac_migrator')
        return principal, listing, revision

    principal, listing, revision = owner()
    other_principal, other_listing, other_revision = owner()

    def effect(kind, target=None, revokes=None, hours=None, subject=principal):
        body = {'action_id': str(uuid.uuid4()), 'case_id': case, 'subject': subject, 'kind': kind,
                'reason_code': 'fixture_reason', 'policy_version': 'actions-fixture-1', 'duration_hours': hours,
                'notice_key': 'actionFixture', 'revokes': revokes, 'effective_at': started}
        if target:
            body['target'] = {'type': 'listing_revision', 'id': target}
        return body

    def apply(payload, event=None, ok=True):
        event = event or str(uuid.uuid4())
        body = json.dumps(payload).replace("'", "''")
        result = execute(f"SELECT standing.apply_ts_effect('{event}','{body}','{policy}');", ROLE, ok)
        return json.loads(result.stdout) if ok else result

    def state(listing_id=listing):
        return execute(f"SELECT state||':'||version FROM listings WHERE id='{listing_id}';").stdout.strip()

    published = state()
    assert published.startswith('published:'), published
    hide = effect('hide_listing', revision)
    for bad in (effect('hide_listing'), effect('hide_listing', revision, hours=24), effect('ban', revision),
                effect('warning', revision), {**hide, 'target': {'type': 'account', 'id': revision}},
                {**hide, 'target': {'type': 'listing_revision', 'id': revision.upper()}},
                {**hide, 'target': {'type': 'listing_revision', 'id': revision, 'extra': 1}},
                {**hide, 'target': None}, {**hide, 'target': revision}):
        assert apply(bad, ok=False).returncode != 0, 'Malformed hide accepted: ' + json.dumps(bad)
    mismatch = apply(effect('hide_listing', other_revision), ok=False)
    assert mismatch.returncode != 0 and 'ts_effect_listing_mismatch' in mismatch.stderr, 'Hid a listing of another account'
    missing = apply(effect('hide_listing', str(uuid.uuid4())), ok=False)
    assert missing.returncode != 0 and 'ts_effect_listing_missing' in missing.stderr
    assert state(other_listing).startswith('published:') and state() == published, 'Refused hide changed a listing'

    event = str(uuid.uuid4())
    assert apply(hide, event) == {'action_id': hide['action_id'], 'duplicate': False, 'changed': True}
    assert apply(hide, event)['duplicate'] is True and apply(hide)['duplicate'] is True, 'Hide replay not idempotent'
    hidden = state()
    assert hidden.startswith('suspended:'), hidden
    second = effect('hide_listing', revision)
    assert apply(second)['changed'] is False, 'Second hold re-suspended'
    assert execute(f"SELECT count(*) FROM standing.listing_holds WHERE listing_id='{listing}' AND released_at IS NULL;").stdout.strip() == '2'

    # A revocation must repeat exactly the hold it releases.
    for bad in (effect('revocation', revokes=hide['action_id']),
                effect('revocation', other_revision, revokes=hide['action_id'])):
        assert apply(bad, ok=False).returncode != 0, 'Revocation released a hold without its target'
    apply(effect('revocation', revision, revokes=hide['action_id']))
    assert state() == hidden, 'Listing restored while another hold is active'
    apply(effect('revocation', revision, revokes=second['action_id']))
    restored = state()
    assert restored.startswith('published:') and int(restored.split(':')[1]) > int(hidden.split(':')[1]), restored
    # Approval refuses suspended listings; restoration keeps the approved snapshot.
    assert execute(f"SELECT published_revision_id='{revision}' FROM listings WHERE id='{listing}';").stdout.strip() == 't'

    for statement in ('UPDATE standing.listing_holds SET listing_id=gen_random_uuid();', 'DELETE FROM standing.listing_holds;',
                      f"UPDATE standing.listing_holds SET released_at=now() WHERE action_id='{hide['action_id']}';"):
        assert execute(statement, ok=False).returncode != 0, 'Hold history mutated: ' + statement
    for role in ('rac_user', 'rac_match', 'rac_chat', 'rac_alert', ROLE):
        assert execute('SELECT * FROM standing.listing_holds;', role, ok=False).returncode != 0, role + ' read holds'
    assert execute("SELECT has_table_privilege('rac_backup','standing.listing_holds','SELECT');").stdout.strip() == 't'
    print('PASS: hide_listing suspends only the subject\'s exact reported listing, replays idempotently, stacks holds and '
          'restores the approved publication only when the revocation naming each target releases the last hold', flush=True)
