from app.routing.missions import MISSIONS


class MissionRoutingAdapter:
    """
    Converts the semantic mission understood by the Mission Agent
    into the routing mission understood by the existing routing system.
    """

    MISSION_MAP = {
        "TRAUMA": "medical",
        "MEDICAL_SUPPLY": "medical",
        "RESCUE": "evacuation",
        "RELIEF": "evacuation",
    }

    def get_routing_mission(self, mission_type: str):
        """
        Convert Mission Agent mission type into an existing
        routing MissionProfile.
        """

        mission_type = mission_type.upper().strip()

        if mission_type not in self.MISSION_MAP:
            raise ValueError(
                f"Unsupported mission type: {mission_type}"
            )

        routing_id = self.MISSION_MAP[mission_type]

        return MISSIONS[routing_id]

    def get_routing_mission_id(self, mission_type: str) -> str:
        """
        Return the routing mission ID used by the routing API.
        """

        mission_type = mission_type.upper().strip()

        if mission_type not in self.MISSION_MAP:
            raise ValueError(
                f"Unsupported mission type: {mission_type}"
            )

        return self.MISSION_MAP[mission_type]