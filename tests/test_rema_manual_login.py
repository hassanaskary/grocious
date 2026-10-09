import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "login"))
import rema_manual_login


def test_manual_login_prints_authorization_link_and_saves_profile_tokens(tmp_path, monkeypatch, capsys):
    profile_dir = tmp_path / "profiles" / "hassan"
    profile_dir.mkdir(parents=True)
    callback_url = "https://ae-appen.appspot.com/redirect/redirect.html?code=temporary-code&state=login-state"
    exchanged = {}

    monkeypatch.setattr(rema_manual_login, "profile_dir", lambda: profile_dir)
    monkeypatch.setattr(rema_manual_login, "generate_pkce", lambda: ("secret-verifier", "public-challenge"))
    monkeypatch.setattr(rema_manual_login, "generate_state", lambda: "login-state")

    def exchange(code, verifier):
        exchanged.update(code=code, verifier=verifier)
        return {"access_token": "access-token", "refresh_token": "refresh-token", "expires_in": 3600}

    monkeypatch.setattr(rema_manual_login, "exchange_code", exchange)
    monkeypatch.setattr("builtins.input", lambda _prompt: "46505173")
    monkeypatch.setattr(rema_manual_login.getpass, "getpass", lambda _prompt: callback_url)

    rema_manual_login.main()

    output = capsys.readouterr().out
    auth_url = next(line for line in output.splitlines() if line.startswith("https://id.rema.no/authorization?"))
    query = parse_qs(urlsplit(auth_url).query)
    assert query["code_challenge"] == ["public-challenge"]
    assert query["state"] == ["login-state"]
    assert query["redirect_uri"] == ["https://ae-appen.appspot.com/redirect/redirect.html"]
    assert exchanged == {"code": "temporary-code", "verifier": "secret-verifier"}
    assert json.loads((profile_dir / "rema_tokens.json").read_text()) == {
        "access_token": "access-token",
        "refresh_token": "refresh-token",
        "expires_in": 3600,
    }
    assert json.loads((profile_dir / "rema_phone.json").read_text()) == {"phone": "46505173"}


@pytest.mark.parametrize(
    "callback_url",
    [
        "https://ae-appen.appspot.com/redirect/redirect.html?code=temporary-code&state=wrong-state",
        "https://attacker.example/redirect/redirect.html?code=temporary-code&state=login-state",
    ],
)
def test_manual_login_rejects_untrusted_callback_without_saving_tokens(tmp_path, monkeypatch, callback_url):
    profile_dir = tmp_path / "profiles" / "hassan"
    profile_dir.mkdir(parents=True)
    exchange_calls = []

    monkeypatch.setattr(rema_manual_login, "profile_dir", lambda: profile_dir)
    monkeypatch.setattr(rema_manual_login, "generate_pkce", lambda: ("secret-verifier", "public-challenge"))
    monkeypatch.setattr(rema_manual_login, "generate_state", lambda: "login-state")
    monkeypatch.setattr(rema_manual_login, "exchange_code", lambda *args: exchange_calls.append(args))
    monkeypatch.setattr("builtins.input", lambda _prompt: "46505173")
    monkeypatch.setattr(rema_manual_login.getpass, "getpass", lambda _prompt: callback_url)

    with pytest.raises(SystemExit):
        rema_manual_login.main()

    assert exchange_calls == []
    assert not (profile_dir / "rema_tokens.json").exists()


def test_manual_login_accepts_rema_app_redirect_after_browser_callback():
    callback = "bella://authorize?code=temporary-code&state=login-state"
    assert rema_manual_login.callback_code(callback, "login-state") == "temporary-code"
