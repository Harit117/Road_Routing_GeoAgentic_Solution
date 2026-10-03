"""Small geometry helpers on (lon, lat) coordinates; no GIS dependency."""

import math

EARTH_RADIUS_M = 6_371_008.8


def haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lon1, lat1, lon2, lat2 = map(math.radians, (*a, *b))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


def line_length_m(coords: list[tuple[float, float]]) -> float:
    return sum(haversine_m(coords[k], coords[k + 1]) for k in range(len(coords) - 1))


def project_on_line(p, coords):
    """Closest point to p on a polyline.

    Returns (distance_m, segment_index, point, fraction_along_line). Uses a
    local equirectangular projection, accurate to centimetres at city scale.
    """
    kx = math.cos(math.radians(p[1])) * 111_320.0
    ky = 110_540.0
    px, py = p[0] * kx, p[1] * ky
    best = None
    walked = 0.0
    along_best = 0.0
    for k in range(len(coords) - 1):
        ax, ay = coords[k][0] * kx, coords[k][1] * ky
        bx, by = coords[k + 1][0] * kx, coords[k + 1][1] * ky
        dx, dy = bx - ax, by - ay
        seg = math.hypot(dx, dy)
        t = 0.0 if seg == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg**2))
        qx, qy = ax + t * dx, ay + t * dy
        d = math.hypot(px - qx, py - qy)
        if best is None or d < best[0]:
            best = (d, k, (qx / kx, qy / ky))
            along_best = walked + t * seg
        walked += seg
    d, k, point = best
    return d, k, point, (along_best / walked if walked else 0.0)


def split_line(coords, segment_index: int, point):
    """Split a polyline at a point lying on segment `segment_index`."""
    before = list(coords[: segment_index + 1]) + [point]
    after = [point] + list(coords[segment_index + 1 :])
    return before, after
