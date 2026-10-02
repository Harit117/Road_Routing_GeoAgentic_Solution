"""Time-stepping simulation: feeds rainfall into a flood model tick by tick
and records the network state after every tick."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.network.models import RoadNetwork
from app.simulation.flood_models.base import FloodModel
from app.simulation.rainfall import RainfallSeries

# Loading bands shared by the API, the map and (later) routing costs.
STATUS_BANDS: list[tuple[str, float]] = [
    ("safe", 0.0),
    ("watch", 0.5),
    ("risky", 0.8),
    ("flooded", 1.0),
]


def status_of(loading: float) -> str:
    label = STATUS_BANDS[0][0]
    for name, lower in STATUS_BANDS:
        if loading >= lower:
            label = name
    return label


@dataclass
class Frame:
    tick: int
    time: datetime
    rainfall_mm_per_h: float
    cumulative_rain_mm: float
    loading: list[float]  # indexed by Road.index
    status_counts: dict[str, int]


class Simulation:
    def __init__(
        self,
        network: RoadNetwork,
        model: FloodModel,
        rainfall: RainfallSeries,
        step_minutes: int,
    ):
        self.network = network
        self.model = model
        self.rainfall = rainfall
        self.step_minutes = step_minutes
        self.reset()

    @property
    def dt_hours(self) -> float:
        return self.step_minutes / 60

    @property
    def finished(self) -> bool:
        return self.tick >= len(self.rainfall)

    def reset(self) -> None:
        self.model.reset(self.network)
        self.tick = 0
        self.cumulative_rain_mm = 0.0
        # First tick at which each road reached loading >= 1 (None = never).
        # This is the "relative onset" ordering routing will consume.
        self.onset_tick: list[int | None] = [None] * len(self.network.roads)
        zero = [0.0] * len(self.network.roads)
        self.frames: list[Frame] = [self._frame(0, 0.0, zero)]

    def step(self) -> Frame:
        if self.finished:
            raise StopIteration("rainfall series exhausted")
        rain = self.rainfall.mm_per_hour[self.tick]
        loading = self.model.step(rain, self.dt_hours)
        self.tick += 1
        self.cumulative_rain_mm += rain * self.dt_hours
        for i, value in enumerate(loading):
            if value >= 1.0 and self.onset_tick[i] is None:
                self.onset_tick[i] = self.tick
        frame = self._frame(self.tick, rain, loading)
        self.frames.append(frame)
        return frame

    def run(self, max_steps: int | None = None) -> list[Frame]:
        produced = []
        while not self.finished and (max_steps is None or len(produced) < max_steps):
            produced.append(self.step())
        return produced

    def _frame(self, tick: int, rain: float, loading: list[float]) -> Frame:
        counts = {name: 0 for name, _ in STATUS_BANDS}
        for value in loading:
            counts[status_of(value)] += 1
        return Frame(
            tick=tick,
            time=self.rainfall.start + timedelta(minutes=self.step_minutes * tick),
            rainfall_mm_per_h=rain,
            cumulative_rain_mm=self.cumulative_rain_mm,
            loading=[round(v, 4) for v in loading],
            status_counts=counts,
        )
