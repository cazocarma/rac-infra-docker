"""Local OCR/normalization/shared-detector proof with synthetic images only.

No .env, credentials, DEV resources or outbound network in the test container.
"""
from pathlib import Path
import subprocess
import uuid

ROOT=Path(__file__).resolve().parents[1]


def run(*args,ok=True):
    result=subprocess.run(args,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=600)
    if ok and result.returncode:
        failures='\n'.join(line for line in result.stdout.splitlines() if '.go:' in line or 'FAIL' in line)
        raise RuntimeError('Local photo analysis proof failed\n'+failures+'\n'+result.stdout[-2000:]+result.stderr[-2000:])
    return result


def main():
    image='rac-photo-analysis-test-'+uuid.uuid4().hex[:12]
    try:
        run('docker','build','-q','-t',image,'-f',str(ROOT/'tools/photo-processing/Dockerfile'),str(ROOT))
        image_id=run('docker','image','inspect','--format','{{.Id}}',image).stdout.strip()
        result=run('docker','run','--rm','--network','none','--cpus','2','--memory','1536m',
            '--mount',f'type=bind,source={ROOT.parent/"rac-user-service"},target=/source,readonly',
            '-v','rac-quota-go-cache:/go/pkg/mod','-v','rac-quota-go-build:/root/.cache/go-build',
            '-e','RAC_TESSERACT_TEST=1',image,'sh','-c',
            'cp -a /source /tmp/rac && cd /tmp/rac && go test -race -count=1 -v '
            './internal/photoassets ./internal/contentproof ./internal/photos ./internal/listings')
        for required in ('TestPhotoProcessingTesseract/contact_border','TestPhotoProcessingTesseract/benign',
                         'TestPhotoProcessingPreservesFrameAndPrivateProof','TestPhotoProcessingFailsClosed',
                         'TestFreezeBoundsAndSnapshotsAnalysis'):
            if '--- PASS: '+required not in result.stdout:
                raise RuntimeError('Required photo analysis proof skipped: '+required)
        print('IMAGE '+image_id,flush=True)
        print('PASS: real local Tesseract on full-frame synthetic contact/benign images, metadata removal, shared signals, immutable private proof and fail-closed errors',flush=True)
    finally:
        run('docker','image','rm',image,ok=False)


if __name__=='__main__':
    main()
