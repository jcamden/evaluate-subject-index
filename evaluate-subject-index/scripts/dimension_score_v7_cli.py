#!/usr/bin/env python3
"""Deterministic V7 scoring, migration, and projection tooling.

V7 changes only the per-locator precision input to Page-reference Reliability.
It derives independent page-treatment and complete-path-fit ceilings from frozen
structured evidence, combines them with ``min(T, F)``, and preserves every V6
non-reliability formula, cap, gate, recall rule, and rounding rule.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import dimension_score_cli as v5
import dimension_score_v6_cli as v6
import item_grade_cli as item_v6
from item_grade_v7_cli import build_v7_assessments
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
CALCULATION_SCHEMA = "subject-index-dimension-calculations-v3"
RESULT_SCHEMA = "subject-index-evaluation-result-v8"
WEB_REPORT_SCHEMA = "subject-index-web-report-v6"
ITEM_ASSESSMENT_SCHEMA = "subject-index-item-assessments-v4"
ITEM_GRADING_POLICY = "subject-index-item-grading-v3"
PROJECTION_METADATA_SCHEMA = "subject-index-v7-projection-metadata-v1"
MIGRATION_SCHEMA = "subject-index-score-migration-v6-to-v7-v1"
VALIDATION_RECEIPT_SCHEMA = "subject-index-score-migration-v6-to-v7-validation-v1"
SUPPLEMENTAL_ARCHITECTURE_REVIEW_SCHEMA = (
    "subject-index-v7-architecture-review-supplement-v1"
)
LOCATOR_FIT_SUPPLEMENT_SCHEMA = "subject-index-v7-locator-fit-supplement-v1"
TOOL_NAME = "dimension_score_v7_cli.py"
TOOL_VERSION = "dimension-score-cli-v7.0.5"
METHODOLOGY_REPOSITORY = "https://github.com/jcamden/evaluate-subject-index"

ZERO = Decimal(0)
ONE = Decimal(1)
TWO = Decimal(2)
FIVE = Decimal(5)

SCORE_VIEW_SHARED_EVIDENCE_FIELDS = (
    "source_sha256",
    "benchmark_sha256",
    "policy_sha256",
    "page_map_sha256",
    "chunk_manifest_sha256",
    "candidate_sha256",
)


write_json = v6.write_json
migration_artifact_root_spec = v6.migration_artifact_root_spec
portable_rooted_artifact_reference = v6.portable_rooted_artifact_reference
migration_artifact_root = v6.migration_artifact_root
resolve_migration_artifact_path = v6.resolve_migration_artifact_path


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
                    "message": "V7 migration requires the frozen locator judgment array.",
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
    """Load the historical V4 structure contract or the native V7 V5 contract.

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
    if structure_document.get("schema_version") != "structure-audit-v5":
        return v5.load_inputs(config_path)
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
            document, "locator-audit.schema.json", f"locator_audit[{index}]"
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
    legacy_defects = historical_locator_fit_defects(loaded["structure"])
    missing = [
        *missing,
        *locator_state_requirements(
            ledgers,
            loaded["config"]["audit_mode"],
            legacy_defects=legacy_defects,
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
    legacy_fit_defects = list(
        historical_locator_fit_defects(loaded["structure"])
        if legacy_fit_defects is None
        else legacy_fit_defects
    )
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
            == LOCATOR_FIT_SUPPLEMENT_SCHEMA,
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
        structure_schema = (
            "structure-audit-v5.schema.json"
            if structure.get("schema_version") == "structure-audit-v5"
            else "structure-audit-v4.schema.json"
            if structure.get("schema_version") == "structure-audit-v4"
            else "structure-audit.schema.json"
        )
        v5.validate_schema_document(structure, structure_schema, "Frozen structure audit")
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
                legacy_defects=historical_locator_fit_defects(
                    loaded["structure"]
                ),
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
        v5.validate_schema_document(result, "dimension-calculations-v3.schema.json", "Generated V7 dimension calculations")
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


def precision_diagnostics(calculation: Mapping[str, Any]) -> dict[str, Any]:
    provenance = deepcopy(reliability_dimension(dict(calculation))["reliability_provenance"])
    return {
        "model": provenance["model"],
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
        "counts_by_treatment_tier": provenance["counts_by_treatment_tier"],
        "counts_by_fit_tier": provenance["counts_by_fit_tier"],
        "counts_by_combined_credit_value": provenance["counts_by_combined_credit_value"],
        "weighted_role": "two_axis_locator_utility_input_to_page_reference_reliability",
        "strict_role": "substantive_validity_diagnostic_not_used_in_v7_dimension_arithmetic",
        "diagnostic_grade_role": "same_scale_display_not_used_as_aggregate_input",
        "weak_presence_is_substantive": False,
    }


def grade_label(score: Any) -> str:
    return v6.grade_label(score)


def scorecard_projection(calculation: Mapping[str, Any], *, web: bool = False) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for dimension in calculation["dimensions"]:
        if web:
            record = {
                "dimension_id": dimension["dimension_id"],
                "label": dimension["dimension_id"].replace("_", " ").title(),
                "rating": dimension["final_rating"],
                "unrounded_rating": dimension["unrounded_rating"],
                "weight": dimension["dimension_weight"],
                "awarded_points": dimension["awarded_points"],
                "status": dimension["status"],
                "formula_id": dimension["formula_id"],
                "input_artifacts": deepcopy(dimension["input_artifacts"]),
                "denominators": deepcopy(dimension["denominators"]),
                "raw_status_counts": deepcopy(dimension["raw_status_counts"]),
                "credit_mappings": deepcopy(dimension["credit_mappings"]),
                "components": deepcopy(dimension["components"]),
                "base_rating": dimension["base_rating"],
                "pre_cap_rating": dimension["pre_cap_rating"],
                "post_cap_rating": dimension["post_cap_rating"],
                "cap_evaluations": deepcopy(dimension["cap_evaluations"]),
                "applied_cap": deepcopy(dimension["applied_cap"]),
                "rounding": deepcopy(dimension["rounding"]),
                "missing_data_bounds": deepcopy(dimension["missing_data_bounds"]),
            }
            if dimension["dimension_id"] == "page_reference_reliability":
                record["reliability_provenance"] = deepcopy(
                    dimension["reliability_provenance"]
                )
        else:
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
                "applied_cap_id": dimension["applied_cap"]["cap_id"] if dimension["applied_cap"] else None,
                "rationale": "Deterministically reconstructed from the bound V7 calculation artifact.",
                "evidence_ids": evidence_ids,
            }
            if dimension["dimension_id"] == "page_reference_reliability":
                record["subscores"] = precision_diagnostics(calculation)
        records.append(record)
    return records


def _resolve_manifest_artifact(
    manifest_path: Path, reference: Mapping[str, Any], label: str
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    stored_path = reference.get("path") if isinstance(reference, Mapping) else None
    v5.require_portable_relative_path(stored_path, label=f"{label}.path")
    v5.require(
        ".." not in Path(str(stored_path)).parts,
        "nonportable_artifact_path",
        f"{label}.path must not traverse outside the migration-input directory.",
        {"path": stored_path},
    )
    root = manifest_path.resolve().parent
    resolved = (root / Path(str(stored_path))).resolve()
    v5.require(
        resolved.is_relative_to(root),
        "migration_input_artifact_escape",
        f"{label}.path escapes the migration-input directory, including through a symlink.",
        {"path": stored_path, "resolved": str(resolved), "root": str(root)},
    )
    return v5.resolve_input(manifest_path, dict(reference), label)


def _load_supplemental_architecture_review(
    path: Path, *, label: str
) -> dict[str, Any]:
    document = v5.load_json(path, label)
    v5.validate_schema_document(
        document,
        "v7-architecture-review-supplement.schema.json",
        label,
    )
    v5.require(
        document.get("supplement_sha256")
        == v5.canonical_hash(document, "supplement_sha256"),
        "supplemental_architecture_review_hash_mismatch",
        "The supplemental V7 architecture review self-hash does not reconstruct.",
    )
    identity_seed = deepcopy(document)
    identity_seed["supplement_id"] = ""
    identity_seed["supplement_sha256"] = ""
    v5.require(
        document.get("supplement_id")
        == f"ARCHSUP-{v5.canonical_hash(identity_seed)[:12].upper()}",
        "supplemental_architecture_review_id_mismatch",
        "The supplemental V7 architecture review identity does not reconstruct.",
    )
    return document


def _validate_supplemental_architecture_review(
    supplement: Mapping[str, Any],
    *,
    loaded: Mapping[str, Any],
    config_path: Path,
    candidate: Mapping[str, Any],
    candidate_path: Path,
    inventory: Mapping[str, Any],
    inventory_path: Path,
    structure_path: Path,
    base_review: Mapping[str, Any],
) -> None:
    bindings = supplement["bindings"]
    expected_bindings = {
        "candidate_sha256": candidate.get("candidate_sha256"),
        "v6_dimension_calculation_input_file_sha256": v5.sha256_file(
            config_path
        ),
        "normalized_candidate_file_sha256": v5.sha256_file(candidate_path),
        "item_inventory_file_sha256": v5.sha256_file(inventory_path),
        "historical_structure_audit_file_sha256": v5.sha256_file(structure_path),
    }
    v5.require(
        bindings == expected_bindings,
        "supplemental_architecture_review_binding_mismatch",
        "The supplemental architecture review must bind the exact frozen candidate, inventory, and historical structure audit.",
        {"expected": expected_bindings, "actual": bindings},
    )
    v5.require(
        supplement.get("evaluation_id") == loaded["config"]["evaluation_id"]
        and supplement.get("audit_mode") == loaded["config"]["audit_mode"],
        "supplemental_architecture_review_identity_mismatch",
        "The supplemental architecture review has a different evaluation identity or audit mode.",
    )

    decisions = supplement["decisions"]
    decision_path_ids = [item["path_id"] for item in decisions]
    scope_path_ids = supplement["review_scope"]["path_ids"]
    unresolved_path_ids = base_review["summary"]["review_required_path_ids"]
    v5.require(
        decision_path_ids == sorted(decision_path_ids)
        and scope_path_ids == sorted(scope_path_ids)
        and decision_path_ids == scope_path_ids
        and decision_path_ids == unresolved_path_ids,
        "supplemental_architecture_review_scope_mismatch",
        "The supplemental review must contain every and only the mechanically unresolved trigger paths, in stable PATH-* order.",
        {
            "decision_path_ids": decision_path_ids,
            "declared_scope_path_ids": scope_path_ids,
            "unresolved_trigger_path_ids": unresolved_path_ids,
        },
    )
    review_ids = [item["review_id"] for item in decisions]
    v5.require(
        len(review_ids) == len(set(review_ids)),
        "supplemental_architecture_review_duplicate_id",
        "Every supplemental architecture decision requires a unique ARCHREV-* identity.",
    )

    candidates_by_path = {
        item["path_id"]: item for item in candidate.get("records", [])
    }
    inventory_by_path = {
        item["path_id"]: item for item in inventory.get("paths", [])
    }
    for decision in decisions:
        path_id = decision["path_id"]
        candidate_record = candidates_by_path[path_id]
        inventory_record = inventory_by_path[path_id]
        allowed_evidence_ids = {
            path_id,
            candidate_record["record_id"],
            *inventory_record["node_ids"],
            *inventory_record["locator_ids"],
            *(
                display["display_id"]
                for display in candidate_record["locator_displays"]
            ),
            *(
                display["range_id"]
                for display in candidate_record["locator_displays"]
                if display.get("range_id") is not None
            ),
        }
        evidence_ids = set(decision["evidence_ids"])
        v5.require(
            evidence_ids <= allowed_evidence_ids,
            "supplemental_architecture_review_evidence_scope_mismatch",
            "A supplemental architecture decision cites evidence outside its frozen candidate path, inventory nodes, displays, ranges, or assignments.",
            {
                "path_id": path_id,
                "unexpected_evidence_ids": sorted(
                    evidence_ids - allowed_evidence_ids
                ),
            },
        )


def _bound_artifact_identity(artifact: Mapping[str, Any]) -> dict[str, Any]:
    role = artifact.get("role")
    schema_version = artifact.get("schema_version")
    sha256 = artifact.get("sha256")
    v5.require(
        isinstance(role, str)
        and role
        and isinstance(schema_version, str)
        and schema_version
        and isinstance(sha256, str)
        and len(sha256) == 64,
        "locator_fit_supplement_binding_mismatch",
        "Every locator-fit binding requires a role, schema identity, and exact file SHA-256.",
        deepcopy(dict(artifact)),
    )
    return {
        "role": role,
        "schema_version": schema_version,
        "file_sha256": sha256,
    }


def _expected_locator_fit_bindings(
    *,
    loaded: Mapping[str, Any],
    config_path: Path,
    candidate_path: Path,
    inventory_path: Path,
    old_calculation: Mapping[str, Any],
    old_calculation_path: Path,
    representation_provenance_artifacts: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    identities = sorted(
        (_bound_artifact_identity(item) for item in loaded["input_artifacts"]),
        key=lambda item: (item["role"], item["file_sha256"]),
    )

    def select(prefix: str) -> list[dict[str, Any]]:
        return [item for item in identities if item["role"].startswith(prefix)]

    def exactly(role: str) -> dict[str, Any]:
        matches = [item for item in identities if item["role"] == role]
        v5.require(
            len(matches) == 1,
            "locator_fit_supplement_binding_mismatch",
            f"The exact {role} artifact binding is required.",
        )
        return matches[0]

    migration_supplements = [
        item for item in identities if item["role"] == "migration_supplement"
    ]
    v5.require(
        len(migration_supplements) <= 1,
        "locator_fit_supplement_binding_mismatch",
        "At most one historical migration supplement may affect a score view.",
    )
    provenance = sorted(
        (
            _bound_artifact_identity(item)
            for item in representation_provenance_artifacts
        ),
        key=lambda item: (item["role"], item["file_sha256"]),
    )
    return {
        "v6_dimension_calculation_input_file_sha256": v5.sha256_file(config_path),
        "normalized_candidate_file_sha256": v5.sha256_file(candidate_path),
        "item_inventory_file_sha256": v5.sha256_file(inventory_path),
        "historical_v6_calculation_file_sha256": v5.sha256_file(
            old_calculation_path
        ),
        "historical_v6_calculation_sha256": old_calculation[
            "calculation_sha256"
        ],
        "locator_audit_artifacts": select("locator_audit["),
        "missing_access_audit_artifacts": select("missing_access_audit["),
        "historical_structure_audit": exactly("structure_audit"),
        "chunk_manifest": exactly("chunk_manifest"),
        "migration_supplement": (
            migration_supplements[0] if migration_supplements else None
        ),
        "representation_correction_provenance_artifacts": provenance,
        "calculation_input_artifact_set_sha256": v5.canonical_hash(
            {"artifacts": identities}
        ),
    }


def _load_locator_fit_supplement(path: Path, *, label: str) -> dict[str, Any]:
    document = v5.load_json(path, label)
    v5.validate_schema_document(
        document, "v7-locator-fit-supplement.schema.json", label
    )
    v5.require(
        document.get("supplement_sha256")
        == v5.canonical_hash(document, "supplement_sha256"),
        "locator_fit_supplement_hash_mismatch",
        "The supplemental locator-fit self-hash does not reconstruct.",
    )
    identity_seed = deepcopy(document)
    identity_seed["supplement_id"] = ""
    identity_seed["supplement_sha256"] = ""
    v5.require(
        document.get("supplement_id")
        == f"FITSUP-{v5.canonical_hash(identity_seed)[:12].upper()}",
        "locator_fit_supplement_id_mismatch",
        "The supplemental locator-fit identity does not reconstruct.",
    )
    decisions = document["decisions"]
    locator_ids = [item["locator_id"] for item in decisions]
    decision_ids = [item["decision_id"] for item in decisions]
    v5.require(
        locator_ids == sorted(locator_ids)
        and len(locator_ids) == len(set(locator_ids))
        and len(decision_ids) == len(set(decision_ids)),
        "locator_fit_supplement_decision_order_invalid",
        "Locator-fit decisions must be unique and ordered by locator ID.",
    )
    for decision in decisions:
        seed = deepcopy(decision)
        seed["decision_id"] = ""
        v5.require(
            decision["decision_id"]
            == f"FITDEC-{v5.canonical_hash(seed)[:12].upper()}",
            "locator_fit_supplement_decision_id_mismatch",
            "A supplemental locator-fit decision identity does not reconstruct.",
            decision["locator_id"],
        )
        v5.require(
            decision["evidence_ids"] == sorted(decision["evidence_ids"]),
            "locator_fit_supplement_evidence_order_invalid",
            "Supplemental locator-fit evidence IDs must use stable sorted order.",
            decision["locator_id"],
        )
    for field in (
        "locator_audit_artifacts",
        "missing_access_audit_artifacts",
        "representation_correction_provenance_artifacts",
    ):
        values = document["bindings"][field]
        v5.require(
            values
            == sorted(values, key=lambda item: (item["role"], item["file_sha256"])),
            "locator_fit_supplement_binding_order_invalid",
            f"{field} must use stable role/hash ordering.",
        )
    return document


def _validate_locator_fit_supplement(
    supplement: Mapping[str, Any],
    *,
    supplement_path: Path,
    loaded: Mapping[str, Any],
    config_path: Path,
    candidate: Mapping[str, Any],
    candidate_path: Path,
    inventory: Mapping[str, Any],
    inventory_path: Path,
    old_calculation: Mapping[str, Any],
    old_calculation_path: Path,
    fit_preflight: Mapping[str, Any],
    representation_provenance_artifacts: Iterable[Mapping[str, Any]],
) -> None:
    expected_bindings = _expected_locator_fit_bindings(
        loaded=loaded,
        config_path=config_path,
        candidate_path=candidate_path,
        inventory_path=inventory_path,
        old_calculation=old_calculation,
        old_calculation_path=old_calculation_path,
        representation_provenance_artifacts=representation_provenance_artifacts,
    )
    v5.require(
        supplement["bindings"] == expected_bindings,
        "locator_fit_supplement_binding_mismatch",
        "The locator-fit supplement must bind every exact artifact whose bytes affect the unresolved set.",
        {"expected": expected_bindings, "actual": supplement["bindings"]},
    )
    v5.require(
        supplement.get("evaluation_id") == loaded["config"]["evaluation_id"]
        and supplement.get("audit_mode") == loaded["config"]["audit_mode"]
        and supplement.get("candidate_identity")
        == {
            "candidate_id": candidate["candidate_id"],
            "candidate_sha256": candidate["candidate_sha256"],
        },
        "locator_fit_supplement_identity_mismatch",
        "The locator-fit supplement has a different evaluation, candidate, or audit-mode identity.",
    )
    unresolved = fit_preflight["unresolved_complete_path_fit"]
    unresolved_ids = [item["locator_id"] for item in unresolved]
    scope = supplement["scope"]
    decision_ids = [item["locator_id"] for item in supplement["decisions"]]
    v5.require(
        scope["unresolved_locator_ids"] == unresolved_ids
        and decision_ids == unresolved_ids
        and scope["unresolved_set_sha256"]
        == fit_preflight["unresolved_set_sha256"],
        "locator_fit_supplement_scope_mismatch",
        "The supplement must contain every and only the independently derived unresolved locator set.",
        {
            "expected_locator_ids": unresolved_ids,
            "declared_locator_ids": scope["unresolved_locator_ids"],
            "decision_locator_ids": decision_ids,
            "expected_unresolved_set_sha256": fit_preflight[
                "unresolved_set_sha256"
            ],
            "declared_unresolved_set_sha256": scope[
                "unresolved_set_sha256"
            ],
        },
    )
    protected_paths = {
        config_path,
        candidate_path,
        inventory_path,
        old_calculation_path,
        *loaded["input_paths"],
    }
    v5.require(
        not v5.aliases_existing_file(supplement_path, protected_paths),
        "locator_fit_supplement_aliases_historical_artifact",
        "A locator-fit supplement cannot alias a historical input through a path, symlink, or hard link.",
    )

    unresolved_by_id = {item["locator_id"]: item for item in unresolved}
    locators_by_id = fit_preflight["_locator_records_by_id"]
    candidates_by_path = {
        item["path_id"]: item for item in candidate.get("records", [])
    }
    inventory_by_path = {
        item["path_id"]: item for item in inventory.get("paths", [])
    }
    for decision in supplement["decisions"]:
        locator_id = decision["locator_id"]
        unresolved_record = unresolved_by_id[locator_id]
        locator = locators_by_id[locator_id]
        path_id = unresolved_record["path_id"]
        v5.require(
            locator.get("judgment") == "unsupported"
            and decision["path_id"] == path_id,
            "locator_fit_supplement_override_forbidden",
            "A supplemental decision may apply only to the matching unresolved unsupported locator.",
            locator_id,
        )
        v5.require(
            path_id in candidates_by_path and path_id in inventory_by_path,
            "locator_fit_supplement_path_identity_mismatch",
            "The unresolved locator's complete path must exist exactly in the bound candidate and inventory.",
            {"locator_id": locator_id, "path_id": path_id},
        )
        candidate_record = candidates_by_path[path_id]
        inventory_record = inventory_by_path[path_id]
        v5.require(
            any(
                item.get("locator_id") == locator_id
                for item in candidate_record.get("locator_assignments", [])
                if isinstance(item, Mapping)
            )
            and any(
                item.get("locator_id") == locator_id
                and item.get("path_id") == path_id
                for item in inventory.get("locators", [])
                if isinstance(item, Mapping)
            ),
            "locator_fit_supplement_path_identity_mismatch",
            "The supplemental locator and path must retain the exact normalized candidate and inventory assignment.",
            {"locator_id": locator_id, "path_id": path_id},
        )
        displays = [
            item
            for item in candidate_record["locator_displays"]
            if locator_id in item["locator_ids"]
        ]
        allowed_evidence_ids = {
            locator_id,
            path_id,
            candidate_record["record_id"],
            inventory_record["record_id"],
            *inventory_record["node_ids"],
            *unresolved_record["applicable_structured_defect_ids"],
            *locator.get("evidence_ids", []),
            *(item["display_id"] for item in displays),
            *(
                item["range_id"]
                for item in displays
                if item.get("range_id") is not None
            ),
        }
        unexpected = set(decision["evidence_ids"]) - allowed_evidence_ids
        v5.require(
            not unexpected,
            "locator_fit_supplement_evidence_scope_mismatch",
            "A locator-fit decision cites evidence outside its affected locator, path, record, inventory nodes, applicable defects, or bound source-evidence IDs.",
            {"locator_id": locator_id, "unexpected_evidence_ids": sorted(unexpected)},
        )


def _structure_with_supplemental_decisions(
    structure: Mapping[str, Any], supplement: Mapping[str, Any]
) -> dict[str, Any]:
    projected = deepcopy(structure)
    historical = projected.get("v7_architecture_review_decisions", [])
    v5.require(
        isinstance(historical, list),
        "invalid_structure_review_input",
        "v7_architecture_review_decisions must be an array.",
    )
    historical_paths = {
        item.get("path_id") for item in historical if isinstance(item, dict)
    }
    supplemental_paths = {item["path_id"] for item in supplement["decisions"]}
    v5.require(
        not historical_paths & supplemental_paths,
        "supplemental_architecture_review_override_forbidden",
        "A supplemental architecture review cannot replace a decision already frozen in the historical structure audit.",
        sorted(historical_paths & supplemental_paths),
    )
    projected["v7_architecture_review_decisions"] = [
        *deepcopy(historical),
        *deepcopy(supplement["decisions"]),
    ]
    return projected


def _write_new(path: Path, document: dict[str, Any]) -> None:
    v5.require(not path.exists(), "migration_output_exists", "Score-only migration refuses to overwrite an existing output.", str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, document)


def _canonical_value_equal(left: Any, right: Any) -> bool:
    """Compare JSON values without treating Decimal and float parses as drift."""

    return v5.canonical_json_text(left) == v5.canonical_json_text(right)


def _verify_historical_v6_calculation(
    old: Mapping[str, Any], loaded: dict[str, Any], *, label: str
) -> None:
    v5.validate_schema_document(dict(old), "dimension-calculations-v2.schema.json", "Historical V6 calculation")
    v5.require(old.get("calculation_sha256") == v5.canonical_hash(old, "calculation_sha256"), "historical_v6_calculation_hash_mismatch", "The historical V6 calculation self-hash does not reconstruct.")
    recomputed = v6.calculate_loaded(loaded)
    evidence_equal = _canonical_value_equal(
        old.get("evidence_identity"), recomputed.get("evidence_identity")
    )
    artifacts_equal = _canonical_value_equal(
        old.get("input_artifacts"), recomputed.get("input_artifacts")
    )
    dimensions_equal = _canonical_value_equal(
        old.get("dimensions"), recomputed.get("dimensions")
    )
    total_equal = _canonical_value_equal(
        old.get("total_score"), recomputed.get("total_score")
    )
    v5.require(
        evidence_equal and artifacts_equal and dimensions_equal and total_equal,
        "historical_v6_recalculation_mismatch",
        "The supplied V6 calculation does not reconstruct from the exact frozen input ledger.",
        {
            "view": label,
            "evidence_identity_equal": evidence_equal,
            "input_artifacts_equal": artifacts_equal,
            "dimensions_equal": dimensions_equal,
            "total_score_equal": total_equal,
        },
    )


def _active_structure_projection(
    structure: Mapping[str, Any], review: Mapping[str, Any]
) -> dict[str, Any]:
    active = deepcopy(structure)
    removed = set(review["summary"]["removed_historical_defect_ids"])
    active["defects"] = [
        item for item in active.get("defects", []) if item.get("defect_id") not in removed
    ]
    if isinstance(active.get("v5_scoring_context"), dict):
        active["v5_scoring_context"]["defects"] = [
            item
            for item in active["v5_scoring_context"].get("defects", [])
            if item.get("defect_id") not in removed
        ]
    restored_nodes = {
        item["terminal_node_id"]
        for item in review["path_reviews"]
        if item["final_architecture_disposition"]
        == "historical_false_positive_removed"
    }
    for node in active.get("node_judgments", []):
        if node.get("node_id") in restored_nodes:
            component = node.get("component_judgments", {}).get(
                "heading_access_architecture"
            )
            v5.require(
                isinstance(component, dict)
                and component.get("status") in {"minor_issues", "major_issues", "fails"},
                "structure_correction_status_ambiguous",
                "The derived item projection cannot restore an ambiguous architecture status.",
                node.get("node_id"),
            )
            component["status"] = "passes"
    return active


def _build_v7_item_projection(
    *,
    loaded: dict[str, Any],
    candidate: dict[str, Any],
    inventory: dict[str, Any],
    inventory_path: Path,
    historical_items: dict[str, Any],
    calculation: dict[str, Any],
    review: dict[str, Any],
    output_path: Path,
) -> dict[str, Any]:
    active_structure = _active_structure_projection(loaded["structure"], review)
    base = item_v6.build_assessments(
        candidate,
        inventory,
        loaded["locator_documents"],
        loaded["missing_documents"],
        active_structure,
        loaded["config"]["audit_mode"],
        loaded["config"]["evaluation_id"],
        v5.sha256_file(inventory_path),
        deepcopy(historical_items["evidence_identity"]),
        os.path.relpath(inventory_path, output_path.parent).replace(os.sep, "/"),
    )
    v6_compatible = item_v6.build_v6_assessments(
        base, loaded["locator_documents"], active_structure
    )
    result = build_v7_assessments(v6_compatible, calculation, review)
    v5.validate_schema_document(result, "item-assessments-v4.schema.json", "Generated V7 item assessments")
    return result


def _dimension_value_snapshot(dimension: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: deepcopy(dimension.get(key))
        for key in (
            "dimension_id",
            "status",
            "denominators",
            "raw_status_counts",
            "credit_mappings",
            "components",
            "base_rating",
            "unrounded_rating",
            "cap_evaluations",
            "applied_cap",
            "pre_cap_rating",
            "post_cap_rating",
            "missing_data_bounds",
            "rounding",
            "final_rating",
            "dimension_weight",
            "awarded_points",
        )
    }


def _dimension_comparison(
    old: Mapping[str, Any], new: Mapping[str, Any], review: Mapping[str, Any]
) -> list[dict[str, Any]]:
    old_by_id = {item["dimension_id"]: item for item in old["dimensions"]}
    result: list[dict[str, Any]] = []
    structure_changed = bool(review["summary"]["removed_historical_defect_ids"])
    for current in new["dimensions"]:
        dimension_id = current["dimension_id"]
        historical = old_by_id[dimension_id]
        value_equal = _canonical_value_equal(
            _dimension_value_snapshot(historical),
            _dimension_value_snapshot(current),
        )
        expected_change = dimension_id == "page_reference_reliability" or (
            dimension_id == "findability_navigation" and structure_changed
        )
        v5.require(
            value_equal or expected_change,
            "non_target_dimension_changed",
            "A V7 migration changed a dimension outside locator utility or the deterministic structure-count correction.",
            dimension_id,
        )
        result.append(
            {
                "dimension_id": dimension_id,
                "old_rating": historical["final_rating"],
                "new_rating": current["final_rating"],
                "old_points": historical["awarded_points"],
                "new_points": current["awarded_points"],
                "value_identical": value_equal,
                "change_basis": (
                    "two_axis_locator_utility"
                    if dimension_id == "page_reference_reliability"
                    else "corrected_displayed_locator_unit"
                    if dimension_id == "findability_navigation" and structure_changed
                    else "unchanged_formula_and_evidence"
                ),
            }
        )
    return result


def _migrate_calculation_view(
    *,
    manifest_path: Path,
    references: Mapping[str, Any],
    review_output: Path,
    calculation_output: Path,
    migration_context: dict[str, Any] | None,
    label: str,
    representation_provenance_artifacts: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    representation_provenance_artifacts = list(
        representation_provenance_artifacts
    )
    config_path, _, _ = _resolve_manifest_artifact(
        manifest_path, references["dimension_calculation_input"], f"{label}.dimension_calculation_input"
    )
    candidate_path, candidate, _ = _resolve_manifest_artifact(
        manifest_path, references["normalized_candidate"], f"{label}.normalized_candidate"
    )
    inventory_path, inventory, _ = _resolve_manifest_artifact(
        manifest_path, references["item_inventory"], f"{label}.item_inventory"
    )
    old_calc_path, old_calculation, _ = _resolve_manifest_artifact(
        manifest_path, references["v6_calculation"], f"{label}.v6_calculation"
    )
    v5.validate_schema_document(candidate, "candidate-index-v2.schema.json", f"{label} normalized candidate")
    v5.validate_schema_document(inventory, "item-inventory-v2.schema.json", f"{label} item inventory")
    loaded = load_v7_inputs(config_path)
    _verify_historical_v6_calculation(old_calculation, loaded, label=label)
    v5.require(
        v5.sha256_file(candidate_path)
        == old_calculation.get("evidence_identity", {}).get(
            "normalized_candidate_file_sha256"
        ),
        "normalized_candidate_binding_mismatch",
        "The migration must use the exact frozen normalized candidate bound by V6.",
    )
    v5.require(
        v5.sha256_file(inventory_path)
        == old_calculation.get("evidence_identity", {}).get(
            "item_inventory_file_sha256"
        ),
        "item_inventory_binding_mismatch",
        "The migration must use the exact frozen item inventory bound by V6.",
    )
    structure_path = next(
        path
        for path, artifact in zip(loaded["input_paths"], loaded["input_artifacts"])
        if artifact["role"] == "structure_audit"
    )
    legacy_fit_defects = historical_locator_fit_defects(loaded["structure"])
    v6_ledgers, v6_missing = v5.preflight_loaded(loaded)
    v5.require(
        v6_ledgers is not None and not v6_missing,
        "v7_inputs_insufficient",
        "The exact V6 ledgers must validate before locator-fit compatibility is derived.",
        v6_missing,
    )
    fit_preflight = locator_fit_preflight(
        v6_ledgers,
        loaded["config"]["audit_mode"],
        legacy_defects=legacy_fit_defects,
        candidate=candidate,
        inventory=inventory,
    )
    v5.require(
        not fit_preflight["invalid_or_contradictory_state"],
        "v7_inputs_insufficient",
        "The unsupplemented V7 locator-fit preflight found invalid or contradictory states.",
        fit_preflight["invalid_or_contradictory_state"],
    )
    locator_fit_supplement_path: Path | None = None
    locator_fit_supplement: dict[str, Any] | None = None
    locator_fit_supplement_artifact: dict[str, Any] | None = None
    if "locator_fit_supplement" in references:
        # The supplement bytes are intentionally not read until V6 has been
        # independently recalculated and the unsupplemented unresolved set is
        # complete.
        locator_fit_supplement_path, _, _ = _resolve_manifest_artifact(
            manifest_path,
            references["locator_fit_supplement"],
            f"{label}.locator_fit_supplement",
        )
        locator_fit_supplement = _load_locator_fit_supplement(
            locator_fit_supplement_path,
            label=f"{label} supplemental locator fit",
        )
        _validate_locator_fit_supplement(
            locator_fit_supplement,
            supplement_path=locator_fit_supplement_path,
            loaded=loaded,
            config_path=config_path,
            candidate=candidate,
            candidate_path=candidate_path,
            inventory=inventory,
            inventory_path=inventory_path,
            old_calculation=old_calculation,
            old_calculation_path=old_calc_path,
            fit_preflight=fit_preflight,
            representation_provenance_artifacts=representation_provenance_artifacts,
        )
        locator_fit_supplement_artifact = {
            "role": "supplemental_locator_fit",
            "path": os.path.relpath(
                locator_fit_supplement_path, calculation_output.parent
            ).replace(os.sep, "/"),
            "sha256": v5.sha256_file(locator_fit_supplement_path),
            "schema_version": locator_fit_supplement["schema_version"],
        }
    else:
        v5.require(
            not fit_preflight["unresolved_complete_path_fit"],
            "v7_locator_fit_unresolved",
            "The V6-to-V7 migration cannot produce a score while complete-path-fit states remain unresolved.",
            {
                "compatibility_classifications": fit_preflight[
                    "compatibility_classifications"
                ],
                "unresolved_complete_path_fit": fit_preflight[
                    "unresolved_complete_path_fit"
                ],
                "unresolved_reason_counts": fit_preflight[
                    "unresolved_reason_counts"
                ],
                "unresolved_set_sha256": fit_preflight[
                    "unresolved_set_sha256"
                ],
            },
        )
    base_review = derive_structure_locator_review(
        candidate,
        inventory,
        loaded["structure"],
        candidate_file_sha256=v5.sha256_file(candidate_path),
        inventory_file_sha256=v5.sha256_file(inventory_path),
        structure_file_sha256=v5.sha256_file(structure_path),
        audit_mode=loaded["config"]["audit_mode"],
    )
    supplemental_path: Path | None = None
    supplemental_document: dict[str, Any] | None = None
    supplemental_artifact: dict[str, Any] | None = None
    if "supplemental_architecture_review" in references:
        supplemental_path, _, _ = _resolve_manifest_artifact(
            manifest_path,
            references["supplemental_architecture_review"],
            f"{label}.supplemental_architecture_review",
        )
        supplemental_document = _load_supplemental_architecture_review(
            supplemental_path,
            label=f"{label} supplemental architecture review",
        )
        _validate_supplemental_architecture_review(
            supplemental_document,
            loaded=loaded,
            config_path=config_path,
            candidate=candidate,
            candidate_path=candidate_path,
            inventory=inventory,
            inventory_path=inventory_path,
            structure_path=structure_path,
            base_review=base_review,
        )
        review_structure = _structure_with_supplemental_decisions(
            loaded["structure"], supplemental_document
        )
        supplemental_artifact = {
            "role": "supplemental_architecture_review",
            "path": os.path.relpath(
                supplemental_path, calculation_output.parent
            ).replace(os.sep, "/"),
            "sha256": v5.sha256_file(supplemental_path),
            "schema_version": supplemental_document["schema_version"],
        }
        review = derive_structure_locator_review(
            candidate,
            inventory,
            review_structure,
            candidate_file_sha256=v5.sha256_file(candidate_path),
            inventory_file_sha256=v5.sha256_file(inventory_path),
            structure_file_sha256=v5.sha256_file(structure_path),
            audit_mode=loaded["config"]["audit_mode"],
            supplemental_architecture_review_file_sha256=supplemental_artifact[
                "sha256"
            ],
        )
    else:
        review = base_review
    v5.validate_schema_document(review, "structure-locator-review-v1.schema.json", f"{label} V7 structure review")
    validate_structure_locator_review_semantics(review)
    v5.require(review["migration_ready"], "v7_migration_review_incomplete", "The V6-to-V7 score-only migration requires a supplemental architecture review or unreconstructable grouping to be resolved.", review["summary"])
    _write_new(review_output, review)
    review_artifact = {
        "role": "structure_locator_review",
        "path": os.path.relpath(review_output, calculation_output.parent).replace(os.sep, "/"),
        "sha256": v5.sha256_file(review_output),
        "schema_version": review["schema_version"],
    }
    calculation = calculate_loaded(
        loaded,
        structure_review=review,
        structure_review_artifact=review_artifact,
        supplemental_architecture_review_artifact=supplemental_artifact,
        legacy_fit_defects=legacy_fit_defects,
        locator_fit_supplement=locator_fit_supplement,
        locator_fit_supplement_artifact=locator_fit_supplement_artifact,
    )
    if migration_context is not None:
        calculation["migration_context"] = deepcopy(migration_context)
        calculation["calculation_sha256"] = v5.canonical_hash(
            calculation, "calculation_sha256"
        )
    v5.validate_schema_document(calculation, "dimension-calculations-v3.schema.json", f"{label} V7 calculation")
    _write_new(calculation_output, calculation)
    return {
        "loaded": loaded,
        "candidate": candidate,
        "candidate_path": candidate_path,
        "inventory": inventory,
        "inventory_path": inventory_path,
        "old_calculation": old_calculation,
        "old_calculation_path": old_calc_path,
        "review": review,
        "review_path": review_output,
        "calculation": calculation,
        "calculation_path": calculation_output,
        "supplemental_architecture_review": supplemental_document,
        "supplemental_architecture_review_path": supplemental_path,
        "supplemental_architecture_review_artifact": supplemental_artifact,
        "locator_fit_preflight": {
            key: deepcopy(fit_preflight[key])
            for key in (
                "schema_version",
                "deterministically_compatible",
                "unresolved_complete_path_fit",
                "invalid_or_contradictory_state",
                "compatibility_classifications",
                "group_counts",
                "unresolved_reason_counts",
                "unresolved_set_sha256",
                "aggregate_v7_score_available",
                "prose_inference_used",
                "historical_artifacts_modified",
            )
        },
        "locator_fit_supplement": locator_fit_supplement,
        "locator_fit_supplement_path": locator_fit_supplement_path,
        "locator_fit_supplement_artifact": locator_fit_supplement_artifact,
    }


def _artifact_reference(path: Path, container: Path, *, schema_version: str) -> dict[str, Any]:
    return {
        "schema_version": schema_version,
        "artifact_path": v5.portable_relative_reference(path, container, label="artifact_path"),
        "sha256": v5.sha256_file(path),
    }


def _calculation_reference(path: Path, container: Path, calculation: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **_artifact_reference(path, container, schema_version=CALCULATION_SCHEMA),
        "calculation_sha256": calculation["calculation_sha256"],
        "rubric_version": RUBRIC_VERSION,
        "calculation_profile": CALCULATION_PROFILE,
    }


def _historical_reference(path: Path, container: Path, document: Mapping[str, Any]) -> dict[str, Any]:
    record = _artifact_reference(path, container, schema_version=str(document.get("schema_version")))
    if "calculation_sha256" in document:
        record["calculation_sha256"] = document["calculation_sha256"]
    return record


def _supplement_reference(
    path: Path, container: Path, document: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        **_artifact_reference(
            path,
            container,
            schema_version=SUPPLEMENTAL_ARCHITECTURE_REVIEW_SCHEMA,
        ),
        "supplement_id": document["supplement_id"],
        "supplement_sha256": document["supplement_sha256"],
    }


def _locator_fit_supplement_reference(
    path: Path, container: Path, document: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        **_artifact_reference(
            path,
            container,
            schema_version=LOCATOR_FIT_SUPPLEMENT_SCHEMA,
        ),
        "supplement_id": document["supplement_id"],
        "supplement_sha256": document["supplement_sha256"],
        "unresolved_set_sha256": document["scope"][
            "unresolved_set_sha256"
        ],
        "decision_count": len(document["decisions"]),
    }


def _build_projection_metadata(
    old_metadata: Mapping[str, Any],
    canonical: Mapping[str, Any],
    counterfactuals: list[dict[str, Any]],
    output_path: Path,
) -> dict[str, Any]:
    metadata = {
        key: deepcopy(value)
        for key, value in old_metadata.items()
        if key not in {"schema_version", "counterfactual_score_views", "projection_metadata_sha256"}
    }
    metadata["schema_version"] = PROJECTION_METADATA_SCHEMA
    metadata["canonical_calculation"] = _calculation_reference(
        canonical["calculation_path"], output_path, canonical["calculation"]
    )
    metadata["canonical_structure_locator_review"] = _artifact_reference(
        canonical["review_path"], output_path, schema_version=canonical["review"]["schema_version"]
    ) | {"review_sha256": canonical["review"]["review_sha256"]}
    if canonical["locator_fit_supplement"] is not None:
        metadata["canonical_locator_fit_supplement"] = (
            _locator_fit_supplement_reference(
                canonical["locator_fit_supplement_path"],
                output_path,
                canonical["locator_fit_supplement"],
            )
        )
    if counterfactuals:
        metadata["counterfactual_score_views"] = [
            ({
                "view_id": item["view_id"],
                "label": item["label"],
                "calculation": _calculation_reference(
                    item["calculation_path"], output_path, item["calculation"]
                ),
                "structure_locator_review": _artifact_reference(
                    item["review_path"], output_path, schema_version=item["review"]["schema_version"]
                ) | {"review_sha256": item["review"]["review_sha256"]},
                "provenance_artifacts": [
                    {
                        "role": provenance["role"],
                        "schema_version": provenance["schema_version"],
                        "artifact_path": v5.portable_relative_reference(
                            provenance["path"], output_path, label="counterfactual provenance"
                        ),
                        "sha256": provenance["sha256"],
                    }
                    for provenance in item["provenance_artifacts"]
                ],
            }
            | (
                {
                    "locator_fit_supplement": _locator_fit_supplement_reference(
                        item["locator_fit_supplement_path"],
                        output_path,
                        item["locator_fit_supplement"],
                    )
                }
                if item["locator_fit_supplement"] is not None
                else {}
            ))
            for item in counterfactuals
        ]
    metadata["projection_metadata_sha256"] = v5.canonical_hash(
        metadata, "projection_metadata_sha256"
    )
    return metadata


def _build_score_views(
    canonical: Mapping[str, Any],
    counterfactuals: list[dict[str, Any]],
    web_output: Path,
) -> dict[str, Any]:
    views = [
        ({
            "view_id": "canonical_as_delivered",
            "label": "Canonical as delivered",
            "view_kind": "observed",
            "score": canonical["calculation"]["total_score"],
            "maximum": 100,
            "calculation": _calculation_reference(
                canonical["calculation_path"], web_output, canonical["calculation"]
            ),
            "structure_locator_review": _artifact_reference(
                canonical["review_path"], web_output, schema_version=canonical["review"]["schema_version"]
            ) | {"review_sha256": canonical["review"]["review_sha256"]},
            "causal_attribution": "primary_observed_result",
            "provenance_artifacts": [],
        }
        | (
            {
                "locator_fit_supplement": _locator_fit_supplement_reference(
                    canonical["locator_fit_supplement_path"],
                    web_output,
                    canonical["locator_fit_supplement"],
                )
            }
            if canonical["locator_fit_supplement"] is not None
            else {}
        ))
    ]
    for item in counterfactuals:
        views.append(
            ({
                "view_id": item["view_id"],
                "label": item["label"],
                "view_kind": "counterfactual",
                "score": item["calculation"]["total_score"],
                "maximum": 100,
                "calculation": _calculation_reference(
                    item["calculation_path"], web_output, item["calculation"]
                ),
                "structure_locator_review": _artifact_reference(
                    item["review_path"], web_output, schema_version=item["review"]["schema_version"]
                ) | {"review_sha256": item["review"]["review_sha256"]},
                "causal_attribution": "separate_evidentiary_correction_not_methodology_effect",
                "provenance_artifacts": [
                    {
                        "role": provenance["role"],
                        "schema_version": provenance["schema_version"],
                        "artifact_path": v5.portable_relative_reference(
                            provenance["path"], web_output, label="score-view provenance"
                        ),
                        "sha256": provenance["sha256"],
                    }
                    for provenance in item["provenance_artifacts"]
                ],
            }
            | (
                {
                    "locator_fit_supplement": _locator_fit_supplement_reference(
                        item["locator_fit_supplement_path"],
                        web_output,
                        item["locator_fit_supplement"],
                    )
                }
                if item["locator_fit_supplement"] is not None
                else {}
            ))
        )
    return {
        "primary_view_id": "canonical_as_delivered",
        "adjustment_status": "separate_evidentiary_correction" if counterfactuals else "none",
        "views": views,
    }


def _build_result_and_web(
    *,
    canonical: Mapping[str, Any],
    items: Mapping[str, Any],
    items_path: Path,
    metadata: Mapping[str, Any],
    migration: Mapping[str, Any],
    migration_path: Path,
    projection_metadata_path: Path,
    counterfactuals: list[dict[str, Any]],
    result_output: Path,
    web_output: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    calculation = canonical["calculation"]
    identity = calculation["evidence_identity"]
    gates = deepcopy(metadata["critical_gates"])
    gate_hash = v5.canonical_hash({"critical_gates": gates})
    calculation_ref_result = _artifact_reference(
        canonical["calculation_path"], result_output, schema_version=CALCULATION_SCHEMA
    ) | {"calculation_profile": CALCULATION_PROFILE}
    item_ref_result = _artifact_reference(
        items_path, result_output, schema_version=ITEM_ASSESSMENT_SCHEMA
    ) | {"grading_policy": ITEM_GRADING_POLICY, "summary": deepcopy(items["summary"])}
    migration_ref_result = _artifact_reference(
        migration_path, result_output, schema_version=MIGRATION_SCHEMA
    ) | {"migration_sha256": migration["migration_sha256"]}
    review_ref_result = _artifact_reference(
        canonical["review_path"], result_output, schema_version=canonical["review"]["schema_version"]
    ) | {"review_sha256": canonical["review"]["review_sha256"], "summary": deepcopy(canonical["review"]["summary"])}
    result = {
        "schema_version": RESULT_SCHEMA,
        "evaluation_id": calculation["evaluation_id"],
        "candidate": {"label": metadata["candidate_label"], "sha256": identity["candidate_sha256"]},
        "provenance": {
            "source_sha256": identity["source_sha256"],
            "judgment_policy_sha256": identity["policy_sha256"],
            "benchmark_sha256": identity["benchmark_sha256"],
            "rubric_version": RUBRIC_VERSION,
            "dimension_calculation_profile": CALCULATION_PROFILE,
        },
        "audit_scope": {"mode": calculation["audit_mode"], "complete": calculation["audit_mode"] == "full"},
        "dimension_calculations": calculation_ref_result,
        "scorecard": scorecard_projection(calculation),
        "total_score": calculation["total_score"],
        "interpretation": metadata.get("interpretation", "V7 score reconstructed from frozen structured evidence."),
        "metrics": {"locator_precision": precision_diagnostics(calculation)},
        "item_assessments": item_ref_result,
        "structure_locator_review": review_ref_result,
        "score_migration": migration_ref_result,
        "projection_metadata": _artifact_reference(projection_metadata_path, result_output, schema_version=PROJECTION_METADATA_SCHEMA) | {"projection_metadata_sha256": metadata["projection_metadata_sha256"]},
        "critical_gates": gates,
        "defect_counts": deepcopy(metadata.get("defect_counts", {})) | {"v7_removed_historical_structure_defects": len(canonical["review"]["summary"]["removed_historical_defect_ids"])},
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
        "limitations": deepcopy(metadata.get("limitations", [])),
    }
    result["locator_fit_compatibility"] = deepcopy(
        calculation["locator_fit_compatibility"]
    )
    if canonical["locator_fit_supplement"] is not None:
        result["locator_fit_supplement"] = _locator_fit_supplement_reference(
            canonical["locator_fit_supplement_path"],
            result_output,
            canonical["locator_fit_supplement"],
        )
    score_views = _build_score_views(canonical, counterfactuals, web_output)
    web = {
        "schema_version": WEB_REPORT_SCHEMA,
        "report_id": metadata.get("report_id", f"{calculation['evaluation_id']}-v7"),
        "headline": metadata.get("headline", "Subject-index evaluation"),
        "summary": metadata.get("summary", "V7 source-grounded evaluation."),
        "grade": {"score": calculation["total_score"], "maximum": 100, "label": grade_label(calculation["total_score"])},
        "scorecard": scorecard_projection(calculation, web=True),
        "calculation_explainer": _calculation_reference(canonical["calculation_path"], web_output, calculation) | {"item_grades_used": False, "gates_used": False},
        "precision_diagnostics": precision_diagnostics(calculation),
        "structure_locator_review": _artifact_reference(canonical["review_path"], web_output, schema_version=canonical["review"]["schema_version"]) | {"review_sha256": canonical["review"]["review_sha256"], "thresholds": deepcopy(canonical["review"]["thresholds"]), "summary": deepcopy(canonical["review"]["summary"]), "path_reviews": deepcopy(canonical["review"]["path_reviews"])},
        "key_metrics": [],
        "density": {},
        "gate_status": {"critical_gates": gates, "outcomes_sha256": gate_hash, "used_in_score_arithmetic": False},
        "strengths": deepcopy(metadata.get("strengths", [])),
        "defects": deepcopy(metadata.get("defects", [])),
        "examples": deepcopy(metadata.get("examples", [])),
        "item_grade_index": _artifact_reference(items_path, web_output, schema_version=ITEM_ASSESSMENT_SCHEMA) | {"grading_policy": ITEM_GRADING_POLICY, "summary": deepcopy(items["summary"]), "color_legend": deepcopy(items["color_legend"]), "interaction": {"color_source": "grade.color_token", "popover_source": "popover", "not_measured_behavior": "neutral_not_failure", "locator_string_language": "displayed_and_atomic_counts_separate"}},
        "migration_comparison": {
            "status": "v6_to_v7",
            "migration_record": _artifact_reference(migration_path, web_output, schema_version=MIGRATION_SCHEMA) | {"migration_sha256": migration["migration_sha256"]},
            "methodology_commit": migration["methodology"]["implementation_commit"],
            "previous_total": migration["from"]["total_score"],
            "migrated_total": migration["to"]["total_score"],
            "dimension_comparison": deepcopy(migration["dimension_comparison"]),
            "gate_comparison": deepcopy(migration["gate_preservation"]),
            "structure_count_correction": deepcopy(migration["structure_count_correction"]),
        },
        "score_views": score_views,
        "methodology": {
            "rubric_version": RUBRIC_VERSION,
            "calculation_profile": CALCULATION_PROFILE,
            "locator_utility": "The lower of independent page-treatment and complete-path-fit scores.",
            "minimum_rule": "Avoids double-counting a limitation shared by mixed treatment and partial fit.",
            "strict_precision": "Public substantive-validity diagnostic; not the two-axis precision.",
            "editorial_selectivity_separate": True,
            "long_string_review": "More than six displayed locators triggers review; a range counts once.",
            "long_range_review": "A continuous range longer than ten pages triggers separate review.",
            "numeric_trigger_is_automatic_defect": False,
        },
        "comparability": {"v6_and_v7_directly_comparable": False, "reason": "Page-reference Reliability uses a new calculation profile; a deterministic structure counting correction may also affect Findability and Navigation."},
        "disclosures": [
            "A displayed locator is one delivered page reference or continuous range; expanded pages remain atomic audit assignments.",
            "Weak presence places a 0.25 ceiling on locator utility and remains non-substantive for Editorial Selectivity.",
            "Caps and publication-readiness gates remain independent of locator credit.",
        ],
        "limitations": deepcopy(metadata.get("limitations", [])),
        "evidence_index": {},
    }
    web["locator_fit_compatibility"] = deepcopy(
        calculation["locator_fit_compatibility"]
    )
    if canonical["locator_fit_supplement"] is not None:
        web["locator_fit_supplement"] = _locator_fit_supplement_reference(
            canonical["locator_fit_supplement_path"],
            web_output,
            canonical["locator_fit_supplement"],
        )
    return result, web


def command_migrate(args: argparse.Namespace) -> None:
    command = "v6-to-v7-score-only-migration"
    try:
        manifest_path = Path(args.manifest).resolve()
        manifest = v5.load_json(manifest_path, "V6-to-V7 migration input")
        v5.validate_schema_document(manifest, "v7-migration-input.schema.json", "V6-to-V7 migration input")
        output_dir = Path(args.output_directory).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        canonical_refs = manifest["canonical"]
        old_calc_path, old_calc, _ = _resolve_manifest_artifact(manifest_path, canonical_refs["v6_calculation"], "canonical.v6_calculation")
        old_result_path, old_result, _ = _resolve_manifest_artifact(manifest_path, canonical_refs["v6_evaluation_result"], "canonical.v6_evaluation_result")
        old_items_path, old_items, _ = _resolve_manifest_artifact(manifest_path, canonical_refs["v6_item_assessments"], "canonical.v6_item_assessments")
        old_web_path, old_web, _ = _resolve_manifest_artifact(manifest_path, canonical_refs["v6_web_report"], "canonical.v6_web_report")
        old_metadata_path, old_metadata, _ = _resolve_manifest_artifact(manifest_path, canonical_refs["v6_projection_metadata"], "canonical.v6_projection_metadata")
        repository_state = manifest["repository_state"]
        v5.require(
            repository_state["frozen_benchmark_sha256"]
            == old_calc.get("evidence_identity", {}).get("benchmark_sha256"),
            "frozen_benchmark_identity_mismatch",
            "The manifest's frozen benchmark identity does not match the exact V6 calculation.",
        )
        v6.validate_projection_artifacts(old_calc_path, old_result_path, old_web_path)
        v5.validate_schema_document(old_items, "item-assessments-v3.schema.json", "Historical V6 item assessments")
        v5.validate_schema_document(old_metadata, "v6-projection-metadata.schema.json", "Historical V6 projection metadata")
        v5.require(old_result.get("critical_gates") == old_metadata.get("critical_gates"), "historical_v6_gate_metadata_mismatch", "V6 result and projection metadata gates differ.")
        bound_old_items = v5.resolve_referenced_artifact(old_result["item_assessments"], old_result_path, label="historical V6 item assessments")
        v5.require_same_artifact(bound_old_items, old_items_path, label="historical V6 item assessments")

        migration_output = output_dir / "score-migration.v6-to-v7.json"
        canonical_review_output = output_dir / "structure-locator-review.v7.json"
        canonical_calc_output = output_dir / "dimension-calculations.v7.json"
        item_output = output_dir / "item-assessments.v7.json"
        metadata_output = output_dir / "projection-metadata.v7.json"
        result_output = output_dir / "evaluation-result.v7.json"
        web_output = output_dir / "web-report.v7.json"
        receipt_output = output_dir / "validation-receipt.v7.json"
        gate_hash = v5.canonical_hash({"critical_gates": old_result["critical_gates"]})
        migration_context = {
            "from_rubric_version": "subject-index-rubric-v6",
            "migration_schema_version": MIGRATION_SCHEMA,
            "migration_record_path": os.path.relpath(migration_output, canonical_calc_output.parent).replace(os.sep, "/"),
            "historical_calculation_sha256": v5.sha256_file(old_calc_path),
            "historical_result_sha256": v5.sha256_file(old_result_path),
            "historical_item_assessments_sha256": v5.sha256_file(old_items_path),
            "historical_web_report_sha256": v5.sha256_file(old_web_path),
            "historical_gate_outcomes_sha256": gate_hash,
            "gate_outcomes_action": "preserve_identically",
        }
        canonical = _migrate_calculation_view(
            manifest_path=manifest_path,
            references=canonical_refs,
            review_output=canonical_review_output,
            calculation_output=canonical_calc_output,
            migration_context=migration_context,
            label="canonical",
        )
        v5.require(canonical["old_calculation"]["calculation_sha256"] == old_calc["calculation_sha256"], "historical_v6_calculation_binding_mismatch", "Canonical migration references resolve to different V6 calculations.")

        old_views = {
            item["view_id"]: item
            for item in old_web.get("score_views", {}).get("views", [])
            if item.get("view_kind") == "counterfactual"
        }
        declared_counterfactuals = {item["view_id"]: item for item in manifest["counterfactuals"]}
        v5.require(set(old_views) == set(declared_counterfactuals), "counterfactual_migration_manifest_incomplete", "Every and only historical V6 counterfactual score view requires its own frozen calculation input and provenance binding.", {"historical": sorted(old_views), "declared": sorted(declared_counterfactuals)})
        counterfactuals: list[dict[str, Any]] = []
        for view_id in sorted(old_views):
            old_view = old_views[view_id]
            refs = declared_counterfactuals[view_id]
            bound_old_view_calc = v5.resolve_referenced_artifact(
                old_view["calculation"],
                old_web_path,
                label=f"historical score view {view_id}",
            )
            provenance_artifacts = []
            for index, provenance in enumerate(
                old_view.get("provenance_artifacts", [])
            ):
                provenance_path = v5.resolve_referenced_artifact(
                    provenance,
                    old_web_path,
                    label=f"historical score view {view_id} provenance[{index}]",
                )
                provenance_artifacts.append(
                    {
                        "role": provenance["role"],
                        "schema_version": provenance["schema_version"],
                        "path": provenance_path,
                        "sha256": v5.sha256_file(provenance_path),
                    }
                )
            migrated = _migrate_calculation_view(
                manifest_path=manifest_path,
                references=refs,
                review_output=output_dir / "score-views" / f"{view_id}.structure-locator-review.v7.json",
                calculation_output=output_dir / "score-views" / f"{view_id}.dimension-calculations.v7.json",
                migration_context=None,
                label=f"counterfactual:{view_id}",
                representation_provenance_artifacts=provenance_artifacts,
            )
            v5.require_same_artifact(bound_old_view_calc, migrated["old_calculation_path"], label=f"historical score view {view_id}")
            migrated |= {"view_id": view_id, "label": old_view["label"], "provenance_artifacts": provenance_artifacts}
            counterfactuals.append(migrated)

        projection_metadata = _build_projection_metadata(old_metadata, canonical, counterfactuals, metadata_output)
        v5.validate_schema_document(projection_metadata, "v7-projection-metadata.schema.json", "Generated V7 projection metadata")
        _write_new(metadata_output, projection_metadata)
        items = _build_v7_item_projection(
            loaded=canonical["loaded"],
            candidate=canonical["candidate"],
            inventory=canonical["inventory"],
            inventory_path=canonical["inventory_path"],
            historical_items=old_items,
            calculation=canonical["calculation"],
            review=canonical["review"],
            output_path=item_output,
        )
        _write_new(item_output, items)
        dimension_comparison = _dimension_comparison(old_calc, canonical["calculation"], canonical["review"])
        supplemental_view_inputs = [
            {
                "view_id": view_id,
                "path": view["supplemental_architecture_review_path"],
                "document": view["supplemental_architecture_review"],
            }
            for view_id, view in [
                ("canonical_as_delivered", canonical),
                *((item["view_id"], item) for item in counterfactuals),
            ]
            if view["supplemental_architecture_review"] is not None
        ]
        supplemental_migration_references = [
            {
                "view_id": item["view_id"],
                "artifact": _supplement_reference(
                    item["path"], migration_output, item["document"]
                ),
            }
            for item in supplemental_view_inputs
        ]
        locator_fit_view_inputs = [
            {
                "view_id": view_id,
                "path": view["locator_fit_supplement_path"],
                "document": view["locator_fit_supplement"],
            }
            for view_id, view in [
                ("canonical_as_delivered", canonical),
                *((item["view_id"], item) for item in counterfactuals),
            ]
            if view["locator_fit_supplement"] is not None
        ]
        locator_fit_migration_references = [
            {
                "view_id": item["view_id"],
                "artifact": _locator_fit_supplement_reference(
                    item["path"], migration_output, item["document"]
                ),
            }
            for item in locator_fit_view_inputs
        ]
        semantic_scopes = {
            (False, False): "none",
            (True, False): "supplemental_architecture_review_only",
            (False, True): "supplemental_locator_fit_only",
            (True, True): "supplemental_architecture_and_locator_fit",
        }
        semantic_scope = semantic_scopes[
            (
                bool(supplemental_migration_references),
                bool(locator_fit_migration_references),
            )
        ]
        migrated_views = [
            ("canonical_as_delivered", canonical),
            *((item["view_id"], item) for item in counterfactuals),
        ]
        migration = {
            "schema_version": MIGRATION_SCHEMA,
            "migration_id": "",
            "evaluation_id": canonical["calculation"]["evaluation_id"],
            "tool": {"name": TOOL_NAME, "version": TOOL_VERSION},
            "methodology": deepcopy(manifest["methodology"]),
            "repository_state": deepcopy(repository_state),
            "from": {
                "rubric_version": "subject-index-rubric-v6",
                "calculation_profile": "subject-index-dimension-calculation-v2",
                "calculation": _historical_reference(old_calc_path, migration_output, old_calc),
                "evaluation_result": _historical_reference(old_result_path, migration_output, old_result),
                "item_assessments": _historical_reference(old_items_path, migration_output, old_items),
                "web_report": _historical_reference(old_web_path, migration_output, old_web),
                "projection_metadata": _historical_reference(old_metadata_path, migration_output, old_metadata),
                "total_score": old_calc["total_score"],
                "score_views": deepcopy(old_web["score_views"]),
            },
            "to": {
                "rubric_version": RUBRIC_VERSION,
                "calculation_profile": CALCULATION_PROFILE,
                "calculation": _calculation_reference(canonical_calc_output, migration_output, canonical["calculation"]),
                "item_assessments": _artifact_reference(item_output, migration_output, schema_version=ITEM_ASSESSMENT_SCHEMA),
                "projection_metadata": _artifact_reference(metadata_output, migration_output, schema_version=PROJECTION_METADATA_SCHEMA) | {"projection_metadata_sha256": projection_metadata["projection_metadata_sha256"]},
                "structure_locator_review": _artifact_reference(canonical_review_output, migration_output, schema_version=canonical["review"]["schema_version"]) | {"review_sha256": canonical["review"]["review_sha256"]},
                "total_score": canonical["calculation"]["total_score"],
                "score_views": _build_score_views(
                    canonical, counterfactuals, migration_output
                ),
                "counterfactual_calculations": [
                    {
                        "view_id": item["view_id"],
                        "calculation": _calculation_reference(
                            item["calculation_path"],
                            migration_output,
                            item["calculation"],
                        ),
                        "structure_locator_review": _artifact_reference(
                            item["review_path"],
                            migration_output,
                            schema_version=item["review"]["schema_version"],
                        )
                        | {"review_sha256": item["review"]["review_sha256"]},
                        "provenance_artifacts": [
                            {
                                "role": provenance["role"],
                                "schema_version": provenance["schema_version"],
                                "artifact_path": v5.portable_relative_reference(
                                    provenance["path"],
                                    migration_output,
                                    label="migration counterfactual provenance",
                                ),
                                "sha256": provenance["sha256"],
                            }
                            for provenance in item["provenance_artifacts"]
                        ],
                        **(
                            {
                                "locator_fit_supplement": _locator_fit_supplement_reference(
                                    item["locator_fit_supplement_path"],
                                    migration_output,
                                    item["locator_fit_supplement"],
                                )
                            }
                            if item["locator_fit_supplement"] is not None
                            else {}
                        ),
                    }
                    for item in counterfactuals
                ],
            },
            "frozen_evidence": {
                "evidence_identity": deepcopy(canonical["calculation"]["evidence_identity"]),
                "historical_input_artifacts": [{**deepcopy(item), "disposition": "unchanged_byte_for_byte"} for item in old_calc["input_artifacts"]],
                "normalized_candidate": _historical_reference(canonical["candidate_path"], migration_output, canonical["candidate"]),
                "item_inventory": _historical_reference(canonical["inventory_path"], migration_output, canonical["inventory"]),
                "supplemental_architecture_reviews": supplemental_migration_references,
                "supplemental_locator_fit_supplements": locator_fit_migration_references,
                "source_pages_reopened": False,
                "prose_inference_used": False,
                "semantic_judgments_added": semantic_scope != "none",
                "semantic_judgment_scope": semantic_scope,
                "historical_artifacts_modified": False,
            },
            "dimension_comparison": dimension_comparison,
            "precision_comparison": {"v6": {"weighted_locator_precision": v6.precision_diagnostics(old_calc)["weighted_locator_precision"], "strict_substantive_precision": v6.precision_diagnostics(old_calc)["strict_substantive_precision"]}, "v7": precision_diagnostics(canonical["calculation"])},
            "gate_preservation": {"historical_gate_outcomes_sha256": gate_hash, "preserved_gate_outcomes_sha256": gate_hash, "historical_outcomes": deepcopy(old_result["critical_gates"]), "preserved_outcomes": deepcopy(old_result["critical_gates"]), "outcomes_equal": True},
            "structure_count_correction": {"thresholds": deepcopy(canonical["review"]["thresholds"]), "path_dispositions": [{key: deepcopy(item[key]) for key in ("path_id", "displayed_locator_count", "maximum_range_span", "atomic_assignment_count", "long_displayed_locator_string_review_trigger", "long_continuous_range_review_trigger", "applicable_structured_defect_ids", "removed_structured_defect_ids", "retained_structured_defect_ids", "historical_defect_dispositions", "final_architecture_disposition", "deterministic_mapping_rule_id")} for item in canonical["review"]["path_reviews"]], "removed_historical_defect_ids": deepcopy(canonical["review"]["summary"]["removed_historical_defect_ids"]), "new_defects_created_from_numeric_triggers": False},
            "locator_fit_supplementation": {
                "supplemental_judgments_added": bool(
                    locator_fit_migration_references
                ),
                "scope": (
                    "complete_path_fit_only"
                    if locator_fit_migration_references
                    else "none"
                ),
                "views": [
                    {
                        "view_id": view_id,
                        "unresolved_set_count_before_supplementation": len(
                            view["locator_fit_preflight"][
                                "unresolved_complete_path_fit"
                            ]
                        ),
                        "unresolved_set_count_after_supplementation": 0,
                        "unresolved_locator_ids": [
                            item["locator_id"]
                            for item in view["locator_fit_preflight"][
                                "unresolved_complete_path_fit"
                            ]
                        ],
                        "unresolved_records_without_supplement": deepcopy(
                            view["locator_fit_preflight"][
                                "unresolved_complete_path_fit"
                            ]
                        ),
                        "unresolved_reason_counts_without_supplement": deepcopy(
                            view["locator_fit_preflight"][
                                "unresolved_reason_counts"
                            ]
                        ),
                        "preflight_group_counts": deepcopy(
                            view["locator_fit_preflight"]["group_counts"]
                        ),
                        "conflict_routed_locator_ids": [
                            item["locator_id"]
                            for item in view["locator_fit_preflight"][
                                "unresolved_complete_path_fit"
                            ]
                            if item["reason_code"]
                            == LEGACY_FIT_CONFLICT_REASON_CODE
                        ],
                        "unresolved_set_sha256": view[
                            "locator_fit_preflight"
                        ]["unresolved_set_sha256"],
                        "compatibility_classifications_without_supplement": deepcopy(
                            view["locator_fit_preflight"][
                                "compatibility_classifications"
                            ]
                        ),
                        "supplement": (
                            _locator_fit_supplement_reference(
                                view["locator_fit_supplement_path"],
                                migration_output,
                                view["locator_fit_supplement"],
                            )
                            if view["locator_fit_supplement"] is not None
                            else None
                        ),
                    }
                    for view_id, view in migrated_views
                ],
                "historical_artifacts_unchanged": True,
                "non_fit_judgments_unchanged": True,
                "numerical_fit_credit_manually_supplied": False,
                "combined_credit_manually_supplied": False,
                "grade_manually_supplied": False,
                "dimension_or_total_score_manually_supplied": False,
            },
            "invariants": {"only_calculation_and_display_artifacts_rebuilt": True, "locator_support_and_missing_access_unchanged": True, "non_reliability_dimensions_unchanged_except_deterministic_structure_correction": True, "gates_unchanged": True, "representation_views_recalculated_from_own_inputs": True, "supplemental_review_narrowly_scoped_and_hash_bound": True, "oxford_artifacts_modified": False, "formula_tuned_to_oxford_result": False},
            "migration_sha256": "",
        }
        migration["invariants"].update(
            {
                "locator_fit_supplement_applied_in_memory_only": True,
                "legacy_fit_conflict_rule_id": LEGACY_FIT_CONFLICT_RULE_ID,
                "legacy_fit_conflicts_routed_without_precedence": True,
                "historical_fit_classifier_records_modified": False,
                "invalid_states_supplement_eligible": False,
                "bare_loc_pos_automatically_mapped": False,
                "evaluation_specific_fit_rule_added": False,
                "evaluation_result_used_as_target": False,
            }
        )
        migration["migration_id"] = f"MIG-{v5.canonical_hash(migration)[:12].upper()}"
        migration["migration_sha256"] = v5.canonical_hash(migration, "migration_sha256")
        v5.validate_schema_document(migration, "score-migration-v6-to-v7.schema.json", "Generated V6-to-V7 migration")
        _write_new(migration_output, migration)
        result, web = _build_result_and_web(canonical=canonical, items=items, items_path=item_output, metadata=projection_metadata, migration=migration, migration_path=migration_output, projection_metadata_path=metadata_output, counterfactuals=counterfactuals, result_output=result_output, web_output=web_output)
        v5.validate_schema_document(result, "evaluation-result-v8.schema.json", "Generated V7 result")
        v5.validate_schema_document(web, "web-report-v6.schema.json", "Generated V7 web report")
        _write_new(result_output, result)
        _write_new(web_output, web)
        receipt = {
            "schema_version": VALIDATION_RECEIPT_SCHEMA,
            "receipt_id": "",
            "evaluation_id": canonical["calculation"]["evaluation_id"],
            "migration": _artifact_reference(migration_output, receipt_output, schema_version=MIGRATION_SCHEMA) | {"migration_sha256": migration["migration_sha256"]},
            "active_projections": {name: _artifact_reference(path, receipt_output, schema_version=document["schema_version"]) for name, path, document in (("calculation", canonical_calc_output, canonical["calculation"]), ("result", result_output, result), ("item_assessments", item_output, items), ("web_report", web_output, web), ("projection_metadata", metadata_output, projection_metadata), ("structure_locator_review", canonical_review_output, canonical["review"]))},
            "historical_projections": {name: _historical_reference(path, receipt_output, document) for name, path, document in (("calculation", old_calc_path, old_calc), ("result", old_result_path, old_result), ("item_assessments", old_items_path, old_items), ("web_report", old_web_path, old_web), ("projection_metadata", old_metadata_path, old_metadata))},
            "counterfactual_projections": [{"view_id": item["view_id"], "calculation": _calculation_reference(item["calculation_path"], receipt_output, item["calculation"]), "structure_locator_review": _artifact_reference(item["review_path"], receipt_output, schema_version=item["review"]["schema_version"]) | {"review_sha256": item["review"]["review_sha256"]}, "provenance_sha256": sorted(provenance["sha256"] for provenance in item["provenance_artifacts"])} for item in counterfactuals],
            "supplemental_architecture_reviews": [
                {
                    "view_id": item["view_id"],
                    "artifact": _supplement_reference(
                        item["path"], receipt_output, item["document"]
                    ),
                }
                for item in supplemental_view_inputs
            ],
            "supplemental_locator_fit_supplements": [
                {
                    "view_id": item["view_id"],
                    "artifact": _locator_fit_supplement_reference(
                        item["path"], receipt_output, item["document"]
                    ),
                }
                for item in locator_fit_view_inputs
            ],
            "validation": {"all_hashes_recomputed": True, "all_schemas_valid": True, "historical_bytes_unchanged": True, "calculation_hash_valid": canonical["calculation"]["calculation_sha256"] == v5.canonical_hash(canonical["calculation"], "calculation_sha256"), "migration_hash_valid": migration["migration_sha256"] == v5.canonical_hash(migration, "migration_sha256"), "structure_review_hash_valid": canonical["review"]["review_sha256"] == structure_review_hash(canonical["review"], "review_sha256"), "supplemental_review_hash_valid": all(item["document"]["supplement_sha256"] == v5.canonical_hash(item["document"], "supplement_sha256") for item in supplemental_view_inputs), "supplemental_review_scope_exact": all(view["review"]["summary"]["review_required_path_ids"] == [] for view in [canonical, *counterfactuals]), "locator_fit_supplement_hash_valid": all(item["document"]["supplement_sha256"] == v5.canonical_hash(item["document"], "supplement_sha256") for item in locator_fit_view_inputs), "locator_fit_supplement_scope_exact": all(view["calculation"]["locator_fit_compatibility"]["unresolved_after_supplement"] == 0 for _, view in migrated_views), "locator_fit_supplement_non_fit_fields_unchanged": True, "locator_fit_supplement_contains_no_manual_numerical_credit_or_score": True, "legacy_fit_conflict_routing_valid": True, "legacy_fit_conflict_provenance_complete": True, "invalid_states_excluded_from_unresolved_set": True, "aggregate_score_absent_during_preflight_and_adjudication": True, "decimal_safe_projection_validation": True, "gate_outcomes_equal": True, "representation_provenance_complete": True},
            "receipt_sha256": "",
        }
        receipt["receipt_id"] = f"VAL-{v5.canonical_hash(receipt)[:12].upper()}"
        receipt["receipt_sha256"] = v5.canonical_hash(receipt, "receipt_sha256")
        v5.validate_schema_document(receipt, "score-migration-v6-to-v7-validation.schema.json", "Generated V7 validation receipt")
        _write_new(receipt_output, receipt)
        v5.emit({"command": command, "ok": True, "evaluation_id": canonical["calculation"]["evaluation_id"], "historical_total": old_calc["total_score"], "v7_total": canonical["calculation"]["total_score"], "removed_historical_structure_defects": canonical["review"]["summary"]["removed_historical_defect_ids"], "counterfactual_view_count": len(counterfactuals), "migration_sha256": migration["migration_sha256"], "validation_receipt_sha256": receipt["receipt_sha256"], "output_directory": str(output_dir)})
    except (OSError, ValueError, v5.CalculationError, StructureReviewError) as exc:
        if isinstance(exc, (v5.CalculationError, StructureReviewError)):
            error = {"code": exc.code, "message": exc.message, "details": exc.details}
        else:
            error = {"code": "migration_error", "message": str(exc)}
        v5.emit({"command": command, "ok": False, "error": error}, 1)


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
    migrate = subparsers.add_parser(
        "migrate-v6-to-v7",
        help="Perform a fail-closed, hash-bound V6-to-V7 score-only migration.",
    )
    migrate.add_argument("--manifest", required=True)
    migrate.add_argument("--output-directory", required=True)
    migrate.set_defaults(func=command_migrate)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
