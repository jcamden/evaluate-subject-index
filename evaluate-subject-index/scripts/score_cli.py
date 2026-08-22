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

STANDARD_DENSITY_METRICS = [
    {
        "metric_id": "locator_bearing_heading_paths_per_1000_source_words",
        "count_field": "locator_bearing_heading_paths",
        "target": 8.0,
        "ideal_min": 6.0,
        "ideal_max": 10.0,
        "acceptable_min": 4.0,
        "acceptable_max": 12.0,
        "weight": 0.5,
    },
    {
        "metric_id": "locator_occurrences_per_1000_source_words",
        "count_field": "locator_occurrences",
        "target": 20.0,
        "ideal_min": 15.0,
        "ideal_max": 25.0,
        "acceptable_min": 10.0,
        "acceptable_max": 30.0,
        "weight": 0.5,
    },
]


def emit(value: Any) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False))


def half_step(value: float) -> float:
    return int(value * 2 + 0.5) / 2


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


def command_density_profile(args: argparse.Namespace) -> None:
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    chapters = payload.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        emit({"ok": False, "errors": ["Input requires a non-empty chapters array."]})
        raise SystemExit(1)

    errors: list[str] = []
    warnings: list[str] = []
    results: list[dict[str, Any]] = []
    total_words = 0
    weighted_rating_total = 0.0
    seen_ids: set[str] = set()

    for index, chapter in enumerate(chapters, start=1):
        if not isinstance(chapter, dict):
            errors.append(f"Chapter {index} must be an object.")
            continue
        chunk_id = chapter.get("chunk_id")
        words = chapter.get("indexable_source_words")
        if not isinstance(chunk_id, str) or not chunk_id or chunk_id in seen_ids:
            errors.append(f"Chapter {index} requires a unique non-empty chunk_id.")
            continue
        seen_ids.add(chunk_id)
        if not isinstance(words, int) or words <= 0:
            errors.append(f"{chunk_id}: indexable_source_words must be a positive integer.")
            continue
        if words < 1000:
            warnings.append(f"{chunk_id}: fewer than 1,000 indexable words; treat its rate as unstable or combine it with a declared adjacent unit.")

        metric_results: list[dict[str, Any]] = []
        raw_unit_rating = 0.0
        counts_valid = True
        for metric in STANDARD_DENSITY_METRICS:
            count = chapter.get(metric["count_field"])
            if not isinstance(count, int) or count < 0:
                errors.append(f"{chunk_id}: {metric['count_field']} must be a nonnegative integer.")
                counts_valid = False
                continue
            value = count / words * 1000
            rating, band, distance = density_rating(
                value,
                metric["acceptable_min"],
                metric["ideal_min"],
                metric["ideal_max"],
                metric["acceptable_max"],
            )
            metric_results.append({
                "metric_id": metric["metric_id"],
                "count": count,
                "value_per_1000_words": round(value, 4),
                "target": metric["target"],
                "target_band": [metric["ideal_min"], metric["ideal_max"]],
                "broad_tolerance_band": [metric["acceptable_min"], metric["acceptable_max"]],
                "band": {"ideal": "target", "acceptable": "broad_tolerance"}.get(band, band),
                "distance_outside_broad_tolerance": round(distance, 6),
                "fit_rating": rating,
                "weight": metric["weight"],
            })
            raw_unit_rating += rating * metric["weight"]
        if not counts_valid:
            continue

        expected_paths = words / 1000 * STANDARD_DENSITY_METRICS[0]["target"]
        expected_locators = words / 1000 * STANDARD_DENSITY_METRICS[1]["target"]
        results.append({
            "chunk_id": chunk_id,
            "source_unit_label": chapter.get("source_unit_label", chunk_id),
            "indexable_source_words": words,
            "locator_bearing_heading_paths": chapter["locator_bearing_heading_paths"],
            "locator_occurrences": chapter["locator_occurrences"],
            "calibration_counts": {
                "locator_bearing_heading_paths": round(expected_paths, 2),
                "locator_occurrences": round(expected_locators, 2),
            },
            "metric_results": metric_results,
            "unit_fit_rating_unrounded": round(raw_unit_rating, 6),
            "unit_fit_rating": half_step(raw_unit_rating),
        })
        total_words += words
        weighted_rating_total += raw_unit_rating * words

    if errors:
        emit({"ok": False, "errors": errors, "warnings": warnings})
        raise SystemExit(1)

    raw_fit = weighted_rating_total / total_words
    fit_rating = half_step(raw_fit)
    result = {
        "ok": True,
        "profile_id": "subject-index-standard-density-v1",
        "measurement_level": "chapter_or_approved_intellectual_unit",
        "aggregation": "indexable_source_word_weighted_mean",
        "targets": [
            {
                "metric_id": metric["metric_id"],
                "target": metric["target"],
                "target_band": [metric["ideal_min"], metric["ideal_max"]],
                "broad_tolerance_band": [metric["acceptable_min"], metric["acceptable_max"]],
                "weight": metric["weight"],
            }
            for metric in STANDARD_DENSITY_METRICS
        ],
        "chapter_measurements": results,
        "indexable_source_words": total_words,
        "fit_rating_unrounded": round(raw_fit, 6),
        "fit_rating": fit_rating,
        "selectivity_points_contributed": fit_rating,
        "maximum_score_contribution": 5,
        "calibration_disclosure": "Targets are 8 locator-bearing heading paths and 20 locator occurrences per 1,000 indexable source words, measured by chapter as permissive calibration rather than quotas or hard ceilings.",
        "warnings": warnings,
    }
    if args.output:
        Path(args.output).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        result["artifact_written"] = str(Path(args.output).resolve())
    emit(result)


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

    density_profile = subparsers.add_parser("density-profile")
    density_profile.add_argument("--input", required=True)
    density_profile.add_argument("--output")
    density_profile.set_defaults(func=command_density_profile)

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
