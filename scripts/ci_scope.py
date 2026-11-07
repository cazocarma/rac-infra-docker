"""Decide how much of the CI suite a run needs. Fails safe to the full suite.

- pull_request: documentation-only changes (every path is Markdown outside
  .github/) skip the heavy jobs; anything else runs everything.
- push: a fast-forward brings exactly a commit whose pull_request run already
  succeeded, so the identical tree is not tested again. Otherwise as above.
- schedule / workflow_dispatch: full suite plus the standing measurements.

Writes `full`, `measure` and `reason` to GITHUB_OUTPUT. Any API or parsing
problem selects the full suite; this script never makes CI weaker silently.
"""
import json
import os
import re
import sys
import urllib.parse
import urllib.request

WORKFLOW = '.github/workflows/ci.yml'
MAX_FILES = 3000


def docs_only(paths):
    return bool(paths) and all(p.endswith('.md') and not p.startswith('.github/') for p in paths)


def api(path, token, repository):
    request = urllib.request.Request(f'https://api.github.com/repos/{repository}/{path}', headers={
        'Accept': 'application/vnd.github+json', 'Authorization': 'Bearer ' + token,
        'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'rac-ci-scope'})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read())


def pull_request_files(number, token, repository):
    paths = []
    for page in range(1, MAX_FILES // 100 + 1):
        batch = api(f'pulls/{number}/files?per_page=100&page={page}', token, repository)
        paths += [item['filename'] for item in batch]
        if len(batch) < 100:
            return paths
    return None  # Too many files to be sure: run everything.


def compare_files(before, after, token, repository):
    if not re.fullmatch('[0-9a-f]{40}', before) or set(before) == {'0'}:
        return None
    body = api(f'compare/{before}...{after}', token, repository)
    files = body.get('files')
    if files is None or len(files) >= 300:  # The compare API truncates at 300 files.
        return None
    return [item['filename'] for item in files]


def verified_in_pull_request(sha, token, repository):
    query = urllib.parse.urlencode({'head_sha': sha, 'event': 'pull_request', 'status': 'success', 'per_page': 50})
    runs = api(f'actions/runs?{query}', token, repository).get('workflow_runs', [])
    return any(run.get('path') == WORKFLOW and run.get('head_sha') == sha and run.get('conclusion') == 'success'
               for run in runs)


def decide(event_name, event, sha, token, repository):
    if event_name in ('schedule', 'workflow_dispatch'):
        return True, True, 'scheduled full suite with measurements'
    if event_name == 'pull_request':
        paths = pull_request_files(event['pull_request']['number'], token, repository)
        if paths is not None and docs_only(paths):
            return False, False, 'documentation-only pull request'
        return True, False, 'code or configuration changed'
    if event_name == 'push':
        if verified_in_pull_request(sha, token, repository):
            return False, False, 'identical commit already passed its pull request run'
        paths = compare_files(event.get('before', ''), sha, token, repository)
        if paths is not None and docs_only(paths):
            return False, False, 'documentation-only push'
        return True, False, 'push not verified by a pull request run'
    return True, False, 'unrecognized event'


def main():
    full, measure, reason = True, False, 'scope unavailable; running everything'
    try:
        event = json.loads(open(os.environ['GITHUB_EVENT_PATH'], encoding='utf-8').read())
        full, measure, reason = decide(os.environ['GITHUB_EVENT_NAME'], event, os.environ['GITHUB_SHA'],
                                       os.environ['GITHUB_TOKEN'], os.environ['GITHUB_REPOSITORY'])
    except Exception as error:  # Fail safe: never skip on doubt.
        print('Scope check failed (' + type(error).__name__ + '); running the full suite', file=sys.stderr)
        full, measure, reason = True, False, 'scope unavailable; running everything'
    with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as output:
        output.write(f'full={str(full).lower()}\nmeasure={str(measure).lower()}\n')
    print(f'CI scope: full={full} measure={measure} ({reason})')


if __name__ == '__main__':
    main()
