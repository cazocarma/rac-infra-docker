"""Exercise P08 history using the real owner role in a disposable database."""
import hashlib
import json


def verify(sql, database, compa_user):
    def execute(statement, role='rac_user', ok=True):
        return sql(database, statement, role, ok=ok)

    profile = execute(f"INSERT INTO compa_perfil(id,usuario_id,descripcion,tarifa_hora) VALUES(gen_random_uuid(),'{compa_user}','Synthetic listing fixture',12000) RETURNING id;").stdout.strip()
    listing = execute(f"INSERT INTO listings(compa_id) VALUES('{profile}') RETURNING id;").stdout.strip()
    payload = json.dumps({'display_name': 'Cris Á', 'description': 'Synthetic public revision'}, ensure_ascii=False, separators=(',', ':'))
    expected = hashlib.sha256(payload.encode('utf-8')).hexdigest()

    def revision(number):
        return execute(f"INSERT INTO listing_revisions(listing_id,revision_no,payload_canonical,assessment,risk_score,policy_version) VALUES('{listing}',{number},'{payload}','{{\"unevaluated\":[\"minors\"]}}',0,'fixture-1') RETURNING id;").stdout.strip()

    first = revision(1)
    assert execute(f"SELECT encode(payload_hash,'hex') FROM listing_revisions WHERE id='{first}';").stdout.strip() == expected
    execute(f"UPDATE listings SET pending_revision_id='{first}',version=version+1 WHERE id='{listing}';")
    # Approval cannot be invented by selecting a pending revision as public.
    assert execute(f"UPDATE listings SET state='published',published_revision_id='{first}',pending_revision_id=NULL,version=version+1 WHERE id='{listing}';", 'rac_migrator', ok=False).returncode != 0
    assert execute(f"UPDATE listings SET version=version WHERE id='{listing}';", ok=False).returncode != 0

    def decision(rev, action='approved', reviewer='staff-fixture'):
        key = {'approved': 'listingApproved', 'rejected': 'listingRejected'}[action]
        return f"INSERT INTO listing_revision_decisions(revision_id,action,reviewer_subject,reason_code,note_to_user_key) VALUES('{rev}','{action}','{reviewer}','fixture_reason','{key}');"

    assert execute(decision(first), ok=False).returncode != 0, 'Public service could forge a moderation decision'
    assert execute(decision(first), 'rac_migrator', ok=False).returncode != 0, 'Decision must clear pending in the same transaction'
    assert execute('BEGIN;' + decision(first, reviewer='kc-p') + f"UPDATE listings SET pending_revision_id=NULL,version=version+1 WHERE id='{listing}';COMMIT;", 'rac_migrator', ok=False).returncode != 0, 'Owner reviewed own publication'
    # Only the migration owner seeds decisions for schema tests. The HTTP
    # moderation writer is separate; this does not pretend to authenticate staff.
    execute('BEGIN;' + decision(first) + f"UPDATE listings SET state='published',published_revision_id='{first}',pending_revision_id=NULL,version=version+1 WHERE id='{listing}';COMMIT;", 'rac_migrator')
    assert execute(f"UPDATE listings SET published_revision_id='{first}',version=version+1 WHERE id='{listing}';", ok=False).returncode != 0, 'Public service could promote a snapshot'

    other_user = execute("INSERT INTO usuario(id,nombre,correo,rol,keycloak_id) SELECT id,'Other fixture','listing-'||id::text||'@example.test','compa','other-'||id::text FROM (SELECT gen_random_uuid() AS id) fixture RETURNING id;").stdout.strip()
    other_profile = execute(f"INSERT INTO compa_perfil(id,usuario_id,descripcion,tarifa_hora) VALUES(gen_random_uuid(),'{other_user}','Other synthetic listing',12000) RETURNING id;").stdout.strip()
    other_listing = execute(f"INSERT INTO listings(compa_id) VALUES('{other_profile}') RETURNING id;").stdout.strip()
    assert execute(f"UPDATE listings SET state='published',published_revision_id='{first}',version=version+1 WHERE id='{other_listing}';", 'rac_migrator', ok=False).returncode != 0, 'Approved revision crossed listing boundary'

    second = revision(2)
    execute(f"UPDATE listings SET pending_revision_id='{second}',version=version+1 WHERE id='{listing}';")
    assert execute(f"UPDATE listings SET pending_revision_id='{second}',version=version+1 WHERE id='{other_listing}';", ok=False).returncode != 0, 'Pending revision crossed listing boundary'
    assert execute(f"SELECT published_revision_id='{first}' AND pending_revision_id='{second}' FROM listings WHERE id='{listing}';").stdout.strip() == 't'
    assert execute('BEGIN;' + decision(first) + f"UPDATE listings SET pending_revision_id=NULL,version=version+1 WHERE id='{listing}';COMMIT;", 'rac_migrator', ok=False).returncode != 0, 'Stale review accepted'
    execute('BEGIN;' + decision(second, 'rejected') + f"UPDATE listings SET pending_revision_id=NULL,version=version+1 WHERE id='{listing}';COMMIT;", 'rac_migrator')
    assert execute(f"SELECT state='published' AND published_revision_id='{first}' AND pending_revision_id IS NULL FROM listings WHERE id='{listing}';").stdout.strip() == 't'

    for role in ('rac_user', 'rac_migrator'):
        for statement in (f"UPDATE listing_revisions SET payload_canonical='{{}}' WHERE id='{first}';",
                          f"DELETE FROM listing_revisions WHERE id='{first}';",
                          f"UPDATE listing_revision_decisions SET reason_code='rewritten' WHERE revision_id='{first}';",
                          f"DELETE FROM listing_revision_decisions WHERE revision_id='{first}';"):
            assert execute(statement, role, ok=False).returncode != 0, 'History was mutable under ' + role
    for role in ('rac_match', 'rac_chat', 'rac_alert', 'rac_admin'):
        for table in ('listings', 'listing_revisions', 'listing_revision_decisions'):
            assert execute('SELECT * FROM ' + table + ';', role, ok=False).returncode != 0
    # Even the owner cannot supply a forged generated digest.
    assert execute(f"INSERT INTO listing_revisions(listing_id,revision_no,payload_canonical,payload_hash,assessment,risk_score,policy_version) VALUES('{listing}',3,'{{}}',decode(repeat('00',32),'hex'),'{{}}',0,'fixture-1');", ok=False).returncode != 0
    print('PASS: listing owner permissions, UTF-8 digest, append-only revisions/decisions, stale/self review and approved snapshot preservation', flush=True)
