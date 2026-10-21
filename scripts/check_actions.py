"""Reject unreviewed Actions pins, obsolete runtimes and floating Linux images."""
import argparse
import json
import re
from pathlib import Path

USES=re.compile(r"^\s*(?:-\s*)?uses:\s*([^\s#]+)",re.MULTILINE)

def validate(root, pins, runtimes):
    errors=[]
    for path in sorted((Path(root)/'.github/workflows').glob('*')):
        if path.suffix not in ('.yml','.yaml'):continue
        text=path.read_text(encoding='utf-8')
        if 'ubuntu-latest' in text:errors.append(f'{path}: pin the Linux runner image')
        if any(flag in text for flag in ('FORCE_JAVASCRIPT_ACTIONS_TO_NODE24','ACTIONS_ALLOW_USE_UNSECURE_NODE_VERSION')):
            errors.append(f'{path}: update the action instead of overriding its runtime')
        for action in USES.findall(text):
            if action.startswith('./'):continue
            name,separator,sha=action.partition('@')
            record=runtimes.get(name,{})
            if not separator or not re.fullmatch('[a-f0-9]{40}',sha) or pins.get(name)!=sha:
                errors.append(f'{path}: unreviewed action reference {action}')
            elif record.get('sha')!=sha or record.get('runtime') not in ('node24','composite','docker'):
                errors.append(f'{path}: missing supported runtime audit for {name}')
    return errors

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace',type=Path,help='also inspect cloned sibling repositories')
    args=parser.parse_args()
    own=Path(__file__).resolve().parents[1]
    pins=json.loads((own/'docs/action-pins.json').read_text(encoding='utf-8'))
    runtimes=json.loads((own/'docs/action-runtimes.json').read_text(encoding='utf-8'))
    roots=sorted(args.workspace.glob('rac-*')) if args.workspace else [own]
    errors=[error for root in roots for error in validate(root,pins,runtimes)]
    if errors:raise SystemExit('\n'.join(errors))
    print('PASS: reviewed immutable actions, supported runtimes and explicit Linux runners')
if __name__=='__main__':main()
