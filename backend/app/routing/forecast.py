"""Flood forecast for routing: the loading of any road at any future minute.

Routing must ask "how wet will this road be when the vehicle reaches it",
not "how wet is it now". The simulation is run to the end of the rainfall
series once, and loading is interpolated between ticks.
"""

from app.simulation.engine import Simulation
from app.simulation.flood_models import create_model

_cache: dict[tuple, list[list[float]]] = {}


def forecast_frames(sim: Simulation) -> list[list[float]]:
    """Loading of every road at every tick of the whole rainfall series.

    Runs a private copy so the active simulation (shown on the map) is not
    advanced. Assumes models are deterministic.
    """
    key = (sim.model.name, tuple(sim.rainfall.mm_per_hour), sim.step_minutes, id(sim.network))
    if key not in _cache:
        copy = Simulation(sim.network, create_model(sim.model.name), sim.rainfall, sim.step_minutes)
        copy.run()
        if len(_cache) > 8:
            _cache.clear()
        _cache[key] = [f.loading for f in copy.frames]
    return _cache[key]


class FloodForecast:
    def __init__(self, frames: list[list[float]], step_minutes: int, depart_tick: int):
        self.frames = frames
        self.step_minutes = step_minutes
        self.depart_tick = depart_tick

    def loading(self, road_index: int, minutes_after_departure: float) -> float:
        t = self.depart_tick + minutes_after_departure / self.step_minutes
        last = len(self.frames) - 1
        if t >= last:  # past the forecast horizon: hold the final state
            return self.frames[last][road_index]
        k = int(t)
        a = self.frames[k][road_index]
        b = self.frames[k + 1][road_index]
        return a + (b - a) * (t - k)
