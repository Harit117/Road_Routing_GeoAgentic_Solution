# Backend: flood simulation and flood-aware routing

FastAPI service that loads the road network from `girlgeeks/data/processed`,
runs a tick-by-tick rainfall simulation over every road using the
susceptibility-based road flood-risk model (`app/flood/`), routes emergency
missions around roads forecast to flood, and serves a map app. Model
coefficients, travel speeds and facilities are prototype values, not
calibrated.

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

**Loading** (simulation, map and routing) is a road's bucket fill divided by its
road-specific threshold: 0 = dry, 1 = threshold reached, above 1 = past it.
The default `susceptibility_bucket` model computes it from `app/flood/`
(susceptibility, threshold = B_MAX × (1 − susceptibility), normalized bucket
filling). The engine records, for every road, the first tick it reached 1
(`onset_tick`).

For flood-risk API responses, `current_flood_loading` and `threshold` are
normalized model quantities, while `risk_score` is the clamped ratio of those
quantities. The legacy `loading` field aliases `risk_score`, so 1.0 means the
road-specific threshold was reached. None of these values is a water depth.

Status bands (`simulation/engine.py`): safe < 0.5 ≤ watch < 0.8 ≤ risky < 1.0 ≤ flooded.

## Where each member plugs in

| Task | Where |
| --- | --- |
| Road flood-risk model | `app/flood/` contains susceptibility, rainfall providers, normalized bucket dynamics, and risk progression. `app/simulation/flood_risk_service.py` adapts it to the established Member 3 API. |
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

## Fleet dispatch: keeping vehicles from jamming in flood zones

When many emergency sites are close together, routing every vehicle
independently sends them down the same roads. On dry roads that is fine; in a
flood zone a queue of vehicles slows everyone and one stalled vehicle can block
the rest. `POST /api/fleet/dispatch` (`app/routing/fleet.py`) routes a whole
fleet so that does not happen.

| Zone | When (checked at each vehicle's arrival time) | Vehicles at a time |
| --- | --- | --- |
| Green | everything else | unlimited |
| Orange | High hazard zone, or forecast loading ≥ 50% | 2 |
| Red | Very High hazard zone, or loading ≥ 80% | 1 |

* "At a time" means the vehicles' time on the road overlaps within ±2 min;
  both directions of a street count as one road.
* Vehicles are routed one by one, medical before evacuation. Everything is
  judged in **jam-adjusted time** = drive minutes + expected jam delay, where
  each vehicle over a road's cap adds that road's drive time × 1 (orange) or
  × 2 (red). The router adds exactly that delay as cost, so it never trades a
  long detour for a short jam.
* A vehicle is re-routed only if the detour beats waiting in the jam, and
  never by more than `max_detour_min` (2) or `max_detour_fraction` (30%) of
  its direct drive, whichever is larger. Otherwise it keeps the direct route
  and the jam is reported. Congestion never closes a road.
* Congestion changes the **route, not the destination**. Each vehicle keeps
  the facility it would choose alone, unless another one is faster in
  **jam-adjusted time** (drive minutes + expected jam delay from vehicles
  already routed) by at least `switch_min_minutes` (2) **and**
  `switch_min_fraction` (15%), or its own facility is only reachable over the
  flood limit while another is reachable within it. Each coordinated vehicle
  carries a `destination_decision` with both times and the reason.
* Every response holds both `plans.coordinated` and `plans.independent`
  (everyone routes alone) and a `report` for each: roads over cap, metres over
  cap, an estimated jam delay, average and slowest drive.
* Rules are `CongestionRules` in `fleet.py` (`GET /api/fleet/rules`):
  PLACEHOLDER values to tune.

```http
POST /api/fleet/dispatch
{"vehicles": [{"mission": "medical", "origin": [80.212, 12.979]},
              {"mission": "medical", "origin": [80.2112, 12.9783]}],
 "depart_tick": 5}
```

In the map app, switch to **Fleet**, click roads to place up to 8 vehicles,
compare the Coordinated / Uncoordinated tabs, and press **Play fleet**.

During **Play fleet** the fleet is re-checked live, like single-vehicle drive
mode: every simulated minute `POST /api/fleet/replan` re-plans each moving
vehicle (medical first, against the others' remaining routes so the jam rules
still hold). A vehicle re-routes when a road ahead is blocked or will be over
its flood limit when reached; it changes facility only if its own can no longer
be reached safely. Click a road to report an incident; **Rain burst** pours
heavier rain than forecast. Flood colours follow the trip clock.

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
| GET | `/health`, `/api/health` | Service health |
| GET | `/api/flood-risk/model-status` | Model status, prototype parameters, calibration/live-feed limitations |
| GET | `/api/flood-risk/roads/{road_id}` | Active-input state; optional `?scenario=heavy` for historical forcing |
| POST | `/api/flood-risk/roads:batch` | Active-input states, or selected scenario with `{"road_ids":[...],"scenario":"heavy"}` |
| POST | `/api/flood-risk/simulate` | Isolated historical `scenario`, existing `preset`, or manual hourly rainfall input |
| GET | `/api/missions` | Mission profiles (medical, evacuation) |
| GET | `/api/facilities?type=` | Hospitals and relief centres, with the roads touching each |
| POST | `/api/route` | Flood-aware route and mid-trip replanning, see below |
| GET | `/api/snap?lon=&lat=` | Nearest road to a point |
| POST | `/api/fleet/dispatch` | Route several vehicles, splitting them in flood zones (see Fleet dispatch) |
| POST | `/api/fleet/replan` | Live re-check of a driving fleet (positions, routes being followed, incidents) |
| GET | `/api/fleet/rules` | Congestion rules in use |

### Routing handoff: Flood & Risk Engineer (Member 2) → Routing Engineer (Member 3)

The `/api/flood-risk` endpoints preserve the routing integration paths and core
response fields while adding susceptibility, road-specific threshold, current
normalized loading, clamped risk score/level, and threshold timing. `loading`
continues as a routing-compatible alias for `risk_score`; legacy `status` values
remain `safe`, `watch`, `risky`, or `flooded`. `time_to_threshold_minutes` is
retained, and `time_to_threshold_hours` is also returned. Either timing field is
null when the selected rainfall series did not reach the road threshold.

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
      "susceptibility": 0.42,
      "threshold": 0.58,
      "current_flood_loading": 0.0,
      "risk_score": 0.0,
      "risk_level": "LOW",
      "threshold_reached": false,
      "elapsed_hours": 0.0,
      "time_to_threshold_hours": null,
      "rainfall_mm_per_h": 0.0,
      "cumulative_rain_mm": 0.0,
      "observed_at": "2026-10-03T12:00:00",
      "time_to_threshold_minutes": null,
      "source": "preset:intensifying_storm"
    }
  ],
  "unknown_road_ids": ["osm_299880378_313444440_1"],
  "observed_at": "2026-10-03T12:00:00",
  "scenario": null,
  "model_status": "scenario_based_prototype"
}
```

Run an isolated historical or caller-supplied scenario without changing the
active simulation used by the map or current-state endpoints:

```http
POST /api/flood-risk/simulate
Content-Type: application/json

