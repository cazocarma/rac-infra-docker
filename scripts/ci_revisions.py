"""Validate immutable integration inputs before fetching application repositories."""
import json
import os
import re
from pathlib import Path
from check_ci_access import REPOSITORIES

def load_revisions(path):
    refs = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(refs, dict) or set(refs) != set(REPOSITORIES):
        raise ValueError("Expected exactly the configured companion repositories")
    if any(not isinstance(ref, str) or not re.fullmatch(r"[a-f0-9]{40}", ref) for ref in refs.values()):
        raise ValueError("Every companion revision must be a full commit SHA")
    return refs

if __name__ == "__main__":
    refs = load_revisions(Path(__file__).resolve().parents[1] / "ci/companion-revisions.json")
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write("repositories=" + json.dumps(refs, separators=(",", ":")) + "\n")
