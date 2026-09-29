"""Create contract-complete synthetic CSV inputs for UI and package validation."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

MEASUREMENT_FIELDS = ("Name", "Row", "Node", "Status")
PREDICTION_FIELDS = (
    "name",
    "row",
    "node",
    "prediction",
    "confidence",
    "review_required",
    "prob_Normal",
    "prob_Open",
    "prob_Short",
    "provenance",
)


def _coordinates():
    for row in range(1, 27):
        for node in range(1, 39):
            yield row, node


def create_inputs(output_dir: Path, *, include_prediction_only: bool = True) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    measurement_path = output_dir / "synthetic_measurement.csv"
    prediction_path = output_dir / "synthetic_prediction.csv"
    measurement_names = (
        "20260807-P3MEEMT_8kgf_350_sam 01",
        "20260807-P3MEEMT_8kgf_350_sam 02",
    )
    prediction_names = (
        "260807 p3meemt 8kgf 350 SAM 1",
        "260807 p3meemt 8kgf 350 SAM 2",
    )
    statuses = ("Pass", "No Gate Effect", "No Active", "None", "Open", "Short")

    with measurement_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MEASUREMENT_FIELDS)
        writer.writeheader()
        for sample_index, name in enumerate(measurement_names):
            for index, (row, node) in enumerate(_coordinates()):
                writer.writerow(
                    {
                        "Name": name,
                        "Row": f"{row:02d}",
                        "Node": f"{node:02d}",
                        "Status": statuses[(index + sample_index) % len(statuses)],
                    }
                )

    names = list(prediction_names)
    if include_prediction_only:
        names.append("260807 p3meemt 8kgf 350 SAM 99")
    with prediction_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PREDICTION_FIELDS)
        writer.writeheader()
        for sample_index, name in enumerate(names):
            for index, (row, node) in enumerate(_coordinates()):
                prediction = ("Normal", "Open", "Short")[(index + sample_index) % 3]
                probabilities = {
                    "Normal": (0.90, 0.05, 0.05),
                    "Open": (0.05, 0.90, 0.05),
                    "Short": (0.05, 0.05, 0.90),
                }[prediction]
                writer.writerow(
                    {
                        "name": name,
                        "row": f"{row:02d}",
                        "node": f"{node:02d}",
                        "prediction": prediction,
                        "confidence": "0.90",
                        "review_required": str(index % 31 == 0).lower(),
                        "prob_Normal": probabilities[0],
                        "prob_Open": probabilities[1],
                        "prob_Short": probabilities[2],
                        "provenance": "synthetic-validation-v1",
                    }
                )
    return measurement_path, prediction_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--without-prediction-only", action="store_true")
    args = parser.parse_args()
    measurement, prediction = create_inputs(
        args.output_dir,
        include_prediction_only=not args.without_prediction_only,
    )
    print(f"measurement={measurement}")
    print(f"prediction={prediction}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
