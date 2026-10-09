"""Resolve an explicitly selected household profile for browser logins."""
import json
import os
import re
import fcntl
import secrets
import tempfile
from pathlib import Path


def profile_dir():
    os.umask(0o077)
    root = Path(os.environ.get("GROCERY_DATA", "/data"))
    name = os.environ.get("GROCIOUS_PROFILE", "Default").strip()
    registry = root / "profiles.json"
    if name.casefold() == "default" and not registry.exists():
        return root
    registry.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (root / "profiles.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = {"version": 1, "profiles": [{"id":"default","name":"Default","legacy":True}]}
        try:
            data = json.loads(registry.read_text())
        except (OSError, ValueError):
            pass
        profiles = data.get("profiles", [])
        profile = next((p for p in profiles if p.get("name", "").casefold() == name.casefold()), None)
        if profile is None:
            if not name or len(name) > 64 or any(ord(c) < 32 for c in name):
                raise SystemExit("Set GROCIOUS_PROFILE to a valid household member name")
            profile = {"id": secrets.token_hex(6), "name": name, "legacy": False}
            profiles.append(profile)
            fd, temporary = tempfile.mkstemp(prefix=".profiles-", dir=root)
            with os.fdopen(fd, "w") as stream:
                json.dump({"version": 1, "profiles": profiles}, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, registry)
    if profile.get("legacy"):
        return root
    if not re.fullmatch(r"[a-f0-9]{12}", profile.get("id", "")):
        raise SystemExit("Invalid profile registry entry")
    result = root / "profiles" / profile["id"]
    result.mkdir(parents=True, exist_ok=True, mode=0o700)
    return result
