import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import profiles
import receipt_archive
import webgui


def test_default_profile_keeps_legacy_data_path_and_receipt_ids(tmp_path, monkeypatch):
    monkeypatch.setenv("GROCERY_DATA", str(tmp_path))

    default = profiles.ensure("Default")

    assert default["id"] == "default"
    assert profiles.data_dir(default) == tmp_path
    expected = hashlib.sha256(b"rema\0receipt-1").hexdigest()
    assert receipt_archive.key("rema", "receipt-1") == expected
    assert receipt_archive.key("rema", "receipt-1", "default") == expected


def test_profiles_are_case_insensitive_and_new_members_have_separate_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("GROCERY_DATA", str(tmp_path))

    partner = profiles.ensure("Partner")
    same_partner = profiles.ensure("partner")

    assert same_partner["id"] == partner["id"]
    assert profiles.data_dir(partner) == tmp_path / "profiles" / partner["id"]
    assert profiles.data_dir(partner) != profiles.data_dir("default")
    assert receipt_archive.key("coop", "receipt-1", partner["id"]) != receipt_archive.key(
        "coop", "receipt-1", "default"
    )


def test_rename_preserves_profile_id(tmp_path, monkeypatch):
    monkeypatch.setenv("GROCERY_DATA", str(tmp_path))
    partner = profiles.ensure("Partner")

    renamed = profiles.rename(partner["id"], "Alex")

    assert renamed["id"] == partner["id"]
    assert profiles.by_name("alex")["id"] == partner["id"]


def test_dashboard_provider_aggregates_members_and_can_filter_one(tmp_path, monkeypatch):
    monkeypatch.setenv("GROCERY_DATA", str(tmp_path))
    monkeypatch.setattr(webgui, "DEMO", False)
    members = [
        {"id": "default", "name": "Default", "providers": ["rema"]},
        {"id": "a1b2c3d4e5f6", "name": "Partner", "providers": ["rema"]},
    ]
    monkeypatch.setattr(profiles, "connected_profiles", lambda: members)
    responses = {
        "default": {"ok": True, "saldo": 10, "receipts": [{"id": "1", "amount": 12.0}]},
        "a1b2c3d4e5f6": {"ok": True, "saldo": 20, "receipts": [{"id": "2", "amount": 14.0}]},
    }
    monkeypatch.setattr(webgui, "rema_data", lambda profile_id: responses[profile_id])

    household = webgui.household_provider("rema")
    partner = webgui.household_provider("rema", "a1b2c3d4e5f6")

    assert household["count"] == 2
    assert {row["profile_name"] for row in household["receipts"]} == {"Default", "Partner"}
    assert household["saldo"] is None
    assert partner["count"] == 1
    assert partner["receipts"][0]["profile_id"] == "a1b2c3d4e5f6"
