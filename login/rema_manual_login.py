"""Complete Rema OAuth login by opening the authorization link on another device."""
import base64
import hashlib
import getpass
import hmac
import json
import os
import secrets
import tempfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen

from common import profile_dir

CLIENT_ID = "android-251010"
REDIRECT_URI = "https://ae-appen.appspot.com/redirect/redirect.html"
AUTH_URL = "https://id.rema.no/authorization"
TOKEN_URL = "https://id.rema.no/token"


def generate_pkce():
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def generate_state():
    # The Rema redirect page only accepts alphanumeric state values.
    return secrets.token_hex(16)


def _write_private_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".rema-login-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def callback_code(callback_url, expected_state):
    parsed = urlsplit(callback_url.strip())
    appspot_callback = (
        parsed.scheme == "https"
        and parsed.netloc.casefold() == "ae-appen.appspot.com"
        and parsed.path == "/redirect/redirect.html"
    )
    rema_app_callback = parsed.scheme == "bella" and parsed.netloc.casefold() == "authorize"
    if not (appspot_callback or rema_app_callback):
        raise ValueError("That is not the Rema OAuth callback URL.")
    params = parse_qs(parsed.query, keep_blank_values=True)
    codes, states = params.get("code", []), params.get("state", [])
    if len(codes) != 1 or not codes[0] or len(states) != 1 or not hmac.compare_digest(states[0], expected_state):
        raise ValueError("The Rema callback is missing a code or has an invalid state. Start login again.")
    return codes[0]


def exchange_code(code, verifier):
    body = urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID,
        "code_verifier": verifier,
    }).encode()
    request = Request(TOKEN_URL, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urlopen(request, timeout=30) as response:
            tokens = json.loads(response.read())
    except HTTPError as error:
        raise RuntimeError(f"Rema token exchange failed (HTTP {error.code}).") from None
    except (URLError, TimeoutError, ValueError) as error:
        raise RuntimeError(f"Rema token exchange failed: {error}") from None
    if not isinstance(tokens, dict) or not tokens.get("access_token") or not tokens.get("refresh_token"):
        raise RuntimeError("Rema token exchange did not return access and refresh tokens.")
    return tokens


def main():
    output_dir = Path(profile_dir())
    selected_profile = os.environ.get("GROCIOUS_PROFILE", "Default")
    use_env = selected_profile.casefold() == "default" or os.environ.get("GROCIOUS_USE_ENV_CREDENTIALS") == "1"
    phone = (os.environ.get("REMA_PHONE") if use_env else None) or input("Rema phone: ").strip()
    if not phone:
        raise SystemExit("A Rema phone number is required.")

    verifier, challenge = generate_pkce()
    state = generate_state()
    authorization_url = AUTH_URL + "?" + urlencode({
        "response_type": "code",
        "client_id": CLIENT_ID,
        "scope": "all",
        "redirect_uri": REDIRECT_URI,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
    })
    print("Open this link in a browser on your computer and complete Rema phone verification:")
    print(authorization_url)
    print("After Rema redirects to its callback page, copy the full callback URL from the address bar.")
    try:
        callback_url = getpass.getpass("Paste callback URL (input hidden): ")
        code = callback_code(callback_url, state)
    except (EOFError, ValueError) as error:
        raise SystemExit(str(error)) from None

    try:
        tokens = exchange_code(code, verifier)
    except RuntimeError as error:
        raise SystemExit(str(error)) from None
    _write_private_json(output_dir / "rema_tokens.json", tokens)
    _write_private_json(output_dir / "rema_phone.json", {"phone": phone})
    print(f"Rema login saved for profile {selected_profile}.")


if __name__ == "__main__":
    main()
