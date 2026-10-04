"""Mission planning: snap the start point, pick the best reachable facility
with flood-aware A*, and compare against the plain fastest route."""

from dataclasses import dataclass
from typing import Callable

from app.routing.astar import EdgeFn, SearchResult, Start, astar
from app.routing.facilities import Facility
from app.routing.forecast import FloodForecast
from app.routing.geo import split_line
from app.routing.graph import RoutingGraph, Snap
from app.routing.missions import MissionProfile
from app.simulation.engine import status_of


class PlanningError(ValueError):
    pass


# A driving vehicle switches to a new route only if it is at least this much
# cheaper than continuing, so near-equal alternatives do not flicker.
REROUTE_GAIN = 0.05


@dataclass
class _Prefix:
    """The part of the start road between the clicked point and its end node."""

    road_index: int
    coords: list
    fraction: float  # share of the road still to drive


def mission_edge(
    mission: MissionProfile, graph: RoutingGraph, fc: FloodForecast, closures: bool = True
) -> EdgeFn:
    def edge(i: int, enter_min: float):
        minutes = graph.travel_min[i]
        loading = max(fc.loading(i, enter_min), fc.loading(i, enter_min + minutes))
        if closures and loading >= mission.max_loading:
            return None
        return minutes * (1 + mission.flood_penalty_weight * loading * loading), minutes

    return edge


def fastest_edge(graph: RoutingGraph) -> EdgeFn:
    return lambda i, _t: (graph.travel_min[i], graph.travel_min[i])


def _without(blocked: set[int], edge: EdgeFn) -> EdgeFn:
    if not blocked:
        return edge
    return lambda i, t: None if i in blocked else edge(i, t)


