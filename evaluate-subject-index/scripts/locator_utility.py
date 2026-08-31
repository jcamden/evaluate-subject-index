#!/usr/bin/env python3
"""Deterministic V7 two-axis locator utility derived from frozen evidence.

This module performs no score aggregation and never reads rationale or evidence
prose.  It validates one combined locator state, assigns independent treatment
and complete-path-fit ceilings, and combines them with ``min(T, F)``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Iterable, Mapping


WEAK_PRESENCE_CLASSES = frozenset(
    {"passing_mention", "attribution_only", "citation_only", "incidental_example"}
)
MATERIAL_TREATMENT_CLASSES = frozenset({"substantive", "mixed"})
PARTIAL_TREATMENT_CLASSES = MATERIAL_TREATMENT_CLASSES | WEAK_PRESENCE_CLASSES
VALID_TREATMENT_CLASSES = PARTIAL_TREATMENT_CLASSES | {"absent", "unavailable"}
VALID_JUDGMENTS = frozenset(
    {"supported", "partially_supported", "unsupported", "uninspectable"}
)
MEASURED_JUDGMENTS = frozenset({"supported", "partially_supported", "unsupported"})
VALID_SCOPE_STATUSES = frozenset({"indexable", "excluded", "unavailable", "ambiguous"})
VALID_SEVERITIES = frozenset({"none", "cosmetic", "minor", "major", "critical"})
VALID_DEFECT_SEVERITIES = frozenset({"cosmetic", "minor", "major", "critical"})

VALID_CODES = frozenset(
    {
        "SCP",
        "COV",
        "SEL",
        "CON",
        "STA",
        "LOC_POS",
        "LOC_NEG",
        "CMP",
        "HED",
        "SUB",
        "XRF",
        "DEN",
        "MEC",
    }
)
TREATMENT_ONLY_CODES = frozenset({"SEL"})
FIT_RELEVANT_CODES = frozenset({"SCP", "CON", "STA", "CMP", "HED", "SUB"})
CONSEQUENCE_ONLY_CODES = frozenset({"LOC_POS"})
FIT_NEUTRAL_CODES = frozenset({"MEC"})
INVALID_LOCATOR_FIT_CODES = frozenset({"COV", "LOC_NEG", "XRF", "DEN"})

VALID_DEFECT_KINDS = frozenset(
    {
        "generic",
        "central_omission",
        "fabricated_locator",
        "nonexistent_locator",
        "out_of_scope_locator",
        "stance_reversal",
        "misleading_relationship",
        "substitutive_see",
        "circular_or_chained_reference",
        "misleading_access_route",
        "unsupported_reference",
        "mechanical_invariant",
        "representation_corruption",
        "clutter_pattern",
        "density_distribution",
        "scope_failure",
    }
)
INVALID_DESTINATION_KINDS = frozenset(
    {"fabricated_locator", "nonexistent_locator", "out_of_scope_locator", "scope_failure"}
)
FIT_RELEVANT_DEFECT_KINDS = frozenset(
    {"stance_reversal", "misleading_relationship", "misleading_access_route"}
)
FIT_NEUTRAL_DEFECT_KINDS = frozenset(
    {"clutter_pattern", "density_distribution", "mechanical_invariant", "representation_corruption"}
)
INVALID_LOCATOR_DEFECT_KINDS = frozenset(
    {
        "central_omission",
        "substitutive_see",
        "circular_or_chained_reference",
        "unsupported_reference",
    }
)
NO_FIT_ROOT_CAUSE_FAMILIES = frozenset(
    {
        "absent_subject",
        "wrong_subject",
        "wrong_sense",
        "no_path_fit",
        "nonindexable_destination",
        "fabricated_destination",
        "nonexistent_destination",
        "out_of_scope_destination",
    }
)

TREATMENT_SCORES = {
    "substantive": Decimal("1.00"),
    "mixed": Decimal("0.70"),
    "weak_presence": Decimal("0.25"),
    "absent": Decimal("0.00"),
    "invalid_destination": Decimal("0.00"),
}
FIT_SCORES = {
    "exact_fit": Decimal("1.00"),
    "material_partial_fit": Decimal("0.70"),
    "material_mismatch": Decimal("0.35"),
    "severe_mismatch": Decimal("0.15"),
    "no_fit": Decimal("0.00"),
}

LEGACY_FIT_COMPATIBILITY_RULE_ID = (
    "F-COMPAT-LEGACY-CODE-SEVERITY-ONLY-V1"
)
SUPPLEMENTAL_FIT_RULE_IDS = {
    "exact_fit": "F-SUPPLEMENTAL-EXACT-100",
    "material_partial_fit": "F-SUPPLEMENTAL-PARTIAL-070",
    "material_mismatch": "F-SUPPLEMENTAL-MISMATCH-035",
    "severe_mismatch": "F-SUPPLEMENTAL-SEVERE-015",
    "no_fit": "F-SUPPLEMENTAL-NO-FIT-000",
}
UNRESOLVED_REASON_MESSAGES = {
    "bare_loc_pos_without_fit_cause": (
        "LOC_POS records a locator-precision consequence but does not identify a complete-path-fit cause."
    ),
    "unsupported_material_treatment_without_fit_classifier": (
        "The unsupported material treatment lacks a unique structured complete-path-fit classifier."
    ),
    "fit_evidence_without_classifying_severity": (
        "Fit-relevant evidence with none or cosmetic severity cannot select a complete-path-fit category."
    ),
}


def decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    if value == value.to_integral():
        return str(value.quantize(Decimal(1)))
    return format(value.normalize(), "f")


def inspectability_state(scope: str, treatment: str) -> str:
    if scope == "excluded":
        return "known_excluded_nonindexable"
    if scope == "unavailable" or treatment == "unavailable":
        return "uninspectable_unavailable"
    if scope == "ambiguous":
        return "uninspectable_ambiguous"
    return "inspectable"


def relevant_structured_defects(
    locator_id: str, defects: Iterable[Mapping[str, Any]]
) -> list[Mapping[str, Any]]:
    result: list[Mapping[str, Any]] = []
    for defect in defects:
        affected = defect.get("affected_item_ids", defect.get("affected_ids", []))
        if isinstance(affected, list) and locator_id in affected:
            result.append(defect)
    return result


def historical_locator_fit_defects(
    structure: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    """Return only legacy top-level defects that predate ``defect_kind``.

    This is an explicit historical compatibility boundary.  Modern scoring-
    context defects remain subject to the complete modern contract and cannot
    become legacy-compatible merely by deleting ``defect_kind``.
    """

    if structure.get("schema_version") != "structure-audit-v3":
        return []
    defects = structure.get("defects", [])
    if not isinstance(defects, list):
        return []
    return [
        item
        for item in defects
        if isinstance(item, Mapping) and "defect_kind" not in item
    ]


def _defect_errors(locator_id: str, defects: Iterable[Mapping[str, Any]]) -> list[str]:
    errors: list[str] = []
    for index, defect in enumerate(relevant_structured_defects(locator_id, defects)):
        label = f"defect[{index}]"
        defect_id = defect.get("defect_id")
        code = defect.get("code")
        kind = defect.get("defect_kind")
        severity = defect.get("severity")
        if not isinstance(defect_id, str) or not defect_id.startswith("DEFECT-"):
            errors.append(f"invalid:{label}.defect_id")
        if code not in VALID_CODES:
            errors.append(f"invalid:{label}.code")
        if kind not in VALID_DEFECT_KINDS:
            errors.append(f"invalid:{label}.defect_kind")
        if severity not in VALID_DEFECT_SEVERITIES:
            errors.append(f"invalid:{label}.severity")
        if code in INVALID_LOCATOR_FIT_CODES:
            errors.append(f"invalid:locator_bound_{code.lower()}_defect")
        if kind in INVALID_LOCATOR_DEFECT_KINDS:
            errors.append(f"invalid:locator_bound_{kind}_defect")
    return errors


def _legacy_defect_errors(
    locator_id: str, defects: Iterable[Mapping[str, Any]]
) -> list[str]:
    errors: list[str] = []
    matched = relevant_structured_defects(locator_id, defects)
    defect_ids = [defect.get("defect_id") for defect in matched]
    if len(defect_ids) != len(set(defect_ids)):
        errors.append("invalid:duplicate_legacy_defect_id")
    for index, defect in enumerate(matched):
        label = f"legacy_defect[{index}]"
        defect_id = defect.get("defect_id")
        code = defect.get("code")
        severity = defect.get("severity")
        summary = defect.get("summary")
        affected = defect.get("affected_ids")
        if not isinstance(defect_id, str) or not defect_id.startswith("DEFECT-"):
            errors.append(f"invalid:{label}.defect_id")
        if code not in VALID_CODES:
            errors.append(f"invalid:{label}.code")
        if severity not in VALID_DEFECT_SEVERITIES:
            errors.append(f"invalid:{label}.severity")
        if not isinstance(summary, str):
            # The historical schema requires the field, but its prose is never
            # read or interpreted as part of compatibility classification.
            errors.append(f"invalid:{label}.summary")
        if (
            not isinstance(affected, list)
            or not affected
            or not all(isinstance(item, str) and item for item in affected)
            or len(affected) != len(set(affected))
            or locator_id not in affected
        ):
            errors.append(f"invalid:{label}.affected_ids")
        if "defect_kind" in defect:
            errors.append(f"invalid:{label}.unexpected_defect_kind")
        if code in INVALID_LOCATOR_FIT_CODES:
            errors.append(f"invalid:legacy_locator_bound_{str(code).lower()}_defect")
    return errors


def _legacy_compatibility_classifications(
    locator_id: str,
    scope: str,
    defects: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Project unique legacy code/severity fit classifications without prose."""

    classifications: list[dict[str, Any]] = []
    for defect in relevant_structured_defects(locator_id, defects):
        code = defect.get("code")
        severity = defect.get("severity")
        if code not in FIT_RELEVANT_CODES:
            continue
        if code == "SCP" and scope != "indexable":
            # Excluded destinations are handled by existing precedence; unknown
            # scope is not converted into a legacy mismatch classification.
            continue
        category_by_severity = {
            "minor": ("material_mismatch", "F-MINOR-MISMATCH-035"),
            "major": ("severe_mismatch", "F-MAJOR-MISMATCH-015"),
            "critical": ("no_fit", "F-NO-FIT-000"),
        }
        projected = category_by_severity.get(str(severity))
        if projected is None:
            continue
        fit_category, fit_rule_id = projected
        classifications.append(
            {
                "defect_id": str(defect["defect_id"]),
                "code": str(code),
                "severity": str(severity),
                "fit_category": fit_category,
                "fit_rule_id": fit_rule_id,
                "compatibility_rule_id": LEGACY_FIT_COMPATIBILITY_RULE_ID,
            }
        )
    return sorted(classifications, key=lambda item: item["defect_id"])


