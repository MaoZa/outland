from .health import router as health_router
from .agents import router as agents_router
from .instances import router as instances_router
from .containers import router as containers_router
from .stream import router as stream_router
from .actions import router as actions_router
from .apk import router as apk_router
from .auth import router as auth_router
from .users import router as users_router

__all__ = [
    "health_router",
    "agents_router",
    "instances_router",
    "containers_router",
    "stream_router",
    "actions_router",
    "apk_router",
    "auth_router",
    "users_router",
]
