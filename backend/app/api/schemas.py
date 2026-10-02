from datetime import datetime

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
