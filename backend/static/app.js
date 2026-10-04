"use strict";

/* =================== Constants =================== */
const css = getComputedStyle(document.documentElement);
const cssVar = (name) => css.getPropertyValue(name).trim();
const STATUS = ["safe", "watch", "risky", "flooded"];
const STATUS_COLORS = Object.fromEntries(STATUS.map((s) => [s, cssVar(`--${s}`)]));
const STATUS_LABELS = { safe: "Safe", watch: "Watch", risky: "Risky", flooded: "Flooded" };
const HAZARD_COLORS = {
  "Very High": "#7f0000",
  "High": "#d7301f",
  "Moderate": "#f08a4b",
  "Low": "#fdb863",
  "Very Low": "#fde3a7",
  "None": "#c4c8cf",
};
const ROAD_WEIGHT = { primary: 3.2, primary_link: 2.4, secondary: 2.8, tertiary: 2.2 };
const ICONS = {
  hospital: '<svg viewBox="0 0 24 24"><path d="M9 3h6v6h6v6h-6v6H9v-6H3V9h6z"/></svg>',
  relief_centre: '<svg viewBox="0 0 24 24"><path d="M12 3 2 11h3v10h5v-6h4v6h5V11h3z"/></svg>',
  medical: '<svg viewBox="0 0 24 24"><path d="M3 7h11v3h3.5l3.5 4v4h-2a2.5 2.5 0 0 1-5 0H9a2.5 2.5 0 0 1-5 0H3zm4 1v2H5v2h2v2h2v-2h2v-2H9V8z"/></svg>',
  evacuation: '<svg viewBox="0 0 24 24"><path d="M5 4h14a2 2 0 0 1 2 2v11h-1.2a2.5 2.5 0 0 1-4.6 0H8.8a2.5 2.5 0 0 1-4.6 0H3V6a2 2 0 0 1 2-2zm0 2v5h6V6zm8 0v5h6V6z"/></svg>',
  check: '<svg viewBox="0 0 24 24"><path d="M9.5 16.2 5.3 12l-1.4 1.4 5.6 5.6L20.1 8.4 18.7 7z"/></svg>',
  detour: '<svg viewBox="0 0 24 24"><path d="M14 4l2.3 2.3-2.9 2.9 1.4 1.4 2.9-2.9L20 10V4zM10 4H4v6l2.3-2.3 4.7 4.7V20h2v-8.4l-5.3-5.3z"/></svg>',
  alert: '<svg viewBox="0 0 24 24"><path d="M1 21h22L12 2zm12-3h-2v-2h2zm0-4h-2v-4h2z"/></svg>',
  info: '<svg viewBox="0 0 24 24"><path d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm1 15h-2v-6h2zm0-8h-2V7h2z"/></svg>',
  rain: '<svg viewBox="0 0 24 24"><path d="M12 3s-6 6.6-6 11a6 6 0 0 0 12 0c0-4.4-6-11-6-11z"/></svg>',
  close: '<svg viewBox="0 0 24 24"><path d="M19 6.4 17.6 5 12 10.6 6.4 5 5 6.4l5.6 5.6L5 17.6 6.4 19l5.6-5.6 5.6 5.6 1.4-1.4-5.6-5.6z"/></svg>',
};
const FACILITY_WORD = { hospital: "hospital", relief_centre: "relief centre" };

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
const fmtMin = (m) => (m < 1 ? "<1" : Math.round(m).toString());
const fmtDist = (m) => (m >= 1000 ? `${(m / 1000).toFixed(1)} km` : `${Math.round(m)} m`);
const pct = (x) => `${Math.round(x * 100)}%`;
const hhmm = (t) => new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
const shortName = (name) => name.replace(/^Sample [^,]+, /, "");

const state = {
  mode: "sim",
  info: null,
  tick: 0,
  loading: null,
  frames: new Map(),
  playing: null,
  missions: [],
  facilities: [],
  mission: "medical",
  facilityId: "",
  origin: null,
  plan: null,
  planSeq: 0,
  planning: false,
  planError: null,
  fitPending: false,
  tab: "directions",
  drive: null, // active trip, see "Drive mode"
  speed: 30, // playback: simulated seconds per real second
  // Fleet mode (see "Fleet mode")
  fleetMode: false,
  fleet: [], // [{id, mission, origin: [lon, lat]}]
  fleetPlan: null, // last /api/fleet/dispatch response
  fleetView: "coordinated",
  fleetSeq: 0,
  fleetPlanning: false,
  fleetError: null,
  fleetPlay: null,
};
const currentMission = () => state.missions.find((m) => m.id === state.mission);

/* =================== Map =================== */
const map = L.map("map", { preferCanvas: true, zoomControl: false });
L.control.zoom({ position: "bottomright" }).addTo(map);
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  attribution: "&copy; OpenStreetMap contributors",
  maxZoom: 19,
  className: "basemap",
}).addTo(map);
map.createPane("routePane").style.zIndex = 450;

let roadLayers = [];
let roadProps = [];
let pointsLayer = null;
const facilityMarkers = new Map();
const routeLayer = L.layerGroup().addTo(map);
let originMarker = null;

/* =================== API =================== */
async function api(path, options) {
  const res = await fetch(path, options);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = body.detail;
    throw new Error(typeof d === "string" ? d : d?.[0]?.msg || `Request failed (${res.status})`);
  }
  return body;
}
const post = (path, body) =>
  api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });

function statusOf(x) {
  let label = "safe";
  for (const [name, lower] of Object.entries(state.info.status_bands)) if (x >= lower) label = name;
  return label;
}

/* =================== Roads & legend =================== */
function roadColor(i) {
  if (state.mode === "sim" && state.loading) return STATUS_COLORS[statusOf(state.loading[i])];
  return HAZARD_COLORS[roadProps[i].hazard || "None"];
}

function restyleRoads() {
  const opacity = state.plan?.route || state.drive || state.fleetPlan ? 0.28 : 0.85;
  for (let i = 0; i < roadLayers.length; i++) roadLayers[i].setStyle({ color: roadColor(i), opacity });
  renderLegend();
}

function renderLegend() {
  const sim = state.mode === "sim";
  const bands = state.info?.status_bands || {};
  const items = sim
    ? STATUS.map((k) => [STATUS_COLORS[k], `${STATUS_LABELS[k]}${bands[k] ? ` ≥${pct(bands[k])}` : ""}`])
    : Object.entries(HAZARD_COLORS).map(([k, c]) => [c, k]);
  const at = state.drive ? minuteTime(state.drive.nowMin) : state.info ? hhmm(state.info.frames[state.tick].time) : "";
  const title = sim ? `Flood forecast at ${at}` : "Historical hazard category";
  let html = `<div class="lg-title">${title}</div><div class="lg-row">${items
    .map(([c, label]) => `<span><i class="swatch" style="background:${c}"></i>${label}</span>`)
    .join("")}</div>`;
  if (state.fleetMode && state.fleetPlan) {
    html += `<div class="lg-row"><span><i class="line-key" style="border-top:4px solid #64748b;border-radius:2px"></i>Vehicle routes (one colour each)</span><span><i class="line-key" style="border-top:4px dashed #111827"></i>Jam: over zone cap</span></div>`;
  } else if (state.drive) {
    html += `<div class="lg-row"><span><i class="line-key route"></i>Route ahead</span><span><i class="line-key" style="border-top:4px solid #64748b;border-radius:2px"></i>Driven</span></div>`;
  } else if (state.plan?.route) {
    html += `<div class="lg-row"><span><i class="line-key route"></i>Flood-aware route</span>${
      state.plan.fastest && !state.plan.fastest.same_as_route ? `<span><i class="line-key fast"></i>Fastest route</span>` : ""
    }</div>`;
  }
  $("legend").innerHTML = html;
}

/* =================== Timeline =================== */
function renderTimeline() {
  const info = state.info;
  const frame = info.frames[state.tick];
  const nextRain = info.rainfall_mm_per_h[state.tick];
  $("clockTime").textContent = hhmm(frame.time);
  $("clockHour").textContent = `Hour ${state.tick} of ${info.total_ticks}`;
  $("clockRain").innerHTML =
    `${ICONS.rain}<span>${nextRain != null ? `<b>${nextRain}</b> mm/h next hour` : "Storm over"} · ${Math.round(frame.cumulative_rain_mm)} mm so far</span>`;
  const total = Object.values(frame.status_counts).reduce((a, b) => a + b, 0) || 1;
  $("netBar").innerHTML = STATUS.map(
    (k) => `<span style="width:${(frame.status_counts[k] / total) * 100}%;background:${STATUS_COLORS[k]}"></span>`
  ).join("");
  $("netBar").parentElement.title = STATUS.map((k) => `${STATUS_LABELS[k]}: ${frame.status_counts[k].toLocaleString()} roads`).join("\n");
  const slider = $("slider");
  slider.max = info.total_ticks;
  slider.value = state.tick;
  $("step").disabled = state.tick >= info.total_ticks;
  renderChart();
}

// The slider thumb travels between 8px from each edge; align bars and labels with it.
const THUMB_INSET = 8;

