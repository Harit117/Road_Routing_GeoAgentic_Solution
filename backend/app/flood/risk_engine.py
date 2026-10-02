"""Numerical progression engine for relative road flood-risk states."""

from collections.abc import Iterable, Iterator
from datetime import datetime, timedelta

from app.flood.bucket_model import BucketModel
from app.flood.config import RiskModelConfig
from app.flood.models import (
    RainfallStep,
    RiskFrame,
    RiskLevel,
    RoadRiskState,
    SusceptibilityEvidence,
)
from app.flood.rainfall_provider import HistoricalScenarioRainfallProvider
from app.flood.susceptibility import SusceptibilityCalculator
from app.network.models import Road


class RiskEngine:
    """Combine cached road susceptibility with any replaceable rainfall series."""

    def __init__(
        self,
        roads: Iterable[Road],
        processed_dir,
        config: RiskModelConfig | None = None,
    ):
        self.config = config or RiskModelConfig()
        self.roads = list(roads)
        self.road_by_id = {road.road_id: road for road in self.roads}
        evidence = [
            # The network loader joins these values once from the historical
            # road_flood_point_links and road_hazard_links tables.
            SusceptibilityEvidence(
                road.road_id, road.flood_depth_cm, road.hazard_rank
            )
            for road in self.roads
        ]
        self.susceptibility = SusceptibilityCalculator(self.config).calculate(evidence)
        self.bucket_model = BucketModel(self.config)
        self.rainfall_provider = HistoricalScenarioRainfallProvider(processed_dir)

    def scenario_steps(self, scenario: str) -> list[RainfallStep]:
        return self.rainfall_provider.get_scenario(scenario)

    def iter_series(
        self,
        steps: Iterable[RainfallStep],
        *,
        source: str,
        scenario: str | None = None,
        road_ids: Iterable[str] | None = None,
        start_time: datetime | None = None,
    ) -> Iterator[RiskFrame]:
        """Yield a frame for the initial bucket state and each rainfall hour."""
        ordered_steps = list(steps)
        if road_ids is None:
            roads = self.roads
        else:
            requested = set(road_ids)
            roads = [road for road in self.roads if road.road_id in requested]
        if not roads:
            return

        susceptibilities = [self.susceptibility[road.road_id] for road in roads]
        thresholds = [
            self.config.b_max * (1.0 - susceptibility)
            for susceptibility in susceptibilities
        ]
        loadings = [0.0] * len(roads)
        crossing_times = [0.0 if threshold == 0 else None for threshold in thresholds]
        cumulative_rain = 0.0
        elapsed_hours = 0.0
        if start_time is None:
            if ordered_steps:
                start_time = ordered_steps[0].time - timedelta(
                    hours=ordered_steps[0].duration_hours
                )
            else:
                start_time = datetime.now()
        yield self._frame(
            roads,
            susceptibilities,
            thresholds,
            loadings,
            crossing_times,
            scenario,
            source,
            0.0,
            0.0,
            cumulative_rain,
            start_time,
        )

        for step in ordered_steps:
            if step.rainfall_mm < 0:
                raise ValueError("rainfall cannot be negative")
            elapsed_hours += step.duration_hours
            cumulative_rain += step.rainfall_mm
            for index, susceptibility in enumerate(susceptibilities):
                loadings[index] = self.bucket_model.advance(
                    loadings[index],
                    step.rainfall_mm,
                    susceptibility,
                )
                if (
                    crossing_times[index] is None
                    and loadings[index] >= thresholds[index]
                ):
                    crossing_times[index] = elapsed_hours
            yield self._frame(
                roads,
                susceptibilities,
                thresholds,
                loadings,
                crossing_times,
                scenario,
                source,
                elapsed_hours,
                step.rainfall_mm / step.duration_hours if step.duration_hours else 0.0,
                cumulative_rain,
                step.time,
            )

    def simulate_scenario(
        self, scenario: str, road_ids: Iterable[str] | None = None
    ) -> RiskFrame:
        steps = self.scenario_steps(scenario)
        final = None
        for final in self.iter_series(
            steps,
            source=f"historical_scenario:{scenario}",
            scenario=scenario,
            road_ids=road_ids,
        ):
            pass
        if final is None:
            raise ValueError("cannot simulate without roads")
        return final

    def _frame(
        self,
        roads: list[Road],
        susceptibilities: list[float],
        thresholds: list[float],
        loadings: list[float],
        crossing_times: list[float | None],
        scenario: str | None,
        source: str,
        elapsed_hours: float,
        rainfall_mm_per_hour: float,
        cumulative_rain_mm: float,
        observed_at: datetime,
    ) -> RiskFrame:
        states = []
        for index, road in enumerate(roads):
            threshold = thresholds[index]
            loading = loadings[index]
            reached = loading >= threshold
            score = 1.0 if threshold <= 0 else min(1.0, loading / threshold)
            level = self._risk_level(score, reached)
            states.append(
                RoadRiskState(
                    road_id=road.road_id,
                    scenario=scenario,
                    susceptibility=susceptibilities[index],
                    threshold=threshold,
                    current_flood_loading=loading,
                    risk_score=score,
                    risk_level=level,
                    threshold_reached=reached,
                    time_to_threshold_hours=crossing_times[index],
                    elapsed_hours=elapsed_hours,
                    rainfall_mm=rainfall_mm_per_hour,
                    cumulative_rain_mm=cumulative_rain_mm,
                    observed_at=observed_at,
                    source=source,
                )
            )
        return RiskFrame(
            elapsed_hours=elapsed_hours,
            rainfall_mm=rainfall_mm_per_hour,
            cumulative_rain_mm=cumulative_rain_mm,
            observed_at=observed_at,
            states=states,
        )

    def _risk_level(self, score: float, reached: bool) -> RiskLevel:
        if reached:
            return "CRITICAL"
        if score >= self.config.high_risk_max:
            return "VERY_HIGH"
        if score >= self.config.moderate_risk_max:
            return "HIGH"
        if score >= self.config.low_risk_max:
            return "MODERATE"
        return "LOW"
