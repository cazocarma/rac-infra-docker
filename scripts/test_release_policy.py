import json
from pathlib import Path
import tempfile
import unittest
import hashlib
import io
import os
import runpy
import shutil
from unittest.mock import patch
from release_policy import IMAGES, load_release, infrastructure_digest
from database_roles import ROLES

class ReleasePolicyTests(unittest.TestCase):
    def test_prd_requires_exact_successful_qa_before_any_host_command(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = Path(__file__).resolve().parent.parent
            for name in ("Makefile", "nginx/environments.conf", "scripts/deploy.py", "scripts/release_policy.py", "scripts/configure_messaging.py", "scripts/build_dev.py", "scripts/database_roles.py", "tools/Dockerfile", "compose.yaml", "db/bootstrap/001-keycloak.sh"):
                dest = root / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source / name, dest)
            (root / "releases").mkdir()
            manifest = {key: "ghcr.io/cazocarma/" + repo + "@sha256:" + "a" * 64 for key, repo in IMAGES.items()}
            (root / "releases/demo.json").write_text(json.dumps(manifest))
            envfile = root / "target.env"
            scoped="\n".join(key+"=postgresql://"+role+":synthetic-independent-"+role+"-123456@postgres:5432/rac_prd?sslmode=disable" for key,role in ROLES.items())
            envfile.write_text("RAC_ENV=prd\nPOSTGRES_DB=rac_prd\nMIGRATION_DB_USER=rac_migrator\nMIGRATION_DB_PASSWORD=synthetic-independent-migrator-123456\n"+scoped+"\n" + "\n".join(k + "=" + v for k, v in manifest.items()))
            proof = {"release_sha256": hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest(), "infra_sha256": infrastructure_digest(root)}
            available = False
            events = []
            def github(request, **kwargs):
                path = request.full_url.split("/repos/owner/infra")[-1]
                events.append((request.get_method(), path))
                if path.startswith("/environments/"): value = {"protection_rules": [{"type": "required_reviewers", "reviewers": [{}]}]}
                elif path.startswith("/deployments?"): value = [{"id": 1, "payload": proof}] if available else []
                elif request.get_method() == "GET" and path.endswith("/statuses"): value = [{"state": "success"}]
                elif path == "/deployments": value = {"id": 2}
                else: value = {}
                return io.BytesIO(json.dumps(value).encode())
            env = dict(DEPLOY_ENVIRONMENT="prd", RELEASE_ID="demo", CONFIRMATION="DEPLOY prd", GITHUB_REPOSITORY="owner/infra", GITHUB_SHA="approved-sha", GITHUB_TOKEN="synthetic", RAC_ENV_FILE=str(envfile))
            with patch.dict(os.environ, env), patch("urllib.request.urlopen", side_effect=github), patch("subprocess.run") as host:
                with self.assertRaisesRegex(RuntimeError, "successful QA"):
                    runpy.run_path(str(root / "scripts/deploy.py"))
                host.assert_not_called()
                self.assertFalse(any(method == "POST" for method, _ in events))
                available = True
                runpy.run_path(str(root / "scripts/deploy.py"))
                commands = [call.args[0] for call in host.call_args_list]
                self.assertEqual([cmd[-1] for cmd in commands[1:]], ["config", "migration-validate", "pull", "up", "observe", "check"])
                self.assertTrue(any(path == "/deployments/2/statuses" for _, path in events))
                host.reset_mock()
                with (root / "db/bootstrap/001-keycloak.sh").open("a") as file: file.write("\n# changed after QA\n")
                with self.assertRaisesRegex(RuntimeError, "successful QA"):
                    runpy.run_path(str(root / "scripts/deploy.py"))
                host.assert_not_called()

    def test_only_immutable_expected_images(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "releases").mkdir()
            path = root / "releases/demo.json"
            manifest = {key: "ghcr.io/cazocarma/" + repo + "@sha256:" + "a" * 64 for key, repo in IMAGES.items()}
            path.write_text(json.dumps(manifest))
            self.assertEqual(load_release(root, "demo"), manifest)
            for invalid in ("../demo", "../../escape", "Demo", "", "missing"):
                with self.assertRaises(RuntimeError): load_release(root, invalid)
            for bad in ({}, {k:v for k,v in manifest.items() if k != "CHAT_IMAGE"}, {**manifest, "EXTRA": "image"}, {**manifest, "USER_IMAGE": "ghcr.io/cazocarma/rac-user-service:latest"}, {**manifest, "USER_IMAGE": None}):
                path.write_text(json.dumps(bad))
                with self.assertRaises(RuntimeError): load_release(root, "demo")

    def test_qa_proof_covers_bootstrap_and_compose_inputs(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ("Makefile", "nginx/environments.conf", "scripts/deploy.py", "scripts/release_policy.py", "scripts/configure_messaging.py", "scripts/build_dev.py", "scripts/database_roles.py", "tools/Dockerfile", "rabbitmq/rabbitmq.conf", "compose.tests.yaml", "db/bootstrap/001-keycloak.sh"):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"original\n")
            original = infrastructure_digest(root)
            for name in ("compose.tests.yaml", "db/bootstrap/001-keycloak.sh", "scripts/release_policy.py", "scripts/configure_messaging.py", "scripts/build_dev.py", "scripts/database_roles.py", "tools/Dockerfile", "rabbitmq/rabbitmq.conf"):
                path = root / name
                path.write_bytes(b"changed\n")
                self.assertNotEqual(original, infrastructure_digest(root))
                path.write_bytes(b"original\r\n")
                self.assertEqual(original, infrastructure_digest(root))

if __name__ == "__main__": unittest.main()
