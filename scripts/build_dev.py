"""Build one Compose service at a time on the development workstation.

Compose/Bake can launch all Go and Flutter compilers together. Separate build
invocations bound that concurrency across Compose versions, including Bake.
The resolved model contains secrets: capture it and never print it.
"""
import json
import subprocess
import sys


def build(command, run=subprocess.run):
    resolved = run(command + ['config', '--format', 'json'], capture_output=True, text=True, check=True)
    model = json.loads(resolved.stdout)
    if model.get('name') != 'rac-dev':
        raise RuntimeError('Workstation builds are DEV-only')
    for name, service in model['services'].items():
        if 'build' in service and not service.get('profiles'):
            run(command + ['build', name], check=True)


if __name__ == '__main__':
    build(sys.argv[1:])
