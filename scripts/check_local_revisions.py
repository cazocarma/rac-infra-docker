"""Read-only preflight for a candidate multi-repository manifest.

Does not fetch, commit, push, retag, change CI inputs or read credentials.
"""
import argparse
from pathlib import Path
import re
import subprocess
from ci_revisions import load_revisions
from check_ci_access import REPOSITORIES

CONSUMERS = ('rac-user-service', 'rac-match-service', 'rac-chat-service', 'rac-alert-service', 'rac-admin-service')
MODULE = 'github.com/cazocarma/rac-platform'


def git(directory, *arguments):
    return subprocess.run(['git', '-C', str(directory), *arguments], check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True).stdout.strip()


def mismatches(refs, workspace, reader=git):
    if set(refs) != set(REPOSITORIES):
        raise ValueError('Exact companion repository set required')
    errors = []
    for repository in REPOSITORIES:
        directory = workspace / repository
        try:
            if reader(directory, 'rev-parse', 'HEAD') != refs[repository]:
                errors.append(repository + ': HEAD differs from candidate')
            if reader(directory, 'status', '--porcelain', '--untracked-files=normal'):
                errors.append(repository + ': uncommitted changes')
        except (OSError, subprocess.CalledProcessError):
            errors.append(repository + ': local checkout unavailable')
    versions = set()
    for repository in CONSUMERS:
        try:
            source = (workspace / repository / 'go.mod').read_text(encoding='utf-8')
            matches = re.findall(r'^\s*(?:require\s+)?' + re.escape(MODULE) + r'\s+(v\d+\.\d+\.\d+)\s*(?:// indirect)?\s*$', source, re.M)
            if len(matches) != 1 or any(MODULE in line and '=>' in line for line in source.splitlines()):
                errors.append(repository + ': exact platform requirement without replacement required')
                continue
            version = matches[0]
            versions.add(version)
            vendor = (workspace / repository / 'vendor/modules.txt').read_text(encoding='utf-8')
            if '# ' + MODULE + ' ' + version not in vendor.splitlines():
                errors.append(repository + ': vendor platform version differs')
        except OSError:
            errors.append(repository + ': module/vendor manifest unavailable')
    if len(versions) != 1:
        errors.append('Platform consumers do not share one exact version')
    else:
        version = next(iter(versions))
        try:
            if reader(workspace / 'rac-platform', 'rev-parse', version + '^{commit}') != refs['rac-platform']:
                errors.append('Platform tag does not resolve to candidate commit')
        except (OSError, subprocess.CalledProcessError):
            errors.append('Platform version tag unavailable locally')
    return errors


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--workspace', type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    failures = mismatches(load_revisions(args.manifest), args.workspace.resolve())
    if failures:
        for failure in failures:
            print('FAIL: ' + failure)
        raise SystemExit(1)
    print('PASS: candidate matches clean local heads, one platform version, vendor metadata and immutable tag')
    print('Remote availability, complete vendor content and integrated artifact/runtime behaviour are separate gates')
