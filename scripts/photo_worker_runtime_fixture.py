"""Run the actual non-root worker with file secrets and synthetic data only."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time
import uuid


def prove(run, root, network, database, tools, fixtures):
    source = root.parent/'rac-user-service'
    image, worker = network+'-worker-image', network+'-worker'
    metadata = root.parent.parent/'revisions.json'
    if metadata.exists():
        commit = json.loads(metadata.read_text(encoding='utf-8'))['rac-user-service']
    else:
        commit = subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()
        dirty = subprocess.check_output(['git','-C',str(source),'status','--porcelain'],text=True).strip()
        if dirty:
            raise RuntimeError('Worker runtime proof requires committed clean user sources or a frozen snapshot')
    if not re.fullmatch('[a-f0-9]{40}',commit):
        raise RuntimeError('Exact source revision required')
    photo = source/'internal/photoassets/testdata/contact_border.png'
    digest = hashlib.sha256(photo.read_bytes()).hexdigest()
    owner, asset = str(uuid.uuid4()), str(uuid.uuid4())
    key = asset.replace('-','')+'.raw'
    def sql(statement):
        return run('docker','exec',database,'psql','-X','-At','-v','ON_ERROR_STOP=1','-U','postgres','-d','photo_processing','-c',statement).stdout.strip()
    try:
        run('docker','build','-q','-t',image,'-f',str(source/'Dockerfile.photo-worker'),str(source))
        descriptor = run('docker','image','inspect','--format','{{json .Descriptor}}',image).stdout
        # containerd stores expose the manifest descriptor; the classic store
        # (GitHub runners) does not, so fall back to the immutable image ID.
        parsed = json.loads(descriptor) if descriptor.strip() else None
        image_digest = parsed['digest'] if parsed else run('docker','image','inspect','--format','{{.Id}}',image).stdout.strip()
        if not re.fullmatch('sha256:[a-f0-9]{64}',image_digest):
            raise RuntimeError('Immutable worker image descriptor required')
        sql(f"""INSERT INTO public.usuario(id,nombre,correo,rol,keycloak_id)
          VALUES('{owner}','Worker runtime fixture','{owner}@example.test','cliente','{owner}');
          INSERT INTO photo.processing_policies VALUES('runtime-fixture-1',120,5,3);
          INSERT INTO photo.processing_releases VALUES('runtime-fixture-1','{commit}','{image_digest}');
          INSERT INTO photo.sources(id,owner_user_id,object_key,source_sha256,source_size,declared_media_type,source_width,source_height,pipeline_version)
          VALUES('{asset}','{owner}','{key}',decode('{digest}','hex'),{photo.stat().st_size},'image/png',1200,400,'runtime-fixture-1');""")
        # The uploader receives only ingestion credentials; the daemon never
        # receives root, ingestion or migration credentials.
        run('docker','run','--rm','--network',network,
            '--mount',f'type=bind,source={photo},target=/input/photo.png,readonly',
            '-e','ENDPOINT='+fixtures['S3_ENDPOINT'], '-e','BUCKET='+fixtures['PHOTO_QUARANTINE_BUCKET'],
            '-e','ACCESS='+fixtures['PHOTO_INGEST_ACCESS_KEY'], '-e','SECRET='+fixtures['PHOTO_INGEST_SECRET_KEY'],
            '-e','KEY='+key,'--entrypoint','python',tools,'-c',
            "import os,boto3;from pathlib import Path;from botocore.config import Config;"
            "c=boto3.client('s3',endpoint_url=os.environ['ENDPOINT'],region_name='us-east-1',aws_access_key_id=os.environ['ACCESS'],aws_secret_access_key=os.environ['SECRET'],config=Config(signature_version='s3v4',s3={'addressing_style':'path'}));"
            "c.put_object(Bucket=os.environ['BUCKET'],Key=os.environ['KEY'],Body=Path('/input/photo.png').read_bytes(),IfNoneMatch='*')")
        # Fixture-only verified ledger seed; the owner upload/confirmation API
        # is not implemented by this runtime proof. RunOnce rechecks actual S3.
        sql(f"""BEGIN; INSERT INTO photo.upload_confirmations(asset_id,verified_sha256,verified_size)
          VALUES('{asset}',decode('{digest}','hex'),{photo.stat().st_size});
          INSERT INTO photo.analysis_outbox(asset_id) VALUES('{asset}'); COMMIT;""")
        with tempfile.TemporaryDirectory(prefix='rac-photo-runtime-') as temporary:
            secrets = {
                'RAC_PHOTO_QUEUE_DATABASE_URL': 'postgres://rac_photo_worker_fixture:synthetic-photo-worker-only@'+database+':5432/photo_processing?sslmode=disable',
                'RAC_PHOTO_QUARANTINE_ACCESS_KEY': fixtures['PHOTO_READER_ACCESS_KEY'],
                'RAC_PHOTO_QUARANTINE_SECRET_KEY': fixtures['PHOTO_READER_SECRET_KEY'],
                'RAC_PHOTO_STAGING_ACCESS_KEY': fixtures['PHOTO_STAGING_ACCESS_KEY'],
                'RAC_PHOTO_STAGING_SECRET_KEY': fixtures['PHOTO_STAGING_SECRET_KEY'],
            }
            flags = []
            for name,value in secrets.items():
                (Path(temporary)/name).write_text(value,encoding='utf-8')
                flags += ['-e',name+'_FILE=/run/secrets/'+name]
            try:
                run('docker','run','-d','--name',worker,'--network',network,
                    '--read-only','--cap-drop','ALL','--security-opt','no-new-privileges:true',
                    '--pids-limit','64','--cpus','1','--memory','512m',
                    '--tmpfs','/tmp:rw,nosuid,nodev,size=32m',
                    '--mount',f'type=bind,source={temporary},target=/run/secrets,readonly',*flags,
                    '-e','RAC_ENV=dev','-e','RAC_PHOTO_S3_ENDPOINT='+fixtures['S3_ENDPOINT'],
                    '-e','RAC_PHOTO_S3_REGION=us-east-1',
                    '-e','RAC_PHOTO_QUARANTINE_BUCKET='+fixtures['PHOTO_QUARANTINE_BUCKET'],
                    '-e','RAC_PHOTO_STAGING_BUCKET='+fixtures['PHOTO_STAGING_BUCKET'],
                    '-e','RAC_PHOTO_PIPELINE_VERSION=runtime-fixture-1',
                    '-e','RAC_PHOTO_BUILD_COMMIT='+commit,'-e','RAC_PHOTO_IMAGE_DIGEST='+image_digest,image)
                for _ in range(60):
                    result=sql(f"SELECT disposition FROM photo.processing_results WHERE asset_id='{asset}';")
                    if result:
                        break
                    if run('docker','inspect','--format','{{.State.Running}}',worker).stdout.strip()!='true':
                        raise RuntimeError('Worker exited before committing its private result')
                    time.sleep(1)
                else:
                    raise RuntimeError('Worker did not complete the synthetic job within the test budget')
                if result!='contact_correction_required':
                    raise AssertionError('Runtime worker did not retain contact correction')
                assert sql(f"SELECT count(*) FROM photo.processing_results WHERE asset_id='{asset}' AND assessment->>'ocr_version' LIKE 'tesseract %' AND assessment->'pending_checks' ? 'human_review';")=='1'
                allowed = ('photo worker started: private processing only; human review required',
                           'private photo processing result committed; human review pending')
                logs=run('docker','logs',worker)
                for line in (logs.stdout+logs.stderr).splitlines():
                    if not any(line.endswith(message) for message in allowed):
                        raise AssertionError('Unexpected worker log; inspect isolated runtime without copying private payloads')
                print('IMAGE worker '+image_digest,flush=True)
                print('PASS: actual non-root worker, read-only filesystem, file secrets, native OCR, isolated IAM and durable contact-correction result; no public promotion',flush=True)
            finally:
                # Stop before unmounting/removing the synthetic secret directory.
                run('docker','rm','-f',worker,ok=False)
    finally:
        run('docker','image','rm',image,ok=False)
