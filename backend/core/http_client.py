import httpx
from typing import Optional

HTTP_CLIENT_LIMITS = httpx.Limits(
    max_keepalive_connections=20,
    max_connections=100,
    keepalive_expiry=30.0
)

_http_client: Optional[httpx.AsyncClient] = None


def get_http_client() -> httpx.AsyncClient:
    return _http_client


def set_http_client(client: httpx.AsyncClient) -> None:
    global _http_client
    _http_client = client


def close_http_client() -> None:
    global _http_client
    if _http_client:
        import asyncio
        asyncio.create_task(_http_client.aclose())
        _http_client = None
