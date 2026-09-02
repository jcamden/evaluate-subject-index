#!/usr/bin/env python3
"""Deterministic current V7 scoring and projection tooling.

V7 changes only the per-locator precision input to Page-reference Reliability.
It derives independent page-treatment and complete-path-fit ceilings from frozen
structured evidence, combines them with ``min(T, F)``, and preserves every V6
non-reliability formula, cap, gate, recall rule, and rounding rule.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import scoring_core as v5
from locator_utility import (
    FIT_SCORES,
    LEGACY_FIT_COMPATIBILITY_RULE_ID,
    LEGACY_FIT_CONFLICT_REASON_CODE,
    LEGACY_FIT_CONFLICT_RULE_ID,
    TREATMENT_SCORES,
    UNRESOLVED_REASON_MESSAGES,
    assign_locator_utility,
    combined_state_errors,
    historical_locator_fit_defects,
    locator_fit_state_analysis,
    not_measured_assignment,
    relevant_structured_defects,
)
from structure_locator_review import (
    StructureReviewError,
    apply_deterministic_structure_corrections,
    canonical_hash as structure_review_hash,
    derive_structure_locator_review,
    validate_structure_locator_review_semantics,
)


RUBRIC_VERSION = "subject-index-rubric-v7"
CALCULATION_PROFILE = "subject-index-dimension-calculation-v3"
CALCULATION_SCHEMA = "subject-index-dimension-calculations-v4"
ITEM_GRADING_POLICY = "subject-index-item-grading-v3"
SUPPLEMENTAL_ARCHITECTURE_REVIEW_SCHEMA = (
    "subject-index-v7-architecture-review-supplement-v1"
)

ZERO = Decimal(0)
ONE = Decimal(1)
TWO = Decimal(2)
FIVE = Decimal(5)

write_json = v5.write_json


def _mapping_failure(locator: Mapping[str, Any], errors: Iterable[str]) -> dict[str, Any]:
    return {
        "code": "inconsistent_or_incomplete_locator_utility_state",
        "path": f"locator:{locator.get('locator_id', '<missing>')}",
        "message": "V7 requires an unambiguous structured treatment and complete-path-fit mapping.",
        "locator_id": locator.get("locator_id"),
        "path_id": locator.get("path_id"),
        "frozen_state": {
            field: deepcopy(locator.get(field))
            for field in (
                "judgment",
                "treatment_class",
                "source_scope_status",
                "error_codes",
                "severity",
            )
        },
        "state_errors": sorted(set(str(error) for error in errors)),
        "prose_inference_permitted": False,
    }


def _unresolved_fit_record(
    locator: Mapping[str, Any],
    analysis: Mapping[str, Any],
    defects: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    locator_id = str(locator["locator_id"])
    relevant_defects = relevant_structured_defects(locator_id, defects)
    defect_ids = sorted(
        {
            *(
                str(item["defect_id"])
                for item in relevant_defects
            ),
            *analysis["applicable_legacy_defect_ids"],
        }
    )
    reason_codes = list(analysis["unresolved_reason_codes"])
    result = {
        "locator_id": locator_id,
        "path_id": locator.get("path_id"),
        "reason_code": reason_codes[0]
        if len(reason_codes) == 1
        else "multiple_fit_classifiers_possible",
        "reason_codes": reason_codes,
        "present_judgment": locator.get("judgment"),
        "treatment_class": locator.get("treatment_class"),
        "source_scope_status": locator.get("source_scope_status"),
        "structured_codes": sorted(
            {
                *locator.get("error_codes", []),
                *(
                    str(item["code"])
                    for item in relevant_defects
                    if isinstance(item.get("code"), str)
                ),
            }
        ),
        "applicable_structured_defect_ids": defect_ids,
        "missing_classifier_category": "complete_path_fit_category",
        "prose_inference_permitted": False,
    }
    if analysis.get("fit_conflict") is not None:
        conflict = deepcopy(analysis["fit_conflict"])
        result.update(conflict)
        result["reason_code"] = LEGACY_FIT_CONFLICT_REASON_CODE
        result["reason_codes"] = [LEGACY_FIT_CONFLICT_REASON_CODE]
    return result


def _deterministic_fit_record(
    locator: Mapping[str, Any], assignment: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "locator_id": assignment["locator_id"],
        "path_id": locator.get("path_id"),
        "fit_category": assignment["fit_category"],
        "fit_classification_source": assignment["fit_classification_source"],
        "compatibility_rule_ids": deepcopy(
            assignment["compatibility_rule_ids"]
        ),
        "prose_inference_used": False,
    }


def _locator_path_identity_errors(
    ledgers: Mapping[str, Any],
    candidate: Mapping[str, Any] | None,
    inventory: Mapping[str, Any] | None,
) -> dict[str, list[str]]:
    """Reject cross-artifact locator/path identity drift before set hashing."""

    if candidate is None or inventory is None:
        return {}

    candidate_paths_by_locator: dict[str, set[str]] = {}
    candidate_path_counts: Counter[str] = Counter()
    for record in candidate.get("records", []):
        if not isinstance(record, Mapping):
            continue
        path_id = record.get("path_id")
        if not isinstance(path_id, str):
            continue
        candidate_path_counts[path_id] += 1
        for assignment in record.get("locator_assignments", []):
            if not isinstance(assignment, Mapping):
                continue
            locator_id = assignment.get("locator_id")
            if isinstance(locator_id, str):
                candidate_paths_by_locator.setdefault(locator_id, set()).add(
                    path_id
                )

    inventory_paths_by_locator: dict[str, set[str]] = {}
    for locator in inventory.get("locators", []):
        if not isinstance(locator, Mapping):
            continue
        locator_id = locator.get("locator_id")
        path_id = locator.get("path_id")
        if isinstance(locator_id, str) and isinstance(path_id, str):
            inventory_paths_by_locator.setdefault(locator_id, set()).add(path_id)
    inventory_path_counts = Counter(
        item.get("path_id")
        for item in inventory.get("paths", [])
        if isinstance(item, Mapping) and isinstance(item.get("path_id"), str)
    )

    errors: dict[str, list[str]] = {}
    for locator in ledgers["locators"]:
        locator_id = locator.get("locator_id")
        path_id = locator.get("path_id")
        if not isinstance(locator_id, str):
            continue
        locator_errors: list[str] = []
        if not isinstance(path_id, str) or not path_id.startswith("PATH-"):
            locator_errors.append("invalid:complete_path_identity")
        else:
            if candidate_paths_by_locator.get(locator_id) != {path_id}:
                locator_errors.append(
                    "inconsistent:normalized_candidate_locator_path_identity"
                )
            if inventory_paths_by_locator.get(locator_id) != {path_id}:
                locator_errors.append(
                    "inconsistent:item_inventory_locator_path_identity"
                )
            if candidate_path_counts[path_id] != 1:
                locator_errors.append(
                    "inconsistent:normalized_candidate_complete_path_identity"
                )
            if inventory_path_counts[path_id] != 1:
                locator_errors.append(
                    "inconsistent:item_inventory_complete_path_identity"
                )
        if locator_errors:
            errors[locator_id] = sorted(set(locator_errors))
    return errors


def locator_fit_preflight(
    ledgers: dict[str, Any],
    audit_mode: str,
    *,
    legacy_defects: Iterable[Mapping[str, Any]] = (),
    candidate: Mapping[str, Any] | None = None,
    inventory: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return deterministic unsupplemented fit compatibility and unresolved sets."""

    legacy_defects = list(legacy_defects)
    invalid: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    deterministic: list[dict[str, Any]] = []
    compatibility: list[dict[str, Any]] = []
    path_identity_errors = _locator_path_identity_errors(
        ledgers, candidate, inventory
    )
    for locator in sorted(
        ledgers["locators"], key=lambda item: str(item.get("locator_id", ""))
    ):
        locator_id = locator.get("locator_id")
        if isinstance(locator_id, str) and locator_id in path_identity_errors:
            invalid.append(
                _mapping_failure(locator, path_identity_errors[locator_id])
            )
            continue
        analysis = locator_fit_state_analysis(
            locator, ledgers["defects"], legacy_defects
        )
        if analysis["hard_errors"]:
            invalid.append(_mapping_failure(locator, analysis["hard_errors"]))
            continue
        if analysis["unresolved_reason_codes"]:
            unresolved.append(
                _unresolved_fit_record(
                    locator,
                    analysis,
                    [*ledgers["defects"], *legacy_defects],
                )
            )
            continue
        try:
            assignment = assign_locator_utility(
                locator, ledgers["defects"], legacy_defects
            ).as_dict()
        except ValueError as exc:
            invalid.append(_mapping_failure(locator, str(exc).split(";")))
            continue
        deterministic.append(_deterministic_fit_record(locator, assignment))
        if assignment["fit_classification_source"] == "legacy_code_severity_compatibility":
            compatibility.append(
                {
                    "locator_id": assignment["locator_id"],
                    "path_id": locator.get("path_id"),
                    "compatibility_rule_id": assignment[
                        "compatibility_rule_ids"
                    ][0],
                    "fit_category": assignment["fit_category"],
                    "fit_rule_id": assignment["fit_rule_id"],
                    "applicable_structured_defect_ids": assignment[
                        "applicable_structured_defect_ids"
                    ],
                    "prose_inference_used": False,
                }
            )
    if audit_mode == "full" and ledgers["locator_not_measured"]:
        invalid.append(
            {
                "code": "required_locator_not_measured",
                "path": "locator_not_measured",
                "message": "Full V7 scoring requires every frozen locator assignment to be measured.",
                "locator_ids": sorted(ledgers["locator_not_measured"]),
                "prose_inference_permitted": False,
            }
        )
    unresolved_reason_counts = dict(
        sorted(
            Counter(
                reason
                for item in unresolved
                for reason in item["reason_codes"]
            ).items()
        )
    )
    deterministic_ids = {item["locator_id"] for item in deterministic}
    unresolved_ids = {item["locator_id"] for item in unresolved}
    invalid_ids = {
        item["locator_id"]
        for item in invalid
        if isinstance(item.get("locator_id"), str)
    }
    v5.require(
        not (deterministic_ids & unresolved_ids)
        and not (deterministic_ids & invalid_ids)
        and not (unresolved_ids & invalid_ids),
        "locator_fit_preflight_group_overlap",
        "Each frozen locator record must appear in exactly one V7 fit-preflight group.",
    )
    locator_invalid_count = sum(
        item.get("code") == "inconsistent_or_incomplete_locator_utility_state"
        for item in invalid
    )
    v5.require(
        len(deterministic) + len(unresolved) + locator_invalid_count
        == len(ledgers["locators"]),
        "locator_fit_preflight_group_coverage_invalid",
        "Every frozen locator record must appear exactly once in a V7 fit-preflight group.",
    )
    return {
        "schema_version": "subject-index-v7-locator-fit-preflight-v1",
        "deterministically_compatible": deterministic,
        "unresolved_complete_path_fit": unresolved,
        "invalid_or_contradictory_state": invalid,
        "compatibility_classifications": compatibility,
        "group_counts": {
            "deterministically_compatible": len(deterministic),
            "unresolved_complete_path_fit": len(unresolved),
            "invalid_or_contradictory_state": len(invalid),
        },
        "unresolved_reason_counts": unresolved_reason_counts,
        "unresolved_set_sha256": v5.canonical_hash(
            {"unresolved_locator_fit": unresolved}
        ),
        "aggregate_v7_score_available": False,
        "prose_inference_used": False,
        "historical_artifacts_modified": False,
        "_locator_records_by_id": {
            item["locator_id"]: item for item in ledgers["locators"]
        },
    }


