import pytest
from unittest.mock import MagicMock, patch, AsyncMock


class TestAdbClient:
    @pytest.fixture
    def adb_client(self):
        from agent.services.adb_client import AdbClient
        return AdbClient("127.0.0.1", 5037)

    @pytest.mark.asyncio
    async def test_connect(self, adb_client):
        with patch("agent.services.adb_client.AdbClient._connect") as mock_connect:
            mock_connect.return_value = True
            result = await adb_client.connect()
            assert result is True

    @pytest.mark.asyncio
    async def test_connect_failure(self, adb_client):
        with patch("agent.services.adb_client.AdbClient._connect") as mock_connect:
            mock_connect.side_effect = Exception("Connection failed")
            result = await adb_client.connect()
            assert result is False
