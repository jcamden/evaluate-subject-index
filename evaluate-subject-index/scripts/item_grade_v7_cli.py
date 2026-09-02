#!/usr/bin/env python3
"""Build V7 diagnostic item projections from a frozen V7 calculation ledger."""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

import dimension_score_cli as v5
import item_grade_cli as legacy
from structure_locator_review import (
    StructureReviewError,
    canonical_hash as structure_review_hash,
    validate_structure_locator_review_semantics,
)


SCHEMA_VERSION = "subject-index-item-assessments-v5"
GRADING_POLICY = "subject-index-item-grading-v3"


def _decimal(value: Any) -> Decimal | None:
    return None if value is None else v5.decimal_value(value)


def _grade_score(value: Decimal | None) -> int | float | None:
    if value is None:
        return None
    score = value * Decimal(100)
    return int(score) if score == score.to_integral() else float(score)


def _reliability(calculation: Mapping[str, Any]) -> Mapping[str, Any]:
    matches = [
        item
        for item in calculation.get("dimensions", [])
        if item.get("dimension_id") == "page_reference_reliability"
    ]
    if len(matches) != 1:
        raise ValueError("v7_reliability_dimension_required")
    return matches[0]


def _score_text(value: int | float | None) -> str:
    if value is None:
        return "not measured"
    return str(value)


def _fit_rationale_required(assignment: Mapping[str, Any]) -> bool:
    treatment_score = _decimal(assignment.get("treatment_score"))
    fit_score = _decimal(assignment.get("fit_score"))
    return bool(
        treatment_score != fit_score
        or fit_score != Decimal("1")
        or assignment.get("supplemental_fit_decision_id")
        or "F-COMPAT-LEGACY-FIT-CONFLICT-TO-SUPPLEMENT-V1"
        in assignment.get("compatibility_rule_ids", [])
    )


def _mechanical_fit_rationale(assignment: Mapping[str, Any]) -> str:
    score = _grade_score(_decimal(assignment["fit_score"]))
    category = str(assignment["fit_category"]).replace("_", " ")
    return (
        f"{category.capitalize()} ({_score_text(score)}/100) follows mechanically from "
        f"{assignment['fit_rule_id']} and the structured complete-path judgment."
    )


def _locator_explanation(
    assessment: Mapping[str, Any],
    assignment: Mapping[str, Any],
    judgment: Mapping[str, Any] | None,
    supplemental_rationale: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], bool]:
    evidence_summary = str(
        (judgment or {}).get("evidence_summary", assessment.get("summary", ""))
    ).strip()
    if not evidence_summary:
        raise ValueError(f"locator_evidence_summary_required:{assignment['locator_id']}")
    rationale_required = _fit_rationale_required(assignment)
    legacy_compatibility = False
    if supplemental_rationale is not None:
        fit_rationale = str(supplemental_rationale["rationale"]).strip()
        fit_rationale_source = str(supplemental_rationale["source"])
    elif judgment is not None and str(judgment.get("fit_rationale", "")).strip():
        fit_rationale = str(judgment["fit_rationale"]).strip()
        fit_rationale_source = "authored_locator_audit"
    elif rationale_required:
        schema_version = None if judgment is None else judgment.get("_audit_schema_version")
        if schema_version == "locator-audit-v2":
            raise ValueError(f"fit_rationale_required:{assignment['locator_id']}")
        fit_rationale = None
        fit_rationale_source = "historical_contract_not_available"
        legacy_compatibility = True
    else:
        fit_rationale = _mechanical_fit_rationale(assignment)
        fit_rationale_source = "mechanical_structured_category_rule"

    treatment_score = _grade_score(_decimal(assignment["treatment_score"]))
    fit_score = _grade_score(_decimal(assignment["fit_score"]))
    combined_score = assignment["diagnostic_grade"]
    evidence_ids = sorted(
        {
            *assessment.get("evidence_ids", []),
            assignment["locator_id"],
            *assignment["applicable_structured_defect_ids"],
            *assignment.get("supplemental_fit_evidence_ids", []),
        }
    )
    return (
        {
            "locator_id": assignment["locator_id"],
            "path_id": assessment["path_id"],
            "evidence_summary": evidence_summary,
            "page_treatment": {
                "category": assignment["treatment_category"],
                "score": treatment_score,
                "rule_id": assignment["treatment_rule_id"],
                "rationale": evidence_summary,
                "rationale_source": "authored_evidence_summary",
            },
            "complete_path_fit": {
                "category": assignment["fit_category"],
                "score": fit_score,
                "rule_id": assignment["fit_rule_id"],
                "rationale": fit_rationale,
                "rationale_source": fit_rationale_source,
            },
            "combined_locator_utility": {
                "rule_id": assignment["mapping_rule_id"],
                "calculation": (
                    f"min({_score_text(treatment_score)}, {_score_text(fit_score)}) = "
                    f"{_score_text(combined_score)}"
                ),
                "score": combined_score,
                "credit": assignment["combined_credit"],
            },
            "evidence_ids": evidence_ids,
            "structured_defect_ids": list(
                assignment["applicable_structured_defect_ids"]
            ),
            "fit_rationale_required": rationale_required,
        },
        legacy_compatibility,
    )


