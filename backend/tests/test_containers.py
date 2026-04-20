import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_instances(client: AsyncClient):
    response = await client.get("/api/instances")
    assert response.status_code == 200
    data = response.json()
    assert "total" in data
    assert "instances" in data
    assert isinstance(data["instances"], list)
