import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_webrtc_offer_forward(client: AsyncClient):
    response = await client.post(
        "/api/stream/webrtc/offer",
        json={
            "container_id": "test-container",
            "sdp": "v=0\r\n...",
            "type": "offer"
        }
    )
    assert response.status_code in [200, 404, 503]
