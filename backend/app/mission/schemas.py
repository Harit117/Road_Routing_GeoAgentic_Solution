from pydantic import BaseModel, Field
from typing import Literal


MISSION_DEFAULTS = {
    "TRAUMA": {
        "time_weight": 0.90,
        "safety_weight": 0.80,
        "payload_sensitivity": 0.90,
    },

    "MEDICAL_SUPPLY": {
        "time_weight": 0.85,
        "safety_weight": 0.75,
        "payload_sensitivity": 0.95,
    },

    "RESCUE": {
        "time_weight": 0.60,
        "safety_weight": 0.90,
        "payload_sensitivity": 0.70,
    },

    "RELIEF": {
        "time_weight": 0.50,
        "safety_weight": 0.75,
        "payload_sensitivity": 0.50,
    },
}


class MissionExtraction(BaseModel):
    mission_type: Literal[
        "TRAUMA",
        "MEDICAL_SUPPLY",
        "RESCUE",
        "RELIEF"
    ]

    priority: Literal[
        "CRITICAL",
        "HIGH",
        "NORMAL"
    ]

    origin: str | None = None
    destination: str | None = None

    confidence: float = Field(ge=0, le=1)

    explanation: str


class MissionProfile(BaseModel):
    mission_type: Literal[
        "TRAUMA",
        "MEDICAL_SUPPLY",
        "RESCUE",
        "RELIEF"
    ]

    priority: Literal[
        "CRITICAL",
        "HIGH",
        "NORMAL"
    ]

    origin: str | None = None
    destination: str | None = None

    time_weight: float = Field(ge=0, le=1)
    safety_weight: float = Field(ge=0, le=1)
    payload_sensitivity: float = Field(ge=0, le=1)

    confidence: float = Field(ge=0, le=1)

    explanation: str