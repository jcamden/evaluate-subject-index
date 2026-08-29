#!/usr/bin/env python3
"""Deterministic V5 dimension ratings derived from frozen subject-index ledgers.

The canonical V5 path accepts artifact references and raw audit ledgers only.  It
never accepts diagnostic item grades, evaluator-selected headline ratings, or
publication-gate outcomes as score inputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable, Sequence

import jsonschema
from referencing import Registry, Resource


RUBRIC_VERSION = "subject-index-rubric-v5"
CALCULATION_PROFILE = "subject-index-dimension-calculation-v1"
CALCULATION_SCHEMA = "subject-index-dimension-calculations-v1"
INPUT_SCHEMA = "subject-index-dimension-calculation-input-v1"
MIGRATION_SCHEMA = "subject-index-score-migration-v2"
MIGRATION_VALIDATION_SCHEMA = "subject-index-score-migration-validation-v1"
TOOL_NAME = "dimension_score_cli.py"
TOOL_VERSION = "dimension-score-cli-v5.1.0"
METHODOLOGY_REPOSITORY = "https://github.com/jcamden/evaluate-subject-index"

WEIGHTS = {
    "meaningful_coverage": 20,
    "editorial_selectivity": 15,
    "conceptual_stance_fidelity": 15,
    "page_reference_reliability": 25,
    "findability_navigation": 20,
    "mechanics_consistency": 5,
}

PRIORITY_CREDIT = {"essential": Decimal(3), "major": Decimal(2), "optional": Decimal(1)}
COVERAGE_CREDIT = {"complete": Decimal(1), "partial": Decimal("0.5"), "missing": Decimal(0)}
SELECTIVITY_CREDIT = {
    "substantive": Decimal(1),
    "mixed": Decimal("0.5"),
    "passing_mention": Decimal(0),
    "attribution_only": Decimal(0),
    "citation_only": Decimal(0),
    "incidental_example": Decimal(0),
}
NODE_CREDIT = {
    "passes": Decimal(1),
    "minor_issues": Decimal("0.85"),
    "major_issues": Decimal("0.55"),
    "fails": Decimal(0),
}
MECHANICS_CREDIT = {
    "passes": Decimal(1),
    "cosmetic_issues": Decimal("0.95"),
    "minor_issues": Decimal("0.85"),
    "major_issues": Decimal("0.55"),
    "fails": Decimal(0),
}
TASK_CREDIT = {"succeeds": Decimal(1), "partially_succeeds": Decimal("0.5"), "fails": Decimal(0)}
REFERENCE_CREDIT = {"supported": Decimal(1), "partially_supported": Decimal("0.5"), "unsupported": Decimal(0)}

RELIABILITY_CODES = {"LOC_POS", "SCP", "CMP", "CON", "STA"}
CONCEPT_CODES = {"CON", "STA", "CMP"}
VALID_SEVERITY_BASES = {
    "critical": {"fabrication", "central_reversal", "broken_scope", "systemic_nonuse"},
    "major": {"materially_misleading", "blocked_retrieval"},
    "minor": {"localized_repairable_friction"},
    "cosmetic": {"no_retrieval_consequence"},
}
VALID_RETRIEVAL_CONSEQUENCES = {"blocks", "misleads", "slows", "none"}
VALID_ATTEMPT_STATUSES = {"meaningful_attempt", "empty", "structurally_incomplete", "unparseable"}
VALID_DEFECT_CODES = {"SCP", "COV", "SEL", "CON", "STA", "LOC_POS", "LOC_NEG", "CMP", "HED", "SUB", "XRF", "DEN", "MEC"}
VALID_DEFECT_KINDS = {
    "generic", "central_omission", "fabricated_locator", "nonexistent_locator", "out_of_scope_locator",
    "stance_reversal", "misleading_relationship", "substitutive_see", "circular_or_chained_reference",
    "misleading_access_route", "unsupported_reference", "mechanical_invariant", "representation_corruption",
    "clutter_pattern", "density_distribution", "scope_failure",
}
DEFECT_ITEM_FAMILIES = {
    "LOC-": "locator",
    "PATH-": "path",
    "SUBJ-": "subject",
    "TASK-": "task",
    "TREAT-": "treatment",
    "NODE-": "node",
    "XREF-": "cross_reference",
}
OWNER_CODES = {
    "meaningful_coverage": {"COV"},
    "editorial_selectivity": {"SEL", "DEN"},
    "conceptual_stance_fidelity": {"CON", "STA", "CMP"},
    "page_reference_reliability": {"SCP", "LOC_POS", "LOC_NEG", "CMP", "CON", "STA"},
    "findability_navigation": {"HED", "SUB", "XRF", "CMP"},
    "mechanics_consistency": {"MEC"},
}

CRITICAL_BASIS_KINDS = {
    "fabrication": {"fabricated_locator", "nonexistent_locator", "out_of_scope_locator"},
    "central_reversal": {"stance_reversal", "misleading_relationship"},
    "broken_scope": {
        "central_omission",
        "out_of_scope_locator",
        "scope_failure",
        "substitutive_see",
        "circular_or_chained_reference",
        "misleading_access_route",
    },
    "systemic_nonuse": {
        "generic",
        "mechanical_invariant",
        "representation_corruption",
        "clutter_pattern",
        "density_distribution",
        "scope_failure",
    },
}
CRITICAL_BASIS_OWNERS = {
    "fabrication": {"page_reference_reliability"},
    "central_reversal": {"conceptual_stance_fidelity"},
    "broken_scope": {"meaningful_coverage", "page_reference_reliability", "findability_navigation"},
    "systemic_nonuse": set(WEIGHTS),
}

ZERO = Decimal(0)
ONE = Decimal(1)
FIVE = Decimal(5)
HALF = Decimal("0.5")
HUNDRED = Decimal(100)
SIX_PLACES = Decimal("0.000001")
SCHEMA_ROOT = Path(__file__).resolve().parents[1] / "references" / "schemas"


class CalculationError(ValueError):
    """Structured, user-facing calculation failure."""

    def __init__(self, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


def require(condition: bool, code: str, message: str, details: Any = None) -> None:
    if not condition:
        raise CalculationError(code, message, details)


def require_methodology_commit(value: Any) -> str:
    require(
        isinstance(value, str)
        and len(value) == 40
        and all(character in "0123456789abcdef" for character in value),
        "invalid_methodology_commit",
        "The methodology commit must be an exact lowercase 40-character Git SHA-1.",
    )
    return value


def require_utc_timestamp(value: Any, *, label: str) -> str:
    require(isinstance(value, str) and value.endswith("Z"), "invalid_timestamp", f"{label} must be an RFC 3339 UTC timestamp ending in Z.")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise CalculationError("invalid_timestamp", f"{label} must be an RFC 3339 UTC timestamp ending in Z.") from exc
    require(parsed.utcoffset() == timezone.utc.utcoffset(parsed), "invalid_timestamp", f"{label} must use UTC.")
    return value


def require_portable_relative_path(value: Any, *, label: str) -> str:
    require(isinstance(value, str) and value, "nonportable_artifact_path", f"{label} must be a non-empty relative POSIX path.")
    drive_prefixed = len(value) >= 2 and value[1] == ":" and value[0].isalpha()
    require(
        not value.startswith(("/", "\\")) and not drive_prefixed and "\\" not in value,
        "nonportable_artifact_path",
        f"{label} must be a relative POSIX path and must not contain an absolute workspace path.",
        {"path": value},
    )
    return value


def portable_relative_reference(target: Path, container_path: Path, *, label: str) -> str:
    reference = os.path.relpath(target.resolve(), start=container_path.resolve().parent).replace(os.sep, "/")
    return require_portable_relative_path(reference, label=label)


def decimal_value(value: Any, field: str = "value") -> Decimal:
    if isinstance(value, bool) or value is None:
        raise CalculationError("invalid_decimal", f"{field} must be a decimal-compatible value.")
    try:
        return value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise CalculationError("invalid_decimal", f"{field} must be a decimal-compatible value.") from exc


def decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    if value == value.to_integral():
        return str(value.quantize(Decimal(1)))
    return format(value.normalize(), "f")


def displayed_number(value: Decimal | None, places: Decimal | None = None) -> float | int | None:
    if value is None:
        return None
    if places is not None:
        value = value.quantize(places, rounding=ROUND_HALF_UP)
    if value == value.to_integral():
        return int(value)
    return float(value)


def round_half_step(value: Decimal) -> Decimal:
    return (value / HALF).quantize(Decimal(1), rounding=ROUND_HALF_UP) * HALF


def round_points(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def rate(numerator: int | Decimal, denominator: int | Decimal) -> Decimal:
    denominator_value = decimal_value(denominator)
    if denominator_value == 0:
        return ZERO
    return decimal_value(numerator) / denominator_value


def rounded_rate(numerator: int, denominator: int) -> str:
    if denominator == 0:
        return "0"
    return decimal_text(rate(numerator, denominator).quantize(SIX_PLACES, rounding=ROUND_HALF_UP)) or "0"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def aliases_existing_file(path: Path, protected_paths: set[Path]) -> bool:
    """Reject resolved-path, symlink, and hard-link aliases before any write."""
    if path in protected_paths:
        return True
    if not path.exists():
        return False
    for protected in protected_paths:
        try:
            if protected.exists() and os.path.samefile(path, protected):
                return True
        except OSError:
            continue
    return False


def canonical_json_text(value: Any) -> str:
    """Serialize canonical JSON while retaining Decimal values as numbers."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, Decimal):
        require(value.is_finite(), "invalid_canonical_number", "Canonical JSON cannot contain a non-finite decimal.")
        return format(value, "f")
    if isinstance(value, float):
        decimal = Decimal(str(value))
        require(decimal.is_finite(), "invalid_canonical_number", "Canonical JSON cannot contain a non-finite float.")
        return format(decimal, "f")
    if isinstance(value, list):
        return "[" + ",".join(canonical_json_text(item) for item in value) + "]"
    if isinstance(value, dict):
        require(all(isinstance(key, str) for key in value), "invalid_canonical_object", "Canonical JSON object keys must be strings.")
        return "{" + ",".join(
            f"{json.dumps(key, ensure_ascii=False)}:{canonical_json_text(value[key])}"
            for key in sorted(value)
        ) + "}"
    raise CalculationError("invalid_canonical_value", f"Unsupported canonical JSON value: {type(value).__name__}.")


def canonical_hash(value: Any, excluded_field: str | None = None) -> str:
    clone = deepcopy(value)
    if excluded_field and isinstance(clone, dict):
        clone.pop(excluded_field, None)
    encoded = canonical_json_text(clone).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)
    except FileNotFoundError as exc:
        raise CalculationError("input_not_found", f"{label} does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise CalculationError("invalid_json", f"{label} is invalid JSON: {exc}") from exc
    require(isinstance(value, dict), "invalid_document", f"{label} must contain a JSON object.")
    return value


def schema_registry() -> Registry:
    registry = Registry()
    for path in SCHEMA_ROOT.glob("*.json"):
        # Ledger instances are loaded with Decimal so schema numeric keywords
        # (notably historical ``multipleOf: 0.5``) must use the same numeric
        # type.  Mixing Decimal instances with binary-float schema constants
        # raises inside jsonschema before it can return a validation error.
        document = json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)
        resource = Resource.from_contents(document)
        registry = registry.with_resource(path.resolve().as_uri(), resource).with_resource(path.name, resource)
    return registry


def validate_schema_document(document: dict[str, Any], schema_name: str, label: str) -> None:
    schema_path = SCHEMA_ROOT / schema_name
    schema = json.loads(schema_path.read_text(encoding="utf-8"), parse_float=Decimal)
    errors = sorted(
        jsonschema.Draft202012Validator(schema, registry=schema_registry()).iter_errors(document),
        key=lambda item: list(item.absolute_path),
    )
    if errors:
        error = errors[0]
        location = ".".join(map(str, error.absolute_path)) or "<root>"
        raise CalculationError(
            "input_schema_validation_failed",
            f"{label} does not satisfy {schema_name} at {location}: {error.message}",
            {"schema": schema_name, "path": location, "error_count": len(errors)},
        )


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def emit(value: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False))
    raise SystemExit(exit_code)


def portable_input_record(record: Any, label: str) -> tuple[str, str]:
    require(isinstance(record, dict), "invalid_input_reference", f"{label} must be an object.")
    require(set(record) == {"path", "sha256"}, "invalid_input_reference", f"{label} must contain exactly path and sha256.")
    path = record.get("path")
    digest = record.get("sha256")
    require_portable_relative_path(path, label=f"{label}.path")
    require(
        isinstance(digest, str) and len(digest) == 64 and all(char in "0123456789abcdef" for char in digest),
        "invalid_input_reference",
        f"{label}.sha256 must be a lowercase SHA-256 value.",
    )
    return path, digest


def resolve_input(config_path: Path, record: dict[str, Any], label: str) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    stored_path, expected_hash = portable_input_record(record, label)
    candidate = Path(stored_path)
    path = candidate if candidate.is_absolute() else config_path.parent / candidate
    path = path.resolve()
    actual_hash = sha256_file(path)
    require(
        actual_hash == expected_hash,
        "input_hash_mismatch",
        f"{label} hash does not match the frozen input reference.",
        {"path": stored_path, "expected_sha256": expected_hash, "actual_sha256": actual_hash},
    )
    document = load_json(path, label)
    artifact = {
        "role": label,
        "path": stored_path,
        "sha256": actual_hash,
        "schema_version": document.get("schema_version"),
    }
    return path, document, artifact


def validate_config_shape(config: dict[str, Any]) -> None:
    required = {"schema_version", "evaluation_id", "audit_mode", "inputs"}
    require(set(config) == required, "invalid_input_config", "Calculation input has missing or unexpected top-level fields.")
    require(config.get("schema_version") == INPUT_SCHEMA, "invalid_input_config", f"Expected {INPUT_SCHEMA}.")
    require(isinstance(config.get("evaluation_id"), str) and config["evaluation_id"], "invalid_input_config", "evaluation_id is required.")
    require(config.get("audit_mode") in {"full", "pilot"}, "invalid_input_config", "audit_mode must be full or pilot.")
    inputs = config.get("inputs")
    require(isinstance(inputs, dict), "invalid_input_config", "inputs must be an object.")
    allowed = {"chunk_manifest", "locator_audits", "missing_access_audits", "structure_audit", "migration_supplement"}
    require(set(inputs).issubset(allowed) and {"locator_audits", "missing_access_audits", "structure_audit"}.issubset(inputs), "invalid_input_config", "inputs has missing or unexpected fields.")
    require(isinstance(inputs["locator_audits"], list), "invalid_input_config", "locator_audits must be an array.")
    require(isinstance(inputs["missing_access_audits"], list), "invalid_input_config", "missing_access_audits must be an array.")
    require(bool(inputs["locator_audits"]), "invalid_input_config", "locator_audits must contain one frozen artifact per approved source unit.")
    require(bool(inputs["missing_access_audits"]), "invalid_input_config", "missing_access_audits must contain one frozen artifact per approved source unit.")


def validate_rate_field(record: dict[str, Any], count_key: str, denominator_key: str, rate_key: str, label: str) -> None:
    count = record.get(count_key)
    denominator = record.get(denominator_key)
    require(isinstance(count, int) and not isinstance(count, bool) and count >= 0, "invalid_scoring_context", f"{label}.{count_key} must be a nonnegative integer.")
    require(isinstance(denominator, int) and not isinstance(denominator, bool) and denominator >= count, "invalid_scoring_context", f"{label}.{denominator_key} must be at least {count_key}.")
    expected = rounded_rate(count, denominator)
    actual = decimal_text(decimal_value(record.get(rate_key), f"{label}.{rate_key}").quantize(SIX_PLACES, rounding=ROUND_HALF_UP))
    require(actual == expected, "invalid_scoring_context", f"{label}.{rate_key} must reconstruct from its count and denominator.", {"expected": expected, "actual": actual})


def validate_defect(record: Any, index: int) -> list[str]:
    label = f"scoring_context.defects[{index}]"
    required = {
        "defect_id", "code", "dimension_owner", "severity", "severity_basis", "retrieval_consequence",
        "defect_kind", "affected_item_ids", "affected_source_sections", "affected_structural_sections",
        "root_cause_family", "affected_count", "applicable_count", "affected_rate",
        "source_section_denominator", "source_section_rate", "structural_section_denominator",
        "structural_section_rate", "high_priority_access_destroyed",
    }
    require(isinstance(record, dict) and set(record) == required, "invalid_scoring_context", f"{label} has missing or unexpected fields.")
    require(isinstance(record["defect_id"], str) and record["defect_id"].startswith("DEFECT-"), "invalid_scoring_context", f"{label}.defect_id is invalid.")
    require(record["dimension_owner"] in WEIGHTS, "invalid_scoring_context", f"{label}.dimension_owner is invalid.")
    require(record["code"] in VALID_DEFECT_CODES and record["code"] in OWNER_CODES[record["dimension_owner"]], "invalid_scoring_context", f"{label}.code is incompatible with its dimension owner.")
    severity = record["severity"]
    require(severity in VALID_SEVERITY_BASES, "invalid_scoring_context", f"{label}.severity is invalid.")
    require(record["severity_basis"] in VALID_SEVERITY_BASES[severity], "invalid_scoring_context", f"{label}.severity_basis is inconsistent with severity.")
    require(record["retrieval_consequence"] in VALID_RETRIEVAL_CONSEQUENCES, "invalid_scoring_context", f"{label}.retrieval_consequence is invalid.")
    consequence_by_severity = {"critical": {"blocks", "misleads"}, "major": {"blocks", "misleads"}, "minor": {"slows"}, "cosmetic": {"none"}}
    require(record["retrieval_consequence"] in consequence_by_severity[severity], "invalid_scoring_context", f"{label} severity and retrieval consequence are inconsistent.")
    for field in ("affected_item_ids", "affected_source_sections", "affected_structural_sections"):
        values = record[field]
        require(isinstance(values, list) and all(isinstance(item, str) and item for item in values) and len(values) == len(set(values)), "invalid_scoring_context", f"{label}.{field} must contain unique non-empty strings.")
    require(bool(record["affected_item_ids"]), "invalid_scoring_context", f"{label}.affected_item_ids must identify at least one frozen item or GLOBAL-STRUCTURE.")
    require(bool(record["affected_source_sections"] or record["affected_structural_sections"]), "invalid_scoring_context", f"{label} must identify an affected source or structural section.")
    require(record["affected_count"] == len(record["affected_item_ids"]), "invalid_scoring_context", f"{label}.affected_count must equal the affected item-ID count.")
    validate_rate_field(record, "affected_count", "applicable_count", "affected_rate", label)
    source_copy = {**record, "source_section_count": len(record["affected_source_sections"])}
    validate_rate_field(source_copy, "source_section_count", "source_section_denominator", "source_section_rate", label)
    structural_copy = {**record, "structural_section_count": len(record["affected_structural_sections"])}
    validate_rate_field(structural_copy, "structural_section_count", "structural_section_denominator", "structural_section_rate", label)
    require(isinstance(record["root_cause_family"], str) and record["root_cause_family"], "invalid_scoring_context", f"{label}.root_cause_family is required.")
    require(record["defect_kind"] in VALID_DEFECT_KINDS, "invalid_scoring_context", f"{label}.defect_kind is invalid.")
    require(isinstance(record["high_priority_access_destroyed"], bool), "invalid_scoring_context", f"{label}.high_priority_access_destroyed must be boolean.")
    basis = record["severity_basis"]
    consequence = record["retrieval_consequence"]
    consequence_by_basis = {
        "fabrication": {"misleads"},
        "central_reversal": {"misleads"},
        "broken_scope": {"blocks", "misleads"},
        "systemic_nonuse": {"blocks"},
        "materially_misleading": {"misleads"},
        "blocked_retrieval": {"blocks"},
        "localized_repairable_friction": {"slows"},
        "no_retrieval_consequence": {"none"},
    }
    require(consequence in consequence_by_basis[basis], "invalid_scoring_context", f"{label}.retrieval_consequence is incompatible with severity_basis.")
    if severity == "critical":
        require(record["defect_kind"] in CRITICAL_BASIS_KINDS[basis], "invalid_scoring_context", f"{label}.defect_kind is incompatible with its critical severity_basis.")
        require(record["dimension_owner"] in CRITICAL_BASIS_OWNERS[basis], "invalid_scoring_context", f"{label}.dimension_owner is incompatible with its critical severity_basis.")
        if basis == "fabrication":
            require(record["code"] in {"SCP", "LOC_POS"}, "invalid_scoring_context", f"{label}.fabrication requires an SCP or LOC_POS reliability defect.")
        elif basis == "central_reversal":
            require(record["code"] in CONCEPT_CODES, "invalid_scoring_context", f"{label}.central_reversal requires a CON, STA, or CMP conceptual defect.")
        elif basis == "broken_scope":
            require(record["code"] in {"COV", "SCP", "LOC_POS", "HED", "SUB", "XRF", "CMP"}, "invalid_scoring_context", f"{label}.broken_scope has an incompatible defect code.")
        else:
            exact_item_rate = rate(record["affected_count"], record["applicable_count"])
            exact_source_section_rate = rate(len(record["affected_source_sections"]), record["source_section_denominator"])
            exact_structural_section_rate = rate(len(record["affected_structural_sections"]), record["structural_section_denominator"])
            systemic = record["affected_count"] >= 3 and (
                exact_item_rate >= Decimal("0.10")
                or exact_source_section_rate >= Decimal("0.50")
                or exact_structural_section_rate >= Decimal("0.50")
            )
            require(systemic, "invalid_scoring_context", f"{label}.systemic_nonuse requires at least three affected items and a 10% item rate or 50% source/structural-section rate.")
    return record["affected_item_ids"]


def defect_item_family(item_id: str) -> str:
    if item_id == "GLOBAL-STRUCTURE":
        return "global_structure"
    for prefix, family in DEFECT_ITEM_FAMILIES.items():
        if item_id.startswith(prefix):
            return family
    raise CalculationError("scoring_context_ledger_mismatch", f"Defect affected item ID has no reconstructable denominator family: {item_id}")


def validate_scoring_context(context: Any) -> None:
    required = {"candidate_attempt", "cross_reference_applicability", "optional_subject_scoring", "node_component_applicability", "defects"}
    require(isinstance(context, dict) and set(context) == required, "invalid_scoring_context", "scoring_context has missing or unexpected fields.")
    attempt = context["candidate_attempt"]
    require(isinstance(attempt, dict) and set(attempt) == {"status", "evidence_ids"}, "invalid_scoring_context", "candidate_attempt has missing or unexpected fields.")
    require(attempt["status"] in VALID_ATTEMPT_STATUSES, "invalid_scoring_context", "candidate_attempt.status is invalid.")
    require(isinstance(attempt["evidence_ids"], list) and all(isinstance(item, str) for item in attempt["evidence_ids"]), "invalid_scoring_context", "candidate_attempt.evidence_ids must be an array of strings.")
    require(len(attempt["evidence_ids"]) == len(set(attempt["evidence_ids"])), "invalid_scoring_context", "candidate_attempt.evidence_ids must be unique.")
    if attempt["status"] != "meaningful_attempt":
        require(bool(attempt["evidence_ids"]), "invalid_scoring_context", "A non-attempt classification requires frozen evidence IDs.")
    reference = context["cross_reference_applicability"]
    reference_required = {"status", "basis_code", "delivered_reference_count", "warranted_reference_obligation_count", "warranted_reference_obligation_ids", "reference_defect_ids"}
    require(isinstance(reference, dict) and set(reference) == reference_required, "invalid_scoring_context", "cross_reference_applicability has missing or unexpected fields.")
    require(reference["status"] in {"applicable", "inapplicable"}, "invalid_scoring_context", "cross_reference_applicability.status is invalid.")
    for field in ("delivered_reference_count", "warranted_reference_obligation_count"):
        require(isinstance(reference[field], int) and not isinstance(reference[field], bool) and reference[field] >= 0, "invalid_scoring_context", f"cross_reference_applicability.{field} must be a nonnegative integer.")
    for field in ("warranted_reference_obligation_ids", "reference_defect_ids"):
        require(isinstance(reference[field], list) and all(isinstance(item, str) and item for item in reference[field]) and len(reference[field]) == len(set(reference[field])), "invalid_scoring_context", f"{field} must contain unique non-empty strings.")
    require(reference["warranted_reference_obligation_count"] == len(reference["warranted_reference_obligation_ids"]), "invalid_scoring_context", "warranted_reference_obligation_count must equal its ID count.")
    if reference["status"] == "inapplicable":
        require(reference["basis_code"] == "no_delivered_references_no_obligation_or_defect", "invalid_scoring_context", "Cross-reference inapplicability requires the frozen no-reference/no-obligation/no-defect basis.")
        require(reference["delivered_reference_count"] == 0 and reference["warranted_reference_obligation_count"] == 0 and not reference["warranted_reference_obligation_ids"] and not reference["reference_defect_ids"], "invalid_scoring_context", "An inapplicable cross-reference component cannot have delivered references, obligations, or defects.")
    else:
        require(reference["delivered_reference_count"] > 0 or reference["warranted_reference_obligation_count"] > 0 or bool(reference["reference_defect_ids"]), "invalid_scoring_context", "An applicable cross-reference component requires delivered references, a warranted obligation, or a defect.")
        basis_requirements = {
            "delivered_references": reference["delivered_reference_count"] > 0,
            "warranted_reference_obligation": reference["warranted_reference_obligation_count"] > 0,
            "reference_defect": bool(reference["reference_defect_ids"]),
        }
        require(reference["basis_code"] in basis_requirements and basis_requirements[reference["basis_code"]], "invalid_scoring_context", "Applicable cross-reference basis_code must identify a present structured basis.")
    optional = context["optional_subject_scoring"]
    require(isinstance(optional, list), "invalid_scoring_context", "optional_subject_scoring must be an array.")
    optional_ids: set[str] = set()
    for index, item in enumerate(optional):
        require(isinstance(item, dict) and set(item) == {"subject_id", "scored", "benchmark_evidence_ids"}, "invalid_scoring_context", f"optional_subject_scoring[{index}] has an invalid shape.")
        require(isinstance(item["subject_id"], str) and item["subject_id"].startswith("SUBJ-") and item["subject_id"] not in optional_ids, "invalid_scoring_context", f"optional_subject_scoring[{index}].subject_id is invalid or duplicated.")
        require(isinstance(item["scored"], bool), "invalid_scoring_context", f"optional_subject_scoring[{index}].scored must be boolean.")
        require(isinstance(item["benchmark_evidence_ids"], list) and bool(item["benchmark_evidence_ids"]), "invalid_scoring_context", f"optional_subject_scoring[{index}] requires frozen benchmark evidence IDs.")
        optional_ids.add(item["subject_id"])
    applicability = context["node_component_applicability"]
    require(isinstance(applicability, list), "invalid_scoring_context", "node_component_applicability must be an array.")
    applicability_keys: set[tuple[str, str]] = set()
    for index, item in enumerate(applicability):
        label = f"node_component_applicability[{index}]"
        require(isinstance(item, dict) and set(item) == {"node_id", "component_id", "basis_code", "evidence_ids"}, "invalid_scoring_context", f"{label} has an invalid shape.")
        require(isinstance(item["node_id"], str) and item["node_id"].startswith("NODE-"), "invalid_scoring_context", f"{label}.node_id is invalid.")
        require(item["component_id"] in {"conceptual_stance_fidelity", "heading_access_architecture", "mechanics_consistency"}, "invalid_scoring_context", f"{label}.component_id is invalid.")
        require(item["basis_code"] == "benchmark_genuinely_inapplicable", "invalid_scoring_context", f"{label}.basis_code must establish genuine benchmark inapplicability.")
        require(isinstance(item["evidence_ids"], list) and bool(item["evidence_ids"]) and all(isinstance(value, str) and value for value in item["evidence_ids"]) and len(item["evidence_ids"]) == len(set(item["evidence_ids"])), "invalid_scoring_context", f"{label}.evidence_ids must contain unique frozen evidence IDs.")
        key = (item["node_id"], item["component_id"])
        require(key not in applicability_keys, "invalid_scoring_context", "node_component_applicability contains a duplicate node/component decision.", key)
        applicability_keys.add(key)
    defects = context["defects"]
    require(isinstance(defects, list), "invalid_scoring_context", "defects must be an array.")
    defect_ids: set[str] = set()
    for index, defect in enumerate(defects):
        validate_defect(defect, index)
        require(defect["defect_id"] not in defect_ids, "invalid_scoring_context", "Defect IDs must be unique.")
        defect_ids.add(defect["defect_id"])
    require(set(reference["reference_defect_ids"]).issubset(defect_ids), "invalid_scoring_context", "reference_defect_ids must resolve to structured defect records.")
    defect_by_id = {item["defect_id"]: item for item in defects}
    invalid_reference_defects = [
        defect_id
        for defect_id in reference["reference_defect_ids"]
        if defect_by_id[defect_id]["dimension_owner"] != "findability_navigation"
        or defect_by_id[defect_id]["code"] != "XRF"
    ]
    require(
        not invalid_reference_defects,
        "invalid_scoring_context",
        "reference_defect_ids may identify only findability-navigation XRF defects.",
        invalid_reference_defects,
    )
    navigation_xrf_defect_ids = {
        item["defect_id"]
        for item in defects
        if item["dimension_owner"] == "findability_navigation" and item["code"] == "XRF"
    }
    if reference["delivered_reference_count"] == 0 and reference["warranted_reference_obligation_count"] == 0:
        require(
            set(reference["reference_defect_ids"]) == navigation_xrf_defect_ids,
            "invalid_scoring_context",
            "With no delivered or warranted route, reference_defect_ids must exhaustively identify every structured findability-navigation XRF defect.",
            {
                "missing_reference_defect_ids": sorted(navigation_xrf_defect_ids - set(reference["reference_defect_ids"])),
                "unexpected_reference_defect_ids": sorted(set(reference["reference_defect_ids"]) - navigation_xrf_defect_ids),
            },
        )


