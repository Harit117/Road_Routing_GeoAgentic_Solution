"""FastAPI entry point: uvicorn app.main:app --reload (run from backend/)."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api import flood_risk, network, routing, simulation
from app.api.schemas import CreateSimulation
from app.config import BACKEND_ROOT, load_settings
from app.flood.config import RiskModelConfig
from app.flood.risk_engine import RiskEngine
from app.network.loader import load_network
from app.routing.facilities import load_facilities
from app.routing.graph import RoutingGraph
from app.routing.planner import Planner


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.settings = load_settings()
    app.state.network = load_network(app.state.settings)
    app.state.planner = Planner(
        RoutingGraph(app.state.network),
        load_facilities(app.state.settings.facilities_file, app.state.network),
    )
    app.state.risk_engine = RiskEngine(
        app.state.network.roads,
        app.state.settings.data_dir,
        RiskModelConfig.from_environment(),
    )
    # Start with a demo storm so the map has something to show.
    app.state.simulation = simulation.build_simulation(
        app, CreateSimulation(preset="intensifying_storm")
    )
    yield


app = FastAPI(title="Flood-aware emergency routing", version="0.1.0", lifespan=lifespan)
app.include_router(network.router)
app.include_router(simulation.router)
app.include_router(flood_risk.router)
app.include_router(routing.router)
app.mount("/map", StaticFiles(directory=BACKEND_ROOT / "static", html=True), name="map")


@app.get("/", include_in_schema=False)
def index():
    return RedirectResponse("/map/")


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "flood-aware-emergency-routing"}


@app.get("/health")
def root_health():
    return health()
