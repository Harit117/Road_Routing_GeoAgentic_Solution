from pydantic import BaseModel, Field
from typing import Any


class MissionState(BaseModel):
    mission_type: str
    priority: str
    origin: str | None = None
    destination: str | None = None

    time_weight: float = Field(ge=0, le=1)
    safety_weight: float = Field(ge=0, le=1)
    payload_sensitivity: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)

    facility_type: str | None = None
    candidate_facilities: list[dict[str, Any]] = Field(
        default_factory=list
    )

    hazard_status: dict[str, Any] | None = None
    previous_hazard_status: dict[str, Any] | None = None

    selected_route: dict[str, Any] | None = None

    explanation: str = ""
    route_explanation: str | None = None