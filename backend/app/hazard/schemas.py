from pydantic import BaseModel, Field
from typing import Literal


class HazardStatus(BaseModel):
    flood_risk: Literal[
        "LOW",
        "MEDIUM",
        "HIGH",
        "CRITICAL"
    ]

    affected_roads: int = Field(ge=0)

    blocked_roads: int = Field(ge=0)

    explanation: str