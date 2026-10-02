"""Build historical rainfall forcing scenarios from the Velachery ERA5 series.

The selected events are representative historical rolling-24-hour rainfall
peaks. They are inputs to the flood-risk model, not flood-depth predictions.
"""

from __future__ import annotations

import csv
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
SOURCE_FILE = (
    PROCESSED_DIR
    / "velachery_era5_hourly_rain_2011-10-01_to_2026-09-30.csv"
)
SCENARIOS_FILE = PROCESSED_DIR / "rainfall_scenarios.csv"
METADATA_FILE = PROCESSED_DIR / "rainfall_scenario_metadata.csv"
WINDOW_HOURS = 24
SEQUENCE_BEFORE = 24
SEQUENCE_AFTER = 23
DECLUSTER_HOURS = 7 * 24
TARGETS = (
    ("normal", 75, 0.75),
    ("moderate", 90, 0.90),
    ("heavy", 95, 0.95),
    ("extreme", 99, 0.99),
)


@dataclass(frozen=True)
class Observation:
    time: datetime
    rain_mm: float


@dataclass(frozen=True)
class Peak:
    index: int
    time: datetime
    rain_24h_mm: float


def load_observations(path: Path) -> list[Observation]:
    """Read hourly data after the location metadata and table header."""
    observations: list[Observation] = []
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        rows = csv.reader(source)
        for row in rows:
            if len(row) >= 2 and row[0].strip().lower() == "time":
                if "rain" not in row[1].strip().lower():
                    continue
                break
        else:
            raise ValueError(f"Could not find the time/rainfall header in {path}")

        for line_number, row in enumerate(rows, start=1):
            if not row or not row[0].strip():
                continue
            if len(row) < 2:
                raise ValueError(f"Malformed rainfall row after header: {row!r}")
            time = datetime.fromisoformat(row[0].strip())
            rain = float(row[1].strip())
            if rain < 0:
                raise ValueError(f"Negative rainfall at {time}: {rain}")
            observations.append(Observation(time, rain))

    if len(observations) < WINDOW_HOURS:
        raise ValueError("The rainfall series has fewer than 24 observations")
    if any(a.time >= b.time for a, b in zip(observations, observations[1:])):
        raise ValueError("Rainfall timestamps must be strictly increasing")
    return observations


def rolling_24h(observations: list[Observation]) -> list[int | None]:
    """Return trailing 24-hour sums only for complete, contiguous hours."""
    totals: list[int | None] = [None] * len(observations)
    window: deque[int] = deque()
    running_total = 0
    for index, observation in enumerate(observations):
        if index and observation.time - observations[index - 1].time != timedelta(hours=1):
            window.clear()
            running_total = 0.0
        # The source CSV records rain to 0.01 mm; integer hundredths avoid
        # floating-point noise that could turn a flat peak into false maxima.
        rain_hundredths = round(observation.rain_mm * 100)
        window.append(rain_hundredths)
        running_total += rain_hundredths
        if len(window) > WINDOW_HOURS:
            running_total -= window.popleft()
        if len(window) == WINDOW_HOURS:
            totals[index] = running_total
    return totals


def quantile(values: list[float], probability: float) -> float:
    """Linear-interpolated sample quantile (the common pandas default)."""
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def local_maxima(
    observations: list[Observation], totals: list[int | None]
) -> list[Peak]:
    """Find maxima, representing a flat maximum by its earliest hour."""
    peaks: list[Peak] = []
    index = 0
    while index < len(totals):
        value = totals[index]
        if value is None:
            index += 1
            continue

        end = index
        while end + 1 < len(totals) and totals[end + 1] == value:
            end += 1
        previous = totals[index - 1] if index else None
        following = totals[end + 1] if end + 1 < len(totals) else None
        if (
            (previous is None or value > previous)
            and (following is None or value > following)
        ):
            peaks.append(Peak(index, observations[index].time, value / 100))
        index = end + 1
    return peaks


def decluster(peaks: list[Peak]) -> list[Peak]:
    """Keep the largest maximum within each seven-day event neighborhood."""
    chosen: list[Peak] = []
    for peak in sorted(peaks, key=lambda item: (-item.rain_24h_mm, item.time)):
        if all(
            abs((peak.time - accepted.time).total_seconds())
            >= DECLUSTER_HOURS * 3600
            for accepted in chosen
        ):
            chosen.append(peak)
    return sorted(chosen, key=lambda item: item.time)