def public_locator_fit_preflight(report: Mapping[str, Any]) -> dict[str, Any]:
    """Return the strict public contract without in-memory locator objects."""

    return {
        key: deepcopy(value)
        for key, value in report.items()
        if not key.startswith("_")
    }


def locator_state_requirements(
    ledgers: dict[str, Any],
    audit_mode: str,
    *,
    legacy_defects: Iterable[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    """Return precise V7 mapping failures without consulting prose."""

    report = locator_fit_preflight(
        ledgers, audit_mode, legacy_defects=legacy_defects
    )
    unresolved = [
        {
            "code": "unresolved_complete_path_fit",
            "path": f"locator:{item['locator_id']}",
            "message": "; ".join(
                UNRESOLVED_REASON_MESSAGES[reason]
                for reason in item["reason_codes"]
            ),
            **item,
        }
        for item in report["unresolved_complete_path_fit"]
    ]
    return [*report["invalid_or_contradictory_state"], *unresolved]


def raw_locator_state_requirements(
    config_path: Path,
) -> tuple[str | None, list[dict[str, Any]], list[Path]]:
    """Pre-scan raw audits for actionable V7 field and mapping failures."""

    try:
        config = v5.load_json(config_path, "V7 calculation input")
    except (OSError, v5.CalculationError):
        return None, [], []
    references = config.get("inputs", {}).get("locator_audits", [])
    if not isinstance(references, list):
        return config.get("evaluation_id"), [], []
    failures: list[dict[str, Any]] = []
    paths: list[Path] = []
    for batch_index, reference in enumerate(references):
        stored = reference.get("path") if isinstance(reference, dict) else None
        if not isinstance(stored, str) or not stored:
            continue
        path = (config_path.parent / stored).resolve()
        paths.append(path)
        try:
            document = v5.load_json(path, f"Raw locator audit {batch_index}")
        except (OSError, v5.CalculationError):
            continue
        judgments = document.get("judgments")
        if not isinstance(judgments, list):
            failures.append(
                {
                    "code": "missing_locator_judgment_collection",
                    "path": f"locator_audit[{batch_index}].judgments",
                        "message": "V7 scoring requires the frozen locator judgment array.",
                    "state_errors": ["missing:judgments"],
                }
            )
            continue
        for judgment_index, locator in enumerate(judgments):
            if not isinstance(locator, dict):
                failures.append(
                    {
                        "code": "invalid_locator_record",
                        "path": f"locator_audit[{batch_index}].judgments[{judgment_index}]",
                        "message": "V7 requires an object for every locator judgment.",
                        "state_errors": ["invalid:locator_record"],
                    }
                )
                continue
            required = {
                "locator_id",
                "judgment",
                "treatment_class",
                "source_scope_status",
                "error_codes",
                "severity",
            }
            absent = sorted(required - set(locator))
            if absent:
                failures.append(
                    _mapping_failure(locator, [f"missing:{field}" for field in absent])
                    | {"path": f"locator_audit[{batch_index}].judgments[{judgment_index}]"}
                )
    return config.get("evaluation_id"), failures, paths


def load_v7_inputs(config_path: Path) -> dict[str, Any]:
    """Load the native V7 V5 structure contract.

    The V5 scorer is reused as an unchanged arithmetic engine.  For a native
    ``structure-audit-v5`` document, only its in-memory schema tag is projected
    to V4 for that engine; the exact V5 bytes and artifact identity remain the
    bound input, and the explicit V7 architecture decisions remain present.
    """

    config = v5.load_json(config_path, "Dimension calculation input")
    v5.validate_config_shape(config)
    v5.validate_schema_document(
        config,
        "dimension-calculation-input.schema.json",
        "Dimension calculation input",
    )
    structure_ref = config["inputs"]["structure_audit"]
    structure_path, structure_document, structure_artifact = v5.resolve_input(
        config_path, structure_ref, "structure_audit"
    )
    v5.require(
        structure_document.get("schema_version") == "structure-audit-v5",
        "unsupported_structure_audit_schema",
        "Current V7 scoring requires structure-audit-v5.",
    )
    v5.validate_schema_document(
        structure_document, "structure-audit-v5.schema.json", "structure_audit"
    )
    runtime_structure = deepcopy(structure_document)
    runtime_structure["schema_version"] = "structure-audit-v4"
    inputs = config["inputs"]
    locator_entries: list[tuple[dict[str, Any], dict[str, Any], Path]] = []
    missing_entries: list[tuple[dict[str, Any], dict[str, Any], Path]] = []
    for index, record in enumerate(inputs["locator_audits"]):
        path, document, artifact = v5.resolve_input(
            config_path, record, f"locator_audit[{index}]"
        )
        v5.validate_schema_document(
            document, "locator-audit-v2.schema.json", f"locator_audit[{index}]"
        )
        locator_entries.append((document, artifact, path))
    for index, record in enumerate(inputs["missing_access_audits"]):
        path, document, artifact = v5.resolve_input(
            config_path, record, f"missing_access_audit[{index}]"
        )
        v5.validate_schema_document(
            document,
            "missing-access-audit.schema.json",
            f"missing_access_audit[{index}]",
        )
        missing_entries.append((document, artifact, path))
    locator_entries.sort(key=lambda item: str(item[0].get("chunk_id", "")))
    missing_entries.sort(key=lambda item: str(item[0].get("chunk_id", "")))
    artifacts: list[dict[str, Any]] = []
    paths: list[Path] = []
    for prefix, entries in (
        ("locator_audit", locator_entries),
        ("missing_access_audit", missing_entries),
    ):
        for index, (_, artifact, path) in enumerate(entries):
            artifact["role"] = f"{prefix}[{index}]"
            artifacts.append(artifact)
            paths.append(path)
    artifacts.append(structure_artifact)
    paths.append(structure_path)
    chunk_manifest = None
    if "chunk_manifest" in inputs:
        chunk_path, chunk_manifest, chunk_artifact = v5.resolve_input(
            config_path, inputs["chunk_manifest"], "chunk_manifest"
        )
        v5.validate_schema_document(
            chunk_manifest, "chunk-manifest.schema.json", "chunk_manifest"
        )
        v5.require(
            chunk_manifest.get("chunk_manifest_sha256")
            == v5.canonical_hash(chunk_manifest, "chunk_manifest_sha256"),
            "chunk_manifest_self_hash_mismatch",
            "The canonical chunk manifest self-hash does not reconstruct.",
        )
        artifacts.append(chunk_artifact)
        paths.append(chunk_path)
    v5.require(
        "migration_supplement" not in inputs,
        "unexpected_migration_supplement",
        "A native structure-audit-v5 calculation cannot use a V5 historical migration supplement.",
    )
    return {
        "config": config,
        "locator_documents": [item[0] for item in locator_entries],
        "missing_documents": [item[0] for item in missing_entries],
        "structure": runtime_structure,
        "frozen_structure": structure_document,
        "chunk_manifest": chunk_manifest,
        "supplement": None,
        "input_artifacts": artifacts,
        "input_paths": paths,
        "config_path": config_path,
    }


def preflight_loaded(
    loaded: dict[str, Any]
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    ledgers, missing = v5.preflight_loaded(loaded)
    if ledgers is None:
        return None, missing
    missing = [
        *missing,
        *locator_state_requirements(
            ledgers,
            loaded["config"]["audit_mode"],
        ),
    ]
    return (ledgers if not missing else None), missing


def utility_assignments(
    ledgers: dict[str, Any],
    *,
    legacy_defects: Iterable[Mapping[str, Any]] = (),
    supplemental_decisions: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    assignments: list[dict[str, Any]] = []
    legacy_defects = list(legacy_defects)
    supplemental_decisions = supplemental_decisions or {}
    for locator in sorted(ledgers["locators"], key=lambda item: item["locator_id"]):
        try:
            assignment = assign_locator_utility(
                locator,
                ledgers["defects"],
                legacy_defects,
                supplemental_decisions.get(locator["locator_id"]),
            )
        except ValueError as exc:
            raise v5.CalculationError(
                "inconsistent_locator_utility_state",
                f"Locator {locator.get('locator_id')} cannot receive a V7 two-axis credit.",
                _mapping_failure(locator, str(exc).split(";")),
            ) from exc
        assignments.append(assignment.as_dict())
    assignments.extend(
        not_measured_assignment(locator_id)
        for locator_id in sorted(ledgers["locator_not_measured"])
    )
    return sorted(assignments, key=lambda item: item["locator_id"])


def _complete_counts(values: Iterable[str], keys: Sequence[str]) -> dict[str, int]:
    counts = Counter(values)
    return {key: counts.get(key, 0) for key in keys}


def _uncertainty_triple(
    numerator: Decimal,
    assessed: int,
    unknown: int,
) -> dict[str, str]:
    denominator = assessed + unknown
    central = numerator / Decimal(assessed) if assessed else ZERO
    lower = numerator / Decimal(denominator) if denominator else ZERO
    upper = (numerator + Decimal(unknown)) / Decimal(denominator) if denominator else ZERO
    return {
        "lower": v5.decimal_text(lower),
        "central": v5.decimal_text(central),
        "upper": v5.decimal_text(upper),
    }


def calculate_reliability(
    ledgers: dict[str, Any],
    audit_mode: str,
    *,
    legacy_defects: Iterable[Mapping[str, Any]] = (),
    supplemental_decisions: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    assignments = utility_assignments(
        ledgers,
        legacy_defects=legacy_defects,
        supplemental_decisions=supplemental_decisions,
    )
    by_id = {item["locator_id"]: item for item in assignments}
    measured_locators = [
        item for item in ledgers["locators"] if item.get("judgment") in {"supported", "partially_supported", "unsupported"}
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

    assessed_assignments = [by_id[item["locator_id"]] for item in measured_locators]
    weighted_numerator = sum(
        (v5.decimal_value(item["combined_credit"]) for item in assessed_assignments), ZERO
    )
    treatment_numerator = sum(
        (v5.decimal_value(item["treatment_score"]) for item in assessed_assignments), ZERO
    )
    fit_numerator = sum(
        (v5.decimal_value(item["fit_score"]) for item in assessed_assignments), ZERO
    )
    supported = sum(item["judgment"] == "supported" for item in measured_locators)
    found = sum(item["status"] == "found" for item in measured_treatments)
    assessable = len(measured_locators)
    pw = weighted_numerator / Decimal(assessable) if assessable else ZERO
    mean_treatment = treatment_numerator / Decimal(assessable) if assessable else ZERO
    mean_fit = fit_numerator / Decimal(assessable) if assessable else ZERO
    strict_precision = v5.rate(supported, assessable)
    recall = v5.rate(found, len(measured_treatments))

    unknown_loc = len(uninspectable_locators) + len(locator_not_measured)
    unknown_treat = len(uninspectable_treatments) + len(treatment_not_measured)
    locator_bound_denominator = assessable + unknown_loc
    pw_lower = weighted_numerator / Decimal(locator_bound_denominator) if locator_bound_denominator else ZERO
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
        item for item in measured_treatments if item.get("locator_class") in {"principal", "synthesis_or_conclusion"}
    ]
    high_unknown = [
        item for item in uninspectable_treatments if item.get("locator_class") in {"principal", "synthesis_or_conclusion"}
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
    # Preserve the exact V6 cap trigger; V7 changes credit, not gate/cap evidence.
    pattern = [
        item
        for item in measured_locators
        if item.get("judgment") == "unsupported"
        and set(item.get("error_codes", [])) & v5.RELIABILITY_CODES
    ]
    pattern_units = {item.get("_source_unit_id") for item in pattern if item.get("_source_unit_id")}
    unknown_locator_units = {
        item.get("_source_unit_id") for item in uninspectable_locators if item.get("_source_unit_id")
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
                {"severity": "critical", "defect_kinds": ["fabricated_locator", "nonexistent_locator", "out_of_scope_locator"]},
                {"defect_count": len(critical)},
                [item["defect_id"] for item in critical],
            ),
            v5.cap_record(
                "reliability.high_value_treatment_recall",
                high_max,
                high_triggered,
                {"table": "pooled_principal_and_synthesis_recall_v1", "band": high_band},
                {"found": high_found_value, "expected": high_total, "rate": v5.decimal_text(v5.rate(high_found_value, high_total))},
                high_miss_evidence,
            ),
            v5.cap_record(
                "reliability.distributed_unsupported_pattern",
                pattern_max,
                pattern_triggered,
                {"minimum_source_unit_rate": "0.25", "rate_table": "reliability_owned_unsupported_v1", "band": pattern_band},
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

    known_high_misses = [item["treatment_id"] for item in high_measured if item["status"] == "missed"]
    known_pattern_ids = [item["locator_id"] for item in pattern]
    central_caps = caps(high_found, len(high_measured), len(pattern), assessable, len(pattern_units), known_high_misses, known_pattern_ids)
    lower_caps = caps(
        high_found,
        len(high_measured) + len(high_unknown) + len(high_not_measured_ids),
        len(pattern) + unknown_loc,
        assessable + unknown_loc,
        len(pattern_units | unknown_locator_units),
        known_high_misses + [item["treatment_id"] for item in high_unknown] + high_not_measured_ids,
        known_pattern_ids + [item["locator_id"] for item in uninspectable_locators] + locator_not_measured,
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
    result["input_roles"] = ["locator_audit", "missing_access_audit", "structure_audit_or_migration_supplement"]

    treatment_tiers = ("substantive", "mixed", "weak_presence", "absent", "invalid_destination", "uninspectable", "not_measured")
    fit_tiers = ("exact_fit", "material_partial_fit", "material_mismatch", "severe_mismatch", "no_fit", "uninspectable", "not_measured")
    combined_values = ("1", "0.7", "0.35", "0.25", "0.15", "0", "uninspectable", "not_measured")

    def combined_count_key(item: dict[str, Any]) -> str:
        if item["disposition"] == "bounded":
            return "uninspectable"
        if item["disposition"] == "not_measured":
            return "not_measured"
        return str(item["combined_credit"])

    treatment_counts = _complete_counts((item["treatment_category"] for item in assignments), treatment_tiers)
    fit_counts = _complete_counts((item["fit_category"] for item in assignments), fit_tiers)
    combined_counts = _complete_counts((combined_count_key(item) for item in assignments), combined_values)
    result["raw_status_counts"] = {
        "locator_support": dict(Counter(item["judgment"] for item in ledgers["locators"])),
        "locator_treatment_class": dict(Counter(item.get("treatment_class") for item in ledgers["locators"])),
        "treatment_tier": treatment_counts,
        "fit_tier": fit_counts,
        "combined_credit": combined_counts,
        "treatment_recall": dict(Counter(item.get("status") or "not_measured" for item in ledgers["treatments"])),
        "not_measured_locators": len(locator_not_measured),
        "not_measured_treatments": len(treatment_not_measured),
    }
    result["credit_mappings"] = {
        "page_treatment": {key: v5.decimal_text(value) for key, value in TREATMENT_SCORES.items()} | {"uninspectable": "neutral_uncertainty_bounds"},
        "complete_path_fit": {key: v5.decimal_text(value) for key, value in FIT_SCORES.items()} | {"uninspectable": "neutral_uncertainty_bounds"},
        "combination": {"rule": "minimum", "formula": "L_j=min(T_j,F_j)"},
        "strict_substantive_precision": {"supported": "1", "partially_supported": "0", "unsupported": "0"},
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
            "component_id": "page_treatment_axis_diagnostic",
            "raw_numerator": v5.decimal_text(treatment_numerator),
            "raw_denominator": v5.decimal_text(Decimal(assessable)),
            "normalized_value": v5.decimal_text(mean_treatment),
            "weight": "reported_diagnostic_only",
            "effective_weight": "not_used_independently_in_dimension_arithmetic",
            "weight_renormalized": False,
        },
        {
            "component_id": "complete_path_fit_axis_diagnostic",
            "raw_numerator": v5.decimal_text(fit_numerator),
            "raw_denominator": v5.decimal_text(Decimal(assessable)),
            "normalized_value": v5.decimal_text(mean_fit),
            "weight": "reported_diagnostic_only",
            "effective_weight": "not_used_independently_in_dimension_arithmetic",
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
        "model": "two_axis_independent_ceilings_minimum_v1",
        "original_locator_denominator": ledgers["locator_original"],
        "assessable_locator_denominator": assessable,
        "uninspectable_locator_count": len(uninspectable_locators),
        "not_measured_locator_count": len(locator_not_measured),
        "counts_by_judgment": _complete_counts(
            (item.get("judgment") for item in ledgers["locators"]),
            ("supported", "partially_supported", "unsupported", "uninspectable"),
        ) | {"not_measured": len(locator_not_measured)},
        "counts_by_treatment_class": dict(sorted(Counter(item.get("treatment_class") for item in ledgers["locators"]).items())) | ({"not_measured": len(locator_not_measured)} if locator_not_measured else {}),
        "counts_by_treatment_tier": treatment_counts,
        "counts_by_fit_tier": fit_counts,
        "counts_by_combined_credit_value": combined_counts,
        "locator_utility_assignments": assignments,
        "mapping_rejections": [],
        "compatibility_classifications": [
            {
                "locator_id": item["locator_id"],
                "fit_category": item["fit_category"],
                "fit_rule_id": item["fit_rule_id"],
                "compatibility_rule_ids": item["compatibility_rule_ids"],
                "applicable_structured_defect_ids": item[
                    "applicable_structured_defect_ids"
                ],
            }
            for item in assignments
            if item["compatibility_rule_ids"]
        ],
        "supplemental_fit_decision_count": sum(
            item["supplemental_fit_decision_id"] is not None
            for item in assignments
        ),
        "treatment_score_numerator": v5.decimal_text(treatment_numerator),
        "treatment_score_denominator": assessable,
        "mean_treatment_score": v5.decimal_text(mean_treatment),
        "fit_score_numerator": v5.decimal_text(fit_numerator),
        "fit_score_denominator": assessable,
        "mean_fit_score": v5.decimal_text(mean_fit),
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
        "treatment_score_uncertainty": _uncertainty_triple(treatment_numerator, assessable, unknown_loc),
        "fit_score_uncertainty": _uncertainty_triple(fit_numerator, assessable, unknown_loc),
        "strict_precision_uncertainty": {"lower": v5.decimal_text(strict_lower), "central": v5.decimal_text(strict_precision), "upper": v5.decimal_text(strict_upper)},
        "weighted_precision_uncertainty": {"lower": v5.decimal_text(pw_lower), "central": v5.decimal_text(pw), "upper": v5.decimal_text(pw_upper)},
        "treatment_recall_uncertainty": {"lower": v5.decimal_text(recall_lower), "central": v5.decimal_text(recall), "upper": v5.decimal_text(recall_upper)},
        "calculation_credit_source": "locator_utility_assignments[].combined_credit",
        "diagnostic_grade_formula": "100 * combined_credit",
        "diagnostic_grades_used_in_dimension_arithmetic": False,
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


def calculate_loaded(
    loaded: dict[str, Any],
    *,
    structure_review: dict[str, Any] | None = None,
    structure_review_artifact: dict[str, Any] | None = None,
    supplemental_architecture_review_artifact: dict[str, Any] | None = None,
    legacy_fit_defects: Iterable[Mapping[str, Any]] | None = None,
    locator_fit_supplement: Mapping[str, Any] | None = None,
    locator_fit_supplement_artifact: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ledgers, missing = v5.preflight_loaded(loaded)
    v5.require(
        ledgers is not None and not missing,
        "v7_inputs_insufficient",
        "The frozen ledgers do not satisfy the V7 two-axis calculation contract.",
        missing,
    )
    audit_mode = loaded["config"]["audit_mode"]
    legacy_fit_defects = [] if legacy_fit_defects is None else list(legacy_fit_defects)
    fit_preflight = locator_fit_preflight(
        ledgers, audit_mode, legacy_defects=legacy_fit_defects
    )
    v5.require(
        not fit_preflight["invalid_or_contradictory_state"],
        "v7_inputs_insufficient",
        "The frozen ledgers contain invalid or contradictory V7 locator states.",
        fit_preflight["invalid_or_contradictory_state"],
    )
    unresolved_ids = [
        item["locator_id"]
        for item in fit_preflight["unresolved_complete_path_fit"]
    ]
    supplemental_decisions: dict[str, Mapping[str, Any]] = {}
    if locator_fit_supplement is None:
        v5.require(
            not unresolved_ids,
            "v7_inputs_insufficient",
            "The frozen ledgers contain unresolved complete-path-fit states.",
            fit_preflight["unresolved_complete_path_fit"],
        )
        v5.require(
            locator_fit_supplement_artifact is None,
            "unexpected_locator_fit_supplement_artifact",
            "A locator-fit supplement artifact cannot be bound without its validated semantic input.",
        )
    else:
        v5.require(
            locator_fit_supplement_artifact is not None
            and locator_fit_supplement_artifact.get("schema_version")
            == locator_fit_supplement.get("schema_version"),
            "locator_fit_supplement_binding_mismatch",
            "A supplemental locator-fit input requires its exact validated artifact binding.",
        )
        supplemental_decisions = {
            item["locator_id"]: item
            for item in locator_fit_supplement["decisions"]
        }
        v5.require(
            sorted(supplemental_decisions) == unresolved_ids,
            "locator_fit_supplement_scope_mismatch",
            "The supplemental decisions must equal the independently derived unresolved locator set.",
            {
                "expected": unresolved_ids,
                "actual": sorted(supplemental_decisions),
            },
        )
    calculation_artifacts = deepcopy(loaded["input_artifacts"])
    if locator_fit_supplement_artifact is not None:
        calculation_artifacts.append(deepcopy(locator_fit_supplement_artifact))
    if structure_review is not None:
        v5.require(
            structure_review_artifact is not None,
            "structure_review_artifact_binding_required",
            "A V7 structure-locator review requires its exact file binding.",
        )
        structure_artifact = next(
            (item for item in loaded["input_artifacts"] if item.get("role") == "structure_audit"),
            None,
        )
        v5.require(
            structure_artifact is not None
            and structure_review.get("inputs", {}).get("structure_audit_file_sha256")
            == structure_artifact.get("sha256"),
            "structure_review_input_binding_mismatch",
            "The V7 review does not bind the exact frozen structure audit used for calculation.",
        )
        supplemental_sha256 = structure_review.get("inputs", {}).get(
            "supplemental_architecture_review_file_sha256"
        )
        if supplemental_sha256 is None:
            v5.require(
                supplemental_architecture_review_artifact is None,
                "unexpected_supplemental_architecture_review_artifact",
                "A V7 calculation cannot bind a supplemental architecture review that is absent from the structure-locator review.",
            )
        else:
            v5.require(
                supplemental_architecture_review_artifact is not None
                and supplemental_architecture_review_artifact.get("sha256")
                == supplemental_sha256
                and supplemental_architecture_review_artifact.get("schema_version")
                == SUPPLEMENTAL_ARCHITECTURE_REVIEW_SCHEMA,
                "supplemental_architecture_review_binding_mismatch",
                "The V7 structure-locator review does not bind the supplied supplemental architecture review.",
            )
            calculation_artifacts.append(
                deepcopy(supplemental_architecture_review_artifact)
            )
        try:
            ledgers = apply_deterministic_structure_corrections(
                ledgers, structure_review, audit_mode=audit_mode
            )
        except StructureReviewError as exc:
            raise v5.CalculationError(exc.code, exc.message, exc.details) from exc
        calculation_artifacts.append(structure_review_artifact)
    dimensions = [
        v5.calculate_coverage(ledgers, audit_mode),
        v5.calculate_selectivity(ledgers, audit_mode),
        v5.calculate_concept(ledgers, audit_mode),
        calculate_reliability(
            ledgers,
            audit_mode,
            legacy_defects=legacy_fit_defects,
            supplemental_decisions=supplemental_decisions,
        ),
        v5.calculate_findability(ledgers, audit_mode),
        v5.calculate_mechanics(ledgers, audit_mode),
    ]
    for dimension in dimensions:
        dimension["formula_id"] = f"{CALCULATION_PROFILE}:{dimension['dimension_id']}"
        selected: list[dict[str, Any]] = []
        for artifact in calculation_artifacts:
            role = artifact["role"]
            include = any(
                role == "chunk_manifest"
                or (requested == "locator_audit" and role.startswith("locator_audit["))
                or (requested == "missing_access_audit" and role.startswith("missing_access_audit["))
                or (requested == "structure_audit" and role == "structure_audit")
                or (requested == "structure_audit_or_migration_supplement" and role in {"structure_audit", "migration_supplement"})
                for requested in dimension["input_roles"]
            )
            if role == "structure_locator_review" and dimension["dimension_id"] == "findability_navigation":
                include = True
            if (
                role == "supplemental_architecture_review"
                and dimension["dimension_id"] == "findability_navigation"
            ):
                include = True
            if (
                role == "supplemental_locator_fit"
                and dimension["dimension_id"] == "page_reference_reliability"
            ):
                include = True
            if include and artifact not in selected:
                selected.append(artifact)
        v5.require(bool(selected), "dimension_input_binding_failed", f"{dimension['dimension_id']} did not resolve frozen inputs.")
        dimension["input_artifacts"] = selected

    all_scored = all(item["status"] == "scored" for item in dimensions)
    total = (
        v5.round_points(sum((v5.decimal_value(item["awarded_points"]) for item in dimensions), ZERO))
        if all_scored
        else None
    )
    result = {
        "schema_version": CALCULATION_SCHEMA,
        "calculation_id": f"CALC-{v5.canonical_hash({'evaluation_id': loaded['config']['evaluation_id'], 'audit_mode': audit_mode, 'rubric_version': RUBRIC_VERSION, 'calculation_profile': CALCULATION_PROFILE, 'inputs': calculation_artifacts})[:12].upper()}",
        "evaluation_id": loaded["config"]["evaluation_id"],
        "rubric_version": RUBRIC_VERSION,
        "calculation_profile": CALCULATION_PROFILE,
        "audit_mode": audit_mode,
        "status": "scored" if all_scored else "not_scored_insufficient_evidence",
        "evidence_identity": {field: ledgers["identity"][field] for field in v5.CALCULATION_EVIDENCE_IDENTITY_FIELDS},
        "input_artifacts": calculation_artifacts,
        "diagnostic_item_grades": {
            "used_in_dimension_arithmetic": False,
            "policy": "separate_non_additive_display_layer_same_scale_as_locator_credit",
            "required_policy_version": ITEM_GRADING_POLICY,
            "expected_source_subjects": {
                "count": len(ledgers["expected_subject_ids"]),
                "id_set_sha256": v5.canonical_hash({"ids": ledgers["expected_subject_ids"]}),
            },
        },
        "publication_readiness_gates": {
            "used_in_score_arithmetic": False,
            "policy": "separate_claim_restrictions_unchanged_from_v6",
        },
        "dimensions": dimensions,
        "total_score": v5.displayed_number(total, Decimal("0.01")) if total is not None else None,
        "maximum_score": 100,
        "arithmetic_check": all_scored and total == sum((v5.decimal_value(item["awarded_points"]) for item in dimensions), ZERO).quantize(Decimal("0.01"), rounding=v5.ROUND_HALF_UP),
    }
    if structure_review is not None:
        result["structure_locator_review"] = {
            "schema_version": structure_review["schema_version"],
            "review_id": structure_review["review_id"],
            "review_sha256": structure_review["review_sha256"],
            "thresholds": deepcopy(structure_review["thresholds"]),
            "summary": deepcopy(structure_review["summary"]),
            "active_correction": deepcopy(ledgers["v7_structure_correction"]),
        }
    result["locator_fit_compatibility"] = {
        "rule": LEGACY_FIT_COMPATIBILITY_RULE_ID,
        "conflict_rule": LEGACY_FIT_CONFLICT_RULE_ID,
        "classifications": deepcopy(
            fit_preflight["compatibility_classifications"]
        ),
        "preflight_group_counts": deepcopy(fit_preflight["group_counts"]),
        "unresolved_reason_counts_before_supplement": deepcopy(
            fit_preflight["unresolved_reason_counts"]
        ),
        "unresolved_records_before_supplement": deepcopy(
            fit_preflight["unresolved_complete_path_fit"]
        ),
        "unresolved_before_supplement": len(unresolved_ids),
        "unresolved_after_supplement": (
            0 if locator_fit_supplement is not None else len(unresolved_ids)
        ),
        "historical_defects_rewritten": False,
        "classifier_precedence_applied": False,
        "aggregate_score_exposed_during_preflight": False,
        "prose_inference_used": False,
    }
    if locator_fit_supplement is not None:
        result["locator_fit_supplement"] = {
            "schema_version": locator_fit_supplement["schema_version"],
            "supplement_id": locator_fit_supplement["supplement_id"],
            "supplement_sha256": locator_fit_supplement["supplement_sha256"],
            "file_sha256": locator_fit_supplement_artifact["sha256"],
            "scope_rule_id": locator_fit_supplement["scope"]["rule_id"],
            "unresolved_set_sha256": locator_fit_supplement["scope"][
                "unresolved_set_sha256"
            ],
            "decision_count": len(locator_fit_supplement["decisions"]),
            "application": "complete_path_fit_only_in_memory",
            "numerical_credit_supplied": False,
        }
    result["calculation_sha256"] = v5.canonical_hash(result, "calculation_sha256")
    return result


def reliability_dimension(calculation: dict[str, Any]) -> dict[str, Any]:
    matches = [item for item in calculation.get("dimensions", []) if item.get("dimension_id") == "page_reference_reliability"]
    v5.require(len(matches) == 1, "v7_reliability_dimension_required", "A V7 calculation must contain exactly one Page-reference Reliability dimension.")
    return matches[0]


def load_structure_review(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    document = v5.load_json(path, "V7 structure-locator review")
    v5.validate_schema_document(
        document,
        "structure-locator-review-v1.schema.json",
        "V7 structure-locator review",
    )
    v5.require(
        document.get("review_sha256")
        == structure_review_hash(document, "review_sha256"),
        "structure_review_hash_mismatch",
        "The V7 structure-locator review self-hash does not reconstruct.",
    )
    validate_structure_locator_review_semantics(document)
    return document, {
        "role": "structure_locator_review",
        "path": str(path),
        "sha256": v5.sha256_file(path),
        "schema_version": document["schema_version"],
    }


def command_derive_structure_review(args: argparse.Namespace) -> None:
    try:
        candidate_path = Path(args.normalized_candidate).resolve()
        inventory_path = Path(args.item_inventory).resolve()
        structure_path = Path(args.structure_audit).resolve()
        output_path = Path(args.output).resolve()
        candidate = v5.load_json(candidate_path, "Frozen normalized candidate")
        inventory = v5.load_json(inventory_path, "Frozen item inventory")
        structure = v5.load_json(structure_path, "Frozen structure audit")
        v5.validate_schema_document(candidate, "candidate-index-v2.schema.json", "Frozen normalized candidate")
        v5.validate_schema_document(inventory, "item-inventory-v2.schema.json", "Frozen item inventory")
        v5.require(
            structure.get("schema_version") == "structure-audit-v5",
            "unsupported_structure_audit_schema",
            "Current V7 scoring requires structure-audit-v5.",
        )
        v5.validate_schema_document(structure, "structure-audit-v5.schema.json", "Frozen structure audit")
        v5.require(
            not v5.aliases_existing_file(
                output_path, {candidate_path, inventory_path, structure_path}
            ),
            "output_aliases_frozen_input",
            "The V7 derived review must not overwrite a frozen artifact.",
        )
        review = derive_structure_locator_review(
            candidate,
            inventory,
            structure,
            candidate_file_sha256=v5.sha256_file(candidate_path),
            inventory_file_sha256=v5.sha256_file(inventory_path),
            structure_file_sha256=v5.sha256_file(structure_path),
            audit_mode=args.audit_mode,
        )
        v5.validate_schema_document(
            review,
            "structure-locator-review-v1.schema.json",
            "Generated V7 structure-locator review",
        )
        write_json(output_path, review)
        v5.emit(
            {
                "command": "derive-v7-structure-locator-review",
                "ok": True,
                "artifact_written": str(output_path),
                "review_id": review["review_id"],
                "review_sha256": review["review_sha256"],
                "migration_ready": review["migration_ready"],
                "summary": review["summary"],
            }
        )
    except (OSError, v5.CalculationError, StructureReviewError) as exc:
        if isinstance(exc, (v5.CalculationError, StructureReviewError)):
            error = {"code": exc.code, "message": exc.message, "details": exc.details}
        else:
            error = {"code": "file_error", "message": str(exc)}
        v5.emit({"command": "derive-v7-structure-locator-review", "ok": False, "error": error}, 1)


def command_preflight(args: argparse.Namespace) -> None:
    config_path = Path(args.input).resolve()
    try:
        raw_evaluation_id, raw_missing, raw_paths = raw_locator_state_requirements(config_path)
        if raw_missing:
            result = {
                "command": "v7-calculation-sufficiency-preflight",
                "ok": True,
                "evaluation_id": raw_evaluation_id,
                "target_rubric_version": RUBRIC_VERSION,
                "target_calculation_profile": CALCULATION_PROFILE,
                "sufficient": False,
                "missing_requirements": raw_missing,
                "aggregate_v7_score_available": False,
                "source_reopened": False,
                "prose_inference_used": False,
                "frozen_evidence_mutated": False,
            }
            if args.output:
                output_path = Path(args.output).resolve()
                v5.require(not v5.aliases_existing_file(output_path, {config_path, *raw_paths}), "output_aliases_frozen_input", "Preflight output must not overwrite frozen evidence.")
                write_json(output_path, result)
                result["artifact_written"] = str(output_path)
            v5.emit(result)
        loaded = load_v7_inputs(config_path)
        ledgers, base_missing = v5.preflight_loaded(loaded)
        fit_report = (
            locator_fit_preflight(
                ledgers,
                loaded["config"]["audit_mode"],
                legacy_defects=(),
            )
            if ledgers is not None
            else {
                "schema_version": "subject-index-v7-locator-fit-preflight-v1",
                "deterministically_compatible": [],
                "unresolved_complete_path_fit": [],
                "invalid_or_contradictory_state": [],
                "compatibility_classifications": [],
                "group_counts": {
                    "deterministically_compatible": 0,
                    "unresolved_complete_path_fit": 0,
                    "invalid_or_contradictory_state": 0,
                },
                "unresolved_reason_counts": {},
                "unresolved_set_sha256": v5.canonical_hash(
                    {"unresolved_locator_fit": []}
                ),
                "aggregate_v7_score_available": False,
                "prose_inference_used": False,
                "historical_artifacts_modified": False,
            }
        )
        missing = [
            *base_missing,
            *fit_report["invalid_or_contradictory_state"],
            *(
                {
                    "code": "unresolved_complete_path_fit",
                    "path": f"locator:{item['locator_id']}",
                    "message": "; ".join(
                        UNRESOLVED_REASON_MESSAGES[reason]
                        for reason in item["reason_codes"]
                    ),
                    **item,
                }
                for item in fit_report["unresolved_complete_path_fit"]
            ),
        ]
        public_fit_report = public_locator_fit_preflight(fit_report)
        v5.validate_schema_document(
            public_fit_report,
            "v7-locator-fit-preflight.schema.json",
            "V7 locator-fit preflight",
        )
        result = {
            "command": "v7-calculation-sufficiency-preflight",
            "ok": True,
            "evaluation_id": loaded["config"]["evaluation_id"],
            "target_rubric_version": RUBRIC_VERSION,
            "target_calculation_profile": CALCULATION_PROFILE,
            "sufficient": not missing,
            "missing_requirements": missing,
            "locator_fit_preflight": public_fit_report,
            "aggregate_v7_score_available": False,
            "required_locator_fields": ["judgment", "treatment_class", "source_scope_status", "error_codes", "severity", "applicable_structured_defects"],
            "source_reopened": False,
            "prose_inference_used": False,
            "frozen_evidence_mutated": False,
        }
        if args.output:
            output_path = Path(args.output).resolve()
            v5.require(not v5.aliases_existing_file(output_path, {loaded["config_path"], *loaded["input_paths"]}), "output_aliases_frozen_input", "Preflight output must not overwrite frozen evidence.")
            write_json(output_path, result)
            result["artifact_written"] = str(output_path)
        v5.emit(result)
    except (OSError, v5.CalculationError) as exc:
        error = {"code": exc.code, "message": exc.message, "details": exc.details} if isinstance(exc, v5.CalculationError) else {"code": "file_error", "message": str(exc)}
        v5.emit({"command": "v7-calculation-sufficiency-preflight", "ok": False, "error": error}, 1)


def command_calculate(args: argparse.Namespace) -> None:
    try:
        loaded = load_v7_inputs(Path(args.input).resolve())
        review_path = Path(args.structure_locator_review).resolve()
        review, review_artifact = load_structure_review(review_path)
        result = calculate_loaded(
            loaded,
            structure_review=review,
            structure_review_artifact=review_artifact,
        )
        v5.validate_schema_document(result, "dimension-calculations-v4.schema.json", "Generated V7 dimension calculations")
        if args.output:
            output_path = Path(args.output).resolve()
            v5.require(not v5.aliases_existing_file(output_path, {loaded["config_path"], *loaded["input_paths"]}), "output_aliases_frozen_input", "Calculation output must not overwrite frozen evidence.")
            write_json(output_path, result)
            response = {"command": "calculate-v7-dimensions", "ok": True, "evaluation_id": result["evaluation_id"], "status": result["status"], "total_score": result["total_score"], "calculation_sha256": result["calculation_sha256"], "artifact_written": str(output_path)}
        else:
            response = {"command": "calculate-v7-dimensions", "ok": True, **result}
        v5.emit(response)
    except (OSError, v5.CalculationError) as exc:
        error = {"code": exc.code, "message": exc.message, "details": exc.details} if isinstance(exc, v5.CalculationError) else {"code": "file_error", "message": str(exc)}
        v5.emit({"command": "calculate-v7-dimensions", "ok": False, "error": error}, 1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    preflight = subparsers.add_parser("preflight", help="Report exact V7 two-axis calculation sufficiency.")
    preflight.add_argument("--input", required=True)
    preflight.add_argument("--output")
    preflight.set_defaults(func=command_preflight)
    derive = subparsers.add_parser(
        "derive-structure-review",
        help="Derive displayed-locator, range-span, and atomic-assignment review evidence.",
    )
    derive.add_argument("--normalized-candidate", required=True)
    derive.add_argument("--item-inventory", required=True)
    derive.add_argument("--structure-audit", required=True)
    derive.add_argument("--audit-mode", required=True, choices=("full", "pilot"))
    derive.add_argument("--output", required=True)
    derive.set_defaults(func=command_derive_structure_review)
    calculate = subparsers.add_parser("calculate", help="Derive all six V7 ratings from frozen ledgers.")
    calculate.add_argument("--input", required=True)
    calculate.add_argument("--structure-locator-review", required=True)
    calculate.add_argument("--output")
    calculate.set_defaults(func=command_calculate)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
