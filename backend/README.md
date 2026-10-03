# Backend: flood simulation and flood-aware routing

FastAPI service that loads the road network from `girlgeeks/data/processed`,
runs a tick-by-tick rainfall simulation over every road, routes emergency
missions around roads forecast to flood, and serves a map app. The flood-model
rules, travel speeds and facilities are still placeholders.

## Run

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload
```

- Map viewer: http://localhost:8000/
- API docs: http://localhost:8000/docs
- Tests: `pytest`

## How it fits together

```
girlgeeks/data/processed  ──>  network/loader.py   ──>  RoadNetwork (roads + static flood context + graph)
                                                              │
rainfall (mm/h per tick)  ──>  simulation/engine.py ──>  FloodModel.step()  ──>  loading per road, per tick
                                                              │
                                                       api/*  ──>  static/ map viewer
                                                              │
                                                       routing/ (time-dependent A*, missions, facilities)
```

**Loading** is the bucket fill level of a road: 0 = dry, 1 = flood threshold
reached. It is relative, not a water depth. The engine records, for every
road, the first tick it reached 1 (`onset_tick`).

Status bands (`simulation/engine.py`): safe < 0.5 ≤ watch < 0.8 ≤ risky < 1.0 ≤ flooded.

## Where each member plugs in

| Task | Where |
| --- | --- |
| Real flood model | Subclass `FloodModel` in `app/simulation/flood_models/`, register it in `flood_models/__init__.py`. Choose it with `"model": "<name>"` when creating a simulation. `placeholder_bucket.py` shows the contract. |
| Open-Meteo rainfall | Produce a `RainfallSeries` (`app/simulation/rainfall.py`); the hourly `precipitation` array maps 1:1 onto ticks. |
| Routing tuning | Mission limits and penalty weights: `app/routing/missions.py`. Travel speeds: `SPEED_KMH` in `app/routing/graph.py`. Facilities: `data/sample_facilities.json`. |
| Whole of Chennai | Regenerate data with `girlgeeks/scripts/02_download_roads.py` for a Chennai bbox, saving files as `chennai_roads.geojson` / `chennai_road_nodes.geojson`, then run with `FLOOD_REGION=chennai`. |

## Flood-aware routing

The user picks a mission and clicks a start point; the planner chooses the
best reachable facility of that mission's type.

| Mission | Vehicle | Goes to | Flood limit | Penalty weight |
| --- | --- | --- | --- | --- |
| `medical` | ambulance | best reachable hospital | 0.8 loading | 4 |
| `evacuation` | bus | best reachable relief centre | 0.6 loading | 8 |

How a route is found (`app/routing/`):

1. **Snap** (`graph.py`): the clicked point is projected onto the nearest road
   (within 250 m). The vehicle can drive the rest of that road forward, or
   back along its twin if the street is two-way.
2. **Forecast** (`forecast.py`): the active simulation's rainfall is run to the
   end on a private copy, giving every road's loading at every tick; loading
   is interpolated between ticks. The map simulation is not advanced.
3. **Time-dependent A\*** (`astar.py`): each label carries the minute the
   vehicle reaches a node, so a road is judged by its loading *when the
   vehicle gets there*, not now. Edge cost is
   `minutes * (1 + weight * loading^2)`; a road whose loading reaches the
   mission's limit is closed. The heuristic (straight line at top speed) never
   overestimates, so A\* returns the optimal path.
4. **Choose** (`planner.py`): A\* runs to every candidate facility. A facility
   is `cut_off` if no path stays under the limit, `site_flooded` if the roads
   touching it are over the limit on arrival. The cheapest `ok` one wins.
5. **Fallback**: if nothing stays under the limit, status is
   `no_safe_route` and the least-flooded route is returned with a warning,
   because "no route" is not an answer in an emergency.
6. **Compare**: the plain fastest route (ignoring floods) is also returned, so
   the UI can show the detour and how much flooded road it avoids.

```http
POST /api/route
{"mission": "medical", "origin": [80.212, 12.979], "depart_tick": 6}
```

Optional `facility_id` forces a destination; `depart_tick` defaults to the
active simulation's current tick. The response has `status`
(`ok` | `no_safe_route` | `unreachable`), `origin` (snapped), `destination`,
`route` and `fastest` (segments with per-road loading at arrival, minutes,
distance, exposure by status, metres over the limit), `options` (every
candidate facility with its state and ETA) and `warnings`.

Rerouting is the same call from the vehicle's current position and tick: the
map app replans automatically as the storm timeline advances.

### Drive mode and rerouting

After planning, **Start trip** animates the vehicle along the route at a
chosen playback speed (10x to 120x simulated time). The flood map follows
the trip clock, interpolating loading between hourly frames. Every simulated
minute the app calls `POST /api/route` again with:

| Field | Meaning |
| --- | --- |
| `origin` + `origin_road_id` | Vehicle position, pinned to the road it is on |
| `depart_minutes` | Current trip clock, minutes since the scenario start |
| `follow_road_ids` | The rest of the route being driven |
| `blocked_road_ids` | Incidents reported so far (closed in both directions) |

The response's `reroute` says whether to switch: `{"changed": false}` keeps
the current route; a change happens only when a road ahead is blocked or will
be over the limit on arrival, the destination will flood, or a new route is at
least 5% cheaper (`REROUTE_GAIN` in `planner.py`). The 5% margin stops the
route flickering between near-equal alternatives.

Because the plan already uses the whole rainfall forecast, a trip only
re-routes when **new information** arrives:

- **Incident:** during a trip, click any road to report it blocked
  (`GET /api/snap?lon=&lat=` finds the road).
- **Rain burst:** pours heavier rain than forecast into the current hour via
  `POST /api/simulation/rainfall`, which replays the simulation to the current
  tick. On short urban trips this rarely flips a route: a few minutes of extra
  rain adds little water.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/network/summary` | Counts, bbox, roads per hazard category |
| GET | `/api/network/roads` | Road GeoJSON; property `i` indexes the loading arrays |
| GET | `/api/network/roads/{road_id}` | Static context + loading history + onset tick |
| GET | `/api/network/hazard-zones` | Hazard polygons clipped to the network area |
| GET | `/api/network/flood-points` | Recorded inundation points in the area |
| GET | `/api/simulation/models`, `/presets` | Available flood models and rainfall presets |
| POST | `/api/simulation` | New simulation: `{"preset": "cloudburst"}` or `{"rainfall_mm_per_h": [5, 8, 20]}`, optional `model`, `start_time` |
| GET | `/api/simulation` | Current tick, rainfall, per-tick status counts |
| POST | `/api/simulation/step?n=1`, `/run`, `/reset` | Advance or rewind |
| POST | `/api/simulation/rainfall` | Replace the rainfall series mid-storm (replays to the current tick) |
| GET | `/api/simulation/frames/{tick}` | Loading of every road at a tick |
| GET | `/api/simulation/onset` | Roads in the order they reached the flood threshold |
| GET | `/api/health` | Service health |
| GET | `/api/flood-risk/model-status` | Model implementation/calibration status for consumers |
| GET | `/api/flood-risk/roads/{road_id}` | Latest active-simulation state for one road |
| POST | `/api/flood-risk/roads:batch` | Latest active-simulation state for requested road IDs |
| POST | `/api/flood-risk/simulate` | Run an isolated rainfall scenario and return per-road outputs |
| GET | `/api/missions` | Mission profiles (medical, evacuation) |
| GET | `/api/facilities?type=` | Hospitals and relief centres, with the roads touching each |
| POST | `/api/route` | Flood-aware route and mid-trip replanning, see below |
| GET | `/api/snap?lon=&lat=` | Nearest road to a point |

### Routing handoff: Flood & Risk Engineer (Member 2) → Routing Engineer (Member 3)

The `/api/flood-risk` endpoints provide the routing integration contract. `loading`
is a relative bucket value (`1.0` means the threshold was reached), `status` is one
of `safe`, `watch`, `risky`, or `flooded`, and
`time_to_threshold_minutes` is elapsed time from the scenario start (or `null` if
the threshold was not reached during the run). These are placeholder-model outputs;
check `/api/flood-risk/model-status` before treating them as calibrated predictions.

Fetch selected current road states in one call:

```http
POST /api/flood-risk/roads:batch
Content-Type: application/json

{"road_ids": ["osm_299880378_313444440_0", "osm_299880378_313444440_1"]}
```

Response shape:

```json
{
  "states": [
    {
      "road_id": "osm_299880378_313444440_0",
      "status": "safe",
      "loading": 0.0,
      "rainfall_mm_per_h": 0.0,
      "cumulative_rain_mm": 0.0,
      "observed_at": "2026-10-03T12:00:00",
      "time_to_threshold_minutes": null,
      "source": "placeholder_simulation"
    }
  ],
  "unknown_road_ids": ["osm_299880378_313444440_1"],
  "observed_at": "2026-10-03T12:00:00",
  "model_status": "placeholder"
}
```

Run a what-if scenario without changing the active simulation used by the map or
single-road/batch current-state endpoints:

```http
POST /api/flood-risk/simulate
Content-Type: application/json

{
  "scenario_name": "heavy-rain",
  "rainfall_mm_per_h": [5, 12, 25, 30, 18, 8],
  "start_time": "2026-10-03T12:00:00Z"
}
```

Use `preset` instead of `rainfall_mm_per_h` to select a built-in series. The
response includes `model_status`, `model_name`, scenario timing, and a `states`
array with one final state per road. Each state includes the first threshold
time observed during that scenario. A single-road lookup is available at
`GET /api/flood-risk/roads/{road_id}`; unknown roads return 404. Batch requests
report unknown IDs in `unknown_road_ids` while returning known roads normally.

The schema is defined in `app/api/schemas.py`; the calculations are isolated in
`app/simulation/flood_risk_service.py` so Member 2 can replace the placeholder
adapter as the historical-susceptibility and calibrated bucket model is built.

## Data notes

- Road hazard = highest category among all hazard polygons the road crosses
  (from `road_hazard_links.csv`).
- Road flood depth = deepest recorded inundation within 50 m, read from
  `road_flood_point_links.csv` itself, because `flood_point_id` is not unique
  in the source points (IDs 24–30, 119 and 120 each name 2–3 different places).
- One simulation is held in memory per server process.
