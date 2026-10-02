from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class CreateSimulation(BaseModel):
    model: str | None = None
    preset: str | None = Field(None, description="Name of a built-in rainfall series")
    rainfall_mm_per_h: list[float] | None = Field(
        None, description="One rainfall intensity per tick", min_length=1, max_length=720
    )
    start_time: datetime | None = None

    @model_validator(mode="after")
    def one_rainfall_source(self):
        if (self.preset is None) == (self.rainfall_mm_per_h is None):
            raise ValueError("give exactly one of 'preset' or 'rainfall_mm_per_h'")
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
    loading: float = Field(ge=0, description="Relative bucket loading; 1.0 is the threshold")
    rainfall_mm_per_h: float
    cumulative_rain_mm: float
    observed_at: datetime
    time_to_threshold_minutes: int | None = Field(
        description="Elapsed simulation time to threshold; null if not reached in this run"
    )
    source: Literal["placeholder_simulation"] = "placeholder_simulation"


class RoadFloodStateBatchRequest(BaseModel):
    road_ids: list[str] = Field(min_length=1, max_length=1000)


class RoadFloodStateBatchResponse(BaseModel):
    states: list[RoadFloodState]
    unknown_road_ids: list[str]
    observed_at: datetime
    model_status: Literal["placeholder"] = "placeholder"


class ScenarioSimulationRequest(CreateSimulation):
    scenario_name: str | None = Field(None, max_length=100)


class ScenarioSimulationResponse(BaseModel):
    scenario_name: str | None
    model_status: Literal["placeholder"] = "placeholder"
    model_name: str
    rainfall_source: str
    step_minutes: int
    started_at: datetime
    completed_at: datetime
    states: list[RoadFloodState]
