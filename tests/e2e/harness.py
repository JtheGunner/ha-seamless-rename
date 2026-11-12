"""Start a real Home Assistant container with a copy of the sample config and talk to it.

The container is the only moving part: it runs the published image with this repository's
``custom_components`` and a throw-away copy of ``sample_config`` mounted as ``/config``.
Onboarding is completed through the public REST API, so no token has to be provided.
"""

import json
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_CONFIG = Path(__file__).parent / "sample_config"
INTEGRATION = REPO_ROOT / "custom_components" / "entity_rename_safe"
CLIENT_ID = "http://localhost:8123/"
STARTUP_TIMEOUT = 300.0


class HaError(RuntimeError):
    """A request to the container failed."""


@dataclass
class HaClient:
    """Minimal REST client for the container, using only the standard library."""

    base_url: str
    token: str | None = None

    def request(
        self, method: str, path: str, body: Any | None = None, *, form: bool = False
    ) -> Any:
        data: bytes | None = None
        headers = {}
        if body is not None:
            if form:
                from urllib.parse import urlencode

                data = urlencode(body).encode()
                headers["Content-Type"] = "application/x-www-form-urlencoded"
            else:
                data = json.dumps(body).encode()
                headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(
            f"{self.base_url}{path}", data=data, method=method, headers=headers
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = response.read()
        except urllib.error.HTTPError as error:
            raise HaError(f"{method} {path}: {error.code} {error.read().decode()[:500]}") from error
        return json.loads(payload) if payload else None

    def call_service(self, domain: str, service: str, data: dict[str, Any]) -> dict[str, Any]:
        """Call a service that returns a response and return that response."""
        result = self.request("POST", f"/api/services/{domain}/{service}?return_response", data)
        response: dict[str, Any] = result["service_response"]
        return response

    def state(self, entity_id: str) -> dict[str, Any] | None:
        try:
            state: dict[str, Any] = self.request("GET", f"/api/states/{entity_id}")
        except HaError as error:
            if " 404 " in str(error):
                return None
            raise
        return state

    def wait_for_state(self, entity_id: str, *, present: bool, timeout: float = 60.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if (self.state(entity_id) is not None) is present:
                return
            time.sleep(1)
        raise HaError(f"{entity_id} did not become {'available' if present else 'absent'}")


def _docker(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], check=True, capture_output=True, text=True)  # noqa: S603, S607


def _onboard(client: HaClient) -> str:
    """Complete onboarding with a throw-away user and return an access token."""
    created = client.request(
        "POST",
        "/api/onboarding/users",
        {
            "client_id": CLIENT_ID,
            "name": "E2E",
            "username": "e2e",
            "password": "e2e-" + uuid.uuid4().hex,
            "language": "en",
        },
    )
    tokens = client.request(
        "POST",
        "/auth/token",
        {"client_id": CLIENT_ID, "grant_type": "authorization_code", "code": created["auth_code"]},
        form=True,
    )
    return str(tokens["access_token"])


def _wait_until_up(client: HaClient) -> None:
    deadline = time.monotonic() + STARTUP_TIMEOUT
    while time.monotonic() < deadline:
        try:
            client.request("GET", "/api/onboarding")
            return
        except HaError, OSError:
            time.sleep(2)
    raise HaError("Home Assistant did not start in time")


@contextmanager
def running_container(image: str, config_dir: Path, port: int) -> Iterator[HaClient]:
    """Run the image against ``config_dir`` and yield a client with a valid token."""
    name = f"entity-rename-safe-e2e-{uuid.uuid4().hex[:8]}"
    _docker(
        "run", "-d", "--name", name,
        "-p", f"127.0.0.1:{port}:8123",
        "-v", f"{config_dir}:/config",
        image,
    )  # fmt: skip
    try:
        client = HaClient(f"http://127.0.0.1:{port}")
        _wait_until_up(client)
        client.token = _onboard(client)
        yield client
    except BaseException:
        logs = subprocess.run(  # noqa: S603, S607
            ["docker", "logs", "--tail", "80", name], capture_output=True, text=True, check=False
        )
        print(logs.stdout + logs.stderr)
        raise
    finally:
        subprocess.run(["docker", "rm", "-f", name], check=False, capture_output=True)  # noqa: S603, S607


def prepare_config(target: Path) -> None:
    """Copy the sample config and the integration into ``target``."""
    shutil.copytree(SAMPLE_CONFIG, target, dirs_exist_ok=True)
    shutil.copytree(
        INTEGRATION,
        target / "custom_components" / "entity_rename_safe",
        ignore=shutil.ignore_patterns("__pycache__"),
        dirs_exist_ok=True,
    )
