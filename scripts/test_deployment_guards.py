"""Run fail-closed deployment preflights without credentials or network calls."""
from pathlib import Path
import os
import subprocess
import sys
script = Path(__file__).with_name("deploy.py")
for environment, confirmation, release in [("dev","DEPLOY dev","demo"),("prd","","demo"),("qa","DEPLOY qa","../../escape")]:
    env = dict(os.environ, DEPLOY_ENVIRONMENT=environment, CONFIRMATION=confirmation, RELEASE_ID=release, PYTHONOPTIMIZE="1")
    result = subprocess.run([sys.executable, str(script)], env=env, capture_output=True, text=True)
    if result.returncode == 0: raise RuntimeError("Deployment gate was bypassed")
    if "GITHUB_TOKEN" in result.stderr: raise RuntimeError("Gate reached authentication before validation")
print("PASS: invalid environment, missing confirmation and path traversal rejected even with Python optimization")
