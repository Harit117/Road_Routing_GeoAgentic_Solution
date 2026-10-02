"""Runtime settings. Override any value with an environment variable, e.g.
FLOOD_DATA_DIR=/path/to/processed uvicorn app.main:app
"""

import os
from dataclasses import dataclass
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent


@dataclass(frozen=True)
class Settings:
    # Folder produced by girlgeeks/scripts (Member 1's data layer).
    data_dir: Path
    # Prefix of the road files inside data_dir: <region>_roads.geojson etc.
    # Switching to all of Chennai = regenerate data with region "chennai".
    region: str
    # Length of one simulation tick. Open-Meteo rainfall is hourly.
    step_minutes: int


def load_settings() -> Settings:
    return Settings(
        data_dir=Path(
            os.environ.get(
                "FLOOD_DATA_DIR", REPO_ROOT / "girlgeeks" / "data" / "processed"
            )
        ),
        region=os.environ.get("FLOOD_REGION", "velachery"),
        step_minutes=int(os.environ.get("FLOOD_STEP_MINUTES", "60")),
    )