{"scenario": "heavy"}
```

The response contains `model_status`, `model_name`, source and scenario timing,
and one final road state per road. `scenario` accepts `normal`, `moderate`,
`heavy`, or `extreme`. Existing `preset` and `rainfall_mm_per_h` request forms
remain supported. Single-road lookup optionally accepts the same scenario as a
query parameter. Batch requests can include a scenario and continue to report
unknown IDs in `unknown_road_ids`.

The schema is defined in `app/api/schemas.py`; calculations are isolated in
`app/flood/` and the API adapter in `app/simulation/flood_risk_service.py`.

## Scenario-based road flood risk

The `RiskEngine` combines historical inundation evidence from
`road_flood_point_links.csv` and hazard evidence from `road_hazard_links.csv`.
Depth is normalized to the deepest linked depth in the loaded network; hazard
rank is normalized to the OpenCity rank maximum. By default susceptibility is
`0.60 * normalized_depth + 0.40 * normalized_hazard`, with either weight
configurable. A road without a linked observation receives zero evidence for
that component; no depth/category is invented.

For susceptibility `S_i`, the normalized threshold is `B_i = B_MAX * (1-S_i)`.
Each hourly rainfall amount is normalized by a configurable 40.2 mm reference,
then multiplied by `BASE_FILL_RATE + SUSCEPTIBILITY_GAIN * S_i`. Defaults are
`B_MAX=1`, base fill `0.20`, and susceptibility gain `0.80`. These are
transparent prototype parameters, not physically calibrated runoff constants.
The bucket is capped at `B_MAX`; risk is `min(1, F_i/B_i)`. A zero threshold is
handled as immediately reached with a critical score, without division by zero.
Risk labels are application labels, not official flood classifications.

Parameters can be overridden with `FLOOD_RISK_B_MAX`,
`FLOOD_RISK_BASE_FILL_RATE`, `FLOOD_RISK_SUSCEPTIBILITY_GAIN`,
`FLOOD_RISK_RAINFALL_REFERENCE_MM`, `FLOOD_RISK_DEPTH_WEIGHT`,
`FLOOD_RISK_HAZARD_WEIGHT`, `FLOOD_RISK_LOW_MAX`,
`FLOOD_RISK_MODERATE_MAX`, and `FLOOD_RISK_HIGH_MAX`.

The model estimates relative road risk and time-to-threshold under a selected
rainfall forcing. It does not predict exact water depth or exact flood onset and
does not implement physically calibrated hydrology. OpenCity historical flood
observations describe spatial susceptibility; the Velachery rainfall scenarios
provide temporal forcing. No live rainfall source is configured. Current-state
responses use the active simulation input (the startup demo preset by default)
and identify that source; historical scenario responses are explicitly
scenario-based rather than live conditions.

Generate the per-road hourly export with:

```bash
python girlgeeks/scripts/05_build_road_flood_risk.py
```

This writes `girlgeeks/data/processed/road_flood_risk_scenarios.csv` with one
final state row per road and scenario after consuming all 48 hourly rainfall
observations. The `hour` column is the elapsed scenario hour represented by the
final state; `time_to_threshold_hours` records the first crossing during the
full sequence, or is blank when the threshold was not reached.

## Data notes

- Road hazard = highest category among all hazard polygons the road crosses
  (from `road_hazard_links.csv`).
- Road flood depth = deepest recorded inundation within 50 m, read from
  `road_flood_point_links.csv` itself, because `flood_point_id` is not unique
  in the source points (IDs 24–30, 119 and 120 each name 2–3 different places).
- One simulation is held in memory per server process.