class Planner:
    def __init__(self, graph: RoutingGraph, facilities: dict[str, Facility]):
        self.graph = graph
        self.facilities = facilities

    def plan(
        self,
        mission: MissionProfile,
        origin: tuple[float, float],
        forecast: FloodForecast,
        facility_id: str | None = None,
        origin_road_id: str | None = None,
        follow_road_ids: list[str] | None = None,
        blocked_road_ids: list[str] | None = None,
        edge_wrapper: Callable[[EdgeFn], EdgeFn] | None = None,
    ) -> dict:
        """`edge_wrapper` lets a caller add cost to roads (fleet congestion);
        it must only ever increase costs, which keeps the A* heuristic valid."""
        wrap = edge_wrapper or (lambda e: e)
        # Reported incidents (fallen tree, stalled vehicle...) close a road in
        # both directions, for every route including the plain fastest one.
        blocked: set[int] = set()
        for rid in blocked_road_ids or []:
            road = self.graph.network.by_id.get(rid)
            if road is None:
                raise PlanningError(f"unknown road {rid}")
            blocked.add(road.index)
            if road.index in self.graph.reverse:
                blocked.add(self.graph.reverse[road.index])
        on_road = None
        if origin_road_id is not None:
            if origin_road_id not in self.graph.network.by_id:
                raise PlanningError(f"unknown road {origin_road_id}")
            on_road = self.graph.network.by_id[origin_road_id].index
        snap = self.graph.snap(*origin, road_index=on_road)
        if snap is None:
            raise PlanningError(
                "That point is not near a road in the network. Click closer to a road."
            )

        if facility_id is not None:
            if facility_id not in self.facilities:
                raise PlanningError(f"unknown facility {facility_id}")
            candidates = [self.facilities[facility_id]]
        else:
            candidates = [f for f in self.facilities.values() if f.type == mission.facility_type]
        if not candidates:
            raise PlanningError(f"no {mission.facility_type} facilities configured")

        starts, prefixes = self._starts(snap, forecast, mission)
        edge = wrap(_without(blocked, mission_edge(mission, self.graph, forecast)))

        options = []
        for fac in candidates:
            found = astar(self.graph, starts, fac.node_id, edge)
            option = {"facility": fac, "result": found, "state": "cut_off"}
            if found is not None:
                site = self._site_loading(fac, forecast, found.minutes)
                option["site_loading"] = site
                option["state"] = "site_flooded" if site >= mission.max_loading else "ok"
            options.append(option)

        usable = [o for o in options if o["state"] == "ok"]
        best = min(usable, key=lambda o: o["result"].cost) if usable else None
        status = "ok"
        if best is None:
            # Nothing stays under the limit. In an emergency "no route" is not
            # an answer: fall back to the least-flooded route, clearly flagged.
            status = "no_safe_route"
            soft = wrap(_without(blocked, mission_edge(mission, self.graph, forecast, closures=False)))
            fallback = []
            for fac in candidates:
                found = astar(self.graph, starts, fac.node_id, soft)
                if found is not None:
                    fallback.append({"facility": fac, "result": found})
            best = min(fallback, key=lambda o: o["result"].cost) if fallback else None
            if best is None:
                status = "unreachable"

        # A vehicle already driving keeps its route unless something changed:
        # a road ahead will now be over the limit, or a clearly better route
        # appeared. Without this, near-equal alternatives would flicker.
        reroute = None
        if follow_road_ids:
            followed, fac, reason = self._follow(
                follow_road_ids, snap, starts, edge, forecast, mission, blocked
            )
            if followed is None:
                reroute = {"changed": True, "reason": reason}
            elif status == "ok" and best["result"].cost < followed.cost * (1 - REROUTE_GAIN):
                better = best["facility"]
                reroute = {
                    "changed": True,
                    "reason": (
                        f"{better.id} is now quicker to reach safely"
                        if better.id != fac.id
                        else "A faster safe route opened up"
                    ),
                }
            else:
                best = {"facility": fac, "result": followed}
                status = "ok"
                reroute = {"changed": False, "reason": None}

        # The route an ordinary navigator would take, ignoring floods entirely.
        fast_starts, _ = self._starts(snap, forecast, None)
        fastest_to = {}
        for o in options:
            fastest_to[o["facility"].id] = astar(
                self.graph, fast_starts, o["facility"].node_id, _without(blocked, fastest_edge(self.graph))
            )
        target = best["facility"] if best else min(
            (o["facility"] for o in options if fastest_to[o["facility"].id]),
            key=lambda f: fastest_to[f.id].minutes,
            default=None,
        )

        start_road = self.graph.network.roads[snap.road_index]
        start_loading = forecast.loading(snap.road_index, 0)
        warnings = []
        if start_loading >= mission.max_loading:
            warnings.append(
                f"The start road is already at {start_loading:.0%} loading, above the "
                f"{mission.vehicle}'s {mission.max_loading:.0%} limit."
            )

        route = self._describe(best["result"], prefixes, forecast, mission) if best else None
        if status == "no_safe_route":
            warnings.append(
                f"No route stays under the {mission.vehicle}'s {mission.max_loading:.0%} flood limit. "
                f"Showing the least-flooded route: {route['blocked_m']:.0f} m of it is over the limit."
            )
        elif status == "unreachable":
            warnings.append(f"No {mission.facility_type.replace('_', ' ')} can be reached from this road.")
        fastest = None
        if target is not None and fastest_to[target.id] is not None:
            fastest = self._describe(fastest_to[target.id], prefixes, forecast, mission)
            fastest["same_as_route"] = route is not None and fastest["road_ids"] == route["road_ids"]

        return {
            "status": status,
            "mission": mission.id,
            "depart_tick": forecast.depart_tick,
            "depart_minutes": round(forecast.depart_tick * forecast.step_minutes, 3),
            "reroute": reroute,
            "origin": {
                "clicked": list(origin),
                "snapped": list(snap.point),
                "snap_distance_m": round(snap.distance_m, 1),
                "road_id": start_road.road_id,
                "road_name": start_road.name,
                "loading": round(start_loading, 4),
            },
            "destination": self._facility_dict(best["facility"]) if best else None,
            "route": route,
            "fastest": fastest,
            "options": sorted(
                (self._option_dict(o) for o in options),
                key=lambda o: (o["state"] != "ok", o["cost"] if o["cost"] is not None else 1e9),
            ),
            "warnings": warnings,
        }

    def _starts(self, snap: Snap, fc: FloodForecast, mission: MissionProfile | None):
        """A start can be mid-road: drive the rest of it toward v, or, on a
        two-way street, back along the twin edge toward u."""
        roads = self.graph.network.roads
        road = roads[snap.road_index]
        before, after = split_line(road.coords, snap.segment_index, snap.point)
        edges = [(snap.road_index, after, 1 - snap.fraction)]
        twin = self.graph.reverse.get(snap.road_index)
        if twin is not None and roads[twin].v != road.v:
            edges.append((twin, before[::-1], snap.fraction))

        starts, prefixes = [], {}
        for i, coords, share in edges:
            minutes = self.graph.travel_min[i] * share
            cost = minutes
            if mission is not None:
                # Already on this road, so it is never closed, only penalised.
                loading = max(fc.loading(i, 0), fc.loading(i, minutes))
                cost = minutes * (1 + mission.flood_penalty_weight * loading * loading)
            node = roads[i].v
            starts.append(Start(node, cost, minutes))
            prefixes[node] = _Prefix(i, coords, share)
        return starts, prefixes

    def _follow(self, road_ids, snap: Snap, starts, edge: EdgeFn, fc: FloodForecast, mission, blocked):
        """Re-evaluate the route the vehicle is driving, from where it is now.

        Returns (result, facility, None), or (None, None, reason) when the
        route can no longer be driven within the mission's limit."""
        roads = self.graph.network.roads
        by_id = self.graph.network.by_id
        if any(r not in by_id for r in road_ids) or by_id[road_ids[0]].index != snap.road_index:
            return None, None, "Vehicle left the planned route"
        indices = [by_id[r].index for r in road_ids]
        start = next(s for s in starts if s.node == roads[snap.road_index].v)
        cost, minutes, node = start.cost, start.minutes, start.node
        for i in indices[1:]:
            if roads[i].u != node:
                return None, None, "Planned route is no longer connected"
            if i in blocked:
                return None, None, f"{roads[i].name or 'A road ahead'} was reported blocked"
            result = edge(i, minutes)
            if result is None:
                loading = max(fc.loading(i, minutes), fc.loading(i, minutes + self.graph.travel_min[i]))
                name = roads[i].name or "A road ahead"
                return None, None, (
                    f"{name} will be at {loading:.0%} loading when reached, "
                    f"over the {mission.vehicle}'s {mission.max_loading:.0%} limit"
                )
            cost += result[0]
            minutes += result[1]
            node = roads[i].v
        fac = next((f for f in self.facilities.values() if f.node_id == node), None)
        if fac is None:
            return None, None, "Planned route does not end at a facility"
        if self._site_loading(fac, fc, minutes) >= mission.max_loading:
            return None, None, f"{fac.name} will be flooded on arrival"
        return SearchResult(start, indices[1:], cost, minutes), fac, None

    def _site_loading(self, fac: Facility, fc: FloodForecast, arrive_min: float) -> float:
        return max(fc.loading(i, arrive_min) for i in fac.road_indices)

    def _describe(self, found: SearchResult, prefixes, fc: FloodForecast, mission: MissionProfile) -> dict:
        roads = self.graph.network.roads
        prefix = prefixes[found.start.node]
        legs = [(prefix.road_index, prefix.coords, prefix.fraction)]
        legs += [(i, roads[i].coords, 1.0) for i in found.road_indices]

        segments, t = [], 0.0
        exposure = {"safe": 0.0, "watch": 0.0, "risky": 0.0, "flooded": 0.0}
        for k, (i, coords, share) in enumerate(legs):
            minutes = self.graph.travel_min[i] * share
            loading = max(fc.loading(i, t), fc.loading(i, t + minutes))
            length = roads[i].length_m * share
            status = status_of(loading)
            exposure[status] += length
            segments.append(
                {
                    "road_id": roads[i].road_id,
                    "name": roads[i].name,
                    "coords": [list(c) for c in coords],
                    "length_m": round(length, 1),
                    "enter_min": round(t, 2),
                    "minutes": round(minutes, 2),
                    "loading": round(loading, 4),
                    "status": status,
                    "over_limit": loading >= mission.max_loading,
                    "is_start": k == 0,
                }
            )
            t += minutes
        segments = [s for s in segments if s["length_m"] > 0]
        return {
            "road_ids": [s["road_id"] for s in segments],
            "segments": segments,
            "distance_m": round(sum(s["length_m"] for s in segments), 1),
            "minutes": round(t, 2),
            "cost": round(found.cost, 3),
            "max_loading": max((s["loading"] for s in segments), default=0.0),
            "exposure_m": {k: round(v, 1) for k, v in exposure.items()},
            # Roads (other than the one the vehicle starts on) above the limit.
            "blocked_m": round(
                sum(s["length_m"] for s in segments if s["over_limit"] and not s["is_start"]), 1
            ),
            "nodes_expanded": found.expanded,
        }

    @staticmethod
    def _facility_dict(fac: Facility) -> dict:
        return {"id": fac.id, "type": fac.type, "name": fac.name, "lon": fac.lon, "lat": fac.lat}

    def _option_dict(self, o) -> dict:
        found = o["result"]
        return {
            "facility": self._facility_dict(o["facility"]),
            "state": o["state"],
            "minutes": round(found.minutes, 2) if found else None,
            "cost": round(found.cost, 3) if found else None,
            "site_loading": round(o["site_loading"], 4) if "site_loading" in o else None,
        }