def _locator_factor(
    assignment: Mapping[str, Any], explanation: Mapping[str, Any]
) -> list[dict[str, Any]]:
    return [
        {
            "factor_id": "page_treatment",
            "label": "Page treatment",
            "status": assignment["treatment_category"],
            "score": _grade_score(_decimal(assignment["treatment_score"])),
            "weight": 0,
            "explanation": explanation["evidence_summary"],
            "evidence_ids": explanation["evidence_ids"],
        },
        {
            "factor_id": "complete_path_fit",
            "label": "Complete-path fit",
            "status": assignment["fit_category"],
            "score": _grade_score(_decimal(assignment["fit_score"])),
            "weight": 0,
            "explanation": (
                explanation["complete_path_fit"]["rationale"]
                or explanation["evidence_summary"]
            ),
            "evidence_ids": explanation["evidence_ids"],
        },
        {
            "factor_id": "combined_locator_utility",
            "label": "Combined locator utility",
            "status": assignment["disposition"],
            "score": assignment["diagnostic_grade"],
            "weight": 0,
            "explanation": explanation["combined_locator_utility"]["calculation"],
            "evidence_ids": explanation["evidence_ids"],
        },
    ]


def _structure_metric_summary(review: Mapping[str, Any]) -> str:
    displayed = review["displayed_locator_count"]
    atomic = review["atomic_assignment_count"]
    maximum = review["maximum_range_span"]
    return (
        f"{displayed} displayed locator(s); {atomic} expanded atomic page assignment(s); "
        f"longest continuous range {maximum} page(s). Displayed locators drive locator-string review; "
        "range span drives the separate long-range review. Neither numerical trigger alone is a defect."
    )


