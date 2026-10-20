"""Crea credenciales del laboratorio DEV sin imprimirlas ni sobrescribirlas."""
from pathlib import Path
import os
import secrets

path = Path(__file__).resolve().parents[1] / "envs" / ".env.storage"
try:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    print("Se conservan las credenciales locales existentes.")
else:
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        output.write("RUSTFS_ACCESS_KEY=" + secrets.token_hex(12) + "\n")
        output.write("RUSTFS_SECRET_KEY=" + secrets.token_urlsafe(36) + "\n")
    print("Credenciales DEV creadas en envs/.env.storage (ignorado por Git).")