def write_outputs(
    observations: list[Observation], totals: list[int | None], peaks: list[Peak]
) -> None:
    valid_totals = [value / 100 for value in totals if value is not None]
    if not valid_totals:
        raise ValueError("No complete rolling 24-hour rainfall totals were found")

    thresholds = {
        percentile: quantile(valid_totals, probability)
        for _, percentile, probability in TARGETS
    }
    metadata_rows: list[dict[str, object]] = []
    scenario_rows: list[dict[str, object]] = []
    selected: list[Peak] = []

    for scenario, percentile, probability in TARGETS:
        threshold = thresholds[percentile]
        eligible = [
            peak
            for peak in peaks
            if all(
                abs((peak.time - other.time).total_seconds())
                >= DECLUSTER_HOURS * 3600
                for other in selected
            )
        ]
        if not eligible:
            raise ValueError(f"No declustered event remains for {scenario}")
        peak = min(
            eligible,
            key=lambda item: (
                abs(item.rain_24h_mm - threshold),
                item.time,
            ),
        )
        selected.append(peak)

        start = peak.index - SEQUENCE_BEFORE
        stop = peak.index + SEQUENCE_AFTER + 1
        if start < 0 or stop > len(observations):
            raise ValueError(f"48-hour sequence for {scenario} exceeds source bounds")
        sequence = observations[start:stop]
        if len(sequence) != 48 or any(
            b.time - a.time != timedelta(hours=1)
            for a, b in zip(sequence, sequence[1:])
        ):
            raise ValueError(f"48-hour sequence for {scenario} is incomplete")
        for offset, observation in enumerate(sequence, start=-SEQUENCE_BEFORE):
            rolling_hundredths = totals[start + offset + SEQUENCE_BEFORE]
            if rolling_hundredths is None:
                raise ValueError(
                    f"Missing rolling 24-hour value at {observation.time}"
                )
            scenario_rows.append(
                {
                    "scenario": scenario,
                    "target_percentile": f"P{percentile}",
                    "target_quantile": f"{probability:.2f}",
                    "selected_peak_time": peak.time.isoformat(sep=" "),
                    "hours_from_peak": offset,
                    "time": observation.time.isoformat(sep=" "),
                    "rain_mm": f"{observation.rain_mm:.2f}",
                    "rain_24h_mm": f"{rolling_hundredths / 100:.3f}",
                    "peak_24h_rain_mm": f"{peak.rain_24h_mm:.3f}",
                }
            )
        metadata_rows.append(
            {
                "scenario": scenario,
                "target_percentile": f"P{percentile}",
                "target_quantile": f"{probability:.2f}",
                "threshold_24h_rain_mm": f"{threshold:.3f}",
                "selected_peak_time": peak.time.isoformat(sep=" "),
                "peak_24h_rain_mm": f"{peak.rain_24h_mm:.3f}",
                "difference_from_threshold_mm": f"{peak.rain_24h_mm - threshold:.3f}",
            }
        )

    with SCENARIOS_FILE.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "scenario",
                "target_percentile",
                "target_quantile",
                "selected_peak_time",
                "hours_from_peak",
                "time",
                "rain_mm",
                "rain_24h_mm",
                "peak_24h_rain_mm",
            ],
        )
        writer.writeheader()
        writer.writerows(scenario_rows)

    with METADATA_FILE.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "scenario",
                "target_percentile",
                "target_quantile",
                "threshold_24h_rain_mm",
                "selected_peak_time",
                "peak_24h_rain_mm",
                "difference_from_threshold_mm",
            ],
        )
        writer.writeheader()
        writer.writerows(metadata_rows)

    for row in metadata_rows:
        print(
            f"{row['scenario']}: {row['target_percentile']} "
            f"threshold={row['threshold_24h_rain_mm']} mm, "
            f"peak={row['peak_24h_rain_mm']} mm at {row['selected_peak_time']}"
        )


def main() -> None:
    if not SOURCE_FILE.is_file():
        raise FileNotFoundError(f"Rainfall source CSV not found: {SOURCE_FILE}")
    observations = load_observations(SOURCE_FILE)
    totals = rolling_24h(observations)
    peaks = decluster(local_maxima(observations, totals))
    write_outputs(observations, totals, peaks)
    print(f"Loaded {len(observations):,} hourly observations")
    print(f"Found {len(peaks):,} declustered local-maximum events")
    print(f"Wrote {SCENARIOS_FILE}")
    print(f"Wrote {METADATA_FILE}")


if __name__ == "__main__":
    main()
