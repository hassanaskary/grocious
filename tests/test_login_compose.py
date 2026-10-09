import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker Compose is needed to inspect login services")
def test_rema_login_compose_service_uses_manual_callback_flow():
    result = subprocess.run(
        ["docker", "compose", "--profile", "login", "config", "--format", "json"],
        cwd=ROOT,
        capture_output=True,
        check=True,
        text=True,
    )

    compose = json.loads(result.stdout)
    assert compose["services"]["rema-login"]["command"] == ["rema_manual_login.py"]