def _fit_category_for_severity(severity: Any) -> str | None:
    return {
        "minor": "material_mismatch",
        "major": "severe_mismatch",
        "critical": "no_fit",
    }.get(str(severity))


def _hard_state_errors(
    record: Mapping[str, Any],
    defects: Iterable[Mapping[str, Any]] = (),
    legacy_defects: Iterable[Mapping[str, Any]] = (),
) -> list[str]:
    """Return invalid or contradictory states that no supplement may bypass."""

    required = (
        "locator_id",
        "judgment",
        "treatment_class",
        "source_scope_status",
        "error_codes",
        "severity",
    )
    errors = [f"missing:{field}" for field in required if field not in record]
    if errors:
        return errors

    locator_id = record.get("locator_id")
    judgment = record.get("judgment")
    treatment = record.get("treatment_class")
    scope = record.get("source_scope_status")
    codes = record.get("error_codes")
    severity = record.get("severity")

    if not isinstance(locator_id, str) or not locator_id.startswith("LOC-"):
        errors.append("invalid:locator_id")
        locator_id = ""
    if judgment not in VALID_JUDGMENTS:
        errors.append("invalid:judgment")
    if treatment not in VALID_TREATMENT_CLASSES:
        errors.append("invalid:treatment_class")
    if scope not in VALID_SCOPE_STATUSES:
        errors.append("invalid:source_scope_status")
    if severity not in VALID_SEVERITIES:
        errors.append("invalid:severity")
    if not isinstance(codes, list) or not all(isinstance(code, str) for code in codes):
        errors.append("invalid:error_codes")
        codes = []
    else:
        if len(codes) != len(set(codes)):
            errors.append("invalid:duplicate_error_codes")
        unknown_codes = sorted(set(codes) - VALID_CODES)
        if unknown_codes:
            errors.extend(f"invalid:error_code:{code}" for code in unknown_codes)
        invalid_locator_codes = sorted(set(codes) & INVALID_LOCATOR_FIT_CODES)
        errors.extend(f"invalid:locator_bound_{code.lower()}_code" for code in invalid_locator_codes)

    if judgment in {"supported", "partially_supported"} and scope != "indexable":
        errors.append("inconsistent:positive_judgment_requires_indexable_scope")
    if judgment == "supported" and treatment not in MATERIAL_TREATMENT_CLASSES:
        errors.append("inconsistent:supported_requires_material_treatment")
    if judgment == "partially_supported" and treatment not in PARTIAL_TREATMENT_CLASSES:
        errors.append("inconsistent:partial_requires_relevant_presence")
    if scope == "excluded" and judgment != "unsupported":
        errors.append("inconsistent:excluded_scope_requires_unsupported")
    if scope in {"unavailable", "ambiguous"} and judgment != "uninspectable":
        errors.append("inconsistent:unknown_scope_requires_uninspectable")
    if treatment == "unavailable" and judgment != "uninspectable":
        errors.append("inconsistent:unavailable_treatment_requires_uninspectable")
    if judgment == "uninspectable" and scope == "excluded":
        errors.append("inconsistent:known_excluded_scope_is_not_uninspectable")
    if judgment == "uninspectable" and scope == "indexable" and treatment != "unavailable":
        errors.append("incomplete:uninspectable_requires_unknown_scope_or_treatment")
    if judgment == "unsupported" and treatment == "unavailable":
        errors.append("inconsistent:unsupported_cannot_use_unavailable_treatment")

    if locator_id:
        matched = relevant_structured_defects(locator_id, defects)
        legacy_matched = relevant_structured_defects(locator_id, legacy_defects)
        errors.extend(_defect_errors(locator_id, matched))
        errors.extend(_legacy_defect_errors(locator_id, legacy_matched))
        invalid_destination = scope == "excluded" or any(
            defect.get("defect_kind") in INVALID_DESTINATION_KINDS for defect in matched
        )
        no_fit_root = any(
            defect.get("root_cause_family") in NO_FIT_ROOT_CAUSE_FAMILIES
            for defect in [*matched, *legacy_matched]
        )
        if judgment in {"supported", "partially_supported"} and (invalid_destination or no_fit_root):
            errors.append("inconsistent:positive_judgment_with_no_fit_state")
        fit_codes = set(codes) & FIT_RELEVANT_CODES
        fit_defects = [
            defect
            for defect in matched
            if defect.get("code") in FIT_RELEVANT_CODES
            or defect.get("defect_kind") in FIT_RELEVANT_DEFECT_KINDS
        ]
        legacy_fit_defects = [
            defect
            for defect in legacy_matched
            if defect.get("code") in FIT_RELEVANT_CODES
        ]
        legacy_categories = {
            category
            for defect in legacy_fit_defects
            if (category := _fit_category_for_severity(defect.get("severity")))
            is not None
            and not (defect.get("code") == "SCP" and scope != "indexable")
        }
        existing_categories = {
            category
            for severity_value in [
                *([severity] if fit_codes else []),
                *(defect.get("severity") for defect in fit_defects),
            ]
            if (category := _fit_category_for_severity(severity_value)) is not None
        }
        if legacy_categories and len(legacy_categories | existing_categories) != 1:
            errors.append("inconsistent:multiple_fit_classifications_possible")
        if judgment == "supported" and (fit_codes or fit_defects or legacy_fit_defects):
            non_cosmetic = (
                bool(fit_codes)
                or any(defect.get("severity") != "cosmetic" for defect in fit_defects)
                or any(
                    defect.get("severity") != "cosmetic"
                    for defect in legacy_fit_defects
                )
            )
            if non_cosmetic:
                errors.append("inconsistent:supported_with_independent_fit_defect")
        if judgment == "partially_supported" and any(
            defect.get("severity") == "critical" for defect in fit_defects
        ):
            errors.append("inconsistent:partial_with_critical_fit_defect")
        if judgment == "partially_supported" and any(
            defect.get("severity") == "critical" for defect in legacy_fit_defects
        ):
            errors.append("inconsistent:partial_with_critical_fit_defect")
        if (
            judgment == "partially_supported"
            and fit_codes
            and severity == "critical"
        ):
            errors.append("inconsistent:partial_with_critical_fit_defect")

    return sorted(set(errors))


