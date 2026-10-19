"""Pure release checks shared by hosted preflight and target deployment."""
import hashlib
import json
import re
from pathlib import Path

IMAGES = {"AUTH_IMAGE": "rac-auth-service", "USER_IMAGE": "rac-user-service",
          "MATCH_IMAGE": "rac-match-service", "FRONTEND_IMAGE": "rac-frontend-flutter"}

def load_release(root, release_id):
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,79}", release_id):
        raise RuntimeError("Invalid release id")
    path = Path(root) / "releases" / (release_id + ".json")
    if not path.is_file():
        raise RuntimeError("Release manifest does not exist on this branch")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or set(manifest) != set(IMAGES):
        raise RuntimeError("Release must contain exactly the four application images")
    for key, repo in IMAGES.items():
        if not isinstance(manifest[key], str) or not re.fullmatch(r"ghcr\.io/cazocarma/" + repo + r"@sha256:[a-f0-9]{64}", manifest[key]):
            raise RuntimeError("Immutable image required: " + key)
    return manifest

def infrastructure_digest(root):
    root = Path(root)
    # Every local runtime input used by Make/Compose must be covered by QA proof.
    files = [root / "Makefile", root / "nginx/environments.conf",
             root / "scripts/deploy.py", root / "scripts/release_policy.py"]
    files += list(root.glob("compose*.yaml")) + list(root.glob("docker-compose.*.yaml"))
    files += [p for folder in ("db", "observability") for p in (root / folder).rglob("*") if p.is_file()]
    digest = hashlib.sha256()
    for file in sorted(set(files)):
        digest.update(file.relative_to(root).as_posix().encode() + b"\0" + file.read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()
