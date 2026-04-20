import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_register_agent(client: AsyncClient):
    response = await client.post(
        "/api/agents/register",
        json={
            "agent_id": "test-agent-001",
            "url": "http://192.168.1.100:9090"
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["agent_id"] == "test-agent-001"


@pytest.mark.asyncio
async def test_list_agents_empty(client: AsyncClient):
    response = await client.get("/api/agents/list")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["agents"] == []


@pytest.mark.asyncio
async def test_heartbeat_unregistered_agent(client: AsyncClient):
    response = await client.post(
        "/api/agents/heartbeat",
        json={"agent_id": "nonexistent-agent"}
    )
    assert response.status_code == 404
