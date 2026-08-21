#!/usr/bin/env python3
"""Deterministic density-fit and rubric arithmetic for subject-index evaluations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


WEIGHTS = {
    "meaningful_coverage": 20,
    "editorial_selectivity": 15,
    "conceptual_stance_fidelity": 15,
    "page_reference_reliability": 25,
    "findability_navigation": 20,
    "mechanics_consistency": 5,
}


def emit(value: Any) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False))


def half_step(value: float) -> float:
    return round(value * 2) / 2


def validate_band(a_min: float, i_min: float, i_max: float, a_max: float) -> None:
    if not a_min <= i_min <= i_max <= a_max:
        raise ValueError("Expected acceptable_min <= ideal_min <= ideal_max <= acceptable_max")
    if a_min < 0:
        raise ValueError("Density boundaries must be nonnegative")


def density_rating(value: float, acceptable_min: float, ideal_min: float, ideal_max: float, acceptable_max: float) -> tuple[float, str, float]:
    validate_band(acceptable_min, ideal_min, ideal_max, acceptable_max)
    if ideal_min <= value <= ideal_max:
        return 5.0, "ideal", 0.0
    if acceptable_min <= value <= acceptable_max:
        return 4.0, "acceptable", 0.0
    if value < acceptable_min:
        distance = (acceptable_min - value) / acceptable_min if acceptable_min else float("inf")
        direction = "below_acceptable"
    else:
        distance = (value - acceptable_max) / acceptable_max if acceptable_max else float("inf")
        direction = "above_acceptable"
    if distance <= 0.25:
        rating = 3.0
    elif distance <= 0.50:
        rating = 2.0
    elif distance <= 1.0:
        rating = 1.0
    else:
        rating = 0.0
    return rating, direction, distance


def command_density(args: argparse.Namespace) -> None:
    try:
        rating, band, distance = density_rating(
            args.value, args.acceptable_min, args.ideal_min, args.ideal_max, args.acceptable_max
        )
    except ValueError as exc:
        emit({"ok": False, "error": str(exc)})
        raise SystemExit(1)
    emit({
        "ok": True,
        "metric_id": args.metric_id,
        "value": args.value,
        "band": band,
        "distance_outside_acceptable": round(distance, 6),
        "density_fit_rating": rating,
        "density_points_out_of_5": rating,
    })


def command_scorecard(args: argparse.Namespace) -> None:
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    ratings = payload.get("ratings", {})
    errors: list[str] = []
    rows: list[dict[str, Any]] = []
    total = 0.0

    for dimension, weight in WEIGHTS.items():
        if dimension == "editorial_selectivity":
            selectivity = payload.get("editorial_selectivity_subscores", {})
            substantive = selectivity.get("substantive_selectivity_rating")
            density = selectivity.get("density_fit_rating")
            if not valid_half_rating(substantive) or not valid_half_rating(density):
                errors.append("Editorial selectivity requires half-step substantive_selectivity_rating and density_fit_rating values from 0 to 5.")
                continue
            points = float(substantive) / 5 * 10 + float(density) / 5 * 5
            equivalent_rating = points / 15 * 5
            rows.append({
                "dimension_id": dimension,
                "weight": weight,
                "rating": round(equivalent_rating, 4),
                "points": round(points, 2),
                "subscores": {
                    "substantive_selectivity_rating": substantive,
                    "substantive_points_out_of_10": round(float(substantive) / 5 * 10, 2),
                    "density_fit_rating": density,
                    "density_points_out_of_5": round(float(density), 2),
                },
            })
            total += points
            continue
        rating = ratings.get(dimension)
        if not valid_half_rating(rating):
            errors.append(f"{dimension} requires a half-step rating from 0 to 5.")
            continue
        points = float(rating) / 5 * weight
        rows.append({"dimension_id": dimension, "weight": weight, "rating": rating, "points": round(points, 2)})
        total += points

    if errors:
        emit({"ok": False, "errors": errors})
        raise SystemExit(1)
    result = {
        "ok": True,
        "scorecard": rows,
        "total_score": round(total, 2),
        "maximum_score": 100,
        "arithmetic_check": round(sum(row["points"] for row in rows), 2) == round(total, 2),
    }
    if args.output:
        Path(args.output).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        result["artifact_written"] = str(Path(args.output).resolve())
    emit(result)


def valid_half_rating(value: Any) -> bool:
    return isinstance(value, (int, float)) and 0 <= value <= 5 and abs(value * 2 - round(value * 2)) < 1e-9


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    density = subparsers.add_parser("density")
    density.add_argument("--metric-id", required=True)
    density.add_argument("--value", type=float, required=True)
    density.add_argument("--acceptable-min", type=float, required=True)
    density.add_argument("--ideal-min", type=float, required=True)
    density.add_argument("--ideal-max", type=float, required=True)
    density.add_argument("--acceptable-max", type=float, required=True)
    density.set_defaults(func=command_density)

    scorecard = subparsers.add_parser("scorecard")
    scorecard.add_argument("--input", required=True)
    scorecard.add_argument("--output")
    scorecard.set_defaults(func=command_scorecard)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
