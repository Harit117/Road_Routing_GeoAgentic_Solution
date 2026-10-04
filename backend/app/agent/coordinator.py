from app.hazard.agent import HazardAgent
from app.mission.mission_service import MissionService
from app.mission.mission_routing_service import MissionRoutingService


class Coordinator:
    """
    Coordinates the mission, hazard, and routing components.

    The Coordinator handles agent-level decisions.
    Deterministic services perform the actual hazard and route calculations.
    """

    def __init__(self, planner, simulation):
        self.mission_service = MissionService()
        self.hazard_agent = HazardAgent(simulation)
        self.routing_service = MissionRoutingService(planner, simulation)

    def process(
        self,
        user_request: str,
        origin: tuple[float, float],
    ):
        mission_state = self.mission_service.process_request(user_request)

        hazard_status = self.hazard_agent.analyze()
        mission_state.hazard_status = hazard_status.model_dump()

        route_result = self.routing_service.plan(
            mission_state,
            origin,
        )

        mission_state.selected_route = route_result

        decision = self._make_initial_decision(
            mission_state,
            hazard_status,
        )

        return {
            "mission": mission_state.model_dump(),
            "hazard": hazard_status.model_dump(),
            "route": route_result,
            "decision": decision,
        }

    def reassess(
        self,
        mission_state,
        origin: tuple[float, float],
    ):
        """
        Reassess an existing mission after the environment changes.

        The Hazard Agent checks the current simulation state.
        If the hazard level has changed, the routing service
        recalculates the route.
        """

        previous_hazard = mission_state.hazard_status

        current_hazard = self.hazard_agent.analyze()
        current_hazard_data = current_hazard.model_dump()

        mission_state.previous_hazard_status = previous_hazard
        mission_state.hazard_status = current_hazard_data

        hazard_changed = (
            previous_hazard is not None
            and previous_hazard.get("flood_risk")
            != current_hazard_data.get("flood_risk")
        )

        if hazard_changed:
            route_result = self.routing_service.plan(
                mission_state,
                origin,
            )

            mission_state.selected_route = route_result

            decision = {
                "action": "REROUTE",
                "reason": (
                    "Flood risk changed, so the Coordinator "
                    "requested a new route."
                ),
            }

            return {
                "mission": mission_state.model_dump(),
                "hazard": current_hazard_data,
                "route": route_result,
                "decision": decision,
            }

        decision = {
            "action": "ROUTE_MAINTAINED",
            "reason": (
                "Current hazard conditions have not changed "
                "enough to require rerouting."
            ),
        }

        return {
            "mission": mission_state.model_dump(),
            "hazard": current_hazard_data,
            "route": mission_state.selected_route,
            "decision": decision,
        }

    @staticmethod
    def _make_initial_decision(mission_state, hazard_status):
        if hazard_status.flood_risk in {"HIGH", "CRITICAL"}:
            return {
                "action": "ROUTE_SELECTED_WITH_HIGH_HAZARD",
                "reason": (
                    "A route was selected while elevated flood risk "
                    "was present."
                ),
            }

        return {
            "action": "ROUTE_SELECTED",
            "reason": (
                f"{mission_state.mission_type} mission classified as "
                f"{mission_state.priority} priority and routed using "
                "the current hazard conditions."
            ),
        }