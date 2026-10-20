"""Initialize the DEV encrypted backup repository configuration, without outputting secrets."""
from pathlib import Path
import os
import secrets

root = Path(__file__).resolve().parents[1]
path = root/"envs/.env.backups"
if not (root/"envs/.env.photos-s3").is_file():
    raise RuntimeError("Activate private S3 before backups")
if path.exists():
    print("Existing backup configuration retained.")
else:
    storage = dict(line.split("=",1) for line in (root/"envs/.env.storage").read_text(encoding="utf-8").splitlines() if "=" in line and not line.startswith("#"))
    directory = root.parent/".local/backups/rac-dev"
    directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    values = {"BACKUP_DIRECTORY":directory.as_posix(),"BACKUP_UID":str(os.getuid() if hasattr(os,"getuid") else 10001),"BACKUP_GID":str(os.getgid() if hasattr(os,"getgid") else 10001),"RESTIC_PASSWORD":secrets.token_urlsafe(48),"BACKUP_S3_ACCESS_KEY":storage["BACKUP_S3_ACCESS_KEY"],"BACKUP_S3_SECRET_KEY":storage["BACKUP_S3_SECRET_KEY"],"BACKUP_S3_BUCKET":storage["PROFILE_S3_BUCKET"]}
    descriptor = os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(descriptor,"w",encoding="utf-8") as output:
        output.write("".join(key+"="+value+"\n" for key,value in values.items()))
    print("DEV backup configuration created. Preserve its encryption password separately.")
