from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class CreateSimulation(BaseModel):
    model: str | None = None
    preset: str | None = Field(None, description="Name of a built-in rainfall series")
    scenario: Literal["normal", "moderate", "heavy", "extreme"] | None = Field(
        None, description="Historical 48-hour rainfall scenario"
    )
    rainfall_mm_per_h: list[float] | None = Field(
        None, description="One rainfall intensity per tick", min_length=1, max_length=720
    )
    start_time: datetime | None = None

    @model_validator(mode="after")
    def one_rainfall_source(self):
        sources = sum(
            value is not None
            for value in (self.preset, self.scenario, self.rainfall_mm_per_h)
        )
        if sources != 1:
            raise ValueError(
                "give exactly one of 'preset', 'scenario', or 'rainfall_mm_per_h'"
            )
        return self


class FrameSummary(BaseModel):
    tick: int
    time: datetime
    rainfall_mm_per_h: float
    cumulative_rain_mm: float
    status_counts: dict[str, int]


class SimulationInfo(BaseModel):
    model: str
    rainfall_source: str
    rainfall_mm_per_h: list[float]
    step_minutes: int
    tick: int
    total_ticks: int
    finished: bool
    status_bands: dict[str, float]
    frames: list[FrameSummary]


class FrameLoading(FrameSummary):
    loading: list[float] = Field(description="Indexed by the road property 'i'")


class OnsetEntry(BaseModel):
    road_id: str
    index: int
    name: str | None
    onset_tick: int


class RoadFloodState(BaseModel):
    road_id: str
    status: Literal["safe", "watch", "risky", "flooded"]
    loading: float = Field(
        ge=0,
        le=1,
        description="Routing-compatible risk score; 1.0 means this road's threshold is reached",
    )
    susceptibility: float = Field(ge=0, le=1)
    threshold: float = Field(ge=0, description="Normalized road-specific risk threshold")
    current_flood_loading: float = Field(
        ge=0, description="Normalized bucket quantity; not a water depth"
    )
    risk_score: float = Field(ge=0, le=1)
    risk_level: Literal["LOW", "MODERATE", "HIGH", "VERY_HIGH", "CRITICAL"]
    threshold_reached: bool
    elapsed_hours: float = Field(ge=0)
    time_to_threshold_hours: float | None = Field(default=None, ge=0)
    rainfall_mm_per_h: float
    cumulative_rain_mm: float
    observed_at: datetime
    time_to_threshold_minutes: int | None = Field(
        description="Elapsed simulation time to threshold; null if not reached in this run"
    )
    source: str = Field(description="Rainfall source used for this modeled state")


class RoadFloodStateBatchRequest(BaseModel):
    road_ids: list[str] = Field(min_length=1, max_length=1000)
    scenario: Literal["normal", "moderate", "heavy", "extreme"] | None = None


class RoadFloodStateBatchResponse(BaseModel):
    states: list[RoadFloodState]
    unknown_road_ids: list[str]
    observed_at: datetime
    scenario: Literal["normal", "moderate", "heavy", "extreme"] | None = None
    model_status: Literal["scenario_based_prototype"] = "scenario_based_prototype"


class ScenarioSimulationRequest(CreateSimulation):
    scenario_name: str | None = Field(None, max_length=100)


class ScenarioSimulationResponse(BaseModel):
    scenario_name: str | None
    model_status: Literal["scenario_based_prototype"] = "scenario_based_prototype"
    model_name: str
    rainfall_source: str
    step_minutes: int
    started_at: datetime
    completed_at: datetime
    states: list[RoadFloodState]
