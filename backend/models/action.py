from pydantic import BaseModel
from typing import Optional


class ClickRequest(BaseModel):
    container_id: str
    agent_id: Optional[str] = None
    x: int
    y: int


class SwipeRequest(BaseModel):
    container_id: str
    agent_id: Optional[str] = None
    x1: int
    y1: int
    x2: int
    y2: int
    duration: int = 300


class TextRequest(BaseModel):
    container_id: str
    agent_id: Optional[str] = None
    text: str


class KeyEventRequest(BaseModel):
    container_id: str
    agent_id: Optional[str] = None
    keycode: int


class ActionResponse(BaseModel):
    success: bool = True
    container_id: str
    action: str
    detail: str = ""
