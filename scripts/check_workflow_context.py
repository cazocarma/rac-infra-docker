"""Validate repository-local script paths using actual GitHub run-directory precedence."""
from pathlib import Path, PurePosixPath
import re
import yaml

SCRIPTS = re.compile(r"(?<![\w/.-])(?:scripts/|scripts(?:\s|$))")


def validate(workflow):
    errors = []
    global_directory = workflow.get('defaults', {}).get('run', {}).get('working-directory', '.')
    for name, job in workflow.get('jobs', {}).items():
        default = job.get('defaults', {}).get('run', {}).get('working-directory', global_directory)
        checkout = None
        for step in job.get('steps', []):
            if step.get('uses', '').startswith('actions/checkout@') and not step.get('with', {}).get('repository'):
                checkout = step.get('with', {}).get('path', '.')
            if 'run' not in step or not SCRIPTS.search(step['run']):
                continue
            directory = step.get('working-directory', default)
            if checkout is None or PurePosixPath(directory) != PurePosixPath(checkout):
                errors.append(f'{name}: local scripts run from {directory!r}, own checkout is {checkout!r}')
    return errors


def main():
    root = Path(__file__).resolve().parents[1]
    errors = []
    for path in sorted((root / '.github/workflows').glob('*.y*ml')):
        errors.extend(f'{path.name}: {error}' for error in validate(yaml.safe_load(path.read_text(encoding='utf-8'))))
    if errors:
        raise SystemExit('\n'.join(errors))
    print('PASS: local workflow scripts use their own checked-out repository directory')


if __name__ == '__main__':
    main()
