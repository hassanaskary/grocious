"""Archive-backed read API used by MCP and HTTP agent clients."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import agent_api
import profiles
import receipt_archive as archive
import webgui


def _receipt(source, profile_id, date, amount_minor, store, *, review=None, lines=None):
    source_id = f"{source}-{profile_id}-{date}-{store}"
    archive_id = archive.key(source, source_id, profile_id)
    record = {
        "schema_version": 1,
        "chain": source if source != "inbox" else "other",
        "id": source_id,
        "archive_id": archive_id,
        "profile_id": profile_id,
        "profile_name": "Default" if profile_id == "default" else "Partner",
        "date": date,
        "store": store,
        "amount": amount_minor / 100,
        "amount_minor": amount_minor,
        "currency": "NOK",
        "bonus": 5.0,
        "discount": 2.0,
        "lines": lines or [],
        "documents": [],
        "source": {},
    }
    if source == "inbox":
        record["review"] = review or {"state": "needs_review"}
        record["interpretation"] = {"confidence": 0.5}
        record["intake"] = {"channel": "upload"}
    directory = archive.folder(source, archive_id)
    archive.atomic_json(directory / "receipt.json", record)
    return record


def _seed(tmp_path, monkeypatch):
    monkeypatch.setenv("GROCERY_DATA", str(tmp_path))
    archive.atomic_json(
        profiles.registry_path(),
        {
            "version": 1,
            "profiles": [
                {"id": "default", "name": "Default", "legacy": True},
                {"id": "a1b2c3d4e5f6", "name": "Partner", "legacy": False},
            ],
        },
    )
    partner_dir = tmp_path / "profiles" / "a1b2c3d4e5f6"
    partner_dir.mkdir(parents=True)
    (partner_dir / "coop_tokens.json").write_text("{}")
    default = _receipt(
        "rema",
        "default",
        "2026-01-01",
        12345,
        "Kiwi Sentrum",
        lines=[{"line_number": 1, "name": "Melk", "amount_minor": 12345}],
    )
    partner = _receipt("coop", "a1b2c3d4e5f6", "2026-01-31", 20000, "Extra Øst")
    inbox = _receipt("inbox", "default", "2026-01-31", 5000, "Lokalbutikk")
    linked = _receipt("inbox", "default", "2026-01-31", 9000, "Linked receipt", review={"state": "linked"})
    for source in ("rema", "coop", "inbox"):
        archive.rebuild(source)
    archive.atomic_json(
        archive.root() / "rema" / "status.json",
        {"state": "complete", "updated_at": "2026-02-01T09:00:00+00:00", "profiles": []},
    )
    return default, partner, inbox, linked


def test_list_receipts_uses_inclusive_start_exclusive_end_and_member_filter(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)

    result = agent_api.list_receipts(
        "2026-01-01", "2026-02-01", member_id="a1b2c3d4e5f6", provider="coop"
    )

    assert result["count"] == 1
    assert result["receipts"][0]["profile_name"] == "Partner"
    assert result["receipts"][0]["provider"] == "coop"
    assert result["has_more"] is False


def test_spending_summary_excludes_inbox_by_default_and_sums_in_minor_units(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)

    result = agent_api.spending_summary("2026-01-01", "2026-02-01", group_by="total")

    assert result["groups"] == [
        {
            "group": "household",
            "receipt_count": 2,
            "known_amount_count": 2,
            "unknown_amount_count": 0,
            "totals_minor": {"NOK": 32345},
            "bonus_minor": {"NOK": 1000},
            "discount_minor": {"NOK": 400},
        }
    ]
    with_inbox = agent_api.spending_summary("2026-01-01", "2026-02-01", include_inbox=True, group_by="total")
    assert with_inbox["groups"][0]["receipt_count"] == 3
    assert with_inbox["groups"][0]["totals_minor"] == {"NOK": 37345}

    status = agent_api.household_status()
    partner_status = status["sources"]["coop"]["accounts"][0]
    assert partner_status["profile_id"] == "a1b2c3d4e5f6"
    assert partner_status["state"] == "not_started"


def test_get_receipt_returns_normalized_lines_without_raw_source(tmp_path, monkeypatch):
    default, _, inbox_receipt, _ = _seed(tmp_path, monkeypatch)

    result = agent_api.get_receipt("rema", default["archive_id"])

    assert result["lines"][0]["name"] == "Melk"
    assert result["profile_id"] == "default"
    assert result["source"] == "rema"
    assert "source_payload" not in result

    inbox = agent_api.get_receipt("inbox", inbox_receipt["archive_id"])
    assert inbox["provider"] is None
    assert inbox["intake_channel"] == "upload"


def test_agent_http_api_requires_opt_in_bearer_token(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    webgui.app.config["TESTING"] = True
    monkeypatch.delenv("GROCIOUS_AGENT_API_TOKEN", raising=False)
    assert webgui.app.test_client().get("/api/agent/v1/household").status_code == 503

    monkeypatch.setenv("GROCIOUS_AGENT_API_TOKEN", "secret-token")
    client = webgui.app.test_client()
    assert client.get("/api/agent/v1/household").status_code == 401
    response = client.get("/api/agent/v1/household", headers={"Authorization": "Bearer secret-token"})
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.get_json()["sources"]["rema"]["updated_at"] == "2026-02-01T09:00:00+00:00"
    assert client.post("/api/agent/v1/household", headers={"Authorization": "Bearer secret-token"}).status_code == 405


def test_agent_http_api_rejects_bad_ranges_and_unknown_profiles(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    monkeypatch.setenv("GROCIOUS_AGENT_API_TOKEN", "secret-token")
    client = webgui.app.test_client()
    headers = {"Authorization": "Bearer secret-token"}

    invalid_range = client.get(
        "/api/agent/v1/receipts?start_date=2026-02-01&end_date=2026-01-01", headers=headers
    )
    assert invalid_range.status_code == 400
    assert client.get(
        "/api/agent/v1/spending?start_date=2026-01-01&end_date=2026-02-01&member_id=unknown", headers=headers
    ).status_code == 400
