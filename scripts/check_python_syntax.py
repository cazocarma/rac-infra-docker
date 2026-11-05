"""Parse repository Python tools without executing them or writing bytecode."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def check(root):
    files = sorted(path for folder in ('scripts', 'tools')
                   for path in (root / folder).rglob('*.py') if not path.is_symlink())
    errors = []
    for path in files:
        relative = path.relative_to(root).as_posix()
        try:
            compile(path.read_bytes(), relative, 'exec')
        except SyntaxError as error:
            # Report locations, never source contents/configuration values.
            errors.append(f'{relative}:{error.lineno}: invalid Python syntax')
        except OSError:
            errors.append(f'{relative}: Python source unavailable')
    if not files:
        errors.append('No repository Python tools found')
    return len(files), errors


if __name__ == '__main__':
    count, failures = check(ROOT)
    for failure in failures:
        print(failure, file=sys.stderr)
    if failures:
        raise SystemExit(1)
    print(f'PASS: {count} Python sources parsed without executing tools')
