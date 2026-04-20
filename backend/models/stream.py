from pydantic import BaseModel, Field
from typing import Optional


class WebRTCOfferRequest(BaseModel):
    container_id: str
    agent_id: Optional[str] = None
    sdp: str
    type: str = "offer"


class WebRTCAnswerResponse(BaseModel):
    sdp: str
    type: str


class QualityChangeRequest(BaseModel):
    container_id: str
    agent_id: Optional[str] = None
    quality: str = Field(description="Quality level: high, medium, or low")


class QualityChangeResponse(BaseModel):
    success: bool
    container_id: str
    old_quality: str
    new_quality: str
    max_size: int
    bitrate: int


class ConnectionStatsResponse(BaseModel):
    status: str
    available_outgoing_bitrate: Optional[int] = None
    packets_lost: Optional[int] = None
    round_trip_time: Optional[float] = None
    bytes_sent: Optional[int] = None
    error: Optional[str] = None
