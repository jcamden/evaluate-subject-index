#!/usr/bin/env python3
"""Shared V6 locator-relevance credit and diagnostic-grade policy.

This module contains no score aggregation.  It validates one frozen locator
assignment and applies the deterministic V6 precedence rules used by both the
dimension calculator and the non-additive item-grading layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Iterable, Mapping


WEAK_PRESENCE_CLASSES = frozenset(
    {"passing_mention", "attribution_only", "citation_only", "incidental_example"}
)
SUBSTANTIVE_TREATMENT_CLASSES = frozenset({"substantive", "mixed"})
ZERO_DISQUALIFYING_CODES = frozenset({"SCP", "CMP", "CON", "STA"})
RELIABILITY_FAILURE_CODES = frozenset({"SCP", "CMP", "CON", "STA", "LOC_POS"})
KNOWN_FALSE_DESTINATION_KINDS = frozenset(
    {"fabricated_locator", "nonexistent_locator", "out_of_scope_locator"}
)
MEASURED_JUDGMENTS = frozenset({"supported", "partially_supported", "unsupported"})
VALID_JUDGMENTS = MEASURED_JUDGMENTS | {"uninspectable"}
VALID_SCOPE_STATUSES = frozenset({"indexable", "excluded", "unavailable", "ambiguous"})
VALID_TREATMENT_CLASSES = frozenset(
    {
        "substantive",
        "mixed",
        "passing_mention",
        "attribution_only",
        "citation_only",
        "incidental_example",
        "absent",
        "unavailable",
    }
)

RELIABILITY_CREDIT = {
    "supported": Decimal("1.00"),
    "partially_supported": Decimal("0.50"),
    "eligible_weak_presence": Decimal("0.25"),
    "other_unsupported": Decimal("0.00"),
}

DIAGNOSTIC_GRADE = {
    "supported": 100.0,
    "partially_supported": 70.0,
    "eligible_weak_presence": 25.0,
    "other_unsupported": 0.0,
    "uninspectable": None,
}


@dataclass(frozen=True)
class LocatorCreditAssignment:
    locator_id: str
    judgment: str
    treatment_class: str
    source_scope_status: str
    credit_tier: str
    reliability_credit: Decimal | None
    diagnostic_grade: float | None
    weak_presence_eligible: bool
    disqualifying_codes: tuple[str, ...]
    disqualifying_defect_ids: tuple[str, ...]
    rationale: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "locator_id": self.locator_id,
            "judgment": self.judgment,
            "treatment_class": self.treatment_class,
            "source_scope_status": self.source_scope_status,
            "credit_tier": self.credit_tier,
            "reliability_credit": (
                None if self.reliability_credit is None else decimal_text(self.reliability_credit)
            ),
            "diagnostic_grade": self.diagnostic_grade,
            "weak_presence_eligible": self.weak_presence_eligible,
            "disqualifying_codes": list(self.disqualifying_codes),
            "disqualifying_defect_ids": list(self.disqualifying_defect_ids),
            "rationale": self.rationale,
        }


def decimal_text(value: Decimal) -> str:
    if value == value.to_integral():
        return str(value.quantize(Decimal(1)))
    return format(value.normalize(), "f")


def combined_state_errors(record: Mapping[str, Any]) -> list[str]:
    """Return deterministic errors for contradictory or incomplete states."""

    required = (
        "locator_id",
        "judgment",
        "treatment_class",
        "source_scope_status",
        "error_codes",
    )
    errors = [f"missing:{field}" for field in required if field not in record]
    if errors:
        return errors

    locator_id = record.get("locator_id")
    judgment = record.get("judgment")
    treatment = record.get("treatment_class")
    scope = record.get("source_scope_status")
    codes = record.get("error_codes")

    if not isinstance(locator_id, str) or not locator_id.startswith("LOC-"):
        errors.append("invalid:locator_id")
    if judgment not in VALID_JUDGMENTS:
        errors.append("invalid:judgment")
    if treatment not in VALID_TREATMENT_CLASSES:
        errors.append("invalid:treatment_class")
    if scope not in VALID_SCOPE_STATUSES:
        errors.append("invalid:source_scope_status")
    if not isinstance(codes, list) or not all(isinstance(code, str) for code in codes):
        errors.append("invalid:error_codes")
        codes = []

    if judgment in {"supported", "partially_supported"}:
        if scope != "indexable":
            errors.append("inconsistent:positive_judgment_requires_indexable_scope")
        if treatment not in SUBSTANTIVE_TREATMENT_CLASSES:
            errors.append("inconsistent:positive_judgment_requires_material_treatment")

    if scope == "excluded" and judgment != "unsupported":
        errors.append("inconsistent:excluded_scope_requires_unsupported")
    if scope in {"unavailable", "ambiguous"} and judgment != "uninspectable":
        errors.append("inconsistent:unknown_scope_requires_uninspectable")
    if treatment == "unavailable" and judgment != "uninspectable":
        errors.append("inconsistent:unavailable_treatment_requires_uninspectable")
    if judgment == "uninspectable" and scope == "excluded":
        errors.append("inconsistent:known_excluded_scope_is_not_uninspectable")

    if judgment in {"supported", "partially_supported"} and set(codes) & ZERO_DISQUALIFYING_CODES:
        errors.append("inconsistent:positive_judgment_with_independent_zero_failure")
    if judgment == "unsupported" and treatment in SUBSTANTIVE_TREATMENT_CLASSES:
        if not set(codes) & RELIABILITY_FAILURE_CODES:
            errors.append("incomplete:unsupported_material_treatment_requires_failure_code")

    return sorted(set(errors))


def relevant_structured_defects(
    locator_id: str, defects: Iterable[Mapping[str, Any]]
) -> list[Mapping[str, Any]]:
    result: list[Mapping[str, Any]] = []
    for defect in defects:
        affected = defect.get("affected_item_ids", defect.get("affected_ids", []))
        if not isinstance(affected, list) or locator_id not in affected:
            continue
        result.append(defect)
    return result


def assign_locator_credit(
    record: Mapping[str, Any], defects: Iterable[Mapping[str, Any]] = ()
) -> LocatorCreditAssignment:
    """Validate and credit one locator using the frozen V6 precedence."""

    errors = combined_state_errors(record)
    if errors:
        raise ValueError(";".join(errors))

    locator_id = str(record["locator_id"])
    judgment = str(record["judgment"])
    treatment = str(record["treatment_class"])
    scope = str(record["source_scope_status"])
    codes = set(record.get("error_codes", []))
    matched_defects = relevant_structured_defects(locator_id, defects)
    structured_zero_defects = [
        defect
        for defect in matched_defects
        if defect.get("code") in ZERO_DISQUALIFYING_CODES
    ]
    false_destination_defects = [
        defect
        for defect in matched_defects
        if defect.get("defect_kind") in KNOWN_FALSE_DESTINATION_KINDS
    ]
    disqualifying_codes = sorted(
        (codes | {str(defect.get("code")) for defect in structured_zero_defects})
        & ZERO_DISQUALIFYING_CODES
    )
    disqualifying_defect_ids = sorted(
        str(defect.get("defect_id"))
        for defect in [*structured_zero_defects, *false_destination_defects]
        if defect.get("defect_id")
    )
    disqualifying_defect_ids = sorted(set(disqualifying_defect_ids))

    if judgment in {"supported", "partially_supported"} and (
        structured_zero_defects or false_destination_defects
    ):
        raise ValueError("inconsistent:positive_judgment_with_structured_zero_failure")

    if judgment == "uninspectable":
        return LocatorCreditAssignment(
            locator_id,
            judgment,
            treatment,
            scope,
            "uninspectable",
            None,
            None,
            False,
            tuple(disqualifying_codes),
            tuple(disqualifying_defect_ids),
            "Evidence is uninspectable; the assignment is neutral and enters uncertainty bounds.",
        )

    if scope != "indexable" or false_destination_defects:
        reason = (
            "A known out-of-scope or nonindexable assignment receives zero."
            if scope != "indexable"
            else "A validated fabricated, nonexistent, or out-of-scope defect requires zero."
        )
        return LocatorCreditAssignment(
            locator_id,
            judgment,
            treatment,
            scope,
            "other_unsupported",
            RELIABILITY_CREDIT["other_unsupported"],
            DIAGNOSTIC_GRADE["other_unsupported"],
            False,
            tuple(sorted(set(disqualifying_codes) | ({"SCP"} if scope != "indexable" else set()))),
            tuple(disqualifying_defect_ids),
            reason,
        )

    if judgment == "supported":
        tier = "supported"
        rationale = "The page substantively supports the complete heading path."
    elif judgment == "partially_supported":
        tier = "partially_supported"
        rationale = "The page materially supports the subject but only partially supports the complete path."
    elif treatment in WEAK_PRESENCE_CLASSES and not disqualifying_codes:
        tier = "eligible_weak_presence"
        rationale = (
            "The page contains the subject only weakly, incidentally, or as attribution/citation; "
            "it is not substantive index treatment, remains editorially unjustified, and receives "
            "limited credit only to distinguish it from a wholly false destination."
        )
    else:
        tier = "other_unsupported"
        rationale = (
            "The assignment is unsupported or independently invalid and receives no reliability credit."
        )

    return LocatorCreditAssignment(
        locator_id,
        judgment,
        treatment,
        scope,
        tier,
        RELIABILITY_CREDIT[tier],
        DIAGNOSTIC_GRADE[tier],
        tier == "eligible_weak_presence",
        tuple(disqualifying_codes),
        tuple(disqualifying_defect_ids),
        rationale,
    )