def locator_fit_state_analysis(
    record: Mapping[str, Any],
    defects: Iterable[Mapping[str, Any]] = (),
    legacy_defects: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Classify one unsupplemented state into deterministic, unresolved, or invalid.

    The returned unresolved reasons are the only failures that a separately
    authorized locator-fit supplement may resolve.  Invalid and contradictory
    states always remain hard failures.
    """

    defects = list(defects)
    legacy_defects = list(legacy_defects)
    hard_errors = _hard_state_errors(record, defects, legacy_defects)
    locator_id = record.get("locator_id")
    if hard_errors or not isinstance(locator_id, str):
        return {
            "hard_errors": sorted(set(hard_errors)),
            "unresolved_reason_codes": [],
            "legacy_compatibility_classifications": [],
            "applicable_legacy_defect_ids": [],
        }

    judgment = str(record.get("judgment"))
    treatment = str(record.get("treatment_class"))
    scope = str(record.get("source_scope_status"))
    codes = set(record.get("error_codes", []))
    matched = relevant_structured_defects(locator_id, defects)
    legacy_matched = relevant_structured_defects(locator_id, legacy_defects)
    invalid_destination = scope == "excluded" or any(
        defect.get("defect_kind") in INVALID_DESTINATION_KINDS
        for defect in matched
    )
    no_fit_root = any(
        defect.get("root_cause_family") in NO_FIT_ROOT_CAUSE_FAMILIES
        for defect in matched
    ) or any(
        defect.get("root_cause_family") in NO_FIT_ROOT_CAUSE_FAMILIES
        for defect in legacy_matched
    )
    fit_codes = codes & FIT_RELEVANT_CODES
    modern_fit_defects = [
        defect
        for defect in matched
        if defect.get("code") in FIT_RELEVANT_CODES
        or defect.get("defect_kind") in FIT_RELEVANT_DEFECT_KINDS
    ]
    legacy_fit_defects = [
        defect
        for defect in legacy_matched
        if defect.get("code") in FIT_RELEVANT_CODES
        and not (
            defect.get("code") == "SCP" and scope != "indexable"
        )
    ]
    legacy_classifications = _legacy_compatibility_classifications(
        locator_id, scope, legacy_matched
    )
    direct_fit_severities = [str(record.get("severity"))] if fit_codes else []
    modern_fit_severities = [
        str(defect.get("severity")) for defect in modern_fit_defects
    ]
    legacy_fit_severities = [
        item["severity"] for item in legacy_classifications
    ]
    classifying_severities = {
        *direct_fit_severities,
        *modern_fit_severities,
        *legacy_fit_severities,
    } & {"minor", "major", "critical"}
    has_fit_evidence = bool(
        fit_codes or modern_fit_defects or legacy_classifications
    )
    has_nonclassifying_fit_evidence = bool(
        (fit_codes or modern_fit_defects or legacy_fit_defects)
        and not classifying_severities
    )
    has_loc_pos = bool(codes & CONSEQUENCE_ONLY_CODES) or any(
        defect.get("code") in CONSEQUENCE_ONLY_CODES
        for defect in [*matched, *legacy_matched]
    )

    unresolved: list[str] = []
    if (
        judgment == "unsupported"
        and treatment in PARTIAL_TREATMENT_CLASSES
        and not invalid_destination
        and not no_fit_root
    ):
        if has_nonclassifying_fit_evidence:
            unresolved.append("fit_evidence_without_classifying_severity")
        elif not has_fit_evidence and has_loc_pos:
            unresolved.append("bare_loc_pos_without_fit_cause")
        elif treatment in MATERIAL_TREATMENT_CLASSES and not has_fit_evidence:
            unresolved.append(
                "unsupported_material_treatment_without_fit_classifier"
            )

    return {
        "hard_errors": [],
        "unresolved_reason_codes": sorted(set(unresolved)),
        "legacy_compatibility_classifications": legacy_classifications,
        "applicable_legacy_defect_ids": sorted(
            str(item["defect_id"]) for item in legacy_matched
        ),
    }


def combined_state_errors(
    record: Mapping[str, Any],
    defects: Iterable[Mapping[str, Any]] = (),
    legacy_defects: Iterable[Mapping[str, Any]] = (),
) -> list[str]:
    """Return deterministic V7 errors for an incomplete or contradictory state."""

    analysis = locator_fit_state_analysis(record, defects, legacy_defects)
    unresolved_errors = {
        "bare_loc_pos_without_fit_cause": (
            "ambiguous:bare_loc_pos_does_not_establish_complete_path_fit"
        ),
        "unsupported_material_treatment_without_fit_classifier": (
            "incomplete:unsupported_material_treatment_requires_classifying_fit_or_no_fit_state"
        ),
        "fit_evidence_without_classifying_severity": (
            "ambiguous:unsupported_fit_failure_requires_minor_major_or_critical_severity"
        ),
    }
    return sorted(
        {
            *analysis["hard_errors"],
            *(
                unresolved_errors[reason]
                for reason in analysis["unresolved_reason_codes"]
            ),
        }
    )


@dataclass(frozen=True)
class LocatorUtilityAssignment:
    locator_id: str
    judgment: str
    treatment_class: str | None
    source_scope_status: str | None
    inspectability: str
    error_codes: tuple[str, ...]
    applicable_structured_defect_ids: tuple[str, ...]
    locator_severity: str | None
    effective_fit_severity: str | None
    treatment_category: str
    treatment_score: Decimal | None
    fit_category: str
    fit_score: Decimal | None
    treatment_rule_id: str
    fit_rule_id: str
    mapping_rule_id: str
    fit_classification_source: str
    compatibility_rule_ids: tuple[str, ...]
    supplemental_fit_decision_id: str | None
    supplemental_fit_evidence_ids: tuple[str, ...]
    combined_credit: Decimal | None
    diagnostic_grade: int | float | None
    disposition: str
    disposition_reason: str
    uncertainty_lower: Decimal
    uncertainty_upper: Decimal

    def as_dict(self) -> dict[str, Any]:
        return {
            "locator_id": self.locator_id,
            "judgment": self.judgment,
            "treatment_class": self.treatment_class,
            "source_scope_status": self.source_scope_status,
            "inspectability_state": self.inspectability,
            "error_codes": list(self.error_codes),
            "applicable_structured_defect_ids": list(self.applicable_structured_defect_ids),
            "locator_severity": self.locator_severity,
            "effective_fit_severity": self.effective_fit_severity,
            "treatment_category": self.treatment_category,
            "treatment_score": decimal_text(self.treatment_score),
            "fit_category": self.fit_category,
            "fit_score": decimal_text(self.fit_score),
            "treatment_rule_id": self.treatment_rule_id,
            "fit_rule_id": self.fit_rule_id,
            "mapping_rule_id": self.mapping_rule_id,
            "fit_classification_source": self.fit_classification_source,
            "compatibility_rule_ids": list(self.compatibility_rule_ids),
            "supplemental_fit_decision_id": self.supplemental_fit_decision_id,
            "supplemental_fit_evidence_ids": list(
                self.supplemental_fit_evidence_ids
            ),
            "combined_credit": decimal_text(self.combined_credit),
            "diagnostic_grade": self.diagnostic_grade,
            "disposition": self.disposition,
            "disposition_reason": self.disposition_reason,
            "used_in_precision_numerator": self.disposition == "assessable",
            "uncertainty_bounds": {
                "lower": decimal_text(self.uncertainty_lower),
                "upper": decimal_text(self.uncertainty_upper),
            },
        }


def _treatment_axis(
    treatment: str,
    *,
    uninspectable: bool,
    invalid_destination: bool,
) -> tuple[str, Decimal | None, str]:
    if uninspectable:
        return "uninspectable", None, "T-UNINSPECTABLE-BOUND"
    if invalid_destination:
        return "invalid_destination", Decimal("0.00"), "T-INVALID-DESTINATION-000"
    if treatment == "substantive":
        return "substantive", Decimal("1.00"), "T-SUBSTANTIVE-100"
    if treatment == "mixed":
        return "mixed", Decimal("0.70"), "T-MIXED-070"
    if treatment in WEAK_PRESENCE_CLASSES:
        return "weak_presence", Decimal("0.25"), "T-WEAK-025"
    if treatment == "absent":
        return "absent", Decimal("0.00"), "T-ABSENT-000"
    raise ValueError("invalid:treatment_axis_state")


def _effective_fit_severity(
    record: Mapping[str, Any],
    matched_defects: list[Mapping[str, Any]],
    legacy_classifications: Iterable[Mapping[str, Any]] = (),
) -> tuple[str | None, bool]:
    direct_fit_codes = set(record.get("error_codes", [])) & FIT_RELEVANT_CODES
    severities: list[str] = []
    if direct_fit_codes:
        severities.append(str(record.get("severity")))
    for defect in matched_defects:
        if (
            defect.get("code") in FIT_RELEVANT_CODES
            or defect.get("defect_kind") in FIT_RELEVANT_DEFECT_KINDS
        ):
            severities.append(str(defect.get("severity")))
    severities.extend(str(item.get("severity")) for item in legacy_classifications)
    if not severities:
        return None, False
    rank = {"none": 0, "cosmetic": 1, "minor": 2, "major": 3, "critical": 4}
    return max(severities, key=lambda value: rank.get(value, -1)), True


def assign_locator_utility(
    record: Mapping[str, Any],
    defects: Iterable[Mapping[str, Any]] = (),
    legacy_defects: Iterable[Mapping[str, Any]] = (),
    supplemental_fit_decision: Mapping[str, Any] | None = None,
) -> LocatorUtilityAssignment:
    """Validate and map one locator under the frozen V7 two-axis rules."""

    defects = list(defects)
    legacy_defects = list(legacy_defects)
    analysis = locator_fit_state_analysis(record, defects, legacy_defects)
    if analysis["hard_errors"]:
        raise ValueError(";".join(analysis["hard_errors"]))
    unresolved = analysis["unresolved_reason_codes"]
    if unresolved and supplemental_fit_decision is None:
        raise ValueError(";".join(
            {
                "bare_loc_pos_without_fit_cause": "ambiguous:bare_loc_pos_does_not_establish_complete_path_fit",
                "unsupported_material_treatment_without_fit_classifier": "incomplete:unsupported_material_treatment_requires_classifying_fit_or_no_fit_state",
                "fit_evidence_without_classifying_severity": "ambiguous:unsupported_fit_failure_requires_minor_major_or_critical_severity",
            }[reason]
            for reason in unresolved
        ))
    if supplemental_fit_decision is not None and not unresolved:
        raise ValueError("invalid:supplemental_fit_decision_for_deterministic_locator")

    locator_id = str(record["locator_id"])
    judgment = str(record["judgment"])
    treatment = str(record["treatment_class"])
    scope = str(record["source_scope_status"])
    codes = set(record.get("error_codes", []))
    matched = relevant_structured_defects(locator_id, defects)
    legacy_matched = relevant_structured_defects(locator_id, legacy_defects)
    defect_ids = tuple(
        sorted(
            {
                *(str(item["defect_id"]) for item in matched),
                *(str(item["defect_id"]) for item in legacy_matched),
            }
        )
    )
    invalid_destination = scope == "excluded" or any(
        item.get("defect_kind") in INVALID_DESTINATION_KINDS for item in matched
    )
    no_fit_root = any(
        item.get("root_cause_family") in NO_FIT_ROOT_CAUSE_FAMILIES
        for item in [*matched, *legacy_matched]
    )
    uninspectable = judgment == "uninspectable"
    inspectability = inspectability_state(scope, treatment)
    treatment_category, treatment_score, treatment_rule = _treatment_axis(
        treatment,
        uninspectable=uninspectable,
        invalid_destination=invalid_destination,
    )
    legacy_classifications = analysis["legacy_compatibility_classifications"]
    effective_severity, has_fit_evidence = _effective_fit_severity(
        record, matched, legacy_classifications
    )
    compatibility_rule_ids: tuple[str, ...] = ()
    supplemental_decision_id: str | None = None
    supplemental_evidence_ids: tuple[str, ...] = ()

    if supplemental_fit_decision is not None:
        fit_category = str(supplemental_fit_decision.get("fit_category"))
        if fit_category not in FIT_SCORES:
            raise ValueError("invalid:supplemental_fit_category")
        fit_score = FIT_SCORES[fit_category]
        fit_rule = SUPPLEMENTAL_FIT_RULE_IDS[fit_category]
        disposition = "assessable"
        reason = (
            "A separately authorized, hash-bound supplemental decision supplies only the complete-path-fit category."
        )
        fit_classification_source = "supplemental_locator_fit"
        supplemental_decision_id = str(
            supplemental_fit_decision.get("decision_id")
        )
        supplemental_evidence_ids = tuple(
            sorted(str(item) for item in supplemental_fit_decision.get("evidence_ids", []))
        )
    elif uninspectable:
        fit_category = "uninspectable"
        fit_score = None
        fit_rule = "F-UNINSPECTABLE-BOUND"
        disposition = "bounded"
        reason = "The frozen destination is uninspectable; it is excluded centrally and enters 0-to-1 uncertainty bounds."
        fit_classification_source = "frozen_uninspectable_state"
    elif invalid_destination or no_fit_root:
        fit_category = "no_fit"
        fit_score = Decimal("0.00")
        fit_rule = "F-NO-FIT-000"
        disposition = "assessable"
        reason = "Structured scope or destination evidence establishes no valid complete-path fit."
        fit_classification_source = "structured_no_fit_precedence"
    elif judgment == "supported":
        fit_category = "exact_fit"
        fit_score = Decimal("1.00")
        fit_rule = "F-SUPPORTED-100"
        disposition = "assessable"
        reason = "The frozen supported judgment establishes exact complete-path fit."
        fit_classification_source = "frozen_supported_judgment"
    elif judgment == "partially_supported":
        fit_category = "material_partial_fit"
        fit_score = Decimal("0.70")
        fit_rule = "F-PARTIAL-070"
        disposition = "assessable"
        reason = "The frozen partially-supported judgment establishes material partial complete-path fit."
        fit_classification_source = "frozen_partially_supported_judgment"
    else:
        if treatment == "absent":
            fit_category = "no_fit"
            fit_score = Decimal("0.00")
            fit_rule = "F-NO-FIT-000"
            reason = "The frozen treatment class establishes that the subject is absent."
            fit_classification_source = "frozen_absent_treatment"
        elif has_fit_evidence:
            if effective_severity == "critical":
                fit_category = "no_fit"
                fit_score = Decimal("0.00")
                fit_rule = "F-NO-FIT-000"
                reason = "A critical structured fit failure establishes no complete-path fit."
            elif effective_severity == "major":
                fit_category = "severe_mismatch"
                fit_score = Decimal("0.15")
                fit_rule = "F-MAJOR-MISMATCH-015"
                reason = "A validated major fit-relevant failure establishes a severe mismatch."
            elif effective_severity == "minor":
                fit_category = "material_mismatch"
                fit_score = Decimal("0.35")
                fit_rule = "F-MINOR-MISMATCH-035"
                reason = "A validated minor fit-relevant failure establishes a material mismatch."
            else:
                raise ValueError("ambiguous:unsupported_fit_failure_requires_minor_major_or_critical_severity")
            fit_classification_source = (
                "legacy_code_severity_compatibility"
                if legacy_classifications
                else "modern_structured_fit_evidence"
            )
            if legacy_classifications:
                compatibility_rule_ids = (
                    LEGACY_FIT_COMPATIBILITY_RULE_ID,
                )
        elif treatment in WEAK_PRESENCE_CLASSES:
            if codes & CONSEQUENCE_ONLY_CODES or any(
                item.get("code") in CONSEQUENCE_ONLY_CODES for item in matched
            ):
                raise ValueError("ambiguous:bare_loc_pos_does_not_establish_complete_path_fit")
            fit_category = "exact_fit"
            fit_score = Decimal("1.00")
            fit_rule = "F-WEAK-TREATMENT-ONLY-100"
            reason = (
                "The exhaustive structured state shows weak presence as the only failure and no independent path mismatch."
            )
            fit_classification_source = "frozen_weak_treatment_only"
        else:
            raise ValueError("incomplete:unsupported_material_treatment_requires_classifying_fit_or_no_fit_state")
        disposition = "assessable"

    combined = (
        None
        if treatment_score is None or fit_score is None
        else min(treatment_score, fit_score)
    )
    diagnostic_grade: int | float | None
    if combined is None:
        diagnostic_grade = None
    else:
        grade_value = combined * Decimal(100)
        diagnostic_grade = int(grade_value) if grade_value == grade_value.to_integral() else float(grade_value)
    rule_parts = [treatment_rule, fit_rule, *compatibility_rule_ids, "MIN"]
    mapping_rule = "+".join(rule_parts)
    return LocatorUtilityAssignment(
        locator_id=locator_id,
        judgment=judgment,
        treatment_class=treatment,
        source_scope_status=scope,
        inspectability=inspectability,
        error_codes=tuple(sorted(codes)),
        applicable_structured_defect_ids=defect_ids,
        locator_severity=str(record.get("severity")),
        effective_fit_severity=effective_severity,
        treatment_category=treatment_category,
        treatment_score=treatment_score,
        fit_category=fit_category,
        fit_score=fit_score,
        treatment_rule_id=treatment_rule,
        fit_rule_id=fit_rule,
        mapping_rule_id=mapping_rule,
        fit_classification_source=fit_classification_source,
        compatibility_rule_ids=compatibility_rule_ids,
        supplemental_fit_decision_id=supplemental_decision_id,
        supplemental_fit_evidence_ids=supplemental_evidence_ids,
        combined_credit=combined,
        diagnostic_grade=diagnostic_grade,
        disposition=disposition,
        disposition_reason=reason,
        uncertainty_lower=Decimal("0") if combined is None else combined,
        uncertainty_upper=Decimal("1") if combined is None else combined,
    )


def not_measured_assignment(locator_id: str) -> dict[str, Any]:
    """Return a neutral V7 ledger row for a pilot-only unmeasured locator."""

    return {
        "locator_id": locator_id,
        "judgment": "not_measured",
        "treatment_class": None,
        "source_scope_status": None,
        "inspectability_state": "not_measured",
        "error_codes": [],
        "applicable_structured_defect_ids": [],
        "locator_severity": None,
        "effective_fit_severity": None,
        "treatment_category": "not_measured",
        "treatment_score": None,
        "fit_category": "not_measured",
        "fit_score": None,
        "treatment_rule_id": "T-NOT-MEASURED-REJECT",
        "fit_rule_id": "F-NOT-MEASURED-REJECT",
        "mapping_rule_id": "T-NOT-MEASURED-REJECT+F-NOT-MEASURED-REJECT+MIN",
        "fit_classification_source": "not_measured",
        "compatibility_rule_ids": [],
        "supplemental_fit_decision_id": None,
        "supplemental_fit_evidence_ids": [],
        "combined_credit": None,
        "diagnostic_grade": None,
        "disposition": "not_measured",
        "disposition_reason": "The required locator assignment was not measured.",
        "used_in_precision_numerator": False,
        "uncertainty_bounds": {"lower": "0", "upper": "1"},
    }
