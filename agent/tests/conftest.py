import pytest
from agent.services.adb_client import AdbClient


@pytest.fixture
def adb_client():
    return AdbClient("127.0.0.1", 5037)


def test_adb_client_instantiation(adb_client):
    assert adb_client.host == "127.0.0.1"
    assert adb_client.port == 5037


def test_adb_client_default_timeout(adb_client):
    assert adb_client.timeout == 30
