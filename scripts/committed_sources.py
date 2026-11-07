"""Read exact committed source bytes from Git or a checked frozen snapshot.

The bundle checksum detects accidental source substitution; a local checksum is
not an independent witness or signature for legal evidence.
"""
import hashlib
import json
from pathlib import Path
import re
import subprocess


def archive(source, expected_revision):
    source = Path(source)
    if not isinstance(expected_revision, str) or not re.fullmatch(r'[0-9a-f]{40}', expected_revision) or expected_revision == '0' * 40:
        raise ValueError('Pinned source revision required')
    if (source / '.git').exists():
        if subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain'], text=True).strip():
            raise ValueError('Committed source must be clean')
        revision = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
        if revision != expected_revision:
            raise ValueError('Source differs from the pinned revision')
        # Export committed bytes: a Windows autocrlf checkout would otherwise
        # convert text files to CRLF inside the archive.
        return subprocess.check_output(['git', '-c', 'core.autocrlf=false', '-C', str(source), 'archive', '--format=tar', revision])
    if source.parent.name != 'sources':
        raise ValueError('Git metadata or explicit snapshot bundle required')
    bundle = source.parent.parent.resolve()
    manifest_path = bundle / 'archive-manifest.json'
    if not manifest_path.resolve().is_relative_to(bundle):
        raise ValueError('Source archive manifest escaped snapshot storage')
    if manifest_path.stat().st_size > 65536:
        raise ValueError('Invalid source archive manifest')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    entry = manifest.get(source.name) if isinstance(manifest, dict) else None
    if not isinstance(entry, dict) or set(entry) != {'revision', 'sha256'} or entry['revision'] != expected_revision:
        raise ValueError('Snapshot differs from the pinned revision')
    path = bundle / 'archives' / (source.name + '.tar')
    if not path.resolve().is_relative_to(bundle / 'archives'):
        raise ValueError('Source archive escaped snapshot storage')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != entry['sha256']:
        raise ValueError('Source archive checksum differs')
    return raw
