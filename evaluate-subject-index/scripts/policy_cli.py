#!/usr/bin/env python3
"""Instantiate the built-in subject-index evaluation policy deterministically."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from schema_validation import schema_errors


POLICY_SCHEMA = "subject-index-evaluation-policy-v3"
POLICY_PROFILE = "subject-index-standard-policy-v7"

DEFAULT_INCLUDED = [
    "preparation-approved indexable content",
    "substantive body, chapter, and part text",
    "substantive block quotations",
    "substantive inspectable notes, footnotes, and endnotes",
    "substantive captions and table text",
    "eligible text whose role remains unknown",
]

DEFAULT_EXCLUDED = [
    "front or back matter designated nonindexable",
    "bibliographies and source lists",
    "publisher and candidate indexes",
    "contents pages and navigation lists",
    "running furniture and page numbers",
    "proof or production material",
    "graph internals and ignored regions",
    "material unavailable in the supplied source",
]

POLICY_AREAS = {
    "scope_compliance": "standard-policy-v7.md#locator-utility",
    "substantive_coverage": "standard-policy-v7.md#locator-utility",
    "editorial_selectivity": "standard-policy-v7.md#locator-utility",
    "conceptual_stance_fidelity": "standard-policy-v7.md#locator-utility",
    "heading_access_architecture": "standard-policy-v7.md#locator-strings-and-ranges",
    "locator_quality": "standard-policy-v7.md#locator-utility",
    "compound_heading_scope": "standard-policy-v7.md#locator-utility",
    "cross_references": "standard-policy-v7.md#locator-utility",
    "whole_index_coherence": "standard-policy-v7.md#locator-strings-and-ranges",
    "mechanical_validity": "standard-policy-v7.md#locator-strings-and-ranges",
}

STAGE_APPLICATION = {
    "source_subject_discovery": [
        "scope_compliance",
        "substantive_coverage",
        "editorial_selectivity",
        "conceptual_stance_fidelity",
        "locator_quality",
    ],
    "benchmark_freeze": [
        "substantive_coverage",
        "conceptual_stance_fidelity",
        "heading_access_architecture",
        "whole_index_coherence",
    ],
    "locator_audit": [
        "scope_compliance",
        "editorial_selectivity",
        "conceptual_stance_fidelity",
        "locator_quality",
        "compound_heading_scope",
    ],
    "missing_access_audit": [
        "substantive_coverage",
        "conceptual_stance_fidelity",
        "heading_access_architecture",
        "locator_quality",
        "cross_references",
    ],
    "structure_audit": [
        "scope_compliance",
        "editorial_selectivity",
        "conceptual_stance_fidelity",
        "heading_access_architecture",
        "compound_heading_scope",
        "cross_references",
        "whole_index_coherence",
        "mechanical_validity",
    ],
    "deterministic_validation": [
        "scope_compliance",
        "heading_access_architecture",
        "locator_quality",
        "cross_references",
        "mechanical_validity",
    ],
}

DENSITY_METRICS = [
    {
        "metric_id": "locator_bearing_heading_paths_per_1000_source_words",
        "unit": "locator-bearing complete heading paths per 1,000 indexable source words",
        "scored": True,
        "weight": 0.5,
        "target": 8.0,
        "ideal_min": 6.0,
        "ideal_max": 10.0,
        "acceptable_min": 4.0,
        "acceptable_max": 12.0,
        "provenance": POLICY_PROFILE,
    },
    {
        "metric_id": "locator_occurrences_per_1000_source_words",
        "unit": "expanded locator occurrences per 1,000 indexable source words",
        "scored": True,
        "weight": 0.5,
        "target": 20.0,
        "ideal_min": 15.0,
        "ideal_max": 25.0,
        "acceptable_min": 10.0,
        "acceptable_max": 30.0,
        "provenance": POLICY_PROFILE,
    },
]

CRITICAL_GATES = [
    ("GATE-SCOPE-LOCATOR", "fabricated, nonexistent, or out-of-scope locator"),
    ("GATE-SYSTEMIC-UNSUPPORTED", "systematic incidental or unsupported locator pattern"),
    ("GATE-CENTRAL-OMISSION", "central subject or conclusion materially omitted"),
    ("GATE-STANCE", "heading reverses or seriously misrepresents source stance"),
    ("GATE-COMPOUND", "compound heading locators support only separate components"),
    ("GATE-SEE-SUBSTITUTION", "see source replaces a warranted substantive entry"),
    ("GATE-CROSS-REFERENCE", "unresolved, self-referential, circular, or chained cross-reference"),
    ("GATE-DEPTH", "third-level heading"),
    ("GATE-CLUTTER", "systematic named-entity, example, or citation clutter"),
    ("GATE-GROUNDING", "critical or major unresolved grounding"),
    ("GATE-UNINSPECTABLE", "more than 1% of in-scope locator assignments uninspectable without a frozen alternative tolerance"),
    ("GATE-SOURCE-SPAN", "wrong source span"),
    ("GATE-STRUCTURE", "structurally invalid or incomplete output"),
]


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_hash(payload: dict[str, Any], own_hash_field: str) -> str:
    clone = dict(payload)
    clone.pop(own_hash_field, None)
    encoded = json.dumps(clone, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def unique_strings(values: list[Any], field: str) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value:
            raise ValueError(f"{field} values must be non-empty strings")
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result


def read_input(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    errors = schema_errors(value, "policy-build-input.schema.json")
    if errors:
        raise ValueError("Policy build input is structurally invalid: " + "; ".join(errors))
    return value


def build_policy(source: dict[str, Any], standard_path: Path) -> dict[str, Any]:
    scope = source.get("source_scope", {})
    audience = source.get("audience", {})
    audit = source.get("audit_design", {})
    span = scope.get("document_page_span")
    if not (isinstance(span, list) and len(span) == 2 and all(isinstance(item, int) for item in span) and span[0] <= span[1]):
        raise ValueError("source_scope.document_page_span must be an ascending integer pair")
    deviations = source.get("deviations", [])

    stamp = now()
    policy: dict[str, Any] = {
        "schema_version": POLICY_SCHEMA,
        "policy_id": source.get("policy_id") or "subject-index-policy",
        "policy_profile": {
            "id": POLICY_PROFILE,
            "standard_policy_sha256": sha256_file(standard_path),
        },
        "source_scope": {
            "source_sha256": scope["source_sha256"],
            "document_page_span": span,
            "page_map_sha256": scope["page_map_sha256"],
            "chunk_manifest_sha256": scope["chunk_manifest_sha256"],
            "included": unique_strings(DEFAULT_INCLUDED + list(scope.get("source_specific_included", [])), "source_scope.included"),
            "excluded": unique_strings(DEFAULT_EXCLUDED + list(scope.get("source_specific_excluded", [])), "source_scope.excluded"),
            "availability": scope.get("availability", {}),
            "mixed_page_rule": "Evaluate eligible regions and ignore excluded regions on the same page.",
            "word_count_basis": "indexable source words only",
        },
        "audience": {
            "label": audience["label"],
            "basis": audience["basis"],
            "confidence": audience["confidence"],
            "rationale": audience["rationale"],
        },
        "audit_design": {
            "mode": audit.get("mode", "full"),
            "candidate_blindness": audit.get("candidate_blindness", "required"),
            "uncertainty_policy": "Record uncertainty explicitly; adjudicate every critical, major, and uncertain item; exclude uninspectable locators from precision denominators and disclose them.",
            "uninspectable_locator_rate_tolerance": 0.01,
        },
        "content_policies": {
            key: {"rule_reference": value, "profile": POLICY_PROFILE}
            for key, value in POLICY_AREAS.items()
        },
        "stage_application": STAGE_APPLICATION,
        "density_profile": {
            "status": "scored",
            "measurement_level": "chapter_or_approved_intellectual_unit",
            "aggregation": "indexable_source_word_weighted_mean",
            "rounding": "nearest_0.5_after_aggregation",
            "metrics": DENSITY_METRICS,
            "short_unit_rule": "Treat an unstable short unit as descriptive or combine it with a declared adjacent unit.",
            "rationale": "Permissive calibration for finished-index scale and distribution; never a subject-discovery quota or hard ceiling.",
            "maximum_score_contribution": 5,
        },
        "critical_gates": [
            {"gate_id": gate_id, "description": description, "standard": True}
            for gate_id, description in CRITICAL_GATES
        ],
        "deviations": deviations,
        "freeze": {"frozen_at": stamp, "candidate_seen": False},
        "policy_sha256": None,
    }
    policy["policy_sha256"] = canonical_hash(policy, "policy_sha256")
    errors = schema_errors(policy, "evaluation-policy-v3.schema.json")
    if errors:
        raise ValueError("Generated policy is structurally invalid: " + "; ".join(errors))
    return policy


def command_build(args: argparse.Namespace) -> None:
    input_path = Path(args.input)
    output_path = Path(args.output)
    standard_path = Path(args.standard_policy) if args.standard_policy else Path(__file__).resolve().parents[1] / "references" / "standard-policy-v7.md"
    try:
        source = read_input(input_path)
        policy = build_policy(source, standard_path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        raise SystemExit(1)
    if output_path.exists() and not args.force:
        print(json.dumps({"ok": False, "error": f"Refusing to overwrite {output_path}"}, indent=2))
        raise SystemExit(1)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(policy, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "ok": True,
        "command": "define-policy",
        "artifact_written": str(output_path.resolve()),
        "policy_profile": POLICY_PROFILE,
        "policy_sha256": policy["policy_sha256"],
        "deviation_count": len(policy["deviations"]),
    }, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--input", required=True)
    build.add_argument("--output", required=True)
    build.add_argument("--standard-policy")
    build.add_argument("--force", action="store_true")
    build.set_defaults(func=command_build)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
