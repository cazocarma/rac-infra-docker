"""Read-only preflight; never invokes Docker or creates deployments."""
import json
import os
from pathlib import Path
import urllib.request
from release_policy import load_release

target = os.environ["DEPLOY_ENVIRONMENT"]
if target not in ("qa", "prd") or os.environ["GITHUB_REF_NAME"] != target:
    raise RuntimeError("Deployment must run from the matching qa/prd branch")
if os.environ["CONFIRMATION"] != "DEPLOY " + target:
    raise RuntimeError("Explicit confirmation required")
load_release(Path(__file__).resolve().parent.parent, os.environ["RELEASE_ID"])
request = urllib.request.Request(
    "https://api.github.com/repos/" + os.environ["GITHUB_REPOSITORY"] + "/environments/" + target,
    headers={"Authorization": "Bearer " + os.environ["GITHUB_TOKEN"], "Accept": "application/vnd.github+json"})
with urllib.request.urlopen(request, timeout=20) as response:
    settings = json.load(response)
if not any(rule.get("type") == "required_reviewers" and rule.get("reviewers") for rule in settings.get("protection_rules", [])):
    raise RuntimeError("Configure required reviewers before requesting a deployment")
print("PASS: branch, confirmation, immutable manifest and environment reviewers")
