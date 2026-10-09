"""Household member registry and per-member provider data directories."""
import fcntl
import json
import os
import re
import uuid
from contextlib import contextmanager
from pathlib import Path


def root():
    return Path(os.environ.get("GROCERY_DATA", "/data"))


def registry_path():
    return root() / "profiles.json"


@contextmanager
def _locked():
    root().mkdir(parents=True, exist_ok=True, mode=0o700)
    with (root() / "profiles.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def _read():
    try:
        data = json.loads(registry_path().read_text())
        if isinstance(data, dict) and isinstance(data.get("profiles"), list):
            return data
    except (OSError, ValueError):
        pass
    # Existing installs become the first member and keep using their existing
    # session files. The household receipt archive remains at the same path.
    return {"version": 1, "profiles": [{"id": "default", "name": "Default", "legacy": True}]}


def all():
    with _locked():
        data = _read()
        if not registry_path().exists():
            _write(data)
        return [dict(p) for p in data["profiles"]]


def _write(data):
    from receipt_archive import atomic_json

    atomic_json(registry_path(), data)


def find(profile_id):
    return next((p for p in all() if p["id"] == profile_id), None)


def by_name(name):
    return next((p for p in all() if p["name"].casefold() == name.casefold()), None)


def ensure(name):
    name = str(name or "").strip()
    if not name or len(name) > 64 or any(ord(c) < 32 for c in name):
        raise ValueError("Profile name must be 1–64 characters without control characters.")
    with _locked():
        data = _read()
        existing = next((p for p in data["profiles"] if p["name"].casefold() == name.casefold()), None)
        if existing:
            return dict(existing)
        profile = {"id": uuid.uuid4().hex[:12], "name": name, "legacy": False}
        data["profiles"].append(profile)
        _write(data)
        data_dir(profile).mkdir(parents=True, exist_ok=True, mode=0o700)
        return dict(profile)


def rename(profile_id, name):
    name = str(name or "").strip()
    if not name or len(name) > 64 or any(ord(c) < 32 for c in name):
        raise ValueError("Profile name must be 1–64 characters without control characters.")
    with _locked():
        data = _read()
        profile = next((p for p in data["profiles"] if p["id"] == profile_id), None)
        if not profile:
            raise ValueError("Unknown profile.")
        if any(p["id"] != profile_id and p["name"].casefold() == name.casefold() for p in data["profiles"]):
            raise ValueError("That profile name is already in use.")
        profile["name"] = name
        _write(data)
        return dict(profile)


def data_dir(profile):
    if isinstance(profile, str):
        profile = find(profile)
    if not profile:
        raise ValueError("Unknown profile")
    if profile.get("legacy"):
        return root()
    if not re.fullmatch(r"[a-f0-9]{12}", str(profile.get("id", ""))):
        raise ValueError("Invalid profile registry entry")
    return root() / "profiles" / profile["id"]


def connected_profiles():
    result = []
    for profile in all():
        directory = data_dir(profile)
        providers = []
        provider_files = (
            ("trumf", "trumf_state.json"),
            ("rema", "rema_tokens.json"),
            ("coop", "coop_tokens.json"),
        )
        for provider, filename in provider_files:
            if (directory / filename).exists():
                providers.append(provider)
        result.append({**profile, "providers": providers})
    return result


def receipt_owner(record):
    profile_id = record.get("profile_id") or "default"
    return next((p for p in all() if p["id"] == profile_id), {"id": profile_id, "name": "Default"})


def valid_id(value):
    return bool(re.fullmatch(r"[a-f0-9]{12}|default", value or ""))
