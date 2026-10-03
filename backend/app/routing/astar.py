"""Time-dependent A* over the directed road graph.

Each label carries the elapsed minutes at which the vehicle reaches a node, so
an edge's flood loading is read at the moment the vehicle would drive it.
"""

import heapq
from dataclasses import dataclass, field
from typing import Callable

from app.routing.geo import haversine_m
from app.routing.graph import RoutingGraph

# edge(road_index, enter_minute) -> (cost, minutes) or None when closed
EdgeFn = Callable[[int, float], tuple[float, float] | None]


@dataclass
class Start:
    node: int
    cost: float
    minutes: float


@dataclass
class SearchResult:
    start: Start
    road_indices: list[int] = field(default_factory=list)
    cost: float = 0.0
    minutes: float = 0.0
    expanded: int = 0


def astar(graph: RoutingGraph, starts: list[Start], goal: int, edge: EdgeFn) -> SearchResult | None:
    nodes = graph.network.nodes
    roads = graph.network.roads
    goal_xy = nodes[goal]
    speed = graph.max_speed_m_per_min

    def h(node: int) -> float:
        # Straight line at top speed: never more than the true cost, so the
        # first time the goal is popped its path is optimal.
        return haversine_m(nodes[node], goal_xy) / speed

    g: dict[int, float] = {}
    minutes: dict[int, float] = {}
    came_from: dict[int, tuple[int, int] | Start] = {}
    heap = []
    for s in starts:
        if s.cost < g.get(s.node, float("inf")):
            g[s.node] = s.cost
            minutes[s.node] = s.minutes
            came_from[s.node] = s
            heapq.heappush(heap, (s.cost + h(s.node), s.cost, s.node))

    closed = set()
    while heap:
        _, cost, node = heapq.heappop(heap)
        if node in closed or cost > g[node]:
            continue
        if node == goal:
            path = []
            while not isinstance(came_from[node], Start):
                node, road_index = came_from[node]
                path.append(road_index)
            path.reverse()
            return SearchResult(came_from[node], path, g[goal], minutes[goal], len(closed))
        closed.add(node)
        for i in graph.out[node]:
            result = edge(i, minutes[node])
            if result is None:
                continue
            edge_cost, edge_minutes = result
            nxt = roads[i].v
            new_cost = cost + edge_cost
            if new_cost < g.get(nxt, float("inf")):
                g[nxt] = new_cost
                minutes[nxt] = minutes[node] + edge_minutes
                came_from[nxt] = (node, i)
                heapq.heappush(heap, (new_cost + h(nxt), new_cost, nxt))
    return None
