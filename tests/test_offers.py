import json
import time
from unittest.mock import Mock

import offers
import webgui
from inbox import store


def test_provider_details_and_safe_links(client, monkeypatch):
    monkeypatch.setattr(
        webgui,
        "trumf_data",
        lambda: {
            "offers": [
                offers.normalize(
                    "trumf",
                    {
                        "kampanjeId": "example",
                        "visningsTekst": "Example",
                        "betingelser": "Full conditions",
                        "beskrivelse": "Details",
                    },
                )
            ]
        },
    )
    page = client.get("/offers/trumf/example")
    assert page.status_code == 200 and "Full conditions" in page.text
    assert client.get("/offers/unknown/example").status_code == 404
    assert offers.url("javascript:alert(1)") is None
    assert offers.url("//example.com") is None
    assert (
        offers.cards("trumf", [{"title": "Example"}])[0]["id"] == offers.cards("trumf", [{"title": "Example"}])[0]["id"]
    )


def test_rema_discount_value_is_shown_on_homepage(client, monkeypatch):
    offers_for_page = [
        offers.normalize(
            "rema",
            {
                "id": "discounted-coffee",
                "header": "Coffee",
                "value": 25,
                "unit": "perc",
                "type": {"code": "def", "desc": "Default"},
            },
        ),
        offers.normalize(
            "rema",
            {
                "id": "personal-price-cut",
                "header": "Milk",
                "value": 10,
                "type": {"code": "ppk", "desc": "Personligt priskutt"},
            },
        ),
    ]
    monkeypatch.setattr(webgui, "rema_data", lambda: {"ok": True, "receipts": [], "offers": offers_for_page})

    response = client.get("/")

    assert response.status_code == 200
    assert 'class="offer-discount"' in response.text
    assert "<span>Discount</span>:" in response.text
    assert "25%" in response.text
    assert "10\u00a0NOK" in response.text


def test_rema_discount_value_without_known_unit_is_not_misrepresented():
    offer = offers.normalize(
        "rema",
        {"id": "unknown-discount-unit", "header": "Offer", "value": 15, "unit": "unknown"},
    )

    assert offer["discount_value"] is None


def test_coop_only_current_unredeemed(tmp_path, monkeypatch):
    monkeypatch.setenv("GROCERY_DATA", str(tmp_path))
    (tmp_path / "coop_session.json").write_text(json.dumps({"headers": {}}))
    now = time.time() * 1000
    rows = [
        {"offerId": "active", "promoName": "Example", "endTime": now + 60000},
        {"offerId": "expired", "endTime": now - 60000},
        {"offerId": "future", "publishDate": now + 60000},
        {"offerId": "used", "redemption": {"redemptionDate": now}},
    ]
    response = Mock()
    response.json.return_value = {"resultCode": "SUCCESS", "membershipCoupons": [{"coupons": rows}]}
    get = Mock(return_value=response)
    monkeypatch.setattr(offers.requests, "get", get)
    assert [o["id"] for o in offers.coop_data()["offers"]] == ["active"]
    assert get.call_args.args[0].endswith("/coupon/all")


def test_state_form_returns_to_inbox_json_stays_json(client, tmp_path, monkeypatch):
    monkeypatch.setenv("GROCERY_DATA", str(tmp_path))
    rid = store.ingest(b"Example\n07.09.2026\nTOTALT 42,00 NOK")["rid"]
    store.correct(rid, {"store": "Example", "date": "2026-09-07", "amount": "42", "currency": "NOK"})
    for state in ("confirmed", "needs_review", "discarded"):
        response = client.post("/inbox/" + rid + "/state", data={"state": state})
        assert response.status_code == 303 and response.location == "/inbox"
    response = client.post("/inbox/" + rid + "/state", json={"state": "needs_review"})
    assert response.is_json and response.json["review"]["state"] == "needs_review"