function renderChart() {
  const svg = $("rainChart");
  const rain = state.info.rainfall_mm_per_h;
  const W = svg.clientWidth || 600;
  const H = 30;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  const max = Math.max(10, ...rain);
  const inner = W - 2 * THUMB_INSET;
  const w = inner / rain.length;
  // Bar k is the rain falling between hour k and k+1.
  svg.innerHTML = rain
    .map((r, k) => {
      const h = Math.max((r / max) * (H - 2), r > 0 ? 2 : 0);
      const cls = k < state.tick ? "bar past" : k === state.tick ? "bar now" : "bar";
      return `<rect class="${cls}" rx="2" x="${THUMB_INSET + k * w + 1.5}" y="${H - h}" width="${Math.max(w - 3, 1)}" height="${h}"><title>${r} mm/h</title></rect>`;
    })
    .join("");
  const n = state.info.total_ticks;
  const every = Math.max(1, Math.ceil(n / 6));
  const labels = [];
  for (let k = 0; k <= n; k += every) labels.push(k);
  $("hourLabels").innerHTML = labels
    .map((k) => `<span style="left:calc(${THUMB_INSET}px + (100% - ${2 * THUMB_INSET}px) * ${k / n})">${hourLabel(k)}</span>`)
    .join("");
}

function hourLabel(k) {
  const start = new Date(state.info.frames[0].time);
  return hhmm(new Date(start.getTime() + k * state.info.step_minutes * 60000));
}

async function goToTick(tick) {
  const info = state.info;
  tick = Math.max(0, Math.min(tick, info.total_ticks));
  if (tick > info.frames.length - 1) {
    state.info = await post(`/api/simulation/step?n=${tick - (info.frames.length - 1)}`);
  }
  if (!state.frames.has(tick)) {
    const f = await api(`/api/simulation/frames/${tick}`);
    state.frames.set(tick, f.loading);
  }
  state.tick = tick;
  state.loading = state.frames.get(tick);
  renderTimeline();
  restyleRoads();
  renderFacilities();
  schedulePlan();
}

function stopPlaying() {
  clearInterval(state.playing);
  state.playing = null;
  $("playIcon").setAttribute("d", "M8 5v14l11-7z");
  $("play").title = "Play storm";
}

async function togglePlay() {
  if (state.playing) return stopPlaying();
  if (state.tick >= state.info.total_ticks) await goToTick(0);
  setMode("sim");
  $("playIcon").setAttribute("d", "M7 5h4v14H7zM13 5h4v14h-4z");
  $("play").title = "Pause";
  let busy = false;
  state.playing = setInterval(async () => {
    if (busy) return;
    if (state.tick >= state.info.total_ticks) return stopPlaying();
    busy = true;
    await goToTick(state.tick + 1);
    busy = false;
  }, 1100);
}

function setMode(mode) {
  state.mode = mode;
  document.querySelector(`input[name=mode][value=${mode}]`).checked = true;
  restyleRoads();
}

/* =================== Facilities =================== */
function facilityStatus(f) {
  if (!state.loading) return "safe";
  return statusOf(Math.max(...f.road_indices.map((i) => state.loading[i])));
}

function renderFacilities() {
  const mission = currentMission();
  const destId = state.drive ? state.drive.dest?.id : state.plan?.destination?.id;
  const fleetDests = new Set(
    state.fleetMode && state.fleetPlan ? fleetVehicles().map((v) => v.destination?.id).filter(Boolean) : []
  );
  const fleetTypes = new Set(state.fleet.map((v) => state.missions.find((m) => m.id === v.mission)?.facility_type));
  for (const f of state.facilities) {
    const status = facilityStatus(f);
    const active = state.fleetMode && state.fleet.length ? fleetTypes.has(f.type) : f.type === mission?.facility_type;
    const isDest = state.fleetMode ? fleetDests.has(f.id) : f.id === destId;
    const cls = ["fac", active ? "" : "dim", isDest ? "dest" : "", status !== "safe" ? `flood-${status}` : ""].join(" ");
    const html = `<div class="${cls}"><div class="fac-icon ${f.type}">${ICONS[f.type]}</div><span class="fac-id">${f.id}</span></div>`;
    let marker = facilityMarkers.get(f.id);
    if (!marker) {
      marker = L.marker([f.lat, f.lon], { riseOnHover: true, keyboard: false })
        .on("click", () => chooseFacility(f.id))
        .addTo(map);
      facilityMarkers.set(f.id, marker);
    }
    if (marker._html !== html) {
      marker.setIcon(L.divIcon({ html, className: "", iconSize: [30, 30], iconAnchor: [15, 15] }));
      marker._html = html;
    }
    marker.setZIndexOffset(f.id === destId ? 1000 : active ? 500 : 0);
    marker.bindTooltip(
      `<b>${f.id} · ${esc(shortName(f.name))}</b><br>` +
        `<span style="color:${STATUS_COLORS[status]}">●</span> Access roads ${STATUS_LABELS[status].toLowerCase()} now` +
        `<br><small class="muted">Click to route here</small>`,
      { direction: "top", offset: [0, -16] }
    );
  }
}

function chooseFacility(id) {
  const f = state.facilities.find((x) => x.id === id);
  if (!f || state.drive || state.fleetMode) return;
  const mission = state.missions.find((m) => m.facility_type === f.type);
  if (mission && mission.id !== state.mission) setMission(mission.id, false);
  state.facilityId = id;
  renderFacilitySelect();
  renderFacilities();
  schedulePlan(true);
}

/* =================== Mission & trip =================== */
function renderMissions() {
  $("missions").innerHTML = state.missions
    .map((m) => {
      const color = m.facility_type === "hospital" ? "var(--hospital)" : "var(--relief)";
      return `<button class="mission" role="radio" aria-checked="${m.id === state.mission}" data-id="${m.id}">
        <span class="m-icon" style="background:${color}">${ICONS[m.id] || ""}</span>
        <span><b>${esc(m.label)}</b><small>${m.vehicle[0].toUpperCase() + m.vehicle.slice(1)} to ${FACILITY_WORD[m.facility_type]}</small></span>
      </button>`;
    })
    .join("");
  $("missions").querySelectorAll(".mission").forEach((el) => el.addEventListener("click", () => setMission(el.dataset.id)));
}

function renderFacilitySelect() {
  const mission = currentMission();
  const word = FACILITY_WORD[mission.facility_type];
  const own = state.facilities.filter((f) => f.type === mission.facility_type);
  $("facility").innerHTML =
    `<option value="">Best reachable ${word}</option>` +
    own.map((f) => `<option value="${f.id}">${f.id} · ${esc(shortName(f.name))}</option>`).join("");
  $("facility").value = state.facilityId;
  document.querySelector(".trip-dot.end").className = `trip-dot end ${mission.facility_type}`;
}

function setMission(id, replan = true) {
  if (state.mission === id) return;
  state.mission = id;
  state.facilityId = "";
  renderMissions();
  renderFacilitySelect();
  renderFacilities();
  if (replan) schedulePlan(true);
  else renderResult();
}

function renderStart() {
  const box = $("startBox");
  if (!state.origin) {
    box.innerHTML = `<div class="start-text placeholder"><b>Click a road on the map</b></div>`;
    return;
  }
  const o = state.plan?.origin;
  const name = o ? o.road_name || "Unnamed road" : state.planError ? "No road here" : "Finding road…";
  const sub = o ? `Start · ${pct(o.loading)} flood loading now` : "Start";
  box.innerHTML = `<div class="start-text"><small>${sub}</small><b>${esc(name)}</b></div>
    <button class="icon-x" id="clearStart" title="Clear start point (Esc)" aria-label="Clear start point">${ICONS.close}</button>`;
  $("clearStart").addEventListener("click", clearOrigin);
}

function setOrigin(latlng) {
  state.origin = [latlng.lng, latlng.lat];
  state.plan = null;
  renderStart();
  schedulePlan(true);
}

function clearOrigin() {
  state.origin = null;
  state.plan = null;
  state.planError = null;
  routeLayer.clearLayers();
  if (originMarker) originMarker.remove();
  originMarker = null;
  renderStart();
  renderResult();
  restyleRoads();
  renderFacilities();
}

/* =================== Planning =================== */
let planTimer = null;
function schedulePlan(immediate = false) {
  if (state.fleetMode) return scheduleFleet(immediate);
  if (!state.origin || state.drive) return;
  if (immediate) state.fitPending = true; // a user choice: frame the new trip
  clearTimeout(planTimer);
  planTimer = setTimeout(plan, immediate ? 0 : 120);
}

