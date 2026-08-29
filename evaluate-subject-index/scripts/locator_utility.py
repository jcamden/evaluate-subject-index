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


def combined_state_errors(
    record: Mapping[str, Any], defects: Iterable[Mapping[str, Any]] = ()
) -> list[str]:
    """Return deterministic V7 errors for an incomplete or contradictory state."""

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
        errors.extend(_defect_errors(locator_id, matched))
        invalid_destination = scope == "excluded" or any(
            defect.get("defect_kind") in INVALID_DESTINATION_KINDS for defect in matched
        )
        no_fit_root = any(
            defect.get("root_cause_family") in NO_FIT_ROOT_CAUSE_FAMILIES
            for defect in matched
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
        if judgment == "supported" and (fit_codes or fit_defects):
            non_cosmetic = fit_codes or any(
                defect.get("severity") != "cosmetic" for defect in fit_defects
            )
            if non_cosmetic:
                errors.append("inconsistent:supported_with_independent_fit_defect")
        if judgment == "partially_supported" and any(
            defect.get("severity") == "critical" for defect in fit_defects
        ):
            errors.append("inconsistent:partial_with_critical_fit_defect")
        if (
            judgment == "partially_supported"
            and fit_codes
            and severity == "critical"
        ):
            errors.append("inconsistent:partial_with_critical_fit_defect")
        if (
            judgment == "unsupported"
            and treatment in PARTIAL_TREATMENT_CLASSES
            and not invalid_destination
            and not no_fit_root
            and not fit_codes
            and not fit_defects
            and (
                bool(set(codes) & CONSEQUENCE_ONLY_CODES)
                or any(defect.get("code") in CONSEQUENCE_ONLY_CODES for defect in matched)
            )
        ):
            errors.append("ambiguous:bare_loc_pos_does_not_establish_complete_path_fit")
        if (
            judgment == "unsupported"
            and treatment in MATERIAL_TREATMENT_CLASSES
            and not invalid_destination
            and not no_fit_root
            and not fit_codes
            and not fit_defects
        ):
            errors.append("incomplete:unsupported_material_treatment_requires_classifying_fit_or_no_fit_state")

    return sorted(set(errors))


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
    record: Mapping[str, Any], matched_defects: list[Mapping[str, Any]]
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
    if not severities:
        return None, False
    rank = {"none": 0, "cosmetic": 1, "minor": 2, "major": 3, "critical": 4}
    return max(severities, key=lambda value: rank.get(value, -1)), True


def assign_locator_utility(
    record: Mapping[str, Any], defects: Iterable[Mapping[str, Any]] = ()
) -> LocatorUtilityAssignment:
    """Validate and map one locator under the frozen V7 two-axis rules."""

    defects = list(defects)
    errors = combined_state_errors(record, defects)
    if errors:
        raise ValueError(";".join(errors))

    locator_id = str(record["locator_id"])
    judgment = str(record["judgment"])
    treatment = str(record["treatment_class"])
    scope = str(record["source_scope_status"])
    codes = set(record.get("error_codes", []))
    matched = relevant_structured_defects(locator_id, defects)
    defect_ids = tuple(sorted(str(item["defect_id"]) for item in matched))
    invalid_destination = scope == "excluded" or any(
        item.get("defect_kind") in INVALID_DESTINATION_KINDS for item in matched
    )
    no_fit_root = any(
        item.get("root_cause_family") in NO_FIT_ROOT_CAUSE_FAMILIES for item in matched
    )
    uninspectable = judgment == "uninspectable"
    inspectability = inspectability_state(scope, treatment)
    treatment_category, treatment_score, treatment_rule = _treatment_axis(
        treatment,
        uninspectable=uninspectable,
        invalid_destination=invalid_destination,
    )
    effective_severity, has_fit_evidence = _effective_fit_severity(record, matched)

    if uninspectable:
        fit_category = "uninspectable"
        fit_score = None
        fit_rule = "F-UNINSPECTABLE-BOUND"
        disposition = "bounded"
        reason = "The frozen destination is uninspectable; it is excluded centrally and enters 0-to-1 uncertainty bounds."
    elif invalid_destination or no_fit_root:
        fit_category = "no_fit"
        fit_score = Decimal("0.00")
        fit_rule = "F-NO-FIT-000"
        disposition = "assessable"
        reason = "Structured scope or destination evidence establishes no valid complete-path fit."
    elif judgment == "supported":
        fit_category = "exact_fit"
        fit_score = Decimal("1.00")
        fit_rule = "F-SUPPORTED-100"
        disposition = "assessable"
        reason = "The frozen supported judgment establishes exact complete-path fit."
    elif judgment == "partially_supported":
        fit_category = "material_partial_fit"
        fit_score = Decimal("0.70")
        fit_rule = "F-PARTIAL-070"
        disposition = "assessable"
        reason = "The frozen partially-supported judgment establishes material partial complete-path fit."
    else:
        if treatment == "absent":
            fit_category = "no_fit"
            fit_score = Decimal("0.00")
            fit_rule = "F-NO-FIT-000"
            reason = "The frozen treatment class establishes that the subject is absent."
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
    mapping_rule = f"{treatment_rule}+{fit_rule}+MIN"
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
        "combined_credit": None,
        "diagnostic_grade": None,
        "disposition": "not_measured",
        "disposition_reason": "The required locator assignment was not measured.",
        "used_in_precision_numerator": False,
        "uncertainty_bounds": {"lower": "0", "upper": "1"},
    }
