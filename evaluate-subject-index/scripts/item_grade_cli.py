#!/usr/bin/env python3
"""Build stable item identities and deterministic diagnostic grades for an index audit."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Iterable

from locator_relevance import assign_locator_credit


GRADING_POLICY = "subject-index-item-grading-v1"
V6_GRADING_POLICY = "subject-index-item-grading-v2"
DEFECT_PROJECTION_ORDER_RULE_ID = "ITEM-PROJECTION-DEFECT-ID-ASC-V1"
COMPONENT_WEIGHTS = {
    "meaningful_coverage": 20.0,
    "editorial_selectivity": 10.0,
    "conceptual_stance_fidelity": 15.0,
    "page_reference_reliability": 25.0,
    "findability_navigation": 20.0,
    "mechanics_consistency": 5.0,
}
STRUCTURE_COMPONENTS = {
    "conceptual_stance_fidelity": "conceptual_stance_fidelity",
    "heading_access_architecture": "findability_navigation",
    "mechanics_consistency": "mechanics_consistency",
}
DEFECT_COMPONENTS = {
    "SCP": "editorial_selectivity",
    "COV": "meaningful_coverage",
    "SEL": "editorial_selectivity",
    "CON": "conceptual_stance_fidelity",
    "STA": "conceptual_stance_fidelity",
    "LOC_POS": "page_reference_reliability",
    "LOC_NEG": "page_reference_reliability",
    "CMP": "conceptual_stance_fidelity",
    "HED": "findability_navigation",
    "SUB": "findability_navigation",
    "XRF": "findability_navigation",
    "MEC": "mechanics_consistency",
}
SEVERITY_CAP = {"cosmetic": 95.0, "minor": 85.0, "major": 55.0, "critical": 0.0}
STRUCTURE_STATUS_SCORE = {
    "passes": 100.0,
    "cosmetic_issues": 95.0,
    "minor_issues": 85.0,
    "major_issues": 55.0,
    "fails": 0.0,
    "uninspectable": None,
    "not_applicable": None,
}
LOCATOR_SCORE = {
    "supported": 100.0,
    "partially_supported": 70.0,
    "unsupported": 0.0,
    "uninspectable": None,
}
TREATMENT_SCORE = {
    "substantive": 100.0,
    "mixed": 70.0,
    "passing_mention": 0.0,
    "attribution_only": 0.0,
    "citation_only": 0.0,
    "incidental_example": 0.0,
    "absent": 0.0,
    "unavailable": None,
}
COVERAGE_SCORE = {"complete": 100.0, "partial": 70.0, "missing": 0.0, "uninspectable": None}
REFERENCE_SCORE = {"supported": 100.0, "partially_supported": 70.0, "unsupported": 0.0, "uninspectable": None}
PRIORITY_WEIGHT = {"essential": 3.0, "major": 2.0, "optional": 1.0}
CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}
V5_IDENTITY_FIELDS = (
    "source_sha256",
    "benchmark_lock_sha256",
    "policy_sha256",
    "page_map_sha256",
    "chunk_manifest_sha256",
    "normalized_candidate_file_sha256",
    "item_inventory_file_sha256",
)


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def canonical_id_set_hash(ids: Iterable[str]) -> str:
    return canonical_hash({"ids": sorted(ids)})


def canonical_audit_set_hash(
    documents: list[dict[str, Any]],
    paths: list[Path],
    collections: tuple[tuple[str, str, str], ...],
) -> str:
    triples = sorted(zip(documents, paths, strict=True), key=lambda item: item[0].get("chunk_id", ""))
    records: list[dict[str, Any]] = []
    for document, path in triples:
        record: dict[str, Any] = {
            "chunk_id": document["chunk_id"],
            "file_sha256": sha256_file(path),
            "byte_length": path.stat().st_size,
        }
        for collection, id_field, output_key in collections:
            record[output_key] = sorted(item[id_field] for item in document.get(collection, []))
        records.append(record)
    return canonical_hash(records)


def defect_dimension(defect: dict[str, Any]) -> str | None:
    """Prefer the validated V5 owner; retain code routing for historical defects."""
    owner = defect.get("dimension_owner")
    return owner if owner in COMPONENT_WEIGHTS else DEFECT_COMPONENTS.get(defect.get("code"))


def defect_affected_ids(defect: dict[str, Any]) -> list[str]:
    """Normalize V5 affected_item_ids and historical affected_ids without dropping either."""
    values = defect.get("affected_item_ids")
    if values is None:
        values = defect.get("affected_ids", [])
    return values if isinstance(values, list) else []


def ordered_unique_defects(
    defect_records: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Deduplicate valid defects by identity and emit them in stable ID order."""
    by_id: dict[str, dict[str, Any]] = {}
    for item in defect_records:
        defect_id = item.get("defect_id")
        if isinstance(defect_id, str) and defect_id:
            by_id.setdefault(defect_id, item)
    return [by_id[defect_id] for defect_id in sorted(by_id)]


def emit(value: Any) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False))


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail("invalid_json", f"Could not load {path}: {exc}")
    if not isinstance(value, dict):
        fail("invalid_json_root", f"Expected an object in {path}")
    return value


def save_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fail(code: str, message: str, details: Iterable[str] | None = None) -> None:
    payload: dict[str, Any] = {"ok": False, "error": {"code": code, "message": message}}
    if details:
        payload["error"]["details"] = list(details)
    emit(payload)
    raise SystemExit(1)


def stable_id(prefix: str, candidate_sha256: str, identity: Any) -> str:
    canonical = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(f"{candidate_sha256}\n{canonical}".encode("utf-8")).hexdigest()[:12].upper()
    return f"{prefix}-{digest}"


def grade(score: float | None, measured: bool = True) -> dict[str, Any]:
    if score is None or not measured:
        return {
            "score": None,
            "rating": None,
            "band": "not_measured",
            "color_token": "grade_neutral",
            "status": "not_measured",
        }
    bounded = round(max(0.0, min(100.0, score)), 2)
    if bounded >= 90:
        band, token, status = "excellent", "grade_excellent", "passes"
    elif bounded >= 80:
        band, token, status = "strong", "grade_strong", "passes_with_issues"
    elif bounded >= 70:
        band, token, status = "mixed", "grade_mixed", "needs_review"
    elif bounded >= 60:
        band, token, status = "weak", "grade_weak", "needs_revision"
    else:
        band, token, status = "poor", "grade_poor", "fails"
    return {
        "score": bounded,
        "rating": round(bounded / 20.0, 3),
        "band": band,
        "color_token": token,
        "status": status,
    }


def popover(
    title: str,
    summary: str,
    item_grade: dict[str, Any],
    grade_scope: str,
    confidence: str | None,
    factors: list[dict[str, Any]],
    evidence_ids: Iterable[str],
    navigation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "title": title,
        "summary": summary,
        "grade": item_grade,
        "grade_scope": grade_scope,
        "confidence": confidence,
        "factors": factors,
        "evidence_ids": list(dict.fromkeys(item for item in evidence_ids if isinstance(item, str) and item)),
        "navigation": navigation or {},
    }