async function plan() {
  const seq = ++state.planSeq;
  state.planning = true;
  state.planError = null;
  renderResult();
  try {
    const body = { mission: state.mission, origin: state.origin, depart_tick: state.tick };
    if (state.facilityId) body.facility_id = state.facilityId;
    const result = await post("/api/route", body);
    if (seq !== state.planSeq || state.drive) return; // superseded, or a trip started
    state.plan = result;
  } catch (e) {
    if (seq !== state.planSeq) return;
    state.plan = null;
    state.planError = e.message;
  }
  state.planning = false;
  drawPlan();
  if (state.fitPending && state.plan?.route) {
    state.fitPending = false;
    const pts = state.plan.route.segments.flatMap((s) => s.coords.map((c) => [c[1], c[0]]));
    const bounds = L.latLngBounds(pts);
    if (!map.getBounds().pad(-0.12).contains(bounds)) {
      map.fitBounds(bounds.pad(0.3), { maxZoom: 16, paddingTopLeft: [0, 70], paddingBottomRight: [0, 110] });
    }
  }
  renderStart();
  renderResult();
  restyleRoads();
  renderFacilities();
}

function drawPlan() {
  routeLayer.clearLayers();
  const p = state.plan;
  if (!p) {
    if (originMarker) originMarker.remove();
    originMarker = null;
    return;
  }
  const ll = (c) => [c[1], c[0]];
  const pane = "routePane";

  if (p.fastest && !p.fastest.same_as_route) {
    const coords = p.fastest.segments.map((s) => s.coords.map(ll));
    L.polyline(coords, { pane, color: "#fff", weight: 6, opacity: 0.9, interactive: false }).addTo(routeLayer);
    L.polyline(coords, { pane, color: "#334155", weight: 3, opacity: 0.95, dashArray: "6 7" })
      .bindTooltip(
        `<b>Fastest route</b> · ignores flooding<br>${fmtMin(p.fastest.minutes)} min` +
          (p.fastest.blocked_m > 0 ? ` · <b style="color:var(--danger-text)">${fmtDist(p.fastest.blocked_m)} over limit</b>` : ""),
        { sticky: true }
      )
      .addTo(routeLayer);
  }
  if (p.route) {
    const all = p.route.segments.map((s) => s.coords.map(ll));
    L.polyline(all, { pane, color: "#0f172a", weight: 13, opacity: 0.18, interactive: false }).addTo(routeLayer);
    L.polyline(all, { pane, color: "#fff", weight: 10, opacity: 1, interactive: false }).addTo(routeLayer);
    for (const s of p.route.segments) {
      L.polyline(s.coords.map(ll), { pane, color: STATUS_COLORS[s.status], weight: 6, opacity: 1, lineCap: "round" })
        .bindTooltip(
          `<b>${esc(s.name || "Unnamed road")}</b><br>Reached at +${fmtMin(s.enter_min)} min · ${pct(s.loading)} loading` +
            (s.over_limit ? `<br><b style="color:var(--danger-text)">Over this vehicle's limit</b>` : ""),
          { sticky: true }
        )
        .addTo(routeLayer);
    }
  }
  const o = p.origin.snapped;
  if (!originMarker) {
    originMarker = L.marker([o[1], o[0]], {
      icon: L.divIcon({ html: '<div class="origin-pin"></div>', className: "", iconSize: [20, 20], iconAnchor: [10, 10] }),
      zIndexOffset: 2000,
      keyboard: false,
    }).addTo(map);
  } else {
    originMarker.setLatLng([o[1], o[0]]);
  }
  originMarker.bindTooltip(`Start · ${esc(p.origin.road_name || "unnamed road")}`, { direction: "top", offset: [0, -10] });
}

/* =================== Result panel =================== */
function renderResult() {
  if (state.fleetMode) return renderFleetResult();
  const el = $("result");
  const mission = currentMission();
  const word = FACILITY_WORD[mission.facility_type];
  const head = `<div class="result-head"><h2>Route</h2>${state.planning ? '<span class="spinner"></span>' : ""}</div>`;

  if (!state.origin) {
    el.innerHTML = `${head}<ol class="guide">
      <li class="done">Choose a mission: <b>${esc(mission.label)}</b></li>
      <li>Click a road on the map to set where the ${esc(mission.vehicle)} starts</li>
      <li>The best reachable ${word} is chosen using the flood forecast. Press play to watch the route adapt as the storm grows.</li>
    </ol>`;
    return;
  }
  if (state.planError) {
    el.innerHTML = `${head}${alert("danger", state.planError)}`;
    return;
  }
  const p = state.plan;
  if (!p) {
    el.innerHTML = `${head}<div class="skeleton"></div>`;
    return;
  }
  const warnings = p.warnings.map((w) => alert(p.status === "ok" ? "warn" : "danger", w)).join("");
  if (!p.route) {
    el.innerHTML = head + warnings + tabs(p);
    bindResult();
    return;
  }

  const r = p.route;
  const f = p.fastest;
  const d = p.destination;
  const arrive = new Date(new Date(p.depart_time).getTime() + r.minutes * 60000);
  let verdict;
  if (p.status !== "ok") verdict = `<span class="verdict over">${ICONS.alert}Over flood limit</span>`;
  else if (f && !f.same_as_route) verdict = `<span class="verdict detour">${ICONS.detour}Flood detour</span>`;
  else verdict = `<span class="verdict clear">${ICONS.check}Clear route</span>`;
  const destSub =
    p.status !== "ok" ? "Least-flooded option" : state.facilityId ? "Chosen destination" : `Best reachable ${word}`;

  el.innerHTML =
    head +
    `<div class="hero">
      <div class="hero-top">
        ${verdict}
        <div class="eta"><b>${fmtMin(r.minutes)}</b><span class="unit">min</span><span class="meta">${fmtDist(r.distance_m)} · arrive ${hhmm(arrive)}</span></div>
        <div class="dest"><span class="badge ${d.type}">${d.id}</span><span class="grow"><b>${esc(shortName(d.name))}</b><span>${destSub}</span></span></div>
      </div>
      <div class="hero-exp">${exposure(r)}</div>
    </div>` +
    warnings +
    comparison(p, mission) +
    `<div class="start-trip"><button class="primary" id="startTrip"><svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>Start trip</button></div>` +
    speedPicker() +
    tabs(p);
  bindResult();
}

function alert(kind, text) {
  const icon = kind === "ok" ? ICONS.check : kind === "warn" ? ICONS.info : ICONS.alert;
  return `<div class="alert ${kind}">${icon}<span>${text}</span></div>`;
}

function exposure(route) {
  const total = route.distance_m || 1;
  const parts = STATUS.map((k) => [k, route.exposure_m[k]]).filter(([, m]) => m > 0);
  return `<div class="exp-head"><span>Flood exposure on this route</span><span class="muted">peak ${pct(route.max_loading)} loading</span></div>
    <div class="exposure">${parts
      .map(([k, m]) => `<span style="width:${(m / total) * 100}%;background:${STATUS_COLORS[k]}" title="${STATUS_LABELS[k]}: ${fmtDist(m)}"></span>`)
      .join("")}</div>
    <div class="exp-legend">${parts.map(([k, m]) => `<span><i class="dot" style="background:${STATUS_COLORS[k]}"></i>${STATUS_LABELS[k]} ${fmtDist(m)}</span>`).join("")}${
      route.blocked_m > 0 ? `<span style="color:var(--danger-text);font-weight:600">${fmtDist(route.blocked_m)} over limit</span>` : ""
    }</div>`;
}

function comparison(p, mission) {
  const f = p.fastest;
  const r = p.route;
  if (!f) return "";
  if (f.same_as_route) {
    return p.status === "ok" ? alert("ok", "This is also the fastest route. No flood detour is needed right now.") : "";
  }
  const extra = r.minutes - f.minutes;
  const cell = (v, cls = "") => `<td class="${cls}">${v}</td>`;
  return `<table class="compare">
    <tr><th></th><th><i class="line-key route"></i>This route</th><th><i class="line-key fast"></i>Fastest</th></tr>
    <tr><td>Drive time</td>${cell(`${fmtMin(r.minutes)} min`, "us")}${cell(`${fmtMin(f.minutes)} min`)}</tr>
    <tr><td>Over ${mission.vehicle} limit (${pct(mission.max_loading)})</td>${cell(fmtDist(r.blocked_m), r.blocked_m > 0 ? "bad" : "good")}${cell(fmtDist(f.blocked_m), f.blocked_m > 0 ? "bad" : "")}</tr>
    <tr><td>Peak flood loading</td>${cell(pct(r.max_loading), "us")}${cell(pct(f.max_loading))}</tr>
  </table>${
    extra >= 0.5
      ? `<p class="muted" style="margin:-4px 0 0;font-size:12px">The detour adds about ${Math.max(1, Math.round(extra))} min to keep the ${mission.vehicle} on drier roads.</p>`
      : ""
  }`;
}

function directions(route, dest) {
  // Merge consecutive segments on the same road into one step.
  const steps = [];
  for (const s of route.segments) {
    const name = s.name || "Unnamed road";
    const last = steps[steps.length - 1];
    if (last && last.name === name) {
      last.length += s.length_m;
      last.loading = Math.max(last.loading, s.loading);
      last.over ||= s.over_limit && !s.is_start;
    } else {
      steps.push({ name, length: s.length_m, at: s.enter_min, loading: s.loading, over: s.over_limit && !s.is_start });
    }
  }
  return `<ol class="steps">${steps
    .map(
      (s) => `<li><i class="dot" style="background:${STATUS_COLORS[statusOf(s.loading)]}"></i><span class="name" title="${esc(s.name)}">${esc(s.name)}</span>${
        s.over ? `<span class="over">over limit</span>` : ""
      }<span class="num">${fmtDist(s.length)}</span><span class="num">+${fmtMin(s.at)}′</span></li>`
    )
    .join("")}<li class="end"><span class="badge sm ${dest.type}">${dest.id}</span><span class="name">Arrive at ${esc(shortName(dest.name))}</span><span class="num">${fmtMin(route.minutes)} min</span></li></ol>`;
}

