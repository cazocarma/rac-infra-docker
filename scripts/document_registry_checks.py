"""Registry assertions against the migration runner's disposable database only."""
from concurrent.futures import ThreadPoolExecutor
import uuid


def check(execute, rejected, role='registry_fixture'):
    def uid():
        return str(uuid.uuid4())

    def document(kind, version, material=True, locale='es', age=60, approved=True):
        ident = uid()
        review = "'approved',gen_random_uuid(),now()-interval '2 days'" if approved else "'pending',NULL,NULL"
        publication = f"now()-interval '{age} minutes'" if approved else 'NULL'
        execute(f"INSERT INTO legal_documents(id,kind,version,locale,content,material_change,legal_review,approved_by,reviewed_at,published_at) "
                f"VALUES('{ident}','{kind}','{version}','{locale}','Synthetic registry fixture only',{str(material).lower()},{review},{publication});")
        return ident

    kinds = ('terms_client', 'terms_compa', 'community_rules', 'privacy', 'safety_rules')
    docs = [document(kind, 'registry-fixture-1') for kind in kinds]
    policy, approval = uid(), uid()

    def activate(event, expected, selected, locale='es'):
        ids = ','.join("'" + value + "'::uuid" for value in selected)
        return f"SELECT documents.activate('{event}',{expected},'{locale}',ARRAY[{ids}],'{policy}','{approval}');"

    # Use a new technical principal on its own audit chain. The real role has
    # no direct DML on the registry; only this fixture explicitly grants ingress.
    execute(f'CREATE ROLE {role} LOGIN;')
    signature = 'documents.activate(uuid,bigint,text,uuid[],uuid,uuid,text[])'
    execute(f'GRANT USAGE ON SCHEMA documents TO {role}; GRANT EXECUTE ON FUNCTION ' + signature + f' TO {role};')
    event = uid()
    assert rejected(f'SET SESSION AUTHORIZATION {role}; ' + activate(event, 0, docs))
    assert execute("SELECT version FROM documents.head WHERE locale='es';") == '0'
    assert execute('SELECT count(*) FROM documents.registry;') == '0'
    chain, actor = uid(), uid()
    execute(f"INSERT INTO audit.chain_heads(chain_id) VALUES('{chain}'); INSERT INTO audit.writer_principals VALUES('{role}','{actor}','{chain}');")

    def command(statement):
        return f'SET SESSION AUTHORIZATION {role}; ' + statement

    # Contenders with the same expected version cannot both activate.
    candidates = [uid(), uid()]
    with ThreadPoolExecutor(max_workers=2) as pool:
        failures = list(pool.map(lambda e: rejected(command(activate(e, 0, docs))), candidates))
    assert sum(failures) == 1
    assert execute("SELECT version FROM documents.head WHERE locale='es';") == '1'
    original = execute("SELECT event_id FROM documents.registry WHERE locale='es' AND version=1;")
    # Replay is canonical across list ordering and preserves its exact version.
    execute(command(activate(original, 0, list(reversed(docs)))))
    assert rejected(command(activate(original, 1, docs)))
    assert execute(f"SELECT count(*) FROM audit.log WHERE chain_id='{chain}';") == '1'

    old = docs[0]
    nonmaterial = document('terms_client', 'registry-fixture-2', False, age=40)
    docs[0] = nonmaterial
    execute(command(activate(uid(), 1, docs)))
    assert execute(f"SELECT material_version='{old}'::uuid FROM documents.lineage WHERE document_id='{nonmaterial}';") == 't'

    # A material publication not selected in an earlier registry must still
    # split the lineage of the next nonmaterial revision.
    material = document('terms_client', 'registry-fixture-3', True, age=30)
    newest = document('terms_client', 'registry-fixture-4', False, age=20)
    docs[0] = newest
    execute(command(activate(uid(), 2, docs)))
    assert execute(f"SELECT material_version='{material}'::uuid FROM documents.lineage WHERE document_id='{newest}';") == 't'
    assert execute(f"SELECT material_version='{old}'::uuid FROM documents.lineage WHERE document_id='{old}';") == 't'
    assert execute(f"SELECT count(*) FROM documents.lineage WHERE document_id IN('{old}','{nonmaterial}','{material}','{newest}');") == '4'
    # Old activation replay after a newer one must not rewind current state.
    execute(command(activate(original, 0, docs[1:] + [old])))
    assert execute("SELECT version FROM documents.head WHERE locale='es';") == '3'
    assert rejected(command(activate(uid(), 3, docs[1:] + [old])))

    draft = document('terms_client', 'registry-draft', approved=False)
    future = document('terms_client', 'registry-future', age=-60)
    foreign = document('terms_client', 'registry-foreign', locale='en')
    for invalid in (docs[:3], docs[:4]+[docs[0]], docs[1:]+[draft], docs[1:]+[future], docs[1:]+[foreign]):
        assert rejected(command(activate(uid(), 3, invalid)))
    assert rejected(command(activate(uid(), 3, docs).replace(');', ",ARRAY[ARRAY['one','two']]);")))
    assert rejected("INSERT INTO legal_documents(id,kind,version,locale,content,material_change) VALUES('00000000-0000-0000-0000-000000000000','privacy','zero-id','es','fixture',true);")
    assert rejected("INSERT INTO legal_documents(kind,version,locale,content,material_change,created_at) VALUES('privacy','infinite','es','fixture',true,'infinity');")
    backdated = document('terms_client', 'registry-backdated', True, age=25)
    later = document('terms_client', 'registry-later', False, age=10)
    assert rejected(command(activate(uid(), 3, docs[1:] + [later])))
    assert execute(f"SELECT count(*) FROM documents.lineage WHERE document_id IN('{backdated}','{later}');") == '0'
    assert execute("SELECT version FROM documents.head WHERE locale='es';") == '3'
    assert execute(f"SELECT count(*) FROM audit.log WHERE chain_id='{chain}' AND action='policy.published';") == '3'
    # First activation also preserves consent to a historical nonmaterial
    # predecessor. A four-document client set need not invent compa approval.
    english = [foreign] + [document(kind, 'registry-en-first', locale='en') for kind in kinds[2:]]
    english_new = document('terms_client', 'registry-en-nonmaterial', False, locale='en', age=40)
    execute(command(activate(uid(), 0, [english_new] + english[1:], 'en')))
    assert execute(f"SELECT material_version='{foreign}'::uuid FROM documents.lineage WHERE document_id='{english_new}';") == 't'
    assert execute(f"SELECT material_version='{foreign}'::uuid FROM documents.lineage WHERE document_id='{foreign}';") == 't'
    for role in ('rac_user', 'rac_match', 'rac_chat', 'rac_alert', 'rac_standing_sessions'):
        assert execute(f"SELECT has_function_privilege('{role}','{signature}','EXECUTE');") == 'f'
    for table in ('registry', 'lineage', 'requirement'):
        assert rejected(f'DELETE FROM documents.{table};')
        assert rejected(f'SET ROLE rac_user; INSERT INTO documents.{table} DEFAULT VALUES;')
    assert execute("SET ROLE rac_user; SELECT count(*) FROM documents.requirement WHERE locale='es';").splitlines()[-1] == '15'
    assert rejected('SET ROLE rac_user; SELECT command FROM documents.registry;')
    assert rejected("SET ROLE rac_user; UPDATE documents.head SET version=0;")
    print('PASS: atomic audited document activation, concurrent version fencing, historical material lineage, replay, invalid sets and minimum privileges')