def load_inputs(config_path: Path) -> dict[str, Any]:
    config = load_json(config_path, "Dimension calculation input")
    validate_config_shape(config)
    validate_schema_document(config, "dimension-calculation-input.schema.json", "Dimension calculation input")
    inputs = config["inputs"]
    locator_entries: list[tuple[dict[str, Any], dict[str, Any], Path]] = []
    missing_entries: list[tuple[dict[str, Any], dict[str, Any], Path]] = []
    artifacts: list[dict[str, Any]] = []
    input_paths: list[Path] = []
    for index, record in enumerate(inputs["locator_audits"]):
        path, document, artifact = resolve_input(config_path, record, f"locator_audit[{index}]")
        validate_schema_document(document, "locator-audit.schema.json", f"locator_audit[{index}]")
        locator_entries.append((document, artifact, path))
    for index, record in enumerate(inputs["missing_access_audits"]):
        path, document, artifact = resolve_input(config_path, record, f"missing_access_audit[{index}]")
        validate_schema_document(document, "missing-access-audit.schema.json", f"missing_access_audit[{index}]")
        missing_entries.append((document, artifact, path))
    locator_entries.sort(key=lambda item: str(item[0].get("chunk_id", "")))
    missing_entries.sort(key=lambda item: str(item[0].get("chunk_id", "")))
    for prefix, entries in (("locator_audit", locator_entries), ("missing_access_audit", missing_entries)):
        for index, (_, artifact, path) in enumerate(entries):
            artifact["role"] = f"{prefix}[{index}]"
            artifacts.append(artifact)
            input_paths.append(path)
    locator_documents = [document for document, _, _ in locator_entries]
    missing_documents = [document for document, _, _ in missing_entries]
    structure_path, structure, structure_artifact = resolve_input(config_path, inputs["structure_audit"], "structure_audit")
    structure_schema = "structure-audit-v4.schema.json" if structure.get("schema_version") == "structure-audit-v4" else "structure-audit.schema.json"
    validate_schema_document(structure, structure_schema, "structure_audit")
    artifacts.append(structure_artifact)
    input_paths.append(structure_path)
    chunk_manifest = None
    if "chunk_manifest" in inputs:
        chunk_path, chunk_manifest, chunk_artifact = resolve_input(config_path, inputs["chunk_manifest"], "chunk_manifest")
        validate_schema_document(chunk_manifest, "chunk-manifest.schema.json", "chunk_manifest")
        require(
            chunk_manifest.get("chunk_manifest_sha256") == canonical_hash(chunk_manifest, "chunk_manifest_sha256"),
            "chunk_manifest_self_hash_mismatch",
            "The canonical chunk manifest self-hash does not reconstruct.",
        )
        artifacts.append(chunk_artifact)
        input_paths.append(chunk_path)
    supplement = None
    if "migration_supplement" in inputs:
        supplement_path, supplement, supplement_artifact = resolve_input(config_path, inputs["migration_supplement"], "migration_supplement")
        validate_schema_document(supplement, "v5-migration-supplement.schema.json", "migration_supplement")
        artifacts.append(supplement_artifact)
        input_paths.append(supplement_path)
    return {
        "config": config,
        "locator_documents": locator_documents,
        "missing_documents": missing_documents,
        "structure": structure,
        "chunk_manifest": chunk_manifest,
        "supplement": supplement,
        "input_artifacts": artifacts,
        "input_paths": input_paths,
        "config_path": config_path,
    }


