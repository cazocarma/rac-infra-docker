"""Synthetic editorial lifecycle checks, called only by the disposable harness."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import uuid
from test_audit_foundation import canonical


def check(sql, rejected):
    def ref():
        return str(uuid.uuid4())

    def quote(value):
        return "'" + value.replace("'", "''") + "'"

    author, reviewer, policy, chain, service = [ref() for _ in range(5)]
    document, draft_event, review_event, publish_event = [ref() for _ in range(4)]
    content = "Documento sintético de prueba: café y privacidad. No son términos aprobados."
    digest = hashlib.sha256(content.encode()).hexdigest()

    def draft(doc, event, version, actor=author, text=content, sha=digest):
        return f"SELECT documents.draft_document('{event}','{doc}','{actor}','{policy}','privacy','{version}','es',{quote(text)},true,'{sha}');"

    def review(doc, event, actor=reviewer, decision='approved', sha=digest):
        return f"SELECT documents.review_document('{event}','{doc}','{actor}','{policy}','{sha}','{decision}');"

    def publish(doc, event, sha=digest):
        return f"SELECT documents.publish_document('{event}','{doc}','{reviewer}','{policy}','{sha}');"

    # No migration or normal runtime identity is silently provisioned as a
    # writer. Missing audit configuration must roll back the entire command.
    assert rejected(draft(document, draft_event, 'editorial-1'))
    assert sql('SELECT count(*) FROM public.legal_documents;') == '0'
    sql(f"INSERT INTO audit.chain_heads(chain_id) VALUES('{chain}'); INSERT INTO audit.writer_principals VALUES('postgres','{service}','{chain}');")
    assert sql(draft(document, draft_event, 'editorial-1')) == document
    assert sql(draft(document, draft_event, 'editorial-1')) == document
    assert sql('SELECT count(*) FROM audit.log;') == '1'
    assert sql(f"SELECT legal_review||':'||(published_at IS NULL)::text FROM public.legal_documents WHERE id='{document}';") == 'pending:true'
    assert rejected(draft(document, draft_event, 'editorial-1', actor=reviewer))
    assert rejected(draft(document, draft_event, 'editorial-1', text='Different text', sha=hashlib.sha256(b'Different text').hexdigest()))
    assert rejected(draft(ref(), ref(), 'bad-hash', sha='0' * 64))
    assert rejected(publish(document, publish_event))
    assert rejected(review(document, review_event, actor=author))
    assert rejected(review(document, review_event, sha='0' * 64))
    assert sql(review(document, review_event)) == document
    reviewed_at = sql(f"SELECT reviewed_at FROM documents.editorial_review WHERE document_id='{document}';")
    assert sql(review(document, review_event)) == document
    assert sql(f"SELECT reviewed_at FROM documents.editorial_review WHERE document_id='{document}';") == reviewed_at
    assert sql("SELECT count(*) FROM public.legal_documents WHERE legal_review='approved' AND published_at<=clock_timestamp();") == '0'
    assert rejected(review(document, ref(), decision='rejected'))
    assert rejected(publish(document, publish_event, sha='0' * 64))
    assert sql(publish(document, publish_event)) == document
    published_at = sql(f"SELECT published_at FROM public.legal_documents WHERE id='{document}';")
    assert sql(publish(document, publish_event)) == document
    assert sql(f"SELECT published_at FROM public.legal_documents WHERE id='{document}';") == published_at
    assert rejected(publish(document, ref()))
    assert sql('SELECT count(*) FROM audit.log;') == '3'
    # Publication does not automatically select or activate a legal set.
    assert sql("SELECT sum(version) FROM documents.head;") == '0'
    assert rejected(f"UPDATE public.legal_documents SET content='changed' WHERE id='{document}';")
    assert rejected(f"UPDATE public.legal_documents SET approved_by='{author}' WHERE id='{document}';")
    for table in ('editorial_revision', 'editorial_event', 'editorial_review'):
        assert rejected(f"DELETE FROM documents.{table};")
        assert rejected(f"UPDATE documents.{table} SET document_id=document_id;")

    denied_doc = ref()
    assert sql(draft(denied_doc, ref(), 'editorial-rejected')) == denied_doc
    assert sql(review(denied_doc, ref(), decision='rejected')) == denied_doc
    assert rejected(publish(denied_doc, ref()))
    assert sql(f"SELECT legal_review||':'||(published_at IS NULL)::text FROM public.legal_documents WHERE id='{denied_doc}';") == 'pending:true'

    concurrent_doc, concurrent_review = ref(), ref()
    sql(draft(concurrent_doc, ref(), 'editorial-concurrent'))
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(sql, [review(concurrent_doc, concurrent_review)] * 2)) == [concurrent_doc] * 2
    assert sql(f"SELECT count(*) FROM documents.editorial_event WHERE document_id='{concurrent_doc}';") == '2'
    competition = ref()
    sql(draft(competition, ref(), 'editorial-competing'))
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(rejected, [review(competition, ref()), review(competition, ref(), decision='rejected')]))
    assert sorted(outcomes) == [False, True], 'competing reviews both committed or both rejected'
    assert sql(f"SELECT count(*) FROM documents.editorial_review WHERE document_id='{competition}';") == '1'

    # A publication cannot escape if audit append is unavailable midway.
    sql("DELETE FROM audit.writer_principals WHERE database_role='postgres';")
    unpublished = ref()
    assert rejected(draft(unpublished, ref(), 'audit-rollback'))
    assert sql(f"SELECT count(*) FROM public.legal_documents WHERE id='{unpublished}';") == '0'
    sql(f"INSERT INTO audit.writer_principals VALUES('postgres','{service}','{chain}');")
    assert rejected("SELECT audit.append(gen_random_uuid(),'unregistered.action',gen_random_uuid(),'operational',gen_random_uuid());")

    # No commercial runtime, backup reader or PUBLIC can forge an editorial
    # transition or delegated actor assertion through these functions.
    signatures = sql("SELECT oid::regprocedure FROM pg_proc WHERE pronamespace='documents'::regnamespace AND proname IN('draft_document','review_document','publish_document','editorial_record','editorial_replay') ORDER BY proname;").splitlines()
    assert len(signatures) == 5
    for role in ('rac_user', 'rac_match', 'rac_chat', 'rac_alert', 'rac_backup', 'rac_seed'):
        for signature in signatures:
            assert sql(f"SELECT has_function_privilege('{role}',{quote(signature)},'EXECUTE');") == 'f'
        assert sql(f"SELECT has_table_privilege('{role}','documents.editorial_event','INSERT,UPDATE,DELETE');") == 'f'

    exported = sql("""SELECT row_to_json(r) FROM (
      SELECT chain_id::text,sequence,event_id::text,to_char(occurred_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS occurred_at,
      actor_id::text,action,resource_id::text,purpose,policy_version::text,coalesce(case_id::text,'') AS case_id,previous_hash::text,hash::text
      FROM audit.log ORDER BY sequence) r;""")
    previous = '0' * 64
    records = [json.loads(line) for line in exported.splitlines()]
    assert len(records) == 9
    for sequence, record in enumerate(records, 1):
        assert record['actor_id'] == service and record['chain_id'] == chain
        assert record['sequence'] == sequence and record['previous_hash'] == previous
        assert hashlib.sha256(canonical(record)).hexdigest() == record['hash']
        previous = record['hash']
    assert sql(f"SELECT sequence||':'||hash FROM audit.chain_heads WHERE chain_id='{chain}';") == f'{len(records)}:{previous}'
    assert sql(f"SELECT human_actor FROM documents.editorial_event WHERE event_id='{review_event}';") == reviewer
    print('PASS: editorial immutable drafts, exact hash, independent review, rejection, audited publication, replay/concurrency, rollback and closed runtime privileges')
