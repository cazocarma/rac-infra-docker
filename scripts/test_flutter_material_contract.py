"""Run the actual frontend Material semantics contract from its Git snapshot."""
from pathlib import Path
import subprocess
from check_flutter_material_contract import check


def main():
    root = Path(__file__).resolve().parents[1]
    frontend = root.parent / 'rac-frontend-flutter'
    revision = subprocess.check_output(['git', '-C', str(frontend), 'rev-parse', 'HEAD'], text=True).strip()
    dirty = subprocess.check_output(['git', '-C', str(frontend), 'status', '--porcelain'], text=True).strip()
    if dirty:
        raise RuntimeError('Material contract requires a clean frontend Git snapshot')
    archive = subprocess.check_output(['git', '-C', str(frontend), 'archive', '--format=tar', revision])
    result = subprocess.run([
        'docker', 'run', '--rm', '-i', '-v', 'rac-flutter-pub-cache:/root/.pub-cache',
        'ghcr.io/cirruslabs/flutter:3.44.0', 'sh', '-c',
        'mkdir /app && tar -xf - -C /app && cd /app && flutter pub get && flutter test test/material_browser_contract_test.dart',
    ], input=archive, capture_output=True, timeout=600)
    output = result.stdout.decode('utf-8', errors='replace') + result.stderr.decode('utf-8', errors='replace')
    evidence = root / '.local/material-browser-contract.log'
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text('SOURCE ' + revision + '\n' + output, encoding='utf-8')
    if result.returncode:
        raise RuntimeError('Material semantics test failed; see .local/material-browser-contract.log\n' + output[-2500:])
    check(output)
    print('PASS: browser expectations match actual es/en Material semantics at frontend ' + revision)


if __name__ == '__main__':
    main()
