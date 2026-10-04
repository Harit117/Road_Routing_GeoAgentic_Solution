from app.hazard.agent import HazardAgent
from app.mission.mission_service import MissionService
from app.mission.mission_routing_service import MissionRoutingService


class Coordinator:
    """
    Coordinates the different agents and deterministic services.

    The Coordinator does not perform flood calculations or routing
    itself. It delegates those tasks to the appropriate component.
    """

    def __init__(self, planner, simulation):
        self.mission_service = MissionService()

        self.hazard_agent = HazardAgent(
            simulation
        )

        self.routing_service = MissionRoutingService(
            planner,
            simulation
        )

    def process(
        self,
        user_request: str,
        origin: tuple[float, float],
    ):
        # --------------------------------------------------
        # 1. Understand the mission
        # --------------------------------------------------

        mission_state = self.mission_service.process_request(
            user_request
        )

        # --------------------------------------------------
        # 2. Analyze current hazards
        # --------------------------------------------------

        hazard_status = self.hazard_agent.analyze()

        # Store hazard information in shared mission state.
        mission_state.hazard_status = hazard_status.model_dump()

        # --------------------------------------------------
        # 3. Plan the mission-specific route
        # --------------------------------------------------

        route_result = self.routing_service.plan(
            mission_state,
            origin,
        )

        # Store route information in shared mission state.
        mission_state.selected_route = route_result

        # --------------------------------------------------
        # 4. Return combined agentic result
        # --------------------------------------------------

        return {
            "mission": mission_state.model_dump(),
            "hazard": hazard_status.model_dump(),
            "route": route_result,
        }