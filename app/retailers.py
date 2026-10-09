"""Household-wide retailer names for manual receipt intake."""

import fcntl
import json
from contextlib import contextmanager

import profiles
import receipt_archive


def _path():
    return profiles.root() / "retailers.json"


@contextmanager
def _locked():
    profiles.root().mkdir(parents=True, exist_ok=True, mode=0o700)
    with (profiles.root() / "retailers.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def _catalog():
    try:
        data = json.loads(_path().read_text())
        if isinstance(data, dict) and isinstance(data.get("retailers"), list):
            return data
    except (OSError, ValueError):
        pass
    return {"version": 1, "retailers": []}


def _write(data):
    receipt_archive.atomic_json(_path(), data)


def all():
    """Return saved retailer names plus merchants already present in the archive."""
    names = _catalog().get("retailers", [])
    result = {}
    for name in names:
        if isinstance(name, str) and name.strip():
            result.setdefault(name.casefold(), name)
    for source in ("rema", "trumf", "coop", "inbox"):
        for row in receipt_archive.summary(source).get("receipts", []):
            name = row.get("store")
            if isinstance(name, str) and name.strip():
                result.setdefault(name.casefold(), name.strip())
    return sorted(result.values(), key=str.casefold)


def add(name):
    """Add or return the household's canonical spelling of a retailer name."""
    name = str(name or "").strip()
    if not name or len(name) > 100 or any(ord(char) < 32 for char in name):
        raise ValueError("Velg eller skriv inn en gyldig butikk (maks. 100 tegn).")
    with _locked():
        data = _catalog()
        for current in data["retailers"]:
            if isinstance(current, str) and current.casefold() == name.casefold():
                return current
        data["retailers"].append(name)
        _write(data)
    return name


def normalize(name):
    name = str(name or "").strip()
    if not name or len(name) > 100 or any(ord(char) < 32 for char in name):
        raise ValueError("Velg eller skriv inn en gyldig butikk (maks. 100 tegn).")
    return next((current for current in all() if current.casefold() == name.casefold()), name)

