"""Validate secret separation and backup mounts using synthetic configs only."""
from pathlib import Path
import json
import shutil
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as directory:
    target=Path(directory);(target/"envs").mkdir()
    for path in ROOT.glob("*.yaml"):shutil.copy2(path,target/path.name)
    shutil.copy2(ROOT/"envs/.env.dev.example",target/"envs/.env.dev")
    (target/"envs/.env.photos-s3").write_text("PROFILE_PHOTO_STORAGE=s3\nPROFILE_S3_ENDPOINT=http://rustfs:9000\nPROFILE_S3_BUCKET=rac-dev-profile-photos\nPROFILE_S3_REGION=us-east-1\nPROFILE_S3_ACCESS_KEY=app-only\nPROFILE_S3_SECRET_KEY=synthetic-app-secret\n")
    (target/"envs/.env.backups").write_text("BACKUP_DIRECTORY="+(target/"copies").as_posix()+"\nBACKUP_UID=10001\nBACKUP_GID=10001\nRESTIC_PASSWORD=synthetic-encryption-password\nBACKUP_S3_ACCESS_KEY=backup-only\nBACKUP_S3_SECRET_KEY=synthetic-read-only-secret\nBACKUP_S3_BUCKET=rac-dev-profile-photos\n")
    result=subprocess.run(["docker","compose","--env-file","envs/.env.dev","--env-file","envs/.env.backups","-p","rac-dev","-f","compose.yaml","-f","docker-compose.dev.yaml","-f","compose.photos-s3.yaml","-f","compose.backups.yaml","config","--format","json"],cwd=target,capture_output=True,text=True,check=True)
    model=json.loads(result.stdout)
    backup=model["services"]["backups"];user=model["services"]["backend-user"]
    assert backup["environment"]["BACKUP_S3_ACCESS_KEY"]=="backup-only"
    assert user["environment"]["PROFILE_S3_ACCESS_KEY"]=="app-only"
    assert "RESTIC_PASSWORD" not in user["environment"]
    for service in (backup,user):
        assert "RUSTFS_ACCESS_KEY" not in service["environment"]
        assert "RUSTFS_SECRET_KEY" not in service["environment"]
    assert backup["read_only"] is True
    assert not backup.get("privileged")
    assert len(backup["volumes"])==1 and backup["volumes"][0]["target"]=="/backups"
    assert "docker.sock" not in json.dumps(backup["volumes"])
    assert any(item.startswith("/work:") for item in backup["tmpfs"])
    print("PASS backup and app credentials separated; no Docker socket/raw source mounts; read-only root and bounded tmpfs")
