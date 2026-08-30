#!/usr/bin/env python3
"""Derive V7 locator-string and continuous-range review evidence.

The derivation is intentionally limited to stable structured identities in the
frozen normalized candidate and item inventory.  It never tokenizes
``original_displayed_form`` or any explanation field.  A displayed range is
one displayed locator and retains an exact binding to every expanded atomic
locator assignment that it owns.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = "subject-index-structure-locator-review-v1"
DISPLAYED_LOCATOR_THRESHOLD = 6
CONTINUOUS_RANGE_SPAN_THRESHOLD = 10

DERIVATION_RULES = (
    "STRUCT-V7-DISPLAY-COUNT-FROM-LOCATOR-DISPLAYS",
    "STRUCT-V7-RANGE-OWNS-EXPANDED-ASSIGNMENTS",
    "STRUCT-V7-RANGE-SPAN-FROM-CONTIGUOUS-DOCUMENT-PAGES",
    "STRUCT-V7-ATOMIC-COUNT-FROM-LOCATOR-ASSIGNMENTS",
    "STRUCT-V7-LONG-STRING-GT-6",
    "STRUCT-V7-LONG-RANGE-GT-10",
    "STRUCT-V7-NUMERIC-TRIGGER-REVIEW-ONLY",
)

# These exact machine-readable families are the only historical bases that may
# support the corresponding deterministic migration dispositions.  Similar
# wording in a summary or rationale is deliberately ignored.
ATOMIC_THRESHOLD_ONLY_FAMILIES = frozenset(
    {
        "long_locator_string_atomic_assignment_threshold_only",
        "undivided_locators_atomic_assignment_threshold_only",
    }
)
INDEPENDENT_ARCHITECTURE_FAMILIES = frozenset(
    {
        "conceptual_heterogeneity_with_impaired_access",
        "conceptually_distinguishable_treatments_without_useful_subdivision",
        "undifferentiated_conceptual_treatments_impair_retrieval",
        "long_locator_string_conceptual_heterogeneity",
        "long_continuous_range_conceptual_heterogeneity",
    }
)

DEFECT_BASIS_CLASSIFICATIONS = {
    "atomic_assignment_threshold_only",
    "independent_architecture",
    "unclassified",
}


class StructureReviewError(ValueError):
    """A frozen grouping or review state cannot be mapped deterministically."""

    def __init__(self, code: str, message: str, details: Any = None):
        super().__init__(f"{code}:{message}")
        self.code = code
        self.message = message
        self.details = details


def _require(condition: Any, code: str, message: str, details: Any = None) -> None:
    if not condition:
        raise StructureReviewError(code, message, details)


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def canonical_hash(value: Any, omitted_field: str | None = None) -> str:
    payload = deepcopy(value)
    if omitted_field is not None and isinstance(payload, dict):
        payload.pop(omitted_field, None)
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def validate_structure_locator_review_semantics(review: Mapping[str, Any]) -> None:
    """Validate cross-field invariants that JSON Schema cannot express.

    In particular, this prevents a consumer from relabeling expanded atomic
    assignments as displayed locators, splitting one range into several
    displayed counts, changing a boundary trigger, or turning a numeric review
    trigger into a scored architecture defect.
    """

    _require(
        review.get("schema_version") == SCHEMA_VERSION,
        "structure_review_schema",
        "Expected the V7 structure-locator review artifact.",
    )
    thresholds = review.get("thresholds", {})
    _require(
        thresholds
        == {
            "long_displayed_locator_string": {
                "operator": ">",
                "displayed_locator_count": DISPLAYED_LOCATOR_THRESHOLD,
            },
            "long_continuous_range": {
                "operator": ">",
                "inclusive_range_span": CONTINUOUS_RANGE_SPAN_THRESHOLD,
            },
            "numeric_trigger_is_automatic_defect": False,
        },
        "structure_review_threshold_mismatch",
        "V7 structure-review thresholds and their review-only status are frozen.",
    )
    path_reviews = review.get("path_reviews")
    _require(
        isinstance(path_reviews, list),
        "structure_review_semantic_mismatch",
        "path_reviews must be an array.",
    )
    seen_paths: set[str] = set()
    for path in path_reviews:
        _require(
            isinstance(path, dict),
            "structure_review_semantic_mismatch",
            "Every path review must be an object.",
        )
        path_id = path.get("path_id")
        _require(
            isinstance(path_id, str) and path_id not in seen_paths,
            "structure_review_semantic_mismatch",
            "Path-review identities must be unique.",
            path_id,
        )
        seen_paths.add(path_id)
        displays = path.get("displayed_locators")
        delivered_ids = path.get("delivered_displayed_locator_ids")
        expanded_ids = path.get("expanded_atomic_locator_ids")
        _require(
            isinstance(displays, list)
            and isinstance(delivered_ids, list)
            and isinstance(expanded_ids, list),
            "structure_review_semantic_mismatch",
            "Displayed and atomic locator ledgers must be arrays.",
            path_id,
        )
        _require(
            delivered_ids == [item.get("display_id") for item in displays]
            and path.get("displayed_locator_count") == len(displays),
            "displayed_locator_count_mismatch",
            "displayed_locator_count must count delivered DISPLAY-* records exactly once.",
            path_id,
        )
        flattened: list[Any] = []
        range_spans: list[int] = []
        display_ids_seen: set[str] = set()
        for display in displays:
            display_id = display.get("display_id")
            display_atomic_ids = display.get("expanded_atomic_locator_ids")
            _require(
                isinstance(display_id, str)
                and display_id not in display_ids_seen
                and isinstance(display_atomic_ids, list),
                "display_assignment_binding_mismatch",
                "Every displayed locator requires one unique identity and an atomic ownership list.",
                {"path_id": path_id, "display_id": display_id},
            )
            display_ids_seen.add(display_id)
            _require(
                display.get("atomic_assignment_count") == len(display_atomic_ids),
                "atomic_assignment_count_mismatch",
                "A displayed locator's atomic count must equal the size of its owned LOC-* list.",
                {"path_id": path_id, "display_id": display_id},
            )
            flattened.extend(display_atomic_ids)
            kind = display.get("kind")
            if kind == "singleton":
                _require(
                    len(display_atomic_ids) == 1
                    and display.get("range_id") is None
                    and display.get("range_endpoints") is None
                    and display.get("inclusive_range_span") is None,
                    "singleton_grouping_invalid",
                    "One singleton display must own exactly one atomic assignment and no range state.",
                    {"path_id": path_id, "display_id": display_id},
                )
            elif kind == "range":
                endpoints = display.get("range_endpoints")
                span = display.get("inclusive_range_span")
                _require(
                    isinstance(endpoints, dict)
                    and isinstance(span, int)
                    and not isinstance(span, bool)
                    and span == len(display_atomic_ids)
                    and display.get("range_id") is not None,
                    "range_grouping_incomplete",
                    "One range display must retain one range identity, endpoints, span, and all expanded assignments.",
                    {"path_id": path_id, "display_id": display_id},
                )
                start = endpoints.get("start", {})
                end = endpoints.get("end", {})
                _require(
                    start.get("locator_id") == display_atomic_ids[0]
                    and end.get("locator_id") == display_atomic_ids[-1]
                    and isinstance(start.get("document_page"), int)
                    and isinstance(end.get("document_page"), int)
                    and end["document_page"] - start["document_page"] + 1 == span,
                    "range_span_mismatch",
                    "A range span must be the exact inclusive span between its bound atomic endpoints.",
                    {"path_id": path_id, "display_id": display_id},
                )
                range_spans.append(span)
        _require(
            flattened == expanded_ids,
            "display_assignment_binding_mismatch",
            "The path atomic ledger must equal the ordered concatenation of each displayed locator's ownership ledger.",
            path_id,
        )
        applicable_ids = path.get("applicable_structured_defect_ids")
        removed_ids = path.get("removed_structured_defect_ids")
        retained_ids = path.get("retained_structured_defect_ids")
        historical_records = path.get("historical_defect_dispositions")
        _require(
            isinstance(applicable_ids, list)
            and isinstance(removed_ids, list)
            and isinstance(retained_ids, list)
            and isinstance(historical_records, list)
            and not (set(removed_ids) & set(retained_ids))
            and sorted(set(removed_ids) | set(retained_ids)) == applicable_ids
            and [item.get("defect_id") for item in historical_records]
            == applicable_ids,
            "historical_defect_disposition_mismatch",
            "Every applicable historical architecture defect must have exactly one removed-or-retained V7 disposition record.",
            path_id,
        )
        expected_metrics = {
            "displayed_locator_count": path.get("displayed_locator_count"),
            "maximum_range_span": path.get("maximum_range_span"),
            "atomic_assignment_count": path.get("atomic_assignment_count"),
            "long_displayed_locator_string_review_trigger": path.get(
                "long_displayed_locator_string_review_trigger"
            ),
            "long_continuous_range_review_trigger": path.get(
                "long_continuous_range_review_trigger"
            ),
        }
        for record in historical_records:
            defect_id = record.get("defect_id")
            basis = record.get("historical_structured_basis")
            expected_active_disposition = (
                "removed_from_active_projection"
                if defect_id in removed_ids
                else "retained_in_active_projection"
            )
            _require(
                isinstance(basis, dict)
                and basis.get("defect_id") == defect_id
                and record.get("historical_structured_basis_sha256")
                == canonical_hash(basis)
                and record.get("basis_classification")
                == _defect_basis_classification(basis)
                and record.get("basis_classification")
                in DEFECT_BASIS_CLASSIFICATIONS
                and record.get("classification_input_fields")
                == ["root_cause_family"]
                and record.get("corrected_metrics") == expected_metrics
                and record.get("deterministic_mapping_rule_id")
                == path.get("deterministic_mapping_rule_id")
                and record.get("path_architecture_disposition")
                == path.get("final_architecture_disposition")
                and record.get("active_v7_defect_disposition")
                == expected_active_disposition
                and record.get("prose_used_for_mapping") is False,
                "historical_defect_basis_binding_mismatch",
                "A historical defect record must bind its complete frozen basis, corrected metrics, mapping rule, and active V7 disposition.",
                {"path_id": path_id, "defect_id": defect_id},
            )
        complete = path.get("derivation_complete") is True
        if complete:
            maximum_span = max(range_spans, default=0)
            _require(
                path.get("atomic_assignment_count") == len(expanded_ids)
                and path.get("maximum_range_span") == maximum_span,
                "atomic_or_range_count_mismatch",
                "Atomic assignment count and maximum range span must reconstruct from display ownership.",
                path_id,
            )
            long_string = len(displays) > DISPLAYED_LOCATOR_THRESHOLD
            long_range = maximum_span > CONTINUOUS_RANGE_SPAN_THRESHOLD
            _require(
                path.get("long_displayed_locator_string_review_trigger") is long_string
                and path.get("long_continuous_range_review_trigger") is long_range,
                "structure_review_trigger_mismatch",
                "Review triggers must be derived from exact displayed-count and range-span boundaries.",
                path_id,
            )
            disposition = path.get("final_architecture_disposition")
            facts = path.get("independent_architecture_evidence", {})
            if disposition == "structured_defect_confirmed":
                _require(
                    (long_string or long_range)
                    and _confirmed_defect_facts(facts)
                    and bool(facts.get("defect_ids"))
                    and set(facts.get("defect_ids", []))
                    <= set(path.get("retained_structured_defect_ids", []))
                    and bool(path.get("retained_structured_defect_ids")),
                    "numeric_trigger_cannot_create_architecture_defect",
                    "A numeric trigger cannot create an architecture defect without complete structured semantic evidence.",
                    path_id,
                )
            if disposition == "review_required":
                _require(
                    (long_string or long_range)
                    and facts.get("review_status") == "not_reviewed",
                    "unreviewed_trigger_disposition_mismatch",
                    "A newly triggered, unreviewed path must remain review_required.",
                    path_id,
                )
            if disposition == "reviewed_no_defect":
                _require(
                    (long_string or long_range)
                    and facts.get("review_status") == "reviewed_no_defect"
                    and not facts.get("defect_ids")
                    and not _confirmed_defect_facts(
                        {**facts, "review_status": "defect_confirmed"}
                    ),
                    "reviewed_no_defect_disposition_mismatch",
                    "A triggered passing disposition requires a structured reviewed-no-defect determination.",
                    path_id,
                )
            if disposition == "historical_false_positive_removed":
                _require(
                    not long_string
                    and not long_range
                    and len(expanded_ids) > DISPLAYED_LOCATOR_THRESHOLD
                    and bool(path.get("removed_structured_defect_ids"))
                    and not path.get("retained_structured_defect_ids"),
                    "false_positive_removal_mismatch",
                    "False-positive removal requires an old atomic-threshold penalty and no corrected numeric trigger.",
                    path_id,
                )

    summary = review.get("summary", {})
    expected_summary = {
        "locator_bearing_path_count": len(path_reviews),
        "long_string_review_trigger_count": sum(
            item.get("long_displayed_locator_string_review_trigger") is True
            for item in path_reviews
        ),
        "long_range_review_trigger_count": sum(
            item.get("long_continuous_range_review_trigger") is True
            for item in path_reviews
        ),
        "review_required_path_ids": sorted(
            item["path_id"]
            for item in path_reviews
            if item.get("final_architecture_disposition") == "review_required"
        ),
        "derivation_failed_path_ids": sorted(
            item["path_id"]
            for item in path_reviews
            if item.get("derivation_complete") is not True
        ),
        "removed_historical_defect_ids": sorted(
            {
                defect_id
                for item in path_reviews
                for defect_id in item.get("removed_structured_defect_ids", [])
            }
        ),
        "retained_historical_defect_ids": sorted(
            {
                defect_id
                for item in path_reviews
                for defect_id in item.get("retained_structured_defect_ids", [])
            }
        ),
    }
    _require(
        summary == expected_summary,
        "structure_review_summary_mismatch",
        "The structure-review summary must reconstruct from path rows.",
    )
    expected_ready = (
        not review.get("derivation_issues")
        and not expected_summary["review_required_path_ids"]
        and not expected_summary["derivation_failed_path_ids"]
    )
    _require(
        review.get("migration_ready") is expected_ready,
        "structure_review_readiness_mismatch",
        "Migration readiness must fail closed for derivation failures or unreviewed triggers.",
    )


def _records_by_id(records: Any, field: str, label: str) -> dict[str, dict[str, Any]]:
    _require(isinstance(records, list), "invalid_structure_review_input", f"{label} must be an array.")
    result: dict[str, dict[str, Any]] = {}
    for index, record in enumerate(records):
        _require(isinstance(record, dict), "invalid_structure_review_input", f"{label}[{index}] must be an object.")
        identity = record.get(field)
        _require(isinstance(identity, str) and identity and identity not in result, "invalid_structure_review_input", f"{label}[{index}].{field} is missing or duplicated.", identity)
        result[identity] = record
    return result


def _structure_defects(structure: Mapping[str, Any]) -> list[dict[str, Any]]:
    context = structure.get("v5_scoring_context")
    records = context.get("defects") if isinstance(context, dict) else structure.get("defects")
    _require(isinstance(records, list), "invalid_structure_review_input", "The structure audit lacks a structured defect ledger.")
    return [record for record in records if isinstance(record, dict)]


def _explicit_decisions(structure: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    records = structure.get("v7_architecture_review_decisions", [])
    _require(isinstance(records, list), "invalid_structure_review_input", "v7_architecture_review_decisions must be an array.")
    result: dict[str, dict[str, Any]] = {}
    for index, record in enumerate(records):
        _require(isinstance(record, dict), "invalid_structure_review_input", f"v7_architecture_review_decisions[{index}] must be an object.")
        path_id = record.get("path_id")
        _require(isinstance(path_id, str) and path_id.startswith("PATH-") and path_id not in result, "invalid_structure_review_input", "Each V7 architecture decision requires a unique PATH-* identity.", path_id)
        result[path_id] = record
    return result


def _affected(defect: Mapping[str, Any], path_id: str, node_id: str) -> bool:
    values = defect.get("affected_item_ids", defect.get("affected_ids", []))
    return isinstance(values, list) and bool({path_id, node_id} & set(values))


def _architecture_defect(defect: Mapping[str, Any]) -> bool:
    return (
        defect.get("dimension_owner") == "findability_navigation"
        and defect.get("code") in {"HED", "SUB"}
        and isinstance(defect.get("defect_id"), str)
    )


def _endpoint(assignment: Mapping[str, Any], delivered: str) -> dict[str, Any]:
    return {
        "delivered": delivered,
        "locator_id": assignment.get("locator_id"),
        "source_page_label": assignment.get("source_page_label"),
        "document_page": assignment.get("document_page"),
    }


def _display_record(
    display: Mapping[str, Any], assignments: list[Mapping[str, Any]]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    display_id = display.get("display_id")
    delivered_kind = display.get("kind")
    output_kind = "singleton" if delivered_kind == "point" else "range" if delivered_kind == "range" else "other"
    declared_ids = display.get("locator_ids")
    actual_ids = [item.get("locator_id") for item in assignments]
    if not isinstance(declared_ids, list) or declared_ids != actual_ids or len(actual_ids) != len(set(actual_ids)):
        issues.append(
            {
                "code": "display_assignment_binding_mismatch",
                "display_id": display_id,
                "declared_locator_ids": declared_ids,
                "assignment_locator_ids": actual_ids,
            }
        )
    record: dict[str, Any] = {
        "display_id": display_id,
        "kind": output_kind,
        "delivered_kind": delivered_kind,
        "range_id": display.get("range_id"),
        "expanded_atomic_locator_ids": actual_ids,
        "atomic_assignment_count": len(actual_ids),
        "derivation_rule_id": "STRUCT-V7-RANGE-OWNS-EXPANDED-ASSIGNMENTS" if output_kind == "range" else "STRUCT-V7-DISPLAY-COUNT-FROM-LOCATOR-DISPLAYS",
    }
    if output_kind == "singleton":
        if len(assignments) != 1 or display.get("range_id") is not None:
            issues.append({"code": "singleton_grouping_invalid", "display_id": display_id})
        record["range_endpoints"] = None
        record["inclusive_range_span"] = None
    elif output_kind == "range":
        range_id = display.get("range_id")
        start_display = display.get("start_display")
        end_display = display.get("end_display")
        pages = [item.get("document_page") for item in assignments]
        range_ids = {item.get("range_id") for item in assignments}
        resolved = bool(assignments) and all(item.get("mapping_status") == "resolved" for item in assignments)
        contiguous = (
            resolved
            and all(isinstance(page, int) and not isinstance(page, bool) for page in pages)
            and pages == list(range(pages[0], pages[-1] + 1))
        )
        grouping_valid = (
            isinstance(range_id, str)
            and range_id.startswith("RANGE-")
            and range_ids == {range_id}
            and isinstance(start_display, str)
            and isinstance(end_display, str)
            and bool(assignments)
        )
        if not grouping_valid:
            issues.append({"code": "range_grouping_incomplete", "display_id": display_id, "range_id": range_id})
        if not contiguous:
            issues.append({"code": "range_span_not_reconstructable", "display_id": display_id, "range_id": range_id})
        record["range_endpoints"] = (
            {
                "start": _endpoint(assignments[0], start_display),
                "end": _endpoint(assignments[-1], end_display),
            }
            if grouping_valid
            else None
        )
        record["inclusive_range_span"] = len(assignments) if grouping_valid and contiguous else None
    else:
        record["range_endpoints"] = None
        record["inclusive_range_span"] = None
        issues.append(
            {
                "code": "unsupported_display_form_requires_structured_mapping",
                "display_id": display_id,
                "delivered_kind": delivered_kind,
            }
        )
    return record, issues


def _decision_facts(
    decision: Mapping[str, Any] | None,
    independent_defects: list[Mapping[str, Any]],
) -> dict[str, Any]:
    if decision is not None:
        facts = {
            "conceptually_distinguishable_treatments": decision.get("conceptually_distinguishable_treatments"),
            "meaningful_subheadings_or_access_routes": decision.get("meaningful_subheadings_or_access_routes"),
            "material_scanning_or_retrieval_impairment": decision.get("material_scanning_or_retrieval_impairment"),
            "subdivision_is_conceptual_not_trivial": decision.get("subdivision_is_conceptual_not_trivial"),
            "review_status": decision.get("review_status"),
            "evidence_ids": sorted(set(decision.get("evidence_ids", []))) if isinstance(decision.get("evidence_ids"), list) else [],
            "defect_ids": sorted(set(decision.get("defect_ids", []))) if isinstance(decision.get("defect_ids"), list) else [],
            "derivation_rule_id": "STRUCT-V7-EXPLICIT-ARCHITECTURE-DECISION",
        }
        return facts
    established = bool(independent_defects)
    return {
        "conceptually_distinguishable_treatments": established if established else None,
        "meaningful_subheadings_or_access_routes": established if established else None,
        "material_scanning_or_retrieval_impairment": established if established else None,
        "subdivision_is_conceptual_not_trivial": established if established else None,
        "review_status": "defect_confirmed" if established else "not_reviewed",
        "evidence_ids": sorted(defect["defect_id"] for defect in independent_defects),
        "defect_ids": sorted(defect["defect_id"] for defect in independent_defects),
        "derivation_rule_id": "STRUCT-V7-HISTORICAL-STRUCTURED-DEFECT-BASIS" if established else "STRUCT-V7-NO-SEMANTIC-INFERENCE",
    }


def _confirmed_defect_facts(facts: Mapping[str, Any]) -> bool:
    return (
        facts.get("review_status") == "defect_confirmed"
        and all(
            facts.get(field) is True
            for field in (
                "conceptually_distinguishable_treatments",
                "meaningful_subheadings_or_access_routes",
                "material_scanning_or_retrieval_impairment",
                "subdivision_is_conceptual_not_trivial",
            )
        )
    )


def _defect_basis_classification(defect: Mapping[str, Any]) -> str:
    family = defect.get("root_cause_family")
    if family in ATOMIC_THRESHOLD_ONLY_FAMILIES:
        return "atomic_assignment_threshold_only"
    if family in INDEPENDENT_ARCHITECTURE_FAMILIES:
        return "independent_architecture"
    return "unclassified"


def _historical_defect_dispositions(
    defects: Iterable[Mapping[str, Any]],
    *,
    removed_ids: Iterable[str],
    path_disposition: str,
    mapping_rule_id: str,
    displayed_locator_count: int,
    maximum_range_span: int | None,
    atomic_assignment_count: int | None,
    long_string_trigger: bool | None,
    long_range_trigger: bool | None,
) -> list[dict[str, Any]]:
    """Bind every historical defect to its exact old basis and V7 outcome.

    The complete defect object is copied and self-hashed.  Classification uses
    only ``root_cause_family`` membership in the closed sets above; stored prose
    remains immutable evidence but is never a mapping input.
    """

    removed = set(removed_ids)
    corrected_metrics = {
        "displayed_locator_count": displayed_locator_count,
        "maximum_range_span": maximum_range_span,
        "atomic_assignment_count": atomic_assignment_count,
        "long_displayed_locator_string_review_trigger": long_string_trigger,
        "long_continuous_range_review_trigger": long_range_trigger,
    }
    records: list[dict[str, Any]] = []
    for defect in sorted(defects, key=lambda item: str(item.get("defect_id", ""))):
        frozen_basis = deepcopy(dict(defect))
        defect_id = frozen_basis.get("defect_id")
        records.append(
            {
                "defect_id": defect_id,
                "historical_structured_basis": frozen_basis,
                "historical_structured_basis_sha256": canonical_hash(frozen_basis),
                "basis_classification": _defect_basis_classification(defect),
                "classification_input_fields": ["root_cause_family"],
                "corrected_metrics": deepcopy(corrected_metrics),
                "deterministic_mapping_rule_id": mapping_rule_id,
                "path_architecture_disposition": path_disposition,
                "active_v7_defect_disposition": (
                    "removed_from_active_projection"
                    if defect_id in removed
                    else "retained_in_active_projection"
                ),
                "prose_used_for_mapping": False,
            }
        )
    return records


def derive_structure_locator_review(
    candidate: Mapping[str, Any],
    inventory: Mapping[str, Any],
    structure: Mapping[str, Any],
    *,
    candidate_file_sha256: str,
    inventory_file_sha256: str,
    structure_file_sha256: str,
    audit_mode: str,
) -> dict[str, Any]:
    """Return the complete deterministic V7 review ledger.

    The function emits derivation failures in the artifact so preflight can
    explain them.  Callers must require ``migration_ready`` before scoring.
    """

    _require(candidate.get("schema_version") == "candidate-index-v2", "invalid_structure_review_input", "Expected candidate-index-v2.")
    _require(inventory.get("schema_version") == "subject-index-item-inventory-v2", "invalid_structure_review_input", "Expected subject-index-item-inventory-v2.")
    candidate_sha = candidate.get("candidate_sha256")
    _require(isinstance(candidate_sha, str) and inventory.get("candidate_sha256") == candidate_sha, "candidate_inventory_binding_mismatch", "Candidate and inventory identities differ.")
    _require(structure.get("candidate_sha256") == candidate_sha, "candidate_structure_binding_mismatch", "Candidate and structure-audit identities differ.")
    for label, value in (
        ("candidate_file_sha256", candidate_file_sha256),
        ("inventory_file_sha256", inventory_file_sha256),
        ("structure_file_sha256", structure_file_sha256),
    ):
        _require(isinstance(value, str) and len(value) == 64, "invalid_structure_review_input", f"{label} must be a SHA-256 digest.")
    _require(audit_mode in {"full", "pilot"}, "invalid_structure_review_input", "audit_mode must be full or pilot.")

    records_by_path = _records_by_id(candidate.get("records"), "path_id", "candidate.records")
    inventory_paths = _records_by_id(inventory.get("paths"), "path_id", "inventory.paths")
    inventory_nodes = _records_by_id(inventory.get("heading_nodes"), "node_id", "inventory.heading_nodes")
    _require(set(records_by_path) == set(inventory_paths), "candidate_inventory_binding_mismatch", "Candidate and inventory PATH-* sets differ.", {"candidate_only": sorted(set(records_by_path) - set(inventory_paths)), "inventory_only": sorted(set(inventory_paths) - set(records_by_path))})

    defects = _structure_defects(structure)
    decisions = _explicit_decisions(structure)
    path_reviews: list[dict[str, Any]] = []
    global_issues: list[dict[str, Any]] = []

    for path_id in sorted(records_by_path):
        candidate_record = records_by_path[path_id]
        path_record = inventory_paths[path_id]
        displays = candidate_record.get("locator_displays")
        assignments = candidate_record.get("locator_assignments")
        _require(isinstance(displays, list) and isinstance(assignments, list), "invalid_structure_review_input", f"{path_id} lacks structured locator grouping arrays.")
        if not displays and not assignments:
            continue
        node_ids = path_record.get("node_ids")
        _require(isinstance(node_ids, list) and node_ids and node_ids[-1] in inventory_nodes, "candidate_inventory_binding_mismatch", f"{path_id} lacks a terminal NODE-* binding.")
        terminal_node_id = node_ids[-1]
        assignment_by_display: dict[str, list[Mapping[str, Any]]] = {}
        for assignment in assignments:
            _require(isinstance(assignment, dict), "invalid_structure_review_input", f"{path_id} has a non-object locator assignment.")
            display_id = assignment.get("display_id")
            _require(isinstance(display_id, str) and display_id.startswith("DISPLAY-"), "invalid_structure_review_input", f"{path_id} assignment lacks DISPLAY-* ownership.")
            assignment_by_display.setdefault(display_id, []).append(assignment)
        display_ids: list[str] = []
        display_records: list[dict[str, Any]] = []
        path_issues: list[dict[str, Any]] = []
        for display in displays:
            _require(isinstance(display, dict), "invalid_structure_review_input", f"{path_id} has a non-object locator display.")
            display_id = display.get("display_id")
            _require(isinstance(display_id, str) and display_id.startswith("DISPLAY-") and display_id not in display_ids, "invalid_structure_review_input", f"{path_id} has a missing or duplicate DISPLAY-* identity.", display_id)
            display_ids.append(display_id)
            derived, issues = _display_record(display, assignment_by_display.pop(display_id, []))
            display_records.append(derived)
            path_issues.extend(issues)
        if assignment_by_display:
            path_issues.append({"code": "assignment_without_display", "display_ids": sorted(assignment_by_display)})

        expanded_ids = [item.get("locator_id") for item in assignments]
        inventory_locator_ids = path_record.get("locator_ids")
        if inventory_locator_ids != expanded_ids:
            path_issues.append({"code": "candidate_inventory_locator_binding_mismatch", "candidate_locator_ids": expanded_ids, "inventory_locator_ids": inventory_locator_ids})
        range_records = [item for item in display_records if item["kind"] == "range"]
        spans = [item["inclusive_range_span"] for item in range_records]
        span_complete = all(isinstance(span, int) for span in spans)
        derivation_complete = not path_issues and span_complete
        displayed_count = len(display_records)
        atomic_count = len(expanded_ids) if derivation_complete else None
        maximum_range_span = max(spans, default=0) if span_complete else None
        long_string_trigger = displayed_count > DISPLAYED_LOCATOR_THRESHOLD if derivation_complete else None
        long_range_trigger = maximum_range_span > CONTINUOUS_RANGE_SPAN_THRESHOLD if derivation_complete else None

        associated = [defect for defect in defects if _architecture_defect(defect) and _affected(defect, path_id, terminal_node_id)]
        threshold_only = [defect for defect in associated if defect.get("root_cause_family") in ATOMIC_THRESHOLD_ONLY_FAMILIES]
        independent = [defect for defect in associated if defect.get("root_cause_family") in INDEPENDENT_ARCHITECTURE_FAMILIES]
        unclassified = [defect for defect in associated if defect not in threshold_only and defect not in independent]
        decision = decisions.get(path_id)
        if decision is not None:
            decision_defect_ids = decision.get("defect_ids", [])
            associated_ids = {defect["defect_id"] for defect in associated}
            decision_status = decision.get("review_status")
            semantic_fields = (
                "conceptually_distinguishable_treatments",
                "meaningful_subheadings_or_access_routes",
                "material_scanning_or_retrieval_impairment",
                "subdivision_is_conceptual_not_trivial",
            )
            decision_valid = (
                isinstance(decision_defect_ids, list)
                and set(decision_defect_ids) <= associated_ids
                and isinstance(decision.get("evidence_ids"), list)
                and bool(decision["evidence_ids"])
                and all(isinstance(decision.get(field), bool) for field in semantic_fields)
                and (
                    decision_status == "defect_confirmed"
                    and bool(decision_defect_ids)
                    and all(decision.get(field) is True for field in semantic_fields)
                    or decision_status == "reviewed_no_defect"
                    and not decision_defect_ids
                    and not all(decision.get(field) is True for field in semantic_fields)
                )
            )
            if not decision_valid:
                path_issues.append(
                    {
                        "code": "architecture_decision_defect_binding_mismatch",
                        "decision_defect_ids": decision_defect_ids,
                        "applicable_structured_defect_ids": sorted(associated_ids),
                    }
                )
                derivation_complete = False
                atomic_count = None
                maximum_range_span = None
                long_string_trigger = None
                long_range_trigger = None
        facts = _decision_facts(decision, independent)
        confirmed = _confirmed_defect_facts(facts)
        removed: list[str] = []
        retained = sorted(defect["defect_id"] for defect in associated)
        mapping_rule_id: str
        if not derivation_complete:
            disposition = "derivation_failed"
            mapping_rule_id = "STRUCT-V7-FAIL-CLOSED-GROUPING-OR-SPAN"
        elif (
            threshold_only
            and atomic_count is not None
            and atomic_count > DISPLAYED_LOCATOR_THRESHOLD
            and not long_string_trigger
            and not long_range_trigger
            and not independent
            and not unclassified
            and decision is None
        ):
            disposition = "historical_false_positive_removed"
            removed = sorted(defect["defect_id"] for defect in threshold_only)
            retained = []
            mapping_rule_id = "STRUCT-V7-REMOVE-ATOMIC-THRESHOLD-ONLY-FALSE-POSITIVE"
        elif long_string_trigger or long_range_trigger:
            if confirmed and retained:
                disposition = "structured_defect_confirmed"
                mapping_rule_id = "STRUCT-V7-TRIGGER-PLUS-INDEPENDENT-ARCHITECTURE-EVIDENCE"
            elif facts.get("review_status") == "reviewed_no_defect":
                disposition = "reviewed_no_defect"
                mapping_rule_id = "STRUCT-V7-TRIGGER-REVIEWED-NO-DEFECT"
            else:
                disposition = "review_required"
                mapping_rule_id = "STRUCT-V7-TRIGGER-DOES-NOT-CREATE-DEFECT"
        elif threshold_only:
            disposition = "historical_defect_retained"
            mapping_rule_id = "STRUCT-V7-RETAIN-NONSOLE-OR-INDEPENDENT-DEFECT"
        elif associated:
            disposition = "independent_architecture_disposition_retained"
            mapping_rule_id = "STRUCT-V7-NUMERIC-TRIGGER-NOT-REQUIRED-FOR-INDEPENDENT-DEFECT"
        else:
            disposition = "no_numeric_review_trigger"
            mapping_rule_id = "STRUCT-V7-BELOW-BOTH-REVIEW-THRESHOLDS"

        historical_defect_dispositions = _historical_defect_dispositions(
            associated,
            removed_ids=removed,
            path_disposition=disposition,
            mapping_rule_id=mapping_rule_id,
            displayed_locator_count=displayed_count,
            maximum_range_span=maximum_range_span,
            atomic_assignment_count=atomic_count,
            long_string_trigger=long_string_trigger,
            long_range_trigger=long_range_trigger,
        )

        review = {
            "path_id": path_id,
            "record_id": candidate_record.get("record_id"),
            "terminal_node_id": terminal_node_id,
            "heading_path": deepcopy(candidate_record.get("heading_path")),
            "delivered_displayed_locator_ids": display_ids,
            "displayed_locator_count": displayed_count,
            "displayed_locators": display_records,
            "expanded_atomic_locator_ids": expanded_ids,
            "atomic_assignment_count": atomic_count,
            "maximum_range_span": maximum_range_span,
            "long_displayed_locator_string_review_trigger": long_string_trigger,
            "long_continuous_range_review_trigger": long_range_trigger,
            "independent_architecture_evidence": facts,
            "applicable_structured_defect_ids": sorted(defect["defect_id"] for defect in associated),
            "unclassified_structured_defect_ids": sorted(defect["defect_id"] for defect in unclassified),
            "removed_structured_defect_ids": removed,
            "retained_structured_defect_ids": retained,
            "historical_defect_dispositions": historical_defect_dispositions,
            "final_architecture_disposition": disposition,
            "deterministic_derivation_rule_ids": list(DERIVATION_RULES),
            "deterministic_mapping_rule_id": mapping_rule_id,
            "derivation_complete": derivation_complete,
            "derivation_issues": sorted(path_issues, key=lambda item: (str(item.get("code")), str(item.get("display_id", "")))),
        }
        path_reviews.append(review)
        global_issues.extend({"path_id": path_id, **issue} for issue in review["derivation_issues"])

    unknown_decisions = sorted(set(decisions) - {item["path_id"] for item in path_reviews})
    if unknown_decisions:
        global_issues.append({"code": "architecture_decision_without_locator_bearing_path", "path_ids": unknown_decisions})
    review_required_ids = sorted(item["path_id"] for item in path_reviews if item["final_architecture_disposition"] == "review_required")
    failed_ids = sorted(item["path_id"] for item in path_reviews if not item["derivation_complete"])
    migration_ready = not global_issues and not review_required_ids
    artifact = {
        "schema_version": SCHEMA_VERSION,
        "review_id": "",
        "evaluation_id": structure.get("evaluation_id"),
        "audit_mode": audit_mode,
        "inputs": {
            "candidate_sha256": candidate_sha,
            "normalized_candidate_file_sha256": candidate_file_sha256,
            "item_inventory_file_sha256": inventory_file_sha256,
            "structure_audit_file_sha256": structure_file_sha256,
        },
        "thresholds": {
            "long_displayed_locator_string": {"operator": ">", "displayed_locator_count": DISPLAYED_LOCATOR_THRESHOLD},
            "long_continuous_range": {"operator": ">", "inclusive_range_span": CONTINUOUS_RANGE_SPAN_THRESHOLD},
            "numeric_trigger_is_automatic_defect": False,
        },
        "path_reviews": path_reviews,
        "summary": {
            "locator_bearing_path_count": len(path_reviews),
            "long_string_review_trigger_count": sum(item["long_displayed_locator_string_review_trigger"] is True for item in path_reviews),
            "long_range_review_trigger_count": sum(item["long_continuous_range_review_trigger"] is True for item in path_reviews),
            "review_required_path_ids": review_required_ids,
            "derivation_failed_path_ids": failed_ids,
            "removed_historical_defect_ids": sorted({defect_id for item in path_reviews for defect_id in item["removed_structured_defect_ids"]}),
            "retained_historical_defect_ids": sorted({defect_id for item in path_reviews for defect_id in item["retained_structured_defect_ids"]}),
        },
        "derivation_issues": sorted(global_issues, key=lambda item: (str(item.get("path_id", "")), str(item.get("code", "")))),
        "migration_ready": migration_ready,
        "source_or_candidate_reinterpreted": False,
        "display_prose_parsed": False,
        "historical_artifacts_mutated": False,
        "review_sha256": "",
    }
    artifact["review_id"] = f"STRUCTREV-{canonical_hash(artifact)[:12].upper()}"
    artifact["review_sha256"] = canonical_hash(artifact, "review_sha256")
    validate_structure_locator_review_semantics(artifact)
    return artifact


def apply_deterministic_structure_corrections(
    ledgers: Mapping[str, Any], review: Mapping[str, Any], *, audit_mode: str
) -> dict[str, Any]:
    """Return an active V7 ledger copy; never mutate the frozen V6 ledgers."""

    _require(review.get("schema_version") == SCHEMA_VERSION, "structure_review_schema", "Expected the V7 structure-locator review artifact.")
    _require(review.get("review_sha256") == canonical_hash(review, "review_sha256"), "structure_review_hash_mismatch", "The V7 structure-locator review self-hash does not reconstruct.")
    validate_structure_locator_review_semantics(review)
    review_required = review.get("summary", {}).get("review_required_path_ids", [])
    derivation_failed = review.get("summary", {}).get("derivation_failed_path_ids", [])
    _require(not derivation_failed, "structure_locator_derivation_incomplete", "Displayed-locator grouping or range spans cannot be reconstructed from frozen structured fields.", derivation_failed)
    if audit_mode == "full":
        _require(not review_required, "supplemental_architecture_review_required", "A newly triggered heading lacks a frozen structured architecture determination.", review_required)

    active = deepcopy(ledgers)
    removed_ids = set(review.get("summary", {}).get("removed_historical_defect_ids", []))
    active["defects"] = [item for item in active.get("defects", []) if item.get("defect_id") not in removed_ids]
    if isinstance(active.get("context"), dict):
        active["context"]["defects"] = [item for item in active["context"].get("defects", []) if item.get("defect_id") not in removed_ids]

    corrected_nodes: list[dict[str, Any]] = []
    for path_review in review.get("path_reviews", []):
        if path_review.get("final_architecture_disposition") != "historical_false_positive_removed":
            continue
        node_id = path_review.get("terminal_node_id")
        remaining_node_defects = [
            defect
            for defect in active["defects"]
            if _architecture_defect(defect) and _affected(defect, path_review.get("path_id"), node_id)
        ]
        _require(not remaining_node_defects, "structure_correction_conflict", "A node cannot be restored while an independent architecture defect remains.", {"node_id": node_id, "defect_ids": [item.get("defect_id") for item in remaining_node_defects]})
        node = next((item for item in active.get("nodes", []) if item.get("node_id") == node_id), None)
        _require(isinstance(node, dict), "structure_correction_binding_mismatch", "A removed defect does not resolve to its frozen NODE-* judgment.", node_id)
        component = node.get("component_judgments", {}).get("heading_access_architecture")
        _require(isinstance(component, dict) and component.get("status") in {"minor_issues", "major_issues", "fails"}, "structure_correction_status_ambiguous", "The historical architecture penalty is not represented by a correctable adverse node status.", {"node_id": node_id, "status": component.get("status") if isinstance(component, dict) else None})
        old_status = component["status"]
        component["status"] = "passes"
        corrected_nodes.append({"node_id": node_id, "old_status": old_status, "new_status": "passes", "rule_id": "STRUCT-V7-RESTORE-NODE-AFTER-SOLE-FALSE-POSITIVE"})

    active["v7_structure_locator_review"] = deepcopy(review)
    active["v7_structure_correction"] = {
        "removed_defect_ids": sorted(removed_ids),
        "corrected_node_statuses": sorted(corrected_nodes, key=lambda item: item["node_id"]),
        "review_required_path_ids": sorted(review_required),
        "historical_ledgers_mutated": False,
    }
    return active
