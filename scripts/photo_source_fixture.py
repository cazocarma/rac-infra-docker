"""Structural P09 permissions/restore fixture; not an image-processing proof."""
import hashlib
import uuid


def verify(sql, database, owner, other):
    source = str(uuid.uuid4())
    key = source.replace('-', '')+'.raw'
    raw = b'private-source-fixture'
    digest = hashlib.sha256(raw).hexdigest()
    request = str(uuid.uuid4())
    def execute(statement, role='rac_user', ok=True):
        return sql(database, statement, role, ok=ok)
    execute(f"INSERT INTO photo.sources(id,owner_user_id,object_key,source_sha256,source_size,declared_media_type,source_width,source_height,pipeline_version) VALUES('{source}','{owner}','{key}',decode('{digest}','hex'),{len(raw)},'image/png',64,48,'fixture-1');")
    assert execute(f"INSERT INTO photo.upload_requests(owner_user_id,request_id,asset_id) VALUES('{other}','{request}','{source}');",ok=False).returncode!=0
    execute(f"INSERT INTO photo.upload_requests(owner_user_id,request_id,asset_id) VALUES('{owner}','{request}','{source}');")
    assert execute(f"SELECT state FROM photo.owner_upload_status((SELECT keycloak_id FROM public.usuario WHERE id='{owner}'),'{source}');").stdout.strip()=='awaiting_upload'
    assert execute(f"INSERT INTO photo.upload_confirmations(asset_id,verified_sha256,verified_size) VALUES('{source}',decode(repeat('00',32),'hex'),{len(raw)});",ok=False).returncode!=0
    execute(f"BEGIN; INSERT INTO photo.upload_confirmations(asset_id,verified_sha256,verified_size) VALUES('{source}',decode('{digest}','hex'),{len(raw)}); INSERT INTO photo.analysis_outbox(asset_id) VALUES('{source}'); COMMIT;")
    assert execute(f"SELECT state FROM photo.owner_upload_status((SELECT keycloak_id FROM public.usuario WHERE id='{owner}'),'{source}');").stdout.strip()=='queued'
    assert execute(f"SELECT count(*) FROM photo.owner_upload_status((SELECT keycloak_id FROM public.usuario WHERE id='{other}'),'{source}');").stdout.strip()=='0'
    for role in ('rac_user','rac_migrator'):
        for statement in ('UPDATE photo.sources SET pipeline_version=\'changed\';',
                          'DELETE FROM photo.sources;',
                          'UPDATE photo.upload_confirmations SET verified_size=1;',
                          'DELETE FROM photo.analysis_outbox;',
                          'UPDATE photo.upload_requests SET request_id=request_id;',
                          'DELETE FROM photo.upload_requests;'):
            assert execute(statement,role,ok=False).returncode!=0, 'Photo source history changed under '+role
    for role in ('rac_match','rac_chat','rac_alert','rac_admin','rac_seed'):
        for table in ('sources','upload_confirmations','analysis_outbox','upload_requests','processing_jobs','processing_attempts','processing_results'):
            assert execute('SELECT * FROM photo.'+table+';',role,ok=False).returncode!=0
        assert execute(f"SELECT * FROM photo.owner_upload_status('kc-c','{source}');",role,ok=False).returncode!=0
    for table in ('processing_jobs','processing_attempts','processing_results'):
        assert execute('SELECT * FROM photo.'+table+';',ok=False).returncode!=0
    print('PASS: immutable private photo source metadata, exact confirmation FK, owner privileges and other-service denial',flush=True)
