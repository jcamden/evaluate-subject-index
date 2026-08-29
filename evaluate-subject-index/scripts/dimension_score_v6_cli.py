#!/usr/bin/env python3
"""Deterministic V6 scoring and V5-to-V6 score-only migration.

V6 reuses the frozen V5 evidence contract and all unchanged dimension formulas.
Only Page-reference Reliability changes: its harmonic mean uses weighted locator
precision while strict substantive precision remains a separately reported
diagnostic.  Historical V5 commands and validators remain in
``dimension_score_cli.py`` and are never reinterpreted by this module.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Sequence

import dimension_score_cli as v5
from locator_relevance import assign_locator_credit, combined_state_errors


RUBRIC_VERSION = "subject-index-rubric-v6"
CALCULATION_PROFILE = "subject-index-dimension-calculation-v2"
CALCULATION_SCHEMA = "subject-index-dimension-calculations-v2"
RESULT_SCHEMA = "subject-index-evaluation-result-v7"
WEB_REPORT_SCHEMA = "subject-index-web-report-v5"
ITEM_ASSESSMENT_SCHEMA = "subject-index-item-assessments-v3"
ITEM_GRADING_POLICY = "subject-index-item-grading-v2"
MIGRATION_SCHEMA = "subject-index-score-migration-v5-to-v6-v1"
TOOL_NAME = "dimension_score_v6_cli.py"
TOOL_VERSION = "dimension-score-cli-v6.0.0"
METHODOLOGY_REPOSITORY = "https://github.com/jcamden/evaluate-subject-index"

ZERO = Decimal(0)
ONE = Decimal(1)
TWO = Decimal(2)
FIVE = Decimal(5)


def write_json(path: Path, value: dict[str, Any]) -> None:
    """Write Decimal-bearing documents without introducing binary-float math."""

    v5.write_json(path, v5.json_output_value(value))


def locator_state_requirements(ledgers: dict[str, Any]) -> list[dict[str, Any]]:
    """Return precise V6 migration/preflight failures without inferring prose."""

    missing: list[dict[str, Any]] = []
    for locator in sorted(ledgers["locators"], key=lambda item: str(item.get("locator_id", ""))):
        errors = combined_state_errors(locator)
        if not errors:
            try:
                assign_locator_credit(locator, ledgers["defects"])
            except ValueError as exc:
                errors = str(exc).split(";")
        if errors:
            missing.append(
                {
                    "code": "inconsistent_or_incomplete_locator_state",
                    "path": f"locator:{locator.get('locator_id', '<missing>')}",
                    "message": "V6 requires an explicit, logically consistent combined locator state.",
                    "locator_id": locator.get("locator_id"),
                    "state_errors": errors,
                }
            )
    return missing


def raw_locator_state_requirements(
    config_path: Path,
) -> tuple[str | None, list[dict[str, Any]], list[Path]]:
    """Pre-scan V5 ledgers so schema-missing V6 fields get an actionable report.

    The authoritative V5 loader still performs every hash and schema check when
    this report is empty.  This narrow pre-scan never treats prose as evidence.
    """

    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, [], []
    references = config.get("inputs", {}).get("locator_audits", [])
    if not isinstance(references, list):
        return config.get("evaluation_id"), [], []
    missing: list[dict[str, Any]] = []
    paths: list[Path] = []
    for batch_index, reference in enumerate(references):
        stored = reference.get("path") if isinstance(reference, dict) else None
        if not isinstance(stored, str) or not stored:
            continue
        path = (config_path.parent / stored).resolve()
        paths.append(path)
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        judgments = document.get("judgments")
        if not isinstance(judgments, list):
            missing.append(
                {
                    "code": "missing_locator_judgment_collection",
                    "path": f"locator_audit[{batch_index}].judgments",
                    "message": "V6 migration requires the frozen locator judgment array.",
                    "state_errors": ["missing:judgments"],
                }
            )
            continue
        for judgment_index, locator in enumerate(judgments):
            errors = (
                combined_state_errors(locator)
                if isinstance(locator, dict)
                else ["invalid:locator_record"]
            )
            if errors:
                locator_id = locator.get("locator_id") if isinstance(locator, dict) else None
                missing.append(
                    {
                        "code": "inconsistent_or_incomplete_locator_state",
                        "path": f"locator_audit[{batch_index}].judgments[{judgment_index}]",
                        "message": "V6 requires an explicit, logically consistent combined locator state.",
                        "locator_id": locator_id,
                        "state_errors": errors,
                    }
                )
    return config.get("evaluation_id"), missing, paths


def preflight_loaded(loaded: dict[str, Any]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    ledgers, missing = v5.preflight_loaded(loaded)
    if ledgers is None:
        return None, missing
    missing = [*missing, *locator_state_requirements(ledgers)]
    return (ledgers if not missing else None), missing


def credit_assignments(ledgers: dict[str, Any]) -> list[dict[str, Any]]:
    assignments: list[dict[str, Any]] = []
    for locator in sorted(ledgers["locators"], key=lambda item: item["locator_id"]):
        try:
            assignment = assign_locator_credit(locator, ledgers["defects"])
        except ValueError as exc:
            raise v5.CalculationError(
                "inconsistent_locator_evidence_state",
                f"Locator {locator.get('locator_id')} cannot receive a V6 reliability credit.",
                {"locator_id": locator.get("locator_id"), "errors": str(exc).split(";")},
            ) from exc
        assignments.append(assignment.as_dict())
    assignments.extend(
        {
            "locator_id": locator_id,
            "judgment": "not_measured",
            "treatment_class": None,
            "source_scope_status": None,
            "credit_tier": "not_measured",
            "reliability_credit": None,
            "diagnostic_grade": None,
            "weak_presence_eligible": False,
            "disqualifying_codes": [],
            "disqualifying_defect_ids": [],
            "rationale": "The required locator assignment was not measured.",
        }
        for locator_id in sorted(ledgers["locator_not_measured"])
    )
    return sorted(assignments, key=lambda item: item["locator_id"])


def calculate_reliability(ledgers: dict[str, Any], audit_mode: str) -> dict[str, Any]:
    assignments = credit_assignments(ledgers)
    by_id = {item["locator_id"]: item for item in assignments}
    measured_locators = [
        item
        for item in ledgers["locators"]
        if item.get("judgment") in {"supported", "partially_supported", "unsupported"}
    ]
    uninspectable_locators = [
        item for item in ledgers["locators"] if item.get("judgment") == "uninspectable"
    ]
    locator_not_measured = ledgers["locator_not_measured"]
    weighted_denom = v5.component_denominators(
        "weighted_locator_precision",
        ledgers["locator_original"],
        ledgers["locator_original"],
        len(measured_locators),
        len(uninspectable_locators),
        len(locator_not_measured),
        {},
    )
    strict_denom = v5.component_denominators(
        "strict_substantive_precision",
        ledgers["locator_original"],
        ledgers["locator_original"],
        len(measured_locators),
        len(uninspectable_locators),
        len(locator_not_measured),
        {},
    )

    measured_treatments = [
        item for item in ledgers["treatments"] if item.get("status") in {"found", "missed"}
    ]
    uninspectable_treatments = [
        item for item in ledgers["treatments"] if item.get("status") == "uninspectable"
    ]
    explicit_treatment_not_measured_records = [
        item for item in ledgers["treatments"] if item.get("status") is None
    ]
    explicit_treatment_not_measured = [
        item["treatment_id"] for item in explicit_treatment_not_measured_records
    ]
    treatment_not_measured = ledgers["treatment_not_measured"] + explicit_treatment_not_measured
    recall_denom = v5.component_denominators(
        "expected_treatment_recall",
        ledgers["treatment_original"],
        ledgers["treatment_original"],
        len(measured_treatments),
        len(uninspectable_treatments),
        len(treatment_not_measured),
        {},
    )

    weighted_numerator = sum(
        (v5.decimal_value(by_id[item["locator_id"]]["reliability_credit"]) for item in measured_locators),
        ZERO,
    )
    supported = sum(item["judgment"] == "supported" for item in measured_locators)
    found = sum(item["status"] == "found" for item in measured_treatments)
    assessable = len(measured_locators)
    pw = weighted_numerator / Decimal(assessable) if assessable else ZERO
    strict_precision = v5.rate(supported, assessable)
    recall = v5.rate(found, len(measured_treatments))

    unknown_loc = len(uninspectable_locators) + len(locator_not_measured)
    unknown_treat = len(uninspectable_treatments) + len(treatment_not_measured)
    locator_bound_denominator = assessable + unknown_loc
    pw_lower = (
        weighted_numerator / Decimal(locator_bound_denominator)
        if locator_bound_denominator
        else ZERO
    )
    pw_upper = (
        (weighted_numerator + Decimal(unknown_loc)) / Decimal(locator_bound_denominator)
        if locator_bound_denominator
        else ZERO
    )
    strict_lower = v5.rate(supported, locator_bound_denominator)
    strict_upper = v5.rate(supported + unknown_loc, locator_bound_denominator)
    recall_lower = v5.rate(found, len(measured_treatments) + unknown_treat)
    recall_upper = v5.rate(found + unknown_treat, len(measured_treatments) + unknown_treat)

    expected_treatments = ledgers["treatment_original"]
    no_locator_assignments = ledgers["locator_original"] == 0
    attempt = ledgers["context"]["candidate_attempt"]["status"]
    if expected_treatments > 0 and no_locator_assignments:
        central_base = lower_base = upper_base = ZERO
        for denominator in (weighted_denom, strict_denom):
            v5.mark_defined_zero(denominator, "expected_treatments_but_no_locator_assignments")
    else:
        central_base = FIVE * v5.f1(pw, recall)
        lower_base = FIVE * v5.f1(pw_lower, recall_lower)
        upper_base = FIVE * v5.f1(pw_upper, recall_upper)
    if attempt in {"empty", "structurally_incomplete", "unparseable"}:
        central_base = lower_base = upper_base = ZERO
        for denominator in (weighted_denom, strict_denom, recall_denom):
            v5.mark_defined_zero(denominator, f"candidate_attempt:{attempt}", non_attempt=True)

    high_measured = [
        item
        for item in measured_treatments
        if item.get("locator_class") in {"principal", "synthesis_or_conclusion"}
    ]
    high_unknown = [
        item
        for item in uninspectable_treatments
        if item.get("locator_class") in {"principal", "synthesis_or_conclusion"}
    ]
    high_not_measured_ids = [
        item["treatment_id"]
        for item in explicit_treatment_not_measured_records
        if item.get("locator_class") in {"principal", "synthesis_or_conclusion"}
    ] + ledgers["treatment_not_measured"]
    high_found = sum(item["status"] == "found" for item in high_measured)
    critical = v5.defect_subset(
        ledgers,
        "page_reference_reliability",
        severities={"critical"},
        kinds={"fabricated_locator", "nonexistent_locator", "out_of_scope_locator"},
    )
    pattern = [
        item
        for item in measured_locators
        if item.get("judgment") == "unsupported"
        and set(item.get("error_codes", [])) & v5.RELIABILITY_CODES
    ]
    pattern_units = {item.get("_source_unit_id") for item in pattern if item.get("_source_unit_id")}
    unknown_locator_units = {
        item.get("_source_unit_id")
        for item in uninspectable_locators
        if item.get("_source_unit_id")
    } | {item for item in ledgers["locator_not_measured_units"] if item}
    unit_denominator = max(1, len(ledgers["source_units"]))

    def caps(
        high_found_value: int,
        high_total: int,
        pattern_count: int,
        locator_total: int,
        units: int,
        high_miss_evidence: Sequence[str],
        pattern_evidence: Sequence[str],
    ) -> list[dict[str, Any]]:
        high_max, high_triggered, high_band = v5.high_value_cap(high_found_value, high_total)
        pattern_max, pattern_triggered, pattern_band = v5.reliability_pattern_cap(
            pattern_count, locator_total, units, unit_denominator
        )
        return [
            v5.cap_record(
                "reliability.critical_locator",
                Decimal(2),
                bool(critical),
                {
                    "severity": "critical",
                    "defect_kinds": [
                        "fabricated_locator",
                        "nonexistent_locator",
                        "out_of_scope_locator",
                    ],
                },
                {"defect_count": len(critical)},
                [item["defect_id"] for item in critical],
            ),
            v5.cap_record(
                "reliability.high_value_treatment_recall",
                high_max,
                high_triggered,
                {"table": "pooled_principal_and_synthesis_recall_v1", "band": high_band},
                {
                    "found": high_found_value,
                    "expected": high_total,
                    "rate": v5.decimal_text(v5.rate(high_found_value, high_total)),
                },
                high_miss_evidence,
            ),
            v5.cap_record(
                "reliability.distributed_unsupported_pattern",
                pattern_max,
                pattern_triggered,
                {
                    "minimum_source_unit_rate": "0.25",
                    "rate_table": "reliability_owned_unsupported_v1",
                    "band": pattern_band,
                },
                {
                    "unsupported_count": pattern_count,
                    "assessable_locator_denominator": locator_total,
                    "rate": v5.decimal_text(v5.rate(pattern_count, locator_total)),
                    "affected_source_units": units,
                    "source_unit_denominator": unit_denominator,
                    "source_unit_rate": v5.decimal_text(v5.rate(units, unit_denominator)),
                },
                pattern_evidence,
            ),
        ]

    known_high_misses = [
        item["treatment_id"] for item in high_measured if item["status"] == "missed"
    ]
    known_pattern_ids = [item["locator_id"] for item in pattern]
    central_caps = caps(
        high_found,
        len(high_measured),
        len(pattern),
        assessable,
        len(pattern_units),
        known_high_misses,
        known_pattern_ids,
    )
    lower_caps = caps(
        high_found,
        len(high_measured) + len(high_unknown) + len(high_not_measured_ids),
        len(pattern) + unknown_loc,
        assessable + unknown_loc,
        len(pattern_units | unknown_locator_units),
        known_high_misses
        + [item["treatment_id"] for item in high_unknown]
        + high_not_measured_ids,
        known_pattern_ids
        + [item["locator_id"] for item in uninspectable_locators]
        + locator_not_measured,
    )
    upper_caps = caps(
        high_found + len(high_unknown) + len(high_not_measured_ids),
        len(high_measured) + len(high_unknown) + len(high_not_measured_ids),
        len(pattern),
        assessable + unknown_loc,
        len(pattern_units),
        known_high_misses,
        known_pattern_ids,
    )

    result = v5.finish_dimension(
        "page_reference_reliability",
        [weighted_denom, strict_denom, recall_denom],
        central_base,
        lower_base,
        upper_base,
        central_caps,
        lower_caps,
        upper_caps,
        audit_mode,
    )
    result["formula_id"] = f"{CALCULATION_PROFILE}:page_reference_reliability"
    result["input_roles"] = [
        "locator_audit",
        "missing_access_audit",
        "structure_audit_or_migration_supplement",
    ]
    result["raw_status_counts"] = {
        "locator_support": dict(Counter(item["judgment"] for item in ledgers["locators"])),
        "locator_treatment_class": dict(
            Counter(item.get("treatment_class") for item in ledgers["locators"])
        ),
        "reliability_credit_tier": dict(Counter(item["credit_tier"] for item in assignments)),
        "treatment_recall": dict(
            Counter(item.get("status") or "not_measured" for item in ledgers["treatments"])
        ),
        "not_measured_locators": len(locator_not_measured),
        "not_measured_treatments": len(treatment_not_measured),
    }
    result["credit_mappings"] = {
        "weighted_locator_precision": {
            "supported": "1",
            "partially_supported": "0.5",
            "eligible_weak_presence": "0.25",
            "other_unsupported": "0",
            "uninspectable": "neutral_uncertainty_bounds",
        },
        "strict_substantive_precision": {
            "supported": "1",
            "partially_supported": "0",
            "eligible_weak_presence": "0",
            "other_unsupported": "0",
        },
        "treatment_recall": {"found": "1", "missed": "0"},
    }
    f1_denominator = pw + recall
    result["components"] = [
        {
            "component_id": "weighted_locator_precision",
            "raw_numerator": v5.decimal_text(weighted_numerator),
            "raw_denominator": v5.decimal_text(Decimal(assessable)),
            "normalized_value": v5.decimal_text(pw),
            "weight": "harmonic_mean",
            "effective_weight": "harmonic_mean",
            "weight_renormalized": False,
        },
        {
            "component_id": "strict_substantive_precision",
            "raw_numerator": v5.decimal_text(Decimal(supported)),
            "raw_denominator": v5.decimal_text(Decimal(assessable)),
            "normalized_value": v5.decimal_text(strict_precision),
            "weight": "reported_diagnostic_only",
            "effective_weight": "not_used_in_dimension_arithmetic",
            "weight_renormalized": False,
        },
        {
            "component_id": "expected_treatment_recall",
            "raw_numerator": v5.decimal_text(Decimal(found)),
            "raw_denominator": v5.decimal_text(Decimal(len(measured_treatments))),
            "normalized_value": v5.decimal_text(recall),
            "weight": "harmonic_mean",
            "effective_weight": "harmonic_mean",
            "weight_renormalized": False,
        },
        {
            "component_id": "weighted_f1",
            "raw_numerator": v5.decimal_text(TWO * pw * recall),
            "raw_denominator": v5.decimal_text(f1_denominator),
            "normalized_value": v5.decimal_text(v5.f1(pw, recall)),
            "weight": "base_rating_times_5",
            "effective_weight": "base_rating_times_5",
            "weight_renormalized": False,
        },
        {
            "component_id": "high_value_treatment_recall_safeguard",
            "raw_numerator": v5.decimal_text(Decimal(high_found)),
            "raw_denominator": v5.decimal_text(Decimal(len(high_measured))),
            "normalized_value": v5.decimal_text(v5.rate(high_found, len(high_measured))),
            "weight": "cap_only",
            "effective_weight": "cap_only",
            "weight_renormalized": False,
        },
    ]
    result["reliability_provenance"] = {
        "original_locator_denominator": ledgers["locator_original"],
        "assessable_locator_denominator": assessable,
        "uninspectable_locator_count": len(uninspectable_locators),
        "not_measured_locator_count": len(locator_not_measured),
        "counts_by_judgment": {
            key: sum(item.get("judgment") == key for item in ledgers["locators"])
            for key in ("supported", "partially_supported", "unsupported", "uninspectable")
        }
        | {"not_measured": len(locator_not_measured)},
        "counts_by_treatment_class": dict(
            sorted(Counter(item.get("treatment_class") for item in ledgers["locators"]).items())
        )
        | ({"not_measured": len(locator_not_measured)} if locator_not_measured else {}),
        "counts_by_reliability_credit_tier": dict(
            sorted(Counter(item["credit_tier"] for item in assignments).items())
        ),
        "locator_credit_assignments": assignments,
        "weighted_precision_numerator": v5.decimal_text(weighted_numerator),
        "weighted_precision_denominator": assessable,
        "weighted_locator_precision": v5.decimal_text(pw),
        "strict_precision_numerator": supported,
        "strict_precision_denominator": assessable,
        "strict_substantive_precision": v5.decimal_text(strict_precision),
        "treatment_recall_numerator": found,
        "treatment_recall_denominator": len(measured_treatments),
        "treatment_recall": v5.decimal_text(recall),
        "weighted_f1": v5.decimal_text(v5.f1(pw, recall)),
        "strict_precision_uncertainty": {
            "lower": v5.decimal_text(strict_lower),
            "central": v5.decimal_text(strict_precision),
            "upper": v5.decimal_text(strict_upper),
        },
        "weighted_precision_uncertainty": {
            "lower": v5.decimal_text(pw_lower),
            "central": v5.decimal_text(pw),
            "upper": v5.decimal_text(pw_upper),
        },
        "treatment_recall_uncertainty": {
            "lower": v5.decimal_text(recall_lower),
            "central": v5.decimal_text(recall),
            "upper": v5.decimal_text(recall_upper),
        },
        "pre_cap_rating": result["pre_cap_rating"],
        "cap_evaluations": result["cap_evaluations"],
        "applied_cap": result["applied_cap"],
        "uncertainty_lower": result["missing_data_bounds"]["lower"],
        "uncertainty_upper": result["missing_data_bounds"]["upper"],
        "rounding": result["rounding"],
        "final_rating": result["final_rating"],
        "dimension_weight": result["dimension_weight"],
        "awarded_points": result["awarded_points"],
    }
    return result


def calculate_loaded(loaded: dict[str, Any]) -> dict[str, Any]:
    ledgers, missing = preflight_loaded(loaded)
    v5.require(
        ledgers is not None and not missing,
        "v6_inputs_insufficient",
        "The frozen ledgers do not satisfy the V6 calculation contract.",
        missing,
    )
    audit_mode = loaded["config"]["audit_mode"]
    dimensions = [
        v5.calculate_coverage(ledgers, audit_mode),
        v5.calculate_selectivity(ledgers, audit_mode),
        v5.calculate_concept(ledgers, audit_mode),
        calculate_reliability(ledgers, audit_mode),
        v5.calculate_findability(ledgers, audit_mode),
        v5.calculate_mechanics(ledgers, audit_mode),
    ]
    for dimension in dimensions:
        dimension["formula_id"] = f"{CALCULATION_PROFILE}:{dimension['dimension_id']}"
        selected: list[dict[str, Any]] = []
        for artifact in loaded["input_artifacts"]:
            role = artifact["role"]
            include = any(
                role == "chunk_manifest"
                or (requested == "locator_audit" and role.startswith("locator_audit["))
                or (requested == "missing_access_audit" and role.startswith("missing_access_audit["))
                or (requested == "structure_audit" and role == "structure_audit")
                or (
                    requested == "structure_audit_or_migration_supplement"
                    and role in {"structure_audit", "migration_supplement"}
                )
                for requested in dimension["input_roles"]
            )
            if include and artifact not in selected:
                selected.append(artifact)
        v5.require(
            bool(selected),
            "dimension_input_binding_failed",
            f"{dimension['dimension_id']} did not resolve frozen inputs.",
        )
        dimension["input_artifacts"] = selected

    all_scored = all(item["status"] == "scored" for item in dimensions)
    total = (
        v5.round_points(
            sum((v5.decimal_value(item["awarded_points"]) for item in dimensions), ZERO)
        )
        if all_scored
        else None
    )
    result = {
        "schema_version": CALCULATION_SCHEMA,
        "calculation_id": f"CALC-{v5.canonical_hash({'evaluation_id': loaded['config']['evaluation_id'], 'audit_mode': audit_mode, 'rubric_version': RUBRIC_VERSION, 'calculation_profile': CALCULATION_PROFILE, 'inputs': loaded['input_artifacts']})[:12].upper()}",
        "evaluation_id": loaded["config"]["evaluation_id"],
        "rubric_version": RUBRIC_VERSION,
        "calculation_profile": CALCULATION_PROFILE,
        "audit_mode": audit_mode,
        "status": "scored" if all_scored else "not_scored_insufficient_evidence",
        "evidence_identity": {
            field: ledgers["identity"][field]
            for field in v5.CALCULATION_EVIDENCE_IDENTITY_FIELDS
        },
        "input_artifacts": loaded["input_artifacts"],
        "diagnostic_item_grades": {
            "used_in_dimension_arithmetic": False,
            "policy": "separate_non_additive_display_layer",
            "required_policy_version": ITEM_GRADING_POLICY,
            "expected_source_subjects": {
                "count": len(ledgers["expected_subject_ids"]),
                "id_set_sha256": v5.canonical_hash({"ids": ledgers["expected_subject_ids"]}),
            },
        },
        "publication_readiness_gates": {
            "used_in_score_arithmetic": False,
            "policy": "separate_claim_restrictions_unchanged_from_v5",
        },
        "dimensions": dimensions,
        "total_score": v5.displayed_number(total, Decimal("0.01")) if total is not None else None,
        "maximum_score": 100,
        "arithmetic_check": all_scored
        and total
        == sum((v5.decimal_value(item["awarded_points"]) for item in dimensions), ZERO).quantize(
            Decimal("0.01"), rounding=v5.ROUND_HALF_UP
        ),
    }
    result["calculation_sha256"] = v5.canonical_hash(result, "calculation_sha256")
    return result


def reliability_dimension(calculation: dict[str, Any]) -> dict[str, Any]:
    matches = [
        item
        for item in calculation.get("dimensions", [])
        if item.get("dimension_id") == "page_reference_reliability"
    ]
    v5.require(
        len(matches) == 1,
        "v6_reliability_dimension_required",
        "A V6 calculation must contain exactly one Page-reference Reliability dimension.",
    )
    return matches[0]


def command_preflight(args: argparse.Namespace) -> None:
    config_path = Path(args.input).resolve()
    try:
        loaded = v5.load_inputs(config_path)
        _, missing = preflight_loaded(loaded)
        result = {
            "command": "v6-calculation-sufficiency-preflight",
            "ok": True,
            "evaluation_id": loaded["config"]["evaluation_id"],
            "target_rubric_version": RUBRIC_VERSION,
            "target_calculation_profile": CALCULATION_PROFILE,
            "sufficient": not missing,
            "input_artifacts": loaded["input_artifacts"],
            "missing_requirements": missing,
            "prose_inference_used": False,
            "mutated_inputs": False,
        }
        if args.output:
            output_path = Path(args.output).resolve()
            v5.require(
                not v5.aliases_existing_file(output_path, {config_path, *loaded["input_paths"]}),
                "output_aliases_frozen_input",
                "Preflight output must not overwrite or alias a frozen input.",
            )
            write_json(output_path, result)
            result["artifact_written"] = str(output_path)
        v5.emit(result)
    except (OSError, v5.CalculationError) as exc:
        error = (
            {"code": exc.code, "message": exc.message, "details": exc.details}
            if isinstance(exc, v5.CalculationError)
            else {"code": "file_error", "message": str(exc)}
        )
        v5.emit({"command": "v6-calculation-sufficiency-preflight", "ok": False, "error": error}, 1)


def command_calculate(args: argparse.Namespace) -> None:
    try:
        loaded = v5.load_inputs(Path(args.input).resolve())
        result = calculate_loaded(loaded)
        v5.validate_schema_document(result, "dimension-calculations-v2.schema.json", "Generated V6 dimension calculations")
        if args.output:
            output_path = Path(args.output).resolve()
            v5.require(
                not v5.aliases_existing_file(output_path, {loaded["config_path"], *loaded["input_paths"]}),
                "output_aliases_frozen_input",
                "Calculation output must not overwrite or alias a frozen input.",
            )
            write_json(output_path, result)
            response = {
                "command": "calculate-v6-dimensions",
                "ok": True,
                "evaluation_id": result["evaluation_id"],
                "status": result["status"],
                "total_score": result["total_score"],
                "calculation_sha256": result["calculation_sha256"],
                "artifact_written": str(output_path),
            }
        else:
            response = {"command": "calculate-v6-dimensions", "ok": True, **result}
        v5.emit(response)
    except (OSError, v5.CalculationError) as exc:
        error = (
            {"code": exc.code, "message": exc.message, "details": exc.details}
            if isinstance(exc, v5.CalculationError)
            else {"code": "file_error", "message": str(exc)}
        )
        v5.emit({"command": "calculate-v6-dimensions", "ok": False, "error": error}, 1)


def validate_historical_v5_projection(
    calculation_path: Path, result_path: Path, web_report_path: Path
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], Path]:
    validation = v5.validate_projection_artifacts(calculation_path, result_path, web_report_path)
    v5.require(validation.get("ok") is True, "historical_v5_projection_invalid", "Historical V5 projections did not validate.")
    calculation = v5.load_json(calculation_path, "Historical V5 calculation")
    result = v5.load_json(result_path, "Historical V5 evaluation result")
    web_report = v5.load_json(web_report_path, "Historical V5 web report")
    v5.require(
        calculation.get("schema_version") == "subject-index-dimension-calculations-v1"
        and calculation.get("rubric_version") == "subject-index-rubric-v5"
        and calculation.get("calculation_profile") == "subject-index-dimension-calculation-v1",
        "not_historical_v5",
        "V5-to-V6 migration requires the canonical V5 calculation identity.",
    )
    item_path = v5.resolve_referenced_artifact(
        result.get("item_assessments"), result_path, label="historical_v5_result.item_assessments"
    )
    return calculation, result, web_report, item_path


def score_snapshot(calculation: dict[str, Any]) -> list[dict[str, Any]]:
    mapped = {item["dimension_id"]: item for item in calculation["dimensions"]}
    v5.require(
        set(mapped) == set(v5.WEIGHTS) and len(calculation["dimensions"]) == len(v5.WEIGHTS),
        "calculation_dimension_set_mismatch",
        "Calculation must contain every dimension exactly once.",
    )
    return [
        {
            "dimension_id": dimension_id,
            "rating": mapped[dimension_id]["final_rating"],
            "points": mapped[dimension_id]["awarded_points"],
        }
        for dimension_id in v5.WEIGHTS
    ]


def compare_score_snapshots(
    previous: list[dict[str, Any]], migrated: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    old = {item["dimension_id"]: item for item in previous}
    new = {item["dimension_id"]: item for item in migrated}
    return [
        {
            "dimension_id": dimension_id,
            "previous": old[dimension_id],
            "migrated": new[dimension_id],
            "rating_delta": v5.nullable_delta(
                new[dimension_id]["rating"], old[dimension_id]["rating"], Decimal("0.0001")
            ),
            "points_delta": v5.nullable_delta(
                new[dimension_id]["points"], old[dimension_id]["points"], Decimal("0.01")
            ),
        }
        for dimension_id in v5.WEIGHTS
    ]


def historical_strict_precision(calculation: dict[str, Any]) -> str:
    reliability = reliability_dimension(calculation)
    components = {
        item["component_id"]: item for item in reliability.get("components", [])
    }
    strict = components.get("strict_locator_precision")
    v5.require(
        isinstance(strict, dict),
        "historical_strict_precision_missing",
        "The V5 calculation does not retain strict locator precision.",
    )
    return strict["normalized_value"]


def migration_preflight(
    loaded: dict[str, Any],
    historical_calculation_path: Path,
    historical_result_path: Path,
    historical_web_report_path: Path,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], dict[str, Any] | None]:
    ledgers, missing = preflight_loaded(loaded)
    history: dict[str, Any] | None = None
    try:
        old_calculation, old_result, old_web, item_path = validate_historical_v5_projection(
            historical_calculation_path, historical_result_path, historical_web_report_path
        )
        history = {
            "calculation": old_calculation,
            "result": old_result,
            "web_report": old_web,
            "item_assessments_path": item_path,
        }
        if ledgers is not None and old_calculation.get("evidence_identity") != ledgers.get("identity"):
            # ledgers.identity has additional runtime keys; compare only the frozen calculation set.
            expected_identity = {
                field: ledgers["identity"][field]
                for field in v5.CALCULATION_EVIDENCE_IDENTITY_FIELDS
            }
            if old_calculation.get("evidence_identity") != expected_identity:
                missing.append(
                    {
                        "code": "historical_v5_evidence_identity_mismatch",
                        "path": "historical_calculation.evidence_identity",
                        "message": "Historical V5 calculation does not bind the supplied frozen ledgers.",
                    }
                )
    except (OSError, v5.CalculationError) as exc:
        missing.append(
            {
                "code": getattr(exc, "code", "file_error"),
                "path": "historical_v5_projection",
                "message": getattr(exc, "message", str(exc)),
                "details": getattr(exc, "details", None),
            }
        )
    return (ledgers if not missing else None), missing, history


def command_migration_preflight(args: argparse.Namespace) -> None:
    try:
        config_path = Path(args.input).resolve()
        raw_evaluation_id, raw_missing, raw_locator_paths = raw_locator_state_requirements(
            config_path
        )
        if raw_missing:
            result = {
                "command": "v5-to-v6-score-only-migration-preflight",
                "ok": True,
                "evaluation_id": raw_evaluation_id,
                "target_rubric_version": RUBRIC_VERSION,
                "target_calculation_profile": CALCULATION_PROFILE,
                "sufficient": False,
                "missing_requirements": raw_missing,
                "required_locator_fields": [
                    "judgment",
                    "treatment_class",
                    "source_scope_status",
                    "error_codes_or_structured_defects",
                    "uninspectable_status",
                ],
                "historical_v5_validated": False,
                "source_reopened": False,
                "prose_inference_used": False,
                "frozen_evidence_mutated": False,
            }
            if args.output:
                output_path = Path(args.output).resolve()
                protected = {
                    config_path,
                    *raw_locator_paths,
                    Path(args.historical_calculation).resolve(),
                    Path(args.historical_result).resolve(),
                    Path(args.historical_web_report).resolve(),
                }
                v5.require(
                    not v5.aliases_existing_file(output_path, protected),
                    "output_aliases_frozen_input",
                    "Migration preflight output must not overwrite a frozen artifact.",
                )
                write_json(output_path, result)
                result["artifact_written"] = str(output_path)
            v5.emit(result)

        loaded = v5.load_inputs(config_path)
        _, missing, history = migration_preflight(
            loaded,
            Path(args.historical_calculation).resolve(),
            Path(args.historical_result).resolve(),
            Path(args.historical_web_report).resolve(),
        )
        result = {
            "command": "v5-to-v6-score-only-migration-preflight",
            "ok": True,
            "evaluation_id": loaded["config"]["evaluation_id"],
            "target_rubric_version": RUBRIC_VERSION,
            "target_calculation_profile": CALCULATION_PROFILE,
            "sufficient": not missing,
            "missing_requirements": missing,
            "required_locator_fields": [
                "judgment",
                "treatment_class",
                "source_scope_status",
                "error_codes_or_structured_defects",
                "uninspectable_status",
            ],
            "historical_v5_validated": history is not None,
            "source_reopened": False,
            "prose_inference_used": False,
            "frozen_evidence_mutated": False,
        }
        if args.output:
            output_path = Path(args.output).resolve()
            protected = {
                loaded["config_path"],
                *loaded["input_paths"],
                Path(args.historical_calculation).resolve(),
                Path(args.historical_result).resolve(),
                Path(args.historical_web_report).resolve(),
            }
            v5.require(
                not v5.aliases_existing_file(output_path, protected),
                "output_aliases_frozen_input",
                "Migration preflight output must not overwrite a frozen artifact.",
            )
            write_json(output_path, result)
            result["artifact_written"] = str(output_path)
        v5.emit(result)
    except (OSError, v5.CalculationError) as exc:
        error = (
            {"code": exc.code, "message": exc.message, "details": exc.details}
            if isinstance(exc, v5.CalculationError)
            else {"code": "file_error", "message": str(exc)}
        )
        v5.emit({"command": "v5-to-v6-score-only-migration-preflight", "ok": False, "error": error}, 1)


def command_migrate(args: argparse.Namespace) -> None:
    historical_calculation_path = Path(args.historical_calculation).resolve()
    historical_result_path = Path(args.historical_result).resolve()
    historical_web_report_path = Path(args.historical_web_report).resolve()
    config_path = Path(args.input).resolve()
    try:
        methodology_commit = v5.require_methodology_commit(args.methodology_commit)
        timestamp = v5.require_utc_timestamp(args.migration_timestamp, label="migration_timestamp")
        loaded = v5.load_inputs(config_path)
        ledgers, missing, history = migration_preflight(
            loaded,
            historical_calculation_path,
            historical_result_path,
            historical_web_report_path,
        )
        v5.require(
            ledgers is not None and not missing and history is not None,
            "v5_to_v6_migration_inputs_insufficient",
            "The frozen V5 evidence is insufficient for score-only V6 migration.",
            missing,
        )
        old_calculation = history["calculation"]
        old_result = history["result"]
        old_web = history["web_report"]
        item_path: Path = history["item_assessments_path"]
        protected_paths = {
            config_path,
            *loaded["input_paths"],
            historical_calculation_path,
            historical_result_path,
            historical_web_report_path,
            item_path,
        }
        protected_hashes = {path: v5.sha256_file(path) for path in protected_paths}
        calculations_output = Path(args.calculations_output).resolve()
        migration_output = Path(args.migration_record_output).resolve()
        v5.require(
            not v5.aliases_existing_file(calculations_output, protected_paths)
            and not v5.aliases_existing_file(migration_output, protected_paths),
            "output_aliases_frozen_input",
            "Migration outputs must not overwrite or alias historical or frozen evidence.",
        )
        v5.require(
            calculations_output != migration_output,
            "output_path_collision",
            "V6 calculation and migration record must use different output paths.",
        )

        calculations = calculate_loaded(loaded)
        gate_hash = v5.canonical_hash({"critical_gates": old_result.get("critical_gates", [])})
        calculations["migration_context"] = {
            "from_rubric_version": "subject-index-rubric-v5",
            "migration_schema_version": MIGRATION_SCHEMA,
            "migration_record_path": v5.portable_relative_reference(
                migration_output, calculations_output, label="migration_context.migration_record_path"
            ),
            "historical_calculation_sha256": protected_hashes[historical_calculation_path],
            "historical_result_sha256": protected_hashes[historical_result_path],
            "historical_web_report_sha256": protected_hashes[historical_web_report_path],
            "historical_gate_outcomes_sha256": gate_hash,
            "gate_outcomes_action": "preserve_identically",
        }
        calculations["calculation_sha256"] = v5.canonical_hash(
            calculations, "calculation_sha256"
        )
        v5.validate_schema_document(
            calculations, "dimension-calculations-v2.schema.json", "Migrated V6 calculations"
        )
        write_json(calculations_output, calculations)

        previous_snapshot = score_snapshot(old_calculation)
        migrated_snapshot = score_snapshot(calculations)
        old_strict = historical_strict_precision(old_calculation)
        new_strict = reliability_dimension(calculations)["reliability_provenance"][
            "strict_substantive_precision"
        ]
        v5.require(
            v5.decimal_value(old_strict) == v5.decimal_value(new_strict),
            "strict_precision_changed_during_migration",
            "V6 migration must preserve the historical strict substantive precision diagnostic.",
            {"historical": old_strict, "migrated": new_strict},
        )
        input_lineage = [
            {
                "role": artifact["role"],
                "path": artifact["path"],
                "sha256": artifact["sha256"],
                "schema_version": artifact["schema_version"],
                "disposition": "unchanged",
            }
            for artifact in loaded["input_artifacts"]
        ]
        migration = {
            "schema_version": MIGRATION_SCHEMA,
            "evaluation_id": calculations["evaluation_id"],
            "migration_timestamp": timestamp,
            "tool": {"name": TOOL_NAME, "version": TOOL_VERSION},
            "methodology": {
                "repository": METHODOLOGY_REPOSITORY,
                "commit_sha": methodology_commit,
                "previous_rubric_version": "subject-index-rubric-v5",
                "migrated_rubric_version": RUBRIC_VERSION,
                "calculation_profile": CALCULATION_PROFILE,
                "credit_values_frozen_not_candidate_fitted": True,
            },
            "from": {
                "rubric_version": "subject-index-rubric-v5",
                "calculation_profile": "subject-index-dimension-calculation-v1",
                "calculation": {
                    "path": v5.portable_relative_reference(
                        historical_calculation_path, migration_output, label="from.calculation.path"
                    ),
                    "sha256": protected_hashes[historical_calculation_path],
                    "calculation_sha256": old_calculation["calculation_sha256"],
                },
                "evaluation_result": {
                    "path": v5.portable_relative_reference(
                        historical_result_path, migration_output, label="from.evaluation_result.path"
                    ),
                    "sha256": protected_hashes[historical_result_path],
                },
                "item_assessments": {
                    "path": v5.portable_relative_reference(
                        item_path, migration_output, label="from.item_assessments.path"
                    ),
                    "sha256": protected_hashes[item_path],
                    "schema_version": old_result["item_assessments"]["schema_version"],
                    "grading_policy": old_result["item_assessments"]["grading_policy"],
                },
                "web_report": {
                    "path": v5.portable_relative_reference(
                        historical_web_report_path, migration_output, label="from.web_report.path"
                    ),
                    "sha256": protected_hashes[historical_web_report_path],
                },
                "total_score": old_calculation["total_score"],
                "scorecard": previous_snapshot,
            },
            "to": {
                "rubric_version": RUBRIC_VERSION,
                "calculation_profile": CALCULATION_PROFILE,
                "calculation_schema_version": CALCULATION_SCHEMA,
                "target_result_schema_version": RESULT_SCHEMA,
                "target_item_assessment_schema_version": ITEM_ASSESSMENT_SCHEMA,
                "target_web_report_schema_version": WEB_REPORT_SCHEMA,
                "calculation": {
                    "path": v5.portable_relative_reference(
                        calculations_output, migration_output, label="to.calculation.path"
                    ),
                    "sha256": v5.sha256_file(calculations_output),
                    "calculation_sha256": calculations["calculation_sha256"],
                },
                "total_score": calculations["total_score"],
                "scorecard": migrated_snapshot,
            },
            "total_delta": v5.nullable_delta(
                calculations["total_score"], old_calculation["total_score"], Decimal("0.01")
            ),
            "dimension_comparison": compare_score_snapshots(previous_snapshot, migrated_snapshot),
            "precision_comparison": {
                "historical_strict_substantive_precision": old_strict,
                "migrated_strict_substantive_precision": new_strict,
                "strict_precision_unchanged": True,
                "weighted_locator_precision": reliability_dimension(calculations)[
                    "reliability_provenance"
                ]["weighted_locator_precision"],
            },
            "frozen_evidence": {
                "input_lineage": input_lineage,
                "evidence_identity": calculations["evidence_identity"],
                "source_reopened": False,
                "prose_inference_used": False,
                "locator_judgments_changed": False,
                "missing_access_judgments_changed": False,
                "structure_judgments_changed": False,
                "candidate_normalization_changed": False,
                "representation_correction_provenance_preserved_via_immutable_v5_projections": True,
            },
            "historical_artifacts": {
                "preserved_immutable": True,
                "historical_v5_calculation_preserved": True,
                "historical_v5_result_preserved": True,
                "historical_v5_item_assessments_preserved": True,
                "historical_v5_web_report_preserved": True,
            },
            "invalidation": {
                "scope": "calculation_derived_and_projection_artifacts_only",
                "invalidated_active_roles": [
                    "dimension_calculations",
                    "evaluation_result",
                    "item_assessments",
                    "web_report",
                ],
                "upstream_evidence_invalidated": False,
            },
            "gate_preservation": {
                "policy_or_evidence_changed": False,
                "historical_gate_outcomes_sha256": gate_hash,
                "preserved_gate_outcomes_sha256": gate_hash,
                "historical_outcomes": deepcopy(old_result.get("critical_gates", [])),
                "preserved_outcomes": deepcopy(old_result.get("critical_gates", [])),
                "outcomes_equal": True,
                "outcomes_action": "preserve_identically",
                "score_based_override_allowed": False,
            },
            "selectivity_preservation": {
                "credit_mapping_changed": False,
                "weak_presence_credit": "0",
            },
            "comparability": "v5_and_v6_totals_are_not_directly_comparable",
        }
        migration["migration_sha256"] = v5.canonical_hash(migration, "migration_sha256")
        v5.validate_schema_document(
            migration,
            "score-migration-v5-to-v6.schema.json",
            "Generated V5-to-V6 score migration",
        )
        write_json(migration_output, migration)
        for path, before in protected_hashes.items():
            v5.require(
                v5.sha256_file(path) == before,
                "frozen_artifact_mutated",
                "A frozen V5 or upstream artifact changed during migration.",
                {"path": str(path)},
            )
        v5.emit(
            {
                "command": "v5-to-v6-score-only-migration",
                "ok": True,
                "evaluation_id": calculations["evaluation_id"],
                "v6_total_score": calculations["total_score"],
                "migration_schema_version": MIGRATION_SCHEMA,
                "methodology_commit": methodology_commit,
                "artifacts_written": [str(calculations_output), str(migration_output)],
                "frozen_evidence_mutated": False,
                "historical_v5_artifacts_mutated": False,
                "gate_outcomes_action": "preserve_identically",
            }
        )
    except (OSError, v5.CalculationError) as exc:
        error = (
            {"code": exc.code, "message": exc.message, "details": exc.details}
            if isinstance(exc, v5.CalculationError)
            else {"code": "file_error", "message": str(exc)}
        )
        v5.emit({"command": "v5-to-v6-score-only-migration", "ok": False, "error": error}, 1)


def precision_diagnostics(calculation: dict[str, Any]) -> dict[str, Any]:
    provenance = deepcopy(reliability_dimension(calculation)["reliability_provenance"])
    return {
        "weighted_locator_precision": provenance["weighted_locator_precision"],
        "weighted_precision_numerator": provenance["weighted_precision_numerator"],
        "weighted_precision_denominator": provenance["weighted_precision_denominator"],
        "strict_substantive_precision": provenance["strict_substantive_precision"],
        "strict_precision_numerator": provenance["strict_precision_numerator"],
        "strict_precision_denominator": provenance["strict_precision_denominator"],
        "treatment_recall": provenance["treatment_recall"],
        "treatment_recall_numerator": provenance["treatment_recall_numerator"],
        "treatment_recall_denominator": provenance["treatment_recall_denominator"],
        "weighted_f1": provenance["weighted_f1"],
        "weighted_role": "severity_sensitive_input_to_page_reference_reliability",
        "strict_role": "substantive_validity_diagnostic_not_used_in_v6_dimension_arithmetic",
        "weak_presence_is_substantive": False,
    }


def grade_label(score: Any) -> str:
    if score is None:
        return "Not scored"
    value = v5.decimal_value(score)
    if value >= 90:
        return "Excellent"
    if value >= 80:
        return "Strong"
    if value >= 70:
        return "Useful foundation"
    if value >= 60:
        return "Weak"
    return "Poor"


def scorecard_projection(calculation: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for dimension in calculation["dimensions"]:
        evidence_ids = sorted(
            {
                evidence_id
                for cap in dimension.get("cap_evaluations", [])
                for evidence_id in cap.get("affected_evidence_ids", [])
            }
        )
        record = {
            "dimension_id": dimension["dimension_id"],
            "label": dimension["dimension_id"].replace("_", " ").title(),
            "weight": dimension["dimension_weight"],
            "rating": dimension["final_rating"],
            "unrounded_rating": dimension["unrounded_rating"],
            "points": dimension["awarded_points"],
            "calculation_status": dimension["status"],
            "formula_id": dimension["formula_id"],
            "applied_cap_id": (
                dimension["applied_cap"]["cap_id"] if dimension["applied_cap"] else None
            ),
            "rationale": "Deterministically reconstructed from the bound V6 calculation artifact.",
            "evidence_ids": evidence_ids,
        }
        if dimension["dimension_id"] == "page_reference_reliability":
            record["subscores"] = precision_diagnostics(calculation)
        result.append(record)
    return result


def web_scorecard_projection(calculation: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for dimension in calculation["dimensions"]:
        record = {
            "dimension_id": dimension["dimension_id"],
            "label": dimension["dimension_id"].replace("_", " ").title(),
            "rating": dimension["final_rating"],
            "unrounded_rating": dimension["unrounded_rating"],
            "weight": dimension["dimension_weight"],
            "awarded_points": dimension["awarded_points"],
            "status": dimension["status"],
            "formula_id": dimension["formula_id"],
            "input_artifacts": dimension["input_artifacts"],
            "denominators": dimension["denominators"],
            "raw_status_counts": dimension["raw_status_counts"],
            "credit_mappings": dimension["credit_mappings"],
            "components": dimension["components"],
            "base_rating": dimension["base_rating"],
            "pre_cap_rating": dimension["pre_cap_rating"],
            "post_cap_rating": dimension["post_cap_rating"],
            "cap_evaluations": dimension["cap_evaluations"],
            "applied_cap": dimension["applied_cap"],
            "rounding": dimension["rounding"],
            "missing_data_bounds": dimension["missing_data_bounds"],
        }
        if dimension["dimension_id"] == "page_reference_reliability":
            record["reliability_provenance"] = deepcopy(dimension["reliability_provenance"])
        records.append(record)
    return records


def load_optional_migration(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    migration = v5.load_json(path, "V5-to-V6 migration record")
    v5.validate_schema_document(
        migration, "score-migration-v5-to-v6.schema.json", "V5-to-V6 migration record"
    )
    return migration


def build_projections(
    calculation_path: Path,
    item_assessments_path: Path,
    metadata_path: Path,
    result_output: Path,
    web_output: Path,
    migration_path: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    calculation = v5.load_json(calculation_path, "V6 calculation")
    items = v5.load_json(item_assessments_path, "V6 item assessments")
    metadata = v5.load_json(metadata_path, "V6 projection metadata")
    v5.validate_schema_document(
        calculation, "dimension-calculations-v2.schema.json", "V6 calculation"
    )
    v5.validate_schema_document(
        items, "item-assessments-v3.schema.json", "V6 item assessments"
    )
    v5.validate_schema_document(
        metadata, "v6-projection-metadata.schema.json", "V6 projection metadata"
    )
    v5.require(
        calculation["evaluation_id"] == items["evaluation_id"],
        "projection_identity_mismatch",
        "Calculation and item assessments belong to different evaluations.",
    )
    v5.require(
        calculation["evidence_identity"] == items["evidence_identity"],
        "projection_identity_mismatch",
        "Item-assessment evidence identity differs from the V6 calculation.",
    )
    migration = load_optional_migration(migration_path)
    if calculation.get("migration_context") is not None:
        v5.require(
            migration is not None,
            "projection_migration_required",
            "A migrated V6 calculation requires its bound migration record.",
        )
    if migration is not None:
        v5.require(
            migration["evaluation_id"] == calculation["evaluation_id"]
            and migration["to"]["calculation"]["calculation_sha256"]
            == calculation["calculation_sha256"],
            "projection_migration_mismatch",
            "Migration record does not bind the supplied V6 calculation.",
        )
        expected_gates = migration["gate_preservation"]["preserved_outcomes"]
        v5.require(
            metadata["critical_gates"] == expected_gates,
            "gate_preservation_mismatch",
            "Projection metadata must preserve the historical V5 gate array exactly.",
        )

    calculation_file_sha = v5.sha256_file(calculation_path)
    item_file_sha = v5.sha256_file(item_assessments_path)
    identity = calculation["evidence_identity"]
    gates = deepcopy(metadata["critical_gates"])
    gate_hash = v5.canonical_hash({"critical_gates": gates})
    result = {
        "schema_version": RESULT_SCHEMA,
        "evaluation_id": calculation["evaluation_id"],
        "candidate": {
            "label": metadata["candidate_label"],
            "sha256": identity["candidate_sha256"],
        },
        "provenance": {
            "source_sha256": identity["source_sha256"],
            "judgment_policy_sha256": identity["policy_sha256"],
            "benchmark_sha256": identity["benchmark_sha256"],
            "rubric_version": RUBRIC_VERSION,
            "dimension_calculation_profile": CALCULATION_PROFILE,
        },
        "audit_scope": {
            "mode": calculation["audit_mode"],
            "complete": calculation["audit_mode"] == "full",
        },
        "dimension_calculations": {
            "schema_version": CALCULATION_SCHEMA,
            "artifact_path": v5.portable_relative_reference(
                calculation_path, result_output, label="dimension_calculations.artifact_path"
            ),
            "sha256": calculation_file_sha,
            "calculation_profile": CALCULATION_PROFILE,
        },
        "scorecard": scorecard_projection(calculation),
        "total_score": calculation["total_score"],
        "interpretation": metadata.get(
            "interpretation", "V6 score reconstructed from frozen evidence."
        ),
        "metrics": {"locator_precision": precision_diagnostics(calculation)},
        "item_assessments": {
            "schema_version": ITEM_ASSESSMENT_SCHEMA,
            "grading_policy": ITEM_GRADING_POLICY,
            "artifact_path": v5.portable_relative_reference(
                item_assessments_path, result_output, label="item_assessments.artifact_path"
            ),
            "sha256": item_file_sha,
            "summary": items["summary"],
        },
        "critical_gates": gates,
        "defect_counts": metadata.get("defect_counts", {}),
        "comparison_key": {
            "source_sha256": identity["source_sha256"],
            "benchmark_sha256": identity["benchmark_sha256"],
            "judgment_policy_sha256": identity["policy_sha256"],
            "page_map_sha256": identity["page_map_sha256"],
            "chunk_manifest_sha256": identity["chunk_manifest_sha256"],
            "inclusion_policy": metadata["inclusion_policy"],
            "audit_mode": calculation["audit_mode"],
            "uncertainty_policy": metadata["uncertainty_policy"],
            "rubric_version": RUBRIC_VERSION,
            "dimension_calculation_profile": CALCULATION_PROFILE,
        },
        "limitations": metadata.get("limitations", []),
    }
    if migration is not None and migration_path is not None:
        result["score_migration"] = {
            "schema_version": MIGRATION_SCHEMA,
            "artifact_path": v5.portable_relative_reference(
                migration_path, result_output, label="score_migration.artifact_path"
            ),
            "sha256": v5.sha256_file(migration_path),
            "migration_sha256": migration["migration_sha256"],
        }

    primary_calculation_reference = {
        "schema_version": CALCULATION_SCHEMA,
        "artifact_path": v5.portable_relative_reference(
            calculation_path, web_output, label="score_views.calculation.artifact_path"
        ),
        "sha256": calculation_file_sha,
        "calculation_sha256": calculation["calculation_sha256"],
        "rubric_version": RUBRIC_VERSION,
        "calculation_profile": CALCULATION_PROFILE,
    }
    migration_comparison: dict[str, Any] = {"status": "not_applicable"}
    if migration is not None and migration_path is not None:
        migration_comparison = {
            "status": "v5_to_v6",
            "migration_record": {
                "schema_version": MIGRATION_SCHEMA,
                "artifact_path": v5.portable_relative_reference(
                    migration_path, web_output, label="migration_comparison.artifact_path"
                ),
                "sha256": v5.sha256_file(migration_path),
                "migration_sha256": migration["migration_sha256"],
            },
            "methodology_commit": migration["methodology"]["commit_sha"],
            "previous_total": migration["from"]["total_score"],
            "migrated_total": migration["to"]["total_score"],
            "dimension_comparison": migration["dimension_comparison"],
            "precision_comparison": migration["precision_comparison"],
            "gate_comparison": {
                "previous_outcomes_sha256": migration["gate_preservation"][
                    "historical_gate_outcomes_sha256"
                ],
                "migrated_outcomes_sha256": gate_hash,
                "previous_outcomes": deepcopy(
                    migration["gate_preservation"]["historical_outcomes"]
                ),
                "migrated_outcomes": gates,
                "outcomes_equal": True,
            },
        }
    web_report = {
        "schema_version": WEB_REPORT_SCHEMA,
        "report_id": metadata.get("report_id", f"{calculation['evaluation_id']}-v6"),
        "headline": metadata.get("headline", "Subject-index evaluation"),
        "summary": metadata.get("summary", "V6 source-grounded evaluation."),
        "grade": {
            "score": calculation["total_score"],
            "maximum": 100,
            "label": grade_label(calculation["total_score"]),
        },
        "scorecard": web_scorecard_projection(calculation),
        "calculation_explainer": {
            "artifact_path": v5.portable_relative_reference(
                calculation_path, web_output, label="calculation_explainer.artifact_path"
            ),
            "sha256": calculation_file_sha,
            "rubric_version": RUBRIC_VERSION,
            "calculation_profile": CALCULATION_PROFILE,
            "item_grades_used": False,
            "gates_used": False,
        },
        "precision_diagnostics": precision_diagnostics(calculation),
        "key_metrics": [],
        "density": {},
        "gate_status": {
            "critical_gates": gates,
            "outcomes_sha256": gate_hash,
            "used_in_score_arithmetic": False,
        },
        "strengths": metadata.get("strengths", []),
        "defects": metadata.get("defects", []),
        "examples": metadata.get("examples", []),
        "item_grade_index": {
            "schema_version": ITEM_ASSESSMENT_SCHEMA,
            "artifact_path": v5.portable_relative_reference(
                item_assessments_path, web_output, label="item_grade_index.artifact_path"
            ),
            "sha256": item_file_sha,
            "grading_policy": ITEM_GRADING_POLICY,
            "summary": items["summary"],
            "color_legend": items["color_legend"],
            "interaction": {
                "color_source": "grade.color_token",
                "popover_source": "popover",
                "not_measured_behavior": "neutral_not_failure",
            },
        },
        "migration_comparison": migration_comparison,
        "score_views": {
            "primary_view_id": "canonical_as_delivered",
            "adjustment_status": "none",
            "views": [
                {
                    "view_id": "canonical_as_delivered",
                    "label": "Canonical as delivered",
                    "view_kind": "observed",
                    "score": calculation["total_score"],
                    "maximum": 100,
                    "calculation": primary_calculation_reference,
                    "causal_attribution": "primary_observed_result",
                    "provenance_artifacts": [],
                }
            ],
        },
        "methodology": {
            "rubric_version": RUBRIC_VERSION,
            "weighted_precision_explanation": "Weights unsuccessful destinations by how severely they misdirect the reader.",
            "strict_precision_explanation": "Counts only substantive locator support and remains a separate diagnostic.",
            "weak_presence_selectivity_credit": 0,
        },
        "comparability": {
            "v5_and_v6_directly_comparable": False,
            "reason": "Page-reference Reliability uses a new calculation profile.",
        },
        "disclosures": [
            "A weakly relevant page is not valid substantive index treatment.",
            "Limited reliability credit does not clear defects or publication-readiness gates.",
        ],
        "limitations": metadata.get("limitations", []),
        "evidence_index": {},
    }
    v5.validate_schema_document(result, "evaluation-result-v7.schema.json", "V6 result projection")
    v5.validate_schema_document(web_report, "web-report-v5.schema.json", "V6 web projection")
    return result, web_report


def validate_v5_to_v6_migration_projection(
    calculation: dict[str, Any],
    calculation_path: Path,
    result: dict[str, Any],
    result_path: Path,
    web_report: dict[str, Any],
    web_report_path: Path,
) -> dict[str, Any] | None:
    """Validate the complete migration chain, or reject migration fields on a native run."""

    context = calculation.get("migration_context")
    if context is None:
        v5.require(
            result.get("score_migration") is None
            and web_report.get("migration_comparison") == {"status": "not_applicable"},
            "unexpected_migration_projection",
            "A native V6 calculation cannot claim V5-to-V6 migration provenance.",
        )
        return None

    v5.require(
        isinstance(result.get("score_migration"), dict)
        and web_report.get("migration_comparison", {}).get("status") == "v5_to_v6",
        "migration_projection_required",
        "A migrated V6 calculation requires migration bindings in both projections.",
    )
    result_migration_path = v5.resolve_referenced_artifact(
        result["score_migration"], result_path, label="evaluation_result.score_migration"
    )
    web_migration_reference = web_report["migration_comparison"]["migration_record"]
    web_migration_path = v5.resolve_referenced_artifact(
        web_migration_reference,
        web_report_path,
        label="web_report.migration_comparison.migration_record",
    )
    context_migration_path = v5.resolve_stored_artifact_path(
        context["migration_record_path"],
        calculation_path,
        label="calculation.migration_context.migration_record_path",
    )
    v5.require_same_artifact(
        result_migration_path, web_migration_path, label="V6 result/web migration binding"
    )
    v5.require_same_artifact(
        result_migration_path,
        context_migration_path,
        label="V6 calculation/result migration binding",
    )
    migration = v5.load_json(result_migration_path, "V5-to-V6 migration record")
    v5.validate_schema_document(
        migration, "score-migration-v5-to-v6.schema.json", "V5-to-V6 migration record"
    )
    v5.require(
        migration["migration_sha256"] == v5.canonical_hash(migration, "migration_sha256"),
        "migration_self_hash_mismatch",
        "The V5-to-V6 migration canonical hash does not reconstruct.",
    )
    v5.require(
        result["score_migration"]["migration_sha256"] == migration["migration_sha256"]
        and web_migration_reference["migration_sha256"] == migration["migration_sha256"],
        "migration_projection_mismatch",
        "A projection carries the wrong V5-to-V6 migration identity.",
    )

    new_calculation_ref = migration["to"]["calculation"]
    bound_new_calculation = v5.resolve_stored_artifact_path(
        new_calculation_ref["path"],
        result_migration_path,
        label="migration.to.calculation.path",
    )
    v5.require_same_artifact(
        bound_new_calculation, calculation_path, label="Migration target calculation"
    )
    v5.require(
        new_calculation_ref["sha256"] == v5.sha256_file(calculation_path)
        and new_calculation_ref["calculation_sha256"] == calculation["calculation_sha256"],
        "migration_target_mismatch",
        "The migration record does not bind the exact V6 calculation bytes and identity.",
    )

    historical_refs = {
        "calculation": migration["from"]["calculation"],
        "result": migration["from"]["evaluation_result"],
        "items": migration["from"]["item_assessments"],
        "web_report": migration["from"]["web_report"],
    }
    historical_paths: dict[str, Path] = {}
    for label, reference in historical_refs.items():
        path = v5.resolve_stored_artifact_path(
            reference["path"],
            result_migration_path,
            label=f"migration.from.{label}.path",
        )
        v5.require(
            reference["sha256"] == v5.sha256_file(path),
            "historical_v5_artifact_changed",
            f"The immutable historical V5 {label} bytes changed after migration.",
        )
        historical_paths[label] = path
    old_calculation, old_result, _, old_item_path = validate_historical_v5_projection(
        historical_paths["calculation"],
        historical_paths["result"],
        historical_paths["web_report"],
    )
    v5.require_same_artifact(
        historical_paths["items"], old_item_path, label="Historical V5 item-assessment binding"
    )
    v5.require(
        historical_refs["calculation"]["calculation_sha256"]
        == old_calculation["calculation_sha256"],
        "historical_v5_calculation_identity_mismatch",
        "The migration record carries the wrong historical V5 calculation identity.",
    )
    v5.require(
        context["historical_calculation_sha256"]
        == historical_refs["calculation"]["sha256"]
        and context["historical_result_sha256"] == historical_refs["result"]["sha256"]
        and context["historical_web_report_sha256"]
        == historical_refs["web_report"]["sha256"],
        "migration_context_history_mismatch",
        "The V6 calculation context does not bind the migration's historical artifacts.",
    )
    v5.require(
        migration["frozen_evidence"]["evidence_identity"] == calculation["evidence_identity"]
        == old_calculation["evidence_identity"],
        "migration_evidence_identity_mismatch",
        "Historical and migrated calculations do not bind the same frozen evidence.",
    )
    expected_lineage = [
        {**artifact, "disposition": "unchanged"} for artifact in calculation["input_artifacts"]
    ]
    v5.require(
        migration["frozen_evidence"]["input_lineage"] == expected_lineage,
        "migration_input_lineage_mismatch",
        "The migration input lineage does not reproduce the V6 calculation inputs.",
    )
    historical_gate_hash = v5.canonical_hash(
        {"critical_gates": old_result.get("critical_gates", [])}
    )
    current_gate_hash = v5.canonical_hash({"critical_gates": result["critical_gates"]})
    gate_record = migration["gate_preservation"]
    v5.require(
        historical_gate_hash == current_gate_hash
        == context["historical_gate_outcomes_sha256"]
        == gate_record["historical_gate_outcomes_sha256"]
        == gate_record["preserved_gate_outcomes_sha256"]
        and gate_record["historical_outcomes"] == old_result.get("critical_gates", [])
        and gate_record["preserved_outcomes"] == result["critical_gates"],
        "migration_gate_preservation_mismatch",
        "V5 publication gates were not preserved exactly in V6.",
    )
    comparison = web_report["migration_comparison"]
    v5.require(
        comparison["methodology_commit"] == migration["methodology"]["commit_sha"]
        and comparison["previous_total"] == migration["from"]["total_score"]
        and comparison["migrated_total"] == migration["to"]["total_score"]
        and comparison["dimension_comparison"] == migration["dimension_comparison"]
        and comparison["precision_comparison"] == migration["precision_comparison"]
        and comparison["gate_comparison"]["outcomes_equal"] is True
        and comparison["gate_comparison"]["previous_outcomes_sha256"]
        == historical_gate_hash
        and comparison["gate_comparison"]["migrated_outcomes_sha256"] == current_gate_hash
        and comparison["gate_comparison"]["previous_outcomes"]
        == old_result.get("critical_gates", [])
        and comparison["gate_comparison"]["migrated_outcomes"] == result["critical_gates"],
        "migration_comparison_mismatch",
        "The web migration comparison does not reconstruct from the migration record.",
    )
    return migration


def validate_projection_artifacts(
    calculation_path: Path, result_path: Path, web_report_path: Path
) -> dict[str, Any]:
    calculation = v5.load_json(calculation_path, "V6 calculation")
    result = v5.load_json(result_path, "V6 evaluation result")
    web_report = v5.load_json(web_report_path, "V6 web report")
    v5.validate_schema_document(
        calculation, "dimension-calculations-v2.schema.json", "V6 calculation"
    )
    v5.validate_schema_document(result, "evaluation-result-v7.schema.json", "V6 evaluation result")
    v5.validate_schema_document(web_report, "web-report-v5.schema.json", "V6 web report")
    v5.require(
        calculation.get("calculation_sha256")
        == v5.canonical_hash(calculation, "calculation_sha256"),
        "calculation_self_hash_mismatch",
        "The V6 dimension-calculation canonical hash does not reconstruct.",
    )
    calculation_file_sha = v5.sha256_file(calculation_path)
    v5.require_bound_calculation(
        result["dimension_calculations"],
        result_path,
        calculation_path,
        calculation_file_sha,
        label="evaluation_result.dimension_calculations",
    )
    v5.require_bound_calculation(
        {
            "artifact_path": web_report["calculation_explainer"]["artifact_path"],
            "sha256": web_report["calculation_explainer"]["sha256"],
        },
        web_report_path,
        calculation_path,
        calculation_file_sha,
        label="web_report.calculation_explainer",
    )
    expected_scorecard = scorecard_projection(calculation)
    result_by_id = {item["dimension_id"]: item for item in result["scorecard"]}
    expected_by_id = {item["dimension_id"]: item for item in expected_scorecard}
    for dimension_id in v5.WEIGHTS:
        for field in (
            "weight",
            "rating",
            "unrounded_rating",
            "points",
            "calculation_status",
            "formula_id",
            "applied_cap_id",
        ):
            v5.require(
                result_by_id[dimension_id][field] == expected_by_id[dimension_id][field],
                "projection_mismatch",
                f"Result scorecard {dimension_id}.{field} differs from the V6 calculation.",
            )
    v5.require(
        result["total_score"] == calculation["total_score"],
        "projection_mismatch",
        "Result total differs from the V6 calculation.",
    )
    identity = calculation["evidence_identity"]
    v5.require(
        result["evaluation_id"] == calculation["evaluation_id"]
        and result["candidate"]["sha256"] == identity["candidate_sha256"]
        and result["provenance"]["source_sha256"] == identity["source_sha256"]
        and result["provenance"]["benchmark_sha256"] == identity["benchmark_sha256"]
        and result["provenance"]["judgment_policy_sha256"] == identity["policy_sha256"]
        and result["audit_scope"]["mode"] == calculation["audit_mode"],
        "projection_identity_mismatch",
        "The V6 result does not reproduce the calculation evidence identity.",
    )
    expected_precision = precision_diagnostics(calculation)
    v5.require(
        result["metrics"]["locator_precision"] == expected_precision
        and web_report["precision_diagnostics"] == expected_precision,
        "projection_mismatch",
        "Strict and weighted precision projections do not reconstruct.",
    )
    web_by_id = {item["dimension_id"]: item for item in web_report["scorecard"]}
    expected_web = {item["dimension_id"]: item for item in web_scorecard_projection(calculation)}
    v5.require(
        web_by_id == expected_web,
        "projection_mismatch",
        "Web scorecard does not reconstruct byte-for-value from V6 calculations.",
    )
    gates = result["critical_gates"]
    gate_hash = v5.canonical_hash({"critical_gates": gates})
    v5.require(
        web_report["gate_status"]["critical_gates"] == gates
        and web_report["gate_status"]["outcomes_sha256"] == gate_hash,
        "gate_projection_mismatch",
        "Web gate projection differs from the V6 result.",
    )
    result_item_path = v5.resolve_referenced_artifact(
        result["item_assessments"], result_path, label="evaluation_result.item_assessments"
    )
    web_item_path = v5.resolve_referenced_artifact(
        web_report["item_grade_index"], web_report_path, label="web_report.item_grade_index"
    )
    v5.require_same_artifact(
        result_item_path, web_item_path, label="V6 result and web item-assessment binding"
    )
    items = v5.load_json(result_item_path, "V6 item assessments")
    v5.validate_schema_document(items, "item-assessments-v3.schema.json", "V6 item assessments")
    v5.require(
        items["evidence_identity"] == calculation["evidence_identity"],
        "projection_identity_mismatch",
        "V6 item-assessment evidence identity differs from calculations.",
    )
    for locator in items["locator_assessments"]:
        if locator["grade"]["score"] == 25:
            summary = locator["popover"]["summary"].lower()
            for phrase in (
                "only weakly",
                "not substantive index treatment",
                "editorially unjustified",
                "wholly false destination",
            ):
                v5.require(
                    phrase in summary,
                    "weak_presence_popover_incomplete",
                    f"Grade-25 locator popover must explain: {phrase}.",
                    {"locator_id": locator["locator_id"]},
                )
    migration = validate_v5_to_v6_migration_projection(
        calculation,
        calculation_path,
        result,
        result_path,
        web_report,
        web_report_path,
    )
    return {
        "ok": True,
        "evaluation_id": calculation["evaluation_id"],
        "calculation_file_sha256": calculation_file_sha,
        "calculation_sha256": calculation["calculation_sha256"],
        "result_file_sha256": v5.sha256_file(result_path),
        "web_report_file_sha256": v5.sha256_file(web_report_path),
        "item_assessments_file_sha256": v5.sha256_file(result_item_path),
        "strict_precision_reported": True,
        "weighted_precision_reported": True,
        "gate_projection_unchanged": True,
        "migration_validated": migration is not None,
    }


def command_build_projections(args: argparse.Namespace) -> None:
    try:
        result_output = Path(args.evaluation_result_output).resolve()
        web_output = Path(args.web_report_output).resolve()
        result, web_report = build_projections(
            Path(args.calculation).resolve(),
            Path(args.item_assessments).resolve(),
            Path(args.metadata).resolve(),
            result_output,
            web_output,
            Path(args.migration_record).resolve() if args.migration_record else None,
        )
        protected = {
            Path(args.calculation).resolve(),
            Path(args.item_assessments).resolve(),
            Path(args.metadata).resolve(),
        }
        if args.migration_record:
            protected.add(Path(args.migration_record).resolve())
        v5.require(
            not v5.aliases_existing_file(result_output, protected)
            and not v5.aliases_existing_file(web_output, protected),
            "output_aliases_frozen_input",
            "Projection outputs must not overwrite a bound artifact.",
        )
        v5.require(
            result_output != web_output,
            "output_path_collision",
            "Evaluation result and web report outputs must differ.",
        )
        write_json(result_output, result)
        write_json(web_output, web_report)
        validation = validate_projection_artifacts(
            Path(args.calculation).resolve(), result_output, web_output
        )
        v5.emit(
            {
                "command": "build-v6-projections",
                "ok": True,
                "evaluation_id": result["evaluation_id"],
                "artifacts_written": [str(result_output), str(web_output)],
                "validation": validation,
            }
        )
    except (OSError, v5.CalculationError) as exc:
        error = (
            {"code": exc.code, "message": exc.message, "details": exc.details}
            if isinstance(exc, v5.CalculationError)
            else {"code": "file_error", "message": str(exc)}
        )
        v5.emit({"command": "build-v6-projections", "ok": False, "error": error}, 1)


def command_validate_projections(args: argparse.Namespace) -> None:
    try:
        result = validate_projection_artifacts(
            Path(args.calculation).resolve(),
            Path(args.evaluation_result).resolve(),
            Path(args.web_report).resolve(),
        )
        v5.emit({"command": "validate-v6-projections", **result})
    except (OSError, v5.CalculationError) as exc:
        error = (
            {"code": exc.code, "message": exc.message, "details": exc.details}
            if isinstance(exc, v5.CalculationError)
            else {"code": "file_error", "message": str(exc)}
        )
        v5.emit({"command": "validate-v6-projections", "ok": False, "error": error}, 1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    preflight = subparsers.add_parser(
        "preflight", help="Report exact V6 calculation sufficiency without changing evidence."
    )
    preflight.add_argument("--input", required=True)
    preflight.add_argument("--output")
    preflight.set_defaults(func=command_preflight)

    calculate = subparsers.add_parser(
        "calculate", help="Derive all six V6 ratings from validated frozen ledgers."
    )
    calculate.add_argument("--input", required=True)
    calculate.add_argument("--output")
    calculate.set_defaults(func=command_calculate)

    migration_preflight_parser = subparsers.add_parser(
        "migration-preflight", help="Verify a V5 evaluation can be migrated without reopening evidence."
    )
    migration_preflight_parser.add_argument("--input", required=True)
    migration_preflight_parser.add_argument("--historical-calculation", required=True)
    migration_preflight_parser.add_argument("--historical-result", required=True)
    migration_preflight_parser.add_argument("--historical-web-report", required=True)
    migration_preflight_parser.add_argument("--output")
    migration_preflight_parser.set_defaults(func=command_migration_preflight)

    migrate = subparsers.add_parser(
        "score-only-migration", help="Preserve V5 history and emit V6 calculations plus provenance."
    )
    migrate.add_argument("--input", required=True)
    migrate.add_argument("--historical-calculation", required=True)
    migrate.add_argument("--historical-result", required=True)
    migrate.add_argument("--historical-web-report", required=True)
    migrate.add_argument("--calculations-output", required=True)
    migrate.add_argument("--migration-record-output", required=True)
    migrate.add_argument("--methodology-commit", required=True)
    migrate.add_argument("--migration-timestamp", required=True)
    migrate.set_defaults(func=command_migrate)

    projections = subparsers.add_parser(
        "build-projections", help="Build V6 evaluation-result and web-report projections."
    )
    projections.add_argument("--calculation", required=True)
    projections.add_argument("--item-assessments", required=True)
    projections.add_argument("--metadata", required=True)
    projections.add_argument("--migration-record")
    projections.add_argument("--evaluation-result-output", required=True)
    projections.add_argument("--web-report-output", required=True)
    projections.set_defaults(func=command_build_projections)

    validate = subparsers.add_parser(
        "validate-projections", help="Reconstruct V6 result and web-report values from provenance."
    )
    validate.add_argument("--calculation", required=True)
    validate.add_argument("--evaluation-result", required=True)
    validate.add_argument("--web-report", required=True)
    validate.set_defaults(func=command_validate_projections)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
