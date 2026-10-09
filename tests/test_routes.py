"""Every route and export format, in demo mode (fixtures, no tokens, no network)."""

import csv
import io
import json

import themes


def upload_language_test_receipt(client, store_name="Language Test Store"):
    response = client.post(
        "/inbox",
        data={
            "profile_id": "default",
            "stores": store_name,
            "files": (io.BytesIO(b"Language Test Store\n08.09.2026\nTOTALT 42,00 NOK"), "receipt.txt"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 303
    return response.location


def test_index_renders_everything(client):
    html = client.get("/").get_data(as_text=True)
    assert "grocious" in html and "DEMO" in html
    assert 'lang="en"' in html and "Settings" in html and "Offers &amp; coupons" in html
    assert 'id="theme"' in html and "Catppuccin Mocha" in html and 'value="auto"' in html
    assert 'id="language"' in html and 'value="no"' in html and "Activate" in html and "✓ Activated" in html
    assert html.index('src="/translations.js"') < html.index('src="/static/app.js"')
    assert 'data-chain="trumf"' in html and 'data-chain="rema"' in html
    assert 'data-month="2026-06"' in html  # dates populate the shared period controls
    assert "412.37\u00a0NOK" in html
    assert "<style>" not in html  # no inline CSS left
    translations = client.get("/translations.js")
    assert translations.mimetype == "application/javascript" and "window.grociousTranslations=" in translations.text


def test_norwegian_language_preference_renders_and_persists(client, tmp_path, monkeypatch):
    monkeypatch.setenv("GROCERY_DATA", str(tmp_path))
    response = client.post("/language", data={"language": "no", "next": "/inbox"})
    assert response.status_code == 303
    assert response.headers["Location"] == "/inbox"
    assert "grocious_language=no" in response.headers["Set-Cookie"]

    detail_path = upload_language_test_receipt(client)
    html = client.get("/inbox").get_data(as_text=True)
    assert 'lang="nb"' in html and "Innstillinger" in html and "Last opp" in html
    assert "42,00\u00a0kr" in html
    detail = client.get(detail_path).get_data(as_text=True)
    assert 'placeholder="DD.MM.ÅÅÅÅ"' in detail


def test_language_preference_rejects_invalid_values_and_external_redirects(client):
    invalid = client.post("/language", data={"language": "fr", "next": "/inbox"})
    assert invalid.status_code == 400
    external = client.post("/language", data={"language": "en", "next": "https://example.com"})
    assert external.status_code == 303
    assert external.headers["Location"] == "/"


def test_english_is_default_across_inbox_archive_and_offer_pages(client, tmp_path, monkeypatch):
    monkeypatch.setenv("GROCERY_DATA", str(tmp_path))
    inbox = client.get("/inbox").get_data(as_text=True)
    assert 'lang="en"' in inbox and "Upload" in inbox and "Take photo" in inbox
    detail_path = upload_language_test_receipt(client)
    detail = client.get(detail_path).get_data(as_text=True)
    assert "Interpret receipt" in detail and "Date (DD/MM/YYYY)" in detail and "Store:" in detail

    archive = client.get("/archive/rema").get_data(as_text=True)
    assert "receipt archive" in archive and "Complete source data is preserved." in archive

    offer = client.get("/offers/rema/DEMO-KAFFE").get_data(as_text=True)
    assert offer.startswith("<!doctype html>") and "Opening an offer does not activate it." in offer


def test_language_translation_preserves_user_supplied_store_names(client, tmp_path, monkeypatch):
    monkeypatch.setenv("GROCERY_DATA", str(tmp_path))
    detail_path = upload_language_test_receipt(client, store_name="Kjøp")
    html = client.get(detail_path).get_data(as_text=True)
    assert '<h1><span translate="no">Kjøp</span></h1>' in html


def test_index_survives_failed_sources(client, monkeypatch):
    import webgui

    monkeypatch.setattr(webgui, "trumf_data", lambda: {"ok": False, "err": "cookie expired"})
    monkeypatch.setattr(webgui, "rema_data", lambda: {"ok": False, "err": "401"})
    html = client.get("/").get_data(as_text=True)
    assert html.count("Could not refresh live data. Archived purchases are shown.") >= 2
    assert "No offers" in html


def test_themes_css_and_files(client):
    css = client.get("/themes.css").get_data(as_text=True)
    ids = [t["id"] for t in themes.load_themes()]
    assert ids == [
        "light",
        "dark",
        "ink",
        "gruvbox",
        "zenburn",
        "catppuccin-latte",
        "catppuccin-frappe",
        "catppuccin-macchiato",
        "catppuccin-mocha",
    ]
    assert css.startswith("/* generated") and ":root{color-scheme:light;" in css
    assert "@media (prefers-color-scheme: dark){:root:not([data-theme]){color-scheme:dark;" in css
    for i in ids:
        assert f'html[data-theme="{i}"]{{' in css
    assert all(f"--{k}:" in css for k in themes.COLOR_KEYS)


def test_new_theme_file_is_picked_up(client, tmp_path, monkeypatch):
    monkeypatch.setattr(themes, "THEMES_DIR", tmp_path)
    (tmp_path / "solarized.json").write_text(
        '{"label": "Solarized", "scheme": "light", "colors": {"bg": "#fdf6e3", "accent": "#268bd2"}}'
    )
    (tmp_path / "dark.json").write_text('{"scheme": "dark", "colors": {"bg": "#000"}}')
    ts = themes.load_themes()
    assert [t["id"] for t in ts] == ["dark", "solarized"]
    css = themes.render_css(ts)
    assert 'html[data-theme="solarized"]{color-scheme:light;' in css and "--bg:#fdf6e3;" in css
    assert "Solarized" in client.get("/").get_data(as_text=True)


def test_api_summary_shape_unchanged(client):
    d = client.get("/api/summary").get_json()
    assert set(d) == {"trumf", "rema", "coop", "inbox", "profiles"}
    assert d["profiles"][0]["name"] == "Demo"
    assert d["trumf"]["ok"] and set(d["trumf"]) >= {"saldo", "akkumulert", "oppdatert", "count", "receipts", "offers"}
    assert set(d["trumf"]["receipts"][0]) == {
        "id",
        "date",
        "store",
        "amount",
        "bonus",
        "chain",
        "hasReceipt",
        "profile_id",
        "profile_name",
    }
    assert set(d["rema"]) >= {"purchaseTotal", "discountTotal", "count", "receipts", "offers"}
    assert set(d["rema"]["receipts"][0]) == {
        "id",
        "date",
        "store",
        "amount",
        "discount",
        "profile_id",
        "profile_name",
    }
    assert set(d["rema"]["offers"][0]) == {"code", "desc", "activated", "img"}


def test_api_export_json_and_csv(client):
    d = client.get("/api/export/2026-06.json").get_json()
    assert (
        set(d) == {"month", "count", "total", "total_currency", "total_minor", "bonus", "discount", "receipts"}
        and d["count"] > 0
    )
    assert all(x["date"].startswith("2026-06") for x in d["receipts"])
    assert set(d["receipts"][0]) == {
        "chain",
        "id",
        "date",
        "store",
        "amount",
        "amount_minor",
        "payment",
        "currency",
        "bonus",
        "discount",
        "archive_id",
        "profile_id",
        "profile_name",
    }
    with_lines = client.get("/api/export/2026-06.json?lines=1").get_json()
    assert all("lines" in x for x in with_lines["receipts"] if x["chain"] == "rema")
    r = client.get("/api/export/2026-06.csv")
    rows = list(csv.reader(io.StringIO(r.get_data(as_text=True))))
    assert (
        rows[0][:7] == ["chain", "receipt_id", "date", "store", "amount", "bonus", "discount"]
        and len(rows) == d["count"] + 1
    )
    rows = list(csv.reader(io.StringIO(client.get("/api/export/2026-06.csv?lines=1").get_data(as_text=True))))
    assert rows[0][:8] == ["chain", "receipt_id", "date", "store", "item", "ean", "qty", "amount"]
    assert "review_state" in rows[0]
    assert client.get("/api/export/2026-6.json").status_code == 404
    assert client.get("/api/export/2026-06.pdf").status_code == 404


def test_receipt_exports(client):
    j = client.get("/trumf/receipt/demo-trumf-001.json")
    assert j.status_code == 200 and j.headers["Content-Disposition"].endswith("trumf-demo-trumf-001.json")
    d = json.loads(j.get_data(as_text=True))
    assert d["id"] == "demo-trumf-001" and set(d["lines"][0]) == {"name", "ean", "qty", "amount"}
    c = client.get("/rema/receipt/900100.csv")
    assert c.status_code == 200 and c.get_data(as_text=True).splitlines()[0] == "vare,ean,antall,beløp"
    p = client.get("/rema/receipt/900100.pdf")
    assert p.status_code == 200 and p.data.startswith(b"%PDF") and p.mimetype == "application/pdf"
    assert client.get("/rema/receipt/900100.xml").status_code == 404
    assert client.get("/rema/receipt/abc.json").status_code == 404


def test_rema_activate_redirects_and_flips(client):
    offers = lambda: client.get("/api/summary").get_json()["rema"]["offers"]
    assert not next(o for o in offers() if o["code"] == "DEMO-LAKS")["activated"]
    r = client.post("/rema/offer/DEMO-LAKS/activate")
    assert r.status_code == 302 and r.headers["Location"].endswith("/")
    assert next(o for o in offers() if o["code"] == "DEMO-LAKS")["activated"]


def test_static_assets_and_no_cdn(client):
    css = client.get("/static/style.css").get_data(as_text=True)
    js = client.get("/static/app.js").get_data(as_text=True)
    head = client.get("/").get_data(as_text=True).split("<main")[0]
    assert "var(--bg)" in css and "grocious.theme" in js
    assert "http://" not in css and "https://" not in js and 'src="http' not in head and 'href="http' not in head


def test_nok_filters():
    import ui
    import webgui

    nb = "\u00a0"
    assert ui.nok(1234.5, 2) == f"1,234.50{nb}NOK" and ui.nok(0) == f"0{nb}NOK" and ui.nok(None) == "–"
    assert ui.day("2026-09-04") == "04/09/2026" and ui.dt("2026-09-04 18:12") == "04/09/2026 18:12"
    assert ui.month_label("2026-06") == "Jun 2026"

    with webgui.app.test_request_context(headers={"Cookie": "grocious_language=no"}):
        assert ui.nok(1234.5, 2) == f"1{nb}234,50{nb}kr"
        assert ui.day("2026-09-04") == "04.09.2026"
        assert ui.month_label("2026-06") == "jun 2026"
