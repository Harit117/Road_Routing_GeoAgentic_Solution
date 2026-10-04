from app.routing.forecast import FloodForecast, forecast_frames

from .routing_adapter import MissionRoutingAdapter
from .state import MissionState


class MissionRoutingService:
    """
    Connects the Mission Agent to the existing deterministic
    flood-aware routing system.
    """

    def __init__(self, planner, simulation):
        self.planner = planner
        self.simulation = simulation
        self.adapter = MissionRoutingAdapter()

    def plan(self, state: MissionState, origin: tuple[float, float]):
        # Convert our agent's mission type into the routing system's
        # existing mission profile.
        routing_mission = self.adapter.get_routing_mission(
            state.mission_type
        )

        # Build the flood forecast used by the existing Planner.
        forecast = FloodForecast(
            forecast_frames(self.simulation),
            self.simulation.step_minutes,
            self.simulation.tick,
        )

        # If a specific facility ID was supplied, use it.
        # Otherwise the Planner selects the best suitable facility.
        facility_id = None

        if state.destination:
            destination = state.destination.strip().upper()

            if destination in self.planner.facilities:
                facility_id = destination

        # Call the existing deterministic routing system.
        result = self.planner.plan(
            routing_mission,
            origin,
            forecast,
            facility_id=facility_id,
        )

        return result