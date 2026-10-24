"""Validate all environment models with synthetic credentials; never deploy."""
from pathlib import Path
import json
import os
import subprocess
import tempfile
from database_roles import ROLES, validate_credentials
ROOT = Path(__file__).resolve().parent.parent
for environment in ("dev", "qa", "prd"):
    template = (ROOT / "envs" / (".env." + environment + ".example")).read_text()
    values = {}
    for line in template.splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1); values[key] = value
    for key, value in values.items():
        if not value:
            if key in ROLES:
                role=ROLES[key]
                values[key]=f"postgresql://{role}:synthetic-independent-{role}-123456@postgres:5432/{values['POSTGRES_DB']}?sslmode=disable"
                continue
            values[key] = {
                "KEYCLOAK_PUBLIC_URL": "https://auth.example.test",
                "MIGRATION_DB_PASSWORD":"synthetic-independent-migrator-123456",
                "DATABASE_URL": f"postgres://rac:synthetic@postgres:5432/rac_{environment}?sslmode=disable",
            }.get(key, "ghcr.io/cazocarma/synthetic:sha-test" if key.endswith("_IMAGE") else "synthetic-not-a-secret")
    validate_credentials(values)
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
        # Validate the operator's actual container input, not only the env-file:
        # adding a scoped role is incomplete if Compose omits its credential.
        validate_credentials(services['database-config']['environment'])
        mapped={'backend-user':'USER_DB_URL','backend-match':'MATCH_DB_URL','backend-chat':'CHAT_DB_URL','backend-alert':'ALERT_DB_URL','booking-maintenance':'MAINTENANCE_DB_URL','booking-events-relay':'RELAY_DB_URL','alert-events-consumer':'ALERT_CONSUMER_DB_URL','standing-events-relay':'STANDING_RELAY_DB_URL','standing-match-consumer':'STANDING_MATCH_DB_URL','standing-alert-consumer':'STANDING_ALERT_DB_URL'}
        for service,key in mapped.items():
            assert services[service]['environment']['DATABASE_URL']==values[key]
            assert 'POSTGRES_PASSWORD' not in services[service]['environment']
            assert 'MIGRATION_DB_PASSWORD' not in services[service]['environment']
        assert '@sha256:' in services['keycloak']['image']
        assert services['migrate']['environment']['FLYWAY_USER']=='rac_migrator'
        assert services['migrate']['depends_on']['database-config']['condition']=='service_completed_successfully'
        if environment == 'dev':
            preview = subprocess.run(command[:-3] + ['-f', 'compose.standing.yaml', 'config', '--format', 'json'], cwd=ROOT, capture_output=True, text=True, check=True)
            preview = json.loads(preview.stdout)['services']
            for name in ('backend-user', 'backend-match', 'backend-chat', 'standing-match-consumer', 'standing-alert-consumer'):
                assert preview[name]['environment']['STANDING_ENFORCEMENT_ENABLED'] == 'true'
                assert not preview[name].get('ports')
                assert 'KEYCLOAK_ADMIN_PASSWORD' not in preview[name]['environment']
            assert preview['backend-match']['environment']['STANDING_CLIENT_SECRET_FILE'] == '/run/standing-client/secret'
            assert any(v['source']=='identity-standing-match' and v['read_only'] for v in preview['backend-match']['volumes'])
            assert not any(v['source']=='identity-standing-match' for v in preview['backend-user']['volumes'])
            assert any(v['source']=='identity-standing-readers' and v['read_only'] for v in preview['backend-user']['volumes'])
            assert any(v['source']=='identity-standing-chat' and v['read_only'] for v in preview['backend-chat']['volumes'])
            assert not any(v['source']=='identity-standing-match' for v in preview['backend-chat']['volumes'])
            assert preview['standing-match-consumer']['environment']['RAC_ENV'] == 'dev'
            assert preview['standing-match-consumer']['environment']['STANDING_AUTHORITY_URL'] == 'http://backend-user:8082/internal/standing'
            assert any(v['source']=='identity-standing-match' and v['read_only'] for v in preview['standing-match-consumer']['volumes'])
            assert any(v['source']=='messaging-standing-match' and v['read_only'] for v in preview['standing-match-consumer']['volumes'])
            assert any(v['source']=='identity-standing-alert' and v['read_only'] for v in preview['standing-alert-consumer']['volumes'])
            assert any(v['source']=='messaging-standing-alert' and v['read_only'] for v in preview['standing-alert-consumer']['volumes'])
            for name in ('backend-user','backend-match','backend-chat','standing-match-consumer'):
                assert not any(v['source']=='identity-standing-alert' for v in preview[name]['volumes'])



        assert '@sha256:' in services['rabbitmq']['image']
        assert services['rabbitmq']['hostname'] == 'rabbitmq'
        assert any(v['source'] == 'rabbitmq-events-data' for v in services['rabbitmq']['volumes'])
        assert 'rabbitmq' not in services['backend-match']['depends_on']
        for worker, role in [('booking-events-relay','publisher'),('alert-events-consumer','consumer'),('standing-events-relay','standing-publisher'),('standing-match-consumer','standing-match'),('standing-alert-consumer','standing-alert')]:
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
