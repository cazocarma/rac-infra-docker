"""Manual P10 capability gate. No .env, real evidence or existing volumes."""
import json
from pathlib import Path
import tempfile
import time
import uuid

from test_photo_storage import ROOT,RUSTFS,run


def main():
    name='rac-evidence-capability-'+uuid.uuid4().hex[:12]
    storage,tools,volume=name+'-storage',name+'-tools',name+'-data'
    access,secret='synthetic-evidence-root','synthetic-evidence-root-password-123456'
    try:
        run('docker','network','create',name)
        run('docker','volume','create',volume)
        run('docker','run','-d','--name',storage,'--network',name,'--network-alias','evidence-storage-fixture',
            '--mount',f'type=volume,source={volume},target=/data',
            '--tmpfs','/logs:rw,mode=1777','-e','RUSTFS_ACCESS_KEY='+access,'-e','RUSTFS_SECRET_KEY='+secret,
            '-e','RUSTFS_VOLUMES=/data','-e','RUSTFS_OBS_LOG_DIRECTORY=/logs','-e','RUSTFS_ADDRESS=:9000',RUSTFS)
        def healthy():
            for _ in range(60):
                if run('docker','exec',storage,'curl','--silent','--fail','--max-time','2','http://localhost:9000/health',ok=False).returncode==0:
                    return
                time.sleep(1)
            raise RuntimeError('Disposable evidence storage did not become healthy')
        healthy()
        run('docker','build','-q','-t',tools,'-f',str(ROOT/'tools/storage/Dockerfile'),str(ROOT))
        flags=['--rm','--network',name,'--mount',f'type=bind,source={ROOT/"scripts/object_lock_fixture.py"},target=/test/object_lock_fixture.py,readonly',
               '-e','AWS_ACCESS_KEY_ID='+access,'-e','AWS_SECRET_ACCESS_KEY='+secret,'-e','S3_ENDPOINT=http://evidence-storage-fixture:9000',
               '--entrypoint','python']
        result=run('docker','run',*flags,tools,'object_lock_fixture.py')
        state=json.loads(result.stdout)
        print('PASS: versioning, COMPLIANCE delete/bypass/shorten/downgrade denial, retained version preserved across overwrite/delete marker, force-delete regression and legal hold',flush=True)
        with tempfile.TemporaryDirectory(prefix='rac-evidence-state-') as temporary:
            state_file=Path(temporary)/'state.json'
            state_file.write_text(json.dumps(state),encoding='utf-8')
            run('docker','restart',storage)
            healthy()
            result=run('docker','run',*flags,'--mount',f'type=bind,source={state_file},target=/test/state.json,readonly',tools,'object_lock_fixture.py','/test/state.json')
            if 'PASS: version-specific bytes and COMPLIANCE retention survive' not in result.stdout:
                raise RuntimeError('Restart capability proof did not run')
            print(result.stdout.strip(),flush=True)
        print('PASS: synthetic provider capability gate only; not legal certification, EvidenceStore implementation or off-PC durability',flush=True)
    finally:
        run('docker','rm','-f',storage,ok=False)
        run('docker','network','rm',name,ok=False)
        # This exact UUID volume was created above; no existing volume is used.
        run('docker','volume','rm',volume,ok=False)
        run('docker','image','rm',tools,ok=False)


if __name__=='__main__':
    main()