function tabs(p) {
  const word = FACILITY_WORD[currentMission().facility_type];
  const back = state.facilityId ? `<button class="link" id="autoDest">← Back to best reachable ${word}</button>` : "";
  const hasDirections = !!p.route;
  const tab = hasDirections ? state.tab : "options";
  const showOptions = p.options.length > 1;
  const header =
    hasDirections && showOptions
      ? `<div class="tabs" role="tablist">
          <button role="tab" data-tab="directions" aria-selected="${tab === "directions"}">Directions</button>
          <button role="tab" data-tab="options" aria-selected="${tab === "options"}">All ${word}s (${p.options.length})</button>
        </div>`
      : hasDirections
        ? `<h3>Directions</h3>`
        : `<h3>All ${word}s from here</h3>`;
  const body = tab === "directions" && hasDirections ? directions(p.route, p.destination) : optionsList(p);
  return header + body + back;
}

function optionsList(p) {
  return `<ul class="options">${p.options
    .map((o) => {
      const f = o.facility;
      const chosen = p.destination && f.id === p.destination.id;
      const right =
        o.state === "ok"
          ? `${chosen && !state.facilityId && p.status === "ok" ? '<span class="chip best">Best</span>' : ""}<span class="eta-cell">${fmtMin(o.minutes)} min</span>`
          : `<span class="chip ${o.state}">${o.state === "cut_off" ? "Cut off" : "Site flooded"}</span>`;
      return `<li class="${chosen ? "chosen" : ""}" data-id="${f.id}" title="Route to ${esc(f.name)}"><span class="badge sm ${f.type}">${f.id}</span><span class="name">${esc(shortName(f.name))}</span>${right}</li>`;
    })
    .join("")}</ul>`;
}

function bindResult() {
  const el = $("result");
  $("startTrip")?.addEventListener("click", startTrip);
  bindSpeed(el);
  el.querySelectorAll(".options li").forEach((li) => li.addEventListener("click", () => chooseFacility(li.dataset.id)));
  el.querySelectorAll(".tabs button").forEach((b) =>
    b.addEventListener("click", () => {
      state.tab = b.dataset.tab;
      renderResult();
    })
  );
  $("autoDest")?.addEventListener("click", () => {
    state.facilityId = "";
    renderFacilitySelect();
    schedulePlan(true);
  });
}

/* =================== Drive mode =================== */
// Playback speeds: simulated seconds per real second.
const SPEEDS = [10, 30, 60, 120];
const REPLAN_EVERY_MIN = 1; // re-check the route every simulated minute
const RAIN_BURST_MM = 80; // extra rain poured into the current hour
const driveLayer = L.layerGroup().addTo(map);
let roadIndexById = new Map();
let vehicleMarker = null;
let trailLine = null;
let toastTimer = null;

const fmtSec = (s) => (s >= 1 ? `${Math.round(s)} s` : `${s.toFixed(1)} s`);
const stepMin = () => state.info.step_minutes;
function minuteTime(min) {
  const start = new Date(state.info.frames[0].time).getTime();
  return hhmm(start + min * 60000);
}

function speedPicker() {
  return `<div class="speed">
    <div class="speed-head"><b>Drive speed</b><span class="muted">1 min of driving plays in ${fmtSec(60 / state.speed)}</span></div>
    <div class="speed-opts" role="group" aria-label="Drive speed">${SPEEDS.map(
      (s) => `<button data-speed="${s}" aria-pressed="${s === state.speed}">${s}×</button>`
    ).join("")}</div>
  </div>`;
}

function bindSpeed(root) {
  root.querySelectorAll(".speed-opts button").forEach((b) =>
    b.addEventListener("click", () => {
      state.speed = Number(b.dataset.speed);
      root.querySelectorAll(".speed-opts button").forEach((x) => x.setAttribute("aria-pressed", x === b));
      root.querySelector(".speed-head .muted").textContent = `1 min of driving plays in ${fmtSec(60 / state.speed)}`;
    })
  );
}

function showToast(title, text) {
  const t = $("toast");
  t.innerHTML = `${ICONS.detour}<span><b>${esc(title)}</b>${esc(text)}</span>`;
  t.hidden = false;
  t.style.animation = "none";
  void t.offsetWidth; // restart the entry animation
  t.style.animation = "";
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), 5000);
}

/** Pre-compute lat/lng points and cumulative metres for each route segment. */
function prepareRoute(route) {
  return route.segments.map((s) => {
    const pts = s.coords.map((c) => L.latLng(c[1], c[0]));
    const cum = [0];
    for (let i = 1; i < pts.length; i++) cum.push(cum[i - 1] + pts[i - 1].distanceTo(pts[i]));
    return { ...s, pts, cum, len: cum[cum.length - 1] };
  });
}

/** Where the vehicle is `elapsed` minutes into a route. */
function positionAt(segs, elapsed) {
  for (let k = 0; k < segs.length; k++) {
    const s = segs[k];
    if (elapsed > s.enter_min + s.minutes && k < segs.length - 1) continue;
    const f = s.minutes > 0 ? Math.min(1, Math.max(0, (elapsed - s.enter_min) / s.minutes)) : 1;
    const target = f * s.len;
    let j = 0;
    while (j < s.cum.length - 2 && s.cum[j + 1] < target) j++;
    const span = s.cum[j + 1] - s.cum[j] || 1;
    const t = Math.min(1, Math.max(0, (target - s.cum[j]) / span));
    const a = s.pts[j];
    const b = s.pts[j + 1] || a;
    return { latlng: L.latLng(a.lat + (b.lat - a.lat) * t, a.lng + (b.lng - a.lng) * t), k };
  }
  return null;
}

function startTrip() {
  const p = state.plan;
  if (!p?.route) return;
  stopPlaying();
  const startMin = state.tick * stepMin();
  const mission = currentMission();
  state.drive = {
    plan: p,
    segs: prepareRoute(p.route),
    dest: p.destination,
    mission,
    tripStartMin: startMin,
    routeStartMin: startMin,
    nowMin: startMin,
    lastReplanMin: startMin,
    lastFloodStamp: null,
    lastPanelTs: 0,
    drawnFromSeg: -1,
    replanning: false,
    paused: false,
    arrived: false,
    lastTs: null,
    reroutes: 0,
    pos: null,
    blocked: [], // incidents reported during this trip
    blockLayer: L.layerGroup().addTo(driveLayer),
    events: [{ min: startMin, kind: "ok", text: `Departed for ${p.destination.id} · ${shortName(p.destination.name)}` }],
  };
  document.body.classList.add("driving");
  $("timeline").classList.add("locked");
  $("slider").step = "any";
  routeLayer.clearLayers();
  if (originMarker) originMarker.remove();
  originMarker = null;
  trailLine = L.polyline([], { pane: "routePane", color: "#64748b", weight: 6, opacity: 0.9, lineCap: "round" }).addTo(driveLayer);
  vehicleMarker = L.marker(state.drive.segs[0].pts[0], {
    icon: L.divIcon({
      html: `<div class="vehicle ${mission.id}">${ICONS[mission.id]}</div>`,
      className: "",
      iconSize: [36, 36],
      iconAnchor: [18, 18],
    }),
    zIndexOffset: 3000,
    keyboard: false,
    interactive: false,
  }).addTo(map);
  renderDrivePanel();
  restyleRoads();
  renderFacilities();
  state.drive.timer = setInterval(driveFrame, DRIVE_TICK_MS);
}

function drawRouteAhead(d, fromSeg) {
  // Redrawn only when the vehicle enters a new segment or the route changes.
  d.aheadLayer?.remove();
  const group = L.layerGroup();
  const segs = d.segs.slice(fromSeg);
  const all = segs.map((s) => s.pts);
  L.polyline(all, { pane: "routePane", color: "#fff", weight: 10, interactive: false }).addTo(group);
  for (const s of segs) {
    L.polyline(s.pts, { pane: "routePane", color: STATUS_COLORS[s.status], weight: 6, lineCap: "round" })
      .bindTooltip(`<b>${esc(s.name || "Unnamed road")}</b><br>${pct(s.loading)} loading when reached`, { sticky: true })
      .addTo(group);
  }
  group.addTo(driveLayer);
  trailLine.bringToFront();
  d.aheadLayer = group;
  d.drawnFromSeg = fromSeg;
}

// A timer, not requestAnimationFrame: the trip keeps running when the page is
// not being painted (background tab). Long gaps are capped so time never jumps.
const DRIVE_TICK_MS = 40;

