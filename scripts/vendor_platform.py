"""Generate consumer vendor from an immutable, clean local platform release.
No private Git credential is mounted into Docker. Public modules use Go's proxy
and checksum database; only the exact private module bypasses public sumdb.
"""
from pathlib import Path
import argparse
import json
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
MODULE = 'github.com/cazocarma/rac-platform'
CONSUMERS = ('rac-user-service','rac-match-service','rac-chat-service','rac-alert-service')

def run(*args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, **kwargs).stdout

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('version', help='Existing immutable platform tag, e.g. v0.10.0')
    args = parser.parse_args()
    if not re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+', args.version):
        parser.error('A stable semantic version tag is required')
    platform = ROOT / 'rac-platform'
    def git(*args):
        return run('git','-C',str(platform),*args).decode('utf-8').strip()
    if git('status','--porcelain'):
        raise RuntimeError('Platform must be clean before generating a release dependency')
    revision = git('rev-parse',args.version+'^{commit}')
    if revision != git('rev-parse','HEAD'):
        raise RuntimeError('Platform HEAD must match the selected tag')
    for name in CONSUMERS:
        if not (ROOT/name/'go.mod').is_file():
            raise RuntimeError('Consumer checkout required: '+name)
    with tempfile.TemporaryDirectory(prefix='rac-platform-proxy-') as directory:
        proxy = Path(directory)
        versions = proxy / MODULE / '@v'
        versions.mkdir(parents=True)
        (versions/(args.version+'.mod')).write_bytes(run('git','-C',str(platform),'show',revision+':go.mod'))
        (versions/(args.version+'.info')).write_text(json.dumps({'Version':args.version,'Time':git('show','-s','--format=%cI',revision)}),encoding='utf-8')
        (versions/(args.version+'.zip')).write_bytes(run('git','-C',str(platform),'archive','--format=zip','--prefix='+MODULE+'@'+args.version+'/',revision))
        for name in CONSUMERS:
            command = 'go mod edit -require='+MODULE+'@'+args.version+' && go mod download '+MODULE+' && go mod vendor'
            result = subprocess.run(['docker','run','--rm','--mount',f'type=bind,source={proxy},target=/proxy,readonly',
                '--mount',f'type=bind,source={ROOT/name},target=/src','-w','/src',
                '-v','rac-quota-go-cache:/go/pkg/mod','-e','GONOPROXY=none',
                '-e','GONOSUMDB='+MODULE,'-e','GOPROXY=file:///proxy,https://proxy.golang.org',
                'golang:1.27.2','sh','-c',command],capture_output=True,text=True)
            if result.returncode:
                raise RuntimeError(name+': Go dependency generation failed\n'+result.stderr[-2000:])
            print('Generated '+name+' vendor from '+args.version+' ('+revision[:12]+')',flush=True)
    from check_go_vendor import check
    check(ROOT)
    print('PASS: all generated consumer dependencies match the immutable platform checkout')

if __name__ == '__main__':
    main()