def canonical_target(value: str) -> str:
    normalized = value.casefold().replace("–", "—")
    normalized = re.sub(r"\s*(?:—|--)\s*", "—", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def severity_cap_records(defect_records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"defect_id": item.get("defect_id"), "severity": item.get("severity"), "maximum_score": SEVERITY_CAP[item["severity"]], "summary": item.get("summary", "")}
        for item in defect_records
        if item.get("severity") in SEVERITY_CAP
    ]


def weighted_mean(values: Iterable[tuple[float | None, float]]) -> float | None:
    measured = [(value, weight) for value, weight in values if value is not None and weight > 0]
    if not measured:
        return None
    denominator = sum(weight for _, weight in measured)
    return sum(float(value) * weight for value, weight in measured) / denominator


def mean(values: Iterable[float | None]) -> float | None:
    measured = [float(value) for value in values if value is not None]
    return None if not measured else sum(measured) / len(measured)


def lowest_confidence(values: Iterable[str | None]) -> str | None:
    measured = [value for value in values if value in CONFIDENCE_RANK]
    return min(measured, key=lambda value: CONFIDENCE_RANK[value]) if measured else None


def build_inventory(candidate: dict[str, Any]) -> dict[str, Any]:
    candidate_schema = candidate.get("schema_version")
    if candidate_schema != "candidate-index-v2":
        fail("candidate_schema", "Candidate schema must be candidate-index-v2.")
    candidate_sha = candidate.get("candidate_sha256")
    if not isinstance(candidate_sha, str) or not candidate_sha:
        fail("candidate_identity", "Candidate requires candidate_sha256.")
    records = candidate.get("records")
    if not isinstance(records, list):
        fail("candidate_shape", "Candidate requires a records array.")

    paths: list[dict[str, Any]] = []
    nodes_by_key: dict[tuple[str, ...], dict[str, Any]] = {}
    locators: list[dict[str, Any]] = []
    references: list[dict[str, Any]] = []
    seen_path_ids: set[str] = set()
    seen_locator_ids: set[str] = set()
    seen_reference_ids: set[str] = set()

    for record in records:
        if not isinstance(record, dict):
            fail("candidate_shape", "Every candidate record must be an object.")
        path_id = record.get("path_id")
        record_id = record.get("record_id")
        heading_path = record.get("heading_path")
        if not isinstance(path_id, str) or path_id in seen_path_ids:
            fail("path_identity", f"Duplicate or missing path_id: {path_id}")
        if not isinstance(record_id, str) or not record_id:
            fail("record_identity", f"{path_id} requires a non-empty record_id.")
        valid_depth = isinstance(heading_path, list) and len(heading_path) >= 1
        if not valid_depth or not all(isinstance(item, str) and item for item in heading_path):
            fail("heading_path", f"{path_id} requires one or more non-empty string heading levels.")
        seen_path_ids.add(path_id)

        node_ids: list[str] = []
        for level in range(1, len(heading_path) + 1):
            key = tuple(heading_path[:level])
            node = nodes_by_key.get(key)
            if node is None:
                node_id = stable_id("NODE", candidate_sha, {"heading_path": list(key)})
                parent_key = key[:-1]
                node = {
                    "node_id": node_id,
                    "level": level,
                    "role": "main_heading" if level == 1 else "subheading",
                    "label": key[-1],
                    "heading_path": list(key),
                    "parent_node_id": nodes_by_key[parent_key]["node_id"] if parent_key else None,
                    "path_ids": [],
                    "record_ids": [],
                    "direct_path_ids": [],
                }
                nodes_by_key[key] = node
            node_ids.append(node["node_id"])
            if path_id not in node["path_ids"]:
                node["path_ids"].append(path_id)
            if isinstance(record_id, str) and record_id not in node["record_ids"]:
                node["record_ids"].append(record_id)
        nodes_by_key[tuple(heading_path)]["direct_path_ids"].append(path_id)

        locator_ids: list[str] = []
        for assignment in record.get("locator_assignments", []):
            locator_id = assignment.get("locator_id")
            if not isinstance(locator_id, str) or locator_id in seen_locator_ids:
                fail("locator_identity", f"Duplicate or missing locator_id: {locator_id}")
            seen_locator_ids.add(locator_id)
            locator_ids.append(locator_id)
            locators.append({
                "locator_id": locator_id,
                "path_id": path_id,
                "node_ids": node_ids,
                "source_page_label": assignment.get("source_page_label"),
                "document_page": assignment.get("document_page"),
                "mapping_status": assignment.get("mapping_status"),
            })

        reference_ids: list[str] = []
        cross_references = record.get("cross_references")
        if not isinstance(cross_references, list):
            fail("cross_reference_shape", f"{path_id}.cross_references must be an array.")
        if record.get("record_type") == "cross_reference" and not cross_references:
            fail("cross_reference_shape", f"{path_id} is a cross-reference without a reference object.")
        for reference_index, reference in enumerate(cross_references):
            if not isinstance(reference, dict):
                fail("cross_reference_shape", f"{path_id} has a non-object cross-reference.")
            if reference.get("type") not in {"see", "see also"} or not isinstance(reference.get("target"), str) or not reference.get("target"):
                fail("cross_reference_shape", f"{path_id} requires valid see/see also references with non-empty targets.")
            identity = {"record_id": record_id, "path_id": path_id, "reference_index": reference_index}
            reference_id = reference.get("reference_id") or stable_id("XREF", candidate_sha, identity)
            if not isinstance(reference_id, str) or reference_id in seen_reference_ids:
                fail("cross_reference_identity", f"Duplicate or invalid cross-reference identity: {reference_id}")
            seen_reference_ids.add(reference_id)
            reference_ids.append(reference_id)
            references.append({
                "reference_id": reference_id,
                "record_id": record_id,
                "source_path_id": path_id,
                "source_node_id": node_ids[-1],
                "reference_type": reference.get("type"),
                "target_display": reference.get("target"),
                "target_path_id": reference.get("target_path_id"),
            })

        path_record = {
            "path_id": path_id,
            "record_id": record_id,
            "record_type": record.get("record_type"),
            "heading_path": heading_path,
            "node_ids": node_ids,
            "locator_ids": locator_ids,
            "reference_ids": reference_ids,
        }
        paths.append(path_record)

    nodes = sorted(nodes_by_key.values(), key=lambda item: (item["heading_path"], item["node_id"]))
    for node in nodes:
        node["path_ids"].sort()
        node["record_ids"].sort()
        node["direct_path_ids"].sort()
    target_index: dict[str, list[str]] = {}
    for path in paths:
        display = "—".join(path["heading_path"])
        target_index.setdefault(canonical_target(display), []).append(path["path_id"])
    for reference in references:
        if reference.get("target_path_id") is None and isinstance(reference.get("target_display"), str):
            matches = target_index.get(canonical_target(reference["target_display"]), [])
            if len(matches) == 1:
                reference["target_path_id"] = matches[0]
    return {
        "schema_version": "subject-index-item-inventory-v2",
        "candidate_id": candidate.get("candidate_id"),
        "candidate_sha256": candidate_sha,
        "paths": sorted(paths, key=lambda item: item["path_id"]),
        "heading_nodes": nodes,
        "locators": sorted(locators, key=lambda item: item["locator_id"]),
        "cross_references": sorted(references, key=lambda item: item["reference_id"]),
        "counts": {
            "paths": len(paths),
            "heading_nodes": len(nodes),
            "locators": len(locators),
            "cross_references": len(references),
        },
    }