function driveFrame() {
  const d = state.drive;
  if (!d) return;
  const ts = performance.now();
  if (d.lastTs != null && !d.paused && !d.arrived) {
    const dt = Math.min((ts - d.lastTs) / 1000, 0.5);
    d.nowMin += (dt * state.speed) / 60;
  }
  d.lastTs = ts;

  const elapsed = d.nowMin - d.routeStartMin;
  const pos = positionAt(d.segs, Math.min(elapsed, d.plan.route.minutes));
  if (pos) {
    d.pos = pos;
    vehicleMarker.setLatLng(pos.latlng);
    const trail = trailLine.getLatLngs();
    if (!trail.length || trail[trail.length - 1].distanceTo(pos.latlng) > 3) trailLine.addLatLng(pos.latlng);
    if (pos.k !== d.drawnFromSeg) drawRouteAhead(d, pos.k);
  }
  if (!d.arrived && elapsed >= d.plan.route.minutes) arrive(d);

  // Flood colours follow the clock (every 15 simulated seconds).
  const stamp = Math.floor(d.nowMin * 4);
  if (stamp !== d.lastFloodStamp && !d.floodBusy) {
    d.lastFloodStamp = stamp;
    updateFloodAt(d.nowMin);
  }
  if (!d.arrived && !d.paused && !d.replanning && d.nowMin - d.lastReplanMin >= REPLAN_EVERY_MIN) replanDrive(d);
  if (ts - d.lastPanelTs > 150) {
    d.lastPanelTs = ts;
    updateDriveLive(d);
  }
}

async function ensureFrame(k) {
  if (k > state.info.frames.length - 1) {
    state.info = await post(`/api/simulation/step?n=${k - (state.info.frames.length - 1)}`);
  }
  if (!state.frames.has(k)) state.frames.set(k, (await api(`/api/simulation/frames/${k}`)).loading);
  return state.frames.get(k);
}

/** Show the network's flood state at a fractional minute (between hourly frames). */
async function updateFloodAt(min) {
  const d = state.drive;
  d.floodBusy = true;
  try {
    const total = state.info.total_ticks;
    const t = Math.min(min / stepMin(), total);
    const k = Math.floor(t);
    const a = await ensureFrame(k);
    const b = await ensureFrame(Math.min(k + 1, total));
    const f = t - k;
    state.loading = f === 0 ? a : a.map((x, i) => x + (b[i] - x) * f);
    state.tick = k;
    restyleRoads();
    renderFacilities();
    renderDriveTimeline(min);
  } finally {
    d.floodBusy = false;
  }
}

function renderDriveTimeline(min) {
  const info = state.info;
  const k = Math.min(Math.floor(min / stepMin()), info.total_ticks);
  $("clockTime").textContent = minuteTime(min);
  $("clockHour").textContent = state.drive?.arrived ? "Arrived" : "Trip in progress";
  const rain = info.rainfall_mm_per_h[k];
  $("clockRain").innerHTML = `${ICONS.rain}<span>${rain != null ? `<b>${rain}</b> mm/h now` : "Storm over"}</span>`;
  const counts = { safe: 0, watch: 0, risky: 0, flooded: 0 };
  for (const x of state.loading) counts[statusOf(x)]++;
  const n = state.loading.length;
  $("netBar").innerHTML = STATUS.map((s) => `<span style="width:${(counts[s] / n) * 100}%;background:${STATUS_COLORS[s]}"></span>`).join("");
  $("slider").max = info.total_ticks;
  $("slider").value = min / stepMin();
  renderChart();
}

async function replanDrive(d) {
  if (!d.pos) return;
  d.replanning = true;
  const reqMin = d.nowMin;
  const seg = d.segs[d.pos.k];
  const body = {
    mission: d.mission.id,
    origin: [d.pos.latlng.lng, d.pos.latlng.lat],
    origin_road_id: seg.road_id,
    follow_road_ids: d.segs.slice(d.pos.k).map((s) => s.road_id),
    depart_minutes: reqMin,
    blocked_road_ids: d.blocked.map((b) => b.road_id),
  };
  if (state.facilityId) body.facility_id = state.facilityId;
  try {
    const r = await post("/api/route", body);
    if (state.drive !== d || d.arrived) return;
    if (r.route) {
      const prevDest = d.dest?.id;
      d.plan = r;
      d.segs = prepareRoute(r.route);
      d.routeStartMin = reqMin;
      d.dest = r.destination;
      d.drawnFromSeg = -1;
      if (r.reroute?.changed) {
        d.reroutes++;
        const dest = r.destination.id !== prevDest ? ` Now heading to ${r.destination.id}.` : "";
        d.events.push({ min: reqMin, kind: "reroute", text: `Re-routed: ${r.reroute.reason}.${dest}` });
        if (r.status !== "ok") {
          d.events.push({ min: reqMin, kind: "danger", text: "No safe route left. Following the least-flooded route." });
        }
        showToast(`Re-routed at ${minuteTime(reqMin)}`, `${r.reroute.reason}.${dest}`);
        renderDrivePanel();
        renderFacilities();
      }
    } else {
      d.events.push({ min: reqMin, kind: "danger", text: "No facility reachable from here any more." });
      renderDrivePanel();
    }
  } catch (e) {
    d.events.push({ min: reqMin, kind: "danger", text: `Re-planning failed: ${e.message}` });
    renderDrivePanel();
  } finally {
    d.replanning = false;
    d.lastReplanMin = reqMin;
  }
}

async function rainBurst() {
  const d = state.drive;
  if (!d || d.arrived) return;
  const k = Math.floor(d.nowMin / stepMin());
  const rain = [...state.info.rainfall_mm_per_h];
  while (rain.length <= k + 1) rain.push(0);
  rain[k] += RAIN_BURST_MM;
  rain[k + 1] += RAIN_BURST_MM / 2;
  try {
    state.info = await post("/api/simulation/rainfall", { rainfall_mm_per_h: rain });
    state.frames.clear();
    d.events.push({
      min: d.nowMin,
      kind: "rain",
      text: `Rain burst: +${RAIN_BURST_MM} mm/h this hour (now ${rain[k]} mm/h). Forecast updated.`,
    });
    d.lastFloodStamp = null; // refresh flood colours
    d.lastReplanMin = -Infinity; // and re-check the route right away
    renderDrivePanel();
  } catch (e) {
    d.events.push({ min: d.nowMin, kind: "danger", text: `Rain update failed: ${e.message}` });
    renderDrivePanel();
  }
}

/** Mid-trip map click: report the clicked road as blocked (an incident). */
async function reportIncident(latlng) {
  const d = state.drive;
  if (!d || d.arrived) return;
  let road;
  try {
    road = await api(`/api/snap?lon=${latlng.lng}&lat=${latlng.lat}`);
  } catch {
    return; // clicked away from any road
  }
  if (state.drive !== d || d.blocked.some((b) => b.road_id === road.road_id)) return;
  d.blocked.push(road);
  const pts = road.coords.map((c) => [c[1], c[0]]);
  L.polyline(pts, { pane: "routePane", color: "#fff", weight: 9, interactive: false }).addTo(d.blockLayer);
  L.polyline(pts, { pane: "routePane", color: "#111827", weight: 5, dashArray: "2 6", lineCap: "butt", interactive: false }).addTo(d.blockLayer);
  L.marker([road.point[1], road.point[0]], {
    icon: L.divIcon({ html: '<div class="incident">!</div>', className: "", iconSize: [22, 22], iconAnchor: [11, 11] }),
    interactive: false,
    keyboard: false,
  }).addTo(d.blockLayer);
  d.events.push({ min: d.nowMin, kind: "danger", text: `Incident: ${road.name || "unnamed road"} reported blocked.` });
  d.lastReplanMin = -Infinity; // re-check the route right away
  renderDrivePanel();
}

function arrive(d) {
  d.arrived = true;
  const trip = d.nowMin - d.tripStartMin;
  d.events.push({
    min: d.nowMin,
    kind: "ok",
    text: `Arrived at ${d.dest.id} after ${fmtMin(trip)} min, ${d.reroutes} re-route${d.reroutes === 1 ? "" : "s"}.`,
  });
  d.aheadLayer?.remove();
  renderDrivePanel();
  renderDriveTimeline(d.nowMin);
}

function togglePause() {
  const d = state.drive;
  if (!d || d.arrived) return;
  d.paused = !d.paused;
  renderDrivePanel();
}

function endTrip() {
  const d = state.drive;
  if (!d) return;
  clearInterval(d.timer);
  state.drive = null;
  driveLayer.clearLayers();
  vehicleMarker?.remove();
  vehicleMarker = null;
  document.body.classList.remove("driving");
  $("timeline").classList.remove("locked");
  $("slider").step = "1";
  $("toast").hidden = true;
  state.plan = null;
  state.frames.clear();
  goToTick(Math.min(Math.floor(d.nowMin / stepMin()), state.info.total_ticks));
}