def flatten_unique(
    documents: Sequence[dict[str, Any]],
    collection: str,
    id_field: str,
    expected_field: str,
) -> tuple[list[dict[str, Any]], int, list[str], list[str]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    expected_seen: set[str] = set()
    not_measured: list[str] = []
    not_measured_source_units: list[str] = []
    for document in documents:
        chunk_id = document.get("chunk_id")
        records = document.get(collection, [])
        expected = document.get(expected_field, [])
        require(isinstance(records, list) and isinstance(expected, list), "invalid_ledger", f"{collection} and {expected_field} must be arrays.")
        require(
            all(isinstance(item, str) and item for item in expected) and len(expected) == len(set(expected)),
            "duplicate_or_invalid_expected_id",
            f"{expected_field} must contain unique non-empty strings within each source unit.",
        )
        overlap = expected_seen & set(expected)
        require(not overlap, "duplicate_expected_id_across_source_units", f"{expected_field} repeats IDs across source units.", sorted(overlap))
        expected_seen.update(expected)
        actual_ids: set[str] = set()
        for record in records:
            require(isinstance(record, dict), "invalid_ledger", f"Every {collection} record must be an object.")
            item_id = record.get(id_field)
            require(isinstance(item_id, str) and item_id and item_id not in seen, "duplicate_or_invalid_id", f"{collection} contains an invalid or duplicate {id_field}: {item_id}")
            seen.add(item_id)
            actual_ids.add(item_id)
            result.append({**record, "_source_unit_id": chunk_id})
        missing_here = sorted(set(expected) - actual_ids)
        not_measured.extend(missing_here)
        not_measured_source_units.extend([chunk_id] * len(missing_here))
        unexpected = actual_ids - set(expected)
        require(not unexpected, "unexpected_ledger_items", f"{collection} contains items outside its expected denominator.", sorted(unexpected))
    return result, len(expected_seen), not_measured, not_measured_source_units


def reconstruct_locator_count_evidence(documents: Sequence[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], set[str], int]:
    """Rebuild every locator-derived count that the structure audit also reports."""
    chapters: dict[str, dict[str, Any]] = {}
    global_path_ids: set[str] = set()
    total_not_measured = 0
    for document in documents:
        chunk_id = document["chunk_id"]
        expected_ids = set(document.get("expected_locator_ids", []))
        judgments = document.get("judgments", [])
        actual_ids = {item.get("locator_id") for item in judgments}
        path_ids = {item.get("path_id") for item in judgments}
        require(
            None not in path_ids and all(isinstance(item, str) and item.startswith("PATH-") for item in path_ids),
            "invalid_ledger",
            f"Locator audit {chunk_id} contains a judgment without a stable PATH-* identity.",
        )
        missing_count = len(expected_ids - actual_ids)
        total_not_measured += missing_count
        global_path_ids.update(path_ids)
        chapters[chunk_id] = {
            "chunk_id": chunk_id,
            "locator_occurrences": len(expected_ids),
            "known_locator_bearing_heading_paths": len(path_ids),
            "not_measured_locator_count": missing_count,
            "locator_bearing_heading_paths_min": len(path_ids),
            "locator_bearing_heading_paths_max": len(path_ids) + missing_count,
        }
    return chapters, global_path_ids, total_not_measured


AUDIT_IDENTITY_FIELDS = (
    "source_sha256",
    "benchmark_lock_sha256",
    "policy_sha256",
    "page_map_sha256",
    "chunk_manifest_sha256",
    "normalized_candidate_file_sha256",
    "item_inventory_file_sha256",
)

CALCULATION_EVIDENCE_IDENTITY_FIELDS = (
    "candidate_sha256",
    "source_sha256",
    "benchmark_sha256",
    "benchmark_lock_sha256",
    "policy_sha256",
    "page_map_sha256",
    "chunk_manifest_sha256",
    "normalized_candidate_file_sha256",
    "item_inventory_file_sha256",
    "structure_audit_file_sha256",
    "locator_audit_set_sha256",
    "missing_access_audit_set_sha256",
)


def canonical_audit_set_hash(documents: Sequence[dict[str, Any]], paths: Sequence[Path], artifact_hashes: Sequence[str], collections: Sequence[tuple[str, str, str]]) -> str:
    records: list[dict[str, Any]] = []
    for document, path, file_hash in zip(documents, paths, artifact_hashes, strict=True):
        require(sha256_file(path) == file_hash, "input_hash_mismatch", "An audit file changed while its canonical set identity was being constructed.", {"path": str(path)})
        record: dict[str, Any] = {
            "chunk_id": document["chunk_id"],
            "file_sha256": file_hash,
            "byte_length": path.stat().st_size,
        }
        for collection, id_field, output_key in collections:
            record[output_key] = sorted(item[id_field] for item in document.get(collection, []))
        records.append(record)
    records.sort(key=lambda item: item["chunk_id"])
    encoded = json.dumps(records, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_ledger_set_integrity(loaded: dict[str, Any], *, require_chunk_manifest: bool = True) -> dict[str, Any]:
    """Bind the complete audit set and reject cross-snapshot ledger mixtures."""
    config = loaded["config"]
    evaluation_id = config["evaluation_id"]
    loc_docs = loaded["locator_documents"]
    missing_docs = loaded["missing_documents"]
    structure = loaded["structure"]
    chunk_manifest = loaded.get("chunk_manifest")
    supplement = loaded.get("supplement")
    all_audits = [*loc_docs, *missing_docs]

    frozen_audit_mode = structure.get("audit_mode")
    if frozen_audit_mode is None and isinstance(supplement, dict):
        frozen_audit_mode = supplement.get("audit_mode")
    require(frozen_audit_mode in {"full", "pilot"}, "required_v5_ledger_field_missing", "A frozen structure audit or migration supplement must bind audit_mode.")
    require(frozen_audit_mode == config["audit_mode"], "audit_mode_identity_mismatch", "Calculation audit_mode differs from the frozen audit provenance.", {"calculation": config["audit_mode"], "frozen": frozen_audit_mode})
    if structure.get("audit_mode") is not None and isinstance(supplement, dict):
        require(supplement.get("audit_mode") == structure.get("audit_mode"), "audit_mode_identity_mismatch", "Migration supplement audit_mode differs from the historical structure audit.")

    for label, documents in (("locator", loc_docs), ("missing-access", missing_docs)):
        chunk_ids = [document.get("chunk_id") for document in documents]
        require(all(isinstance(item, str) and item.startswith("CHUNK-") for item in chunk_ids), "invalid_chunk_set", f"Every {label} audit requires a CHUNK-* chunk_id.")
        require(len(chunk_ids) == len(set(chunk_ids)), "duplicate_chunk_id", f"The {label} audit set contains duplicate chunk IDs.", chunk_ids)
        for document in documents:
            require(document.get("evaluation_id") == evaluation_id, "evaluation_identity_mismatch", f"A {label} audit has a different evaluation_id.")
            require(isinstance(document.get("provenance"), dict), "required_v5_ledger_field_missing", f"{label} audit {document.get('chunk_id')} requires provenance for V5 identity binding.")
            missing_fields = [field for field in AUDIT_IDENTITY_FIELDS if field not in document["provenance"]]
            require(not missing_fields, "required_v5_ledger_field_missing", f"{label} audit {document.get('chunk_id')} lacks V5 identity fields.", missing_fields)

    locator_chunks = {document["chunk_id"] for document in loc_docs}
    missing_chunks = {document["chunk_id"] for document in missing_docs}
    density_chapters = structure.get("density", {}).get("chapter_measurements", []) if isinstance(structure.get("density"), dict) else []
    density_chunks = [chapter.get("chunk_id") for chapter in density_chapters if isinstance(chapter, dict)]
    require(density_chunks and all(isinstance(item, str) and item.startswith("CHUNK-") for item in density_chunks), "invalid_chunk_set", "Structure density measurements must identify every approved CHUNK-* source unit.")
    require(len(density_chunks) == len(set(density_chunks)), "duplicate_chunk_id", "Structure density measurements contain duplicate chunk IDs.", density_chunks)
    if chunk_manifest is None:
        require(not require_chunk_manifest, "canonical_chunk_manifest_required", "The canonical user-approved chunk manifest is required to prove complete source-unit coverage.")
        approved_chunks = set(density_chunks)
    else:
        require(chunk_manifest.get("user_approved") is True, "invalid_chunk_manifest", "The canonical chunk manifest must record user approval.")
        require(chunk_manifest.get("require_full_scope_coverage") is True, "invalid_chunk_manifest", "The canonical chunk manifest must require full in-scope coverage.")
        validation = chunk_manifest.get("validation")
        require(
            isinstance(validation, dict)
            and validation.get("owned_pages_unique") is True
            and validation.get("scope_coverage_complete") is True,
            "invalid_chunk_manifest",
            "The canonical chunk manifest must prove unique ownership and complete scope coverage.",
        )
        manifest_chunks = [item.get("chunk_id") for item in chunk_manifest.get("chunks", []) if isinstance(item, dict)]
        require(
            manifest_chunks
            and all(isinstance(item, str) and item.startswith("CHUNK-") for item in manifest_chunks)
            and len(manifest_chunks) == len(set(manifest_chunks)),
            "invalid_chunk_set",
            "The canonical chunk manifest must contain unique CHUNK-* identifiers.",
            manifest_chunks,
        )
        approved_chunks = set(manifest_chunks)
    require(locator_chunks == missing_chunks == set(density_chunks) == approved_chunks, "incomplete_or_mixed_chunk_set", "Locator audits, missing-access audits, structure density, and the canonical manifest must cover the same complete approved chunk set.", {
        "locator_only": sorted(locator_chunks - missing_chunks - approved_chunks),
        "missing_access_only": sorted(missing_chunks - locator_chunks - approved_chunks),
        "structure_only": sorted(approved_chunks - locator_chunks - missing_chunks),
        "locator_chunks": sorted(locator_chunks),
        "missing_access_chunks": sorted(missing_chunks),
        "structure_chunks": sorted(density_chunks),
        "manifest_chunks": sorted(approved_chunks) if chunk_manifest is not None else None,
    })

    candidate_hashes = {document.get("candidate_sha256") for document in all_audits} | {structure.get("candidate_sha256")}
    require(len(candidate_hashes) == 1 and None not in candidate_hashes, "candidate_identity_mismatch", "All audit ledgers must bind the same candidate SHA-256.", sorted(str(item) for item in candidate_hashes))

    identity: dict[str, Any] = {"candidate_sha256": next(iter(candidate_hashes)), "audit_mode": frozen_audit_mode, "approved_chunk_ids": sorted(approved_chunks)}
    for field in AUDIT_IDENTITY_FIELDS:
        values = {document["provenance"].get(field) for document in all_audits}
        require(len(values) == 1 and None not in values, "audit_provenance_mismatch", f"Audit ledgers bind different {field} values.", sorted(str(item) for item in values))
        identity[field] = next(iter(values))

    if chunk_manifest is not None:
        require(chunk_manifest.get("page_map_sha256") == identity["page_map_sha256"], "chunk_manifest_identity_mismatch", "Chunk-manifest page-map identity differs from the audit ledgers.")
        require(chunk_manifest.get("chunk_manifest_sha256") == identity["chunk_manifest_sha256"], "chunk_manifest_identity_mismatch", "Audit ledgers do not bind the supplied canonical chunk manifest.")

    benchmark_values = {document["provenance"]["benchmark_sha256"] for document in loc_docs}
    benchmark_values.update(document.get("benchmark_sha256") for document in missing_docs)
    require(len(benchmark_values) == 1 and None not in benchmark_values, "benchmark_identity_mismatch", "Locator and missing-access audits bind different benchmark SHA-256 values.", sorted(str(item) for item in benchmark_values))
    identity["benchmark_sha256"] = next(iter(benchmark_values))

    structure_provenance = structure.get("provenance")
    require(isinstance(structure_provenance, dict), "required_v5_ledger_field_missing", "Structure audit requires provenance for V5 identity binding.")
    for field in ("benchmark_sha256", "normalized_candidate_file_sha256", "item_inventory_file_sha256"):
        require(structure_provenance.get(field) == identity[field], "structure_identity_mismatch", f"Structure audit {field} differs from the chunk audit set.", {"structure": structure_provenance.get(field), "audit_set": identity[field]})
    require(structure.get("item_inventory_sha256") == identity["item_inventory_file_sha256"], "structure_identity_mismatch", "Structure audit item-inventory SHA-256 differs from the chunk audit set.")
    if structure.get("schema_version") == "structure-audit-v4":
        for field in AUDIT_IDENTITY_FIELDS:
            require(structure_provenance.get(field) == identity[field], "structure_identity_mismatch", f"Structure audit {field} differs from the chunk audit set.", {"structure": structure_provenance.get(field), "audit_set": identity[field]})

    locator_count = len(loc_docs)
    missing_count = len(missing_docs)
    locator_paths = loaded["input_paths"][:locator_count]
    missing_paths = loaded["input_paths"][locator_count:locator_count + missing_count]
    locator_hashes = [item["sha256"] for item in loaded["input_artifacts"][:locator_count]]
    missing_hashes = [item["sha256"] for item in loaded["input_artifacts"][locator_count:locator_count + missing_count]]
    locator_set_sha256 = canonical_audit_set_hash(loc_docs, locator_paths, locator_hashes, (("judgments", "locator_id", "locator_ids"),))
    missing_set_sha256 = canonical_audit_set_hash(
        missing_docs,
        missing_paths,
        missing_hashes,
        (("subject_judgments", "subject_id", "subject_ids"), ("reader_task_results", "task_id", "reader_task_ids"), ("treatment_judgments", "treatment_id", "treatment_ids")),
    )
    if structure.get("schema_version") == "structure-audit-v4":
        for document in missing_docs:
            require(document["provenance"].get("locator_audit_set_sha256") == locator_set_sha256, "locator_audit_set_identity_mismatch", f"Missing-access audit {document['chunk_id']} does not bind the exact supplied locator-audit set.", {"expected": locator_set_sha256, "actual": document["provenance"].get("locator_audit_set_sha256")})
        require(structure_provenance.get("locator_audit_set_sha256") == locator_set_sha256, "locator_audit_set_identity_mismatch", "Structure audit does not bind the exact supplied locator-audit set.", {"expected": locator_set_sha256, "actual": structure_provenance.get("locator_audit_set_sha256")})
        require(structure_provenance.get("missing_access_audit_set_sha256") == missing_set_sha256, "missing_access_audit_set_identity_mismatch", "Structure audit does not bind the exact supplied missing-access audit set.", {"expected": missing_set_sha256, "actual": structure_provenance.get("missing_access_audit_set_sha256")})
    else:
        # Historical V3 audits can carry an audit-set identity produced by an
        # earlier canonicalization scheme. Those frozen values are provenance,
        # not bytes that V5 may rewrite. A reviewed supplement must bind both
        # schemes over the exact same frozen input files.
        for document in missing_docs:
            require(document["provenance"].get("locator_audit_set_sha256") == locator_set_sha256, "locator_audit_set_identity_mismatch", f"Missing-access audit {document['chunk_id']} does not bind the exact supplied locator-audit set.", {"expected": locator_set_sha256, "actual": document["provenance"].get("locator_audit_set_sha256")})
        # The historical V3 structure/result checkpoint used a different
        # aggregate identity scheme even though the later missing-access files
        # already bind the canonical locator set. Keep that frozen structure
        # identity separate and reconcile it explicitly in the supplement.
        historical_locator_sha256 = structure_provenance.get("locator_audit_set_sha256")
        historical_missing_sha256 = structure_provenance.get("missing_access_audit_set_sha256")
        if isinstance(supplement, dict):
            require(supplement.get("locator_audit_set_sha256") == locator_set_sha256, "migration_supplement_binding_mismatch", "Migration supplement does not bind the V5-canonical supplied locator-audit set.", {"expected": locator_set_sha256, "actual": supplement.get("locator_audit_set_sha256")})
            require(supplement.get("missing_access_audit_set_sha256") == missing_set_sha256, "migration_supplement_binding_mismatch", "Migration supplement does not bind the V5-canonical supplied missing-access audit set.", {"expected": missing_set_sha256, "actual": supplement.get("missing_access_audit_set_sha256")})
            if historical_locator_sha256 is not None:
                require(supplement.get("historical_locator_audit_set_sha256") == historical_locator_sha256, "migration_supplement_binding_mismatch", "Migration supplement does not preserve the locator-audit-set identity recorded by the historical ledgers.", {"expected": historical_locator_sha256, "actual": supplement.get("historical_locator_audit_set_sha256")})
            if historical_missing_sha256 is not None:
                require(supplement.get("historical_missing_access_audit_set_sha256") == historical_missing_sha256, "migration_supplement_binding_mismatch", "Migration supplement does not preserve the missing-access-audit-set identity recorded by the historical structure audit.", {"expected": historical_missing_sha256, "actual": supplement.get("historical_missing_access_audit_set_sha256")})
            historical_locator_sha256 = supplement["historical_locator_audit_set_sha256"]
            historical_missing_sha256 = supplement["historical_missing_access_audit_set_sha256"]
            require(
                supplement.get("audit_set_reconciliation_basis") == "same_frozen_files_rehashed_with_subject_index_canonical_audit_set_v1",
                "migration_supplement_binding_mismatch",
                "Migration supplement lacks the required historical-to-canonical audit-set reconciliation basis.",
            )
        identity["historical_locator_audit_set_sha256"] = historical_locator_sha256
        identity["historical_missing_access_audit_set_sha256"] = historical_missing_sha256
    identity["locator_audit_set_sha256"] = locator_set_sha256
    identity["missing_access_audit_set_sha256"] = missing_set_sha256
    structure_artifact = next(item for item in loaded["input_artifacts"] if item["role"] == "structure_audit")
    identity["structure_audit_file_sha256"] = structure_artifact["sha256"]
    return identity


def collect_ledgers(loaded: dict[str, Any]) -> dict[str, Any]:
    config = loaded["config"]
    evaluation_id = config["evaluation_id"]
    loc_docs = loaded["locator_documents"]
    missing_docs = loaded["missing_documents"]
    structure = loaded["structure"]
    identity = validate_ledger_set_integrity(loaded)
    for label, documents, versions in (
        ("locator audit", loc_docs, {"locator-audit-v1"}),
        ("missing-access audit", missing_docs, {"missing-access-audit-v1"}),
    ):
        for document in documents:
            require(document.get("schema_version") in versions, "unsupported_ledger_version", f"Unsupported {label} schema version: {document.get('schema_version')}")
            require(document.get("evaluation_id") == evaluation_id, "evaluation_identity_mismatch", f"A {label} has a different evaluation_id.")
    for document in loc_docs:
        completion = document["completion"]
        expected = document["expected_locator_ids"]
        judgments = document["judgments"]
        exact = len(expected) == len(judgments) and len({item.get("locator_id") for item in judgments}) == len(judgments)
        require(
            completion.get("expected") == len(expected)
            and completion.get("judged") == len(judgments)
            and completion.get("unique") is True
            and completion.get("complete") is exact,
            "ledger_completion_mismatch",
            f"Locator-audit completion fields do not reconstruct for {document.get('chunk_id')}.",
        )
    for document in missing_docs:
        completion = document["completion"]
        expected = document["expected_subject_ids"]
        judgments = document["subject_judgments"]
        exact = len(expected) == len(judgments) and len({item.get("subject_id") for item in judgments}) == len(judgments)
        require(
            completion.get("expected") == len(expected)
            and completion.get("judged") == len(judgments)
            and completion.get("complete") is exact,
            "ledger_completion_mismatch",
            f"Missing-access completion fields do not reconstruct for {document.get('chunk_id')}.",
        )
        for expected_field, collection, id_field, completion_field in (
            ("expected_reader_task_ids", "reader_task_results", "task_id", "reader_task_completion"),
            ("expected_treatment_ids", "treatment_judgments", "treatment_id", "treatment_completion"),
        ):
            require(expected_field in document and collection in document and completion_field in document, "required_v5_ledger_field_missing", f"Missing-access audit {document.get('chunk_id')} lacks V5-required {expected_field}, {collection}, or {completion_field}.")
            expected_items = document[expected_field]
            actual_items = document[collection]
            exact_completion = document[completion_field]
            exact_ids = [item.get(id_field) for item in actual_items]
            exact_complete = len(expected_items) == len(actual_items) and len(exact_ids) == len(set(exact_ids))
            require(
                exact_completion.get("expected") == len(expected_items)
                and exact_completion.get("judged") == len(actual_items)
                and exact_completion.get("unique") is True
                and exact_completion.get("complete") is exact_complete,
                "ledger_completion_mismatch",
                f"{completion_field} does not reconstruct for {document.get('chunk_id')}.",
            )
    require(structure.get("schema_version") in {"structure-audit-v3", "structure-audit-v4"}, "unsupported_ledger_version", "Structure audit must use v3 or v4.")
    require(structure.get("evaluation_id") == evaluation_id, "evaluation_identity_mismatch", "Structure audit has a different evaluation_id.")

    locators, locator_original, locator_not_measured, locator_not_measured_units = flatten_unique(loc_docs, "judgments", "locator_id", "expected_locator_ids")
    subjects, subject_original, subject_not_measured, _ = flatten_unique(missing_docs, "subject_judgments", "subject_id", "expected_subject_ids")
    tasks, task_original, task_not_measured, _ = flatten_unique(missing_docs, "reader_task_results", "task_id", "expected_reader_task_ids")
    treatments, treatment_original, treatment_not_measured, _ = flatten_unique(missing_docs, "treatment_judgments", "treatment_id", "expected_treatment_ids")
    # Referential integrity uses the complete frozen expected-subject universe.
    # In pilot mode a valid expected subject may have no judgment yet; the
    # judged-only `subjects` collection must remain incomplete so the scoring
    # functions can carry that record through their adverse/favorable bounds.
    expected_subject_ids = {
        subject_id
        for document in missing_docs
        for subject_id in document["expected_subject_ids"]
    }
    for task in tasks:
        required_subject_ids = task.get("subject_ids")
        require(isinstance(required_subject_ids, list) and bool(required_subject_ids) and all(isinstance(item, str) for item in required_subject_ids), "invalid_ledger", f"Reader task {task.get('task_id')} must identify at least one required subject.")
        require(set(required_subject_ids).issubset(expected_subject_ids), "invalid_ledger", f"Reader task {task.get('task_id')} cites an unknown subject.", sorted(set(required_subject_ids) - expected_subject_ids))
    treatment_units: set[tuple[str, int, str]] = set()
    for treatment in treatments:
        require(treatment.get("subject_id") in expected_subject_ids, "invalid_ledger", f"Treatment {treatment.get('treatment_id')} cites an unknown subject.")
        require(treatment.get("locator_class") in {"principal", "supporting", "synthesis_or_conclusion"}, "invalid_ledger", f"Treatment {treatment.get('treatment_id')} lacks a valid locator class.")
        require(isinstance(treatment.get("document_page"), int) and not isinstance(treatment.get("document_page"), bool) and treatment["document_page"] > 0, "invalid_ledger", f"Treatment {treatment.get('treatment_id')} lacks a positive document page.")
        unit = (treatment["subject_id"], treatment["document_page"], treatment["locator_class"])
        require(unit not in treatment_units, "duplicate_treatment_unit", "Expected-treatment recall requires unique (subject_id, document_page, locator_class) units.", {"subject_id": unit[0], "document_page": unit[1], "locator_class": unit[2]})
        treatment_units.add(unit)

    nodes = structure.get("node_judgments", [])
    expected_nodes = structure.get("expected_node_ids", [])
    references = structure.get("cross_reference_judgments", [])
    expected_references = structure.get("expected_cross_reference_ids", [])
    require(isinstance(nodes, list) and isinstance(expected_nodes, list), "invalid_ledger", "Structure nodes and expected IDs must be arrays.")
    require(isinstance(references, list) and isinstance(expected_references, list), "invalid_ledger", "Cross references and expected IDs must be arrays.")
    node_ids = [item.get("node_id") for item in nodes]
    reference_ids = [item.get("reference_id") for item in references]
    require(all(isinstance(item, str) for item in node_ids) and len(node_ids) == len(set(node_ids)), "duplicate_or_invalid_id", "Structure node IDs must be unique strings.")
    require(all(isinstance(item, str) for item in reference_ids) and len(reference_ids) == len(set(reference_ids)), "duplicate_or_invalid_id", "Cross-reference IDs must be unique strings.")
    require(set(node_ids).issubset(set(expected_nodes)), "unexpected_ledger_items", "Structure audit contains unexpected node IDs.")
    require(set(reference_ids).issubset(set(expected_references)), "unexpected_ledger_items", "Structure audit contains unexpected cross-reference IDs.")
    node_not_measured = sorted(set(expected_nodes) - set(node_ids))
    reference_not_measured = sorted(set(expected_references) - set(reference_ids))
    structure_completion = structure.get("completion", {})
    structure_exact = not node_not_measured and not reference_not_measured
    require(
        structure_completion.get("expected_nodes") == len(expected_nodes)
        and structure_completion.get("judged_nodes") == len(nodes)
        and structure_completion.get("expected_cross_references") == len(expected_references)
        and structure_completion.get("judged_cross_references") == len(references)
        and structure_completion.get("complete") is structure_exact,
        "ledger_completion_mismatch",
        "Structure-audit completion fields do not reconstruct from expected and judged IDs.",
    )

    locator_count_evidence, known_global_path_ids, not_measured_locator_count = reconstruct_locator_count_evidence(loc_docs)
    metrics = structure.get("metrics")
    require(isinstance(metrics, dict), "invalid_ledger", "Structure audit metrics must be an object.")
    for field in ("page_bearing_paths", "expanded_locators", "cross_references"):
        require(
            isinstance(metrics.get(field), int) and not isinstance(metrics.get(field), bool) and metrics[field] >= 0,
            "invalid_ledger",
            f"Structure metric {field} must be a nonnegative integer.",
        )
    require(
        metrics["expanded_locators"] == locator_original,
        "recomputable_aggregate_mismatch",
        "Structure expanded_locators does not equal the exact stable locator-ID denominator.",
        {"field": "metrics.expanded_locators", "expected": locator_original, "actual": metrics["expanded_locators"]},
    )
    require(
        metrics["cross_references"] == len(expected_references),
        "recomputable_aggregate_mismatch",
        "Structure cross_references does not equal the exact stable cross-reference-ID denominator.",
        {"field": "metrics.cross_references", "expected": len(expected_references), "actual": metrics["cross_references"]},
    )
    global_path_minimum = len(known_global_path_ids)
    global_path_maximum = global_path_minimum + not_measured_locator_count
    require(
        global_path_minimum <= metrics["page_bearing_paths"] <= global_path_maximum,
        "recomputable_aggregate_mismatch",
        "Structure page_bearing_paths is outside the range reconstructable from stable locator judgments.",
        {
            "field": "metrics.page_bearing_paths",
            "minimum": global_path_minimum,
            "maximum": global_path_maximum,
            "actual": metrics["page_bearing_paths"],
            "not_measured_locator_count": not_measured_locator_count,
        },
    )
    if not_measured_locator_count == 0:
        require(
            metrics["page_bearing_paths"] == global_path_minimum,
            "recomputable_aggregate_mismatch",
            "Structure page_bearing_paths does not equal the unique stable PATH-* identities in the complete locator ledger.",
            {"field": "metrics.page_bearing_paths", "expected": global_path_minimum, "actual": metrics["page_bearing_paths"]},
        )

    density_chapters = structure.get("density", {}).get("chapter_measurements", [])
    density_by_chunk = {item.get("chunk_id"): item for item in density_chapters if isinstance(item, dict)}
    density_count_reconstruction: dict[str, dict[str, Any]] = {}
    for chunk_id, evidence in locator_count_evidence.items():
        chapter = density_by_chunk[chunk_id]
        declared_paths = chapter.get("locator_bearing_heading_paths")
        declared_occurrences = chapter.get("locator_occurrences")
        require(
            isinstance(declared_paths, int) and not isinstance(declared_paths, bool) and declared_paths >= 0
            and isinstance(declared_occurrences, int) and not isinstance(declared_occurrences, bool) and declared_occurrences >= 0,
            "density_inputs_missing",
            f"Density chapter {chunk_id} lacks valid raw path and occurrence counts.",
        )
        require(
            declared_occurrences == evidence["locator_occurrences"],
            "recomputable_aggregate_mismatch",
            f"Density locator_occurrences for {chunk_id} does not equal its exact stable locator-ID denominator.",
            {"chunk_id": chunk_id, "field": "locator_occurrences", "expected": evidence["locator_occurrences"], "actual": declared_occurrences},
        )
        require(
            evidence["locator_bearing_heading_paths_min"] <= declared_paths <= evidence["locator_bearing_heading_paths_max"],
            "recomputable_aggregate_mismatch",
            f"Density locator_bearing_heading_paths for {chunk_id} is outside the range reconstructable from stable locator judgments.",
            {
                "chunk_id": chunk_id,
                "field": "locator_bearing_heading_paths",
                "minimum": evidence["locator_bearing_heading_paths_min"],
                "maximum": evidence["locator_bearing_heading_paths_max"],
                "actual": declared_paths,
                "not_measured_locator_count": evidence["not_measured_locator_count"],
            },
        )
        if evidence["not_measured_locator_count"] == 0:
            require(
                declared_paths == evidence["known_locator_bearing_heading_paths"],
                "recomputable_aggregate_mismatch",
                f"Density locator_bearing_heading_paths for {chunk_id} does not equal its unique stable PATH-* identities.",
                {"chunk_id": chunk_id, "field": "locator_bearing_heading_paths", "expected": evidence["known_locator_bearing_heading_paths"], "actual": declared_paths},
            )
        density_count_reconstruction[chunk_id] = {
            **evidence,
            "locator_bearing_heading_paths": declared_paths,
            "path_count_basis": "recomputed_from_path_ids" if evidence["not_measured_locator_count"] == 0 else "frozen_count_within_reconstructed_missing_item_bounds",
            "occurrence_count_basis": "recomputed_from_expected_locator_ids",
        }

    supplement = loaded["supplement"]
    if structure.get("schema_version") == "structure-audit-v4":
        require(supplement is None, "unexpected_migration_supplement", "A current structure-audit-v4 calculation must not use a historical migration supplement.")
        context = structure.get("v5_scoring_context")
    else:
        require(supplement is not None, "migration_supplement_required", "Historical structure-audit-v3 requires a hash-bound V5 migration supplement.")
        require(supplement.get("schema_version") == "subject-index-v5-migration-supplement-v1", "unsupported_ledger_version", "Unsupported migration supplement version.")
        structure_hash = next(item["sha256"] for item in loaded["input_artifacts"] if item["role"] == "structure_audit")
        require(supplement.get("structure_audit_sha256") == structure_hash, "migration_supplement_binding_mismatch", "Migration supplement does not bind the supplied historical structure audit.")
        require(supplement.get("evaluation_id") == evaluation_id, "evaluation_identity_mismatch", "Migration supplement has a different evaluation_id.")
        context = supplement.get("scoring_context")
    validate_scoring_context(context)
    if structure.get("schema_version") == "structure-audit-v4":
        top_defects = structure.get("defects", [])
        context_defects = context["defects"]
        top_by_id = {item.get("defect_id"): item for item in top_defects if isinstance(item, dict)}
        context_by_id = {item["defect_id"]: item for item in context_defects}
        require(
            len(top_by_id) == len(top_defects)
            and top_by_id == context_by_id,
            "structure_defect_projection_mismatch",
            "structure-audit-v4 defects and v5_scoring_context.defects must contain exactly the same structured records, independent of order.",
            {"top_level_ids": sorted(str(item) for item in top_by_id), "scoring_context_ids": sorted(context_by_id)},
        )
    reference_context = context["cross_reference_applicability"]
    require(
        reference_context["delivered_reference_count"] == len(expected_references),
        "scoring_context_ledger_mismatch",
        "Frozen delivered-reference count does not match the structure-audit denominator.",
        {"context_count": reference_context["delivered_reference_count"], "structure_count": len(expected_references)},
    )
    completion = structure.get("completion", {}) if isinstance(structure.get("completion"), dict) else {}
    if completion.get("complete") is False or structure.get("scope_complete") is False:
        require(
            context["candidate_attempt"]["status"] in {"structurally_incomplete", "unparseable"},
            "scoring_context_ledger_mismatch",
            "An incomplete structure audit must freeze the corresponding non-attempt status.",
        )
    optional_map = {item["subject_id"]: item["scored"] for item in context["optional_subject_scoring"]}
    optional_ids = {item["subject_id"] for item in subjects if item.get("priority") == "optional"}
    require(optional_ids == set(optional_map), "optional_subject_scoring_incomplete", "Every and only optional audited subject must have a frozen scored/unscored decision.", {"missing": sorted(optional_ids - set(optional_map)), "unexpected": sorted(set(optional_map) - optional_ids)})
    actual_inapplicable_components = {
        (node["node_id"], component_id)
        for node in nodes
        for component_id, judgment in node.get("component_judgments", {}).items()
        if isinstance(judgment, dict) and judgment.get("status") == "not_applicable"
    }
    frozen_inapplicable_components = {(item["node_id"], item["component_id"]) for item in context["node_component_applicability"]}
    require(actual_inapplicable_components == frozen_inapplicable_components, "node_applicability_basis_mismatch", "Every and only not-applicable node component requires a frozen benchmark-genuine-inapplicability decision.", {
        "missing_decisions": sorted(actual_inapplicable_components - frozen_inapplicable_components),
        "unexpected_decisions": sorted(frozen_inapplicable_components - actual_inapplicable_components),
    })

    attempt_status = context["candidate_attempt"]["status"]
    if attempt_status == "empty":
        require(locator_original == 0 and len(expected_nodes) == 0 and structure.get("metrics", {}).get("expanded_locators") == 0, "scoring_context_ledger_mismatch", "candidate_attempt empty must reconstruct from zero locator and node denominators.")
    elif attempt_status in {"structurally_incomplete", "unparseable"}:
        require(structure.get("scope_complete") is False or structure_completion.get("complete") is False, "scoring_context_ledger_mismatch", "A structurally incomplete or unparseable attempt requires an incomplete structure ledger.")
    else:
        require(locator_original > 0 or len(expected_nodes) > 0, "scoring_context_ledger_mismatch", "A meaningful attempt requires locator-bearing output or a non-empty navigation structure.")

    known_item_ids = (
        {item_id for document in loc_docs for item_id in document.get("expected_locator_ids", [])}
        | {item.get("path_id") for item in locators if item.get("path_id")}
        | {item_id for document in missing_docs for item_id in document.get("expected_subject_ids", [])}
        | {item_id for document in missing_docs for item_id in document.get("expected_reader_task_ids", [])}
        | {item_id for document in missing_docs for item_id in document.get("expected_treatment_ids", [])}
        | set(expected_nodes)
        | set(expected_references)
        | {"GLOBAL-STRUCTURE"}
    )
    warranted_obligation_ids = set(reference_context["warranted_reference_obligation_ids"])
    valid_obligation_ids = {
        item_id
        for item_id in known_item_ids
        if item_id == "GLOBAL-STRUCTURE" or item_id.startswith(("SUBJ-", "TASK-", "TREAT-", "NODE-"))
    }
    unresolved_obligations = warranted_obligation_ids - valid_obligation_ids
    require(
        not unresolved_obligations,
        "scoring_context_ledger_mismatch",
        "Warranted cross-reference obligations must identify undelivered subject, task, treatment, node, or global-structure obligations; delivered XREF, locator, and path IDs are not obligations.",
        sorted(unresolved_obligations),
    )
    approved_source_sections = set(identity["approved_chunk_ids"])
    approved_structural_sections = {item["node_id"] for item in nodes if item.get("role") == "main_heading"}
    if not approved_structural_sections:
        approved_structural_sections = set(expected_nodes)
    high_priority_subjects = {item["subject_id"] for item in subjects if item.get("priority") in {"essential", "major"}}
    path_denominator = metrics["page_bearing_paths"]
    defect_family_denominators = {
        "locator": locator_original,
        "path": path_denominator,
        "subject": subject_original,
        "task": task_original,
        "treatment": treatment_original,
        "node": len(expected_nodes),
        "cross_reference": len(expected_references),
        "global_structure": 1,
    }
    for defect in context["defects"]:
        unresolved = set(defect["affected_item_ids"]) - known_item_ids
        require(not unresolved, "scoring_context_ledger_mismatch", f"Defect {defect['defect_id']} cites affected item IDs absent from the frozen ledgers.", sorted(unresolved))
        item_families = {defect_item_family(item_id) for item_id in defect["affected_item_ids"]}
        require(
            len(item_families) == 1,
            "scoring_context_ledger_mismatch",
            f"Defect {defect['defect_id']} mixes affected item families, so its one applicable denominator cannot be reconstructed.",
            {"families": sorted(item_families)},
        )
        item_family = next(iter(item_families))
        expected_applicable_count = defect_family_denominators[item_family]
        require(
            defect["applicable_count"] == expected_applicable_count,
            "scoring_context_ledger_mismatch",
            f"Defect {defect['defect_id']} applicable_count does not equal the frozen {item_family} denominator.",
            {"item_family": item_family, "expected": expected_applicable_count, "actual": defect["applicable_count"]},
        )
        invalid_source_sections = set(defect["affected_source_sections"]) - approved_source_sections
        require(not invalid_source_sections, "scoring_context_ledger_mismatch", f"Defect {defect['defect_id']} cites source sections outside the approved chunk set.", sorted(invalid_source_sections))
        invalid_structural_sections = set(defect["affected_structural_sections"]) - approved_structural_sections
        require(not invalid_structural_sections, "scoring_context_ledger_mismatch", f"Defect {defect['defect_id']} cites structural sections outside the audited main-heading set.", sorted(invalid_structural_sections))
        require(defect["source_section_denominator"] == len(approved_source_sections), "scoring_context_ledger_mismatch", f"Defect {defect['defect_id']} source-section denominator does not equal the approved chunk count.", {"recorded": defect["source_section_denominator"], "expected": len(approved_source_sections)})
        require(defect["structural_section_denominator"] == len(approved_structural_sections), "scoring_context_ledger_mismatch", f"Defect {defect['defect_id']} structural-section denominator does not equal the audited main-heading count.", {"recorded": defect["structural_section_denominator"], "expected": len(approved_structural_sections)})
        if defect["high_priority_access_destroyed"]:
            require(bool(set(defect["affected_item_ids"]) & high_priority_subjects), "scoring_context_ledger_mismatch", f"Defect {defect['defect_id']} claims destroyed high-priority access without naming an affected essential or major subject.")

    return {
        "locators": locators,
        "locator_original": locator_original,
        "locator_not_measured": locator_not_measured,
        "locator_not_measured_units": locator_not_measured_units,
        "subjects": subjects,
        "expected_subject_ids": sorted(expected_subject_ids),
        "subject_original": subject_original,
        "subject_not_measured": subject_not_measured,
        "tasks": tasks,
        "task_original": task_original,
        "task_not_measured": task_not_measured,
        "treatments": treatments,
        "treatment_original": treatment_original,
        "treatment_not_measured": treatment_not_measured,
        "nodes": nodes,
        "node_original": len(expected_nodes),
        "node_not_measured": node_not_measured,
        "references": references,
        "reference_original": len(expected_references),
        "reference_not_measured": reference_not_measured,
        "structure": structure,
        "context": context,
        "defects": context["defects"],
        "optional_map": optional_map,
        "identity": identity,
        "source_units": sorted({item.get("chunk_id") for item in loc_docs if item.get("chunk_id")}),
        "density_count_reconstruction": density_count_reconstruction,
    }


def component_denominators(
    component_id: str,
    original: int,
    applicable: int,
    measured: int,
    uninspectable: int = 0,
    not_measured: int = 0,
    exclusions: dict[str, int] | None = None,
    inapplicable: bool = False,
    zero_due_to_non_attempt: bool = False,
    defined_zero_rule: str | None = None,
) -> dict[str, Any]:
    exclusions = {key: value for key, value in (exclusions or {}).items() if value}
    excluded = original - applicable
    require(excluded >= 0 and measured + uninspectable + not_measured == applicable, "denominator_reconstruction_failed", f"{component_id} denominators do not reconstruct.")
    require(sum(exclusions.values()) == excluded, "denominator_reconstruction_failed", f"{component_id} exclusion reasons do not reconstruct.", {"excluded": excluded, "reasons": exclusions})
    coverage = rate(measured, applicable) if applicable else (ONE if inapplicable else ZERO)
    small_exception = applicable < 20 and uninspectable == 1 and measured >= 1 and not_measured == 0
    if zero_due_to_non_attempt and defined_zero_rule is None:
        defined_zero_rule = "candidate_not_meaningfully_attempted"
    provisional = inapplicable or defined_zero_rule is not None or (applicable > 0 and (coverage >= Decimal("0.95") or small_exception))
    return {
        "component_id": component_id,
        "original": original,
        "applicable": applicable,
        "measured": measured,
        "excluded": excluded,
        "uninspectable": uninspectable,
        "not_measured": not_measured,
        "exclusion_reasons": exclusions,
        "measurement_coverage": decimal_text(coverage),
        "small_denominator_exception": small_exception,
        "genuinely_inapplicable": inapplicable,
        "zero_due_to_non_attempt": zero_due_to_non_attempt,
        "defined_zero_rule": defined_zero_rule,
        "provisionally_scoreable": provisional,
    }


def mark_defined_zero(denominator: dict[str, Any], rule: str, *, non_attempt: bool = False) -> None:
    denominator["defined_zero_rule"] = rule
    denominator["zero_due_to_non_attempt"] = non_attempt
    denominator["provisionally_scoreable"] = True


def cap_record(
    cap_id: str,
    maximum: Decimal,
    triggered: bool,
    threshold: dict[str, Any],
    observed: dict[str, Any],
    evidence_ids: Iterable[str] = (),
) -> dict[str, Any]:
    return {
        "cap_id": cap_id,
        "maximum_rating": displayed_number(maximum),
        "triggered": bool(triggered),
        "threshold": threshold,
        "observed": observed,
        "affected_evidence_ids": sorted({item for item in evidence_ids if isinstance(item, str) and item}),
    }


def choose_cap(evaluations: list[dict[str, Any]]) -> dict[str, Any] | None:
    triggered = [item for item in evaluations if item["triggered"]]
    if not triggered:
        return None
    selected = sorted(triggered, key=lambda item: (decimal_value(item["maximum_rating"]), item["cap_id"]))[0]
    return {
        "cap_id": selected["cap_id"],
        "maximum_rating": selected["maximum_rating"],
        "affected_evidence_ids": selected["affected_evidence_ids"],
    }


def apply_cap(base: Decimal, evaluations: list[dict[str, Any]]) -> tuple[Decimal, dict[str, Any] | None]:
    applied = choose_cap(evaluations)
    if applied is None:
        return base, None
    return min(base, decimal_value(applied["maximum_rating"])), applied


def finish_dimension(
    dimension_id: str,
    components: list[dict[str, Any]],
    central_base: Decimal,
    lower_base: Decimal,
    upper_base: Decimal,
    central_caps: list[dict[str, Any]],
    lower_caps: list[dict[str, Any]],
    upper_caps: list[dict[str, Any]],
    audit_mode: str,
    final_rounding: bool = True,
    fixed_points: tuple[Decimal, Decimal, Decimal] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    weight = WEIGHTS[dimension_id]
    warnings = list(warnings or [])
    full_not_measured = audit_mode == "full" and any(item["not_measured"] for item in components if not item["genuinely_inapplicable"])
    insufficient_component = any(not item["provisionally_scoreable"] for item in components if not item["genuinely_inapplicable"])
    central_post, central_applied = apply_cap(central_base, central_caps)
    lower_post, lower_applied = apply_cap(lower_base, lower_caps)
    upper_post, upper_applied = apply_cap(upper_base, upper_caps)
    if final_rounding:
        central_rounded = round_half_step(central_post)
        lower_rounded = round_half_step(lower_post)
        upper_rounded = round_half_step(upper_post)
    else:
        central_rounded = central_post
        lower_rounded = lower_post
        upper_rounded = upper_post
    lower_cap_id = lower_applied["cap_id"] if lower_applied else None
    upper_cap_id = upper_applied["cap_id"] if upper_applied else None
    stable = lower_rounded == upper_rounded and lower_cap_id == upper_cap_id
    scored = not full_not_measured and not insufficient_component and stable
    if fixed_points is None:
        points = round_points(central_rounded / FIVE * Decimal(weight)) if scored else None
        lower_points = round_points(lower_rounded / FIVE * Decimal(weight))
        upper_points = round_points(upper_rounded / FIVE * Decimal(weight))
    else:
        points = fixed_points[0] if scored else None
        lower_points = fixed_points[1]
        upper_points = fixed_points[2]
    if full_not_measured:
        status = "not_scored_incomplete_full_audit"
    elif insufficient_component or not stable:
        status = "not_scored_insufficient_evidence"
    else:
        status = "scored"
    return {
        "dimension_id": dimension_id,
        "status": status,
        "formula_id": f"{CALCULATION_PROFILE}:{dimension_id}",
        "input_roles": [],
        "denominators": {"components": components},
        "raw_status_counts": {},
        "credit_mappings": {},
        "components": [],
        "base_rating": decimal_text(central_base),
        "unrounded_rating": decimal_text(central_post),
        "cap_evaluations": central_caps,
        "applied_cap": central_applied,
        "pre_cap_rating": decimal_text(central_base),
        "post_cap_rating": decimal_text(central_post),
        "missing_data_bounds": {
            "lower": {
                "pre_cap_rating": decimal_text(lower_base),
                "post_cap_rating": decimal_text(lower_post),
                "rounded_rating": displayed_number(lower_rounded, Decimal("0.0001") if not final_rounding else None),
                "cap_evaluations": lower_caps,
                "applied_cap_id": lower_cap_id,
                "awarded_points": displayed_number(lower_points, Decimal("0.01")),
            },
            "upper": {
                "pre_cap_rating": decimal_text(upper_base),
                "post_cap_rating": decimal_text(upper_post),
                "rounded_rating": displayed_number(upper_rounded, Decimal("0.0001") if not final_rounding else None),
                "cap_evaluations": upper_caps,
                "applied_cap_id": upper_cap_id,
                "awarded_points": displayed_number(upper_points, Decimal("0.01")),
            },
            "stable_rating": lower_rounded == upper_rounded,
            "stable_cap_outcome": lower_cap_id == upper_cap_id,
        },
        "rounding": {
            "mode": "ROUND_HALF_UP",
            "quantum": "0.5" if final_rounding else "editorial_10_plus_5_equivalent",
            "input": decimal_text(central_post),
            "output": displayed_number(central_rounded, Decimal("0.0001") if not final_rounding else None) if scored else None,
        },
        "final_rating": displayed_number(central_rounded, Decimal("0.0001") if not final_rounding else None) if scored else None,
        "dimension_weight": weight,
        "awarded_points": displayed_number(points, Decimal("0.01")) if points is not None else None,
        "warnings": warnings,
    }


def defect_subset(ledgers: dict[str, Any], owner: str, *, severities: set[str] | None = None, kinds: set[str] | None = None, codes: set[str] | None = None) -> list[dict[str, Any]]:
    result = [item for item in ledgers["defects"] if item.get("dimension_owner") == owner]
    if severities is not None:
        result = [item for item in result if item.get("severity") in severities]
    if kinds is not None:
        result = [item for item in result if item.get("defect_kind") in kinds]
    if codes is not None:
        result = [item for item in result if item.get("code") in codes]
    return result


def essential_cap(missing: int, denominator: int) -> tuple[Decimal, str]:
    miss_rate = rate(missing, denominator)
    if missing == 0 or denominator == 0:
        return FIVE, "0_percent"
    for boundary, maximum, label in (
        (Decimal("0.05"), Decimal("4.5"), "above_0_through_5_percent"),
        (Decimal("0.10"), Decimal("4.0"), "above_5_through_10_percent"),
        (Decimal("0.20"), Decimal("3.5"), "above_10_through_20_percent"),
        (Decimal("0.35"), Decimal("3.0"), "above_20_through_35_percent"),
        (Decimal("0.50"), Decimal("2.0"), "above_35_through_50_percent"),
    ):
        if miss_rate <= boundary:
            return maximum, label
    return Decimal("1.0"), "above_50_percent"


def calculate_coverage(ledgers: dict[str, Any], audit_mode: str) -> dict[str, Any]:
    optional_map = ledgers["optional_map"]
    excluded_optional = [item for item in ledgers["subjects"] if item.get("priority") == "optional" and not optional_map[item["subject_id"]]]
    applicable_records = [item for item in ledgers["subjects"] if item.get("priority") != "optional" or optional_map[item["subject_id"]]]
    measured = [item for item in applicable_records if item.get("coverage") in COVERAGE_CREDIT]
    uninspectable = [item for item in applicable_records if item.get("coverage") == "uninspectable"]
    explicit_not_measured = [item for item in applicable_records if item.get("coverage") == "not_measured"]
    missing_ids = ledgers["subject_not_measured"]
    denominator = component_denominators(
        "priority_weighted_subject_access",
        ledgers["subject_original"],
        len(applicable_records) + len(missing_ids),
        len(measured),
        len(uninspectable),
        len(explicit_not_measured) + len(missing_ids),
        {"optional_not_frozen_as_scored": len(excluded_optional)},
    )
    weight_total = sum((PRIORITY_CREDIT[item["priority"]] for item in measured), ZERO)
    measured_credit = sum((PRIORITY_CREDIT[item["priority"]] * COVERAGE_CREDIT[item["coverage"]] for item in measured), ZERO)
    unknown_weight = sum((PRIORITY_CREDIT[item["priority"]] for item in uninspectable + explicit_not_measured), ZERO)
    # Missing expected records have unknown priorities, so a full audit is blocked.  In pilot mode they
    # conservatively use the maximum priority weight for bounds.
    unknown_weight += Decimal(3 * len(missing_ids))
    central_base = FIVE * measured_credit / weight_total if weight_total else ZERO
    lower_base = FIVE * measured_credit / (weight_total + unknown_weight) if weight_total + unknown_weight else ZERO
    upper_base = FIVE * (measured_credit + unknown_weight) / (weight_total + unknown_weight) if weight_total + unknown_weight else ZERO
    attempt = ledgers["context"]["candidate_attempt"]["status"]
    if attempt != "meaningful_attempt":
        central_base = lower_base = upper_base = ZERO
        mark_defined_zero(denominator, f"candidate_attempt:{attempt}", non_attempt=True)
    essential_measured = [item for item in measured if item.get("priority") == "essential"]
    essential_unknown = [item for item in uninspectable + explicit_not_measured if item.get("priority") == "essential"]
    essential_total = len(essential_measured) + len(essential_unknown)
    lower_essential_total = essential_total + len(missing_ids)
    essential_missing = sum(item["coverage"] == "missing" for item in essential_measured)
    central_max, central_band = essential_cap(essential_missing, len(essential_measured))
    lower_max, lower_band = essential_cap(essential_missing + len(essential_unknown) + len(missing_ids), lower_essential_total)
    upper_max, upper_band = essential_cap(essential_missing, essential_total)
    critical = defect_subset(ledgers, "meaningful_coverage", severities={"critical"}, kinds={"central_omission"})

    def caps(maximum: Decimal, band: str, missing_count: int, total: int, miss_evidence: Sequence[str]) -> list[dict[str, Any]]:
        return [
            cap_record(
                "coverage.essential_miss_rate",
                maximum,
                maximum < FIVE,
                {"table": "essential_miss_rate_v1", "band": band},
                {"missing": missing_count, "essential_denominator": total, "rate": decimal_text(rate(missing_count, total))},
                miss_evidence,
            ),
            cap_record(
                "coverage.critical_central_omission",
                Decimal(2),
                bool(critical),
                {"severity": "critical", "defect_kind": "central_omission"},
                {"defect_count": len(critical)},
                [item["defect_id"] for item in critical],
            ),
        ]

    result = finish_dimension(
        "meaningful_coverage", [denominator], central_base, lower_base, upper_base,
        caps(central_max, central_band, essential_missing, len(essential_measured), [item["subject_id"] for item in essential_measured if item["coverage"] == "missing"]),
        caps(lower_max, lower_band, essential_missing + len(essential_unknown) + len(missing_ids), lower_essential_total, [item["subject_id"] for item in essential_measured if item["coverage"] == "missing"] + [item["subject_id"] for item in essential_unknown] + missing_ids),
        caps(upper_max, upper_band, essential_missing, essential_total, [item["subject_id"] for item in essential_measured if item["coverage"] == "missing"]), audit_mode,
    )
    result["input_roles"] = ["missing_access_audit", "structure_audit_or_migration_supplement"]
    result["raw_status_counts"] = dict(Counter(item.get("coverage") for item in applicable_records)) | {"not_measured_expected_ids": len(missing_ids)}
    result["credit_mappings"] = {"coverage": {key: decimal_text(value) for key, value in COVERAGE_CREDIT.items()}, "priority": {key: decimal_text(value) for key, value in PRIORITY_CREDIT.items()}}
    result["components"] = [{
        "component_id": "priority_weighted_subject_access",
        "raw_numerator": decimal_text(measured_credit),
        "raw_denominator": decimal_text(weight_total),
        "normalized_value": decimal_text(central_base / FIVE if FIVE else ZERO),
        "weight": "1",
        "effective_weight": "1",
        "weight_renormalized": False,
    }]
    return result


def density_metric_rating(value: Decimal, acceptable_min: Decimal, ideal_min: Decimal, ideal_max: Decimal, acceptable_max: Decimal) -> Decimal:
    require(ZERO <= acceptable_min <= ideal_min <= ideal_max <= acceptable_max, "invalid_density_band", "Density boundaries are invalid.")
    if value == 0:
        return ZERO
    if ideal_min <= value <= ideal_max:
        return FIVE
    if acceptable_min <= value <= acceptable_max:
        return Decimal(4)
    if value < acceptable_min:
        distance = (acceptable_min - value) / acceptable_min if acceptable_min else Decimal("Infinity")
    else:
        distance = (value - acceptable_max) / acceptable_max if acceptable_max else Decimal("Infinity")
    if distance <= Decimal("0.25"):
        return Decimal(3)
    if distance <= Decimal("0.50"):
        return Decimal(2)
    if distance <= ONE:
        return ONE
    return ZERO


def calculate_density(ledgers: dict[str, Any]) -> tuple[Decimal, dict[str, Any]]:
    structure = ledgers["structure"]
    density = structure.get("density") if isinstance(structure.get("density"), dict) else {}
    chapters = density.get("chapter_measurements")
    require(isinstance(chapters, list) and chapters, "density_inputs_missing", "V5 density requires non-empty chapter measurements with raw word and count fields.")
    count_reconstruction = ledgers.get("density_count_reconstruction")
    if not isinstance(count_reconstruction, dict):
        actual_by_chunk: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for locator in ledgers.get("locators", []):
            actual_by_chunk[locator.get("_source_unit_id")].append(locator)
        missing_by_chunk = Counter(ledgers.get("locator_not_measured_units", []))
        count_reconstruction = {}
        for chapter in chapters:
            chunk_id = chapter.get("chunk_id")
            locators = actual_by_chunk.get(chunk_id, [])
            path_ids = {item.get("path_id") for item in locators}
            require(
                None not in path_ids and all(isinstance(item, str) and item.startswith("PATH-") for item in path_ids),
                "invalid_ledger",
                f"Density reconstruction for {chunk_id} requires a stable PATH-* identity for every locator judgment.",
            )
            missing_count = missing_by_chunk[chunk_id]
            declared_paths = chapter.get("locator_bearing_heading_paths")
            declared_occurrences = chapter.get("locator_occurrences")
            expected_occurrences = len(locators) + missing_count
            require(
                declared_occurrences == expected_occurrences,
                "recomputable_aggregate_mismatch",
                f"Density locator_occurrences for {chunk_id} does not equal the stable locator-ID count.",
                {"chunk_id": chunk_id, "field": "locator_occurrences", "expected": expected_occurrences, "actual": declared_occurrences},
            )
            require(
                len(path_ids) <= declared_paths <= len(path_ids) + missing_count,
                "recomputable_aggregate_mismatch",
                f"Density locator_bearing_heading_paths for {chunk_id} is outside the reconstructable stable-ID range.",
                {"chunk_id": chunk_id, "field": "locator_bearing_heading_paths", "minimum": len(path_ids), "maximum": len(path_ids) + missing_count, "actual": declared_paths},
            )
            count_reconstruction[chunk_id] = {
                "locator_occurrences": expected_occurrences,
                "locator_bearing_heading_paths": declared_paths,
                "known_locator_bearing_heading_paths": len(path_ids),
                "not_measured_locator_count": missing_count,
                "path_count_basis": "recomputed_from_path_ids" if missing_count == 0 else "frozen_count_within_reconstructed_missing_item_bounds",
                "occurrence_count_basis": "recomputed_from_expected_locator_ids",
            }
    total_words = 0
    weighted = ZERO
    chapter_results: list[dict[str, Any]] = []
    for index, chapter in enumerate(chapters):
        words = chapter.get("indexable_source_words")
        chunk_id = chapter.get("chunk_id")
        require(chunk_id in count_reconstruction, "density_inputs_missing", f"Density chapter {index} has no locator-ledger count reconstruction.")
        count_evidence = count_reconstruction[chunk_id]
        paths = count_evidence["locator_bearing_heading_paths"]
        occurrences = count_evidence["locator_occurrences"]
        require(isinstance(words, int) and words > 0 and isinstance(paths, int) and paths >= 0 and isinstance(occurrences, int) and occurrences >= 0, "density_inputs_missing", f"Density chapter {index} lacks valid raw counts.")
        path_rate = Decimal(paths) / Decimal(words) * Decimal(1000)
        occurrence_rate = Decimal(occurrences) / Decimal(words) * Decimal(1000)
        path_rating = density_metric_rating(path_rate, Decimal(4), Decimal(6), Decimal(10), Decimal(12))
        occurrence_rating = density_metric_rating(occurrence_rate, Decimal(10), Decimal(15), Decimal(25), Decimal(30))
        unit = path_rating * HALF + occurrence_rating * HALF
        total_words += words
        weighted += unit * Decimal(words)
        chapter_results.append({
            "chunk_id": chunk_id,
            "indexable_source_words": words,
            "locator_bearing_heading_paths": paths,
            "locator_occurrences": occurrences,
            "count_provenance": {
                "locator_bearing_heading_paths": count_evidence["path_count_basis"],
                "locator_occurrences": count_evidence["occurrence_count_basis"],
                "known_locator_bearing_heading_paths": count_evidence["known_locator_bearing_heading_paths"],
                "not_measured_locator_count": count_evidence["not_measured_locator_count"],
            },
            "path_rate": decimal_text(path_rate),
            "occurrence_rate": decimal_text(occurrence_rate),
            "path_fit_rating": displayed_number(path_rating),
            "occurrence_fit_rating": displayed_number(occurrence_rating),
            "unit_fit_rating_unrounded": decimal_text(unit),
            "unit_fit_rating": displayed_number(round_half_step(unit)),
        })
    raw = weighted / Decimal(total_words)
    final = round_half_step(raw)
    return final, {
        "profile_id": "subject-index-standard-density-v1-v5-edge-correction",
        "aggregation": "indexable_source_word_weighted_mean",
        "metric_weights": {"paths": "0.5", "occurrences": "0.5"},
        "fit_rating_unrounded": decimal_text(raw),
        "fit_rating": displayed_number(final),
        "chapter_measurements": chapter_results,
        "zero_metric_rule": "a metric value of zero receives 0/5",
    }


def selectivity_cap(rate_value: Decimal, count: int, unit_rate: Decimal) -> tuple[Decimal, bool, str]:
    systemic = count >= 10 and unit_rate >= Decimal("0.25")
    if not systemic or rate_value < Decimal("0.05"):
        return FIVE, False, "below_5_percent_or_not_systemic"
    if rate_value < Decimal("0.15"):
        return Decimal(4), True, "5_to_below_15_percent"
    if rate_value < Decimal("0.30"):
        return Decimal(3), True, "15_to_below_30_percent"
    if rate_value < Decimal("0.50"):
        return Decimal(2), True, "30_to_below_50_percent"
    return Decimal(1), True, "at_least_50_percent"


def calculate_selectivity(ledgers: dict[str, Any], audit_mode: str) -> dict[str, Any]:
    attempt = ledgers["context"]["candidate_attempt"]["status"]
    applicable_classes = set(SELECTIVITY_CREDIT)
    measured = [item for item in ledgers["locators"] if item.get("source_scope_status") == "indexable" and item.get("treatment_class") in applicable_classes and item.get("judgment") != "uninspectable"]
    uninspectable = [item for item in ledgers["locators"] if item.get("source_scope_status") == "indexable" and item.get("treatment_class") in applicable_classes and item.get("judgment") == "uninspectable"]
    not_measured = ledgers["locator_not_measured"]
    excluded_counts = Counter()
    for item in ledgers["locators"]:
        if item in measured or item in uninspectable:
            continue
        if item.get("treatment_class") == "absent":
            excluded_counts["absent_owned_by_reliability"] += 1
        elif item.get("treatment_class") == "unavailable" or item.get("source_scope_status") in {"excluded", "unavailable", "ambiguous"}:
            excluded_counts["scope_or_ambiguity_owned_elsewhere"] += 1
        else:
            excluded_counts["not_selectivity_applicable"] += 1
    original = ledgers["locator_original"]
    applicable = len(measured) + len(uninspectable) + len(not_measured)
    non_attempt = attempt != "meaningful_attempt"
    locator_output_without_supported_access = bool(ledgers["locators"]) and not any(item.get("treatment_class") in {"substantive", "mixed"} for item in measured)
    zero_rule = None
    if non_attempt:
        zero_rule = f"candidate_attempt:{attempt}"
    elif locator_output_without_supported_access:
        zero_rule = "locator_output_without_substantive_or_mixed_supported_access"
    substantive_denom = component_denominators(
        "substantive_selectivity",
        original,
        applicable,
        len(measured),
        len(uninspectable),
        len(not_measured),
        dict(excluded_counts),
        zero_due_to_non_attempt=non_attempt,
        defined_zero_rule=zero_rule,
    )
    density_denom = component_denominators(
        "density_fit",
        1,
        1,
        1,
        0,
        0,
        {},
        zero_due_to_non_attempt=non_attempt,
        defined_zero_rule=f"candidate_attempt:{attempt}" if non_attempt else None,
    )
    credit = sum((SELECTIVITY_CREDIT[item["treatment_class"]] for item in measured), ZERO)
    if non_attempt or locator_output_without_supported_access:
        central_base = ZERO
    else:
        central_base = FIVE * credit / Decimal(len(measured)) if measured else ZERO
    lower_base = FIVE * credit / Decimal(len(measured) + len(uninspectable) + len(not_measured)) if applicable else ZERO
    upper_base = FIVE * (credit + Decimal(len(uninspectable) + len(not_measured))) / Decimal(applicable) if applicable else ZERO
    zero_measured = [item for item in measured if SELECTIVITY_CREDIT[item["treatment_class"]] == 0]
    unit_total = max(1, len(ledgers["source_units"]))

    def caps(zero_count: int, denom: int, units: set[str], evidence_ids: Sequence[str]) -> list[dict[str, Any]]:
        zero_rate = rate(zero_count, denom)
        unit_rate = rate(len(units), unit_total)
        maximum, triggered, band = selectivity_cap(zero_rate, zero_count, unit_rate)
        return [cap_record(
            "selectivity.systemic_zero_credit",
            maximum,
            triggered,
            {"minimum_count": 10, "minimum_source_unit_rate": "0.25", "rate_table": "systemic_zero_credit_v1", "band": band},
            {"zero_credit_count": zero_count, "applicable_count": denom, "zero_credit_rate": decimal_text(zero_rate), "affected_source_units": len(units), "source_unit_denominator": unit_total, "source_unit_rate": decimal_text(unit_rate)},
            evidence_ids,
        )]

    central_units = {item["_source_unit_id"] for item in zero_measured if item.get("_source_unit_id")}
    unknown_units = {item["_source_unit_id"] for item in uninspectable if item.get("_source_unit_id")}
    unknown_units.update(item for item in ledgers["locator_not_measured_units"] if item)
    known_zero_ids = [item["locator_id"] for item in zero_measured]
    central_caps = caps(len(zero_measured), len(measured), central_units, known_zero_ids)
    lower_caps = caps(len(zero_measured) + len(uninspectable) + len(not_measured), applicable, central_units | unknown_units, known_zero_ids + [item["locator_id"] for item in uninspectable] + not_measured)
    upper_caps = caps(len(zero_measured), applicable, central_units, known_zero_ids)
    observed_density_rating, density_detail = calculate_density(ledgers)
    density_rating = ZERO if non_attempt else observed_density_rating
    if non_attempt:
        density_detail["scoring_override"] = {"rating": 0, "rule": f"candidate_attempt:{attempt}"}

    central_sub_post, _ = apply_cap(central_base, central_caps)
    lower_sub_post, _ = apply_cap(lower_base, lower_caps)
    upper_sub_post, _ = apply_cap(upper_base, upper_caps)
    if non_attempt:
        lower_sub_post = upper_sub_post = ZERO
    central_sub = round_half_step(central_sub_post)
    lower_sub = round_half_step(lower_sub_post)
    upper_sub = round_half_step(upper_sub_post)
    central_base_points = central_base / FIVE * Decimal(10) + density_rating
    central_base_equivalent = central_base_points / Decimal(15) * FIVE
    central_points = round_points(central_sub / FIVE * Decimal(10) + density_rating)
    lower_points = round_points(lower_sub / FIVE * Decimal(10) + density_rating)
    upper_points = round_points(upper_sub / FIVE * Decimal(10) + density_rating)
    central_equivalent = central_points / Decimal(15) * FIVE
    lower_equivalent = lower_points / Decimal(15) * FIVE
    upper_equivalent = upper_points / Decimal(15) * FIVE
    central_post_unrounded_equivalent = (central_sub_post / FIVE * Decimal(10) + density_rating) / Decimal(15) * FIVE
    lower_pre_unrounded_equivalent = (lower_base / FIVE * Decimal(10) + density_rating) / Decimal(15) * FIVE
    lower_post_unrounded_equivalent = (lower_sub_post / FIVE * Decimal(10) + density_rating) / Decimal(15) * FIVE
    upper_pre_unrounded_equivalent = (upper_base / FIVE * Decimal(10) + density_rating) / Decimal(15) * FIVE
    upper_post_unrounded_equivalent = (upper_sub_post / FIVE * Decimal(10) + density_rating) / Decimal(15) * FIVE
    result = finish_dimension(
        "editorial_selectivity", [substantive_denom, density_denom], central_equivalent, lower_equivalent, upper_equivalent,
        [], [], [], audit_mode, final_rounding=False,
        fixed_points=(central_points, lower_points, upper_points),
    )
    # The consequence cap applies to the substantive subscore before 10+5 arithmetic.
    central_applied = choose_cap(central_caps)
    lower_applied = choose_cap(lower_caps)
    upper_applied = choose_cap(upper_caps)
    cap_stable = (lower_applied["cap_id"] if lower_applied else None) == (upper_applied["cap_id"] if upper_applied else None)
    if not cap_stable and result["status"] == "scored":
        result["status"] = "not_scored_insufficient_evidence"
        result["final_rating"] = None
        result["awarded_points"] = None
        result["rounding"]["output"] = None
    result["base_rating"] = decimal_text(central_base_equivalent)
    result["pre_cap_rating"] = decimal_text(central_base_equivalent)
    result["post_cap_rating"] = decimal_text(central_post_unrounded_equivalent)
    result["unrounded_rating"] = decimal_text(central_post_unrounded_equivalent)
    result["cap_evaluations"] = central_caps
    result["applied_cap"] = central_applied
    result["missing_data_bounds"]["lower"]["applied_cap_id"] = lower_applied["cap_id"] if lower_applied else None
    result["missing_data_bounds"]["lower"]["cap_evaluations"] = lower_caps
    result["missing_data_bounds"]["lower"]["pre_cap_rating"] = decimal_text(lower_pre_unrounded_equivalent)
    result["missing_data_bounds"]["lower"]["post_cap_rating"] = decimal_text(lower_post_unrounded_equivalent)
    result["missing_data_bounds"]["upper"]["applied_cap_id"] = upper_applied["cap_id"] if upper_applied else None
    result["missing_data_bounds"]["upper"]["cap_evaluations"] = upper_caps
    result["missing_data_bounds"]["upper"]["pre_cap_rating"] = decimal_text(upper_pre_unrounded_equivalent)
    result["missing_data_bounds"]["upper"]["post_cap_rating"] = decimal_text(upper_post_unrounded_equivalent)
    result["missing_data_bounds"]["stable_cap_outcome"] = cap_stable
    result["rounding"] = {"mode": "ROUND_HALF_UP", "quantum": "substantive_0.5_then_points_0.01", "input": decimal_text(central_sub_post), "output": result["final_rating"]}
    result["input_roles"] = ["locator_audit", "structure_audit_or_migration_supplement"]
    result["raw_status_counts"] = dict(Counter(item.get("treatment_class") for item in measured)) | {"uninspectable": len(uninspectable), "not_measured": len(not_measured)}
    result["credit_mappings"] = {"treatment_class": {key: decimal_text(value) for key, value in SELECTIVITY_CREDIT.items()}}
    result["components"] = [
        {"component_id": "substantive_selectivity", "raw_numerator": decimal_text(credit), "raw_denominator": decimal_text(Decimal(len(measured))), "normalized_value": decimal_text(central_sub_post / FIVE), "weight": "10/15", "effective_weight": "10/15", "weight_renormalized": False, "rounded_rating": displayed_number(central_sub)},
        {"component_id": "density_fit", "raw_numerator": decimal_text(density_rating), "raw_denominator": "5", "normalized_value": decimal_text(density_rating / FIVE), "weight": "5/15", "effective_weight": "5/15", "weight_renormalized": False, "rounded_rating": displayed_number(density_rating), "details": density_detail},
    ]
    return result


def node_component(ledgers: dict[str, Any], component: str, mapping: dict[str, Decimal], component_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[str], dict[str, Any]]:
    measured: list[dict[str, Any]] = []
    uninspectable: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    explicit_not_measured: list[dict[str, Any]] = []
    for node in ledgers["nodes"]:
        judgment = node.get("component_judgments", {}).get(component, {})
        status = judgment.get("status")
        decorated = {**node, "_status": status, "_component_evidence_ids": judgment.get("evidence_ids", [])}
        if status in mapping:
            measured.append(decorated)
        elif status == "uninspectable":
            uninspectable.append(decorated)
        elif status == "not_applicable":
            excluded.append(decorated)
        elif status == "not_measured" or status is None:
            explicit_not_measured.append(decorated)
        else:
            raise CalculationError("invalid_component_status", f"Unsupported {component_id} status: {status}")
    not_measured_ids = [item["node_id"] for item in explicit_not_measured] + ledgers["node_not_measured"]
    denominator = component_denominators(
        component_id, ledgers["node_original"], ledgers["node_original"] - len(excluded), len(measured), len(uninspectable), len(not_measured_ids), {"not_applicable": len(excluded)}
    )
    return measured, uninspectable, excluded, not_measured_ids, denominator


def prevalence_caps(prefix: str, major_fail: int, denominator: int, evidence_ids: list[str], table: Sequence[tuple[Decimal, Decimal]]) -> list[dict[str, Any]]:
    observed_rate = rate(major_fail, denominator)
    records: list[dict[str, Any]] = []
    for threshold, maximum in table:
        records.append(cap_record(
            f"{prefix}.prevalence_at_least_{decimal_text(threshold)}",
            maximum,
            denominator > 0 and observed_rate >= threshold,
            {"operator": ">=", "rate": decimal_text(threshold)},
            {"affected_count": major_fail, "applicable_count": denominator, "rate": decimal_text(observed_rate)},
            evidence_ids,
        ))
    return records


def require_node_defect_binding(node: dict[str, Any], ledgers: dict[str, Any], owner: str, component_label: str) -> None:
    evidence_ids = set(node.get("_component_evidence_ids", []))
    matches = [
        defect
        for defect in ledgers["defects"]
        if defect["dimension_owner"] == owner
        and defect["defect_id"] in evidence_ids
        and node["node_id"] in defect["affected_item_ids"]
        and defect["severity"] in {"major", "critical"}
    ]
    require(
        bool(matches),
        "unstructured_major_or_fail_node",
        f"Major/fail {component_label} node {node['node_id']} must cite a same-dimension structured major/critical defect that names the node.",
    )


def calculate_concept(ledgers: dict[str, Any], audit_mode: str) -> dict[str, Any]:
    measured, uninspectable, _, not_measured_ids, denominator = node_component(ledgers, "conceptual_stance_fidelity", NODE_CREDIT, "conceptual_stance_nodes")
    credit = sum((NODE_CREDIT[item["_status"]] for item in measured), ZERO)
    central_base = FIVE * credit / Decimal(len(measured)) if measured else ZERO
    unknown = len(uninspectable) + len(not_measured_ids)
    applicable = len(measured) + unknown
    lower_base = FIVE * credit / Decimal(applicable) if applicable else ZERO
    upper_base = FIVE * (credit + Decimal(unknown)) / Decimal(applicable) if applicable else ZERO
    attempt = ledgers["context"]["candidate_attempt"]["status"]
    if attempt in {"empty", "structurally_incomplete", "unparseable"}:
        central_base = lower_base = upper_base = ZERO
        mark_defined_zero(denominator, f"candidate_attempt:{attempt}", non_attempt=True)
    major_fail = [item for item in measured if item["_status"] in {"major_issues", "fails"}]
    major_fail_ids = [item["node_id"] for item in major_fail]
    for node in major_fail:
        require_node_defect_binding(node, ledgers, "conceptual_stance_fidelity", "conceptual/stance")
    critical = defect_subset(ledgers, "conceptual_stance_fidelity", severities={"critical"}, codes=CONCEPT_CODES)
    local_major = defect_subset(ledgers, "conceptual_stance_fidelity", severities={"major"}, codes=CONCEPT_CODES)
    reversals = [item for item in local_major if item.get("defect_kind") in {"stance_reversal", "misleading_relationship"}]

    def caps(major_fail_count: int, total: int, prevalence_evidence: Sequence[str]) -> list[dict[str, Any]]:
        return [
            cap_record("concept.critical_defect", Decimal(2), bool(critical), {"severity": "critical", "codes": sorted(CONCEPT_CODES)}, {"defect_count": len(critical)}, [item["defect_id"] for item in critical]),
            cap_record("concept.localized_major_defect", Decimal("4.5"), bool(local_major), {"severity": "major", "codes": sorted(CONCEPT_CODES)}, {"defect_count": len(local_major)}, [item["defect_id"] for item in local_major]),
            cap_record("concept.major_stance_or_relationship", Decimal(4), bool(reversals), {"severity": "major", "defect_kinds": ["stance_reversal", "misleading_relationship"]}, {"defect_count": len(reversals)}, [item["defect_id"] for item in reversals]),
            *prevalence_caps("concept", major_fail_count, total, list(prevalence_evidence), ((Decimal("0.05"), Decimal("3.5")), (Decimal("0.15"), Decimal("2.5")), (Decimal("0.30"), Decimal("1.5")))),
        ]

    unknown_node_ids = [item["node_id"] for item in uninspectable] + not_measured_ids
    result = finish_dimension(
        "conceptual_stance_fidelity", [denominator], central_base, lower_base, upper_base,
        caps(len(major_fail), len(measured), major_fail_ids),
        caps(len(major_fail) + unknown, applicable, major_fail_ids + unknown_node_ids),
        caps(len(major_fail), applicable, major_fail_ids),
        audit_mode,
    )
    result["input_roles"] = ["structure_audit", "structure_audit_or_migration_supplement"]
    result["raw_status_counts"] = dict(Counter(item["_status"] for item in measured)) | {"uninspectable": len(uninspectable), "not_measured": len(not_measured_ids)}
    result["credit_mappings"] = {"node_status": {key: decimal_text(value) for key, value in NODE_CREDIT.items()}}
    result["components"] = [{"component_id": "conceptual_stance_nodes", "raw_numerator": decimal_text(credit), "raw_denominator": decimal_text(Decimal(len(measured))), "normalized_value": decimal_text(central_base / FIVE), "weight": "1", "effective_weight": "1", "weight_renormalized": False}]
    return result


def high_value_cap(found: int, denominator: int) -> tuple[Decimal, bool, str]:
    if denominator == 0:
        return FIVE, False, "inapplicable_no_high_value_treatments"
    value = rate(found, denominator)
    if value >= Decimal("0.90"):
        return FIVE, False, "at_least_90_percent"
    if value >= Decimal("0.75"):
        return Decimal(4), True, "75_to_below_90_percent"
    if value >= Decimal("0.50"):
        return Decimal(3), True, "50_to_below_75_percent"
    if value >= Decimal("0.25"):
        return Decimal(2), True, "25_to_below_50_percent"
    return Decimal(1), True, "below_25_percent"


def reliability_pattern_cap(pattern_count: int, denominator: int, affected_units: int, unit_denominator: int) -> tuple[Decimal, bool, str]:
    value = rate(pattern_count, denominator)
    distributed = unit_denominator > 0 and rate(affected_units, unit_denominator) >= Decimal("0.25")
    if not distributed or value < Decimal("0.01"):
        return FIVE, False, "below_1_percent_or_not_distributed"
    if value < Decimal("0.03"):
        return Decimal("4.5"), True, "1_to_below_3_percent"
    if value < Decimal("0.075"):
        return Decimal(4), True, "3_to_below_7_5_percent"
    if value < Decimal("0.15"):
        return Decimal("3.5"), True, "7_5_to_below_15_percent"
    if value < Decimal("0.30"):
        return Decimal("2.5"), True, "15_to_below_30_percent"
    return Decimal("1.5"), True, "at_least_30_percent"


def f1(precision: Decimal, recall: Decimal) -> Decimal:
    return ZERO if precision + recall == 0 else Decimal(2) * precision * recall / (precision + recall)


def calculate_reliability(ledgers: dict[str, Any], audit_mode: str) -> dict[str, Any]:
    measured_locators = [item for item in ledgers["locators"] if item.get("judgment") in {"supported", "partially_supported", "unsupported"}]
    uninspectable_locators = [item for item in ledgers["locators"] if item.get("judgment") == "uninspectable"]
    locator_not_measured = ledgers["locator_not_measured"]
    precision_denom = component_denominators("strict_locator_precision", ledgers["locator_original"], ledgers["locator_original"], len(measured_locators), len(uninspectable_locators), len(locator_not_measured), {})
    measured_treatments = [item for item in ledgers["treatments"] if item.get("status") in {"found", "missed"}]
    uninspectable_treatments = [item for item in ledgers["treatments"] if item.get("status") == "uninspectable"]
    explicit_treatment_not_measured_records = [item for item in ledgers["treatments"] if item.get("status") is None]
    explicit_treatment_not_measured = [item["treatment_id"] for item in explicit_treatment_not_measured_records]
    treatment_not_measured = ledgers["treatment_not_measured"] + explicit_treatment_not_measured
    recall_denom = component_denominators("expected_treatment_recall", ledgers["treatment_original"], ledgers["treatment_original"], len(measured_treatments), len(uninspectable_treatments), len(treatment_not_measured), {})
    supported = sum(item["judgment"] == "supported" for item in measured_locators)
    found = sum(item["status"] == "found" for item in measured_treatments)
    p = rate(supported, len(measured_locators))
    r = rate(found, len(measured_treatments))
    unknown_loc = len(uninspectable_locators) + len(locator_not_measured)
    unknown_treat = len(uninspectable_treatments) + len(treatment_not_measured)
    p_lower = rate(supported, len(measured_locators) + unknown_loc)
    p_upper = rate(supported + unknown_loc, len(measured_locators) + unknown_loc)
    r_lower = rate(found, len(measured_treatments) + unknown_treat)
    r_upper = rate(found + unknown_treat, len(measured_treatments) + unknown_treat)
    expected_treatments = ledgers["treatment_original"]
    no_locator_assignments = ledgers["locator_original"] == 0
    attempt = ledgers["context"]["candidate_attempt"]["status"]
    if expected_treatments > 0 and no_locator_assignments:
        central_base = lower_base = upper_base = ZERO
        mark_defined_zero(precision_denom, "expected_treatments_but_no_locator_assignments")
    else:
        central_base = FIVE * f1(p, r)
        lower_base = FIVE * f1(p_lower, r_lower)
        upper_base = FIVE * f1(p_upper, r_upper)
    if attempt in {"empty", "structurally_incomplete", "unparseable"}:
        central_base = lower_base = upper_base = ZERO
        for component in (precision_denom, recall_denom):
            mark_defined_zero(component, f"candidate_attempt:{attempt}", non_attempt=True)
    high_measured = [item for item in measured_treatments if item.get("locator_class") in {"principal", "synthesis_or_conclusion"}]
    high_unknown = [item for item in uninspectable_treatments if item.get("locator_class") in {"principal", "synthesis_or_conclusion"}]
    high_not_measured_ids = [
        item["treatment_id"]
        for item in explicit_treatment_not_measured_records
        if item.get("locator_class") in {"principal", "synthesis_or_conclusion"}
    ] + ledgers["treatment_not_measured"]
    high_found = sum(item["status"] == "found" for item in high_measured)
    critical = defect_subset(ledgers, "page_reference_reliability", severities={"critical"}, kinds={"fabricated_locator", "nonexistent_locator", "out_of_scope_locator"})
    pattern = [item for item in measured_locators if item.get("judgment") == "unsupported" and set(item.get("error_codes", [])) & RELIABILITY_CODES]
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
        high_max, high_triggered, high_band = high_value_cap(high_found_value, high_total)
        pattern_max, pattern_triggered, pattern_band = reliability_pattern_cap(pattern_count, locator_total, units, unit_denominator)
        return [
            cap_record("reliability.critical_locator", Decimal(2), bool(critical), {"severity": "critical", "defect_kinds": ["fabricated_locator", "nonexistent_locator", "out_of_scope_locator"]}, {"defect_count": len(critical)}, [item["defect_id"] for item in critical]),
            cap_record("reliability.high_value_treatment_recall", high_max, high_triggered, {"table": "pooled_principal_and_synthesis_recall_v1", "band": high_band}, {"found": high_found_value, "expected": high_total, "rate": decimal_text(rate(high_found_value, high_total))}, high_miss_evidence),
            cap_record("reliability.distributed_unsupported_pattern", pattern_max, pattern_triggered, {"minimum_source_unit_rate": "0.25", "rate_table": "reliability_owned_unsupported_v1", "band": pattern_band}, {"unsupported_count": pattern_count, "strict_precision_denominator": locator_total, "rate": decimal_text(rate(pattern_count, locator_total)), "affected_source_units": units, "source_unit_denominator": unit_denominator, "source_unit_rate": decimal_text(rate(units, unit_denominator))}, pattern_evidence),
        ]

    known_high_misses = [item["treatment_id"] for item in high_measured if item["status"] == "missed"]
    known_pattern_ids = [item["locator_id"] for item in pattern]
    central_caps = caps(high_found, len(high_measured), len(pattern), len(measured_locators), len(pattern_units), known_high_misses, known_pattern_ids)
    lower_caps = caps(
        high_found,
        len(high_measured) + len(high_unknown) + len(high_not_measured_ids),
        len(pattern) + unknown_loc,
        len(measured_locators) + unknown_loc,
        len(pattern_units | unknown_locator_units),
        known_high_misses + [item["treatment_id"] for item in high_unknown] + high_not_measured_ids,
        known_pattern_ids + [item["locator_id"] for item in uninspectable_locators] + locator_not_measured,
    )
    upper_caps = caps(
        high_found + len(high_unknown) + len(high_not_measured_ids),
        len(high_measured) + len(high_unknown) + len(high_not_measured_ids),
        len(pattern),
        len(measured_locators) + unknown_loc,
        len(pattern_units),
        known_high_misses,
        known_pattern_ids,
    )
    result = finish_dimension("page_reference_reliability", [precision_denom, recall_denom], central_base, lower_base, upper_base, central_caps, lower_caps, upper_caps, audit_mode)
    result["input_roles"] = ["locator_audit", "missing_access_audit", "structure_audit_or_migration_supplement"]
    result["raw_status_counts"] = {
        "locator_support": dict(Counter(item["judgment"] for item in ledgers["locators"])),
        "treatment_recall": dict(Counter(item.get("status") or "not_measured" for item in ledgers["treatments"])),
        "not_measured_locators": len(locator_not_measured),
        "not_measured_treatments": len(treatment_not_measured),
    }
    result["credit_mappings"] = {"strict_precision": {"supported": "1", "partially_supported": "0", "unsupported": "0"}, "treatment_recall": {"found": "1", "missed": "0"}}
    result["components"] = [
        {"component_id": "strict_locator_precision", "raw_numerator": decimal_text(Decimal(supported)), "raw_denominator": decimal_text(Decimal(len(measured_locators))), "normalized_value": decimal_text(p), "weight": "harmonic_mean", "effective_weight": "harmonic_mean", "weight_renormalized": False},
        {"component_id": "expected_treatment_recall", "raw_numerator": decimal_text(Decimal(found)), "raw_denominator": decimal_text(Decimal(len(measured_treatments))), "normalized_value": decimal_text(r), "weight": "harmonic_mean", "effective_weight": "harmonic_mean", "weight_renormalized": False},
        {"component_id": "high_value_treatment_recall_safeguard", "raw_numerator": decimal_text(Decimal(high_found)), "raw_denominator": decimal_text(Decimal(len(high_measured))), "normalized_value": decimal_text(rate(high_found, len(high_measured))), "weight": "cap_only", "effective_weight": "cap_only", "weight_renormalized": False},
    ]
    return result


def mean_credit(values: Sequence[Decimal]) -> Decimal:
    return sum(values, ZERO) / Decimal(len(values)) if values else ZERO


def task_component(
    ledgers: dict[str, Any],
) -> tuple[Decimal, Decimal, Decimal, dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    coverage = {item["subject_id"]: item.get("coverage") for item in ledgers["subjects"]}
    fixed: list[Decimal] = []
    eligible_records: list[dict[str, Any]] = []
    coverage_uncertain: list[dict[str, Any]] = []
    result_uninspectable: list[dict[str, Any]] = []
    result_not_measured: list[dict[str, Any]] = []
    coverage_excluded = 0
    for task in ledgers["tasks"]:
        required_subjects = task.get("subject_ids", [])
        statuses = [coverage.get(subject_id, "not_measured") for subject_id in required_subjects]
        if any(status == "missing" for status in statuses):
            coverage_excluded += 1
            continue
        if any(status in {"uninspectable", "not_measured", None} for status in statuses):
            result = task.get("result")
            measured_credit = TASK_CREDIT.get(result)
            coverage_uncertain.append({
                **task,
                "_lower_credit": measured_credit if measured_credit is not None else ZERO,
                "_upper_credit": measured_credit if measured_credit is not None else ONE,
                "_lower_failure": result == "fails" or measured_credit is None,
                "_upper_failure": result == "fails",
            })
            continue
        result = task.get("result")
        if result in TASK_CREDIT:
            fixed.append(TASK_CREDIT[result])
            eligible_records.append(task)
        elif result == "uninspectable":
            result_uninspectable.append(task)
        else:
            result_not_measured.append(task)
    expected_not_measured = len(ledgers["task_not_measured"])
    central = mean_credit(fixed)
    fixed_failure_ids = [item["task_id"] for item in eligible_records if item.get("result") == "fails"]
    known_result_unknown_ids = [item["task_id"] for item in result_uninspectable + result_not_measured]

    def optimize_optional_eligibility(
        mandatory_values: Sequence[Decimal],
        mandatory_failure_ids: Sequence[str],
        optional: Sequence[tuple[Decimal, str, bool]],
        *,
        minimize: bool,
        scenario: str,
    ) -> dict[str, Any]:
        values = list(mandatory_values)
        failure_ids = list(mandatory_failure_ids)
        selected_optional_ids: list[str] = []
        ordered = sorted(optional, key=lambda item: (item[0], item[1]), reverse=not minimize)
        for credit, task_id, failure in ordered:
            current = mean_credit(values)
            include = credit < current or (credit == current and failure) if minimize else credit > current or (credit == current and not failure)
            if include:
                values.append(credit)
                selected_optional_ids.append(task_id)
                if failure:
                    failure_ids.append(task_id)
        return {
            "scenario": scenario,
            "value": mean_credit(values),
            "total": len(values),
            "failure_ids": failure_ids,
            "coverage_uncertain_included_ids": selected_optional_ids,
        }

    lower_scenario = optimize_optional_eligibility(
        fixed + [ZERO] * (len(result_uninspectable) + len(result_not_measured) + expected_not_measured),
        fixed_failure_ids + known_result_unknown_ids + ledgers["task_not_measured"],
        [(item["_lower_credit"], item["task_id"], item["_lower_failure"]) for item in coverage_uncertain],
        minimize=True,
        scenario="adverse_coverage_eligibility_and_task_credit",
    )
    upper_scenario = optimize_optional_eligibility(
        fixed + [ONE] * (len(result_uninspectable) + len(result_not_measured) + expected_not_measured),
        fixed_failure_ids,
        [(item["_upper_credit"], item["task_id"], item["_upper_failure"]) for item in coverage_uncertain],
        minimize=False,
        scenario="favorable_coverage_eligibility_and_task_credit",
    )
    lower = lower_scenario["value"]
    upper = upper_scenario["value"]
    original = ledgers["task_original"]
    not_measured = expected_not_measured + len(result_not_measured)
    uninspectable = len(coverage_uncertain) + len(result_uninspectable)
    applicable = len(eligible_records) + uninspectable + not_measured
    denominator = component_denominators(
        "coverage_conditioned_reader_tasks",
        original,
        applicable,
        len(eligible_records),
        uninspectable,
        not_measured,
        {"excluded_due_to_missing_access": coverage_excluded},
    )
    bound_counts = {
        "coverage_uncertain": coverage_uncertain,
        "result_uninspectable": result_uninspectable,
        "result_not_measured": result_not_measured,
        "expected_not_measured": expected_not_measured,
        "lower_scenario": lower_scenario["scenario"],
        "lower_total": lower_scenario["total"],
        "lower_failures": len(lower_scenario["failure_ids"]),
        "lower_failure_evidence": lower_scenario["failure_ids"],
        "lower_coverage_uncertain_included_ids": lower_scenario["coverage_uncertain_included_ids"],
        "upper_scenario": upper_scenario["scenario"],
        "upper_total": upper_scenario["total"],
        "upper_failures": len(upper_scenario["failure_ids"]),
        "upper_failure_evidence": upper_scenario["failure_ids"],
        "upper_coverage_uncertain_included_ids": upper_scenario["coverage_uncertain_included_ids"],
    }
    return central, lower, upper, denominator, eligible_records, bound_counts


def reference_rate_caps(unsupported: int, denominator: int, evidence_ids: list[str]) -> list[dict[str, Any]]:
    value = rate(unsupported, denominator)
    return [
        cap_record("findability.reference_unsupported_10_percent", Decimal(4), unsupported >= 2 and value >= Decimal("0.10"), {"minimum_count": 2, "operator": ">=", "rate": "0.10"}, {"unsupported": unsupported, "denominator": denominator, "rate": decimal_text(value)}, evidence_ids),
        cap_record("findability.reference_unsupported_25_percent", Decimal(3), unsupported >= 2 and value >= Decimal("0.25"), {"minimum_count": 2, "operator": ">=", "rate": "0.25"}, {"unsupported": unsupported, "denominator": denominator, "rate": decimal_text(value)}, evidence_ids),
        cap_record("findability.reference_unsupported_50_percent", Decimal(2), unsupported >= 3 and value >= Decimal("0.50"), {"minimum_count": 3, "operator": ">=", "rate": "0.50"}, {"unsupported": unsupported, "denominator": denominator, "rate": decimal_text(value)}, evidence_ids),
    ]


def task_failure_caps(failures: int, denominator: int, evidence_ids: Sequence[str]) -> list[dict[str, Any]]:
    value = rate(failures, denominator)
    return [
        cap_record("findability.task_failure_10_percent", Decimal(4), denominator > 0 and value >= Decimal("0.10"), {"operator": ">=", "rate": "0.10"}, {"failures": failures, "eligible_tasks": denominator, "rate": decimal_text(value)}, evidence_ids),
        cap_record("findability.task_failure_25_percent", Decimal(3), denominator > 0 and value >= Decimal("0.25"), {"operator": ">=", "rate": "0.25"}, {"failures": failures, "eligible_tasks": denominator, "rate": decimal_text(value)}, evidence_ids),
        cap_record("findability.task_failure_50_percent", Decimal(2), denominator > 0 and value >= Decimal("0.50"), {"operator": ">=", "rate": "0.50"}, {"failures": failures, "eligible_tasks": denominator, "rate": decimal_text(value)}, evidence_ids),
    ]


def calculate_findability(ledgers: dict[str, Any], audit_mode: str) -> dict[str, Any]:
    task_central, task_lower, task_upper, task_denom, eligible_tasks, task_bounds = task_component(ledgers)
    architecture, arch_unknown, _, arch_not_measured, arch_denom = node_component(ledgers, "heading_access_architecture", NODE_CREDIT, "heading_access_architecture")
    arch_credit = sum((NODE_CREDIT[item["_status"]] for item in architecture), ZERO)
    arch_central = arch_credit / Decimal(len(architecture)) if architecture else ZERO
    arch_applicable = len(architecture) + len(arch_unknown) + len(arch_not_measured)
    arch_lower = arch_credit / Decimal(arch_applicable) if arch_applicable else ZERO
    arch_upper = (arch_credit + Decimal(len(arch_unknown) + len(arch_not_measured))) / Decimal(arch_applicable) if arch_applicable else ZERO

    ref_context = ledgers["context"]["cross_reference_applicability"]
    refs_measured = [item for item in ledgers["references"] if item.get("judgment") in REFERENCE_CREDIT]
    refs_unknown = [item for item in ledgers["references"] if item.get("judgment") == "uninspectable"]
    refs_explicit_not_measured = [item for item in ledgers["references"] if item.get("judgment") == "not_measured"]
    refs_not_measured = ledgers["reference_not_measured"] + [item["reference_id"] for item in refs_explicit_not_measured]
    ref_inapplicable = ref_context["status"] == "inapplicable"
    if ref_inapplicable:
        ref_denom = component_denominators("cross_reference_validity", ledgers["reference_original"], 0, 0, 0, 0, {"genuinely_inapplicable": ledgers["reference_original"]}, inapplicable=True)
        ref_central = ref_lower = ref_upper = ZERO
        ref_raw_numerator = ref_raw_denominator = None
        weights = (Decimal("0.6666666666666666666666666667"), Decimal("0.3333333333333333333333333333"), ZERO)
    else:
        ref_applicable_count = len(refs_measured) + len(refs_unknown) + len(refs_not_measured)
        # Every frozen warranted-but-undelivered route is a measured zero, including
        # when the candidate also delivered other cross-references.
        obligation_zeros = ref_context["warranted_reference_obligation_count"]
        # With no delivered or warranted route, each structured reference defect is
        # itself applicable adverse evidence; it cannot create an undefined component.
        defect_zeros = len(ref_context["reference_defect_ids"]) if ledgers["reference_original"] == 0 and obligation_zeros == 0 else 0
        adverse_zeros = obligation_zeros + defect_zeros
        ref_applicable_count += adverse_zeros
        reference_original = ledgers["reference_original"] + adverse_zeros
        ref_denom = component_denominators("cross_reference_validity", reference_original, ref_applicable_count, len(refs_measured) + adverse_zeros, len(refs_unknown), len(refs_not_measured), {"not_reference_applicable": reference_original - ref_applicable_count})
        ref_credit = sum((REFERENCE_CREDIT[item["judgment"]] for item in refs_measured), ZERO)
        ref_raw_numerator = ref_credit
        ref_raw_denominator = Decimal(len(refs_measured) + adverse_zeros)
        ref_central = ref_credit / Decimal(len(refs_measured) + adverse_zeros) if len(refs_measured) + adverse_zeros else ZERO
        ref_lower = ref_credit / Decimal(ref_applicable_count) if ref_applicable_count else ZERO
        ref_upper = (ref_credit + Decimal(len(refs_unknown) + len(refs_not_measured))) / Decimal(ref_applicable_count) if ref_applicable_count else ZERO
        weights = (Decimal("0.60"), Decimal("0.30"), Decimal("0.10"))
    attempt = ledgers["context"]["candidate_attempt"]["status"]
    if attempt in {"empty", "structurally_incomplete", "unparseable"}:
        central_base = lower_base = upper_base = ZERO
        for component in (task_denom, arch_denom, ref_denom):
            mark_defined_zero(component, f"candidate_attempt:{attempt}", non_attempt=True)
    else:
        central_base = FIVE * (weights[0] * task_central + weights[1] * arch_central + weights[2] * ref_central)
        lower_base = FIVE * (weights[0] * task_lower + weights[1] * arch_lower + weights[2] * ref_lower)
        upper_base = FIVE * (weights[0] * task_upper + weights[1] * arch_upper + weights[2] * ref_upper)
    nav_critical = defect_subset(ledgers, "findability_navigation", severities={"critical"})
    nav_major = defect_subset(ledgers, "findability_navigation", severities={"major"})
    destructive = [item for item in nav_major if item.get("defect_kind") in {"substitutive_see", "circular_or_chained_reference", "misleading_access_route"} and item.get("high_priority_access_destroyed")]
    eligible_failures = [item for item in eligible_tasks if item.get("result") == "fails"]
    arch_major_fail = [item for item in architecture if item["_status"] in {"major_issues", "fails"}]
    unsupported_refs = [item for item in refs_measured if item.get("judgment") == "unsupported"]

    def caps(
        task_failures: int,
        task_total: int,
        architecture_bad: int,
        architecture_total: int,
        ref_bad: int,
        ref_total: int,
        task_evidence: Sequence[str],
        architecture_evidence: Sequence[str],
        reference_evidence: Sequence[str],
    ) -> list[dict[str, Any]]:
        return [
            cap_record("findability.critical_navigation", Decimal(2), bool(nav_critical), {"severity": "critical"}, {"defect_count": len(nav_critical)}, [item["defect_id"] for item in nav_critical]),
            cap_record("findability.localized_major_navigation", Decimal("4.5"), bool(nav_major), {"severity": "major"}, {"defect_count": len(nav_major)}, [item["defect_id"] for item in nav_major]),
            cap_record("findability.destructive_access_route", Decimal("3.5"), bool(destructive), {"severity": "major", "high_priority_access_destroyed": True}, {"defect_count": len(destructive)}, [item["defect_id"] for item in destructive]),
            *task_failure_caps(task_failures, task_total, task_evidence),
            *prevalence_caps("findability.architecture", architecture_bad, architecture_total, list(architecture_evidence), ((Decimal("0.05"), Decimal(4)), (Decimal("0.15"), Decimal(3)), (Decimal("0.30"), Decimal(2)))),
            *reference_rate_caps(ref_bad, ref_total, list(reference_evidence)),
        ]

    arch_unknown_count = len(arch_unknown) + len(arch_not_measured)
    ref_unknown_count = len(refs_unknown) + len(refs_not_measured)
    central_task_evidence = [item["task_id"] for item in eligible_failures]
    lower_task_evidence = task_bounds["lower_failure_evidence"]
    upper_task_evidence = task_bounds["upper_failure_evidence"]
    central_arch_evidence = [item["node_id"] for item in arch_major_fail]
    lower_arch_evidence = central_arch_evidence + [item["node_id"] for item in arch_unknown] + arch_not_measured
    central_ref_evidence = [item["reference_id"] for item in unsupported_refs]
    lower_ref_evidence = central_ref_evidence + [item["reference_id"] for item in refs_unknown] + refs_not_measured
    central_caps = caps(len(eligible_failures), len(eligible_tasks), len(arch_major_fail), len(architecture), len(unsupported_refs), len(refs_measured), central_task_evidence, central_arch_evidence, central_ref_evidence)
    lower_caps = caps(task_bounds["lower_failures"], task_bounds["lower_total"], len(arch_major_fail) + arch_unknown_count, len(architecture) + arch_unknown_count, len(unsupported_refs) + ref_unknown_count, len(refs_measured) + ref_unknown_count, lower_task_evidence, lower_arch_evidence, lower_ref_evidence)
    upper_caps = caps(task_bounds["upper_failures"], task_bounds["upper_total"], len(arch_major_fail), len(architecture) + arch_unknown_count, len(unsupported_refs), len(refs_measured) + ref_unknown_count, upper_task_evidence, central_arch_evidence, central_ref_evidence)
    result = finish_dimension("findability_navigation", [task_denom, arch_denom, ref_denom], central_base, lower_base, upper_base, central_caps, lower_caps, upper_caps, audit_mode)
    result["input_roles"] = ["missing_access_audit", "structure_audit_or_migration_supplement"]
    result["raw_status_counts"] = {
        "tasks": dict(Counter(item.get("result") for item in ledgers["tasks"])),
        "tasks_excluded_due_to_coverage": task_denom["exclusion_reasons"].get("excluded_due_to_missing_access", 0),
        "architecture": dict(Counter(item["_status"] for item in architecture)) | {"uninspectable": len(arch_unknown), "not_measured": len(arch_not_measured)},
        "cross_references": dict(Counter(item.get("judgment") for item in ledgers["references"])) | {"warranted_undelivered_zero": 0 if ref_inapplicable else obligation_zeros, "reference_defect_zero": 0 if ref_inapplicable else defect_zeros},
    }
    result["credit_mappings"] = {
        "tasks": {key: decimal_text(value) for key, value in TASK_CREDIT.items()},
        "architecture": {key: decimal_text(value) for key, value in NODE_CREDIT.items()},
        "cross_references": {key: decimal_text(value) for key, value in REFERENCE_CREDIT.items()} | {"warranted_undelivered": "0", "reference_defect_without_delivered_or_warranted_route": "0"},
    }
    result["components"] = [
        {"component_id": "coverage_conditioned_reader_tasks", "raw_numerator": decimal_text(sum((TASK_CREDIT[item["result"]] for item in eligible_tasks), ZERO)), "raw_denominator": decimal_text(Decimal(len(eligible_tasks))), "normalized_value": decimal_text(task_central), "weight": "0.60", "effective_weight": decimal_text(weights[0]), "weight_renormalized": ref_inapplicable, "label": "navigation success among subjects having at least partial access", "details": {"lower_bound_scenario": task_bounds["lower_scenario"], "upper_bound_scenario": task_bounds["upper_scenario"]}},
        {"component_id": "heading_access_architecture", "raw_numerator": decimal_text(arch_credit), "raw_denominator": decimal_text(Decimal(len(architecture))), "normalized_value": decimal_text(arch_central), "weight": "0.30", "effective_weight": decimal_text(weights[1]), "weight_renormalized": ref_inapplicable},
        {"component_id": "cross_reference_validity", "raw_numerator": decimal_text(ref_raw_numerator), "raw_denominator": decimal_text(ref_raw_denominator), "normalized_value": None if ref_inapplicable else decimal_text(ref_central), "weight": "0.10", "effective_weight": decimal_text(weights[2]), "weight_renormalized": ref_inapplicable, "details": {"warranted_undelivered_zero_count": 0 if ref_inapplicable else obligation_zeros, "reference_defect_zero_count": 0 if ref_inapplicable else defect_zeros}},
    ]
    return result


def mechanics_pattern_caps(ledgers: dict[str, Any]) -> list[dict[str, Any]]:
    families: dict[str, dict[str, Any]] = defaultdict(lambda: {"items": set(), "structural_sections": set(), "defects": []})
    for defect in defect_subset(ledgers, "mechanics_consistency", severities={"major"}):
        family = families[defect["root_cause_family"]]
        family["items"].update(item for item in defect["affected_item_ids"] if item.startswith("NODE-"))
        family["structural_sections"].update(defect["affected_structural_sections"])
        family["defects"].append(defect["defect_id"])
    node_total = max(1, ledgers["node_original"])
    records: list[dict[str, Any]] = []
    for family_id in sorted(families):
        family = families[family_id]
        count = len(family["items"])
        item_rate = rate(count, node_total)
        defect_records = [item for item in ledgers["defects"] if item["defect_id"] in family["defects"]]
        section_denominator = max((item["structural_section_denominator"] for item in defect_records), default=0)
        section_rate = rate(len(family["structural_sections"]), section_denominator)
        recurrent = count >= 3 and (item_rate >= Decimal("0.01") or len(family["structural_sections"]) >= 2)
        systematic = count >= 3 and (item_rate >= Decimal("0.10") or section_rate >= Decimal("0.50"))
        observed = {"root_cause_family": family_id, "affected_count": count, "node_denominator": node_total, "affected_rate": decimal_text(item_rate), "affected_structural_sections": len(family["structural_sections"]), "structural_section_denominator": section_denominator, "structural_section_rate": decimal_text(section_rate)}
        records.append(cap_record(f"mechanics.recurrent_major.{family_id}", Decimal(4), recurrent, {"minimum_count": 3, "any_of": [{"item_rate": ">=0.01"}, {"structural_sections": ">=2"}]}, observed, family["defects"]))
        records.append(cap_record(f"mechanics.systematic_major.{family_id}", Decimal(3), systematic, {"minimum_count": 3, "any_of": [{"item_rate": ">=0.10"}, {"structural_section_rate": ">=0.50"}]}, observed, family["defects"]))
    if not records:
        records.extend([
            cap_record("mechanics.recurrent_major.none", Decimal(4), False, {"minimum_count": 3, "any_of": [{"item_rate": ">=0.01"}, {"structural_sections": ">=2"}]}, {"root_cause_family_count": 0}),
            cap_record("mechanics.systematic_major.none", Decimal(3), False, {"minimum_count": 3, "any_of": [{"item_rate": ">=0.10"}, {"structural_section_rate": ">=0.50"}]}, {"root_cause_family_count": 0}),
        ])
    return records


def mechanics_aggregate_caps(affected: int, denominator: int, evidence_ids: Sequence[str]) -> list[dict[str, Any]]:
    affected_rate = rate(affected, denominator)
    observed = {"affected_count": affected, "node_denominator": denominator, "rate": decimal_text(affected_rate)}
    return [
        cap_record("mechanics.aggregate_cosmetic_minor_5_percent", Decimal("4.5"), denominator > 0 and affected_rate >= Decimal("0.05"), {"operator": ">=", "rate": "0.05"}, observed, evidence_ids),
        cap_record("mechanics.aggregate_cosmetic_minor_20_percent", Decimal(4), denominator > 0 and affected_rate >= Decimal("0.20"), {"operator": ">=", "rate": "0.20"}, observed, evidence_ids),
    ]


def calculate_mechanics(ledgers: dict[str, Any], audit_mode: str) -> dict[str, Any]:
    measured, uninspectable, _, not_measured_ids, denominator = node_component(ledgers, "mechanics_consistency", MECHANICS_CREDIT, "mechanics_nodes")
    credit = sum((MECHANICS_CREDIT[item["_status"]] for item in measured), ZERO)
    central_base = FIVE * credit / Decimal(len(measured)) if measured else ZERO
    unknown = len(uninspectable) + len(not_measured_ids)
    applicable = len(measured) + unknown
    lower_base = FIVE * credit / Decimal(applicable) if applicable else ZERO
    upper_base = FIVE * (credit + Decimal(unknown)) / Decimal(applicable) if applicable else ZERO
    attempt = ledgers["context"]["candidate_attempt"]["status"]
    if attempt in {"empty", "structurally_incomplete", "unparseable"}:
        central_base = lower_base = upper_base = ZERO
        mark_defined_zero(denominator, f"candidate_attempt:{attempt}", non_attempt=True)
    major_fail_nodes = [item for item in measured if item["_status"] in {"major_issues", "fails"}]
    for node_record in major_fail_nodes:
        require_node_defect_binding(node_record, ledgers, "mechanics_consistency", "mechanics")
    for structured_defect in defect_subset(ledgers, "mechanics_consistency"):
        require(
            all(item.startswith("NODE-") or item == "GLOBAL-STRUCTURE" for item in structured_defect["affected_item_ids"]),
            "invalid_mechanics_defect_attachment",
            f"Mechanics defect {structured_defect['defect_id']} must attach to NODE-* IDs or GLOBAL-STRUCTURE.",
        )
    critical = defect_subset(ledgers, "mechanics_consistency", severities={"critical"})
    major = defect_subset(ledgers, "mechanics_consistency", severities={"major"})
    aggregate = [item for item in measured if item["_status"] in {"cosmetic_issues", "minor_issues"}]

    def caps(aggregate_count: int, total: int) -> list[dict[str, Any]]:
        return [
            cap_record("mechanics.structurally_incomplete_or_unparseable", ZERO, attempt in {"structurally_incomplete", "unparseable"}, {"candidate_attempt_status": ["structurally_incomplete", "unparseable"]}, {"candidate_attempt_status": attempt}, ledgers["context"]["candidate_attempt"]["evidence_ids"]),
            cap_record("mechanics.critical_defect", Decimal(2), bool(critical), {"severity": "critical"}, {"defect_count": len(critical)}, [item["defect_id"] for item in critical]),
            cap_record("mechanics.localized_major", Decimal("4.5"), bool(major), {"severity": "major"}, {"defect_count": len(major)}, [item["defect_id"] for item in major]),
            *mechanics_pattern_caps(ledgers),
            *mechanics_aggregate_caps(aggregate_count, total, [item["node_id"] for item in aggregate]),
        ]

    central_caps = caps(len(aggregate), len(measured))
    lower_caps = caps(len(aggregate), applicable)
    upper_caps = caps(len(aggregate), applicable)
    result = finish_dimension("mechanics_consistency", [denominator], central_base, lower_base, upper_base, central_caps, lower_caps, upper_caps, audit_mode)
    result["input_roles"] = ["structure_audit", "structure_audit_or_migration_supplement"]
    result["raw_status_counts"] = dict(Counter(item["_status"] for item in measured)) | {"uninspectable": len(uninspectable), "not_measured": len(not_measured_ids)}
    result["credit_mappings"] = {"node_status": {key: decimal_text(value) for key, value in MECHANICS_CREDIT.items()}}
    result["components"] = [{"component_id": "mechanics_nodes", "raw_numerator": decimal_text(credit), "raw_denominator": decimal_text(Decimal(len(measured))), "normalized_value": decimal_text(central_base / FIVE if FIVE else ZERO), "weight": "1", "effective_weight": "1", "weight_renormalized": False}]
    return result


def preflight_loaded(loaded: dict[str, Any]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    missing: list[dict[str, Any]] = []
    manifest_missing = loaded.get("chunk_manifest") is None
    if manifest_missing:
        missing.append({
            "code": "canonical_chunk_manifest_required",
            "path": "inputs.chunk_manifest",
            "message": "The canonical user-approved chunk manifest is required to prove the complete approved source-unit set.",
        })
    try:
        validate_ledger_set_integrity(loaded, require_chunk_manifest=not manifest_missing)
    except CalculationError as exc:
        missing.append({"code": exc.code, "path": None, "message": exc.message, "details": exc.details})
    if loaded["structure"].get("schema_version") == "structure-audit-v3" and loaded.get("supplement") is None:
        missing.append({
            "code": "migration_supplement_required",
            "path": "inputs.migration_supplement",
            "message": "Historical structure-audit-v3 requires a hash-bound supplement; the historical audit itself must remain byte-identical.",
            "required_fields": [
                "audit_mode",
                "historical_locator_audit_set_sha256",
                "historical_missing_access_audit_set_sha256",
                "locator_audit_set_sha256",
                "missing_access_audit_set_sha256",
                "audit_set_reconciliation_basis",
                "scoring_context.candidate_attempt",
                "scoring_context.cross_reference_applicability",
                "scoring_context.cross_reference_applicability.warranted_reference_obligation_ids",
                "scoring_context.optional_subject_scoring",
                "scoring_context.node_component_applicability",
                "scoring_context.defects[].dimension_owner",
                "scoring_context.defects[].severity_basis",
                "scoring_context.defects[].retrieval_consequence",
                "scoring_context.defects[].affected_item_ids",
                "scoring_context.defects[].affected_source_sections",
                "scoring_context.defects[].affected_structural_sections",
                "scoring_context.defects[].root_cause_family",
                "scoring_context.defects[].affected_count",
                "scoring_context.defects[].applicable_count",
                "scoring_context.defects[].affected_rate",
                "scoring_context.defects[].source_section_denominator",
                "scoring_context.defects[].source_section_rate",
                "scoring_context.defects[].structural_section_denominator",
                "scoring_context.defects[].structural_section_rate",
            ],
        })
    if missing:
        return None, missing
    try:
        ledgers = collect_ledgers(loaded)
    except CalculationError as exc:
        missing.append({"code": exc.code, "path": None, "message": exc.message, "details": exc.details})
        return None, missing
    structure = ledgers["structure"]
    density = structure.get("density", {}) if isinstance(structure.get("density"), dict) else {}
    chapters = density.get("chapter_measurements")
    if not isinstance(chapters, list) or not chapters:
        missing.append({"code": "density_inputs_missing", "path": "structure_audit.density.chapter_measurements", "message": "Raw chapter density measurements are required."})
    else:
        for index, chapter in enumerate(chapters):
            for field in ("indexable_source_words", "locator_bearing_heading_paths", "locator_occurrences"):
                if not isinstance(chapter.get(field), int):
                    missing.append({"code": "density_inputs_missing", "path": f"structure_audit.density.chapter_measurements[{index}].{field}", "message": "Raw integer density input is required."})
    audit_mode = loaded["config"]["audit_mode"]
    if audit_mode == "full":
        for field in ("locator_not_measured", "subject_not_measured", "task_not_measured", "treatment_not_measured", "node_not_measured", "reference_not_measured"):
            if ledgers[field]:
                missing.append({"code": "incomplete_full_audit", "path": field, "message": "Full mode cannot score required not-measured items.", "item_ids": ledgers[field]})
        for node in ledgers["nodes"]:
            for component_id in ("conceptual_stance_fidelity", "heading_access_architecture", "mechanics_consistency"):
                status = node.get("component_judgments", {}).get(component_id, {}).get("status")
                if status == "not_measured" or status is None:
                    missing.append({
                        "code": "incomplete_full_audit",
                        "path": f"structure_audit.node_judgments[{node.get('node_id')}].component_judgments.{component_id}",
                        "message": "Full mode cannot score a required not-measured node component.",
                        "item_ids": [node.get("node_id")],
                    })
        explicit_reference_ids = [item.get("reference_id") for item in ledgers["references"] if item.get("judgment") == "not_measured"]
        if explicit_reference_ids:
            missing.append({
                "code": "incomplete_full_audit",
                "path": "structure_audit.cross_reference_judgments",
                "message": "Full mode cannot score required not-measured cross-references.",
                "item_ids": explicit_reference_ids,
            })
        explicit_task_ids = [item.get("task_id") for item in ledgers["tasks"] if item.get("result") is None]
        if explicit_task_ids:
            missing.append({"code": "incomplete_full_audit", "path": "missing_access_audits.reader_task_results", "message": "Full mode cannot score reader-task records without a result.", "item_ids": explicit_task_ids})
        explicit_treatment_ids = [item.get("treatment_id") for item in ledgers["treatments"] if item.get("status") is None]
        if explicit_treatment_ids:
            missing.append({"code": "incomplete_full_audit", "path": "missing_access_audits.treatment_judgments", "message": "Full mode cannot score expected-treatment records without a status.", "item_ids": explicit_treatment_ids})
    return ledgers, missing


def calculate_loaded(loaded: dict[str, Any], *, allow_historical_migration: bool = False) -> dict[str, Any]:
    ledgers, missing = preflight_loaded(loaded)
    require(ledgers is not None and not missing, "migration_inputs_insufficient", "The frozen ledgers do not satisfy the V5 calculation contract.", missing)
    historical_structure = loaded.get("structure", {}).get("schema_version") == "structure-audit-v3"
    require(
        not historical_structure or allow_historical_migration,
        "score_only_migration_required",
        "Historical structure-audit-v3 inputs may be scored only through score-only-migration so the exact V4 result and gate outcomes remain bound.",
    )
    audit_mode = loaded["config"]["audit_mode"]
    dimensions = [
        calculate_coverage(ledgers, audit_mode),
        calculate_selectivity(ledgers, audit_mode),
        calculate_concept(ledgers, audit_mode),
        calculate_reliability(ledgers, audit_mode),
        calculate_findability(ledgers, audit_mode),
        calculate_mechanics(ledgers, audit_mode),
    ]
    for dimension in dimensions:
        selected: list[dict[str, Any]] = []
        for artifact in loaded["input_artifacts"]:
            role = artifact["role"]
            include = any(
                role == "chunk_manifest"
                or (requested == "locator_audit" and role.startswith("locator_audit["))
                or (requested == "missing_access_audit" and role.startswith("missing_access_audit["))
                or (requested == "structure_audit" and role == "structure_audit")
                or (requested == "structure_audit_or_migration_supplement" and role in {"structure_audit", "migration_supplement"})
                for requested in dimension["input_roles"]
            )
            if include and artifact not in selected:
                selected.append(artifact)
        require(bool(selected), "dimension_input_binding_failed", f"{dimension['dimension_id']} did not resolve any frozen input artifacts.")
        dimension["input_artifacts"] = selected
    all_scored = all(item["status"] == "scored" for item in dimensions)
    total = round_points(sum((decimal_value(item["awarded_points"]) for item in dimensions), ZERO)) if all_scored else None
    result = {
        "schema_version": CALCULATION_SCHEMA,
        "calculation_id": f"CALC-{canonical_hash({'evaluation_id': loaded['config']['evaluation_id'], 'audit_mode': audit_mode, 'rubric_version': RUBRIC_VERSION, 'calculation_profile': CALCULATION_PROFILE, 'inputs': loaded['input_artifacts']})[:12].upper()}",
        "evaluation_id": loaded["config"]["evaluation_id"],
        "rubric_version": RUBRIC_VERSION,
        "calculation_profile": CALCULATION_PROFILE,
        "audit_mode": audit_mode,
        "status": "scored" if all_scored else "not_scored_insufficient_evidence",
        "evidence_identity": {field: ledgers["identity"][field] for field in CALCULATION_EVIDENCE_IDENTITY_FIELDS},
        "input_artifacts": loaded["input_artifacts"],
        "diagnostic_item_grades": {
            "used_in_dimension_arithmetic": False,
            "policy": "separate_non_additive_display_layer",
            "expected_source_subjects": {
                "count": len(ledgers["expected_subject_ids"]),
                "id_set_sha256": canonical_hash({"ids": ledgers["expected_subject_ids"]}),
            },
        },
        "publication_readiness_gates": {"used_in_score_arithmetic": False, "policy": "separate_claim_restrictions"},
        "dimensions": dimensions,
        "total_score": displayed_number(total, Decimal("0.01")) if total is not None else None,
        "maximum_score": 100,
        "arithmetic_check": all_scored and total == sum((decimal_value(item["awarded_points"]) for item in dimensions), ZERO).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
    }
    result["calculation_sha256"] = canonical_hash(result, "calculation_sha256")
    return result


def command_preflight(args: argparse.Namespace) -> None:
    config_path = Path(args.input).resolve()
    try:
        loaded = load_inputs(config_path)
        _, missing = preflight_loaded(loaded)
        result = {
            "command": "migration-sufficiency-preflight",
            "ok": True,
            "evaluation_id": loaded["config"]["evaluation_id"],
            "target_rubric_version": RUBRIC_VERSION,
            "target_calculation_profile": CALCULATION_PROFILE,
            "sufficient": not missing,
            "input_artifacts": loaded["input_artifacts"],
            "missing_requirements": missing,
            "mutated_inputs": False,
        }
        if args.output:
            output_path = Path(args.output).resolve()
            protected_paths = {config_path, *loaded["input_paths"]}
            require(not aliases_existing_file(output_path, protected_paths), "output_aliases_frozen_input", "Preflight output must not overwrite or alias the input config or any frozen ledger.")
            write_json(output_path, result)
            result["artifact_written"] = str(output_path)
        emit(result)
    except CalculationError as exc:
        emit({"command": "migration-sufficiency-preflight", "ok": False, "error": {"code": exc.code, "message": exc.message, "details": exc.details}}, 1)


def command_calculate(args: argparse.Namespace) -> None:
    try:
        loaded = load_inputs(Path(args.input).resolve())
        result = calculate_loaded(loaded)
        validate_schema_document(result, "dimension-calculations.schema.json", "Generated V5 dimension calculations")
        if args.output:
            output_path = Path(args.output).resolve()
            protected_paths = {loaded["config_path"], *loaded["input_paths"]}
            require(not aliases_existing_file(output_path, protected_paths), "output_aliases_frozen_input", "Calculation output must not overwrite or alias the input config or any frozen ledger.")
            write_json(output_path, result)
            response = {"command": "calculate-v5-dimensions", "ok": True, "evaluation_id": result["evaluation_id"], "status": result["status"], "total_score": result["total_score"], "calculation_sha256": result["calculation_sha256"], "artifact_written": str(output_path)}
        else:
            response = result
            response = {"command": "calculate-v5-dimensions", "ok": True, **response}
        emit(response)
    except CalculationError as exc:
        emit({"command": "calculate-v5-dimensions", "ok": False, "error": {"code": exc.code, "message": exc.message, "details": exc.details}}, 1)


def exact_dimension_map(records: Any, label: str) -> dict[str, dict[str, Any]]:
    require(isinstance(records, list), "projection_mismatch", f"{label} must be an array.")
    mapped = {
        item.get("dimension_id"): item
        for item in records
        if isinstance(item, dict) and isinstance(item.get("dimension_id"), str)
    }
    require(
        len(records) == len(WEIGHTS)
        and len(mapped) == len(records)
        and set(mapped) == set(WEIGHTS),
        "projection_mismatch",
        f"{label} must contain every V5 dimension exactly once.",
        {"expected": sorted(WEIGHTS), "actual": sorted(str(item) for item in mapped)},
    )
    return mapped


def resolve_referenced_artifact(reference: Any, container_path: Path, *, label: str, allow_legacy_absolute: bool = False) -> Path:
    require(isinstance(reference, dict), "projection_binding_mismatch", f"{label} must be an object.")
    stored_path = reference.get("artifact_path")
    if allow_legacy_absolute:
        require(isinstance(stored_path, str) and stored_path, "projection_binding_mismatch", f"{label}.artifact_path is required.")
    else:
        require_portable_relative_path(stored_path, label=f"{label}.artifact_path")
    candidate = Path(stored_path)
    resolved = (candidate if allow_legacy_absolute and candidate.is_absolute() else container_path.parent / candidate).resolve()
    require(resolved.is_file(), "projection_binding_mismatch", f"{label}.artifact_path does not resolve to a file.", {"resolved": str(resolved)})
    actual_hash = sha256_file(resolved)
    require(reference.get("sha256") == actual_hash, "projection_binding_mismatch", f"{label}.sha256 does not match the referenced file bytes.", {"expected": actual_hash, "actual": reference.get("sha256")})
    return resolved


def require_bound_calculation(reference: Any, container_path: Path, calculation_path: Path, calculation_file_sha256: str, *, label: str) -> None:
    resolved = resolve_referenced_artifact(reference, container_path, label=label)
    same_file = resolved == calculation_path
    if not same_file and resolved.exists() and calculation_path.exists():
        try:
            same_file = os.path.samefile(resolved, calculation_path)
        except OSError:
            same_file = False
    require(same_file, "projection_binding_mismatch", f"{label} does not resolve to the supplied calculation artifact.", {"bound": str(resolved), "supplied": str(calculation_path)})
    require(reference.get("sha256") == calculation_file_sha256, "projection_binding_mismatch", f"{label}.sha256 does not match the calculation file bytes.", {"expected": calculation_file_sha256, "actual": reference.get("sha256")})


def validate_projection_artifacts(calculation_path: Path, evaluation_result_path: Path, web_report_path: Path | None = None) -> dict[str, Any]:
    calculation_path = calculation_path.resolve()
    evaluation_result_path = evaluation_result_path.resolve()
    calculation = load_json(calculation_path, "V5 dimension calculation")
    validate_schema_document(calculation, "dimension-calculations.schema.json", "V5 dimension calculation")
    require(
        calculation.get("calculation_sha256") == canonical_hash(calculation, "calculation_sha256"),
        "calculation_self_hash_mismatch",
        "The V5 dimension-calculation canonical hash does not reconstruct.",
    )
    calculation_file_sha256 = sha256_file(calculation_path)
    calculation_dimensions = exact_dimension_map(calculation.get("dimensions"), "dimension calculation")

    evaluation = load_json(evaluation_result_path, "V5 evaluation result")
    validate_schema_document(evaluation, "evaluation-result-v6.schema.json", "V5 evaluation result")
    require_bound_calculation(evaluation.get("dimension_calculations"), evaluation_result_path, calculation_path, calculation_file_sha256, label="dimension_calculations")
    require(evaluation.get("evaluation_id") == calculation.get("evaluation_id"), "projection_mismatch", "Evaluation-result and calculation evaluation IDs differ.")
    require(evaluation.get("provenance", {}).get("rubric_version") == calculation.get("rubric_version"), "projection_mismatch", "Evaluation-result rubric version differs from the calculation.")
    require(evaluation.get("provenance", {}).get("dimension_calculation_profile") == calculation.get("calculation_profile"), "projection_mismatch", "Evaluation-result calculation profile differs from the calculation.")
    require(evaluation.get("audit_scope", {}).get("mode") == calculation.get("audit_mode"), "projection_mismatch", "Evaluation-result audit mode differs from the calculation.")
    require(evaluation.get("total_score") == calculation.get("total_score"), "projection_mismatch", "Evaluation-result total score differs from the calculation.")
    require(evaluation.get("dimension_calculations", {}).get("schema_version") == calculation.get("schema_version"), "projection_mismatch", "Evaluation-result calculation schema version differs from the bound artifact.")
    require(evaluation.get("dimension_calculations", {}).get("calculation_profile") == calculation.get("calculation_profile"), "projection_mismatch", "Evaluation-result bound calculation profile differs from the calculation.")
    evidence_identity = calculation["evidence_identity"]
    evaluation_identity_projections = (
        ("candidate.sha256", evaluation.get("candidate", {}).get("sha256"), evidence_identity["candidate_sha256"]),
        ("provenance.source_sha256", evaluation.get("provenance", {}).get("source_sha256"), evidence_identity["source_sha256"]),
        ("provenance.benchmark_sha256", evaluation.get("provenance", {}).get("benchmark_sha256"), evidence_identity["benchmark_sha256"]),
        ("provenance.judgment_policy_sha256", evaluation.get("provenance", {}).get("judgment_policy_sha256"), evidence_identity["policy_sha256"]),
        ("comparison_key.source_sha256", evaluation.get("comparison_key", {}).get("source_sha256"), evidence_identity["source_sha256"]),
        ("comparison_key.benchmark_sha256", evaluation.get("comparison_key", {}).get("benchmark_sha256"), evidence_identity["benchmark_sha256"]),
        ("comparison_key.judgment_policy_sha256", evaluation.get("comparison_key", {}).get("judgment_policy_sha256"), evidence_identity["policy_sha256"]),
        ("comparison_key.page_map_sha256", evaluation.get("comparison_key", {}).get("page_map_sha256"), evidence_identity["page_map_sha256"]),
        ("comparison_key.chunk_manifest_sha256", evaluation.get("comparison_key", {}).get("chunk_manifest_sha256"), evidence_identity["chunk_manifest_sha256"]),
        ("comparison_key.audit_mode", evaluation.get("comparison_key", {}).get("audit_mode"), calculation["audit_mode"]),
        ("comparison_key.rubric_version", evaluation.get("comparison_key", {}).get("rubric_version"), calculation["rubric_version"]),
        ("comparison_key.dimension_calculation_profile", evaluation.get("comparison_key", {}).get("dimension_calculation_profile"), calculation["calculation_profile"]),
    )
    for field, actual, expected in evaluation_identity_projections:
        require(actual == expected, "projection_identity_mismatch", f"Evaluation-result {field} differs from the bound calculation evidence identity.", {"expected": expected, "actual": actual})

    item_reference = evaluation["item_assessments"]
    item_path = resolve_referenced_artifact(item_reference, evaluation_result_path, label="item_assessments")
    item_assessments = load_json(item_path, "Diagnostic item assessments")
    validate_schema_document(item_assessments, "item-assessments-v2.schema.json", "Projection-safe diagnostic item assessments")
    item_binding_checks = (
        ("schema_version", item_reference.get("schema_version"), item_assessments.get("schema_version")),
        ("grading_policy", item_reference.get("grading_policy"), item_assessments.get("grading_policy")),
        ("summary", item_reference.get("summary"), item_assessments.get("summary")),
        ("evaluation_id", item_assessments.get("evaluation_id"), calculation.get("evaluation_id")),
        ("candidate_sha256", item_assessments.get("candidate_sha256"), evidence_identity["candidate_sha256"]),
        ("item_inventory_sha256", item_assessments.get("item_inventory_sha256"), evidence_identity["item_inventory_file_sha256"]),
        ("audit_mode", item_assessments.get("audit_mode"), calculation.get("audit_mode")),
    )
    for field, actual, expected in item_binding_checks:
        require(actual == expected, "item_assessment_binding_mismatch", f"Item-assessment {field} differs from its result reference or bound calculation.", {"expected": expected, "actual": actual})
    for field in CALCULATION_EVIDENCE_IDENTITY_FIELDS:
        require(
            item_assessments.get("evidence_identity", {}).get(field) == evidence_identity[field],
            "item_assessment_binding_mismatch",
            f"Item-assessment evidence_identity.{field} differs from the exact calculation ledger identity.",
            {"expected": evidence_identity[field], "actual": item_assessments.get("evidence_identity", {}).get(field)},
        )
    inventory_reference = item_assessments["item_inventory_artifact"]
    inventory_path = resolve_referenced_artifact(inventory_reference, item_path, label="item_inventory_artifact")
    inventory = load_json(inventory_path, "Bound item inventory")
    validate_schema_document(inventory, "item-inventory-v2.schema.json", "Bound item inventory")
    require(inventory_reference.get("schema_version") == inventory.get("schema_version"), "item_assessment_binding_mismatch", "Item-assessment inventory schema reference differs from the bound file.")
    require(inventory.get("candidate_sha256") == evidence_identity["candidate_sha256"], "item_assessment_binding_mismatch", "Bound item inventory belongs to a different candidate.")
    require(inventory_reference.get("sha256") == evidence_identity["item_inventory_file_sha256"], "item_assessment_binding_mismatch", "Bound item inventory differs from the calculation identity.")

    item_families = {
        "locators": (inventory.get("locators", []), "locator_id", item_assessments.get("locator_assessments", [])),
        "paths": (inventory.get("paths", []), "path_id", item_assessments.get("path_assessments", [])),
        "heading_nodes": (inventory.get("heading_nodes", []), "node_id", item_assessments.get("heading_node_assessments", [])),
        "cross_references": (inventory.get("cross_references", []), "reference_id", item_assessments.get("cross_reference_assessments", [])),
    }
    completeness = item_assessments["assessment_completeness"]
    for family, (expected_records, id_field, assessed_records) in item_families.items():
        expected_ids = [item[id_field] for item in expected_records]
        assessed_ids = [item[id_field] for item in assessed_records]
        require(len(expected_ids) == len(set(expected_ids)), "item_assessment_completeness_mismatch", f"Bound inventory has duplicate {family} IDs.")
        require(len(assessed_ids) == len(set(assessed_ids)) and set(assessed_ids) == set(expected_ids), "item_assessment_completeness_mismatch", f"Item assessments do not exactly cover the bound {family} inventory.", {"missing": sorted(set(expected_ids) - set(assessed_ids)), "unexpected": sorted(set(assessed_ids) - set(expected_ids))})
        expected_completeness = {
            "expected": len(expected_ids),
            "assessed": len(assessed_ids),
            "unique": True,
            "complete": True,
            "id_set_sha256": canonical_hash({"ids": sorted(expected_ids)}),
        }
        require(completeness.get(family) == expected_completeness, "item_assessment_completeness_mismatch", f"Item-assessment completeness record for {family} does not reconstruct.", {"expected": expected_completeness, "actual": completeness.get(family)})
    subject_ids = [item["subject_id"] for item in item_assessments.get("source_subject_assessments", [])]
    subject_expectation = calculation["diagnostic_item_grades"]["expected_source_subjects"]
    expected_subject_completeness = {
        "expected": subject_expectation["count"],
        "assessed": len(subject_ids),
        "unique": True,
        "complete": True,
        "id_set_sha256": canonical_hash({"ids": sorted(subject_ids)}),
    }
    require(len(subject_ids) == len(set(subject_ids)), "item_assessment_completeness_mismatch", "Source-subject assessments contain duplicate IDs.")
    require(len(subject_ids) == subject_expectation["count"] and expected_subject_completeness["id_set_sha256"] == subject_expectation["id_set_sha256"], "item_assessment_completeness_mismatch", "Source-subject assessments do not exactly cover the calculation's frozen expected-subject set.", {"expected": subject_expectation, "actual": {"count": len(subject_ids), "id_set_sha256": expected_subject_completeness["id_set_sha256"]}})
    require(completeness.get("source_subjects") == expected_subject_completeness, "item_assessment_completeness_mismatch", "Source-subject completeness record does not reconstruct.", {"expected": expected_subject_completeness, "actual": completeness.get("source_subjects")})
    for family, assessed_records in (
        ("locators", item_assessments["locator_assessments"]),
        ("paths", item_assessments["path_assessments"]),
        ("heading_nodes", item_assessments["heading_node_assessments"]),
        ("cross_references", item_assessments["cross_reference_assessments"]),
        ("source_subjects", item_assessments["source_subject_assessments"]),
    ):
        summary = item_assessments.get("summary", {}).get(family)
        graded = sum(item.get("grade", {}).get("score") is not None for item in assessed_records)
        not_measured = len(assessed_records) - graded
        require(isinstance(summary, dict) and summary.get("total") == len(assessed_records) and summary.get("graded") == graded and summary.get("not_measured") == not_measured, "item_assessment_completeness_mismatch", f"Item-assessment summary for {family} does not reconstruct.")

    migration_context = calculation.get("migration_context")
    migration_reference = evaluation.get("score_migration")
    migration: dict[str, Any] | None = None
    migration_path: Path | None = None
    if migration_context is None:
        require(migration_reference is None, "unexpected_score_migration", "A native V5 calculation must not claim a V4-to-V5 score migration.")
    else:
        require(isinstance(migration_reference, dict), "score_migration_binding_required", "A migrated calculation requires a bound score-migration record in the V5 result.")
        migration_path = resolve_referenced_artifact(
            migration_reference,
            evaluation_result_path,
            label="score_migration",
            allow_legacy_absolute=migration_reference.get("schema_version") == "subject-index-score-migration-v1",
        )
        migration = validate_migration_record_for_calculation(calculation, calculation_path, migration_path)
        migration_checks = (
            ("schema_version", migration_reference.get("schema_version"), migration.get("schema_version")),
            ("migration_sha256", migration_reference.get("migration_sha256"), migration.get("migration_sha256")),
            ("evaluation_id", migration.get("evaluation_id"), calculation.get("evaluation_id")),
            ("historical_result_sha256", migration.get("from", {}).get("historical_result_sha256"), migration_context["historical_result_sha256"]),
            ("calculation_file_sha256", migration.get("to", {}).get("calculation_file_sha256"), calculation_file_sha256),
            ("calculation_canonical_sha256", migration.get("to", {}).get("calculation_canonical_sha256"), calculation.get("calculation_sha256")),
            ("historical_gate_outcomes_sha256", migration.get("gate_preservation", {}).get("historical_gate_outcomes_sha256"), migration_context["historical_gate_outcomes_sha256"]),
            ("preserved_gate_outcomes_sha256", migration.get("gate_preservation", {}).get("preserved_gate_outcomes_sha256"), migration_context["historical_gate_outcomes_sha256"]),
        )
        for field, actual, expected in migration_checks:
            require(actual == expected, "score_migration_binding_mismatch", f"Score-migration {field} differs from the bound calculation or result reference.", {"expected": expected, "actual": actual})
        projected_gate_hash = canonical_hash({"critical_gates": evaluation.get("critical_gates", [])})
        require(projected_gate_hash == migration_context["historical_gate_outcomes_sha256"], "gate_preservation_mismatch", "The migrated V5 result did not preserve historical critical gates byte-for-byte at the canonical JSON boundary.", {"expected": migration_context["historical_gate_outcomes_sha256"], "actual": projected_gate_hash})
    evaluation_dimensions = exact_dimension_map(evaluation.get("scorecard"), "evaluation-result scorecard")
    evaluation_projection = {
        "weight": "dimension_weight",
        "rating": "final_rating",
        "unrounded_rating": "unrounded_rating",
        "points": "awarded_points",
        "calculation_status": "status",
        "formula_id": "formula_id",
    }
    for dimension_id, source in calculation_dimensions.items():
        projected = evaluation_dimensions[dimension_id]
        for projected_field, source_field in evaluation_projection.items():
            require(projected.get(projected_field) == source.get(source_field), "projection_mismatch", f"Evaluation-result {dimension_id}.{projected_field} differs from the calculation.", {"expected": source.get(source_field), "actual": projected.get(projected_field)})
        expected_cap_id = source.get("applied_cap", {}).get("cap_id") if isinstance(source.get("applied_cap"), dict) else None
        require(projected.get("applied_cap_id") == expected_cap_id, "projection_mismatch", f"Evaluation-result {dimension_id}.applied_cap_id differs from the calculation.")

    validated = [str(evaluation_result_path)]
    if web_report_path is not None:
        web_report_path = web_report_path.resolve()
        report = load_json(web_report_path, "V5 web report")
        validate_schema_document(report, "web-report-v4.schema.json", "V5 web report")
        explainer = report.get("calculation_explainer")
        require_bound_calculation(explainer, web_report_path, calculation_path, calculation_file_sha256, label="calculation_explainer")
        require(explainer.get("rubric_version") == calculation.get("rubric_version"), "projection_mismatch", "Web-report rubric version differs from the calculation.")
        require(explainer.get("calculation_profile") == calculation.get("calculation_profile"), "projection_mismatch", "Web-report calculation profile differs from the calculation.")
        require(explainer.get("item_grades_used") is False and explainer.get("gates_used") is False, "projection_mismatch", "Web report must disclose that item grades and gates are excluded from score arithmetic.")
        require(report.get("grade", {}).get("score") == calculation.get("total_score"), "projection_mismatch", "Web-report headline score differs from the calculation.")
        require(report.get("grade", {}).get("maximum") == calculation.get("maximum_score"), "projection_mismatch", "Web-report maximum score differs from the calculation.")
        web_item_reference = report["item_grade_index"]
        web_item_path = resolve_referenced_artifact(web_item_reference, web_report_path, label="item_grade_index")
        same_item_file = web_item_path == item_path
        if not same_item_file:
            try:
                same_item_file = os.path.samefile(web_item_path, item_path)
            except OSError:
                same_item_file = False
        require(same_item_file, "item_assessment_binding_mismatch", "Evaluation result and web report must bind the same item-assessment artifact.")
        for field, expected in (
            ("schema_version", item_assessments["schema_version"]),
            ("grading_policy", item_assessments["grading_policy"]),
            ("summary", item_assessments["summary"]),
            ("color_legend", item_assessments["color_legend"]),
        ):
            require(web_item_reference.get(field) == expected, "item_assessment_binding_mismatch", f"Web-report item_grade_index.{field} differs from the bound item-assessment artifact.")
        gate_status = report["gate_status"]
        result_gate_hash = canonical_hash({"critical_gates": evaluation.get("critical_gates", [])})
        require(gate_status.get("critical_gates") == evaluation.get("critical_gates", []), "gate_projection_mismatch", "Web-report critical gates differ from the evaluation result.")
        require(gate_status.get("outcomes_sha256") == result_gate_hash, "gate_projection_mismatch", "Web-report gate-outcome hash differs from the evaluation result.")
        score_views = report["score_views"]
        views = score_views.get("views", [])
        view_ids = [item.get("view_id") for item in views]
        require(len(view_ids) == len(set(view_ids)), "score_view_mismatch", "Web-report score-view IDs must be unique.")
        primary_id = score_views.get("primary_view_id")
        primary_matches = [item for item in views if item.get("view_id") == primary_id]
        require(len(primary_matches) == 1, "score_view_mismatch", "Web-report primary_view_id must identify exactly one score view.")
        primary_view = primary_matches[0]
        require(primary_view.get("view_kind") == "observed", "score_view_mismatch", "The primary score view must be the observed result.")
        require(all(item is primary_view or item.get("view_kind") == "counterfactual" for item in views), "score_view_mismatch", "Every non-primary score view must be an explicit counterfactual.")
        require(primary_view.get("score") == calculation.get("total_score"), "score_view_mismatch", "The primary score view total differs from the canonical calculation.")
        primary_calculation_reference = primary_view.get("calculation")
        primary_calculation_path = resolve_referenced_artifact(primary_calculation_reference, web_report_path, label="score_views.primary.calculation")
        require_same_artifact(primary_calculation_path, calculation_path, label="The primary score-view calculation")
        require(primary_calculation_reference.get("calculation_sha256") == calculation.get("calculation_sha256"), "score_view_mismatch", "The primary score view canonical calculation hash differs.")
        for index, view in enumerate(views):
            view_calculation_reference = view.get("calculation")
            view_calculation_path = resolve_referenced_artifact(view_calculation_reference, web_report_path, label=f"score_views.views[{index}].calculation")
            view_calculation = load_json(view_calculation_path, f"Score-view calculation[{index}]")
            validate_schema_document(view_calculation, "dimension-calculations.schema.json", f"Score-view calculation[{index}]")
            require(view_calculation.get("calculation_sha256") == canonical_hash(view_calculation, "calculation_sha256"), "score_view_mismatch", f"Score-view calculation[{index}] canonical hash does not reconstruct.")
            require(view_calculation_reference.get("calculation_sha256") == view_calculation.get("calculation_sha256"), "score_view_mismatch", f"Score-view calculation[{index}] canonical hash differs from its reference.")
            require(view.get("score") == view_calculation.get("total_score"), "score_view_mismatch", f"Score-view calculation[{index}] total differs from the displayed view.")
            require(view_calculation.get("evaluation_id") == calculation.get("evaluation_id"), "score_view_mismatch", f"Score-view calculation[{index}] belongs to another evaluation.")
            for field in ("candidate_sha256", "source_sha256", "benchmark_sha256", "policy_sha256", "page_map_sha256", "chunk_manifest_sha256"):
                require(view_calculation.get("evidence_identity", {}).get(field) == evidence_identity[field], "score_view_mismatch", f"Score-view calculation[{index}] evidence_identity.{field} differs from the canonical view.")
            for provenance_index, provenance in enumerate(view.get("provenance_artifacts", [])):
                provenance_path = resolve_referenced_artifact(provenance, web_report_path, label=f"score_views.views[{index}].provenance_artifacts[{provenance_index}]")
                require(provenance.get("sha256") == sha256_file(provenance_path), "score_view_mismatch", "A score-view provenance artifact hash differs from its file.")

        migration_comparison = report["migration_comparison"]
        if migration_context is None:
            require(migration_comparison.get("status") == "not_applicable", "migration_projection_mismatch", "A native V5 web report must mark migration comparison not applicable.")
        else:
            require(isinstance(migration, dict) and migration_path is not None, "migration_projection_mismatch", "Migrated web validation requires the bound migration record.")
            require(migration_comparison.get("status") == "v4_to_v5", "migration_projection_mismatch", "A migrated V5 web report must expose its V4-to-V5 comparison.")
            comparison_reference = migration_comparison.get("migration_record")
            comparison_path = resolve_referenced_artifact(comparison_reference, web_report_path, label="migration_comparison.migration_record")
            require_same_artifact(comparison_path, migration_path, label="The web migration-comparison record")
            expected_gate_comparison = {
                "previous_outcomes_sha256": migration["gate_preservation"]["historical_gate_outcomes_sha256"],
                "migrated_outcomes_sha256": result_gate_hash,
                "previous_outcomes": json_compatible(migration["gate_preservation"]["historical_outcomes"]),
                "migrated_outcomes": json_compatible(evaluation.get("critical_gates", [])),
                "outcomes_equal": True,
            }
            comparison_checks = (
                ("migration_record.schema_version", comparison_reference.get("schema_version"), migration.get("schema_version")),
                ("migration_record.migration_sha256", comparison_reference.get("migration_sha256"), migration.get("migration_sha256")),
                ("methodology_commit", migration_comparison.get("methodology_commit"), migration.get("methodology", {}).get("commit_sha")),
                ("previous_total", migration_comparison.get("previous_total"), migration.get("from", {}).get("total_score")),
                ("migrated_total", migration_comparison.get("migrated_total"), migration.get("to", {}).get("total_score")),
                ("dimension_comparison", migration_comparison.get("dimension_comparison"), migration.get("dimension_comparison")),
                ("gate_comparison", migration_comparison.get("gate_comparison"), expected_gate_comparison),
            )
            for field, actual, expected in comparison_checks:
                require(actual == expected, "migration_projection_mismatch", f"Web-report migration comparison {field} differs from the migration record.", {"expected": expected, "actual": actual})
            adjustment = migration.get("representation_adjustment", {})
            expected_adjustment_status = "separate_evidentiary_correction" if adjustment.get("status") == "separate_evidentiary_correction" else "none"
            require(score_views.get("adjustment_status") == expected_adjustment_status, "score_view_mismatch", "Web-report score-view adjustment status differs from the migration record.")
            if adjustment.get("status") == "separate_evidentiary_correction":
                required_hashes = {item["sha256"] for item in adjustment.get("provenance_artifacts", [])}
                counterfactual_hashes = {
                    artifact["sha256"]
                    for view in views if view.get("view_kind") == "counterfactual"
                    for artifact in view.get("provenance_artifacts", [])
                }
                require(required_hashes <= counterfactual_hashes, "score_view_mismatch", "Counterfactual score views do not expose every representation-adjustment provenance artifact.", {"missing_sha256": sorted(required_hashes - counterfactual_hashes)})
        web_dimensions = exact_dimension_map(report.get("scorecard"), "web-report scorecard")
        web_projection = {
            "rating": "final_rating",
            "unrounded_rating": "unrounded_rating",
            "weight": "dimension_weight",
            "awarded_points": "awarded_points",
            "status": "status",
            "formula_id": "formula_id",
            "input_artifacts": "input_artifacts",
            "denominators": "denominators",
            "raw_status_counts": "raw_status_counts",
            "credit_mappings": "credit_mappings",
            "components": "components",
            "base_rating": "base_rating",
            "pre_cap_rating": "pre_cap_rating",
            "post_cap_rating": "post_cap_rating",
            "cap_evaluations": "cap_evaluations",
            "applied_cap": "applied_cap",
            "rounding": "rounding",
            "missing_data_bounds": "missing_data_bounds",
        }
        for dimension_id, source in calculation_dimensions.items():
            projected = web_dimensions[dimension_id]
            for projected_field, source_field in web_projection.items():
                require(projected.get(projected_field) == source.get(source_field), "projection_mismatch", f"Web-report {dimension_id}.{projected_field} differs from the calculation.", {"expected": source.get(source_field), "actual": projected.get(projected_field)})
        validated.append(str(web_report_path))
    return {
        "command": "validate-v5-projections",
        "ok": True,
        "calculation_path": str(calculation_path),
        "calculation_file_sha256": calculation_file_sha256,
        "calculation_canonical_sha256": calculation["calculation_sha256"],
        "validated_projections": validated,
    }


def migration_validation_receipt(
    calculation_path: Path,
    evaluation_result_path: Path,
    web_report_path: Path,
    output_path: Path,
    *,
    methodology_commit: str,
    validation_timestamp: str,
) -> dict[str, Any]:
    calculation_path = calculation_path.resolve()
    evaluation_result_path = evaluation_result_path.resolve()
    web_report_path = web_report_path.resolve()
    output_path = output_path.resolve()
    require_methodology_commit(methodology_commit)
    require_utc_timestamp(validation_timestamp, label="validation_timestamp")
    calculation = load_json(calculation_path, "V5 dimension calculation")
    evaluation = load_json(evaluation_result_path, "V5 evaluation result")
    report = load_json(web_report_path, "V5 web report")
    require(isinstance(calculation.get("migration_context"), dict), "migration_validation_requires_migration", "A migration-validation receipt requires a score-only migration calculation.")
    migration_path = resolve_referenced_artifact(evaluation.get("score_migration"), evaluation_result_path, label="score_migration")
    migration = validate_migration_record_for_calculation(calculation, calculation_path, migration_path)
    require(migration.get("schema_version") == MIGRATION_SCHEMA, "migration_validation_requires_v2", "A canonical migration-validation receipt requires a V2 migration record.")
    require(migration.get("methodology", {}).get("commit_sha") == methodology_commit, "migration_validation_methodology_mismatch", "Validation methodology commit differs from the migration record.")
    historical_path = resolve_stored_artifact_path(migration["from"]["historical_result_path"], migration_path, label="score_migration.from.historical_result_path")
    historical = load_json(historical_path, "Historical V4 evaluation result")
    historical_gates = json_compatible(historical.get("critical_gates", []))
    migrated_gates = json_compatible(evaluation.get("critical_gates", []))
    historical_gate_hash = canonical_hash({"critical_gates": historical.get("critical_gates", [])})
    migrated_gate_hash = canonical_hash({"critical_gates": evaluation.get("critical_gates", [])})
    require(historical_gate_hash == migrated_gate_hash and historical_gates == migrated_gates, "gate_preservation_mismatch", "Migration-validation receipt requires byte-identical canonical gate outcomes.")
    protected_paths = {calculation_path, evaluation_result_path, web_report_path, migration_path, historical_path}
    protected_paths.update(
        resolve_stored_artifact_path(lineage["path"], migration_path, label=f"score_migration.input_lineage.{lineage['role']}.path")
        for lineage in migration.get("input_lineage", [])
    )
    item_path = resolve_referenced_artifact(evaluation["item_assessments"], evaluation_result_path, label="item_assessments")
    protected_paths.add(item_path)
    item_assessments = load_json(item_path, "Diagnostic item assessments")
    protected_paths.add(resolve_referenced_artifact(item_assessments["item_inventory_artifact"], item_path, label="item_inventory_artifact"))
    for view_index, view in enumerate(report["score_views"]["views"]):
        protected_paths.add(resolve_referenced_artifact(view["calculation"], web_report_path, label=f"score_views.views[{view_index}].calculation"))
        protected_paths.update(
            resolve_referenced_artifact(provenance, web_report_path, label=f"score_views.views[{view_index}].provenance_artifacts[{provenance_index}]")
            for provenance_index, provenance in enumerate(view["provenance_artifacts"])
        )
    require(not aliases_existing_file(output_path, protected_paths), "output_aliases_frozen_input", "Migration-validation receipt must not overwrite or alias a bound artifact.")

    def artifact(path: Path, schema_version: str, *, canonical_sha256: str | None = None) -> dict[str, Any]:
        record = {
            "schema_version": schema_version,
            "path": portable_relative_reference(path, output_path, label=f"validation.artifacts.{schema_version}.path"),
            "sha256": sha256_file(path),
        }
        if canonical_sha256 is not None:
            record["canonical_sha256"] = canonical_sha256
        return record

    receipt = {
        "schema_version": MIGRATION_VALIDATION_SCHEMA,
        "validation_timestamp": validation_timestamp,
        "tool": {"name": TOOL_NAME, "version": TOOL_VERSION},
        "methodology": {"repository": METHODOLOGY_REPOSITORY, "commit_sha": methodology_commit},
        "evaluation_id": calculation["evaluation_id"],
        "artifacts": {
            "historical_result": artifact(historical_path, historical["schema_version"]),
            "dimension_calculations": artifact(calculation_path, calculation["schema_version"], canonical_sha256=calculation["calculation_sha256"]),
            "migration_record": artifact(migration_path, migration["schema_version"], canonical_sha256=migration["migration_sha256"]),
            "evaluation_result": artifact(evaluation_result_path, evaluation["schema_version"]),
            "web_report": artifact(web_report_path, report["schema_version"]),
        },
        "totals": json_compatible({
            "previous": migration["from"]["total_score"],
            "migrated": migration["to"]["total_score"],
            "delta": migration["total_delta"],
        }),
        "dimension_comparison": json_compatible(migration["dimension_comparison"]),
        "gate_comparison": {
            "historical_outcomes_sha256": historical_gate_hash,
            "migrated_outcomes_sha256": migrated_gate_hash,
            "historical_outcomes": historical_gates,
            "migrated_outcomes": migrated_gates,
            "outcomes_equal": True,
        },
        "score_views": json_compatible(report["score_views"]),
    }
    receipt["validation_sha256"] = canonical_hash(receipt, "validation_sha256")
    validate_schema_document(receipt, "score-migration-validation.schema.json", "Migration-validation receipt")
    write_json(output_path, receipt)
    return receipt


def command_validate_projections(args: argparse.Namespace) -> None:
    try:
        result = validate_projection_artifacts(
            Path(args.calculation),
            Path(args.evaluation_result),
            Path(args.web_report) if args.web_report else None,
        )
        if args.output:
            require(args.web_report, "migration_validation_requires_web_report", "Writing a migration-validation receipt requires --web-report.")
            require(args.methodology_commit, "migration_validation_methodology_required", "Writing a migration-validation receipt requires --methodology-commit.")
            require(args.validation_timestamp, "migration_validation_timestamp_required", "Writing a migration-validation receipt requires --validation-timestamp.")
            output_path = Path(args.output).resolve()
            receipt = migration_validation_receipt(
                Path(args.calculation),
                Path(args.evaluation_result),
                Path(args.web_report),
                output_path,
                methodology_commit=args.methodology_commit,
                validation_timestamp=args.validation_timestamp,
            )
            result["migration_validation_receipt"] = {
                "path": str(output_path),
                "sha256": sha256_file(output_path),
                "validation_sha256": receipt["validation_sha256"],
            }
        emit(result)
    except (OSError, CalculationError) as exc:
        if isinstance(exc, CalculationError):
            error = {"code": exc.code, "message": exc.message, "details": exc.details}
        else:
            error = {"code": "file_error", "message": str(exc)}
        emit({"command": "validate-v5-projections", "ok": False, "error": error}, 1)


def verify_historical_gate_identity(
    historical: dict[str, Any],
    identity: dict[str, Any],
    structure: dict[str, Any],
    supplement: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    provenance = historical.get("provenance") if isinstance(historical.get("provenance"), dict) else {}
    structure_provenance = structure.get("provenance") if isinstance(structure.get("provenance"), dict) else {}
    pairs = [
        ("candidate_sha256", historical.get("candidate", {}).get("sha256"), identity["candidate_sha256"]),
        ("source_sha256", provenance.get("source_sha256"), identity["source_sha256"]),
        ("benchmark_sha256", provenance.get("benchmark_sha256"), identity["benchmark_sha256"]),
        ("policy_sha256", provenance.get("policy_sha256"), identity["policy_sha256"]),
        ("page_map_sha256", provenance.get("page_map_sha256"), identity["page_map_sha256"]),
        ("chunk_manifest_sha256", provenance.get("chunk_manifest_sha256"), identity["chunk_manifest_sha256"]),
        ("normalized_candidate_file_sha256", provenance.get("normalized_candidate_file_sha256"), identity["normalized_candidate_file_sha256"]),
        ("item_inventory_file_sha256", provenance.get("item_inventory_file_sha256"), identity["item_inventory_file_sha256"]),
        ("structure_audit_file_sha256", provenance.get("structure_audit_file_sha256"), identity["structure_audit_file_sha256"]),
        ("audit_mode", historical.get("audit_scope", {}).get("mode"), identity["audit_mode"]),
    ]
    checks: dict[str, dict[str, Any]] = {}
    for field, historical_value, current_value in pairs:
        require(isinstance(historical_value, str) and historical_value, "historical_gate_identity_missing", f"Historical V4 result lacks {field}; unchanged gate policy/evidence cannot be proven.")
        require(isinstance(current_value, str) and current_value, "historical_gate_identity_missing", f"Frozen V5 inputs lack {field}; unchanged gate policy/evidence cannot be proven.")
        require(historical_value == current_value, "historical_gate_identity_mismatch", f"Historical V4 {field} differs from the supplied frozen evidence.", {"historical": historical_value, "current": current_value})
        checks[field] = {
            "historical": historical_value,
            "current": current_value,
            "equal": True,
            "evidence_equivalent": True,
            "comparison_basis": "direct_sha256_or_value_equality",
        }
    for field in ("locator_audit_set_sha256", "missing_access_audit_set_sha256"):
        historical_value = provenance.get(field)
        current_value = identity[field]
        require(isinstance(historical_value, str) and historical_value, "historical_gate_identity_missing", f"Historical V4 result lacks {field}; unchanged gate policy/evidence cannot be proven.")
        require(isinstance(current_value, str) and current_value, "historical_gate_identity_missing", f"Frozen V5 inputs lack {field}; unchanged gate policy/evidence cannot be proven.")
        if historical_value == current_value:
            checks[field] = {
                "historical": historical_value,
                "current": current_value,
                "equal": True,
                "evidence_equivalent": True,
                "comparison_basis": "direct_sha256_or_value_equality",
            }
            continue
        historical_identity_field = f"historical_{field}"
        require(isinstance(supplement, dict), "historical_gate_identity_mismatch", f"Historical V4 {field} uses a different identity scheme and no reconciliation supplement was supplied.", {"historical": historical_value, "current": current_value})
        require(identity.get(historical_identity_field) == historical_value, "historical_gate_identity_mismatch", f"Historical V4 {field} differs from the supplement-bound frozen provenance.", {"historical": historical_value, "supplement_bound": identity.get(historical_identity_field)})
        require(supplement.get(field) == current_value, "historical_gate_identity_mismatch", f"The migration supplement does not bind the V5-canonical {field}.", {"canonical": current_value, "supplement": supplement.get(field)})
        checks[field] = {
            "historical": historical_value,
            "current": current_value,
            "equal": False,
            "evidence_equivalent": True,
            "comparison_basis": "hash_bound_migration_supplement_reconciliation",
        }
    return checks


def resolve_stored_artifact_path(stored_path: Any, container_path: Path, *, label: str, allow_legacy_absolute: bool = False) -> Path:
    if allow_legacy_absolute:
        require(isinstance(stored_path, str) and stored_path, "score_migration_binding_mismatch", f"{label} is required.")
    else:
        require_portable_relative_path(stored_path, label=label)
    candidate = Path(stored_path)
    resolved = (candidate if allow_legacy_absolute and candidate.is_absolute() else container_path.parent / candidate).resolve()
    require(resolved.is_file(), "score_migration_binding_mismatch", f"{label} does not resolve to a file.", {"resolved": str(resolved)})
    return resolved


def require_same_artifact(first: Path, second: Path, *, label: str) -> None:
    same_file = first.resolve() == second.resolve()
    if not same_file and first.exists() and second.exists():
        try:
            same_file = os.path.samefile(first, second)
        except OSError:
            same_file = False
    require(same_file, "score_migration_binding_mismatch", f"{label} resolves to a different artifact.", {"expected": str(second.resolve()), "actual": str(first.resolve())})


def validate_migration_record_for_calculation(
    calculation: dict[str, Any],
    calculation_path: Path,
    migration_path: Path | None = None,
    loaded: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate a migration record, its exact historical V4 result, and optional frozen ledgers."""
    calculation_path = calculation_path.resolve()
    context = calculation.get("migration_context")
    require(isinstance(context, dict), "score_only_migration_required", "A migrated V5 calculation requires a bound migration context.")
    legacy_context = context.get("migration_schema_version") in {None, "subject-index-score-migration-v1"}
    context_migration_path = resolve_stored_artifact_path(
        context.get("migration_record_path"),
        calculation_path,
        label="migration_context.migration_record_path",
        allow_legacy_absolute=legacy_context,
    )
    if migration_path is None:
        migration_path = context_migration_path
    else:
        migration_path = migration_path.resolve()
        require_same_artifact(context_migration_path, migration_path, label="The calculation migration context")

    migration = load_json(migration_path, "Score-migration record")
    validate_schema_document(migration, "score-migration.schema.json", "Score-migration record")
    legacy_migration = migration.get("schema_version") == "subject-index-score-migration-v1"
    if legacy_migration:
        require(context.get("migration_schema_version") in {None, migration.get("schema_version")}, "score_migration_binding_mismatch", "Legacy calculation migration-context schema version differs from its V1 migration record.")
    else:
        require(context.get("migration_schema_version") == migration.get("schema_version"), "score_migration_binding_mismatch", "A V2 calculation must declare the exact migration schema version in its migration context.")
        require_portable_relative_path(context.get("migration_record_path"), label="migration_context.migration_record_path")
    require(migration.get("migration_sha256") == canonical_hash(migration, "migration_sha256"), "migration_self_hash_mismatch", "The score-migration canonical hash does not reconstruct.")
    historical_path = resolve_stored_artifact_path(migration.get("from", {}).get("historical_result_path"), migration_path, label="score_migration.from.historical_result_path", allow_legacy_absolute=legacy_migration)
    historical = load_json(historical_path, "Historical V4 evaluation result")
    validate_schema_document(historical, "evaluation-result.schema.json", "Historical V4 evaluation result")
    require(historical.get("provenance", {}).get("rubric_version") == "subject-index-rubric-v4", "not_historical_v4", "The bound historical result is not an explicit V4 result.")

    historical_file_sha256 = sha256_file(historical_path)
    historical_gate_sha256 = canonical_hash({"critical_gates": historical.get("critical_gates", [])})
    recorded_calculation_path = resolve_stored_artifact_path(migration.get("to", {}).get("calculation_path"), migration_path, label="score_migration.to.calculation_path", allow_legacy_absolute=legacy_migration)
    require_same_artifact(recorded_calculation_path, calculation_path, label="The score-migration calculation binding")
    checks = (
        ("evaluation_id", migration.get("evaluation_id"), calculation.get("evaluation_id")),
        ("historical_evaluation_id", historical.get("evaluation_id"), calculation.get("evaluation_id")),
        ("historical_result_sha256", migration.get("from", {}).get("historical_result_sha256"), historical_file_sha256),
        ("context_historical_result_sha256", context.get("historical_result_sha256"), historical_file_sha256),
        ("context_historical_gate_outcomes_sha256", context.get("historical_gate_outcomes_sha256"), historical_gate_sha256),
        ("calculation_file_sha256", migration.get("to", {}).get("calculation_file_sha256"), sha256_file(calculation_path)),
        ("calculation_canonical_sha256", migration.get("to", {}).get("calculation_canonical_sha256"), calculation.get("calculation_sha256")),
        ("migration_total_score", migration.get("to", {}).get("total_score"), calculation.get("total_score")),
        ("historical_total_score", migration.get("from", {}).get("total_score"), historical.get("total_score")),
        ("input_ledgers", migration.get("input_ledgers"), calculation.get("input_artifacts")),
        ("historical_gate_outcomes_sha256", migration.get("gate_preservation", {}).get("historical_gate_outcomes_sha256"), historical_gate_sha256),
        ("preserved_gate_outcomes_sha256", migration.get("gate_preservation", {}).get("preserved_gate_outcomes_sha256"), historical_gate_sha256),
    )
    for field, actual, expected in checks:
        require(actual == expected, "score_migration_binding_mismatch", f"Score-migration {field} differs from its exact calculation or historical result.", {"expected": expected, "actual": actual})

    if migration.get("schema_version") == MIGRATION_SCHEMA:
        require_utc_timestamp(migration.get("migration_timestamp"), label="score_migration.migration_timestamp")
        require_methodology_commit(migration.get("methodology", {}).get("commit_sha"))
        previous_scorecard = score_snapshots(historical.get("scorecard"), migrated=False)
        migrated_scorecard = score_snapshots(calculation.get("dimensions"), migrated=True)
        v2_checks = (
            ("from.result_schema_version", migration.get("from", {}).get("result_schema_version"), historical.get("schema_version")),
            ("from.scorecard", migration.get("from", {}).get("scorecard"), previous_scorecard),
            ("to.calculation_schema_version", migration.get("to", {}).get("calculation_schema_version"), calculation.get("schema_version")),
            ("to.scorecard", migration.get("to", {}).get("scorecard"), migrated_scorecard),
            ("dimension_comparison", migration.get("dimension_comparison"), compare_score_snapshots(previous_scorecard, migrated_scorecard)),
            ("total_delta", migration.get("total_delta"), nullable_delta(calculation.get("total_score"), historical.get("total_score"), Decimal("0.01"))),
            ("historical_outcomes", migration.get("gate_preservation", {}).get("historical_outcomes"), json_compatible(historical.get("critical_gates", []))),
            ("preserved_outcomes", migration.get("gate_preservation", {}).get("preserved_outcomes"), json_compatible(historical.get("critical_gates", []))),
        )
        for field, actual, expected in v2_checks:
            require(canonical_json_text(actual) == canonical_json_text(expected), "score_migration_binding_mismatch", f"Score-migration {field} does not reconstruct.", {"expected": expected, "actual": actual})
        lineage_roles: set[str] = set()
        lineage_by_role: dict[str, dict[str, Any]] = {}
        for index, lineage in enumerate(migration.get("input_lineage", [])):
            role = lineage.get("role")
            require(isinstance(role, str) and role not in lineage_roles, "score_migration_binding_mismatch", "Score-migration input-lineage roles must be unique.", {"role": role})
            lineage_roles.add(role)
            lineage_by_role[role] = lineage
            path = resolve_stored_artifact_path(lineage.get("path"), migration_path, label=f"score_migration.input_lineage[{index}].path")
            require(lineage.get("sha256") == sha256_file(path), "score_migration_binding_mismatch", f"Score-migration input_lineage[{index}] hash differs from the bound file.")
        ledger_roles = {item["role"] for item in migration.get("input_ledgers", [])}
        representation_roles = {item["role"] for item in migration.get("representation_adjustment", {}).get("provenance_artifacts", [])}
        expected_lineage_roles = {"historical_v4_result", "dimension_calculation_input", "v5_dimension_calculations", *ledger_roles, *representation_roles}
        require(lineage_roles == expected_lineage_roles, "score_migration_binding_mismatch", "Score-migration input lineage does not exactly cover every frozen input and derived calculation.", {"missing": sorted(expected_lineage_roles - lineage_roles), "unexpected": sorted(lineage_roles - expected_lineage_roles)})
        require(lineage_by_role["historical_v4_result"].get("disposition") == "unchanged" and lineage_by_role["historical_v4_result"].get("sha256") == historical_file_sha256, "score_migration_binding_mismatch", "Historical V4 result lineage is not immutable and hash-bound.")
        require(lineage_by_role["dimension_calculation_input"].get("disposition") == "unchanged", "score_migration_binding_mismatch", "Dimension-calculation input lineage must be recorded as unchanged.")
        for artifact in migration.get("input_ledgers", []):
            lineage = lineage_by_role[artifact["role"]]
            require(lineage.get("disposition") == "unchanged" and lineage.get("sha256") == artifact["sha256"], "score_migration_binding_mismatch", f"Frozen input lineage for {artifact['role']} does not match the migration input ledger.")
        for artifact in migration.get("representation_adjustment", {}).get("provenance_artifacts", []):
            lineage = lineage_by_role[artifact["role"]]
            require(lineage.get("disposition") == "unchanged" and lineage.get("sha256") == artifact["sha256"], "score_migration_binding_mismatch", f"Representation-adjustment lineage for {artifact['role']} does not match its provenance artifact.")
        calculation_lineage = lineage_by_role["v5_dimension_calculations"]
        expected_derived_roles = ["historical_v4_result", "dimension_calculation_input", *[item["role"] for item in migration.get("input_ledgers", [])]]
        require(calculation_lineage.get("disposition") == "deterministically_derived" and calculation_lineage.get("sha256") == sha256_file(calculation_path) and calculation_lineage.get("derived_from_roles") == expected_derived_roles, "score_migration_binding_mismatch", "V5 calculation lineage does not reconstruct from the declared inputs.")
        for index, artifact in enumerate(migration.get("representation_adjustment", {}).get("provenance_artifacts", [])):
            path = resolve_stored_artifact_path(artifact.get("path"), migration_path, label=f"score_migration.representation_adjustment.provenance_artifacts[{index}].path")
            require(artifact.get("sha256") == sha256_file(path), "score_migration_binding_mismatch", "Representation-adjustment provenance hash differs from the bound file.")

    if loaded is not None:
        require(calculation.get("input_artifacts") == loaded.get("input_artifacts"), "score_migration_binding_mismatch", "The migrated calculation does not bind the supplied frozen input artifacts.")
        if migration.get("schema_version") == MIGRATION_SCHEMA:
            config_lineage_path = resolve_stored_artifact_path(lineage_by_role["dimension_calculation_input"]["path"], migration_path, label="score_migration.input_lineage.dimension_calculation_input.path")
            require_same_artifact(config_lineage_path, loaded["config_path"], label="The score-migration dimension-calculation input")
            require(lineage_by_role["dimension_calculation_input"]["sha256"] == sha256_file(loaded["config_path"]), "score_migration_binding_mismatch", "Dimension-calculation input lineage hash differs from the supplied configuration.")
            for artifact, input_path in zip(loaded["input_artifacts"], loaded["input_paths"], strict=True):
                lineage_path = resolve_stored_artifact_path(lineage_by_role[artifact["role"]]["path"], migration_path, label=f"score_migration.input_lineage.{artifact['role']}.path")
                require_same_artifact(lineage_path, input_path, label=f"The score-migration {artifact['role']} input")
        ledger_identity = validate_ledger_set_integrity(loaded)
        expected_identity_checks = verify_historical_gate_identity(historical, ledger_identity, loaded["structure"], loaded.get("supplement"))
        require(migration.get("gate_preservation", {}).get("identity_checks") == expected_identity_checks, "score_migration_binding_mismatch", "The score-migration gate identity checks do not reconstruct from the historical result and frozen ledgers.")
        expected_frozen_hash = canonical_hash(loaded["input_artifacts"])
        require(migration.get("gate_preservation", {}).get("frozen_gate_evidence_inputs_sha256") == expected_frozen_hash, "score_migration_binding_mismatch", "The score-migration frozen gate-evidence hash does not reconstruct.")
    return migration


def score_snapshots(records: Any, *, migrated: bool) -> list[dict[str, Any]]:
    mapped = exact_dimension_map(records, "migrated calculation" if migrated else "historical scorecard")
    snapshots: list[dict[str, Any]] = []
    for dimension_id in WEIGHTS:
        record = mapped[dimension_id]
        rating = record.get("final_rating" if migrated else "rating")
        points = record.get("awarded_points" if migrated else "points")
        snapshots.append({
            "dimension_id": dimension_id,
            "rating": displayed_number(decimal_value(rating), Decimal("0.0001")) if rating is not None else None,
            "points": displayed_number(decimal_value(points), Decimal("0.01")) if points is not None else None,
        })
    return snapshots


def nullable_delta(current: Any, previous: Any, quantum: Decimal) -> int | float | None:
    if current is None or previous is None:
        return None
    return displayed_number(decimal_value(current) - decimal_value(previous), quantum)


def compare_score_snapshots(previous: list[dict[str, Any]], migrated: list[dict[str, Any]]) -> list[dict[str, Any]]:
    previous_by_id = {item["dimension_id"]: item for item in previous}
    migrated_by_id = {item["dimension_id"]: item for item in migrated}
    return [
        {
            "dimension_id": dimension_id,
            "previous": previous_by_id[dimension_id],
            "migrated": migrated_by_id[dimension_id],
            "rating_delta": nullable_delta(migrated_by_id[dimension_id]["rating"], previous_by_id[dimension_id]["rating"], Decimal("0.0001")),
            "points_delta": nullable_delta(migrated_by_id[dimension_id]["points"], previous_by_id[dimension_id]["points"], Decimal("0.01")),
        }
        for dimension_id in WEIGHTS
    ]


def json_compatible(value: Any) -> Any:
    return json.loads(canonical_json_text(value))


def representation_provenance(paths: Sequence[str], migration_output: Path) -> tuple[dict[str, Any], list[Path]]:
    if not paths:
        return {"status": "not_applicable"}, []
    artifacts: list[dict[str, Any]] = []
    resolved_paths: list[Path] = []
    for index, raw_path in enumerate(paths):
        path = Path(raw_path).resolve()
        document = load_json(path, f"Representation-adjustment provenance[{index}]")
        schema_version = document.get("schema_version")
        require(isinstance(schema_version, str) and schema_version, "invalid_representation_provenance", "Representation-adjustment provenance must declare schema_version.")
        artifacts.append({
            "role": f"representation_adjustment_provenance[{index}]",
            "path": portable_relative_reference(path, migration_output, label=f"representation_adjustment.provenance_artifacts[{index}].path"),
            "sha256": sha256_file(path),
            "schema_version": schema_version,
        })
        resolved_paths.append(path)
    return {
        "status": "separate_evidentiary_correction",
        "causal_attribution": "not_a_v5_methodology_effect",
        "provenance_artifacts": artifacts,
    }, resolved_paths


def command_migrate(args: argparse.Namespace) -> None:
    historical_path = Path(args.historical_result).resolve()
    try:
        methodology_commit = require_methodology_commit(args.methodology_commit)
        migration_timestamp = require_utc_timestamp(args.migration_timestamp, label="migration_timestamp")
        historical_bytes_before = historical_path.read_bytes()
        historical = load_json(historical_path, "Historical evaluation result")
        validate_schema_document(historical, "evaluation-result.schema.json", "Historical V4 evaluation result")
        require(historical.get("provenance", {}).get("rubric_version") == "subject-index-rubric-v4", "not_historical_v4", "Score-only migration requires an explicit historical V4 result.")
        config_path = Path(args.input).resolve()
        config_bytes_before = config_path.read_bytes()
        historical_result_sha256 = hashlib.sha256(historical_bytes_before).hexdigest()
        historical_gate_hash = canonical_hash({"critical_gates": historical.get("critical_gates", [])})
        loaded = load_inputs(config_path)
        calculations_output = Path(args.calculations_output).resolve()
        migration_output = Path(args.migration_record_output).resolve()
        migration_record_reference = portable_relative_reference(migration_output, calculations_output, label="migration_context.migration_record_path")
        representation_record, representation_paths = representation_provenance(args.representation_adjustment_provenance or [], migration_output)
        representation_hashes_before = {path: sha256_file(path) for path in representation_paths}
        calculations = calculate_loaded(loaded, allow_historical_migration=True)
        calculations["migration_context"] = {
            "from_rubric_version": "subject-index-rubric-v4",
            "migration_schema_version": MIGRATION_SCHEMA,
            "migration_record_path": migration_record_reference,
            "historical_result_sha256": historical_result_sha256,
            "historical_gate_outcomes_sha256": historical_gate_hash,
            "gate_outcomes_action": "preserve_identically",
        }
        calculations["calculation_sha256"] = canonical_hash(calculations, "calculation_sha256")
        ledger_identity = validate_ledger_set_integrity(loaded)
        protected_paths = {historical_path, config_path, *loaded["input_paths"], *representation_paths}
        require(historical.get("evaluation_id") == calculations["evaluation_id"], "evaluation_identity_mismatch", "The historical result and frozen ledgers belong to different evaluations.")
        gate_identity_checks = verify_historical_gate_identity(historical, ledger_identity, loaded["structure"], loaded.get("supplement"))
        require(not aliases_existing_file(calculations_output, protected_paths) and not aliases_existing_file(migration_output, protected_paths), "output_aliases_frozen_input", "Migration outputs must not overwrite or alias the historical result, input config, or any frozen ledger.")
        outputs_collide = calculations_output == migration_output
        if not outputs_collide and calculations_output.exists() and migration_output.exists():
            try:
                outputs_collide = os.path.samefile(calculations_output, migration_output)
            except OSError:
                outputs_collide = False
        require(not outputs_collide, "output_path_collision", "Calculation and migration-record outputs must be different files.")
        validate_schema_document(calculations, "dimension-calculations.schema.json", "Generated V5 dimension calculations")
        write_json(calculations_output, calculations)
        historical_bytes_after = historical_path.read_bytes()
        require(historical_bytes_before == historical_bytes_after, "historical_input_mutated", "Historical result bytes changed during migration.")
        require(config_bytes_before == config_path.read_bytes(), "input_config_mutated", "Dimension-calculation input bytes changed during migration.")
        input_hashes_after = {item["path"]: item["sha256"] for item in loaded["input_artifacts"]}
        # Re-resolve every input to prove the migration did not mutate a ledger byte.
        loaded_again = load_inputs(Path(args.input).resolve())
        require(input_hashes_after == {item["path"]: item["sha256"] for item in loaded_again["input_artifacts"]}, "input_ledger_mutated", "An input-ledger hash changed during migration.")
        require(representation_hashes_before == {path: sha256_file(path) for path in representation_paths}, "representation_provenance_mutated", "A representation-adjustment provenance artifact changed during migration.")
        previous_scorecard = score_snapshots(historical["scorecard"], migrated=False)
        migrated_scorecard = score_snapshots(calculations["dimensions"], migrated=True)
        input_lineage = [{
            "role": "historical_v4_result",
            "path": portable_relative_reference(historical_path, migration_output, label="input_lineage.historical_v4_result.path"),
            "sha256": historical_result_sha256,
            "disposition": "unchanged",
        }, {
            "role": "dimension_calculation_input",
            "path": portable_relative_reference(config_path, migration_output, label="input_lineage.dimension_calculation_input.path"),
            "sha256": hashlib.sha256(config_bytes_before).hexdigest(),
            "disposition": "unchanged",
        }]
        input_lineage.extend({
            "role": artifact["role"],
            "path": portable_relative_reference(path, migration_output, label=f"input_lineage.{artifact['role']}.path"),
            "sha256": artifact["sha256"],
            "disposition": "unchanged",
        } for artifact, path in zip(loaded["input_artifacts"], loaded["input_paths"], strict=True))
        input_lineage.extend({
            "role": artifact["role"],
            "path": artifact["path"],
            "sha256": artifact["sha256"],
            "disposition": "unchanged",
        } for artifact in representation_record.get("provenance_artifacts", []))
        input_lineage.append({
            "role": "v5_dimension_calculations",
            "path": portable_relative_reference(calculations_output, migration_output, label="input_lineage.v5_dimension_calculations.path"),
            "sha256": sha256_file(calculations_output),
            "disposition": "deterministically_derived",
            "derived_from_roles": ["historical_v4_result", "dimension_calculation_input", *[artifact["role"] for artifact in loaded["input_artifacts"]]],
        })
        historical_total = displayed_number(decimal_value(historical["total_score"])) if historical.get("total_score") is not None else None
        migration = {
            "schema_version": MIGRATION_SCHEMA,
            "evaluation_id": calculations["evaluation_id"],
            "migration_timestamp": migration_timestamp,
            "tool": {"name": TOOL_NAME, "version": TOOL_VERSION},
            "methodology": {
                "repository": METHODOLOGY_REPOSITORY,
                "commit_sha": methodology_commit,
                "previous_rubric_version": "subject-index-rubric-v4",
                "migrated_rubric_version": RUBRIC_VERSION,
                "calculation_profile": CALCULATION_PROFILE,
            },
            "from": {
                "rubric_version": "subject-index-rubric-v4",
                "result_schema_version": historical["schema_version"],
                "historical_result_path": portable_relative_reference(historical_path, migration_output, label="from.historical_result_path"),
                "historical_result_sha256": historical_result_sha256,
                "total_score": historical_total,
                "scorecard": previous_scorecard,
            },
            "to": {
                "rubric_version": RUBRIC_VERSION,
                "calculation_profile": CALCULATION_PROFILE,
                "calculation_schema_version": calculations["schema_version"],
                "target_result_schema_version": "subject-index-evaluation-result-v6",
                "calculation_path": portable_relative_reference(calculations_output, migration_output, label="to.calculation_path"),
                "calculation_file_sha256": sha256_file(calculations_output),
                "calculation_canonical_sha256": calculations["calculation_sha256"],
                "total_score": calculations["total_score"],
                "scorecard": migrated_scorecard,
            },
            "total_delta": nullable_delta(calculations["total_score"], historical_total, Decimal("0.01")),
            "dimension_comparison": compare_score_snapshots(previous_scorecard, migrated_scorecard),
            "input_ledgers": loaded["input_artifacts"],
            "input_lineage": input_lineage,
            "input_ledgers_mutated": False,
            "historical_result_mutated": False,
            "representation_adjustment": representation_record,
            "gate_preservation": {
                "policy_or_evidence_changed": False,
                "identity_checks": gate_identity_checks,
                "frozen_gate_evidence_inputs_sha256": canonical_hash(loaded["input_artifacts"]),
                "historical_gate_outcomes_sha256": historical_gate_hash,
                "preserved_gate_outcomes_sha256": historical_gate_hash,
                "historical_outcomes": json_compatible(historical.get("critical_gates", [])),
                "preserved_outcomes": json_compatible(historical.get("critical_gates", [])),
                "outcomes_equal": True,
                "outcomes_action": "preserve_identically",
            },
            "comparability": "v4_and_v5_totals_are_not_directly_comparable",
        }
        migration["migration_sha256"] = canonical_hash(migration, "migration_sha256")
        validate_schema_document(migration, "score-migration.schema.json", "Generated score-migration record")
        write_json(migration_output, migration)
        validate_migration_record_for_calculation(calculations, calculations_output, migration_output, loaded)
        emit({"command": "score-only-migration", "ok": True, "evaluation_id": calculations["evaluation_id"], "v5_total_score": calculations["total_score"], "migration_schema_version": MIGRATION_SCHEMA, "methodology_commit": methodology_commit, "artifacts_written": [str(calculations_output), str(migration_output)], "input_ledgers_mutated": False, "historical_result_mutated": False, "gate_outcomes_action": "preserve_identically"})
    except (OSError, CalculationError) as exc:
        if isinstance(exc, CalculationError):
            error = {"code": exc.code, "message": exc.message, "details": exc.details}
        else:
            error = {"code": "file_error", "message": str(exc)}
        emit({"command": "score-only-migration", "ok": False, "error": error}, 1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    preflight = subparsers.add_parser("preflight", help="Report exact V5 migration/calculation sufficiency without changing inputs.")
    preflight.add_argument("--input", required=True)
    preflight.add_argument("--output")
    preflight.set_defaults(func=command_preflight)
    calculate = subparsers.add_parser("calculate", help="Derive all six V5 ratings from validated ledgers.")
    calculate.add_argument("--input", required=True)
    calculate.add_argument("--output")
    calculate.set_defaults(func=command_calculate)
    projections = subparsers.add_parser("validate-projections", help="Validate evaluation-result and web-report projections against one exact V5 calculation artifact.")
    projections.add_argument("--calculation", required=True)
    projections.add_argument("--evaluation-result", required=True)
    projections.add_argument("--web-report")
    projections.add_argument("--output", help="Write a canonical post-projection migration-validation receipt.")
    projections.add_argument("--methodology-commit", help="Exact merged methodology commit; required with --output.")
    projections.add_argument("--validation-timestamp", help="RFC 3339 UTC timestamp ending in Z; required with --output.")
    projections.set_defaults(func=command_validate_projections)
    migrate = subparsers.add_parser("score-only-migration", help="Preserve V4 history and produce a distinct V5 calculation and migration record.")
    migrate.add_argument("--input", required=True)
    migrate.add_argument("--historical-result", required=True)
    migrate.add_argument("--calculations-output", required=True)
    migrate.add_argument("--migration-record-output", required=True)
    migrate.add_argument("--methodology-commit", required=True, help="Exact merged methodology commit used for the migration.")
    migrate.add_argument("--migration-timestamp", required=True, help="RFC 3339 UTC timestamp ending in Z.")
    migrate.add_argument("--representation-adjustment-provenance", action="append", default=[], help="Existing provenance artifact for a separate evidentiary correction; may be repeated.")
    migrate.set_defaults(func=command_migrate)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
