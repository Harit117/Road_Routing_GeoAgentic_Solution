from pydantic import BaseModel, Field
from typing import Any


class MissionState(BaseModel):
    # Mission information
    mission_type: str
    priority: str

    # Locations
    origin: str | None = None
    destination: str | None = None

    # Mission-specific routing preferences
    time_weight: float = Field(ge=0, le=1)
    safety_weight: float = Field(ge=0, le=1)
    payload_sensitivity: float = Field(ge=0, le=1)

    # Mission Agent confidence
    confidence: float = Field(ge=0, le=1)

    # Facilities identified by Mission Service
    facility_type: str | None = None
    candidate_facilities: list[dict[str, Any]] = []

    # Information that will be filled by other agents later
    hazard_status: dict[str, Any] | None = None
    selected_route: dict[str, Any] | None = None

    # Human-readable explanation
    explanation: str = ""
    route_explanation: str | None = None