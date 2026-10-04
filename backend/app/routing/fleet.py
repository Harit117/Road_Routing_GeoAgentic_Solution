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
* Congestion changes the route, not the destination: each vehicle keeps the
  facility it would pick alone, unless another one is faster in jam-adjusted
  time (drive + expected jam delay) by at least switch_min_minutes AND
  switch_min_fraction, or its own facility is only reachable over the flood
  limit while another is not.

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
    # Expected jam delay per extra vehicle over the cap, as a share of that
    # road's drive time. Red-zone jams last longer. This one number is used
    # both by the router (as added cost, never a closure) and for jam-adjusted
    # ETAs, so a detour is only taken when it really saves time.
    orange_jam_factor: float = 1.0
    red_jam_factor: float = 2.0
    # Never accept a detour longer than this to avoid a jam (the larger of the
    # two); beyond it the vehicle keeps its direct route and the jam is reported.
    max_detour_min: float = 2.0
    max_detour_fraction: float = 0.30
    # Congestion re-routes a vehicle; it does not send it to a different
    # facility unless that is clearly faster once jams are counted: the other
    # facility's jam-adjusted time must beat its own by BOTH margins.
    switch_min_minutes: float = 2.0
    switch_min_fraction: float = 0.15

    def zone(self, hazard_rank: int, loading: float) -> str | None:
        if hazard_rank >= self.red_hazard_rank or loading >= self.red_loading:
            return "red"
        if hazard_rank >= self.orange_hazard_rank or loading >= self.orange_loading:
            return "orange"
        return None

    def cap(self, zone: str) -> int:
        return self.red_cap if zone == "red" else self.orange_cap

    def jam_delay(self, zone: str, minutes: float, excess: int) -> float:
        if excess <= 0:
            return 0.0
        factor = self.red_jam_factor if zone == "red" else self.orange_jam_factor
        return minutes * factor * excess

    def detour_limit(self, direct_minutes: float) -> float:
        return max(self.max_detour_min, self.max_detour_fraction * direct_minutes)


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
class MovingVehicle:
    """A vehicle mid-trip: where it is now and the route it is driving."""

    id: str
    mission: MissionProfile
    position: tuple[float, float]
    road_id: str  # road it is on
    follow_road_ids: list[str]  # rest of its route, starting with road_id
    destination_id: str
    forced: bool = False  # destination chosen by the user: never switched


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
        decisions = {}
        occupancy = _Occupancy()
        for k in order:
            v = vehicles[k]
            alone = self._plan(v, forecast, blocked_road_ids, None)
            independent[v.id] = alone
            plan, decisions[v.id] = self._coordinated_plan(v, alone, forecast, blocked_road_ids, occupancy)
            coordinated[v.id] = plan
            for start, end, phys in self._occupied(plan):
                occupancy.add(phys, start, end, v.id)

        ids = [v.id for v in vehicles]
        return {
            "rules": asdict(self.rules),
            "routing_order": [vehicles[k].id for k in order],
            "plans": {
                "coordinated": [
                    self._vehicle(vid, coordinated[vid], independent[vid], decisions[vid]) for vid in ids
                ],
                "independent": [self._vehicle(vid, independent[vid], independent[vid], None) for vid in ids],
            },
            "report": {
                "coordinated": self._evaluate(coordinated, ids),
                "independent": self._evaluate(independent, ids),
            },
        }

    def replan(
        self,
        vehicles: list[MovingVehicle],
        forecast: FloodForecast,
        blocked_road_ids: list[str] | None = None,
    ) -> dict:
        """Re-check a fleet that is already driving (live, every few minutes).

        Same flood logic as single-vehicle drive mode: each vehicle keeps its
        route unless a road ahead will be over its flood limit when reached,
        is blocked, or a clearly better route appeared. Vehicles are
        re-checked medical-first against the others' remaining routes, so the
        congestion rules keep holding while the fleet drives. A vehicle keeps
        its facility unless that can no longer be reached safely.
        """
        order = sorted(
            range(len(vehicles)),
            key=lambda k: (MISSION_PRIORITY.get(vehicles[k].mission.id, 9), k),
        )
        occupancy = _Occupancy()
        results = {}
        for k in order:
            v = vehicles[k]
            wrapper = self._congestion(occupancy, forecast, v.id)
            try:
                plan = self.planner.plan(
                    v.mission,
                    v.position,
                    forecast,
                    v.destination_id,
                    origin_road_id=v.road_id,
                    follow_road_ids=v.follow_road_ids,
                    blocked_road_ids=blocked_road_ids,
                    edge_wrapper=wrapper,
                )
                if plan["status"] != "ok" and not v.forced:
                    # Own facility no longer reachable within the flood limit:
                    # look for one that is (safety beats proximity).
                    other = self.planner.plan(
                        v.mission,
                        v.position,
                        forecast,
                        None,
                        origin_road_id=v.road_id,
                        blocked_road_ids=blocked_road_ids,
                        edge_wrapper=wrapper,
                    )
                    if other["status"] == "ok" and other["destination"]["id"] != v.destination_id:
                        other["reroute"] = {
                            "changed": True,
                            "reason": (
                                f"{v.destination_id} can no longer be reached within the flood limit; "
                                f"heading to {other['destination']['id']}"
                            ),
                        }
                        plan = other
            except PlanningError as e:
                raise PlanningError(f"{v.id}: {e}") from e
            results[v.id] = plan
            for start, end, phys in self._occupied(plan):
                occupancy.add(phys, start, end, v.id)

        return {
            "routing_order": [vehicles[k].id for k in order],
            "vehicles": [
                {
                    "id": v.id,
                    "mission": results[v.id]["mission"],
                    "status": results[v.id]["status"],
                    "destination": results[v.id]["destination"],
                    "route": results[v.id]["route"],
                    "reroute": results[v.id]["reroute"],
                    "warnings": results[v.id]["warnings"],
                }
                for v in vehicles
            ],
        }

    # ---------- routing ----------

    def _plan(self, v: VehicleRequest, forecast, blocked, wrapper, facility_id=None) -> dict:
        try:
            return self.planner.plan(
                v.mission,
                v.origin,
                forecast,
                facility_id or v.facility_id,
                blocked_road_ids=blocked,
                edge_wrapper=wrapper,
            )
        except PlanningError as e:
            raise PlanningError(f"{v.id}: {e}") from e

    def _coordinated_plan(self, v, alone: dict, forecast, blocked, occupancy: "_Occupancy"):
        """Decide this vehicle's coordinated plan, given vehicles already routed.

        1. Route: take the jam-avoiding route to its own facility only if it is
           faster in jam-adjusted time than driving the direct route through
           the jam, and the detour stays within the detour limit.
        2. Facility: keep its own facility unless another one is clearly
           faster once expected jam delay is counted.
        """
        home = alone.get("destination")
        if home is None or not alone.get("route"):
            return alone, None
        wrapper = self._congestion(occupancy, forecast, v.id)

        direct = self._jam_adjusted(alone, occupancy, v.id)
        to_home, home_eff, route_reason = alone, direct, None
        if direct["jam_delay"] > 0:
            split = self._plan(v, forecast, blocked, wrapper, facility_id=home["id"])
            split_eff = self._jam_adjusted(split, occupancy, v.id)
            detour = split_eff["total_drive"] - direct["total_drive"]
            limit = self.rules.detour_limit(direct["total_drive"])
            if split.get("route") and split["route"]["road_ids"] == alone["route"]["road_ids"]:
                route_reason = (
                    f"Kept direct route: no other road avoids the jam (~{direct['jam_delay']:.1f} min expected)"
                )
            elif split["status"] != "ok" and alone["status"] == "ok":
                route_reason = "Kept direct route: the alternative goes over the flood limit"
            elif detour > limit:
                route_reason = (
                    f"Kept direct route through the jam: avoiding it needs +{detour:.1f} min "
                    f"(limit {limit:.1f})"
                )
            elif split_eff["total"] >= direct["total"]:
                route_reason = (
                    f"Kept direct route: a detour (+{detour:.1f} min) would not beat "
                    f"waiting in the jam (+{direct['jam_delay']:.1f} min)"
                )
            else:
                to_home, home_eff = split, split_eff
                avoided = direct["jam_delay"] - split_eff["jam_delay"]
                cost = f"+{detour:.1f} min drive" if detour >= 0.05 else (
                    f"{-detour:.1f} min shorter drive" if detour <= -0.05 else "same drive time"
                )
                route_reason = f"Re-routed: {cost}, avoids ~{avoided:.1f} min of jam"

        decision = {
            "home": home["id"],
            "chosen": home["id"],
            "switched": False,
            "home_minutes": home_eff["minutes"],
            "home_jam_delay_min": home_eff["jam_delay"],
            "alternative": None,
            "route_reason": route_reason,
            "reason": route_reason or f"Kept {home['id']}: no jam on its route",
        }
        if v.facility_id:
            return to_home, decision  # destination forced by the user

        best = self._plan(v, forecast, blocked, wrapper)
        alt = best.get("destination")
        if alt is None or alt["id"] == home["id"] or not best.get("route"):
            return to_home, decision

        alt_eff = self._jam_adjusted(best, occupancy, v.id)
        if to_home["status"] != "ok" and best["status"] == "ok":
            # Safety beats proximity: the own facility is only reachable over
            # the flood limit, the other one within it.
            decision.update(
                chosen=alt["id"],
                switched=True,
                alternative=alt["id"],
                alt_minutes=alt_eff["minutes"],
                alt_jam_delay_min=alt_eff["jam_delay"],
                reason=f"Switched to {alt['id']}: {home['id']} is only reachable over the flood limit",
            )
            return best, decision
        if best["status"] != "ok" and to_home["status"] == "ok":
            return to_home, decision
        saving = home_eff["total"] - alt_eff["total"]
        needed = max(self.rules.switch_min_minutes, self.rules.switch_min_fraction * home_eff["total"])
        decision.update(
            alternative=alt["id"],
            alt_minutes=alt_eff["minutes"],
            alt_jam_delay_min=alt_eff["jam_delay"],
            saving_min=round(saving, 2),
            needed_min=round(needed, 2),
        )
        if saving >= needed:
            decision.update(
                chosen=alt["id"],
                switched=True,
                reason=(
                    f"Switched to {alt['id']}: {alt_eff['total']:.1f} min vs {home_eff['total']:.1f} min "
                    f"to {home['id']} with jams, saves {saving:.1f} min (needs {needed:.1f})"
                ),
            )
            return best, decision
        if route_reason is None:
            decision["reason"] = (
                f"Kept {home['id']}: {alt['id']} would save only {saving:.1f} min (needs {needed:.1f})"
                if saving > 0
                else f"Kept {home['id']}: {alt['id']} is not faster ({alt_eff['total']:.1f} vs {home_eff['total']:.1f} min with jams)"
            )
        return to_home, decision

    def _jam_adjusted(self, plan: dict, occupancy: "_Occupancy", vid: str) -> dict:
        """Drive time plus the delay expected from vehicles already routed."""
        route = plan.get("route")
        if not route:
            return {"minutes": None, "jam_delay": None, "total": float("inf"), "total_drive": float("inf")}
        roads = self.planner.graph.network.roads
        delay = 0.0
        for s in route["segments"]:
            i = self._index[s["road_id"]]
            zone = self.rules.zone(roads[i].hazard_rank, s["loading"])
            if zone is None:
                continue
            start = s["enter_min"]
            sharing = occupancy.count(self._physical[i], start, start + s["minutes"], self.rules.window_min, exclude=vid)
            delay += self.rules.jam_delay(zone, s["minutes"], sharing + 1 - self.rules.cap(zone))
        return {
            "minutes": round(route["minutes"], 2),
            "jam_delay": round(delay, 2),
            "total": route["minutes"] + delay,
            "total_drive": route["minutes"],
        }

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
                # Add exactly the expected jam delay, in minutes: the same
                # figure used to judge the route, so A* never "pays" more
                # detour than the jam would actually cost.
                delay = rules.jam_delay(zone, minutes, sharing + 1 - rules.cap(zone))
                return (cost + delay, minutes) if delay else result

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
                delay += rules.jam_delay(zone, s["minutes"], excess)
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
    def _vehicle(vid: str, plan: dict, baseline: dict, decision: dict | None) -> dict:
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
            # Why this facility: own one kept, or switched because clearly faster.
            "destination_decision": decision,
        }
