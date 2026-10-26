"""Explicit release promotion. Requires GitHub environment reviewers and QA proof."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import urllib.request
from release_policy import load_release, infrastructure_digest
from database_roles import validate_credentials

def require(condition, message="Deployment gate rejected"):
    if not condition: raise RuntimeError(message)

environment = os.environ["DEPLOY_ENVIRONMENT"]
release_id = os.environ["RELEASE_ID"]
require(environment in {"qa", "prd"})
require(os.environ["CONFIRMATION"] == "DEPLOY " + environment, "Explicit confirmation required")
require(re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,79}", release_id), "Invalid release id")
root = Path(__file__).resolve().parent.parent
manifest = load_release(root, release_id)
release_hash = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
# Promote infrastructure and migration contents as well as application images.
infra_hash = infrastructure_digest(root)
repository = os.environ["GITHUB_REPOSITORY"]
def api(path, data=None):
    req = urllib.request.Request("https://api.github.com/repos/" + repository + path,
        data=None if data is None else json.dumps(data).encode(),
        headers={"Authorization":"Bearer " + os.environ["GITHUB_TOKEN"], "Accept":"application/vnd.github+json", "Content-Type":"application/json"})
    with urllib.request.urlopen(req, timeout=20) as response: return json.load(response)

settings = api("/environments/" + environment)
require(any(r.get("type") == "required_reviewers" and r.get("reviewers") for r in settings.get("protection_rules", [])), "Required reviewers must be configured; refusing unprotected deployment")
if environment == "prd":
    proven = False
    for deployment in api("/deployments?environment=qa&per_page=100"):
        payload = deployment.get("payload", {})
        if isinstance(payload, dict) and payload.get("release_sha256") == release_hash and payload.get("infra_sha256") == infra_hash:
            statuses = api("/deployments/" + str(deployment["id"]) + "/statuses")
            if statuses and statuses[0]["state"] == "success": proven = True; break
    require(proven, "This exact release must have a successful QA deployment")

env_file = Path(os.environ["RAC_ENV_FILE"]).resolve()
require(env_file.is_file(), "Provision env file on target host; do not commit secrets")
values = {}
for line in env_file.read_text().splitlines():
    if "=" in line and not line.lstrip().startswith("#"):
        key, value = line.split("=", 1); values[key.strip()] = value.strip().strip('"').strip("'")
require(values.get("RAC_ENV") == environment)
require(values.get("POSTGRES_DB") == "rac_" + environment, "Wrong target DB")
validate_credentials(values)
for key, image in manifest.items(): require(values.get(key) == image, "Host image manifest differs from approved release")
deployment = api("/deployments", {"ref":os.environ["GITHUB_SHA"], "environment":environment, "auto_merge":False,
    "required_contexts":[], "payload":{"release_sha256":release_hash,"infra_sha256":infra_hash}, "description":"Approved immutable RAC release"})
status_path = "/deployments/" + str(deployment["id"]) + "/statuses"
try:
    api(status_path, {"state":"in_progress"})
    # Environment secrets remain on the target host; login uses token on stdin.
    subprocess.run(["docker","login","ghcr.io","-u",repository.split('/')[0],"--password-stdin"], input=os.environ["GITHUB_TOKEN"], text=True, check=True)
    for target in ["config","migration-validate","pull","up","observe","check"]:
        subprocess.run(["make", "ENV=" + environment, "ENV_FILE=" + str(env_file), target], cwd=root, check=True)
    api(status_path, {"state":"success"})
except Exception:
    api(status_path, {"state":"failure"})
    raise
