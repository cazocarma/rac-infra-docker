"""Compare generated private dependency sources with the pinned platform checkout.

Normal Go builds validate modules.txt consistency. This additional integrated
gate detects manual edits or omitted source files in the shared rules without
giving every consumer CI a credential for another private repository.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
MODULE = 'github.com/cazocarma/rac-platform'


def check(workspace):
    platform = workspace / 'rac-platform'
    if not (platform / 'go.mod').is_file():
        raise ValueError('Pinned platform checkout required')
    versions = set()
    for name in ('rac-user-service', 'rac-match-service', 'rac-chat-service'):
        service = workspace / name
        match = re.search(r'^\s*' + re.escape(MODULE) + r'\s+(v[0-9]+\.[0-9]+\.[0-9]+)\s*$', (service / 'go.mod').read_text(), re.M)
        if not match:
            raise ValueError(name + ': immutable shared module version required')
        version = match[1]
        versions.add(version)
        manifest = (service / 'vendor/modules.txt').read_text()
        if '# ' + MODULE + ' ' + version + '\n' not in manifest:
            raise ValueError(name + ': vendor module version mismatch')
        generated = service / 'vendor' / MODULE
        files = list(generated.rglob('*.go'))
        if not files:
            raise ValueError(name + ': shared dependency missing')
        for directory in {file.parent for file in files}:
            original = platform / directory.relative_to(generated)
            expected = {f.name for f in original.glob('*.go') if not f.name.endswith('_test.go')}
            if expected != {f.name for f in directory.glob('*.go')}:
                raise ValueError(name + ': shared package source set differs from pinned revision')
        for file in files:
            original = platform / file.relative_to(generated)
            if not original.is_file() or file.read_text(encoding='utf-8') != original.read_text(encoding='utf-8'):
                raise ValueError(name + ': generated shared dependency differs from pinned revision')
    if len(versions) != 1:
        raise ValueError('Consumers must agree on the shared module version')


if __name__ == '__main__':
    check(ROOT)
    print('PASS: generated shared rules match pinned platform sources in all consumers')
