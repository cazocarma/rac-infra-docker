"""Initialize DEV storage secrets; retain existing root/app identities."""
from pathlib import Path
import os
import secrets

path = Path(__file__).resolve().parents[1] / "envs" / ".env.storage"
values = {}
if path.exists():
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            key,value = line.split("=",1)
            values[key] = value
required = {
    "RUSTFS_ACCESS_KEY":lambda:secrets.token_hex(12),
    "RUSTFS_SECRET_KEY":lambda:secrets.token_urlsafe(36),
    "PROFILE_S3_ACCESS_KEY":lambda:"rac-user-"+secrets.token_hex(8),
    "PROFILE_S3_SECRET_KEY":lambda:secrets.token_urlsafe(36),
    "PROFILE_S3_BUCKET":lambda:"rac-dev-profile-photos",
    "BACKUP_S3_ACCESS_KEY":lambda:"rac-backup-"+secrets.token_hex(8),
    "BACKUP_S3_SECRET_KEY":lambda:secrets.token_urlsafe(36),
}
changed = False
for key,generate in required.items():
    if not values.get(key):
        values[key] = generate()
        changed = True
if changed:
    temporary = path.with_suffix(".storage.tmp")
    descriptor = os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(descriptor,"w",encoding="utf-8") as output:
        output.write("".join(key+"="+value+"\n" for key,value in values.items()))
    os.replace(temporary,path)
print("DEV storage credentials ready; values are never printed.")
