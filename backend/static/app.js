"use strict";

const HAZARD_COLORS = {
  "Very High": "#7f0000",
  "High": "#d7301f",
  "Moderate": "#f08a4b",
  "Low": "#fdb863",
  "Very Low": "#fde3a7",
  "None": "#b8bcc4",
};
const STATUS_COLORS = {
  safe: "#4c9a5f",
  watch: "#e8b730",
  risky: "#e06c2a",
  flooded: "#b3122e",
};
const ROAD_WEIGHT = { primary: 4, primary_link: 3, secondary: 3.5, tertiary: 3 };

const $ = (id) => document.getElementById(id);
const state = {
  mode: "static",
  info: null, // SimulationInfo
  tick: 0,
  loading: null, // loading array of the displayed tick
  frames: new Map(), // tick -> loading
  playing: null,
};

const map = L.map("map", { preferCanvas: true });
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  attribution: "&copy; OpenStreetMap contributors",
  maxZoom: 19,
  className: "basemap",
}).addTo(map);

let roadLayers = []; // index -> Leaflet polyline
let roadProps = [];
let zonesLayer = null;
let pointsLayer = null;

async function api(path, options) {
  const res = await fetch(path, options);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail));
  return body;
}
const post = (path, body) =>
  api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });

function statusOf(v) {
  const bands = state.info.status_bands;
  let label = "safe";
  for (const [name, lower] of Object.entries(bands)) if (v >= lower) label = name;
  return label;
}

function roadColor(i) {
  if (state.mode === "sim" && state.loading) return STATUS_COLORS[statusOf(state.loading[i])];
  return HAZARD_COLORS[roadProps[i].hazard || "None"];
}

function restyle() {
  for (let i = 0; i < roadLayers.length; i++) roadLayers[i].setStyle({ color: roadColor(i) });
  renderLegend();
}

function renderLegend() {
  const entries = state.mode === "sim" ? Object.entries(STATUS_COLORS) : Object.entries(HAZARD_COLORS);
  $("legendTitle").textContent = state.mode === "sim" ? "Bucket loading" : "Hazard category";
  const bands = state.info?.status_bands || {};
  $("legend").innerHTML =
    entries
      .map(([k, c]) => {
        const label = state.mode === "sim" && k in bands ? `${k} (≥ ${Math.round(bands[k] * 100)}%)` : k;
        return `<li><span class="swatch" style="background:${c}"></span>${label}</li>`;
      })
      .join("") + `<li><span class="dot"></span>Recorded flood point</li>`;
}

function renderChart() {
  const svg = $("rainChart");
  const rain = state.info.rainfall_mm_per_h;
  const max = Math.max(10, ...rain);
  const w = 300 / rain.length;
  svg.innerHTML =
    rain
      .map((r, k) => {
        // Bar k is the rain that falls during tick k -> k+1.
        const h = (r / max) * 76;
        const cls = k + 1 === state.tick ? "bar now" : k < state.tick ? "bar done" : "bar";
        return `<rect class="${cls}" x="${k * w + 1}" y="${86 - h}" width="${Math.max(w - 2, 1)}" height="${h}"><title>${r} mm/h</title></rect>`;
      })
      .join("") + `<text x="4" y="10">${max} mm/h</text>`;
}

function renderStatus() {
  const info = state.info;
  const frame = info.frames[state.tick];
  const time = new Date(frame.time).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
  $("clock").textContent =
    `Tick ${state.tick}/${info.total_ticks} · ${time} · ${frame.rainfall_mm_per_h} mm/h · ` +
    `${frame.cumulative_rain_mm} mm total`;
  $("counts").innerHTML = Object.entries(frame.status_counts)
    .map(([k, n]) => `<dt><span class="swatch" style="background:${STATUS_COLORS[k]}"></span>${k}</dt><dd>${n.toLocaleString()} roads</dd>`)
    .join("");
  const slider = $("slider");
  slider.max = info.frames.length - 1;
  slider.value = state.tick;
  $("step").disabled = $("run").disabled = info.finished;
  renderChart();
}

async function showTick(tick) {
  if (!state.frames.has(tick)) {
    const f = await api(`/api/simulation/frames/${tick}`);
    state.frames.set(tick, f.loading);
  }
  state.tick = tick;
  state.loading = state.frames.get(tick);
  renderStatus();
  restyle();
}

function setMode(mode) {
  state.mode = mode;
  document.querySelector(`input[name=mode][value=${mode}]`).checked = true;
  restyle();
}

function showError(message) {
  $("error").hidden = !message;
  $("error").textContent = message || "";
}

async function adopt(info, tick) {
  state.info = info;
  await showTick(tick ?? info.frames.length - 1);
}

async function createSimulation() {
  stopPlaying();
  showError(null);
  const custom = $("custom").value.trim();
  const body = { model: $("model").value };
  if (custom) body.rainfall_mm_per_h = custom.split(/[,\s]+/).filter(Boolean).map(Number);
  else body.preset = $("preset").value;
  try {
    state.frames.clear();
    await adopt(await post("/api/simulation", body), 0);
  } catch (e) {
    showError(e.message);
  }
}

