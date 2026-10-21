"""Validate all environment models with synthetic credentials; never deploy."""
from pathlib import Path
import json
import os
import subprocess
import tempfile
ROOT = Path(__file__).resolve().parent.parent
for environment in ("dev", "qa", "prd"):
    template = (ROOT / "envs" / (".env." + environment + ".example")).read_text()
    values = {}
    for line in template.splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1); values[key] = value
    for key, value in values.items():
        if not value:
            values[key] = {
                "KEYCLOAK_PUBLIC_URL": "https://auth.example.test",
                "DATABASE_URL": f"postgres://rac:synthetic@postgres:5432/rac_{environment}?sslmode=disable",
            }.get(key, "ghcr.io/cazocarma/synthetic:sha-test" if key.endswith("_IMAGE") else "synthetic-not-a-secret")
    with tempfile.NamedTemporaryFile(mode="w", delete=False, encoding="utf-8") as file:
        file.write("\n".join(key + "=" + value for key, value in values.items())); filename = file.name
    try:
        command = ["docker", "compose", "--env-file", filename, "-p", "rac-" + environment, "-f", "compose.yaml"]
        if environment != "dev": command += ["-f", "compose.release.yaml"]
        command += ["-f", "docker-compose." + environment + ".yaml", "-f", "compose.observability.yaml", "config", "--format", "json"]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=True)
        config = json.loads(result.stdout)
        assert config["name"] == "rac-" + environment
        assert config["volumes"]["profile-photos"]["name"] == "rac-" + environment + "_profile-photos"
        assert any(v["target"] == "/var/lib/rac/photos" and v["source"] == "profile-photos" for v in config["services"]["backend-user"]["volumes"])
        assert config["services"]["migrate"]["environment"]["FLYWAY_DEFAULT_SCHEMA"] == "meta"
        services = config['services']
        assert '@sha256:' in services['rabbitmq']['image']
        assert services['rabbitmq']['hostname'] == 'rabbitmq'
        assert any(v['source'] == 'rabbitmq-events-data' for v in services['rabbitmq']['volumes'])
        assert 'rabbitmq' not in services['backend-match']['depends_on']
        for worker, role in [('booking-events-relay','publisher'),('alert-events-consumer','consumer')]:
            assert 'RABBITMQ_PASSWORD' not in services[worker]['environment']
            assert services[worker]['environment']['RABBITMQ_URL_FILE'] == '/run/messaging/url'
            assert len(services[worker]['volumes']) == 1
            assert services[worker]['volumes'][0]['source'] == 'messaging-' + role
            assert services[worker]['volumes'][0]['read_only']
            assert not services[worker].get('ports')
        if environment != "dev":
            for name in ("backend-auth","backend-user","backend-match","backend-chat","flutter-web"): assert "build" not in config["services"][name]
            assert "ports" not in config["services"]["postgres"]
            assert "ports" not in config["services"]["rabbitmq"]
            assert "start-dev" not in config["services"]["keycloak"]["command"]
            assert not config["services"]["keycloak"].get("volumes")
            assert services['booking-events-relay']['image'] == services['backend-match']['image']
            assert services['alert-events-consumer']['image'] == services['backend-alert']['image']
        print("PASS:", environment, "configuration and isolation")
    finally: os.unlink(filename)
