import os
import shutil
import socket
from collections.abc import Iterator
from pathlib import Path

import pytest
from pytest_socket import enable_socket

from . import harness

E2E_ENABLED = os.environ.get("E2E") == "1"
IMAGE = os.environ.get("E2E_HA_IMAGE", "ghcr.io/home-assistant/home-assistant:stable")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="session")
def e2e_config_dir(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """A throw-away copy of the sample config that the container mounts."""
    directory = tmp_path_factory.mktemp("ha-config")
    harness.prepare_config(directory)
    yield directory
    shutil.rmtree(directory, ignore_errors=True)


@pytest.fixture(scope="session")
def ha(e2e_config_dir: Path) -> Iterator[harness.HaClient]:
    """A running Home Assistant container with the integration set up."""
    if not E2E_ENABLED:
        pytest.skip("set E2E=1 to run the container tests")
    if shutil.which("docker") is None:
        pytest.skip("docker is not available")
    # The Home Assistant test plugin blocks sockets; this test talks to a real container.
    enable_socket()
    with harness.running_container(IMAGE, e2e_config_dir, _free_port()) as client:
        flow = client.request(
            "POST", "/api/config/config_entries/flow", {"handler": "seamless_rename"}
        )
        assert flow["type"] == "create_entry", flow
        yield client
