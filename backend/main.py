import asyncio
import httpx
from contextlib import asynccontextmanager
from slowapi import Limiter
from slowapi.middleware import SlowAPIMiddleware
from slowapi.errors import RateLimitExceeded
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from core.config import settings
from core.http_client import set_http_client, HTTP_CLIENT_LIMITS, close_http_client
from services import agent_cleanup_loop
from routers import (
    health_router,
    agents_router,
    instances_router,
    containers_router,
    stream_router,
    actions_router,
    apk_router,
    auth_router,
    users_router,
    external_devices_router,
)
from middleware import RequestLoggingMiddleware, ExceptionHandlerMiddleware


limiter = Limiter(key_func=lambda: "global")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _http_client = httpx.AsyncClient(
        limits=HTTP_CLIENT_LIMITS,
        http2=True
    )
    set_http_client(_http_client)

    from database import init_db
    await init_db()

    cleanup_task = asyncio.create_task(agent_cleanup_loop())

    yield

    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass

    await close_http_client()


app = FastAPI(
    title="Outland API",
    description="Android cloud container management platform backend API",
    version="0.1.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(SlowAPIMiddleware)
app.add_middleware(ExceptionHandlerMiddleware)
app.add_middleware(RequestLoggingMiddleware)

app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={
            "error": "rate_limit_exceeded",
            "detail": str(exc.detail)
        }
    )


app.include_router(health_router)
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(agents_router)
app.include_router(instances_router)
app.include_router(containers_router)
app.include_router(stream_router)
app.include_router(actions_router)
app.include_router(apk_router)
app.include_router(external_devices_router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=True,
        log_level="info"
    )