function renderDrivePanel() {
  const d = state.drive;
  if (!d) return;
  const live = d.arrived
    ? `<span class="live arrived">Arrived</span>`
    : d.paused
      ? `<span class="live paused">Paused</span>`
      : `<span class="live">Driving</span>`;
  const dest = d.dest;
  $("result").innerHTML = `
    <div class="result-head"><h2>Trip</h2></div>
    <div class="drive-card">
      <div class="drive-top">
        <div class="drive-state">${live}<span class="drive-clock" id="dClock"></span></div>
        <div class="eta"><b id="dLeft">–</b><span class="unit" id="dUnit">min left</span><span class="meta" id="dArrive"></span></div>
        <div class="progress"><span id="dProg"></span></div>
        <div class="dest"><span class="badge ${dest.type}">${dest.id}</span><span class="grow"><b>${esc(shortName(dest.name))}</b><span>${esc(d.mission.label)} · ${esc(d.mission.vehicle)}${d.reroutes ? ` · ${d.reroutes} re-route${d.reroutes === 1 ? "" : "s"}` : ""}</span></span></div>
      </div>
      <div class="now-road"><i class="dot" id="dRoadDot"></i><span class="name" id="dRoad">–</span><span class="muted" id="dRoadLoad"></span></div>
    </div>
    <div class="drive-controls">
      ${
        d.arrived
          ? `<button class="primary" id="dEnd" style="grid-column:1/-1">Done</button>`
          : `<button class="secondary" id="dPause">${d.paused ? `<svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>Resume` : `<svg viewBox="0 0 24 24"><path d="M7 5h4v14H7zM13 5h4v14h-4z"/></svg>Pause`}</button>
             <button class="secondary" id="dEnd"><svg viewBox="0 0 24 24"><path d="M6 6h12v12H6z"/></svg>End trip</button>`
      }
    </div>
    ${d.arrived ? "" : speedPicker()}
    ${
      d.arrived
        ? ""
        : `<button class="secondary rain-btn" id="dRain">${ICONS.rain}Rain burst: +${RAIN_BURST_MM} mm/h now</button>
           <div class="alert warn" style="margin-top:-2px">${ICONS.info}<span><b>Report an incident:</b> click any road on the map to mark it blocked. The vehicle re-checks its route every simulated minute and re-routes when a road ahead is blocked or will flood.</span></div>`
    }
    <h3>Trip log</h3>
    <ol class="events">${[...d.events]
      .reverse()
      .map((e) => `<li class="${e.kind}"><time>${minuteTime(e.min)}</time><i class="ev-dot"></i><span>${esc(e.text)}</span></li>`)
      .join("")}</ol>`;
  $("dPause")?.addEventListener("click", togglePause);
  $("dEnd").addEventListener("click", endTrip);
  $("dRain")?.addEventListener("click", rainBurst);
  bindSpeed($("result"));
  updateDriveLive(d);
}

function updateDriveLive(d) {
  if (!$("dClock")) return;
  const elapsedTrip = d.nowMin - d.tripStartMin;
  const left = Math.max(0, d.plan.route.minutes - (d.nowMin - d.routeStartMin));
  $("dClock").textContent = minuteTime(d.nowMin);
  if (d.arrived) {
    $("dLeft").textContent = fmtMin(elapsedTrip);
    $("dUnit").textContent = "min trip";
    $("dArrive").textContent = `arrived ${minuteTime(d.nowMin)}`;
  } else {
    $("dLeft").textContent = left < 1 ? "<1" : Math.ceil(left);
    $("dUnit").textContent = "min left";
    $("dArrive").textContent = `arrive ${minuteTime(d.nowMin + left)}`;
  }
  $("dProg").style.width = `${Math.min(100, (elapsedTrip / (elapsedTrip + left || 1)) * 100)}%`;
  const seg = d.pos ? d.segs[d.pos.k] : d.segs[0];
  const i = roadIndexById.get(seg.road_id);
  const loading = state.loading && i != null ? state.loading[i] : seg.loading;
  $("dRoad").textContent = d.arrived ? `At ${shortName(d.dest.name)}` : seg.name || "Unnamed road";
  $("dRoadDot").style.background = STATUS_COLORS[statusOf(loading)];
  $("dRoadLoad").textContent = `${pct(loading)} loading`;
}

/* =================== Fleet mode =================== */
// Several vehicles dispatched at once. The backend splits them in flood zones
// so no jam-sensitive road carries more vehicles at a time than its zone allows.
const VEHICLE_COLORS = ["#2563eb", "#9333ea", "#0d9488", "#db2777", "#4338ca", "#0891b2", "#92400e", "#334155"];
const MAX_FLEET = 8;
const fleetLayer = L.layerGroup().addTo(map);
let fleetPlanTimer = null;

function fleetVehicles() {
  return state.fleetPlan?.plans?.[state.fleetView] || [];
}

function setPlanMode(mode) {
  const fleet = mode === "fleet";
  if (fleet === state.fleetMode) return;
  stopFleetPlay();
  state.fleetMode = fleet;
  document.body.classList.toggle("fleet-mode", fleet);
  document.querySelectorAll(".mode-switch button").forEach((b) => b.setAttribute("aria-selected", b.dataset.mode === mode));
  $("missionTitle").textContent = fleet ? "Mission for new vehicles" : "Mission";
  if (fleet) {
    routeLayer.clearLayers();
    originMarker?.remove();
    originMarker = null;
    renderFleet();
    scheduleFleet(true);
  } else {
    fleetLayer.clearLayers();
    drawPlan();
    renderStart();
    renderResult();
    restyleRoads();
    renderFacilities();
  }
}

function addVehicle(latlng) {
  if (state.fleet.length >= MAX_FLEET) {
    showToast("Fleet is full", `Up to ${MAX_FLEET} vehicles. Remove one to add another.`);
    return;
  }
  const used = new Set(state.fleet.map((v) => v.id));
  let n = 1;
  while (used.has(`V${n}`)) n++;
  state.fleet.push({ id: `V${n}`, mission: state.mission, origin: [latlng.lng, latlng.lat], color: VEHICLE_COLORS[(n - 1) % VEHICLE_COLORS.length] });
  renderFleet();
  scheduleFleet(true);
}

function scheduleFleet(immediate = false) {
  if (!state.fleetMode || state.fleetPlay) return;
  clearTimeout(fleetPlanTimer);
  if (!state.fleet.length) {
    state.fleetPlan = null;
    renderFleet();
    return;
  }
  fleetPlanTimer = setTimeout(dispatchFleet, immediate ? 0 : 150);
}

async function dispatchFleet() {
  const seq = ++state.fleetSeq;
  state.fleetPlanning = true;
  state.fleetError = null;
  renderFleetResult();
  try {
    const result = await post("/api/fleet/dispatch", {
      vehicles: state.fleet.map((v) => ({ id: v.id, mission: v.mission, origin: v.origin })),
      depart_tick: state.tick,
    });
    if (seq !== state.fleetSeq || !state.fleetMode) return;
    state.fleetPlan = result;
  } catch (e) {
    if (seq !== state.fleetSeq) return;
    state.fleetPlan = null;
    state.fleetError = e.message;
  }
  state.fleetPlanning = false;
  renderFleet();
}

function renderFleet() {
  renderFleetList();
  drawFleet();
  renderFleetResult();
  restyleRoads();
  renderFacilities();
}

function renderFleetList() {
  const list = $("fleetList");
  $("fleetClear").hidden = !state.fleet.length;
  if (!state.fleet.length) {
    list.innerHTML = `<div class="fleet-empty">Click roads on the map to place vehicles (up to ${MAX_FLEET}). Each new vehicle uses the mission selected above. Place several close together to see how they get split up in flood zones.</div>`;
    return;
  }
  const planned = new Map(fleetVehicles().map((v) => [v.id, v]));
  list.innerHTML = `<ul class="fleet-list">${state.fleet
    .map((v) => {
      const p = planned.get(v.id);
      const road = p ? p.origin.road_name || "Unnamed road" : state.fleetPlanning ? "Locating road…" : "Not planned yet";
      return `<li><span class="vnum" style="background:${v.color}">${v.id.slice(1)}</span>
        <span class="name">${esc(road)}<small>${v.id}</small></span>
        <button class="mchip ${v.mission}" data-toggle="${v.id}" title="Switch mission">${v.mission === "medical" ? "Medical" : "Evacuation"}</button>
        <button class="icon-x" data-remove="${v.id}" title="Remove ${v.id}" aria-label="Remove ${v.id}">${ICONS.close}</button></li>`;
    })
    .join("")}</ul>`;
  list.querySelectorAll("[data-toggle]").forEach((b) =>
    b.addEventListener("click", () => {
      const v = state.fleet.find((x) => x.id === b.dataset.toggle);
      v.mission = v.mission === "medical" ? "evacuation" : "medical";
      renderFleetList();
      scheduleFleet(true);
    })
  );
  list.querySelectorAll("[data-remove]").forEach((b) =>
    b.addEventListener("click", () => {
      state.fleet = state.fleet.filter((x) => x.id !== b.dataset.remove);
      renderFleet();
      scheduleFleet(true);
    })
  );
}

