from fastapi import APIRouter
from models import ErrorResponse

router = APIRouter(tags=["Health"])


@router.get("/")
async def root():
    return {"status": "ok", "service": "outland-backend"}


@router.get("/health")
async def health_check():
    import docker
    from models import ErrorResponse

    try:
        client = docker.from_env()
        docker_info = client.info()
        from services import AGENT_REGISTRY
        return {
            "status": "healthy",
            "docker": "connected",
            "docker_version": docker_info.get("ServerVersion", "unknown"),
            "registered_agents": len(AGENT_REGISTRY)
        }
    except docker.errors.DockerException:
        return {
            "status": "degraded",
            "docker": "disconnected"
        }
    except Exception:
        return {
            "status": "degraded",
            "docker": "disconnected"
        }