def collect_unique(records: Iterable[dict[str, Any]], key: str, label: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for record in records:
        identity = record.get(key)
        if not isinstance(identity, str) or not identity:
            fail("missing_identity", f"{label} record lacks {key}.")
        if identity in result:
            fail("duplicate_identity", f"Duplicate {label} identity: {identity}")
        result[identity] = record
    return result


def build_v5_evidence_identity(
    candidate: dict[str, Any],
    inventory_sha256: str,
    locator_batches: list[dict[str, Any]],
    locator_paths: list[Path],
    missing_batches: list[dict[str, Any]],
    missing_paths: list[Path],
    structure: dict[str, Any],
    structure_path: Path,
) -> dict[str, str] | None:
    """Return exact V5 projection identity, or None for legacy provenance-poor inputs."""
    audit_documents = [*locator_batches, *missing_batches]
    audit_provenances = [item.get("provenance") for item in audit_documents]
    if not all(isinstance(item, dict) for item in audit_provenances):
        return None
    structure_provenance = structure.get("provenance") if isinstance(structure.get("provenance"), dict) else {}
    identity: dict[str, str] = {"candidate_sha256": candidate["candidate_sha256"]}
    for field in V5_IDENTITY_FIELDS:
        values = {item.get(field) for item in audit_provenances if isinstance(item, dict)}
        if len(values) != 1 or None in values:
            fail("v5_item_assessment_identity_mismatch", f"V5 item-assessment inputs do not bind one exact {field}.", sorted(str(item) for item in values))
        identity[field] = next(iter(values))
        historical_value = structure_provenance.get(field)
        if structure.get("schema_version") == "structure-audit-v4" or historical_value is not None:
            if historical_value != identity[field]:
                fail("v5_item_assessment_identity_mismatch", f"Structure audit {field} differs from the exact chunk-audit identity.", {"structure": historical_value, "audit_set": identity[field]})
    if identity["item_inventory_file_sha256"] != inventory_sha256:
        fail("item_inventory_mismatch", "V5 audit provenance does not bind the exact item inventory supplied for diagnostic grading.")
    benchmark_values = {item.get("provenance", {}).get("benchmark_sha256") for item in locator_batches}
    benchmark_values.update(item.get("benchmark_sha256") for item in missing_batches)
    historical_benchmark = structure_provenance.get("benchmark_sha256")
    if structure.get("schema_version") == "structure-audit-v4" or historical_benchmark is not None:
        benchmark_values.add(historical_benchmark)
    if len(benchmark_values) != 1 or None in benchmark_values:
        fail("v5_item_assessment_identity_mismatch", "V5 item-assessment inputs do not bind one exact benchmark_sha256.", sorted(str(item) for item in benchmark_values))
    identity["benchmark_sha256"] = next(iter(benchmark_values))
    identity["structure_audit_file_sha256"] = sha256_file(structure_path)
    identity["locator_audit_set_sha256"] = canonical_audit_set_hash(
        locator_batches,
        locator_paths,
        (("judgments", "locator_id", "locator_ids"),),
    )
    identity["missing_access_audit_set_sha256"] = canonical_audit_set_hash(
        missing_batches,
        missing_paths,
        (
            ("subject_judgments", "subject_id", "subject_ids"),
            ("reader_task_results", "task_id", "reader_task_ids"),
            ("treatment_judgments", "treatment_id", "treatment_ids"),
        ),
    )
    for document in missing_batches:
        if document["provenance"].get("locator_audit_set_sha256") != identity["locator_audit_set_sha256"]:
            fail("v5_item_assessment_identity_mismatch", "A missing-access audit does not bind the exact locator-audit set used for item grading.", {"chunk_id": document.get("chunk_id")})
    return identity


def apply_caps(score: float | None, defect_records: Iterable[dict[str, Any]]) -> float | None:
    if score is None:
        return None
    caps = [SEVERITY_CAP[item["severity"]] for item in defect_records if item.get("severity") in SEVERITY_CAP]
    return min([score, *caps]) if caps else score


def build_assessments(
    candidate: dict[str, Any],
    inventory: dict[str, Any],
    locator_batches: list[dict[str, Any]],
    missing_batches: list[dict[str, Any]],
    structure: dict[str, Any],
    audit_mode: str,
    evaluation_id: str | None,
    inventory_sha256: str,
    v5_evidence_identity: dict[str, str] | None = None,
    inventory_artifact_path: str | None = None,
) -> dict[str, Any]:
    candidate_sha = candidate.get("candidate_sha256")
    if inventory.get("candidate_sha256") != candidate_sha or structure.get("candidate_sha256") != candidate_sha:
        fail("candidate_mismatch", "Candidate, inventory, and structure audit hashes must match.")
    if audit_mode not in {"full", "pilot"}:
        fail("audit_mode", "audit_mode must be full or pilot.")
    if audit_mode == "full" and (not structure.get("scope_complete") or not structure.get("completion", {}).get("complete")):
        fail("incomplete_structure_audit", "Full item grading requires a scope-complete structure audit with complete node and cross-reference counts.")
    effective_evaluation_id = evaluation_id or structure.get("evaluation_id")
    if not isinstance(effective_evaluation_id, str) or not effective_evaluation_id:
        fail("evaluation_identity", "Item assessments require an evaluation_id.")
    if structure.get("item_inventory_sha256") != inventory_sha256:
        fail("item_inventory_mismatch", "Structure audit does not reference the exact item-inventory file supplied for grading.")
    for label, batches in (("locator", locator_batches), ("missing-access", missing_batches)):
        for batch in batches:
            if batch.get("candidate_sha256") != candidate_sha:
                fail("candidate_mismatch", f"A {label} audit uses a different candidate hash.")
            if effective_evaluation_id and batch.get("evaluation_id") != effective_evaluation_id:
                fail("evaluation_mismatch", f"A {label} audit uses a different evaluation_id.")
    if effective_evaluation_id and structure.get("evaluation_id") != effective_evaluation_id:
        fail("evaluation_mismatch", "Structure audit uses a different evaluation_id.")

    locator_judgments = collect_unique(
        (judgment for batch in locator_batches for judgment in batch.get("judgments", [])),
        "locator_id",
        "locator judgment",
    )
    subject_judgments = collect_unique(
        (judgment for batch in missing_batches for judgment in batch.get("subject_judgments", [])),
        "subject_id",
        "subject judgment",
    )
    expected_subject_ids: list[str] = []
    for batch in missing_batches:
        expected_here = batch.get("expected_subject_ids", [])
        if not isinstance(expected_here, list) or not all(isinstance(item, str) and item for item in expected_here):
            fail("missing_subject_denominator", "Every missing-access audit must declare valid expected_subject_ids.")
        expected_subject_ids.extend(expected_here)
    if len(expected_subject_ids) != len(set(expected_subject_ids)):
        fail("duplicate_identity", "Expected source-subject IDs must be unique across missing-access audits.")
    unexpected_subjects = set(subject_judgments) - set(expected_subject_ids)
    if unexpected_subjects:
        fail("subject_denominator_mismatch", "Source-subject judgments fall outside the frozen expected set.", sorted(unexpected_subjects))
    if audit_mode == "full" and set(subject_judgments) != set(expected_subject_ids):
        fail("incomplete_subject_audit", "Full item grading requires every expected source subject to have a judgment.", sorted(set(expected_subject_ids) - set(subject_judgments)))
    node_judgments = collect_unique(structure.get("node_judgments", []), "node_id", "node judgment")
    reference_judgments = collect_unique(structure.get("cross_reference_judgments", []), "reference_id", "cross-reference judgment")
    defects = structure.get("defects", [])
    if not isinstance(defects, list):
        fail("structure_shape", "structure-audit defects must be an array.")

    locators_by_path: dict[str, list[dict[str, Any]]] = {}
    locator_assessments: list[dict[str, Any]] = []
    for locator in inventory.get("locators", []):
        locator_id = locator["locator_id"]
        judgment = locator_judgments.get(locator_id)
        mapping_status = locator.get("mapping_status")
        if judgment is None:
            if audit_mode == "full" and mapping_status == "resolved":
                fail("incomplete_locator_audit", f"Resolved locator lacks a judgment in full mode: {locator_id}")
            score = 0.0 if mapping_status == "unresolved" else None
            judgment_label = "not_measured" if mapping_status == "resolved" else ("unsupported" if mapping_status == "unresolved" else "uninspectable")
            evidence_ids: list[str] = []
            confidence = None
            severity = "major" if mapping_status == "unresolved" else "none"
            evidence_summary = "The displayed locator does not resolve to a source page." if mapping_status == "unresolved" else "Locator was not measured in this audit."
            treatment_class = "unavailable"
            error_codes: list[str] = []
        else:
            score = LOCATOR_SCORE.get(judgment.get("judgment"))
            judgment_label = judgment.get("judgment")
            evidence_ids = [locator_id]
            confidence = judgment.get("confidence")
            severity = judgment.get("severity")
            evidence_summary = judgment.get("evidence_summary", "")
            treatment_class = judgment.get("treatment_class")
            error_codes = judgment.get("error_codes", [])
        assessment = {
            "locator_id": locator_id,
            "path_id": locator["path_id"],
            "node_ids": locator.get("node_ids", []),
            "source_page_label": locator.get("source_page_label"),
            "document_page": locator.get("document_page"),
            "mapping_status": mapping_status,
            "judgment": judgment_label,
            "treatment_class": treatment_class,
            "error_codes": error_codes,
            "grade_scope": "one_complete_heading_path_and_source_page_assignment",
            "grade": grade(score),
            "severity": severity,
            "confidence": confidence,
            "summary": evidence_summary,
            "evidence_ids": list(dict.fromkeys(evidence_ids)),
        }
        assessment["popover"] = popover(
            f"Locator {locator.get('source_page_label')}",
            evidence_summary,
            assessment["grade"],
            assessment["grade_scope"],
            confidence,
            [
                {"factor_id": "locator_support", "label": "Page support", "status": judgment_label, "score": score, "severity": severity, "applied_cap": None, "explanation": evidence_summary, "error_codes": error_codes, "evidence_ids": assessment["evidence_ids"]},
                {"factor_id": "treatment_class", "label": "Treatment class", "status": treatment_class, "score": TREATMENT_SCORE.get(treatment_class), "explanation": "Whether the cited page gives substantive treatment rather than a passing, attribution-only, citation-only, or incidental occurrence.", "evidence_ids": assessment["evidence_ids"]},
                {"factor_id": "mapping", "label": "Page mapping", "status": mapping_status, "score": None, "explanation": "Whether the displayed locator resolves to exactly one source page.", "evidence_ids": []},
                {"factor_id": "confidence", "label": "Audit confidence", "status": confidence or "not_measured", "score": None, "explanation": "Confidence in the source-grounded judgment; confidence does not change the grade.", "evidence_ids": []},
            ],
            assessment["evidence_ids"],
            navigation={"path_id": assessment["path_id"], "node_ids": assessment["node_ids"]},
        )
        locator_assessments.append(assessment)
        locators_by_path.setdefault(locator["path_id"], []).append(assessment)

    subjects_by_path: dict[str, list[dict[str, Any]]] = {}
    source_subject_assessments: list[dict[str, Any]] = []
    for subject_id in sorted(expected_subject_ids):
        judgment = subject_judgments.get(subject_id)
        score = COVERAGE_SCORE.get(judgment.get("coverage")) if judgment else None
        record = {
            "subject_id": subject_id,
            "priority": judgment.get("priority") if judgment else None,
            "coverage": judgment.get("coverage") if judgment else "not_measured",
            "matched_path_ids": judgment.get("matched_path_ids", []) if judgment else [],
            "missed_document_pages": judgment.get("missed_document_pages", []) if judgment else [],
            "grade_scope": "access_to_one_frozen_source_subject",
            "grade": grade(score),
            "severity": judgment.get("severity") if judgment else None,
            "confidence": judgment.get("confidence") if judgment else None,
            "evidence_ids": [subject_id],
        }
        record["popover"] = popover(
            f"Source subject {subject_id}",
            "Measures whether the independently discovered source subject has useful access in the candidate.",
            record["grade"],
            record["grade_scope"],
            record["confidence"],
            [{"factor_id": "concept_coverage", "label": "Meaningful coverage", "status": judgment.get("coverage") if judgment else "not_measured", "score": score, "explanation": "Coverage is judged from the frozen source benchmark, not discovered from the candidate.", "evidence_ids": [subject_id]}],
            [subject_id],
            navigation={"matched_path_ids": record["matched_path_ids"]},
        )
        source_subject_assessments.append(record)
        if judgment:
            for path_id in judgment.get("matched_path_ids", []):
                subjects_by_path.setdefault(path_id, []).append(judgment)

    defects_by_affected_id: dict[str, list[dict[str, Any]]] = {}
    for defect in defects:
        for affected_id in defect_affected_ids(defect):
            defects_by_affected_id.setdefault(affected_id, []).append(defect)

    node_assessments: list[dict[str, Any]] = []
    node_component_scores: dict[str, dict[str, float | None]] = {}
    inventory_node_ids = {node["node_id"] for node in inventory.get("heading_nodes", [])}
    if audit_mode == "full" and structure.get("scope_complete"):
        if set(structure.get("expected_node_ids", [])) != inventory_node_ids:
            fail("node_inventory_mismatch", "Structure audit expected_node_ids do not exactly match the item inventory.")
        missing_nodes = sorted(inventory_node_ids - set(node_judgments))
        if missing_nodes:
            fail("incomplete_node_audit", "Full structure audit lacks heading-node judgments.", missing_nodes)

    for node in inventory.get("heading_nodes", []):
        node_id = node["node_id"]
        judgment = node_judgments.get(node_id)
        components: list[dict[str, Any]] = []
        scores: dict[str, float | None] = {}
        for source_name, dimension in STRUCTURE_COMPONENTS.items():
            source = judgment.get("component_judgments", {}).get(source_name, {}) if judgment else {}
            status = source.get("status", "uninspectable") if audit_mode == "full" else source.get("status", "not_applicable")
            score = STRUCTURE_STATUS_SCORE.get(status)
            relevant = ordered_unique_defects(
                item
                for item in defects_by_affected_id.get(node_id, [])
                if defect_dimension(item) == dimension
            )
            score = apply_caps(score, relevant)
            cap_records = severity_cap_records(relevant)
            scores[dimension] = score
            components.append({
                "dimension_id": dimension,
                "status": status,
                "score": None if score is None else round(score, 2),
                "weight": COMPONENT_WEIGHTS[dimension],
                "severity_caps": cap_records,
                "applied_cap": min((item["maximum_score"] for item in cap_records), default=None),
                "summary": source.get("summary", ""),
                "evidence_ids": list(dict.fromkeys([*source.get("evidence_ids", []), *[item.get("defect_id") for item in relevant]])),
            })
        node_component_scores[node_id] = scores
        node_score = weighted_mean((item["score"], item["weight"]) for item in components)
        node_record = {
            **node,
            "grade_scope": "heading_wording_and_structural_role",
            "grade": grade(node_score),
            "component_results": components,
            "summary": judgment.get("summary", "Heading node was not measured.") if judgment else "Heading node was not measured.",
            "confidence": judgment.get("confidence") if judgment else None,
            "evidence_ids": judgment.get("evidence_ids", []) if judgment else [],
        }
        node_record["popover"] = popover(
            " — ".join(node["heading_path"]),
            node_record["summary"],
            node_record["grade"],
            node_record["grade_scope"],
            node_record["confidence"],
            [
                {
                    "factor_id": item["dimension_id"],
                    "label": item["dimension_id"].replace("_", " ").title(),
                    "status": item["status"],
                    "score": item["score"],
                    "weight": item["weight"],
                    "severity_caps": item["severity_caps"],
                    "applied_cap": item["applied_cap"],
                    "explanation": item["summary"],
                    "evidence_ids": item["evidence_ids"],
                }
                for item in components
            ],
            node_record["evidence_ids"],
            navigation={"node_id": node_id, "parent_node_id": node.get("parent_node_id"), "path_ids": node.get("path_ids", [])},
        )
        node_assessments.append(node_record)

    path_assessments: list[dict[str, Any]] = []
    for path in inventory.get("paths", []):
        path_id = path["path_id"]
        path_locators = locators_by_path.get(path_id, [])
        path_subjects = subjects_by_path.get(path_id, [])
        # Preserve intentional path/node/locator source order for lookup. Defect
        # projection order is a separate identity-set concern governed by
        # ITEM-PROJECTION-DEFECT-ID-ASC-V1.
        affected_ids = list(dict.fromkeys([
            path_id,
            *path.get("node_ids", []),
            *path.get("locator_ids", []),
        ]))
        path_defects = ordered_unique_defects(
            item
            for affected_id in affected_ids
            for item in defects_by_affected_id.get(affected_id, [])
        )

        locator_score = mean(item["grade"]["score"] for item in path_locators)
        treatment_values = []
        for locator in path.get("locator_ids", []):
            judgment = locator_judgments.get(locator)
            treatment_values.append(TREATMENT_SCORE.get(judgment.get("treatment_class")) if judgment else None)
        selectivity_score = mean(treatment_values)
        coverage_score = weighted_mean(
            (COVERAGE_SCORE.get(item.get("coverage")), PRIORITY_WEIGHT.get(item.get("priority"), 1.0)) for item in path_subjects
        )
        conceptual_score = min(
            (node_component_scores.get(node_id, {}).get("conceptual_stance_fidelity") for node_id in path.get("node_ids", [])),
            default=None,
            key=lambda value: float("inf") if value is None else value,
        )
        if conceptual_score is None:
            measured = [node_component_scores.get(node_id, {}).get("conceptual_stance_fidelity") for node_id in path.get("node_ids", [])]
            conceptual_score = mean(measured)
        findability_score = mean(node_component_scores.get(node_id, {}).get("findability_navigation") for node_id in path.get("node_ids", []))
        path_reference_ids = path.get("reference_ids")
        if not isinstance(path_reference_ids, list):
            fail("inventory_shape", f"{path.get('path_id')} requires reference_ids.")
        reference_scores = []
        for reference_id in path_reference_ids:
            reference_judgment = reference_judgments.get(reference_id)
            reference_scores.append(REFERENCE_SCORE.get(reference_judgment.get("judgment")) if reference_judgment else None)
        measured_findability = [value for value in [findability_score, *reference_scores] if value is not None]
        findability_score = min(measured_findability) if measured_findability else None
        mechanics_score = mean(node_component_scores.get(node_id, {}).get("mechanics_consistency") for node_id in path.get("node_ids", []))
        component_values = {
            "meaningful_coverage": coverage_score,
            "editorial_selectivity": selectivity_score,
            "conceptual_stance_fidelity": conceptual_score,
            "page_reference_reliability": locator_score,
            "findability_navigation": findability_score,
            "mechanics_consistency": mechanics_score,
        }
        measured_locator_count = sum(item["grade"]["score"] is not None for item in path_locators)
        component_evidence = {
            "meaningful_coverage": [item.get("subject_id") for item in path_subjects],
            "editorial_selectivity": path.get("locator_ids", []),
            "conceptual_stance_fidelity": path.get("node_ids", []),
            "page_reference_reliability": path.get("locator_ids", []),
            "findability_navigation": [*path.get("node_ids", []), *path_reference_ids],
            "mechanics_consistency": path.get("node_ids", []),
        }
        component_summaries = {
            "meaningful_coverage": f"Priority-weighted coverage of {len(path_subjects)} frozen source subject(s) explicitly matched to this path.",
            "editorial_selectivity": f"Mean substantive-treatment classification for {measured_locator_count} measured locator(s).",
            "conceptual_stance_fidelity": "Conceptual and stance judgments for every heading node in the complete path, with applicable defect caps.",
            "page_reference_reliability": f"Mean diagnostic grade for {measured_locator_count} measured locator(s) attached to this path.",
            "findability_navigation": "Heading-node architecture and any cross-reference judgment associated with this path, with applicable defect caps.",
            "mechanics_consistency": "Mechanical judgments for every heading node in the path, with applicable defect caps.",
        }
        component_results: list[dict[str, Any]] = []
        for dimension, value in component_values.items():
            relevant = [item for item in path_defects if defect_dimension(item) == dimension]
            adjusted = apply_caps(value, relevant)
            cap_records = severity_cap_records(relevant)
            component_results.append({
                "dimension_id": dimension,
                "score": None if adjusted is None else round(adjusted, 2),
                "weight": COMPONENT_WEIGHTS[dimension],
                "measurement_status": "measured" if adjusted is not None else "not_measured",
                "severity_caps": cap_records,
                "applied_cap": min((item["maximum_score"] for item in cap_records), default=None),
                "summary": component_summaries[dimension],
                "evidence_ids": list(dict.fromkeys([
                    *component_evidence[dimension],
                    *[item.get("defect_id") for item in relevant],
                ])),
            })
        path_score = weighted_mean((item["score"], item["weight"]) for item in component_results)
        path_confidence = lowest_confidence([
            *[locator_judgments.get(locator_id, {}).get("confidence") for locator_id in path.get("locator_ids", [])],
            *[item.get("confidence") for item in path_subjects],
            *[node_judgments.get(node_id, {}).get("confidence") for node_id in path.get("node_ids", [])],
            *[reference_judgments.get(reference_id, {}).get("confidence") for reference_id in path_reference_ids],
        ])
        path_record = {
            **path,
            "grade_scope": "complete_heading_path_as_delivered",
            "grade": grade(path_score),
            "confidence": path_confidence,
            "component_results": component_results,
            "defect_ids": sorted(item.get("defect_id") for item in path_defects if item.get("defect_id")),
            "matched_subject_ids": sorted(item.get("subject_id") for item in path_subjects if item.get("subject_id")),
            "evidence_ids": sorted(set(path.get("locator_ids", [])) | set(item.get("defect_id") for item in path_defects if item.get("defect_id"))),
        }
        if path_reference_ids:
            path_record["evidence_ids"] = sorted(set(path_record["evidence_ids"]) | set(path_reference_ids))
        path_record["popover"] = popover(
            " — ".join(path["heading_path"]),
            "Diagnostic grade for the complete heading path as delivered, including its measured locators and path-specific audit findings.",
            path_record["grade"],
            path_record["grade_scope"],
            path_record["confidence"],
            [
                {
                    "factor_id": item["dimension_id"],
                    "label": item["dimension_id"].replace("_", " ").title(),
                    "status": item["measurement_status"],
                    "score": item["score"],
                    "weight": item["weight"],
                    "severity_caps": item["severity_caps"],
                    "applied_cap": item["applied_cap"],
                    "explanation": item["summary"] + " This factor is reweighted only when it is not applicable or not measured; it is never treated as zero.",
                    "evidence_ids": item["evidence_ids"],
                }
                for item in component_results
            ],
            path_record["evidence_ids"],
            navigation={
                "path_id": path_id,
                "node_ids": path.get("node_ids", []),
                "locator_ids": path.get("locator_ids", []),
                "reference_ids": path_reference_ids,
            },
        )
        path_assessments.append(path_record)

    cross_reference_assessments: list[dict[str, Any]] = []
    inventory_reference_ids = {item["reference_id"] for item in inventory.get("cross_references", [])}
    if audit_mode == "full" and structure.get("scope_complete"):
        if set(structure.get("expected_cross_reference_ids", [])) != inventory_reference_ids:
            fail("cross_reference_inventory_mismatch", "Structure audit expected_cross_reference_ids do not exactly match the item inventory.")
        missing_references = sorted(inventory_reference_ids - set(reference_judgments))
        if missing_references:
            fail("incomplete_cross_reference_audit", "Full structure audit lacks cross-reference judgments.", missing_references)
    for reference in inventory.get("cross_references", []):
        reference_id = reference["reference_id"]
        judgment = reference_judgments.get(reference_id)
        score = REFERENCE_SCORE.get(judgment.get("judgment")) if judgment else None
        relevant = ordered_unique_defects(
            item
            for item in defects_by_affected_id.get(reference_id, [])
            if defect_dimension(item) == "findability_navigation"
        )
        score = apply_caps(score, relevant)
        cap_records = severity_cap_records(relevant)
        reference_record = {
            **reference,
            "grade_scope": "one_cross_reference_relationship",
            "grade": grade(score),
            "judgment": judgment.get("judgment", "not_measured") if judgment else "not_measured",
            "summary": judgment.get("summary", "Cross-reference was not measured.") if judgment else "Cross-reference was not measured.",
            "confidence": judgment.get("confidence") if judgment else None,
            "evidence_ids": list(dict.fromkeys([
                *(judgment.get("evidence_ids", []) if judgment else []),
                *[item.get("defect_id") for item in relevant],
            ])),
        }
        reference_record["popover"] = popover(
            f"{reference.get('reference_type')} {reference.get('target_display')}",
            reference_record["summary"],
            reference_record["grade"],
            reference_record["grade_scope"],
            reference_record["confidence"],
            [{"factor_id": "cross_reference_validity", "label": "Cross-reference validity", "status": reference_record["judgment"], "score": score, "severity_caps": cap_records, "applied_cap": min((item["maximum_score"] for item in cap_records), default=None), "explanation": reference_record["summary"], "evidence_ids": reference_record["evidence_ids"]}],
            reference_record["evidence_ids"],
            navigation={"source_path_id": reference.get("source_path_id"), "source_node_id": reference.get("source_node_id"), "target_path_id": reference.get("target_path_id")},
        )
        cross_reference_assessments.append(reference_record)

    collections = {
        "locators": locator_assessments,
        "paths": path_assessments,
        "heading_nodes": node_assessments,
        "cross_references": cross_reference_assessments,
        "source_subjects": source_subject_assessments,
    }
    summary = {
        name: {
            "total": len(items),
            "graded": sum(item["grade"]["score"] is not None for item in items),
            "not_measured": sum(item["grade"]["score"] is None for item in items),
            "bands": {
                band: sum(item["grade"]["band"] == band for item in items)
                for band in ("excellent", "strong", "mixed", "weak", "poor", "not_measured")
            },
        }
        for name, items in collections.items()
    }
    result = {
        "schema_version": "subject-index-item-assessments-v1",
        "grading_policy": GRADING_POLICY,
        "evaluation_id": effective_evaluation_id,
        "candidate_id": candidate.get("candidate_id"),
        "candidate_sha256": candidate_sha,
        "item_inventory_sha256": inventory_sha256,
        "audit_mode": audit_mode,
        "scope_complete": bool(audit_mode == "full" and structure.get("scope_complete")),
        "grade_disclosure": "Item grades are diagnostic display summaries derived from frozen evidence. They do not add to or replace the six-dimension 100-point rubric. Not-measured items are neutral, not failures.",
        "color_legend": [
            {"band": "excellent", "minimum_score": 90, "color_token": "grade_excellent"},
            {"band": "strong", "minimum_score": 80, "color_token": "grade_strong"},
            {"band": "mixed", "minimum_score": 70, "color_token": "grade_mixed"},
            {"band": "weak", "minimum_score": 60, "color_token": "grade_weak"},
            {"band": "poor", "minimum_score": 0, "color_token": "grade_poor"},
            {"band": "not_measured", "minimum_score": None, "color_token": "grade_neutral"},
        ],
        "locator_assessments": locator_assessments,
        "path_assessments": path_assessments,
        "heading_node_assessments": node_assessments,
        "cross_reference_assessments": cross_reference_assessments,
        "source_subject_assessments": source_subject_assessments,
        "summary": summary,
    }
    if v5_evidence_identity is not None:
        if not isinstance(inventory_artifact_path, str) or not inventory_artifact_path:
            fail("item_inventory_reference_required", "Projection-safe V5 item assessments require a resolvable item-inventory artifact path.")
        assessment_sets = {
            "locators": (inventory.get("locators", []), "locator_id"),
            "paths": (inventory.get("paths", []), "path_id"),
            "heading_nodes": (inventory.get("heading_nodes", []), "node_id"),
            "cross_references": (inventory.get("cross_references", []), "reference_id"),
            "source_subjects": (source_subject_assessments, "subject_id"),
        }
        assessed_collections = {
            "locators": locator_assessments,
            "paths": path_assessments,
            "heading_nodes": node_assessments,
            "cross_references": cross_reference_assessments,
            "source_subjects": source_subject_assessments,
        }
        completeness: dict[str, dict[str, Any]] = {}
        for family, (expected_records, id_field) in assessment_sets.items():
            expected_ids = [item[id_field] for item in expected_records]
            assessed_ids = [item[id_field] for item in assessed_collections[family]]
            if len(expected_ids) != len(set(expected_ids)) or set(expected_ids) != set(assessed_ids) or len(assessed_ids) != len(set(assessed_ids)):
                fail("item_assessment_set_mismatch", f"V5 {family} assessments do not exactly cover their frozen denominator.", {"expected": sorted(expected_ids), "assessed": sorted(assessed_ids)})
            completeness[family] = {
                "expected": len(expected_ids),
                "assessed": len(assessed_ids),
                "unique": True,
                "complete": True,
                "id_set_sha256": canonical_id_set_hash(expected_ids),
            }
        result.update({
            "schema_version": "subject-index-item-assessments-v2",
            "item_inventory_artifact": {
                "schema_version": inventory.get("schema_version"),
                "artifact_path": inventory_artifact_path,
                "sha256": inventory_sha256,
            },
            "evidence_identity": v5_evidence_identity,
            "assessment_completeness": completeness,
        })
    return result


def rebuild_summary(result: dict[str, Any]) -> None:
    collections = {
        "locators": result["locator_assessments"],
        "paths": result["path_assessments"],
        "heading_nodes": result["heading_node_assessments"],
        "cross_references": result["cross_reference_assessments"],
        "source_subjects": result["source_subject_assessments"],
    }
    result["summary"] = {
        name: {
            "total": len(items),
            "graded": sum(item["grade"]["score"] is not None for item in items),
            "not_measured": sum(item["grade"]["score"] is None for item in items),
            "bands": {
                band: sum(item["grade"]["band"] == band for item in items)
                for band in ("excellent", "strong", "mixed", "weak", "poor", "not_measured")
            },
        }
        for name, items in collections.items()
    }


def build_v6_assessments(
    result: dict[str, Any],
    locator_batches: list[dict[str, Any]],
    structure: dict[str, Any],
) -> dict[str, Any]:
    """Upgrade a projection-safe V2 item artifact to the V6 grading policy."""

    if result.get("schema_version") != "subject-index-item-assessments-v2":
        fail(
            "v6_item_evidence_identity_required",
            "V6 diagnostic grading requires a projection-safe V2 evidence identity before upgrade.",
        )
    judgment_by_id = collect_unique(
        (judgment for batch in locator_batches for judgment in batch.get("judgments", [])),
        "locator_id",
        "locator judgment",
    )
    defects = structure.get("defects", [])
    if not isinstance(defects, list):
        fail("structure_shape", "structure-audit defects must be an array.")

    locator_by_id: dict[str, dict[str, Any]] = {}
    credit_tiers: dict[str, int] = {}
    for assessment in result["locator_assessments"]:
        locator_id = assessment["locator_id"]
        judgment = judgment_by_id.get(locator_id)
        if judgment is None:
            score = 0.0 if assessment.get("mapping_status") == "unresolved" else None
            credit = "0" if score == 0 else None
            tier = "other_unsupported" if score == 0 else "uninspectable"
            rationale = assessment.get("summary", "Locator was not measured.")
            disqualifying_codes: list[str] = []
            disqualifying_defect_ids: list[str] = []
        else:
            try:
                assignment = assign_locator_credit(judgment, defects)
            except ValueError as exc:
                fail(
                    "inconsistent_locator_evidence_state",
                    f"Locator {locator_id} cannot receive a V6 diagnostic grade.",
                    str(exc).split(";"),
                )
            score = assignment.diagnostic_grade
            credit = (
                None
                if assignment.reliability_credit is None
                else format(assignment.reliability_credit.normalize(), "f")
            )
            tier = assignment.credit_tier
            rationale = assignment.rationale
            disqualifying_codes = list(assignment.disqualifying_codes)
            disqualifying_defect_ids = list(assignment.disqualifying_defect_ids)
            assessment["source_scope_status"] = assignment.source_scope_status
        assessment["grade"] = grade(score)
        assessment["dimension_reliability_credit"] = credit
        assessment["credit_tier"] = tier
        assessment["disqualifying_codes"] = disqualifying_codes
        assessment["disqualifying_defect_ids"] = disqualifying_defect_ids
        assessment["summary"] = rationale
        assessment["popover"]["summary"] = rationale
        assessment["popover"]["grade"] = assessment["grade"]
        for factor in assessment["popover"].get("factors", []):
            if factor.get("factor_id") == "locator_support":
                factor["score"] = score
                factor["explanation"] = rationale
        locator_by_id[locator_id] = assessment
        credit_tiers[tier] = credit_tiers.get(tier, 0) + 1

    for path in result["path_assessments"]:
        locator_scores = [
            locator_by_id[locator_id]["grade"]["score"]
            for locator_id in path.get("locator_ids", [])
            if locator_id in locator_by_id
        ]
        raw_locator_score = mean(locator_scores)
        page_component = next(
            (
                item
                for item in path.get("component_results", [])
                if item.get("dimension_id") == "page_reference_reliability"
            ),
            None,
        )
        if page_component is not None:
            applied_cap = page_component.get("applied_cap")
            adjusted = raw_locator_score
            if adjusted is not None and applied_cap is not None:
                adjusted = min(adjusted, applied_cap)
            page_component["score"] = None if adjusted is None else round(adjusted, 2)
            page_component["measurement_status"] = (
                "measured" if adjusted is not None else "not_measured"
            )
            page_component["summary"] = (
                "Mean V6 diagnostic locator grade (100/70/25/0) for this path. "
                "This presentation value does not replace weighted locator precision in the dimension formula."
            )
        path_score = weighted_mean(
            (item.get("score"), item.get("weight", 0))
            for item in path.get("component_results", [])
        )
        path["grade"] = grade(path_score)
        path["popover"]["grade"] = path["grade"]
        for factor in path["popover"].get("factors", []):
            if factor.get("factor_id") == "page_reference_reliability" and page_component:
                factor["score"] = page_component["score"]
                factor["status"] = page_component["measurement_status"]
                factor["explanation"] = page_component["summary"]

    result["schema_version"] = "subject-index-item-assessments-v3"
    result["grading_policy"] = V6_GRADING_POLICY
    result["grade_disclosure"] = (
        "V6 item grades are non-additive diagnostic presentation values. Locator grades are "
        "100, 70, 25, 0, or neutral; they are never averaged to reconstruct the 100-point score. "
        "A grade of 25 remains editorially unjustified and receives zero selectivity credit."
    )
    result["locator_grading_provenance"] = {
        "dimension_credit_mapping": {
            "supported": "1",
            "partially_supported": "0.5",
            "eligible_weak_presence": "0.25",
            "other_unsupported": "0",
            "uninspectable": None,
        },
        "diagnostic_grade_mapping": {
            "supported": 100,
            "partially_supported": 70,
            "eligible_weak_presence": 25,
            "other_unsupported": 0,
            "uninspectable": None,
        },
        "selectivity_mapping_unchanged": True,
        "weak_presence_selectivity_credit": 0,
        "counts_by_credit_tier": dict(sorted(credit_tiers.items())),
    }
    rebuild_summary(result)
    return result


def command_build_inventory(args: argparse.Namespace) -> None:
    candidate = load_json(Path(args.candidate))
    result = build_inventory(candidate)
    if args.output:
        save_json(Path(args.output), result)
    emit({"ok": True, **result, "artifact_written": args.output})


def command_build_assessments(args: argparse.Namespace) -> None:
    candidate = load_json(Path(args.candidate))
    inventory_path = Path(args.inventory).resolve()
    inventory = load_json(inventory_path)
    inventory_sha256 = sha256_file(inventory_path)
    locator_paths = [Path(path).resolve() for path in args.locator_audit]
    missing_paths = [Path(path).resolve() for path in args.missing_access_audit]
    structure_path = Path(args.structure_audit).resolve()
    locator_batches = [load_json(path) for path in locator_paths]
    missing_batches = [load_json(path) for path in missing_paths]
    structure = load_json(structure_path)
    output_path = Path(args.output).resolve()
    v5_evidence_identity = build_v5_evidence_identity(
        candidate,
        inventory_sha256,
        locator_batches,
        locator_paths,
        missing_batches,
        missing_paths,
        structure,
        structure_path,
    )
    inventory_artifact_path = os.path.relpath(inventory_path, output_path.parent).replace(os.sep, "/")
    result = build_assessments(
        candidate,
        inventory,
        locator_batches,
        missing_batches,
        structure,
        args.audit_mode,
        args.evaluation_id,
        inventory_sha256,
        v5_evidence_identity,
        inventory_artifact_path if v5_evidence_identity is not None else None,
    )
    if args.grading_policy == V6_GRADING_POLICY:
        result = build_v6_assessments(result, locator_batches, structure)
    if args.output:
        save_json(output_path, result)
    emit({"ok": True, **result, "artifact_written": args.output})


def command_upgrade_v6_assessments(args: argparse.Namespace) -> None:
    """Upgrade an exact projection-safe V5 item artifact for score-only migration."""

    from dimension_score_cli import validate_schema_document

    item_path = Path(args.item_assessments).resolve()
    locator_paths = [Path(path).resolve() for path in args.locator_audit]
    structure_path = Path(args.structure_audit).resolve()
    output_path = Path(args.output).resolve()
    result = load_json(item_path)
    locator_batches = [load_json(path) for path in locator_paths]
    structure = load_json(structure_path)
    validate_schema_document(result, "item-assessments-v2.schema.json", "V5 item assessments")
    identity = result["evidence_identity"]
    expected_locator_set = canonical_audit_set_hash(
        locator_batches,
        locator_paths,
        (("judgments", "locator_id", "locator_ids"),),
    )
    if identity.get("locator_audit_set_sha256") != expected_locator_set:
        fail(
            "v6_item_evidence_identity_mismatch",
            "The supplied locator-audit set is not the exact set bound by V5 item assessments.",
        )
    if identity.get("structure_audit_file_sha256") != sha256_file(structure_path):
        fail(
            "v6_item_evidence_identity_mismatch",
            "The supplied structure audit is not the exact file bound by V5 item assessments.",
        )
    result = build_v6_assessments(result, locator_batches, structure)
    validate_schema_document(result, "item-assessments-v3.schema.json", "V6 item assessments")
    protected = {item_path, structure_path, *locator_paths}
    if output_path in protected or (output_path.exists() and any(os.path.samefile(output_path, path) for path in protected if path.exists())):
        fail("output_aliases_frozen_input", "V6 item output must not overwrite a frozen V5 artifact.")
    save_json(output_path, result)
    emit({"ok": True, **result, "artifact_written": args.output})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    inventory = subparsers.add_parser("build-inventory")
    inventory.add_argument("--candidate", required=True)
    inventory.add_argument("--output", required=True)
    inventory.set_defaults(func=command_build_inventory)

    assessments = subparsers.add_parser("build-assessments")
    assessments.add_argument("--candidate", required=True)
    assessments.add_argument("--inventory", required=True)
    assessments.add_argument("--locator-audit", nargs="+", required=True)
    assessments.add_argument("--missing-access-audit", nargs="+", required=True)
    assessments.add_argument("--structure-audit", required=True)
    assessments.add_argument("--audit-mode", choices=["full", "pilot"], required=True)
    assessments.add_argument("--evaluation-id")
    assessments.add_argument(
        "--grading-policy",
        choices=[GRADING_POLICY, V6_GRADING_POLICY],
        default=GRADING_POLICY,
        help="Select the historical V5 diagnostic mapping or the V6 100/70/25/0 mapping.",
    )
    assessments.add_argument("--output", required=True)
    assessments.set_defaults(func=command_build_assessments)

    upgrade = subparsers.add_parser(
        "upgrade-v6-assessments",
        help="Upgrade exact projection-safe V5 item assessments to the V6 diagnostic policy.",
    )
    upgrade.add_argument("--item-assessments", required=True)
    upgrade.add_argument("--locator-audit", nargs="+", required=True)
    upgrade.add_argument("--structure-audit", required=True)
    upgrade.add_argument("--output", required=True)
    upgrade.set_defaults(func=command_upgrade_v6_assessments)
    return parser


def main() -> None:
    emit({
        "ok": False,
        "error": {
            "code": "unsupported_legacy_cli",
            "message": "This module is retained only as an internal projection dependency. Use item_grade_v7_cli.py.",
        },
    }, 2)


if __name__ == "__main__":
    main()