function drawFleet() {
  fleetLayer.clearLayers();
  if (!state.fleetMode) return;
  const ll = (c) => [c[1], c[0]];
  const pane = "routePane";
  const planned = new Map(fleetVehicles().map((v) => [v.id, v]));
  for (const v of state.fleet) {
    const p = planned.get(v.id);
    if (!p?.route) continue;
    const lines = p.route.segments.map((s) => s.coords.map(ll));
    L.polyline(lines, { pane, color: "#fff", weight: 9, interactive: false }).addTo(fleetLayer);
    L.polyline(lines, { pane, color: v.color, weight: 5, opacity: 0.95, lineCap: "round" })
      .bindTooltip(`<b>${v.id}</b> → ${p.destination.id} · ${fmtMin(p.route.minutes)} min`, { sticky: true })
      .addTo(fleetLayer);
  }
  const report = state.fleetPlan?.report?.[state.fleetView];
  for (const r of report?.roads || []) {
    const pts = r.coords.map(ll);
    L.polyline(pts, { pane, color: "#fff", weight: 11, interactive: false }).addTo(fleetLayer);
    L.polyline(pts, { pane, color: "#111827", weight: 6, dashArray: "4 6", lineCap: "butt" })
      .bindTooltip(
        `<b>${esc(r.name || "Unnamed road")}</b><br>${r.vehicles.join(", ")} on it within ±${state.fleetPlan.rules.window_min} min` +
          `<br>${r.zone === "red" ? "Red" : "Orange"} zone allows ${r.cap} at a time`,
        { sticky: true }
      )
      .addTo(fleetLayer);
  }
  // During playback the moving markers replace the start pins.
  for (const v of state.fleetPlay ? [] : state.fleet) {
    const p = planned.get(v.id);
    const at = p ? p.origin.snapped : v.origin;
    L.marker([at[1], at[0]], {
      icon: L.divIcon({ html: `<div class="fleet-pin" style="background:${v.color}">${v.id.slice(1)}</div>`, className: "", iconSize: [26, 26], iconAnchor: [13, 13] }),
      zIndexOffset: 2000,
      keyboard: false,
    })
      .bindTooltip(`${v.id} · ${v.mission === "medical" ? "ambulance" : "bus"}`, { direction: "top", offset: [0, -12] })
      .addTo(fleetLayer);
  }
}

function renderFleetResult() {
  if (state.fleetPlay) return renderFleetPlayPanel();
  const el = $("result");
  const head = `<div class="result-head"><h2>Fleet routes</h2>${state.fleetPlanning ? '<span class="spinner"></span>' : ""}</div>`;
  if (!state.fleet.length) {
    el.innerHTML = `${head}<ol class="guide">
      <li>Pick the mission for the next vehicle</li>
      <li>Click several roads to place vehicles, ideally close together</li>
      <li>Move the timeline to hour 5 or later. Vehicles heading through flood zones are split so no road carries more vehicles at a time than its zone allows.</li>
    </ol>`;
    return;
  }
  if (state.fleetError) {
    el.innerHTML = head + alert("danger", esc(state.fleetError));
    return;
  }
  const P = state.fleetPlan;
  if (!P) {
    el.innerHTML = `${head}<div class="skeleton"></div>`;
    return;
  }
  const I = P.report.independent;
  const C = P.report.coordinated;
  const split = P.plans.coordinated.filter((v) => v.changed).length;
  let verdict;
  if (I.overloaded_roads === 0) verdict = `<span class="verdict clear">${ICONS.check}No jam risk: routes only share safe roads</span>`;
  else if (C.overloaded_roads < I.overloaded_roads)
    verdict = `<span class="verdict detour">${ICONS.detour}Split ${split} vehicle${split === 1 ? "" : "s"} to avoid ${I.overloaded_roads - C.overloaded_roads} jam road${I.overloaded_roads - C.overloaded_roads === 1 ? "" : "s"}</span>`;
  else verdict = `<span class="verdict over">${ICONS.alert}Jam unavoidable on ${C.overloaded_roads} road${C.overloaded_roads === 1 ? "" : "s"}</span>`;

  const better = (a, b) => (a < b ? "win" : "");
  const row = (label, c, i, fmt) => `<tr><td>${label}</td><td class="us ${better(c, i)}">${fmt(c)}</td><td class="${better(i, c)}">${fmt(i)}</td></tr>`;
  const minutes = (m) => (m == null ? "–" : `${m.toFixed(1)} min`);
  const view = fleetVehicles();
  const rules = P.rules;

  el.innerHTML =
    head +
    `<div class="hero"><div class="hero-top">${verdict}
      <table class="compare">
        <tr><th></th><th>Coordinated</th><th>Uncoordinated</th></tr>
        ${row("Jam-zone roads over cap", C.overloaded_roads, I.overloaded_roads, (x) => x)}
        ${row("Length over cap", C.overloaded_m, I.overloaded_m, fmtDist)}
        ${row("Estimated jam delay", C.estimated_jam_delay_min, I.estimated_jam_delay_min, minutes)}
        ${row("Average drive", C.mean_minutes, I.mean_minutes, minutes)}
        ${row("Slowest vehicle", C.max_minutes, I.max_minutes, minutes)}
      </table></div>
      <div class="hero-exp"><span class="muted" style="font-size:12px">Orange zone (High hazard, or ≥${pct(rules.orange_loading)} loading) allows ${rules.orange_cap} vehicles at a time; red (Very High, or ≥${pct(rules.red_loading)}) allows ${rules.red_cap}. "At a time" = within ±${rules.window_min} min. Medical vehicles are routed first.</span></div>
    </div>
    <div class="tabs" role="tablist">
      <button role="tab" data-view="coordinated" aria-selected="${state.fleetView === "coordinated"}">Coordinated</button>
      <button role="tab" data-view="independent" aria-selected="${state.fleetView === "independent"}">Uncoordinated</button>
    </div>
    <ul class="fleet-rows">${view
      .map((v) => {
        const color = state.fleet.find((x) => x.id === v.id)?.color;
        const chip =
          v.status !== "ok"
            ? `<span class="chip cut_off">${v.status === "no_safe_route" ? "Over limit" : "No route"}</span>`
            : state.fleetView === "coordinated" && v.changed
              ? `<span class="chip split">Split${v.extra_minutes > 0.05 ? ` +${v.extra_minutes.toFixed(1)} min` : ""}</span>`
              : "";
        return `<li><span class="vnum" style="background:${color}">${v.id.slice(1)}</span>
          ${v.destination ? `<span class="badge sm ${v.destination.type}">${v.destination.id}</span>` : ""}
          <span class="name">${esc(v.destination ? shortName(v.destination.name) : "No destination")}</span>
          ${chip}<span class="num">${v.route ? `${fmtMin(v.route.minutes)} min` : "–"}</span></li>`;
      })
      .join("")}</ul>
    <div class="start-trip"><button class="primary" id="playFleet"><svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>Play fleet</button></div>
    ${speedPicker()}`;
  el.querySelectorAll("[data-view]").forEach((b) =>
    b.addEventListener("click", () => {
      state.fleetView = b.dataset.view;
      renderFleet();
    })
  );
  $("playFleet").addEventListener("click", startFleetPlay);
  bindSpeed(el);
}

/* Fleet playback: every vehicle drives its planned route at once. */
function startFleetPlay() {
  const vehicles = fleetVehicles().filter((v) => v.route);
  if (!vehicles.length) return;
  stopPlaying();
  const startMin = state.tick * stepMin();
  state.fleetPlay = {
    view: state.fleetView,
    startMin,
    nowMin: startMin,
    lastTs: null,
    paused: false,
    finished: false,
    lastPanelTs: 0,
    items: vehicles.map((v) => {
      const color = state.fleet.find((x) => x.id === v.id)?.color || "#334155";
      const segs = prepareRoute(v.route);
      const marker = L.marker(segs[0].pts[0], {
        icon: L.divIcon({ html: `<div class="fleet-pin" style="background:${color};width:30px;height:30px">${v.id.slice(1)}</div>`, className: "", iconSize: [30, 30], iconAnchor: [15, 15] }),
        zIndexOffset: 3000,
        interactive: false,
        keyboard: false,
      }).addTo(map);
      return { v, color, segs, marker, done: false };
    }),
  };
  document.body.classList.add("driving");
  $("timeline").classList.add("locked");
  drawFleet();
  state.fleetPlay.timer = setInterval(fleetFrame, DRIVE_TICK_MS);
  renderFleetPlayPanel();
}

function fleetFrame() {
  const fp = state.fleetPlay;
  if (!fp) return;
  const ts = performance.now();
  if (fp.lastTs != null && !fp.paused && !fp.finished) {
    fp.nowMin += (Math.min((ts - fp.lastTs) / 1000, 0.5) * state.speed) / 60;
  }
  fp.lastTs = ts;
  const elapsed = fp.nowMin - fp.startMin;
  let all = true;
  for (const it of fp.items) {
    const pos = positionAt(it.segs, Math.min(elapsed, it.v.route.minutes));
    if (pos) it.marker.setLatLng(pos.latlng);
    it.done = elapsed >= it.v.route.minutes;
    all &&= it.done;
  }
  $("clockTime").textContent = minuteTime(fp.nowMin);
  $("clockHour").textContent = all ? "Fleet arrived" : "Fleet en route";
  if (all && !fp.finished) {
    fp.finished = true;
    renderFleetPlayPanel();
  } else if (ts - fp.lastPanelTs > 200) {
    fp.lastPanelTs = ts;
    updateFleetLive();
  }
}

