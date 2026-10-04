from .agent import MissionAgent
from .facility_resolver import FacilityResolver
from .state import MissionState


class MissionService:
    def __init__(self):
        self.mission_agent = MissionAgent()
        self.facility_resolver = FacilityResolver()

    def process_request(self, user_request: str) -> MissionState:

        # Step 1: Understand the mission
        mission = self.mission_agent.analyze(user_request)

        # Step 2: Determine relevant facility type
        if mission.mission_type in ["TRAUMA", "MEDICAL_SUPPLY"]:
            facility_type = "hospital"

        elif mission.mission_type in ["RESCUE", "RELIEF"]:
            facility_type = "relief_centre"

        # Step 3: Find candidate facilities
        facilities = self.facility_resolver.find_by_type(
            facility_type
        )

        # Step 4: Create shared mission state
        state = MissionState(
            mission_type=mission.mission_type,
            priority=mission.priority,
            origin=mission.origin,
            destination=mission.destination,
            time_weight=mission.time_weight,
            safety_weight=mission.safety_weight,
            payload_sensitivity=mission.payload_sensitivity,
            confidence=mission.confidence,
            facility_type=facility_type,
            candidate_facilities=facilities,
            explanation=mission.explanation,
        )

        return state