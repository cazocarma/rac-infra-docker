"""V035 authored data survives catalog generalization without changing receipts."""
import hashlib
import uuid


def check(sql, migrate):
    migrate(35)
    chain, service, author, reviewer, policy, document, draft, review, publish = [str(uuid.uuid4()) for _ in range(9)]
    text = 'Synthetic pre-V036 editorial record; never real legal text.'
    digest = hashlib.sha256(text.encode()).hexdigest()
    sql(f"INSERT INTO audit.chain_heads(chain_id) VALUES('{chain}'); INSERT INTO audit.writer_principals VALUES('postgres','{service}','{chain}');")
    commands = [
        f"SELECT documents.draft_document('{draft}','{document}','{author}','{policy}','privacy','upgrade-v35','es','{text}',true,'{digest}');",
        f"SELECT documents.review_document('{review}','{document}','{reviewer}','{policy}','{digest}','approved');",
        f"SELECT documents.publish_document('{publish}','{document}','{reviewer}','{policy}','{digest}');",
    ]
    for statement in commands:
        assert sql(statement) == document
    snapshot = sql(f"SELECT jsonb_build_object('document',to_jsonb(d),'events',(SELECT jsonb_agg(to_jsonb(e) ORDER BY occurred_at,event_id) FROM documents.editorial_event e),'review',(SELECT to_jsonb(r) FROM documents.editorial_review r WHERE document_id=d.id)) FROM legal_documents d WHERE id='{document}';")
    reader = sql(f"SELECT documents.read_editorial_document('{document}');")
    head = sql(f"SELECT sequence||':'||hash FROM audit.chain_heads WHERE chain_id='{chain}';")
    migrate(None)
    assert sql(f"SELECT document_id FROM documents.editorial_resource WHERE resource_id='{document}' AND assessment_id IS NULL;") == document
    for statement in commands:
        assert sql(statement) == document
    assert sql(f"SELECT documents.read_editorial_document('{document}');") == reader
    assert sql(f"SELECT jsonb_build_object('document',to_jsonb(d),'events',(SELECT jsonb_agg(to_jsonb(e) ORDER BY occurred_at,event_id) FROM documents.editorial_event e),'review',(SELECT to_jsonb(r) FROM documents.editorial_review r WHERE document_id=d.id)) FROM legal_documents d WHERE id='{document}';") == snapshot
    assert sql(f"SELECT sequence||':'||hash FROM audit.chain_heads WHERE chain_id='{chain}';") == head
    print('PASS: V035 authored drafts/reviews/publications, original times/content/events, exact replays and audit head survive typed catalog upgrade')
