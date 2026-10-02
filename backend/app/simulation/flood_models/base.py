"""Contract between the simulation engine and a flood model.

The engine owns time and rainfall; a model owns the physics/rules. To add the
real model, subclass FloodModel and register it in flood_models/__init__.py.
"""

from abc import ABC, abstractmethod

from app.network.models import RoadNetwork


class FloodModel(ABC):
    name: str = "base"
    description: str = ""

    @abstractmethod
    def reset(self, network: RoadNetwork) -> None:
        """Derive per-road parameters (e.g. bucket capacity) and zero the state."""

    @abstractmethod
    def step(self, rainfall_mm_per_h: float, dt_hours: float) -> list[float]:
        """Advance one tick and return the loading of every road, indexed by
        Road.index. Loading is relative: 0 = dry, 1 = flood threshold reached.
        Values above 1 are allowed (further past the threshold)."""