function renderFleetPlayPanel() {
  const fp = state.fleetPlay;
  if (!fp) return;
  const live = fp.finished
    ? `<span class="live arrived">All arrived</span>`
    : fp.paused
      ? `<span class="live paused">Paused</span>`
      : `<span class="live">Fleet en route</span>`;
  $("result").innerHTML = `
    <div class="result-head"><h2>Fleet ${fp.view === "coordinated" ? "(coordinated)" : "(uncoordinated)"}</h2></div>
    <div class="drive-card"><div class="drive-top">
      <div class="drive-state">${live}<span class="drive-clock" id="fClock"></span></div>
      <div class="eta"><b id="fDone">0</b><span class="unit">/ ${fp.items.length} arrived</span></div>
      <div class="progress"><span id="fProg"></span></div>
    </div></div>
    <ul class="fleet-rows">${fp.items
      .map(
        (it) => `<li><span class="vnum" style="background:${it.color}">${it.v.id.slice(1)}</span>
          <span class="badge sm ${it.v.destination.type}">${it.v.destination.id}</span>
          <span class="name">${esc(shortName(it.v.destination.name))}</span>
          <span class="num" id="f-${it.v.id}"></span></li>`
      )
      .join("")}</ul>
    <div class="drive-controls">${
      fp.finished
        ? `<button class="primary" id="fStop" style="grid-column:1/-1">Done</button>`
        : `<button class="secondary" id="fPause">${fp.paused ? "Resume" : "Pause"}</button><button class="secondary" id="fStop">Stop</button>`
    }</div>
    ${fp.finished ? "" : speedPicker()}`;
  $("fPause")?.addEventListener("click", () => {
    fp.paused = !fp.paused;
    renderFleetPlayPanel();
  });
  $("fStop").addEventListener("click", stopFleetPlay);
  bindSpeed($("result"));
  updateFleetLive();
}

function updateFleetLive() {
  const fp = state.fleetPlay;
  if (!fp || !$("fClock")) return;
  const elapsed = fp.nowMin - fp.startMin;
  $("fClock").textContent = minuteTime(fp.nowMin);
  $("fDone").textContent = fp.items.filter((it) => it.done).length;
  const longest = Math.max(...fp.items.map((it) => it.v.route.minutes));
  $("fProg").style.width = `${Math.min(100, (elapsed / longest) * 100)}%`;
  for (const it of fp.items) {
    const left = it.v.route.minutes - elapsed;
    $(`f-${it.v.id}`).textContent = left <= 0 ? "Arrived" : `${left < 1 ? "<1" : Math.ceil(left)} min left`;
  }
}

function stopFleetPlay() {
  const fp = state.fleetPlay;
  if (!fp) return;
  clearInterval(fp.timer);
  fp.items.forEach((it) => it.marker.remove());
  state.fleetPlay = null;
  document.body.classList.remove("driving");
  $("timeline").classList.remove("locked");
  renderTimeline();
  renderFleet();
}

/* =================== Scenario & layers =================== */
function showError(message) {
  $("error").hidden = !message;
  $("error").textContent = message || "";
}

async function createSimulation() {
  stopPlaying();
  showError(null);
  const custom = $("custom").value.trim();
  const body = { model: $("model").value };
  if (custom) body.rainfall_mm_per_h = custom.split(/[,\s]+/).filter(Boolean).map(Number);
  else {
    const [kind, name] = $("preset").value.split(":");
    body[kind] = name; // "scenario" (historical) or "preset" (synthetic)
  }
  try {
    state.info = await post("/api/simulation", body);
    state.frames.clear();
    await goToTick(0);
  } catch (e) {
    showError(e.message);
  }
}

/* =================== Boot =================== */
async function init() {
  const [summary, roads, points, models, presets, scenarios, info, missions, facilities] = await Promise.all([
    api("/api/network/summary"),
    api("/api/network/roads"),
    api("/api/network/flood-points"),
    api("/api/simulation/models"),
    api("/api/simulation/presets"),
    api("/api/simulation/scenarios"),
    api("/api/simulation"),
    api("/api/missions"),
    api("/api/facilities"),
  ]);
  state.info = info;
  state.missions = missions;
  state.facilities = facilities;
  state.mission = missions[0].id;

  const region = summary.region[0].toUpperCase() + summary.region.slice(1);
  $("region").textContent = `${region}, Chennai · ${summary.total_length_km} km of roads`;
  $("region").title = `${summary.roads.toLocaleString()} road segments, ${summary.intersections.toLocaleString()} intersections`;
  $("model").innerHTML = models.map((m) => `<option value="${m.name}" title="${esc(m.description)}">${m.name}</option>`).join("");
  const label = (k) => k[0].toUpperCase() + k.slice(1).replaceAll("_", " ");
  const total = (s) => Math.round(s.reduce((a, b) => a + b, 0));
  $("preset").innerHTML =
    `<optgroup label="Historical Velachery rainfall (ERA5)">${Object.entries(scenarios)
      .map(([k, s]) => `<option value="scenario:${k}">${label(k)} · ${s.length} h, ${total(s)} mm total</option>`)
      .join("")}</optgroup>` +
    `<optgroup label="Synthetic storms">${Object.entries(presets)
      .map(([k, s]) => `<option value="preset:${k}">${label(k)} · ${s.length} h, peak ${Math.max(...s)} mm/h</option>`)
      .join("")}</optgroup>`;
  $("preset").value = info.rainfall_source
    .replace("historical_scenario:", "scenario:")
    .replace(/^manual$/, "");

  roadProps = roads.features.map((f) => f.properties);
  roadIndexById = new Map(roadProps.map((p) => [p.id, p.i]));
  roadLayers = new Array(roadProps.length);
  L.geoJSON(roads, {
    style: (f) => ({ weight: ROAD_WEIGHT[f.properties.highway] || 1.4, opacity: 0.85 }),
    interactive: false,
    onEachFeature: (f, layer) => (roadLayers[f.properties.i] = layer),
  }).addTo(map);

  pointsLayer = L.layerGroup(
    points.map((p) =>
      L.circleMarker([p.lat, p.lon], { radius: 3.5, color: "#fff", weight: 1.2, fillColor: "#3b7fd0", fillOpacity: 0.9 })
        .bindTooltip(`Recorded flood: ${p.depth_cm} cm${p.remarks ? ` · ${esc(p.remarks)}` : ""}`)
    )
  );

  const [w, s, e, n] = summary.bbox;
  map.fitBounds([[s, w], [n, e]], { paddingTopLeft: [0, 60], paddingBottomRight: [0, 110] });

  renderMissions();
  renderFacilitySelect();
  renderStart();
  renderResult();
  await goToTick(info.tick);
  $("loading").classList.add("hidden");

  map.on("click", (ev) => {
    if (state.drive) reportIncident(ev.latlng);
    else if (state.fleetPlay) return;
    else if (state.fleetMode) addVehicle(ev.latlng);
    else setOrigin(ev.latlng);
  });
  document.querySelectorAll(".mode-switch button").forEach((b) => b.addEventListener("click", () => setPlanMode(b.dataset.mode)));
  $("fleetClear").addEventListener("click", () => {
    state.fleet = [];
    state.fleetPlan = null;
    renderFleet();
  });
  document.querySelectorAll("input[name=mode]").forEach((el) =>
    el.addEventListener("change", () => {
      setMode(el.value);
      // Hazard view also shows the historical flood points it is based on.
      if (el.value === "static") pointsLayer.addTo(map);
      else pointsLayer.remove();
    })
  );
  $("facility").addEventListener("change", (ev) => {
    state.facilityId = ev.target.value;
    renderFacilities();
    schedulePlan(true);
  });
  $("create").addEventListener("click", createSimulation);
  $("play").addEventListener("click", togglePlay);
  $("step").addEventListener("click", () => {
    stopPlaying();
    setMode("sim");
    goToTick(state.tick + 1);
  });
  $("reset").addEventListener("click", async () => {
    stopPlaying();
    state.info = await post("/api/simulation/reset");
    state.frames.clear();
    goToTick(0);
  });
  let scrub = null;
  $("slider").addEventListener("input", (ev) => {
    stopPlaying();
    clearTimeout(scrub);
    scrub = setTimeout(() => goToTick(Number(ev.target.value)), 60);
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && state.origin && !state.drive) clearOrigin();
    if (ev.key === " " && state.drive && ev.target === document.body) {
      ev.preventDefault();
      togglePause();
    }
  });
  window.addEventListener("resize", () => state.info && renderChart());
}

init().catch((e) => {
  $("loading").innerHTML = `<span style="color:var(--danger-text)">Failed to load: ${esc(e.message)}</span>`;
});
