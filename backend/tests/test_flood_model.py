from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.flood.bucket_model import BucketModel
from app.flood.config import RiskModelConfig
from app.flood.models import RainfallStep, SusceptibilityEvidence
from app.flood.rainfall_provider import HistoricalScenarioRainfallProvider
from app.flood.risk_engine import RiskEngine
from app.flood.susceptibility import SusceptibilityCalculator


PROCESSED_DIR = (
    Path(__file__).resolve().parents[2]
    / "girlgeeks"
    / "data"
    / "processed"
)


def test_susceptibility_uses_depth_and_hazard_evidence():
    calculator = SusceptibilityCalculator(RiskModelConfig())
    result = calculator.calculate(
        [
            SusceptibilityEvidence("none", None, 0),
            SusceptibilityEvidence("middle", 5.0, 2),
            SusceptibilityEvidence("high", 10.0, 5),
        ]
    )
    assert result["none"] == 0
    assert result["middle"] == pytest.approx(0.46)
    assert result["high"] == 1


def test_zero_rainfall_does_not_increase_bucket():
    model = BucketModel(RiskModelConfig())
    assert model.advance(0.2, 0.0, 0.5) == pytest.approx(0.2)


def test_rainfall_and_susceptibility_increase_loading():
    model = BucketModel(RiskModelConfig())
    dry = model.advance(0.0, 0.0, 0.8)
    low = model.advance(0.0, 10.0, 0.2)
    high = model.advance(0.0, 10.0, 0.8)
    assert dry == 0
    assert high > low > dry


def _engine(roads, config=None):
    return RiskEngine(roads, PROCESSED_DIR, config)


def _road(road_id, flood_depth_cm, hazard_rank=0):
    return SimpleNamespace(
        road_id=road_id,
        flood_depth_cm=flood_depth_cm,
        hazard_rank=hazard_rank,
    )


def test_higher_susceptibility_crosses_earlier_under_same_rain():
    engine = _engine(
        [_road("lower", 5.0), _road("higher", 10.0)],
        RiskModelConfig(depth_weight=1.0, hazard_weight=0.0),
    )
    steps = [
        RainfallStep(datetime(2020, 1, 1) + timedelta(hours=i + 1), 40.2)
        for i in range(3)
    ]
    frames = list(engine.iter_series(steps, source="test"))
    first = {state.road_id: state for state in frames[1].states}
    final = {state.road_id: state for state in frames[-1].states}
    assert first["higher"].current_flood_loading > first["lower"].current_flood_loading
    assert final["higher"].time_to_threshold_hours <= final["lower"].time_to_threshold_hours


def test_risk_clamps_and_records_first_threshold_crossing():
    engine = _engine(
        [_road("mid", 5.0), _road("max", 10.0)],
        RiskModelConfig(depth_weight=1.0, hazard_weight=0.0),
    )
    steps = [RainfallStep(datetime(2020, 1, 1) + timedelta(hours=i + 1), 500.0) for i in range(2)]
    frame = list(engine.iter_series(steps, source="test"))[-1]
    states = {state.road_id: state for state in frame.states}
    assert all(0 <= state.risk_score <= 1 for state in states.values())
    assert states["mid"].time_to_threshold_hours == 1
    assert states["mid"].risk_level == "CRITICAL"


def test_unreached_threshold_has_null_time():
    engine = _engine(
        [_road("low", 5.0), _road("high", 10.0)],
        RiskModelConfig(depth_weight=1.0, hazard_weight=0.0),
    )
    frame = list(
        engine.iter_series(
            [RainfallStep(datetime(2020, 1, 1, 1), 0.1)], source="test"
        )
    )[-1]
    state = next(state for state in frame.states if state.road_id == "low")
    assert state.time_to_threshold_hours is None
    assert not state.threshold_reached


def test_zero_threshold_is_critical_without_division_by_zero():
    engine = _engine(
        [_road("max", 10.0)],
        RiskModelConfig(depth_weight=1.0, hazard_weight=0.0),
    )
    initial = next(engine.iter_series([], source="test")).states[0]
    assert initial.threshold == 0
    assert initial.risk_score == 1
    assert initial.risk_level == "CRITICAL"
    assert initial.time_to_threshold_hours == 0


def test_all_historical_rainfall_scenarios_load_as_48_hour_series():
    provider = HistoricalScenarioRainfallProvider(PROCESSED_DIR)
    assert provider.scenario_names == ("normal", "moderate", "heavy", "extreme")
    assert all(len(provider.get_scenario(name)) == 48 for name in provider.scenario_names)


def test_simulation_default_model_uses_flood_risk_rules():
    """The map/routing simulation and /api/flood-risk share the same road rules."""
    from fastapi.testclient import TestClient

    from app.main import app
    from app.simulation.flood_models import DEFAULT_MODEL

    assert DEFAULT_MODEL == "susceptibility_bucket"
    with TestClient(app) as client:
        client.post("/api/simulation", json={"scenario": "extreme"})
        info = client.post("/api/simulation/run").json()
        assert info["model"] == "susceptibility_bucket"
        loading = client.get(f"/api/simulation/frames/{info['tick']}").json()["loading"]
        roads = client.get("/api/network/roads").json()["features"]
        road_id = roads[0]["properties"]["id"]
        risk = client.get(f"/api/flood-risk/roads/{road_id}", params={"scenario": "extreme"}).json()
        # Frames are stored to 4 decimals.
        assert min(loading[0], 1.0) == pytest.approx(risk["risk_score"], abs=1e-4)
        assert len(client.get("/api/simulation/scenarios").json()["heavy"]) == 48
