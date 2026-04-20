from pydantic import BaseModel


class ApkInstallResponse(BaseModel):
    success: bool
    container_id: str
    message: str