def build_v7_assessments(
    v6_compatible_items: Mapping[str, Any],
    calculation: Mapping[str, Any],
    structure_review: Mapping[str, Any],
    locator_documents: list[Mapping[str, Any]] | None = None,
    supplemental_fit_rationales: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Project locator grades and structure metrics without changing evidence."""

    if v6_compatible_items.get("schema_version") != "subject-index-item-assessments-v3":
        raise ValueError("v6_item_assessments_required")
    if calculation.get("schema_version") != "subject-index-dimension-calculations-v4":
        raise ValueError("v7_calculation_required")
    if v6_compatible_items.get("evaluation_id") != calculation.get("evaluation_id"):
        raise ValueError("item_calculation_evaluation_mismatch")
    if v6_compatible_items.get("evidence_identity") != calculation.get("evidence_identity"):
        raise ValueError("item_calculation_evidence_identity_mismatch")

    result = deepcopy(v6_compatible_items)
    provenance = _reliability(calculation)["reliability_provenance"]
    assignments = {
        item["locator_id"]: item
        for item in provenance["locator_utility_assignments"]
    }
    item_ids = {item.get("locator_id") for item in result.get("locator_assessments", [])}
    if item_ids != set(assignments):
        raise ValueError("item_locator_utility_ledger_mismatch")

    judgments: dict[str, dict[str, Any]] = {}
    for document in locator_documents or []:
        schema_version = document.get("schema_version")
        for record in document.get("judgments", []):
            enriched = deepcopy(record)
            enriched["_audit_schema_version"] = schema_version
            if enriched.get("locator_id") in judgments:
                raise ValueError("duplicate_locator_explanation_source")
            judgments[enriched["locator_id"]] = enriched
    supplemental_fit_rationales = supplemental_fit_rationales or {}
    legacy_compatibility_mode = False
    for assessment in result["locator_assessments"]:
        assignment = assignments[assessment["locator_id"]]
        explanation, legacy_compatibility = _locator_explanation(
            assessment,
            assignment,
            judgments.get(assessment["locator_id"]),
            supplemental_fit_rationales.get(assessment["locator_id"]),
        )
        legacy_compatibility_mode = legacy_compatibility_mode or legacy_compatibility
        score = assignment["diagnostic_grade"]
        assessment["grade"] = legacy.grade(score)
        assessment["dimension_reliability_credit"] = assignment["combined_credit"]
        assessment["locator_utility"] = deepcopy(assignment)
        assessment["locator_explanation"] = explanation
        assessment["summary"] = explanation["evidence_summary"]
        assessment["popover"]["summary"] = explanation["evidence_summary"]
        assessment["popover"]["grade"] = assessment["grade"]
        assessment["popover"]["factors"] = _locator_factor(assignment, explanation)
        assessment.pop("credit_tier", None)
        assessment.pop("disqualifying_codes", None)
        assessment.pop("disqualifying_defect_ids", None)

    review_by_path = {
        item["path_id"]: item for item in structure_review.get("path_reviews", [])
    }
    for path in result.get("path_assessments", []):
        page_component = next(
            (
                item
                for item in path.get("component_results", [])
                if item.get("dimension_id") == "page_reference_reliability"
            ),
            None,
        )
        if page_component is not None:
            page_component["score"] = None
            page_component["measurement_status"] = "locator_level_only"
            page_component["summary"] = (
                "V7 exposes each locator grade on the same 0–100 scale as its calculation credit. "
                "No path-level average is canonical, and Page-reference Reliability is reconstructed "
                "only from the frozen locator-utility credit ledger."
            )
            page_factor = next(
                (
                    item
                    for item in path.get("popover", {}).get("factors", [])
                    if item.get("factor_id") == "page_reference_reliability"
                ),
                None,
            )
            if page_factor is not None:
                page_factor["score"] = None
                page_factor["status"] = "locator_level_only"
                page_factor["explanation"] = page_component["summary"]
            path_score = legacy.weighted_mean(
                (item.get("score"), item.get("weight", 0))
                for item in path.get("component_results", [])
            )
            path["grade"] = legacy.grade(path_score)
            path["popover"]["grade"] = deepcopy(path["grade"])
            path["popover"]["summary"] = (
                "Complete-path display summary from non-reliability diagnostics only. "
                "Locator utility remains individually displayed and is not averaged here."
            )
        metric = review_by_path.get(path.get("path_id"))
        if metric is not None:
            path["locator_string_review"] = {
                key: deepcopy(metric[key])
                for key in (
                    "delivered_displayed_locator_ids",
                    "displayed_locator_count",
                    "displayed_locators",
                    "expanded_atomic_locator_ids",
                    "atomic_assignment_count",
                    "maximum_range_span",
                    "long_displayed_locator_string_review_trigger",
                    "long_continuous_range_review_trigger",
                    "independent_architecture_evidence",
                    "final_architecture_disposition",
                    "applicable_structured_defect_ids",
                    "deterministic_derivation_rule_ids",
                    "deterministic_mapping_rule_id",
                )
            }
            path["popover"]["factors"].append(
                {
                    "factor_id": "locator_string_and_range_review",
                    "label": "Locator-string and range review",
                    "status": metric["final_architecture_disposition"],
                    "score": None,
                    "weight": 0,
                    "explanation": _structure_metric_summary(metric),
                    "evidence_ids": [
                        *metric["delivered_displayed_locator_ids"],
                        *metric["expanded_atomic_locator_ids"],
                        *metric["applicable_structured_defect_ids"],
                    ],
                }
            )

    result["schema_version"] = SCHEMA_VERSION
    result["grading_policy"] = GRADING_POLICY
    result["explanation_contract"] = {
        "contract_version": "locator-explanations-v1",
        "authored_evidence_is_primary": True,
        "prose_used_in_scoring": False,
        "legacy_compatibility_mode": legacy_compatibility_mode,
    }
    result["grade_disclosure"] = (
        "V7 locator grades equal 100 times the frozen combined locator credit and are non-additive. "
        "They are not averaged to reconstruct Page-reference Reliability; the canonical calculation uses "
        "locator_utility_assignments[].combined_credit. Editorial Selectivity remains separate."
    )
    result["locator_grading_provenance"] = {
        "model": "two_axis_independent_ceilings_minimum_v1",
        "page_treatment_mapping": {
            "substantive": "1",
            "mixed": "0.7",
            "weak_presence": "0.25",
            "absent": "0",
            "invalid_destination": "0",
            "uninspectable": None,
        },
        "complete_path_fit_mapping": {
            "exact_fit": "1",
            "material_partial_fit": "0.7",
            "material_mismatch": "0.35",
            "severe_mismatch": "0.15",
            "no_fit": "0",
            "uninspectable": None,
        },
        "combination_rule": "min(page_treatment_score, complete_path_fit_score)",
        "diagnostic_grade_rule": "100 * combined_credit",
        "calculation_credit_ledger_sha256": v5.canonical_hash(
            {"locator_utility_assignments": provenance["locator_utility_assignments"]}
        ),
        "diagnostic_grades_used_in_dimension_arithmetic": False,
        "selectivity_mapping_unchanged": True,
        "weak_presence_selectivity_credit": 0,
        "counts_by_treatment_tier": deepcopy(provenance["counts_by_treatment_tier"]),
        "counts_by_fit_tier": deepcopy(provenance["counts_by_fit_tier"]),
        "counts_by_combined_credit_value": deepcopy(
            provenance["counts_by_combined_credit_value"]
        ),
    }
    result["structure_locator_review_binding"] = {
        "schema_version": structure_review["schema_version"],
        "review_id": structure_review["review_id"],
        "review_sha256": structure_review["review_sha256"],
    }
    if "locator_fit_compatibility" in calculation:
        result["locator_fit_compatibility"] = deepcopy(
            calculation["locator_fit_compatibility"]
        )
    if "locator_fit_supplement" in calculation:
        result["locator_fit_supplement"] = deepcopy(
            calculation["locator_fit_supplement"]
        )
    legacy.rebuild_summary(result)
    result["summary"]["locator_utility_tiers"] = {
        "treatment": dict(sorted(Counter(item["treatment_category"] for item in assignments.values()).items())),
        "fit": dict(sorted(Counter(item["fit_category"] for item in assignments.values()).items())),
        "combined_credit": dict(sorted(Counter(str(item["combined_credit"]) for item in assignments.values()).items())),
    }
    return result


def command_build_assessments(args: argparse.Namespace) -> None:
    try:
        items_path = Path(args.v6_compatible_items).resolve()
        calculation_path = Path(args.calculation).resolve()
        review_path = Path(args.structure_locator_review).resolve()
        output_path = Path(args.output).resolve()
        items = v5.load_json(items_path, "V6-compatible item assessments")
        calculation = v5.load_json(calculation_path, "V7 calculation")
        review = v5.load_json(review_path, "V7 structure-locator review")
        locator_documents = []
        for index, stored in enumerate(args.locator_audit or []):
            document = v5.load_json(Path(stored).resolve(), f"Locator audit {index}")
            schema_name = {"locator-audit-v2": "locator-audit-v2.schema.json"}.get(document.get("schema_version"))
            v5.require(
                schema_name is not None,
                "unsupported_locator_audit_schema",
                "V7 item projection accepts current locator-audit-v2 only.",
            )
            v5.validate_schema_document(document, schema_name, f"Locator audit {index}")
            locator_documents.append(document)
        v5.validate_schema_document(
            items, "item-assessments-v3.schema.json", "V6-compatible item assessments"
        )
        v5.validate_schema_document(
            calculation, "dimension-calculations-v4.schema.json", "V7 calculation"
        )
        v5.validate_schema_document(
            review,
            "structure-locator-review-v1.schema.json",
            "V7 structure-locator review",
        )
        v5.require(
            calculation.get("calculation_sha256")
            == v5.canonical_hash(calculation, "calculation_sha256"),
            "calculation_self_hash_mismatch",
            "The V7 calculation self-hash does not reconstruct.",
        )
        v5.require(
            review.get("review_sha256")
            == structure_review_hash(review, "review_sha256"),
            "structure_review_hash_mismatch",
            "The V7 structure-locator review self-hash does not reconstruct.",
        )
        validate_structure_locator_review_semantics(review)
        v5.require(
            not review.get("summary", {}).get("removed_historical_defect_ids"),
            "score_only_migration_item_projection_required",
            "Current item projection cannot consume a structure review that removes historical defects.",
        )
        result = build_v7_assessments(
            items,
            calculation,
            review,
            locator_documents=locator_documents,
        )
        v5.validate_schema_document(
            result, "item-assessments-v5.schema.json", "Generated V7 item assessments"
        )
        v5.require(
            not v5.aliases_existing_file(
                output_path,
                {
                    items_path,
                    calculation_path,
                    review_path,
                    *(Path(path).resolve() for path in (args.locator_audit or [])),
                },
            ),
            "output_aliases_frozen_input",
            "V7 item assessments must not overwrite a bound input artifact.",
        )
        v5.write_json(output_path, result)
        v5.emit(
            {
                "command": "build-v7-item-assessments",
                "ok": True,
                "evaluation_id": result["evaluation_id"],
                "schema_version": result["schema_version"],
                "grading_policy": result["grading_policy"],
                "artifact_written": str(output_path),
            }
        )
    except (OSError, ValueError, v5.CalculationError, StructureReviewError) as exc:
        if isinstance(exc, (v5.CalculationError, StructureReviewError)):
            error = {"code": exc.code, "message": exc.message, "details": exc.details}
        else:
            error = {"code": "item_projection_error", "message": str(exc)}
        v5.emit(
            {"command": "build-v7-item-assessments", "ok": False, "error": error},
            1,
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser(
        "build-assessments",
        help="Project current V7 locator grades from base items and frozen V7 ledgers.",
    )
    build.add_argument("--base-items", dest="v6_compatible_items", required=True)
    build.add_argument("--calculation", required=True)
    build.add_argument("--structure-locator-review", required=True)
    build.add_argument(
        "--locator-audit",
        action="append",
        default=[],
        help="Frozen locator audit; repeat once per chunk. V2 carries authored fit rationale.",
    )
    build.add_argument("--output", required=True)
    build.set_defaults(func=command_build_assessments)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
