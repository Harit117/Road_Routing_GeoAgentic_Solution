"""Export hourly relative road-risk states for the four historical scenarios.

This is a normalized prototype model. Its bucket values are not water depths
and its configurable parameters are not calibrated physical constants.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import load_settings  # noqa: E402
from app.flood.config import RiskModelConfig  # noqa: E402
from app.flood.rainfall_provider import SCENARIO_NAMES  # noqa: E402
from app.flood.risk_engine import RiskEngine  # noqa: E402
from app.network.loader import load_network  # noqa: E402


OUTPUT_FILE = REPO_ROOT / "girlgeeks" / "data" / "processed" / "road_flood_risk_scenarios.csv"


def main() -> None:
    settings = load_settings()
    network = load_network(settings)
    engine = RiskEngine(
        network.roads,
        settings.data_dir,
        RiskModelConfig.from_environment(),
    )
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "road_id",
        "scenario",
        "susceptibility",
        "threshold",
        "hour",
        "rainfall_mm",
        "flood_loading",
        "risk_score",
        "risk_level",
        "threshold_reached",
        "time_to_threshold_hours",
    ]
    rows_written = 0
    with OUTPUT_FILE.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for scenario in SCENARIO_NAMES:
            frame = engine.simulate_scenario(scenario)
            for state in frame.states:
                writer.writerow(
                    {
                        "road_id": state.road_id,
                        "scenario": scenario,
                        "susceptibility": f"{state.susceptibility:.6f}",
                        "threshold": f"{state.threshold:.6f}",
                        "hour": f"{frame.elapsed_hours:g}",
                        "rainfall_mm": f"{state.rainfall_mm:.2f}",
                        "flood_loading": f"{state.current_flood_loading:.6f}",
                        "risk_score": f"{state.risk_score:.6f}",
                        "risk_level": state.risk_level,
                        "threshold_reached": str(state.threshold_reached).lower(),
                        "time_to_threshold_hours": (
                            ""
                            if state.time_to_threshold_hours is None
                            else f"{state.time_to_threshold_hours:g}"
                        ),
                    }
                )
                rows_written += 1
    print(f"Wrote {rows_written:,} final road-risk rows to {OUTPUT_FILE}")
    print(f"Roads: {len(network.roads):,}; scenarios: {', '.join(SCENARIO_NAMES)}")


if __name__ == "__main__":
    main()
