"""Multi-vehicle dispatch that keeps vehicles from jamming in flood zones.

Sharing a road is harmless on dry roads, but in a flooded or flood-prone area
a queue of emergency vehicles slows everyone, and a stalled vehicle can block
the rest for a long time. So:

* A road is jam-sensitive when it lies in a High / Very High historical
  hazard zone, or when its forecast loading at arrival is high.
* Each sensitive zone allows only so many vehicles on the same road at the
  same time (their time on it overlaps, within a small window).
* Vehicles are routed one by one, most urgent first. Each later vehicle pays
  a heavy cost for squeezing past the cap, so it is split onto another route
  when a reasonable one exists. Roads are never closed by congestion alone,
  so no vehicle is stranded.

Every dispatch also routes the fleet independently (no coordination) so the
two plans can be compared.
"""

from dataclasses import asdict, dataclass, field

from app.routing.astar import EdgeFn
from app.routing.forecast import FloodForecast
from app.routing.missions import MissionProfile
from app.routing.planner import Planner, PlanningError


@dataclass(frozen=True)
class CongestionRules:
    """PLACEHOLDER values; tune with the team."""

    # Max vehicles on one road at the same time, per zone.
    red_cap: int = 1
    orange_cap: int = 2
    # Historical hazard rank (1 = Very Low ... 5 = Very High) that makes a zone.
    red_hazard_rank: int = 5
    orange_hazard_rank: int = 4
    # Forecast loading at arrival that makes a road sensitive.
    red_loading: float = 0.8
    orange_loading: float = 0.5
    # Two vehicles are "on the road together" if their times overlap within this.
    window_min: float = 2.0
    # Cost multiplier added per vehicle over the cap (soft, never a closure).
    overflow_penalty: float = 3.0
    # For the report only: estimated slowdown per extra vehicle in a jam.
    jam_delay_factor: float = 0.5

    def zone(self, hazard_rank: int, loading: float) -> str | None:
        if hazard_rank >= self.red_hazard_rank or loading >= self.red_loading:
            return "red"
        if hazard_rank >= self.orange_hazard_rank or loading >= self.orange_loading:
            return "orange"
        return None

    def cap(self, zone: str) -> int:
        return self.red_cap if zone == "red" else self.orange_cap


# Lower runs first: urgent missions get first pick of the roads.
MISSION_PRIORITY = {"medical": 0, "evacuation": 1}
MAX_VEHICLES = 12


@dataclass
class VehicleRequest:
    id: str
    mission: MissionProfile
    origin: tuple[float, float]
    facility_id: str | None = None


@dataclass
class _Occupancy:
    """Who is on which physical road, and when (minutes after departure)."""

    slots: dict[int, list[tuple[float, float, str]]] = field(default_factory=dict)

    def count(self, road: int, start: float, end: float, window: float, exclude: str | None = None) -> int:
        return sum(
            1
            for s, e, vid in self.slots.get(road, ())
            if vid != exclude and s - window < end and start < e + window
        )

    def others(self, road: int, start: float, end: float, window: float, exclude: str) -> list[str]:
        return [
            vid
            for s, e, vid in self.slots.get(road, ())
            if vid != exclude and s - window < end and start < e + window
        ]

    def add(self, road: int, start: float, end: float, vid: str) -> None:
        self.slots.setdefault(road, []).append((start, end, vid))


