"""Resolve fixture commands without letting a disposable run fall back to DEV."""
import json
import os
from pathlib import Path
import re

PROJECT = re.compile(r'rac-browser-e2e-[0-9a-f]{12}')


def command(root, state_file=None):
    root = Path(root).resolve()
    if state_file is None:
        state_file = os.environ.get('RAC_BROWSER_LAB_STATE')
    if state_file is not None:
        if not state_file:
            raise RuntimeError('Explicit browser lab state cannot be empty')
        path = Path(state_file).resolve()
        if (path.name != 'state.json' or not PROJECT.fullmatch(path.parent.name)
                or root.name != 'rac-infra-docker' or root.parent.name != 'sources'
                or root.parent.parent != path.parent):
            raise RuntimeError('Owned browser lab snapshot required')
        state = json.loads(path.read_text(encoding='utf-8'))
        if state.get('project') != path.parent.name or state.get('source_root') != str(root):
            raise RuntimeError('Browser lab identity mismatch')
        if not (path.parent / 'fixture.env').is_file() or not (path.parent / 'compose.json').is_file():
            raise RuntimeError('Browser lab configuration is incomplete')
        return ['docker', 'compose', '--env-file', str(path.parent / 'fixture.env'),
                '-p', state['project'], '--profile', 'tools', '--profile', 'tests',
                '-f', str(path.parent / 'compose.json')]
    result = ['docker', 'compose', '--env-file', 'envs/.env.dev', '-p', 'rac-dev',
              '-f', 'compose.yaml', '-f', 'docker-compose.dev.yaml',
              '-f', 'compose.observability.yaml', '-f', 'compose.tests.yaml']
    if (root / 'envs/.env.photos-s3').exists():
        result += ['-f', 'compose.photos-s3.yaml']
    if (root / 'envs/.env.backups').exists():
        result += ['--env-file', 'envs/.env.backups', '-f', 'compose.backups.yaml']
    return result
