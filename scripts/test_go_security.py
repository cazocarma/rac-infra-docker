"""Scan current Go call paths using a pinned local-container scanner.

No .env/private Git credentials or source uploads. The public Go vulnerability
database supplies advisories. Optional payment checkout is scanned when present.
An unreachable-module advisory is reported by govulncheck, never suppressed.
"""
from pathlib import Path
import subprocess
from check_go_vendor import CONSUMERS

ROOT=Path(__file__).resolve().parents[2]
IMAGE='golang:1.27.3'
SCANNER='golang.org/x/vuln/cmd/govulncheck@v1.9.0'


def main():
    required=('rac-platform','rac-auth-service',*CONSUMERS)
    names=(*required,'rac-payment-service') if (ROOT/'rac-payment-service/go.mod').is_file() else required
    for name in names:
        source=ROOT/name
        if not (source/'go.mod').is_file():
            raise RuntimeError('Go security checkout missing: '+name)
        mode='vendor' if (source/'vendor/modules.txt').is_file() else 'readonly'
        command='cd /tmp && GOBIN=/tmp/bin go install '+SCANNER+' && cd /source && GOFLAGS=-mod='+mode+' /tmp/bin/govulncheck ./...'
        result=subprocess.run(['docker','run','--rm',
            '--mount',f'type=bind,source={source},target=/source,readonly',
            '-v','rac-quota-go-cache:/go/pkg/mod','-v','rac-quota-go-build:/root/.cache/go-build',
            IMAGE,'sh','-c',command],capture_output=True,text=True,encoding='utf-8',timeout=600)
        print(name,flush=True)
        print(result.stdout,flush=True)
        if result.returncode:
            raise RuntimeError('Go security scan failed for '+name+'\n'+result.stderr[-2000:])
    print('PASS: all available RAC Go modules scanned with patched toolchain; no reachable advisories reported',flush=True)


if __name__=='__main__':
    main()