class FleetDispatcher:
    def __init__(self, planner: Planner, rules: CongestionRules | None = None):
        self.planner = planner
        self.rules = rules or CongestionRules()
        graph = planner.graph
        # Both directions of a street are one physical road for congestion.
        self._physical = [min(i, graph.reverse.get(i, i)) for i in range(len(graph.network.roads))]
        self._index = {r.road_id: r.index for r in graph.network.roads}

    def dispatch(
        self,
        vehicles: list[VehicleRequest],
        forecast: FloodForecast,
        blocked_road_ids: list[str] | None = None,
    ) -> dict:
        order = sorted(
            range(len(vehicles)),
            key=lambda k: (MISSION_PRIORITY.get(vehicles[k].mission.id, 9), k),
        )
        independent = {}
        coordinated = {}
        occupancy = _Occupancy()
        for k in order:
            v = vehicles[k]
            independent[v.id] = self._plan(v, forecast, blocked_road_ids, None)
            plan = self._plan(v, forecast, blocked_road_ids, self._congestion(occupancy, forecast, v.id))
            coordinated[v.id] = plan
            for start, end, phys in self._occupied(plan):
                occupancy.add(phys, start, end, v.id)

        ids = [v.id for v in vehicles]
        return {
            "rules": asdict(self.rules),
            "routing_order": [vehicles[k].id for k in order],
            "plans": {
                "coordinated": [self._vehicle(vid, coordinated[vid], independent[vid]) for vid in ids],
                "independent": [self._vehicle(vid, independent[vid], independent[vid]) for vid in ids],
            },
            "report": {
                "coordinated": self._evaluate(coordinated, ids),
                "independent": self._evaluate(independent, ids),
            },
        }

    # ---------- routing ----------

    def _plan(self, v: VehicleRequest, forecast, blocked, wrapper) -> dict:
        try:
            return self.planner.plan(
                v.mission,
                v.origin,
                forecast,
                v.facility_id,
                blocked_road_ids=blocked,
                edge_wrapper=wrapper,
            )
        except PlanningError as e:
            raise PlanningError(f"{v.id}: {e}") from e

    def _congestion(self, occupancy: _Occupancy, forecast: FloodForecast, vid: str):
        rules = self.rules
        roads = self.planner.graph.network.roads
        physical = self._physical

        def wrapper(edge: EdgeFn) -> EdgeFn:
            def congested(i: int, t: float):
                result = edge(i, t)
                if result is None:
                    return None
                cost, minutes = result
                loading = max(forecast.loading(i, t), forecast.loading(i, t + minutes))
                zone = rules.zone(roads[i].hazard_rank, loading)
                if zone is None:
                    return result
                sharing = occupancy.count(physical[i], t, t + minutes, rules.window_min, exclude=vid)
                excess = sharing + 1 - rules.cap(zone)
                if excess <= 0:
                    return result
                return cost * (1 + rules.overflow_penalty * excess), minutes

            return congested

        return wrapper

    def _occupied(self, plan: dict):
        route = plan.get("route")
        if not route:
            return []
        return [
            (s["enter_min"], s["enter_min"] + s["minutes"], self._physical[self._index[s["road_id"]]])
            for s in route["segments"]
        ]

    # ---------- reporting ----------

    def _evaluate(self, plans: dict[str, dict], ids: list[str]) -> dict:
        """Find roads where more vehicles share a jam zone than its cap allows."""
        rules = self.rules
        roads = self.planner.graph.network.roads
        occupancy = _Occupancy()
        for vid in ids:
            for start, end, phys in self._occupied(plans[vid]):
                occupancy.add(phys, start, end, vid)

        overloaded: dict[int, dict] = {}
        delay = 0.0
        sensitive_m = 0.0
        for vid in ids:
            route = plans[vid].get("route")
            if not route:
                continue
            for s in route["segments"]:
                i = self._index[s["road_id"]]
                zone = rules.zone(roads[i].hazard_rank, s["loading"])
                if zone is None:
                    continue
                sensitive_m += s["length_m"]
                start, end = s["enter_min"], s["enter_min"] + s["minutes"]
                others = occupancy.others(self._physical[i], start, end, rules.window_min, exclude=vid)
                excess = len(others) + 1 - rules.cap(zone)
                if excess <= 0:
                    continue
                delay += s["minutes"] * rules.jam_delay_factor * excess
                phys = self._physical[i]
                entry = overloaded.setdefault(
                    phys,
                    {
                        "road_id": roads[phys].road_id,
                        "name": roads[phys].name,
                        "zone": zone,
                        "cap": rules.cap(zone),
                        "vehicles": set(),
                        "length_m": round(roads[phys].length_m, 1),
                        "coords": [list(c) for c in roads[phys].coords],
                    },
                )
                if zone == "red":
                    entry["zone"], entry["cap"] = "red", rules.red_cap
                entry["vehicles"].update([vid, *others])

        minutes = [plans[vid]["route"]["minutes"] for vid in ids if plans[vid].get("route")]
        roads_out = sorted(overloaded.values(), key=lambda e: (-len(e["vehicles"]), e["road_id"]))
        for e in roads_out:
            e["vehicles"] = sorted(e["vehicles"])
        return {
            "overloaded_roads": len(roads_out),
            "overloaded_m": round(sum(e["length_m"] for e in roads_out), 1),
            "estimated_jam_delay_min": round(delay, 2),
            "jam_zone_m": round(sensitive_m, 1),
            "mean_minutes": round(sum(minutes) / len(minutes), 2) if minutes else None,
            "max_minutes": round(max(minutes), 2) if minutes else None,
            "roads": roads_out,
        }

    @staticmethod
    def _vehicle(vid: str, plan: dict, baseline: dict) -> dict:
        route = plan.get("route")
        base = baseline.get("route")
        return {
            "id": vid,
            "mission": plan["mission"],
            "status": plan["status"],
            "origin": plan["origin"],
            "destination": plan["destination"],
            "route": route,
            "warnings": plan["warnings"],
            # Minutes this vehicle gives up so the fleet avoids jams.
            "extra_minutes": round(route["minutes"] - base["minutes"], 2) if route and base else None,
            "changed": bool(route and base and route["road_ids"] != base["road_ids"]),
        }