async function stepOnce() {
  if (state.tick < state.info.frames.length - 1) return showTick(state.tick + 1);
  if (state.info.finished) return false;
  await adopt(await post("/api/simulation/step"));
  return true;
}

function stopPlaying() {
  clearInterval(state.playing);
  state.playing = null;
  $("play").textContent = "Play";
}

function togglePlay() {
  if (state.playing) return stopPlaying();
  setMode("sim");
  $("play").textContent = "Pause";
  let busy = false;
  state.playing = setInterval(async () => {
    if (busy) return;
    busy = true;
    const atEnd = state.info.finished && state.tick === state.info.frames.length - 1;
    if (atEnd) stopPlaying();
    else await stepOnce();
    busy = false;
  }, 700);
}

async function openRoadPopup(i, latlng) {
  const p = roadProps[i];
  const d = await api(`/api/network/roads/${encodeURIComponent(p.id)}`);
  const loading = state.loading ? state.loading[i] : 0;
  const row = (k, v) => `<tr><td>${k}</td><td><b>${v ?? "—"}</b></td></tr>`;
  L.popup()
    .setLatLng(latlng)
    .setContent(
      `<b>${d.name || "Unnamed road"}</b><table>` +
        row("Type", d.highway) +
        row("Length", `${Math.round(d.length_m)} m`) +
        row("Hazard", d.hazard_category) +
        row("Recorded depth", d.flood_depth_cm != null ? `${d.flood_depth_cm} cm` : null) +
        row(`Loading @ tick ${state.tick}`, `${Math.round(loading * 100)}% (${statusOf(loading)})`) +
        row("Threshold reached", d.onset_tick != null ? `tick ${d.onset_tick}` : "not yet") +
        `</table><small>${d.road_id}</small>`
    )
    .openOn(map);
}

async function toggleZones(on) {
  if (on && !zonesLayer) {
    const zones = await api("/api/network/hazard-zones");
    zonesLayer = L.geoJSON(zones, {
      style: (f) => ({
        color: HAZARD_COLORS[f.properties.hazard_category] || "#999",
        weight: 0.5,
        fillOpacity: 0.25,
      }),
      interactive: false,
    });
  }
  if (on) zonesLayer.addTo(map).bringToBack();
  else if (zonesLayer) zonesLayer.remove();
}

async function init() {
  const [summary, roads, points, models, presets, info] = await Promise.all([
    api("/api/network/summary"),
    api("/api/network/roads"),
    api("/api/network/flood-points"),
    api("/api/simulation/models"),
    api("/api/simulation/presets"),
    api("/api/simulation"),
  ]);

  $("region").textContent =
    `${summary.region[0].toUpperCase() + summary.region.slice(1)} · ${summary.roads.toLocaleString()} road segments · ` +
    `${summary.intersections.toLocaleString()} intersections · ${summary.total_length_km} km`;

  $("model").innerHTML = models.map((m) => `<option value="${m.name}" title="${m.description}">${m.name}</option>`).join("");
  $("preset").innerHTML = Object.entries(presets)
    .map(([k, v]) => `<option value="${k}">${k.replaceAll("_", " ")} (${v.length} h)</option>`)
    .join("");

  roadProps = roads.features.map((f) => f.properties);
  roadLayers = new Array(roadProps.length);
  L.geoJSON(roads, {
    style: (f) => ({ weight: ROAD_WEIGHT[f.properties.highway] || 2, opacity: 0.9 }),
    onEachFeature: (f, layer) => {
      roadLayers[f.properties.i] = layer;
      layer.on("click", (e) => openRoadPopup(f.properties.i, e.latlng));
    },
  }).addTo(map);

  pointsLayer = L.layerGroup(
    points.map((p) =>
      L.circleMarker([p.lat, p.lon], { radius: 5, color: "#fff", weight: 2, fillColor: "#3b82c4", fillOpacity: 1 })
        .bindTooltip(`Recorded flood: ${p.depth_cm} cm${p.remarks ? ` — ${p.remarks}` : ""}`)
    )
  ).addTo(map);

  const [w, s, e, n] = summary.bbox;
  map.fitBounds([[s, w], [n, e]]);

  $("preset").value = info.rainfall_source.replace("preset:", "");
  await adopt(info, 0);

  document.querySelectorAll("input[name=mode]").forEach((el) => el.addEventListener("change", () => setMode(el.value)));
  $("showZones").addEventListener("change", (e) => toggleZones(e.target.checked));
  $("showPoints").addEventListener("change", (e) => (e.target.checked ? pointsLayer.addTo(map) : pointsLayer.remove()));
  $("create").addEventListener("click", createSimulation);
  $("step").addEventListener("click", () => { setMode("sim"); stepOnce(); });
  $("play").addEventListener("click", togglePlay);
  $("run").addEventListener("click", async () => {
    stopPlaying();
    setMode("sim");
    await adopt(await post("/api/simulation/run"));
  });
  $("reset").addEventListener("click", async () => {
    stopPlaying();
    state.frames.clear();
    await adopt(await post("/api/simulation/reset"), 0);
  });
  $("slider").addEventListener("input", (e) => showTick(Number(e.target.value)));
}

init().catch((e) => showError(`Failed to load: ${e.message}`));
