"""DEV-only fault test: broker outage does not roll back a booking transition.

Stops only this Compose project's broker and always starts it again. Uses a
disposable OIDC buyer; the API never receives fixture identity overrides.
"""
from pathlib import Path
import json
import subprocess

ROOT = Path(__file__).resolve().parent.parent
COMMAND = ['docker','compose','--env-file','envs/.env.dev','-p','rac-dev',
    '-f','compose.yaml','-f','docker-compose.dev.yaml','-f','compose.tests.yaml']


def run(*args):
    result = subprocess.run(COMMAND + list(args), cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
    if result.returncode:
        raise RuntimeError('DEV recovery test command failed: ' + result.stderr[-600:])
    return result.stdout.strip()


def fixture(*args):
    return run('run','--rm','--no-deps','test-integration','python','test_chat_fixture.py',*args)


def main():
    # Check only the required safe selector; never echo the resolved secret model.
    model = json.loads(run('--profile','tests','config','--format','json'))
    if model['name'] != 'rac-dev' or model['services']['test-integration']['environment']['RAC_ENV'] != 'dev':
        raise RuntimeError('Fault injection is DEV-only')
    info = None
    try:
        info = json.loads(fixture())
        run('stop','rabbitmq')
        fixture('cancel-queued',info['username'],info['booking'])
        queued = json.loads(fixture('delivery-status',info['username'],info['booking']))
        assert queued == {'pending': 1, 'notices': 0}, queued
        run('start','rabbitmq')
        fixture('wait-cancelled',info['username'],info['booking'])
        delivered = json.loads(fixture('delivery-status',info['username'],info['booking']))
        assert delivered == {'pending': 0, 'notices': 2}, delivered
        print('PASS: booking change committed with broker offline; recovery delivered once per participant')
    finally:
        run('start','rabbitmq')
        if info:
            fixture('cleanup',info['username'])


if __name__ == '__main__':
    main()
