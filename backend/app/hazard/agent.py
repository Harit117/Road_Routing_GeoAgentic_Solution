from .schemas import HazardStatus


class HazardAgent:
    """
    Interprets the current flood simulation state.

    The flood simulation performs the actual deterministic calculations.
    The Hazard Agent converts that state into a compact hazard summary
    for the agentic layer.
    """

    def __init__(self, simulation):
        self.simulation = simulation

    def analyze(self) -> HazardStatus:
        frame = self.simulation.frames[-1]

        counts = frame.status_counts

        affected_roads = (
            counts.get("risky", 0)
            + counts.get("flooded", 0)
        )

        blocked_roads = counts.get("flooded", 0)

        flood_risk = self._overall_risk(counts)

        return HazardStatus(
            flood_risk=flood_risk,
            affected_roads=affected_roads,
            blocked_roads=blocked_roads,
            explanation=(
                f"{affected_roads} roads currently have elevated "
                f"flood risk, including {blocked_roads} flooded roads."
            ),
        )

    @staticmethod
    def _overall_risk(counts: dict[str, int]) -> str:
        """
        Convert simulation status bands into the HazardAgent's
        LOW / MEDIUM / HIGH / CRITICAL representation.
        """

        flooded = counts.get("flooded", 0)
        risky = counts.get("risky", 0)
        watch = counts.get("watch", 0)

        if flooded > 0:
            return "CRITICAL"

        if risky > 0:
            return "HIGH"

        if watch > 0:
            return "MEDIUM"

        return "LOW"