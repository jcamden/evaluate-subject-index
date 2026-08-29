#!/usr/bin/env python3
"""Deterministic formula, boundary, migration, and adversarial tests for V5."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from decimal import Decimal
from pathlib import Path

import jsonschema


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
SCHEMAS = SKILL_ROOT / "references" / "schemas"
FIXTURES = SKILL_ROOT / "tests"
TEST_METHODOLOGY_COMMIT = "6" * 40
TEST_MIGRATION_TIMESTAMP = "2026-08-29T02:00:00Z"
MIGRATION_METADATA_ARGS = ("--methodology-commit", TEST_METHODOLOGY_COMMIT, "--migration-timestamp", TEST_MIGRATION_TIMESTAMP)
sys.path.insert(0, str(SCRIPTS))

import dimension_score_cli as v5  # noqa: E402
import score_cli as v4  # noqa: E402
import state_cli as state_manager  # noqa: E402


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_cli(script: str, *arguments: object, expect_ok: bool = True) -> dict:
    completed = subprocess.run(
        [sys.executable, str(SCRIPTS / script), *map(str, arguments)],
        cwd=SKILL_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"{script} emitted no JSON\nstdout={completed.stdout}\nstderr={completed.stderr}") from exc
    if expect_ok and (completed.returncode != 0 or payload.get("ok") is not True):
        raise AssertionError(f"{script} failed\nstdout={completed.stdout}\nstderr={completed.stderr}")
    if not expect_ok and completed.returncode == 0:
        raise AssertionError(f"{script} unexpectedly succeeded: {completed.stdout}")
    return payload


def component(status: str, *evidence: str) -> dict:
    return {"status": status, "summary": status, "evidence_ids": list(evidence)}


def node(number: int, concept: str = "passes", architecture: str = "passes", mechanics: str = "passes", evidence: tuple[str, ...] = ()) -> dict:
    return {
        "node_id": f"NODE-{number:04d}",
        "heading_path": [f"Heading {number}"],
        "role": "main_heading",
        "component_judgments": {
            "conceptual_stance_fidelity": component(concept, *evidence),
            "heading_access_architecture": component(architecture, *evidence),
            "mechanics_consistency": component(mechanics, *evidence),
        },
        "summary": "Synthetic node.",
        "confidence": "high",
        "evidence_ids": list(evidence),
    }


def defect(
    defect_id: str,
    owner: str,
    code: str,
    severity: str,
    kind: str = "generic",
    affected: list[str] | None = None,
    source_sections: list[str] | None = None,
    structural_sections: list[str] | None = None,
    applicable: int = 100,
    structural_denominator: int = 2,
    high_priority: bool = False,
    family: str = "synthetic-family",
) -> dict:
    affected = affected or ["NODE-0001"]
    source_sections = source_sections or ["CHUNK-001"]
    structural_sections = structural_sections or ["NODE-0001"]
    if severity == "critical" and kind in {"fabricated_locator", "nonexistent_locator", "out_of_scope_locator"}:
        basis, consequence = "fabrication", "misleads"
    elif severity == "critical" and kind in {"stance_reversal", "misleading_relationship"}:
        basis, consequence = "central_reversal", "misleads"
    elif severity == "critical":
        basis, consequence = "broken_scope", "blocks"
    elif severity == "major" and kind in {"stance_reversal", "misleading_relationship", "misleading_access_route"}:
        basis, consequence = "materially_misleading", "misleads"
    elif severity == "major":
        basis, consequence = "blocked_retrieval", "blocks"
    elif severity == "minor":
        basis, consequence = "localized_repairable_friction", "slows"
    else:
        basis, consequence = "no_retrieval_consequence", "none"
    return {
        "defect_id": defect_id,
        "code": code,
        "dimension_owner": owner,
        "severity": severity,
        "severity_basis": basis,
        "retrieval_consequence": consequence,
        "defect_kind": kind,
        "affected_item_ids": affected,
        "affected_source_sections": source_sections,
        "affected_structural_sections": structural_sections,
        "root_cause_family": family,
        "affected_count": len(affected),
        "applicable_count": applicable,
        "affected_rate": v5.rounded_rate(len(affected), applicable),
        "source_section_denominator": 1,
        "source_section_rate": v5.rounded_rate(len(source_sections), 1),
        "structural_section_denominator": structural_denominator,
        "structural_section_rate": v5.rounded_rate(len(structural_sections), structural_denominator),
        "high_priority_access_destroyed": high_priority,
    }


def base_documents(subject_count: int = 2, uninspectable_major: bool = False) -> tuple[dict, dict, dict]:
    locators = []
    subjects = []
    tasks = []
    treatments = []
    for index in range(1, subject_count + 1):
        subject_id = f"SUBJ-{index:04d}"
        priority = "essential" if index == 1 else "major"
        coverage = "uninspectable" if uninspectable_major and index == subject_count else "complete"
        subjects.append({
            "subject_id": subject_id,
            "priority": priority,
            "coverage": coverage,
            "direct_access": coverage != "uninspectable",
            "cross_reference_access": False,
            "stance_preserved": "yes" if coverage != "uninspectable" else "uninspectable",
            "matched_path_ids": [f"PATH-{index:04d}"] if coverage != "uninspectable" else [],
            "expected_document_pages": [index],
            "found_document_pages": [index] if coverage != "uninspectable" else [],
            "missed_document_pages": [],
            "severity": "none",
            "confidence": "high",
        })
        tasks.append({"task_id": f"TASK-{index:04d}", "subject_ids": [subject_id], "result": "succeeds", "access_mode": "direct", "matched_path_ids": [f"PATH-{index:04d}"], "severity": "none", "confidence": "high", "evidence_ids": []})
        treatments.append({"treatment_id": f"TREAT-{index:04d}", "subject_id": subject_id, "document_page": index, "locator_class": "principal", "status": "found", "evidence_ids": []})
        locator = {
            "locator_id": f"LOC-{index:04d}",
            "path_id": f"PATH-{index:04d}",
            "complete_heading_path": [f"Heading {index}"],
            "document_page": index,
            "source_page_label": str(index),
            "source_scope_status": "indexable",
            "treatment_class": "substantive",
            "judgment": "supported",
            "evidence_summary": "Synthetic support.",
            "confidence": "high",
            "error_codes": [],
            "severity": "none",
        }
        locators.append(locator)
        locators.append({**locator, "locator_id": f"LOC-DUP-{index:04d}"})
    locator = {
        "schema_version": "locator-audit-v1",
        "evaluation_id": "eval-v5",
        "candidate_sha256": "a" * 64,
        "chunk_id": "CHUNK-001",
        "expected_locator_ids": [item["locator_id"] for item in locators],
        "judgments": locators,
        "completion": {"expected": len(locators), "judged": len(locators), "unique": True, "complete": True},
        "provenance": {
            "source_sha256": "d" * 64,
            "benchmark_sha256": "b" * 64,
            "benchmark_lock_sha256": "e" * 64,
            "policy_sha256": "f" * 64,
            "page_map_sha256": "1" * 64,
            "chunk_manifest_sha256": "2" * 64,
            "normalized_candidate_file_sha256": "3" * 64,
            "item_inventory_file_sha256": "c" * 64,
        },
    }
    missing = {
        "schema_version": "missing-access-audit-v1",
        "evaluation_id": "eval-v5",
        "benchmark_sha256": "b" * 64,
        "candidate_sha256": "a" * 64,
        "chunk_id": "CHUNK-001",
        "expected_subject_ids": [item["subject_id"] for item in subjects],
        "expected_reader_task_ids": [item["task_id"] for item in tasks],
        "expected_treatment_ids": [item["treatment_id"] for item in treatments],
        "subject_judgments": subjects,
        "reader_task_results": tasks,
        "treatment_judgments": treatments,
        "reader_task_completion": {"expected": len(tasks), "judged": len(tasks), "unique": True, "complete": True},
        "treatment_completion": {"expected": len(treatments), "judged": len(treatments), "unique": True, "complete": True},
        "completion": {"expected": len(subjects), "judged": len(subjects), "complete": True},
        "provenance": {
            "source_sha256": "d" * 64,
            "benchmark_file_sha256": "4" * 64,
            "benchmark_lock_sha256": "e" * 64,
            "policy_sha256": "f" * 64,
            "page_map_sha256": "1" * 64,
            "chunk_manifest_sha256": "2" * 64,
            "normalized_candidate_file_sha256": "3" * 64,
            "item_inventory_file_sha256": "c" * 64,
            "locator_audit_set_sha256": "0" * 64,
        },
    }
    nodes = [node(index) for index in range(1, max(subject_count, 2) + 1)]
    structure = {
        "schema_version": "structure-audit-v4",
        "evaluation_id": "eval-v5",
        "candidate_sha256": "a" * 64,
        "item_inventory_sha256": "c" * 64,
        "audit_mode": "full",
        "scope_complete": True,
        "metrics": {"page_bearing_paths": subject_count, "expanded_locators": len(locators), "cross_references": 0},
        "density": {
            "policy_status": "scored",
            "measurement_level": "chapter_or_approved_intellectual_unit",
            "targets": [{"metric_id": "paths"}, {"metric_id": "occurrences"}],
            "chapter_measurements": [{"chunk_id": "CHUNK-001", "indexable_source_words": max(1, subject_count * 100), "locator_bearing_heading_paths": subject_count, "locator_occurrences": len(locators)}],
            "fit_rating": 5,
            "maximum_score_contribution": 5,
            "distribution_findings": [],
        },
        "expected_node_ids": [item["node_id"] for item in nodes],
        "node_judgments": nodes,
        "expected_cross_reference_ids": [],
        "cross_reference_judgments": [],
        "defects": [],
        "strengths": [],
        "completion": {"expected_nodes": len(nodes), "judged_nodes": len(nodes), "expected_cross_references": 0, "judged_cross_references": 0, "complete": True},
        "provenance": {
            "source_sha256": "d" * 64,
            "benchmark_sha256": "b" * 64,
            "benchmark_lock_sha256": "e" * 64,
            "policy_sha256": "f" * 64,
            "page_map_sha256": "1" * 64,
            "chunk_manifest_sha256": "2" * 64,
            "normalized_candidate_file_sha256": "3" * 64,
            "item_inventory_file_sha256": "c" * 64,
            "locator_audit_set_sha256": "0" * 64,
            "missing_access_audit_set_sha256": "0" * 64,
        },
        "v5_scoring_context": {
            "candidate_attempt": {"status": "meaningful_attempt", "evidence_ids": []},
            "cross_reference_applicability": {"status": "inapplicable", "basis_code": "no_delivered_references_no_obligation_or_defect", "delivered_reference_count": 0, "warranted_reference_obligation_count": 0, "warranted_reference_obligation_ids": [], "reference_defect_ids": []},
            "optional_subject_scoring": [],
            "node_component_applicability": [],
            "defects": [],
        },
    }
    return locator, missing, structure


def synthetic_item_inventory(locator: dict, structure: dict) -> dict:
    judgments = locator.get("judgments", [])
    path_ids = sorted({item["path_id"] for item in judgments})
    nodes = structure.get("node_judgments", [])
    node_ids = [item["node_id"] for item in nodes]
    paths = []
    for index, path_id in enumerate(path_ids, 1):
        node_id = node_ids[min(index - 1, len(node_ids) - 1)]
        paths.append({
            "path_id": path_id,
            "record_id": f"REC-{index:04d}",
            "record_type": "page_bearing",
            "heading_path": [f"Heading {index}"],
            "node_ids": [node_id],
            "locator_ids": [item["locator_id"] for item in judgments if item["path_id"] == path_id],
            "reference_ids": [],
        })
    heading_nodes = []
    for index, node_record in enumerate(nodes, 1):
        associated_paths = [item["path_id"] for item in paths if node_record["node_id"] in item["node_ids"]]
        heading_nodes.append({
            "node_id": node_record["node_id"],
            "level": len(node_record["heading_path"]),
            "role": node_record["role"],
            "label": node_record["heading_path"][-1],
            "heading_path": node_record["heading_path"],
            "parent_node_id": None,
            "path_ids": associated_paths,
            "record_ids": [item["record_id"] for item in paths if item["path_id"] in associated_paths],
            "direct_path_ids": associated_paths,
        })
    locators = [{
        "locator_id": item["locator_id"],
        "path_id": item["path_id"],
        "node_ids": next(path["node_ids"] for path in paths if path["path_id"] == item["path_id"]),
        "source_page_label": item["source_page_label"],
        "document_page": item["document_page"],
        "mapping_status": "resolved",
    } for item in judgments]
    references = []
    for index, item in enumerate(structure.get("cross_reference_judgments", []), 1):
        source_path = path_ids[0]
        references.append({
            "reference_id": item["reference_id"],
            "record_id": f"REC-XREF-{index:04d}",
            "source_path_id": source_path,
            "source_node_id": paths[0]["node_ids"][0],
            "reference_type": "see also",
            "target_display": "Synthetic target",
            "target_path_id": source_path,
        })
        paths[0]["reference_ids"].append(item["reference_id"])
    return {
        "schema_version": "subject-index-item-inventory-v2",
        "candidate_id": "candidate-synthetic",
        "candidate_sha256": locator["candidate_sha256"],
        "paths": paths,
        "heading_nodes": heading_nodes,
        "locators": locators,
        "cross_references": references,
        "counts": {"paths": len(paths), "heading_nodes": len(heading_nodes), "locators": len(locators), "cross_references": len(references)},
    }


def calculation_files(root: Path, locator: dict, missing: dict, structure: dict, audit_mode: str = "full") -> Path:
    paths = {
        "locator": root / "locator.json",
        "missing": root / "missing.json",
        "structure": root / "structure.json",
        "chunk_manifest": root / "chunk-manifest.json",
        "item_inventory": root / "item-inventory.json",
    }
    structure["audit_mode"] = audit_mode
    inventory = synthetic_item_inventory(locator, structure)
    write_json(paths["item_inventory"], inventory)
    inventory_sha256 = digest(paths["item_inventory"])
    structure["item_inventory_sha256"] = inventory_sha256
    for document in (locator, missing):
        document["provenance"]["item_inventory_file_sha256"] = inventory_sha256
    structure["provenance"]["item_inventory_file_sha256"] = inventory_sha256
    chunks = [item["chunk_id"] for item in structure["density"]["chapter_measurements"]]
    manifest = {
        "schema_version": "chunk-manifest-v1",
        "document_page_basis": "one_based_inclusive",
        "page_map_sha256": "1" * 64,
        "user_approved": True,
        "require_full_scope_coverage": True,
        "chunks": [
            {
                "chunk_id": chunk_id,
                "title": f"Synthetic unit {index}",
                "source_units": [f"Unit {index}"],
                "owned_document_page_ranges": [[index, index]],
                "context_document_page_ranges": [],
                "packet_order": index,
            }
            for index, chunk_id in enumerate(chunks, 1)
        ],
        "validation": {"owned_pages_unique": True, "scope_coverage_complete": True},
        "chunk_manifest_sha256": None,
    }
    manifest["chunk_manifest_sha256"] = v5.canonical_hash(manifest, "chunk_manifest_sha256")
    for document in (locator, missing):
        document["provenance"]["chunk_manifest_sha256"] = manifest["chunk_manifest_sha256"]
    structure["provenance"]["chunk_manifest_sha256"] = manifest["chunk_manifest_sha256"]
    write_json(paths["chunk_manifest"], manifest)
    write_json(paths["locator"], locator)
    locator_set_sha256 = v5.canonical_audit_set_hash(
        [locator], [paths["locator"]], [digest(paths["locator"])], (("judgments", "locator_id", "locator_ids"),)
    )
    missing["provenance"]["locator_audit_set_sha256"] = locator_set_sha256
    write_json(paths["missing"], missing)
    missing_set_sha256 = v5.canonical_audit_set_hash(
        [missing],
        [paths["missing"]],
        [digest(paths["missing"])],
        (("subject_judgments", "subject_id", "subject_ids"), ("reader_task_results", "task_id", "reader_task_ids"), ("treatment_judgments", "treatment_id", "treatment_ids")),
    )
    structure["provenance"]["locator_audit_set_sha256"] = locator_set_sha256
    structure["provenance"]["missing_access_audit_set_sha256"] = missing_set_sha256
    write_json(paths["structure"], structure)
    config = {
        "schema_version": "subject-index-dimension-calculation-input-v1",
        "evaluation_id": "eval-v5",
        "audit_mode": audit_mode,
        "inputs": {
            "chunk_manifest": {"path": paths["chunk_manifest"].name, "sha256": digest(paths["chunk_manifest"])},
            "locator_audits": [{"path": paths["locator"].name, "sha256": digest(paths["locator"])}],
            "missing_access_audits": [{"path": paths["missing"].name, "sha256": digest(paths["missing"])}],
            "structure_audit": {"path": paths["structure"].name, "sha256": digest(paths["structure"])},
        },
    }
    config_path = root / "input.json"
    write_json(config_path, config)
    return config_path


def calculate(root: Path, locator: dict, missing: dict, structure: dict, audit_mode: str = "full") -> dict:
    config = calculation_files(root, locator, missing, structure, audit_mode)
    return v5.calculate_loaded(v5.load_inputs(config))


def dimension(result: dict, dimension_id: str) -> dict:
    return next(item for item in result["dimensions"] if item["dimension_id"] == dimension_id)


def minimal_item_assessments(calculations: dict, inventory_path: Path) -> dict:
    identity = calculations["evidence_identity"]
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    bands = (
        ("excellent", 90, "grade_excellent"),
        ("strong", 80, "grade_strong"),
        ("mixed", 65, "grade_mixed"),
        ("weak", 50, "grade_weak"),
        ("poor", 0, "grade_poor"),
        ("not_measured", None, "grade_neutral"),
    )
    grade = {"score": 100, "rating": 5, "band": "excellent", "color_token": "grade_excellent", "status": "passes"}

    def assessed(title: str) -> dict:
        return {
            "grade": copy.deepcopy(grade),
            "grade_scope": "synthetic_projection_fixture",
            "confidence": "high",
            "evidence_ids": [],
            "popover": {
                "title": title,
                "summary": "Synthetic complete diagnostic assessment.",
                "grade": copy.deepcopy(grade),
                "grade_scope": "synthetic_projection_fixture",
                "confidence": "high",
                "factors": [],
                "evidence_ids": [],
                "navigation": {},
            },
        }

    locator_assessments = [{**assessed(item["locator_id"]), "locator_id": item["locator_id"], "path_id": item["path_id"], "judgment": "supported"} for item in inventory["locators"]]
    path_assessments = [{**assessed(item["path_id"]), "path_id": item["path_id"], "heading_path": item["heading_path"], "node_ids": item["node_ids"], "component_results": []} for item in inventory["paths"]]
    node_assessments = [{**assessed(item["node_id"]), "node_id": item["node_id"], "heading_path": item["heading_path"], "role": item["role"], "component_results": []} for item in inventory["heading_nodes"]]
    reference_assessments = [{**assessed(item["reference_id"]), "reference_id": item["reference_id"], "judgment": "supported"} for item in inventory["cross_references"]]
    subject_count = calculations["diagnostic_item_grades"]["expected_source_subjects"]["count"]
    subject_assessments = [{**assessed(f"SUBJ-{index:04d}"), "subject_id": f"SUBJ-{index:04d}", "coverage": "complete", "matched_path_ids": []} for index in range(1, subject_count + 1)]
    collections = {
        "locators": (locator_assessments, "locator_id"),
        "paths": (path_assessments, "path_id"),
        "heading_nodes": (node_assessments, "node_id"),
        "cross_references": (reference_assessments, "reference_id"),
        "source_subjects": (subject_assessments, "subject_id"),
    }
    completeness = {
        family: {
            "expected": len(records),
            "assessed": len(records),
            "unique": True,
            "complete": True,
            "id_set_sha256": v5.canonical_hash({"ids": sorted(item[id_field] for item in records)}),
        }
        for family, (records, id_field) in collections.items()
    }
    summary = {
        family: {"total": len(records), "graded": len(records), "not_measured": 0, "bands": {"excellent": len(records), "strong": 0, "mixed": 0, "weak": 0, "poor": 0, "not_measured": 0}}
        for family, (records, _) in collections.items()
    }
    return {
        "schema_version": "subject-index-item-assessments-v2",
        "grading_policy": "subject-index-item-grading-v1",
        "evaluation_id": calculations["evaluation_id"],
        "candidate_id": "candidate-synthetic",
        "candidate_sha256": identity["candidate_sha256"],
        "item_inventory_sha256": identity["item_inventory_file_sha256"],
        "item_inventory_artifact": {"schema_version": inventory["schema_version"], "artifact_path": inventory_path.name, "sha256": digest(inventory_path)},
        "evidence_identity": copy.deepcopy(identity),
        "assessment_completeness": completeness,
        "audit_mode": calculations["audit_mode"],
        "scope_complete": True,
        "grade_disclosure": "Synthetic complete diagnostic fixture.",
        "color_legend": [
            {"band": band, "minimum_score": minimum, "color_token": color}
            for band, minimum, color in bands
        ],
        "locator_assessments": locator_assessments,
        "path_assessments": path_assessments,
        "heading_node_assessments": node_assessments,
        "cross_reference_assessments": reference_assessments,
        "source_subject_assessments": subject_assessments,
        "summary": summary,
    }


def evaluation_projection(
    calculations: dict,
    calculations_path: Path,
    item_assessments_path: Path,
    critical_gates: list[dict],
    migration_path: Path | None = None,
) -> dict:
    identity = calculations["evidence_identity"]
    item_assessments = json.loads(item_assessments_path.read_text(encoding="utf-8"))
    result = {
        "schema_version": "subject-index-evaluation-result-v6",
        "evaluation_id": calculations["evaluation_id"],
        "candidate": {"label": "Synthetic", "sha256": identity["candidate_sha256"]},
        "provenance": {
            "source_sha256": identity["source_sha256"],
            "judgment_policy_sha256": identity["policy_sha256"],
            "benchmark_sha256": identity["benchmark_sha256"],
            "rubric_version": calculations["rubric_version"],
            "dimension_calculation_profile": calculations["calculation_profile"],
        },
        "audit_scope": {"mode": calculations["audit_mode"], "complete": True},
        "dimension_calculations": {
            "schema_version": calculations["schema_version"],
            "artifact_path": calculations_path.name,
            "sha256": digest(calculations_path),
            "calculation_profile": calculations["calculation_profile"],
        },
        "scorecard": [
            {
                "dimension_id": item["dimension_id"],
                "label": item["dimension_id"].replace("_", " ").title(),
                "weight": item["dimension_weight"],
                "rating": item["final_rating"],
                "unrounded_rating": item["unrounded_rating"],
                "points": item["awarded_points"],
                "calculation_status": item["status"],
                "formula_id": item["formula_id"],
                "applied_cap_id": item["applied_cap"]["cap_id"] if item["applied_cap"] else None,
                "rationale": "Deterministic projection.",
                "evidence_ids": [],
            }
            for item in calculations["dimensions"]
        ],
        "total_score": calculations["total_score"],
        "interpretation": "Synthetic projection.",
        "metrics": {},
        "item_assessments": {
            "schema_version": item_assessments["schema_version"],
            "grading_policy": item_assessments["grading_policy"],
            "artifact_path": item_assessments_path.name,
            "sha256": digest(item_assessments_path),
            "summary": item_assessments["summary"],
        },
        "critical_gates": critical_gates,
        "defect_counts": {},
        "comparison_key": {
            "source_sha256": identity["source_sha256"],
            "benchmark_sha256": identity["benchmark_sha256"],
            "judgment_policy_sha256": identity["policy_sha256"],
            "page_map_sha256": identity["page_map_sha256"],
            "chunk_manifest_sha256": identity["chunk_manifest_sha256"],
            "inclusion_policy": "standard",
            "audit_mode": calculations["audit_mode"],
            "uncertainty_policy": "v5_bounds",
            "rubric_version": calculations["rubric_version"],
            "dimension_calculation_profile": calculations["calculation_profile"],
        },
        "limitations": [],
    }
    if migration_path is not None:
        migration = json.loads(migration_path.read_text(encoding="utf-8"))
        result["score_migration"] = {
            "schema_version": migration["schema_version"],
            "artifact_path": migration_path.name,
            "sha256": digest(migration_path),
            "migration_sha256": migration["migration_sha256"],
        }
    return result


def web_projection(
    calculations: dict,
    calculations_path: Path,
    item_assessments_path: Path,
    critical_gates: list[dict],
    migration_path: Path | None = None,
) -> dict:
    item_assessments = json.loads(item_assessments_path.read_text(encoding="utf-8"))
    web_scorecard = [
        {
            "dimension_id": item["dimension_id"],
            "label": item["dimension_id"].replace("_", " ").title(),
            "rating": item["final_rating"],
            "unrounded_rating": item["unrounded_rating"],
            "weight": item["dimension_weight"],
            "awarded_points": item["awarded_points"],
            "status": item["status"],
            "formula_id": item["formula_id"],
            "input_artifacts": item["input_artifacts"],
            "denominators": item["denominators"],
            "raw_status_counts": item["raw_status_counts"],
            "credit_mappings": item["credit_mappings"],
            "components": item["components"],
            "base_rating": item["base_rating"],
            "pre_cap_rating": item["pre_cap_rating"],
            "post_cap_rating": item["post_cap_rating"],
            "cap_evaluations": item["cap_evaluations"],
            "applied_cap": item["applied_cap"],
            "rounding": item["rounding"],
            "missing_data_bounds": item["missing_data_bounds"],
        }
        for item in calculations["dimensions"]
    ]
    primary_calculation_reference = {
        "schema_version": calculations["schema_version"],
        "artifact_path": calculations_path.name,
        "sha256": digest(calculations_path),
        "calculation_sha256": calculations["calculation_sha256"],
        "rubric_version": calculations["rubric_version"],
        "calculation_profile": calculations["calculation_profile"],
    }
    migration_comparison = {"status": "not_applicable"}
    if migration_path is not None:
        migration = json.loads(migration_path.read_text(encoding="utf-8"))
        migration_comparison = {
            "status": "v4_to_v5",
            "migration_record": {
                "schema_version": migration["schema_version"],
                "artifact_path": migration_path.name,
                "sha256": digest(migration_path),
                "migration_sha256": migration["migration_sha256"],
            },
            "methodology_commit": migration["methodology"]["commit_sha"],
            "previous_total": migration["from"]["total_score"],
            "migrated_total": migration["to"]["total_score"],
            "dimension_comparison": migration["dimension_comparison"],
            "gate_comparison": {
                "previous_outcomes_sha256": migration["gate_preservation"]["historical_gate_outcomes_sha256"],
                "migrated_outcomes_sha256": v5.canonical_hash({"critical_gates": critical_gates}),
                "previous_outcomes": migration["gate_preservation"]["historical_outcomes"],
                "migrated_outcomes": copy.deepcopy(critical_gates),
                "outcomes_equal": True,
            },
        }
    return {
        "schema_version": "subject-index-web-report-v4",
        "report_id": "report-v5",
        "headline": "Synthetic V5 report",
        "summary": "Contract fixture.",
        "grade": {"score": calculations["total_score"], "maximum": 100, "label": "Excellent"},
        "scorecard": web_scorecard,
        "calculation_explainer": {
            "artifact_path": calculations_path.name,
            "sha256": digest(calculations_path),
            "rubric_version": "subject-index-rubric-v5",
            "calculation_profile": "subject-index-dimension-calculation-v1",
            "item_grades_used": False,
            "gates_used": False,
        },
        "key_metrics": [],
        "density": {},
        "gate_status": {
            "critical_gates": critical_gates,
            "outcomes_sha256": v5.canonical_hash({"critical_gates": critical_gates}),
            "used_in_score_arithmetic": False,
        },
        "strengths": [],
        "defects": [],
        "examples": [],
        "item_grade_index": {
            "schema_version": item_assessments["schema_version"],
            "artifact_path": item_assessments_path.name,
            "sha256": digest(item_assessments_path),
            "grading_policy": item_assessments["grading_policy"],
            "summary": item_assessments["summary"],
            "color_legend": item_assessments["color_legend"],
            "interaction": {
                "color_source": "grade.color_token",
                "popover_source": "popover",
                "not_measured_behavior": "neutral_not_failure",
            },
        },
        "migration_comparison": migration_comparison,
        "score_views": {
            "primary_view_id": "canonical_as_delivered",
            "adjustment_status": "none",
            "views": [{
                "view_id": "canonical_as_delivered",
                "label": "Canonical as delivered",
                "view_kind": "observed",
                "score": calculations["total_score"],
                "maximum": 100,
                "calculation": primary_calculation_reference,
                "causal_attribution": "primary_observed_result",
                "provenance_artifacts": [],
            }],
        },
        "methodology": {},
        "comparability": {},
        "disclosures": [],
        "limitations": [],
        "evidence_index": {},
    }


def historical_v4_result(total_score: float = 84.5, gates: list[dict] | None = None, input_root: Path | None = None) -> dict:
    weights = {
        "meaningful_coverage": 20,
        "editorial_selectivity": 15,
        "conceptual_stance_fidelity": 15,
        "page_reference_reliability": 25,
        "findability_navigation": 20,
        "mechanics_consistency": 5,
    }
    result = {
        "schema_version": "subject-index-evaluation-result-v5",
        "evaluation_id": "eval-v5",
        "candidate": {"label": "Synthetic historical result", "sha256": "a" * 64},
        "provenance": {
            "source_sha256": "d" * 64,
            "policy_sha256": "f" * 64,
            "benchmark_sha256": "b" * 64,
            "page_map_sha256": "1" * 64,
            "chunk_manifest_sha256": "2" * 64,
            "normalized_candidate_file_sha256": "3" * 64,
            "item_inventory_file_sha256": "c" * 64,
            "rubric_version": "subject-index-rubric-v4",
        },
        "audit_scope": {"mode": "full", "complete": True},
        "scorecard": [
            {
                "dimension_id": dimension_id,
                "label": dimension_id.replace("_", " ").title(),
                "weight": weight,
                "rating": 4,
                "points": weight * 0.8,
                "rationale": "Synthetic historical fixture.",
                "evidence_ids": [],
            }
            for dimension_id, weight in weights.items()
        ],
        "total_score": total_score,
        "interpretation": "Synthetic historical fixture.",
        "metrics": {},
        "item_assessments": {
            "schema_version": "subject-index-item-assessments-v1",
            "grading_policy": "subject-index-item-grading-v1",
            "artifact_path": "item-assessments.json",
            "sha256": "4" * 64,
            "summary": {},
        },
        "critical_gates": gates or [],
        "defect_counts": {},
        "comparison_key": {},
        "limitations": [],
    }
    if input_root is not None:
        structure_path = input_root / "structure.json"
        structure = json.loads(structure_path.read_text(encoding="utf-8"))
        result["provenance"]["chunk_manifest_sha256"] = structure["provenance"]["chunk_manifest_sha256"]
        result["provenance"]["item_inventory_file_sha256"] = structure["provenance"]["item_inventory_file_sha256"]
        result["provenance"]["structure_audit_file_sha256"] = digest(structure_path)
        result["provenance"]["locator_audit_set_sha256"] = structure["provenance"]["locator_audit_set_sha256"]
        result["provenance"]["missing_access_audit_set_sha256"] = structure["provenance"]["missing_access_audit_set_sha256"]
    return result


def oxford_regression_ledgers(fixture: dict, *, adjusted: bool = False) -> dict:
    """Materialize the approved published counts as raw engine ledger records."""
    coverage = fixture["coverage"]
    subjects: list[dict] = []
    # 155 essential subjects: 143 complete and 12 missing -> 429/465 credit.
    for index in range(155):
        status = "complete" if index < 143 else "missing"
        subjects.append({"subject_id": f"SUBJ-{index + 1:04d}", "priority": "essential", "coverage": status})
    # Remaining 2,336 priority-weight units: 700 complete, 127 partial, 341 missing majors.
    for offset, status in enumerate(["complete"] * 700 + ["partial"] * 127 + ["missing"] * 341, start=156):
        subjects.append({"subject_id": f"SUBJ-{offset:04d}", "priority": "major", "coverage": status})
    self_check_credit = sum(v5.PRIORITY_CREDIT[item["priority"]] * v5.COVERAGE_CREDIT[item["coverage"]] for item in subjects)
    self_check_weight = sum(v5.PRIORITY_CREDIT[item["priority"]] for item in subjects)
    assert self_check_credit == Decimal(coverage["weighted_credit"])
    assert self_check_weight == Decimal(coverage["weighted_denominator"])

    selectivity = fixture["selectivity"]
    treatment_classes = (
        ["substantive"] * selectivity["substantive"]
        + ["mixed"] * selectivity["mixed"]
        + ["passing_mention"] * 115
        + ["attribution_only"] * 70
        + ["incidental_example"] * 165
        + ["absent"] * 95
    )
    reliability = fixture["reliability"]
    locator_statuses = (
        ["supported"] * reliability["supported"]
        + ["partially_supported"] * reliability["partially_supported"]
        + ["unsupported"] * reliability["unsupported"]
    )
    density_chapters = [dict(item) for item in selectivity["published_density_chapters"]]
    density_slots: list[tuple[str, str]] = []
    remaining_occurrences = {item["chunk_id"]: item["locator_occurrences"] for item in density_chapters}
    emitted_occurrences = {item["chunk_id"]: 0 for item in density_chapters}
    while any(remaining_occurrences.values()):
        for chapter in density_chapters:
            chunk_id = chapter["chunk_id"]
            if remaining_occurrences[chunk_id] == 0:
                continue
            occurrence = emitted_occurrences[chunk_id]
            density_slots.append((chunk_id, f"PATH-{chunk_id.removeprefix('CHUNK-')}-{(occurrence % chapter['locator_bearing_heading_paths']) + 1:04d}"))
            remaining_occurrences[chunk_id] -= 1
            emitted_occurrences[chunk_id] += 1
    locators: list[dict] = []
    unsupported_seen = 0
    for index, (treatment_class, judgment, density_slot) in enumerate(zip(treatment_classes, locator_statuses, density_slots, strict=True), start=1):
        source_unit_id, path_id = density_slot
        error_codes: list[str] = []
        if judgment == "unsupported":
            unsupported_seen += 1
            error_codes = ["LOC_POS"] if unsupported_seen <= reliability["reliability_pattern"] else ["SEL"]
        locators.append({
            "locator_id": f"LOC-{index:05d}",
            "path_id": path_id,
            "treatment_class": treatment_class,
            "source_scope_status": "indexable",
            "judgment": judgment,
            "error_codes": error_codes,
            "_source_unit_id": source_unit_id,
        })

    treatments: list[dict] = []
    high_found = reliability["high_value_found"]
    high_missed = reliability["high_value_expected"] - high_found
    supporting_found = reliability["found_treatments"] - high_found
    supporting_missed = reliability["missed_treatments"] - high_missed
    for index, (locator_class, status) in enumerate(
        [("principal", "found")] * high_found
        + [("principal", "missed")] * high_missed
        + [("supporting", "found")] * supporting_found
        + [("supporting", "missed")] * supporting_missed,
        start=1,
    ):
        treatments.append({"treatment_id": f"TREAT-{index:05d}", "locator_class": locator_class, "status": status})

    concept = fixture["concept"]
    findability = fixture["findability"]
    mechanics = fixture["mechanics"]
    concept_statuses = ["passes"] * concept["passes"] + ["minor_issues"] * concept["minor"] + ["major_issues"] * concept["major"] + ["fails"] * concept["fails"]
    architecture_statuses = ["passes"] * findability["architecture_passes"] + ["minor_issues"] * findability["architecture_minor"] + ["major_issues"] * findability["architecture_major"] + ["fails"] * findability["architecture_fails"]
    if adjusted:
        mechanics_statuses = ["passes"] * mechanics["adjusted_passes"] + ["minor_issues"] * mechanics["adjusted_minor"] + ["major_issues"] * mechanics["adjusted_major"]
    else:
        mechanics_statuses = ["passes"] * mechanics["passes"] + ["minor_issues"] * mechanics["minor"] + ["major_issues"] * mechanics["major"]
    nodes: list[dict] = []
    defects: list[dict] = []
    mechanics_major_ids: list[str] = []
    for index, (concept_status, architecture_status, mechanics_status) in enumerate(zip(concept_statuses, architecture_statuses, mechanics_statuses, strict=True), start=1):
        node_id = f"NODE-{index:04d}"
        concept_evidence: list[str] = []
        mechanics_evidence: list[str] = []
        if concept_status in {"major_issues", "fails"}:
            defect_id = f"DEFECT-CON-{index:04d}"
            concept_evidence = [defect_id]
            kind = "stance_reversal" if len(defects) < concept["major_stance_defects"] else "generic"
            defects.append(defect(defect_id, "conceptual_stance_fidelity", "STA" if kind == "stance_reversal" else "CON", "major", kind=kind, affected=[node_id], applicable=len(concept_statuses), structural_denominator=len(concept_statuses)))
        if mechanics_status == "major_issues":
            mechanics_evidence = ["DEFECT-MEC-REPRESENTATION"]
            mechanics_major_ids.append(node_id)
        nodes.append({
            "node_id": node_id,
            "role": "main_heading",
            "component_judgments": {
                "conceptual_stance_fidelity": {"status": concept_status, "evidence_ids": concept_evidence},
                "heading_access_architecture": {"status": architecture_status, "evidence_ids": []},
                "mechanics_consistency": {"status": mechanics_status, "evidence_ids": mechanics_evidence},
            },
        })
    if mechanics_major_ids:
        defects.append(defect(
            "DEFECT-MEC-REPRESENTATION",
            "mechanics_consistency",
            "MEC",
            "major",
            kind="representation_corruption",
            affected=mechanics_major_ids,
            structural_sections=["NODE-0001", "NODE-1000"],
            applicable=len(nodes),
            structural_denominator=len(nodes),
            family="digit-for-accent-representation",
        ))
    defects.append(defect(
        "DEFECT-XREF-DESTRUCTIVE",
        "findability_navigation",
        "XRF",
        "major",
        kind="substitutive_see",
        affected=["SUBJ-0001"],
        applicable=len(subjects),
        structural_denominator=len(nodes),
        high_priority=True,
    ))

    eligible_results = ["succeeds"] * findability["eligible_succeeds"] + ["partially_succeeds"] * findability["eligible_partial"] + ["fails"] * findability["eligible_fails"]
    tasks = [{"task_id": f"TASK-{index + 1:04d}", "subject_ids": ["SUBJ-0001"], "result": status} for index, status in enumerate(eligible_results)]
    tasks.extend({"task_id": f"TASK-{len(tasks) + 1:04d}", "subject_ids": ["SUBJ-0144"], "result": "fails"} for _ in range(1026 - len(tasks)))

    supported_references = findability["references_supported_adjusted"] if adjusted else findability["references_supported_as_delivered"]
    references = [{"reference_id": f"XREF-{index + 1:04d}", "judgment": "supported" if index < supported_references else "unsupported"} for index in range(findability["references_total"])]
    context = {
        "candidate_attempt": {"status": "meaningful_attempt", "evidence_ids": []},
        "cross_reference_applicability": {"status": "applicable", "basis_code": "delivered_references", "delivered_reference_count": len(references), "warranted_reference_obligation_count": 0, "warranted_reference_obligation_ids": [], "reference_defect_ids": []},
        "optional_subject_scoring": [],
        "node_component_applicability": [],
        "defects": defects,
    }
    return {
        "locators": locators,
        "locator_original": len(locators),
        "locator_not_measured": [],
        "locator_not_measured_units": [],
        "subjects": subjects,
        "subject_original": len(subjects),
        "subject_not_measured": [],
        "tasks": tasks,
        "task_original": len(tasks),
        "task_not_measured": [],
        "treatments": treatments,
        "treatment_original": len(treatments),
        "treatment_not_measured": [],
        "nodes": nodes,
        "node_original": len(nodes),
        "node_not_measured": [],
        "references": references,
        "reference_original": len(references),
        "reference_not_measured": [],
        "structure": {"scope_complete": True, "density": {"chapter_measurements": density_chapters}},
        "context": context,
        "defects": defects,
        "optional_map": {},
        "source_units": [f"CHUNK-{index:03d}" for index in range(1, 18)],
    }


class FormulaBoundaryTests(unittest.TestCase):
    def test_all_approved_status_credit_mappings(self) -> None:
        self.assertEqual({"complete": Decimal(1), "partial": Decimal("0.5"), "missing": Decimal(0)}, v5.COVERAGE_CREDIT)
        self.assertEqual({"essential": Decimal(3), "major": Decimal(2), "optional": Decimal(1)}, v5.PRIORITY_CREDIT)
        self.assertEqual({
            "substantive": Decimal(1), "mixed": Decimal("0.5"), "passing_mention": Decimal(0),
            "attribution_only": Decimal(0), "citation_only": Decimal(0), "incidental_example": Decimal(0),
        }, v5.SELECTIVITY_CREDIT)
        self.assertEqual({"passes": Decimal(1), "minor_issues": Decimal("0.85"), "major_issues": Decimal("0.55"), "fails": Decimal(0)}, v5.NODE_CREDIT)
        self.assertEqual({"passes": Decimal(1), "cosmetic_issues": Decimal("0.95"), "minor_issues": Decimal("0.85"), "major_issues": Decimal("0.55"), "fails": Decimal(0)}, v5.MECHANICS_CREDIT)
        self.assertEqual({"succeeds": Decimal(1), "partially_succeeds": Decimal("0.5"), "fails": Decimal(0)}, v5.TASK_CREDIT)
        self.assertEqual({"supported": Decimal(1), "partially_supported": Decimal("0.5"), "unsupported": Decimal(0)}, v5.REFERENCE_CREDIT)

    def test_decimal_rounding_boundaries(self) -> None:
        for half_step_index in range(10):
            lower = Decimal(half_step_index) * Decimal("0.5")
            tie = lower + Decimal("0.25")
            expected = lower + Decimal("0.5")
            self.assertEqual(lower, v5.round_half_step(tie - Decimal("0.0001")))
            self.assertEqual(expected, v5.round_half_step(tie))
            self.assertEqual(expected, v5.round_half_step(tie + Decimal("0.0001")))
        for hundredth in range(10000):
            lower = Decimal(hundredth) / Decimal(100)
            tie = lower + Decimal("0.005")
            expected = lower + Decimal("0.01")
            self.assertEqual(lower, v5.round_points(tie - Decimal("0.0001")))
            self.assertEqual(expected, v5.round_points(tie))
            self.assertEqual(expected, v5.round_points(tie + Decimal("0.0001")))

    def test_density_zero_and_boundary_correction(self) -> None:
        self.assertEqual(Decimal(0), v5.density_metric_rating(Decimal(0), Decimal(4), Decimal(6), Decimal(10), Decimal(12)))

    def test_v5_density_correction_does_not_rewrite_historical_v4(self) -> None:
        rating, direction, distance = v4.density_rating(0, 4, 6, 10, 12)
        self.assertEqual((1.0, "below_acceptable", 1.0), (rating, direction, distance))

    def test_one_item_systemic_nonuse_cannot_claim_critical_severity(self) -> None:
        record = defect("DEFECT-SYSTEMIC", "mechanics_consistency", "MEC", "critical", kind="generic", affected=["NODE-0001"], applicable=100)
        record["severity_basis"] = "systemic_nonuse"
        with self.assertRaises(v5.CalculationError) as caught:
            v5.validate_defect(record, 0)
        self.assertEqual("invalid_scoring_context", caught.exception.code)
        self.assertEqual(Decimal(1), v5.density_metric_rating(Decimal("0.0001"), Decimal(4), Decimal(6), Decimal(10), Decimal(12)))

    def test_locator_recall_defect_has_a_valid_reliability_owner(self) -> None:
        record = defect(
            "DEFECT-LOC-NEG",
            "page_reference_reliability",
            "LOC_NEG",
            "major",
            affected=["TREAT-0001"],
            applicable=10,
        )
        self.assertEqual(["TREAT-0001"], v5.validate_defect(record, 0))

    def test_coverage_cap_boundaries(self) -> None:
        cases = (
            (0, 5), (1, "4.5"),
            (499, "4.5"), (500, "4.5"), (501, 4),
            (999, 4), (1000, 4), (1001, "3.5"),
            (1999, "3.5"), (2000, "3.5"), (2001, 3),
            (3499, 3), (3500, 3), (3501, 2),
            (4999, 2), (5000, 2), (5001, 1),
        )
        for missing, expected in cases:
            with self.subTest(missing=missing):
                self.assertEqual(Decimal(str(expected)), v5.essential_cap(missing, 10000)[0])

    def test_selectivity_cap_count_distribution_and_rate_boundaries(self) -> None:
        self.assertFalse(v5.selectivity_cap(Decimal("0.05"), 9, Decimal("1"))[1])
        self.assertFalse(v5.selectivity_cap(Decimal("0.05"), 10, Decimal("0.2499"))[1])
        self.assertTrue(v5.selectivity_cap(Decimal("0.05"), 10, Decimal("0.25"))[1])
        for before, exact, after, threshold, prior, current in (
            ("0.049999", "0.05", "0.050001", "0.05", 5, 4),
            ("0.149999", "0.15", "0.150001", "0.15", 4, 3),
            ("0.299999", "0.30", "0.300001", "0.30", 3, 2),
            ("0.499999", "0.50", "0.500001", "0.50", 2, 1),
        ):
            with self.subTest(threshold=threshold):
                self.assertEqual(Decimal(prior), v5.selectivity_cap(Decimal(before), 10, Decimal("0.25"))[0])
                self.assertEqual(Decimal(current), v5.selectivity_cap(Decimal(exact), 10, Decimal("0.25"))[0])
                self.assertEqual(Decimal(current), v5.selectivity_cap(Decimal(after), 10, Decimal("0.25"))[0])

    def test_high_value_recall_boundaries(self) -> None:
        for found, expected, maximum in (
            (8999, 10000, 4), (9000, 10000, 5), (9001, 10000, 5),
            (7499, 10000, 3), (7500, 10000, 4), (7501, 10000, 4),
            (4999, 10000, 2), (5000, 10000, 3), (5001, 10000, 3),
            (2499, 10000, 1), (2500, 10000, 2), (2501, 10000, 2),
        ):
            self.assertEqual(Decimal(maximum), v5.high_value_cap(found, expected)[0])

    def test_reliability_pattern_boundaries(self) -> None:
        self.assertFalse(v5.reliability_pattern_cap(100, 10000, 2499, 10000)[1])
        self.assertTrue(v5.reliability_pattern_cap(100, 10000, 2500, 10000)[1])
        for before, exact, after, threshold, prior, current in (
            (99, 100, 101, "0.01", 5, "4.5"),
            (299, 300, 301, "0.03", "4.5", 4),
            (749, 750, 751, "0.075", 4, "3.5"),
            (1499, 1500, 1501, "0.15", "3.5", "2.5"),
            (2999, 3000, 3001, "0.30", "2.5", "1.5"),
        ):
            with self.subTest(threshold=threshold):
                self.assertEqual(Decimal(str(prior)), v5.reliability_pattern_cap(before, 10000, 2500, 10000)[0])
                self.assertEqual(Decimal(str(current)), v5.reliability_pattern_cap(exact, 10000, 2500, 10000)[0])
                self.assertEqual(Decimal(str(current)), v5.reliability_pattern_cap(after, 10000, 2500, 10000)[0])

    def test_reference_rate_caps_absolute_counts(self) -> None:
        self.assertFalse(any(item["triggered"] for item in v5.reference_rate_caps(1, 2, [])))
        for suffix, below, exact, above in (
            ("10_percent", (2, 21), (2, 20), (2, 19)),
            ("25_percent", (2, 9), (2, 8), (2, 7)),
            ("50_percent", (3, 7), (3, 6), (3, 5)),
        ):
            with self.subTest(threshold=suffix):
                self.assertFalse(next(item for item in v5.reference_rate_caps(*below, []) if item["cap_id"].endswith(suffix))["triggered"])
                self.assertTrue(next(item for item in v5.reference_rate_caps(*exact, []) if item["cap_id"].endswith(suffix))["triggered"])
                self.assertTrue(next(item for item in v5.reference_rate_caps(*above, []) if item["cap_id"].endswith(suffix))["triggered"])

    def test_prevalence_task_and_mechanics_aggregate_cap_boundaries(self) -> None:
        for prefix, thresholds in (
            ("concept", (("0.05", "3.5"), ("0.15", "2.5"), ("0.30", "1.5"))),
            ("findability.architecture", (("0.05", 4), ("0.15", 3), ("0.30", 2))),
        ):
            table = tuple((Decimal(threshold), Decimal(str(maximum))) for threshold, maximum in thresholds)
            for threshold, _ in table:
                exact = int(threshold * 10000)
                cap_id = f"{prefix}.prevalence_at_least_{v5.decimal_text(threshold)}"
                for count, expected in ((exact - 1, False), (exact, True), (exact + 1, True)):
                    record = next(item for item in v5.prevalence_caps(prefix, count, 10000, [], table) if item["cap_id"] == cap_id)
                    self.assertEqual(expected, record["triggered"], (cap_id, count))
        for suffix, exact in (("10_percent", 1000), ("25_percent", 2500), ("50_percent", 5000)):
            for count, expected in ((exact - 1, False), (exact, True), (exact + 1, True)):
                record = next(item for item in v5.task_failure_caps(count, 10000, []) if item["cap_id"].endswith(suffix))
                self.assertEqual(expected, record["triggered"], (suffix, count))
        for suffix, exact in (("5_percent", 500), ("20_percent", 2000)):
            for count, expected in ((exact - 1, False), (exact, True), (exact + 1, True)):
                record = next(item for item in v5.mechanics_aggregate_caps(count, 10000, []) if item["cap_id"].endswith(suffix))
                self.assertEqual(expected, record["triggered"], (suffix, count))

    def test_measurement_sufficiency_boundaries_and_small_denominator_exception(self) -> None:
        for measured, applicable, expected in ((9499, 10000, False), (9500, 10000, True), (9900, 10000, True), (10000, 10000, True)):
            value = v5.component_denominators("x", applicable, applicable, measured, applicable - measured, 0, {})
            self.assertEqual(expected, value["provisionally_scoreable"])
        small = v5.component_denominators("x", 2, 2, 1, 1, 0, {})
        self.assertTrue(small["small_denominator_exception"])
        self.assertTrue(small["provisionally_scoreable"])
        blocked = v5.component_denominators("x", 2, 2, 1, 0, 1, {})
        self.assertFalse(blocked["provisionally_scoreable"])

    def test_mechanics_recurrence_and_systematic_thresholds(self) -> None:
        def cap_for(count: int, sections: int, denominator: int = 1000, section_denominator: int = 10) -> dict[str, dict]:
            record = defect(
                "DEFECT-MEC", "mechanics_consistency", "MEC", "major",
                kind="representation_corruption", affected=[f"NODE-{index}" for index in range(count)],
                structural_sections=[f"S{index}" for index in range(sections)], applicable=denominator,
                structural_denominator=section_denominator, family="representation",
            )
            ledgers = {"defects": [record], "node_original": denominator}
            return {item["cap_id"].split(".")[1]: item for item in v5.mechanics_pattern_caps(ledgers)}

        self.assertFalse(cap_for(2, 2)["recurrent_major"]["triggered"])
        self.assertTrue(cap_for(3, 2)["recurrent_major"]["triggered"])
        self.assertTrue(cap_for(4, 2)["recurrent_major"]["triggered"])
        self.assertFalse(cap_for(9, 1)["recurrent_major"]["triggered"])
        self.assertTrue(cap_for(10, 1)["recurrent_major"]["triggered"])
        self.assertTrue(cap_for(11, 1)["recurrent_major"]["triggered"])
        self.assertFalse(cap_for(99, 1)["systematic_major"]["triggered"])
        self.assertTrue(cap_for(100, 1)["systematic_major"]["triggered"])
        self.assertTrue(cap_for(101, 1)["systematic_major"]["triggered"])
        self.assertFalse(cap_for(3, 4)["systematic_major"]["triggered"])
        self.assertTrue(cap_for(3, 5)["systematic_major"]["triggered"])
        self.assertTrue(cap_for(3, 6)["systematic_major"]["triggered"])


class EndToEndCalculationTests(unittest.TestCase):
    def test_perfect_ledgers_score_100_and_validate_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = calculate(root, *base_documents())
            self.assertEqual(100, result["total_score"])
            self.assertTrue(result["arithmetic_check"])
            self.assertFalse(result["diagnostic_item_grades"]["used_in_dimension_arithmetic"])
            self.assertFalse(result["publication_readiness_gates"]["used_in_score_arithmetic"])
            schema = json.loads((SCHEMAS / "dimension-calculations.schema.json").read_text())
            jsonschema.validate(result, schema)
            duplicated = copy.deepcopy(result)
            duplicated["dimensions"][1] = copy.deepcopy(duplicated["dimensions"][0])
            with self.assertRaises(jsonschema.ValidationError):
                jsonschema.validate(duplicated, schema)
            for dimension_record in result["dimensions"]:
                for component_record in dimension_record["components"]:
                    self.assertIn("raw_numerator", component_record)
                    self.assertIn("raw_denominator", component_record)
                    if component_record["normalized_value"] is None:
                        self.assertIsNone(component_record["raw_numerator"])
                        self.assertIsNone(component_record["raw_denominator"])
                    else:
                        numerator = Decimal(component_record["raw_numerator"])
                        denominator = Decimal(component_record["raw_denominator"])
                        self.assertGreater(denominator, 0)
                        self.assertEqual(Decimal(component_record["normalized_value"]), numerator / denominator)

    def test_v5_result_and_web_projection_contracts_validate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            calculations = calculate(root, *base_documents())
            calculations_path = root / "dimension-calculations.v1.json"
            write_json(calculations_path, calculations)
            calculation_sha256 = digest(calculations_path)
            item_assessments_path = root / "item-assessments.v1.json"
            item_assessments = minimal_item_assessments(calculations, root / "item-inventory.json")
            write_json(item_assessments_path, item_assessments)
            evaluation_result = evaluation_projection(
                calculations,
                calculations_path,
                item_assessments_path,
                critical_gates=[],
            )
            v5.validate_schema_document(evaluation_result, "evaluation-result-v6.schema.json", "V5 result projection")
            duplicated_result = copy.deepcopy(evaluation_result)
            duplicated_result["scorecard"][1] = copy.deepcopy(duplicated_result["scorecard"][0])
            with self.assertRaises(v5.CalculationError):
                v5.validate_schema_document(duplicated_result, "evaluation-result-v6.schema.json", "duplicate V5 result projection")

            web_scorecard = []
            for item in calculations["dimensions"]:
                web_scorecard.append({
                    "dimension_id": item["dimension_id"],
                    "label": item["dimension_id"].replace("_", " ").title(),
                    "rating": item["final_rating"],
                    "unrounded_rating": item["unrounded_rating"],
                    "weight": item["dimension_weight"],
                    "awarded_points": item["awarded_points"],
                    "status": item["status"],
                    "formula_id": item["formula_id"],
                    "input_artifacts": item["input_artifacts"],
                    "denominators": item["denominators"],
                    "raw_status_counts": item["raw_status_counts"],
                    "credit_mappings": item["credit_mappings"],
                    "components": item["components"],
                    "base_rating": item["base_rating"],
                    "pre_cap_rating": item["pre_cap_rating"],
                    "post_cap_rating": item["post_cap_rating"],
                    "cap_evaluations": item["cap_evaluations"],
                    "applied_cap": item["applied_cap"],
                    "rounding": item["rounding"],
                    "missing_data_bounds": item["missing_data_bounds"],
                })
            web_report = {
                "schema_version": "subject-index-web-report-v4",
                "report_id": "report-v5",
                "headline": "Synthetic V5 report",
                "summary": "Contract fixture.",
                "grade": {"score": 100, "maximum": 100, "label": "Excellent"},
                "scorecard": web_scorecard,
                "calculation_explainer": {
                    "artifact_path": calculations_path.name,
                    "sha256": calculation_sha256,
                    "rubric_version": "subject-index-rubric-v5",
                    "calculation_profile": "subject-index-dimension-calculation-v1",
                    "item_grades_used": False,
                    "gates_used": False,
                },
                "key_metrics": [],
                "density": {},
                "gate_status": {
                    "critical_gates": [],
                    "outcomes_sha256": v5.canonical_hash({"critical_gates": []}),
                    "used_in_score_arithmetic": False,
                },
                "strengths": [],
                "defects": [],
                "examples": [],
                "item_grade_index": {
                    "schema_version": item_assessments["schema_version"],
                    "artifact_path": item_assessments_path.name,
                    "sha256": digest(item_assessments_path),
                    "grading_policy": item_assessments["grading_policy"],
                    "summary": item_assessments["summary"],
                    "color_legend": item_assessments["color_legend"],
                    "interaction": {
                        "color_source": "grade.color_token",
                        "popover_source": "popover",
                        "not_measured_behavior": "neutral_not_failure",
                    },
                },
                "migration_comparison": {"status": "not_applicable"},
                "score_views": {
                    "primary_view_id": "canonical_as_delivered",
                    "adjustment_status": "none",
                    "views": [{
                        "view_id": "canonical_as_delivered",
                        "label": "Canonical as delivered",
                        "view_kind": "observed",
                        "score": calculations["total_score"],
                        "maximum": 100,
                        "calculation": {
                            "schema_version": calculations["schema_version"],
                            "artifact_path": calculations_path.name,
                            "sha256": calculation_sha256,
                            "calculation_sha256": calculations["calculation_sha256"],
                            "rubric_version": calculations["rubric_version"],
                            "calculation_profile": calculations["calculation_profile"],
                        },
                        "causal_attribution": "primary_observed_result",
                        "provenance_artifacts": [],
                    }],
                },
                "methodology": {},
                "comparability": {},
                "disclosures": [],
                "limitations": [],
                "evidence_index": {},
            }
            v5.validate_schema_document(web_report, "web-report-v4.schema.json", "V5 web projection")
            for required_display in ("migration_comparison", "score_views"):
                incomplete_report = copy.deepcopy(web_report)
                incomplete_report.pop(required_display)
                with self.assertRaises(v5.CalculationError):
                    v5.validate_schema_document(incomplete_report, "web-report-v4.schema.json", f"web report missing {required_display}")
            duplicated_report = copy.deepcopy(web_report)
            duplicated_report["scorecard"][1] = copy.deepcopy(duplicated_report["scorecard"][0])
            with self.assertRaises(v5.CalculationError):
                v5.validate_schema_document(duplicated_report, "web-report-v4.schema.json", "duplicate V5 web projection")

            evaluation_path = root / "evaluation-result.v6.json"
            report_path = root / "web-report.v4.json"
            write_json(evaluation_path, evaluation_result)
            write_json(report_path, web_report)
            validation = v5.validate_projection_artifacts(calculations_path, evaluation_path, report_path)
            self.assertTrue(validation["ok"])
            cli_validation = run_cli(
                "dimension_score_cli.py",
                "validate-projections",
                "--calculation",
                calculations_path,
                "--evaluation-result",
                evaluation_path,
                "--web-report",
                report_path,
            )
            self.assertEqual(calculation_sha256, cli_validation["calculation_file_sha256"])
            identity_drifts = (
                ("candidate", "sha256"),
                ("provenance", "source_sha256"),
                ("provenance", "benchmark_sha256"),
                ("provenance", "judgment_policy_sha256"),
                ("comparison_key", "source_sha256"),
                ("comparison_key", "benchmark_sha256"),
                ("comparison_key", "judgment_policy_sha256"),
                ("comparison_key", "page_map_sha256"),
                ("comparison_key", "chunk_manifest_sha256"),
            )
            for section, field in identity_drifts:
                with self.subTest(identity=f"{section}.{field}"):
                    drifted = copy.deepcopy(evaluation_result)
                    drifted[section][field] = "9" * 64
                    drifted_path = root / f"drifted-{section}-{field}.json"
                    write_json(drifted_path, drifted)
                    with self.assertRaises(v5.CalculationError) as caught:
                        v5.validate_projection_artifacts(calculations_path, drifted_path)
                    self.assertEqual("projection_identity_mismatch", caught.exception.code)
            for field, value in (("rating", 4.5), ("points", 19),):
                with self.subTest(field=field):
                    drifted = copy.deepcopy(evaluation_result)
                    drifted["scorecard"][0][field] = value
                    drifted_path = root / f"drifted-{field}.json"
                    write_json(drifted_path, drifted)
                    with self.assertRaises(v5.CalculationError) as caught:
                        v5.validate_projection_artifacts(calculations_path, drifted_path)
                    self.assertEqual("projection_mismatch", caught.exception.code)
            drifted_total = copy.deepcopy(evaluation_result)
            drifted_total["total_score"] = 99
            drifted_total_path = root / "drifted-total.json"
            write_json(drifted_total_path, drifted_total)
            with self.assertRaises(v5.CalculationError) as caught:
                v5.validate_projection_artifacts(calculations_path, drifted_total_path)
            self.assertEqual("projection_mismatch", caught.exception.code)
            drifted_report = copy.deepcopy(web_report)
            drifted_report["scorecard"][0]["awarded_points"] = 19
            drifted_report_path = root / "drifted-web.json"
            write_json(drifted_report_path, drifted_report)
            with self.assertRaises(v5.CalculationError) as caught:
                v5.validate_projection_artifacts(calculations_path, evaluation_path, drifted_report_path)
            self.assertEqual("projection_mismatch", caught.exception.code)

            alternate_item_assessments = copy.deepcopy(item_assessments)
            alternate_item_assessments["candidate_sha256"] = "9" * 64
            alternate_item_path = root / "alternate-item-assessments.v1.json"
            write_json(alternate_item_path, alternate_item_assessments)
            drifted_item_result = copy.deepcopy(evaluation_result)
            drifted_item_result["item_assessments"].update({
                "artifact_path": alternate_item_path.name,
                "sha256": digest(alternate_item_path),
            })
            drifted_item_result_path = root / "drifted-item-result.json"
            write_json(drifted_item_result_path, drifted_item_result)
            with self.assertRaises(v5.CalculationError) as caught:
                v5.validate_projection_artifacts(calculations_path, drifted_item_result_path)
            self.assertEqual("item_assessment_binding_mismatch", caught.exception.code)

            wrong_snapshot = copy.deepcopy(item_assessments)
            wrong_snapshot["evidence_identity"]["locator_audit_set_sha256"] = "9" * 64
            wrong_snapshot_path = root / "wrong-snapshot-item-assessments.v2.json"
            write_json(wrong_snapshot_path, wrong_snapshot)
            wrong_snapshot_result = copy.deepcopy(evaluation_result)
            wrong_snapshot_result["item_assessments"].update({"artifact_path": wrong_snapshot_path.name, "sha256": digest(wrong_snapshot_path), "summary": wrong_snapshot["summary"]})
            wrong_snapshot_result_path = root / "wrong-snapshot-result.json"
            write_json(wrong_snapshot_result_path, wrong_snapshot_result)
            with self.assertRaises(v5.CalculationError) as caught:
                v5.validate_projection_artifacts(calculations_path, wrong_snapshot_result_path)
            self.assertEqual("item_assessment_binding_mismatch", caught.exception.code)

            empty_items = copy.deepcopy(item_assessments)
            for key in ("locator_assessments", "path_assessments", "heading_node_assessments", "cross_reference_assessments", "source_subject_assessments"):
                empty_items[key] = []
            empty_set_hash = v5.canonical_hash({"ids": []})
            empty_items["assessment_completeness"] = {
                family: {"expected": 0, "assessed": 0, "unique": True, "complete": True, "id_set_sha256": empty_set_hash}
                for family in ("locators", "paths", "heading_nodes", "cross_references", "source_subjects")
            }
            empty_items["summary"] = {
                family: {"total": 0, "graded": 0, "not_measured": 0, "bands": {"excellent": 0, "strong": 0, "mixed": 0, "weak": 0, "poor": 0, "not_measured": 0}}
                for family in ("locators", "paths", "heading_nodes", "cross_references", "source_subjects")
            }
            empty_item_path = root / "empty-item-assessments.v2.json"
            write_json(empty_item_path, empty_items)
            empty_result = copy.deepcopy(evaluation_result)
            empty_result["item_assessments"].update({"artifact_path": empty_item_path.name, "sha256": digest(empty_item_path), "summary": empty_items["summary"]})
            empty_result_path = root / "empty-item-result.json"
            write_json(empty_result_path, empty_result)
            with self.assertRaises(v5.CalculationError) as caught:
                v5.validate_projection_artifacts(calculations_path, empty_result_path)
            self.assertEqual("item_assessment_completeness_mismatch", caught.exception.code)

            drifted_item_report = copy.deepcopy(web_report)
            drifted_item_report["item_grade_index"].update({
                "artifact_path": alternate_item_path.name,
                "sha256": digest(alternate_item_path),
            })
            drifted_item_report_path = root / "drifted-item-report.json"
            write_json(drifted_item_report_path, drifted_item_report)
            with self.assertRaises(v5.CalculationError) as caught:
                v5.validate_projection_artifacts(calculations_path, evaluation_path, drifted_item_report_path)
            self.assertEqual("item_assessment_binding_mismatch", caught.exception.code)

            drifted_gate_report = copy.deepcopy(web_report)
            drifted_gate_report["gate_status"]["critical_gates"] = [{"gate_id": "GATE-X", "status": "failed"}]
            drifted_gate_report["gate_status"]["outcomes_sha256"] = v5.canonical_hash({
                "critical_gates": drifted_gate_report["gate_status"]["critical_gates"],
            })
            drifted_gate_report_path = root / "drifted-gate-report.json"
            write_json(drifted_gate_report_path, drifted_gate_report)
            with self.assertRaises(v5.CalculationError) as caught:
                v5.validate_projection_artifacts(calculations_path, evaluation_path, drifted_gate_report_path)
            self.assertEqual("gate_projection_mismatch", caught.exception.code)

            del web_report["scorecard"][0]["raw_status_counts"]
            with self.assertRaises(v5.CalculationError):
                v5.validate_schema_document(web_report, "web-report-v4.schema.json", "incomplete V5 web projection")

    def test_policy_v3_validates_without_score_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "evaluation-policy.v3.json"
            run_cli(
                "policy_cli.py",
                "build",
                "--input",
                FIXTURES / "policy-build-input.valid.json",
                "--output",
                output,
            )
            policy = json.loads(output.read_text(encoding="utf-8"))
            self.assertNotIn("rubric", policy)
            v5.validate_schema_document(policy, "evaluation-policy-v3.schema.json", "V3 judgment policy")

    def test_historical_v3_decimal_schema_boundary_validates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "structure-audit.v3.json"
            _, _, structure = base_documents()
            structure["schema_version"] = "structure-audit-v3"
            structure.pop("v5_scoring_context")
            structure["density"]["fit_rating"] = 3.5
            structure["density"]["chapter_measurements"][0].update({"metric_results": [], "unit_fit_rating": 3.5})
            write_json(path, structure)
            historical = v5.load_json(path, "historical structure audit")
            self.assertIsInstance(historical["density"]["fit_rating"], Decimal)
            v5.validate_schema_document(historical, "structure-audit.schema.json", "historical structure audit")

    def test_all_dimension_and_component_weights_are_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = calculate(Path(temporary), *base_documents())
        self.assertEqual({
            "meaningful_coverage": 20,
            "editorial_selectivity": 15,
            "conceptual_stance_fidelity": 15,
            "page_reference_reliability": 25,
            "findability_navigation": 20,
            "mechanics_consistency": 5,
        }, {item["dimension_id"]: item["dimension_weight"] for item in result["dimensions"]})
        selectivity = dimension(result, "editorial_selectivity")
        self.assertEqual(["10/15", "5/15"], [item["weight"] for item in selectivity["components"]])
        findability = dimension(result, "findability_navigation")
        self.assertEqual(["0.60", "0.30", "0.10"], [item["weight"] for item in findability["components"]])
        reliability = dimension(result, "page_reference_reliability")
        self.assertEqual(["harmonic_mean", "harmonic_mean", "cap_only"], [item["weight"] for item in reliability["components"]])
        for dimension_id in ("meaningful_coverage", "conceptual_stance_fidelity", "mechanics_consistency"):
            self.assertEqual("1", dimension(result, dimension_id)["components"][0]["weight"])

    def test_calculation_identity_binds_audit_mode_and_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path = calculation_files(root, *base_documents())
            full = v5.calculate_loaded(v5.load_inputs(config_path))
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["audit_mode"] = "pilot"
            write_json(config_path, config)
            with self.assertRaises(v5.CalculationError) as caught:
                v5.calculate_loaded(v5.load_inputs(config_path))
            self.assertEqual("migration_inputs_insufficient", caught.exception.code)
            pilot_root = root / "pilot"
            pilot_root.mkdir()
            pilot_path = calculation_files(pilot_root, *base_documents(), audit_mode="pilot")
            pilot = v5.calculate_loaded(v5.load_inputs(pilot_path))
            self.assertNotEqual(full["calculation_id"], pilot["calculation_id"])
            self.assertEqual("subject-index-rubric-v5", full["rubric_version"])
            self.assertEqual("subject-index-dimension-calculation-v1", full["calculation_profile"])

    def test_preflight_rejects_incomplete_chunks_and_mixed_candidate_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            locator, missing, structure = base_documents()
            structure["density"]["chapter_measurements"].append({"chunk_id": "CHUNK-002", "indexable_source_words": 1000, "locator_bearing_heading_paths": 8, "locator_occurrences": 20})
            config = calculation_files(root, locator, missing, structure)
            payload = run_cli("dimension_score_cli.py", "preflight", "--input", config)
            self.assertFalse(payload["sufficient"])
            self.assertEqual("incomplete_or_mixed_chunk_set", payload["missing_requirements"][0]["code"])

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            locator, missing, structure = base_documents()
            missing["candidate_sha256"] = "9" * 64
            config = calculation_files(root, locator, missing, structure)
            payload = run_cli("dimension_score_cli.py", "preflight", "--input", config)
            self.assertFalse(payload["sufficient"])
            self.assertEqual("candidate_identity_mismatch", payload["missing_requirements"][0]["code"])

    def test_locator_derived_structure_and_density_aggregates_must_reconstruct(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            locator, missing, structure = base_documents(subject_count=100)
            structure["metrics"]["page_bearing_paths"] = 10
            config = calculation_files(Path(temporary), locator, missing, structure)
            payload = run_cli("dimension_score_cli.py", "preflight", "--input", config)
        self.assertFalse(payload["sufficient"])
        mismatch = payload["missing_requirements"][0]
        self.assertEqual("recomputable_aggregate_mismatch", mismatch["code"])
        self.assertEqual("metrics.page_bearing_paths", mismatch["details"]["field"])
        self.assertEqual(100, mismatch["details"]["minimum"])
        self.assertEqual(10, mismatch["details"]["actual"])

        for field, forged in (("locator_bearing_heading_paths", 8), ("locator_occurrences", 20)):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                locator, missing, structure = base_documents()
                structure["density"]["chapter_measurements"][0][field] = forged
                config = calculation_files(Path(temporary), locator, missing, structure)
                payload = run_cli("dimension_score_cli.py", "preflight", "--input", config)
            self.assertFalse(payload["sufficient"])
            mismatch = payload["missing_requirements"][0]
            self.assertEqual("recomputable_aggregate_mismatch", mismatch["code"])
            self.assertEqual(field, mismatch["details"]["field"])

    def test_preflight_reports_missing_canonical_chunk_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path = calculation_files(root, *base_documents())
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["inputs"].pop("chunk_manifest")
            write_json(config_path, config)
            payload = run_cli("dimension_score_cli.py", "preflight", "--input", config_path)
            self.assertFalse(payload["sufficient"])
            self.assertTrue(any(item["code"] == "canonical_chunk_manifest_required" for item in payload["missing_requirements"]))
            with self.assertRaises(v5.CalculationError) as caught:
                v5.calculate_loaded(v5.load_inputs(config_path))
            self.assertEqual("migration_inputs_insufficient", caught.exception.code)

    def test_not_applicable_node_component_requires_frozen_basis(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            locator, missing, structure = base_documents()
            structure["node_judgments"][0]["component_judgments"]["mechanics_consistency"]["status"] = "not_applicable"
            config = calculation_files(root, locator, missing, structure)
            payload = run_cli("dimension_score_cli.py", "preflight", "--input", config)
            self.assertFalse(payload["sufficient"])
            self.assertEqual("node_applicability_basis_mismatch", payload["missing_requirements"][0]["code"])

    def test_duplicate_logical_treatment_unit_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            locator, missing, structure = base_documents()
            duplicate = copy.deepcopy(missing["treatment_judgments"][0])
            duplicate["treatment_id"] = "TREAT-DUPLICATE"
            missing["expected_treatment_ids"].append(duplicate["treatment_id"])
            missing["treatment_judgments"].append(duplicate)
            missing["treatment_completion"] = {"expected": 3, "judged": 3, "unique": True, "complete": True}
            config = calculation_files(root, locator, missing, structure)
            payload = run_cli("dimension_score_cli.py", "preflight", "--input", config)
            self.assertFalse(payload["sufficient"])
            self.assertEqual("duplicate_treatment_unit", payload["missing_requirements"][0]["code"])

    def test_denominator_and_exclusion_rules_reconstruct(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            locator, missing, structure = base_documents(subject_count=6)
            missing["subject_judgments"][5]["priority"] = "optional"
            structure["v5_scoring_context"]["optional_subject_scoring"] = [{"subject_id": "SUBJ-0006", "scored": False, "benchmark_evidence_ids": ["BENCH-OPTIONAL"]}]
            locator["judgments"][1]["treatment_class"] = "absent"
            locator["judgments"][2]["treatment_class"] = "unavailable"
            locator["judgments"][2]["judgment"] = "uninspectable"
            locator["judgments"][3]["source_scope_status"] = "excluded"
            locator["judgments"][4]["source_scope_status"] = "ambiguous"
            structure["node_judgments"][5]["component_judgments"]["conceptual_stance_fidelity"]["status"] = "not_applicable"
            structure["node_judgments"][5]["component_judgments"]["heading_access_architecture"]["status"] = "not_applicable"
            structure["node_judgments"][5]["component_judgments"]["mechanics_consistency"]["status"] = "not_applicable"
            structure["v5_scoring_context"]["node_component_applicability"] = [
                {"node_id": "NODE-0006", "component_id": component_id, "basis_code": "benchmark_genuinely_inapplicable", "evidence_ids": ["BENCH-NODE-0006"]}
                for component_id in ("conceptual_stance_fidelity", "heading_access_architecture", "mechanics_consistency")
            ]
            result = calculate(root, locator, missing, structure)
        coverage_denom = dimension(result, "meaningful_coverage")["denominators"]["components"][0]
        self.assertEqual({"original": 6, "applicable": 5, "excluded": 1}, {key: coverage_denom[key] for key in ("original", "applicable", "excluded")})
        self.assertEqual(1, coverage_denom["exclusion_reasons"]["optional_not_frozen_as_scored"])
        selectivity_denom = dimension(result, "editorial_selectivity")["denominators"]["components"][0]
        self.assertEqual(selectivity_denom["original"], selectivity_denom["applicable"] + selectivity_denom["excluded"])
        self.assertEqual(1, selectivity_denom["exclusion_reasons"]["absent_owned_by_reliability"])
        self.assertEqual(3, selectivity_denom["exclusion_reasons"]["scope_or_ambiguity_owned_elsewhere"])
        self.assertEqual(0, selectivity_denom["uninspectable"])
        for dimension_id in ("conceptual_stance_fidelity", "findability_navigation", "mechanics_consistency"):
            denominators = dimension(result, dimension_id)["denominators"]["components"]
            node_denominators = [item for item in denominators if item["component_id"] != "coverage_conditioned_reader_tasks" and item["component_id"] != "cross_reference_validity"]
            self.assertTrue(any(item["exclusion_reasons"].get("not_applicable") == 1 for item in node_denominators))

    def test_defined_zero_reliability_without_locator_assignments(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            locator, missing, structure = base_documents()
            locator["expected_locator_ids"] = []
            locator["judgments"] = []
            locator["completion"] = {"expected": 0, "judged": 0, "unique": True, "complete": True}
            structure["metrics"]["page_bearing_paths"] = 0
            structure["metrics"]["expanded_locators"] = 0
            structure["density"]["chapter_measurements"][0]["locator_bearing_heading_paths"] = 0
            structure["density"]["chapter_measurements"][0]["locator_occurrences"] = 0
            result = calculate(root, locator, missing, structure)
        reliability = dimension(result, "page_reference_reliability")
        self.assertEqual(0, reliability["final_rating"])
        precision = reliability["denominators"]["components"][0]
        self.assertEqual("expected_treatments_but_no_locator_assignments", precision["defined_zero_rule"])

    def test_item_grades_and_gates_are_rejected_as_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path = calculation_files(root, *base_documents())
            config = json.loads(config_path.read_text())
            config["item_assessments"] = {"ratings": [5, 5, 5, 5, 5, 5]}
            write_json(config_path, config)
            with self.assertRaises(v5.CalculationError) as caught:
                v5.load_inputs(config_path)
            self.assertEqual("invalid_input_config", caught.exception.code)
            config.pop("item_assessments")
            config["critical_gates"] = [{"status": "passed"}]
            write_json(config_path, config)
            with self.assertRaises(v5.CalculationError):
                v5.load_inputs(config_path)

    def test_preflight_and_calculate_cannot_overwrite_frozen_inputs(self) -> None:
        for command in ("preflight", "calculate"):
            with self.subTest(command=command), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                config = calculation_files(root, *base_documents())
                ledger = root / "locator.json"
                before = digest(ledger)
                payload = run_cli("dimension_score_cli.py", command, "--input", config, "--output", ledger, expect_ok=False)
                self.assertEqual("output_aliases_frozen_input", payload["error"]["code"])
                self.assertEqual(before, digest(ledger))

    def test_full_not_measured_blocks_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            locator, missing, structure = base_documents()
            locator["expected_locator_ids"].append("LOC-MISSING")
            locator["completion"] = {"expected": len(locator["expected_locator_ids"]), "judged": len(locator["judgments"]), "unique": True, "complete": False}
            structure["metrics"]["expanded_locators"] += 1
            structure["density"]["chapter_measurements"][0]["locator_occurrences"] += 1
            config = calculation_files(root, locator, missing, structure)
            payload = run_cli("dimension_score_cli.py", "preflight", "--input", config)
            self.assertFalse(payload["sufficient"])
            self.assertTrue(any(item["code"] == "incomplete_full_audit" for item in payload["missing_requirements"]))

    def test_full_missing_task_and_treatment_statuses_block_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            locator, missing, structure = base_documents()
            missing["reader_task_results"][0].pop("result")
            missing["treatment_judgments"][0].pop("status")
            config = calculation_files(root, locator, missing, structure)
            payload = run_cli("dimension_score_cli.py", "preflight", "--input", config)
            self.assertFalse(payload["sufficient"])
            missing_paths = {item["path"] for item in payload["missing_requirements"]}
            self.assertIn("missing_access_audits.reader_task_results", missing_paths)
            self.assertIn("missing_access_audits.treatment_judgments", missing_paths)

    def test_pilot_explicit_not_measured_treatments_use_bounds_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            locator, missing, structure = base_documents(subject_count=109)
            for treatment in missing["treatment_judgments"][-2:]:
                treatment.pop("status")
            result = calculate(Path(temporary), locator, missing, structure, audit_mode="pilot")
        reliability = dimension(result, "page_reference_reliability")
        self.assertEqual("scored", reliability["status"])
        self.assertEqual(5, reliability["final_rating"])
        self.assertEqual(2, reliability["raw_status_counts"]["treatment_recall"]["not_measured"])
        self.assertEqual(2, reliability["raw_status_counts"]["not_measured_treatments"])

        with tempfile.TemporaryDirectory() as temporary:
            locator, missing, structure = base_documents(subject_count=109)
            for treatment in missing["treatment_judgments"][-20:]:
                treatment.pop("status")
            result = calculate(Path(temporary), locator, missing, structure, audit_mode="pilot")
        reliability = dimension(result, "page_reference_reliability")
        self.assertEqual("not_scored_insufficient_evidence", reliability["status"])
        self.assertIsNone(reliability["final_rating"])

    def test_pilot_known_supporting_unknowns_do_not_enter_high_value_cap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            locator, missing, structure = base_documents(subject_count=109)
            for index, treatment in enumerate(missing["treatment_judgments"]):
                treatment["locator_class"] = "principal" if index < 9 else "supporting"
            for treatment in missing["treatment_judgments"][-2:]:
                treatment.pop("status")
            result = calculate(Path(temporary), locator, missing, structure, audit_mode="pilot")
        reliability = dimension(result, "page_reference_reliability")
        self.assertEqual("scored", reliability["status"])
        self.assertEqual(5, reliability["final_rating"])
        lower_high_value_cap = next(
            item
            for item in reliability["missing_data_bounds"]["lower"]["cap_evaluations"]
            if item["cap_id"] == "reliability.high_value_treatment_recall"
        )
        self.assertFalse(lower_high_value_cap["triggered"])
        self.assertEqual({"found": 9, "expected": 9, "rate": "1"}, lower_high_value_cap["observed"])

    def test_uninspectable_neutral_stable_and_unstable_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stable = calculate(root, *base_documents(subject_count=100, uninspectable_major=True))
            coverage = stable["dimensions"][0]
            self.assertEqual("scored", coverage["status"])
            self.assertEqual(5, coverage["final_rating"])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            unstable = calculate(root, *base_documents(subject_count=2, uninspectable_major=True))
            coverage = unstable["dimensions"][0]
            self.assertEqual("not_scored_insufficient_evidence", coverage["status"])
            self.assertIsNone(unstable["total_score"])

    def test_all_uninspectable_component_is_not_scored_or_zeroed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            locator, missing, structure = base_documents()
            for subject in missing["subject_judgments"]:
                subject["coverage"] = "uninspectable"
                subject["direct_access"] = False
                subject["stance_preserved"] = "uninspectable"
            result = calculate(Path(temporary), locator, missing, structure)
        coverage = dimension(result, "meaningful_coverage")
        denominator = coverage["denominators"]["components"][0]
        self.assertEqual("0", denominator["measurement_coverage"])
        self.assertIsNone(denominator["defined_zero_rule"])
        self.assertEqual("not_scored_insufficient_evidence", coverage["status"])
        self.assertIsNone(coverage["final_rating"])
        self.assertIsNone(result["total_score"])

    def test_coverage_conditioned_task_bounds_order_coupled_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            locator, missing, structure = base_documents()
            missing["subject_judgments"][1]["coverage"] = "uninspectable"
            missing["subject_judgments"][1]["direct_access"] = False
            missing["subject_judgments"][1]["stance_preserved"] = "uninspectable"
            missing["reader_task_results"][1]["result"] = "fails"
            config = calculation_files(root, locator, missing, structure, audit_mode="pilot")
            ledgers, gaps = v5.preflight_loaded(v5.load_inputs(config))
            self.assertFalse(gaps)
            central, lower, upper, _, _, bounds = v5.task_component(ledgers)
        self.assertEqual(Decimal(1), central)
        self.assertEqual(Decimal("0.5"), lower)
        self.assertEqual(Decimal(1), upper)
        self.assertEqual("adverse_coverage_eligibility_and_task_credit", bounds["lower_scenario"])
        self.assertEqual("favorable_coverage_eligibility_and_task_credit", bounds["upper_scenario"])

    def test_pilot_task_and_treatment_may_reference_expected_unjudged_subject(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            locator, missing, structure = base_documents()
            missing["subject_judgments"] = [missing["subject_judgments"][0]]
            missing["completion"] = {"expected": 2, "judged": 1, "complete": False}
            config = calculation_files(Path(temporary), locator, missing, structure, audit_mode="pilot")
            ledgers, gaps = v5.preflight_loaded(v5.load_inputs(config))
            self.assertFalse(gaps)
            self.assertIn("TASK-0002", {item["task_id"] for item in ledgers["tasks"]})
            self.assertIn("TREAT-0002", {item["treatment_id"] for item in ledgers["treatments"]})
            central, lower, upper, _, _, bounds = v5.task_component(ledgers)
        self.assertEqual(Decimal(1), central)
        self.assertEqual(Decimal(1), lower)
        self.assertEqual(Decimal(1), upper)
        self.assertIn("TASK-0002", bounds["upper_coverage_uncertain_included_ids"])

    def test_full_unjudged_expected_subject_still_blocks_scoring(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            locator, missing, structure = base_documents()
            missing["subject_judgments"] = [missing["subject_judgments"][0]]
            missing["completion"] = {"expected": 2, "judged": 1, "complete": False}
            config = calculation_files(Path(temporary), locator, missing, structure, audit_mode="full")
            _, gaps = v5.preflight_loaded(v5.load_inputs(config))
        self.assertTrue(any(item["code"] == "incomplete_full_audit" and "SUBJ-0002" in item.get("item_ids", []) for item in gaps))

    def test_coverage_uncertain_task_with_unknown_result_has_genuine_adverse_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            locator, missing, structure = base_documents()
            missing["subject_judgments"][1].update({
                "coverage": "uninspectable",
                "direct_access": False,
                "stance_preserved": "uninspectable",
            })
            missing["reader_task_results"][1]["result"] = "uninspectable"
            config = calculation_files(Path(temporary), locator, missing, structure, audit_mode="pilot")
            ledgers, gaps = v5.preflight_loaded(v5.load_inputs(config))
            self.assertFalse(gaps)
            central, lower, upper, _, _, bounds = v5.task_component(ledgers)
            result = v5.calculate_loaded(v5.load_inputs(config))
        self.assertEqual(Decimal(1), central)
        self.assertEqual(Decimal("0.5"), lower)
        self.assertEqual(Decimal(1), upper)
        self.assertEqual(["TASK-0002"], bounds["lower_coverage_uncertain_included_ids"])
        self.assertEqual(["TASK-0002"], bounds["lower_failure_evidence"])
        navigation = dimension(result, "findability_navigation")
        self.assertEqual("not_scored_insufficient_evidence", navigation["status"])
        self.assertEqual("3.333333333333333333333333334", navigation["missing_data_bounds"]["lower"]["pre_cap_rating"])
        self.assertEqual(2, navigation["missing_data_bounds"]["lower"]["rounded_rating"])
        self.assertEqual("findability.task_failure_50_percent", navigation["missing_data_bounds"]["lower"]["applied_cap_id"])
        self.assertEqual(5, navigation["missing_data_bounds"]["upper"]["rounded_rating"])

    def test_task_coverage_conditioning_and_no_reference_renormalization(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            locator, missing, structure = base_documents()
            missing["subject_judgments"][1]["coverage"] = "missing"
            missing["subject_judgments"][1]["direct_access"] = False
            missing["reader_task_results"][1]["result"] = "fails"
            result = calculate(root, locator, missing, structure)
            navigation = next(item for item in result["dimensions"] if item["dimension_id"] == "findability_navigation")
            self.assertEqual(1, navigation["raw_status_counts"]["tasks_excluded_due_to_coverage"])
            self.assertEqual("0.6666666666666666666666666667", navigation["components"][0]["effective_weight"])
            self.assertTrue(navigation["components"][0]["weight_renormalized"])

    def test_all_tasks_excluded_by_missing_coverage_make_navigation_not_scoreable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            locator, missing, structure = base_documents()
            for subject in missing["subject_judgments"]:
                subject["coverage"] = "missing"
                subject["direct_access"] = False
                subject["matched_path_ids"] = []
            result = calculate(Path(temporary), locator, missing, structure)
        navigation = dimension(result, "findability_navigation")
        task_denominator = next(item for item in navigation["denominators"]["components"] if item["component_id"] == "coverage_conditioned_reader_tasks")
        self.assertEqual(0, task_denominator["applicable"])
        self.assertEqual(2, task_denominator["exclusion_reasons"]["excluded_due_to_missing_access"])
        self.assertIsNone(task_denominator["defined_zero_rule"])
        self.assertFalse(task_denominator["provisionally_scoreable"])
        self.assertEqual("not_scored_insufficient_evidence", navigation["status"])
        self.assertIsNone(navigation["final_rating"])
        self.assertIsNone(result["total_score"])

    def test_low_coverage_can_have_conditionally_strong_navigation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            locator, missing, structure = base_documents()
            missing["subject_judgments"][1]["coverage"] = "missing"
            missing["subject_judgments"][1]["direct_access"] = False
            missing["reader_task_results"][1]["result"] = "fails"
            missing["treatment_judgments"][1]["status"] = "missed"
            result = calculate(root, locator, missing, structure)
        self.assertEqual(3, dimension(result, "meaningful_coverage")["final_rating"])
        navigation = dimension(result, "findability_navigation")
        self.assertEqual(5, navigation["final_rating"])
        self.assertEqual(1, navigation["raw_status_counts"]["tasks_excluded_due_to_coverage"])

    def test_absent_references_with_warranted_route_are_not_inapplicable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            locator, missing, structure = base_documents()
            structure["v5_scoring_context"]["cross_reference_applicability"] = {
                "status": "applicable",
                "basis_code": "warranted_reference_obligation",
                "delivered_reference_count": 0,
                "warranted_reference_obligation_count": 1,
                "warranted_reference_obligation_ids": ["SUBJ-0001"],
                "reference_defect_ids": [],
            }
            result = calculate(root, locator, missing, structure)
            navigation = next(item for item in result["dimensions"] if item["dimension_id"] == "findability_navigation")
            reference = next(item for item in navigation["components"] if item["component_id"] == "cross_reference_validity")
            self.assertEqual("0", reference["normalized_value"])
            self.assertFalse(reference["weight_renormalized"])
            self.assertEqual(4.5, navigation["final_rating"])

    def test_delivered_reference_does_not_hide_an_undelivered_warranted_route(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            locator, missing, structure = base_documents()
            structure["metrics"]["cross_references"] = 1
            structure["expected_cross_reference_ids"] = ["XREF-0001"]
            structure["cross_reference_judgments"] = [{"reference_id": "XREF-0001", "judgment": "supported", "summary": "Supported.", "severity": "none", "confidence": "high", "evidence_ids": []}]
            structure["completion"].update({"expected_cross_references": 1, "judged_cross_references": 1})
            structure["v5_scoring_context"]["cross_reference_applicability"] = {
                "status": "applicable",
                "basis_code": "delivered_references",
                "delivered_reference_count": 1,
                "warranted_reference_obligation_count": 1,
                "warranted_reference_obligation_ids": ["SUBJ-0001"],
                "reference_defect_ids": [],
            }
            result = calculate(root, locator, missing, structure)
        reference = next(item for item in dimension(result, "findability_navigation")["components"] if item["component_id"] == "cross_reference_validity")
        self.assertEqual("0.5", reference["normalized_value"])
        self.assertEqual(1, reference["details"]["warranted_undelivered_zero_count"])

    def test_reference_defect_without_a_delivered_route_is_adverse_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            locator, missing, structure = base_documents()
            record = defect("DEFECT-XREF", "findability_navigation", "XRF", "major", kind="misleading_access_route", affected=["SUBJ-0001"], applicable=2, structural_denominator=2)
            structure["v5_scoring_context"]["defects"] = [record]
            structure["defects"] = [copy.deepcopy(record)]
            structure["v5_scoring_context"]["cross_reference_applicability"] = {
                "status": "applicable",
                "basis_code": "reference_defect",
                "delivered_reference_count": 0,
                "warranted_reference_obligation_count": 0,
                "warranted_reference_obligation_ids": [],
                "reference_defect_ids": ["DEFECT-XREF"],
            }
            result = calculate(root, locator, missing, structure)
        navigation = dimension(result, "findability_navigation")
        reference = next(item for item in navigation["components"] if item["component_id"] == "cross_reference_validity")
        self.assertEqual("0", reference["normalized_value"])
        self.assertEqual(1, reference["details"]["reference_defect_zero_count"])
        self.assertNotEqual("not_scored_insufficient_evidence", navigation["status"])

    def test_reference_defect_cannot_reclassify_another_dimension_defect(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            locator, missing, structure = base_documents()
            record = defect("DEFECT-MECHANICS", "mechanics_consistency", "MEC", "major", affected=["NODE-0001"], applicable=2, structural_denominator=2)
            structure["defects"] = [copy.deepcopy(record)]
            structure["v5_scoring_context"]["defects"] = [record]
            structure["v5_scoring_context"]["cross_reference_applicability"] = {
                "status": "applicable",
                "basis_code": "reference_defect",
                "delivered_reference_count": 0,
                "warranted_reference_obligation_count": 0,
                "warranted_reference_obligation_ids": [],
                "reference_defect_ids": ["DEFECT-MECHANICS"],
            }
            config = calculation_files(Path(temporary), locator, missing, structure)
            payload = run_cli("dimension_score_cli.py", "preflight", "--input", config)
        self.assertFalse(payload["sufficient"])
        self.assertEqual("invalid_scoring_context", payload["missing_requirements"][0]["code"])

    def test_delivered_reference_id_cannot_be_an_undelivered_obligation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            locator, missing, structure = base_documents()
            structure["metrics"]["cross_references"] = 1
            structure["expected_cross_reference_ids"] = ["XREF-0001"]
            structure["cross_reference_judgments"] = [{"reference_id": "XREF-0001", "judgment": "supported", "summary": "Supported.", "severity": "none", "confidence": "high", "evidence_ids": []}]
            structure["completion"].update({"expected_cross_references": 1, "judged_cross_references": 1})
            structure["v5_scoring_context"]["cross_reference_applicability"] = {
                "status": "applicable",
                "basis_code": "warranted_reference_obligation",
                "delivered_reference_count": 1,
                "warranted_reference_obligation_count": 1,
                "warranted_reference_obligation_ids": ["XREF-0001"],
                "reference_defect_ids": [],
            }
            config = calculation_files(Path(temporary), locator, missing, structure)
            payload = run_cli("dimension_score_cli.py", "preflight", "--input", config, expect_ok=False)
        self.assertFalse(payload["ok"])
        self.assertEqual("input_schema_validation_failed", payload["error"]["code"])

    def test_structure_defect_projection_must_match_scoring_context(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            locator, missing, structure = base_documents()
            record = defect("DEFECT-COV-MISMATCH", "meaningful_coverage", "COV", "major", affected=["SUBJ-0001"], applicable=2, structural_denominator=2)
            structure["v5_scoring_context"]["defects"] = [record]
            config = calculation_files(Path(temporary), locator, missing, structure)
            payload = run_cli("dimension_score_cli.py", "preflight", "--input", config)
        self.assertFalse(payload["sufficient"])
        self.assertEqual("structure_defect_projection_mismatch", payload["missing_requirements"][0]["code"])

    def test_defect_applicable_count_is_bound_to_frozen_item_family(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            locator, missing, structure = base_documents(subject_count=100)
            record = defect(
                "DEFECT-FORGED-DENOMINATOR",
                "mechanics_consistency",
                "MEC",
                "critical",
                affected=["NODE-0001", "NODE-0002", "NODE-0003"],
                structural_sections=["NODE-0001"],
                applicable=10,
                structural_denominator=100,
            )
            record.update({
                "severity_basis": "systemic_nonuse",
                "affected_source_sections": [],
                "source_section_rate": "0",
            })
            structure["defects"] = [copy.deepcopy(record)]
            structure["v5_scoring_context"]["defects"] = [record]
            for node_record in structure["node_judgments"][:3]:
                mechanics = node_record["component_judgments"]["mechanics_consistency"]
                mechanics["status"] = "fails"
                mechanics["evidence_ids"] = [record["defect_id"]]
            with self.assertRaises(v5.CalculationError) as caught:
                calculate(Path(temporary), locator, missing, structure)
        self.assertEqual("migration_inputs_insufficient", caught.exception.code)
        self.assertEqual("scoring_context_ledger_mismatch", caught.exception.details[0]["code"])
        self.assertEqual(
            {"item_family": "node", "expected": 100, "actual": 10},
            caught.exception.details[0]["details"],
        )

    def test_path_denominator_is_recomputed_from_locator_path_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            locator, missing, structure = base_documents(subject_count=100)
            structure["metrics"]["page_bearing_paths"] = 10
            record = defect(
                "DEFECT-FORGED-PATH-DENOMINATOR",
                "conceptual_stance_fidelity",
                "CON",
                "critical",
                affected=["PATH-0001", "PATH-0002", "PATH-0003"],
                applicable=10,
                structural_denominator=100,
            )
            record.update({
                "severity_basis": "systemic_nonuse",
                "affected_source_sections": [],
                "source_section_rate": "0",
            })
            structure["defects"] = [copy.deepcopy(record)]
            structure["v5_scoring_context"]["defects"] = [record]
            with self.assertRaises(v5.CalculationError) as caught:
                calculate(Path(temporary), locator, missing, structure)
        self.assertEqual("migration_inputs_insufficient", caught.exception.code)
        self.assertEqual("recomputable_aggregate_mismatch", caught.exception.details[0]["code"])
        self.assertEqual("metrics.page_bearing_paths", caught.exception.details[0]["details"]["field"])
        self.assertEqual(100, caught.exception.details[0]["details"]["minimum"])
        self.assertEqual(10, caught.exception.details[0]["details"]["actual"])

    def test_density_counts_are_recomputed_from_locator_ledgers(self) -> None:
        for field, forged_value in (("locator_bearing_heading_paths", 8), ("locator_occurrences", 20)):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                locator, missing, structure = base_documents()
                structure["density"]["chapter_measurements"][0][field] = forged_value
                with self.assertRaises(v5.CalculationError) as caught:
                    calculate(Path(temporary), locator, missing, structure)
            self.assertEqual("migration_inputs_insufficient", caught.exception.code)
            self.assertEqual("recomputable_aggregate_mismatch", caught.exception.details[0]["code"])
            self.assertEqual(field, caught.exception.details[0]["details"]["field"])

    def test_inapplicable_reference_context_cannot_omit_an_identified_xrf_defect(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            locator, missing, structure = base_documents()
            record = defect(
                "DEFECT-XRF-OMITTED",
                "findability_navigation",
                "XRF",
                "minor",
                kind="unsupported_reference",
                affected=["SUBJ-0001"],
                applicable=2,
                structural_denominator=2,
            )
            structure["defects"] = [copy.deepcopy(record)]
            structure["v5_scoring_context"]["defects"] = [record]
            config = calculation_files(Path(temporary), locator, missing, structure)
            payload = run_cli("dimension_score_cli.py", "preflight", "--input", config)
        self.assertFalse(payload["sufficient"])
        self.assertEqual("invalid_scoring_context", payload["missing_requirements"][0]["code"])
        self.assertIn("DEFECT-XRF-OMITTED", payload["missing_requirements"][0]["details"]["missing_reference_defect_ids"])

    def test_empty_index_is_zero_not_favorably_inapplicable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            locator, missing, structure = base_documents()
            locator["expected_locator_ids"] = []
            locator["judgments"] = []
            locator["completion"] = {"expected": 0, "judged": 0, "unique": True, "complete": True}
            for subject in missing["subject_judgments"]:
                subject["coverage"] = "missing"
                subject["direct_access"] = False
            for task in missing["reader_task_results"]:
                task["result"] = "fails"
            for treatment in missing["treatment_judgments"]:
                treatment["status"] = "missed"
            structure["expected_node_ids"] = []
            structure["node_judgments"] = []
            structure["completion"]["expected_nodes"] = 0
            structure["completion"]["judged_nodes"] = 0
            structure["metrics"]["page_bearing_paths"] = 0
            structure["metrics"]["expanded_locators"] = 0
            structure["density"]["chapter_measurements"][0]["locator_bearing_heading_paths"] = 0
            structure["density"]["chapter_measurements"][0]["locator_occurrences"] = 0
            structure["v5_scoring_context"]["candidate_attempt"]["status"] = "empty"
            structure["v5_scoring_context"]["candidate_attempt"]["evidence_ids"] = ["GLOBAL-STRUCTURE"]
            result = calculate(root, locator, missing, structure)
            self.assertEqual(0, result["total_score"])
            self.assertTrue(all(item["final_rating"] == 0 for item in result["dimensions"] if item["dimension_id"] != "editorial_selectivity"))
            self.assertEqual(0, next(item for item in result["dimensions"] if item["dimension_id"] == "editorial_selectivity")["awarded_points"])

    def test_density_is_owned_only_by_selectivity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = calculate(root, *base_documents())
            density_owners = [item["dimension_id"] for item in result["dimensions"] if any(component["component_id"] == "density_fit" for component in item["components"])]
            self.assertEqual(["editorial_selectivity"], density_owners)

    def test_localized_recurrent_systematic_and_aggregate_mechanics(self) -> None:
        ledgers = {"defects": [], "node_original": 100}
        self.assertFalse(any(item["triggered"] for item in v5.mechanics_pattern_caps(ledgers)))
        ledgers["defects"] = [defect("DEFECT-LOC", "mechanics_consistency", "MEC", "major", affected=["NODE-1"], structural_sections=["A"])]
        self.assertFalse(any("recurrent_major" in item["cap_id"] and item["triggered"] for item in v5.mechanics_pattern_caps(ledgers)))
        ledgers["defects"] = [defect("DEFECT-REC", "mechanics_consistency", "MEC", "major", kind="representation_corruption", affected=["NODE-1", "NODE-2", "NODE-3"], structural_sections=["A", "B"], family="representation")]
        self.assertTrue(any("recurrent_major" in item["cap_id"] and item["triggered"] for item in v5.mechanics_pattern_caps(ledgers)))
        ledgers["defects"] = [defect("DEFECT-SYS", "mechanics_consistency", "MEC", "major", affected=[f"NODE-{i}" for i in range(10)], structural_sections=["A"], family="systematic")]
        self.assertTrue(any("systematic_major" in item["cap_id"] and item["triggered"] for item in v5.mechanics_pattern_caps(ledgers)))

    def test_strong_coverage_with_stance_reversal_uses_consequence_cap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            locator, missing, structure = base_documents(subject_count=100)
            record = defect("DEFECT-STANCE", "conceptual_stance_fidelity", "STA", "major", kind="stance_reversal", affected=["NODE-0001"], applicable=100, structural_denominator=100)
            structure["v5_scoring_context"]["defects"] = [record]
            structure["defects"] = [copy.deepcopy(record)]
            concept = structure["node_judgments"][0]["component_judgments"]["conceptual_stance_fidelity"]
            concept["status"] = "major_issues"
            concept["evidence_ids"] = ["DEFECT-STANCE"]
            result = calculate(root, locator, missing, structure)
        self.assertEqual(5, dimension(result, "meaningful_coverage")["final_rating"])
        fidelity = dimension(result, "conceptual_stance_fidelity")
        self.assertEqual(4, fidelity["final_rating"])
        self.assertEqual("concept.major_stance_or_relationship", fidelity["applied_cap"]["cap_id"])

    def test_structured_critical_and_navigation_consequence_caps(self) -> None:
        scenarios = (
            ("meaningful_coverage", defect("DEFECT-COV", "meaningful_coverage", "COV", "critical", kind="central_omission", affected=["SUBJ-0001"], applicable=2), "coverage.critical_central_omission", 2),
            ("page_reference_reliability", defect("DEFECT-LOC", "page_reference_reliability", "LOC_POS", "critical", kind="fabricated_locator", affected=["LOC-0001"], applicable=4), "reliability.critical_locator", 2),
            ("findability_navigation", defect("DEFECT-NAV-LOCAL", "findability_navigation", "HED", "major", affected=["NODE-0001"], applicable=2), "findability.localized_major_navigation", 4.5),
            ("findability_navigation", defect("DEFECT-NAV-ROUTE", "findability_navigation", "HED", "major", kind="misleading_access_route", affected=["SUBJ-0001"], applicable=2, high_priority=True), "findability.destructive_access_route", 3.5),
            ("findability_navigation", defect("DEFECT-NAV-CRIT", "findability_navigation", "HED", "critical", kind="misleading_access_route", affected=["SUBJ-0001"], applicable=2, high_priority=True), "findability.critical_navigation", 2),
        )
        for dimension_id, record, cap_id, maximum in scenarios:
            with self.subTest(cap=cap_id), tempfile.TemporaryDirectory() as temporary:
                locator, missing, structure = base_documents()
                structure["v5_scoring_context"]["defects"] = [record]
                structure["defects"] = [copy.deepcopy(record)]
                result = calculate(Path(temporary), locator, missing, structure)
                scored = dimension(result, dimension_id)
                self.assertEqual(cap_id, scored["applied_cap"]["cap_id"])
                self.assertEqual(maximum, scored["final_rating"])

    def test_critical_concept_cap_requires_and_uses_node_bound_defect(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            locator, missing, structure = base_documents(subject_count=100)
            record = defect("DEFECT-CON-CRIT", "conceptual_stance_fidelity", "CON", "critical", kind="stance_reversal", affected=["NODE-0001"], applicable=100, structural_denominator=100)
            structure["v5_scoring_context"]["defects"] = [record]
            structure["defects"] = [copy.deepcopy(record)]
            component_judgment = structure["node_judgments"][0]["component_judgments"]["conceptual_stance_fidelity"]
            component_judgment["status"] = "fails"
            component_judgment["evidence_ids"] = ["DEFECT-CON-CRIT"]
            result = calculate(Path(temporary), locator, missing, structure)
        fidelity = dimension(result, "conceptual_stance_fidelity")
        self.assertEqual("concept.critical_defect", fidelity["applied_cap"]["cap_id"])
        self.assertEqual(2, fidelity["final_rating"])

    def test_mechanics_localized_recurrent_and_pervasive_adversarial_cases(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            locator, missing, structure = base_documents(subject_count=100)
            localized = defect("DEFECT-LOCAL", "mechanics_consistency", "MEC", "major", affected=["NODE-0001"], applicable=100, structural_denominator=100, family="local")
            structure["v5_scoring_context"]["defects"] = [localized]
            structure["defects"] = [copy.deepcopy(localized)]
            mechanics = structure["node_judgments"][0]["component_judgments"]["mechanics_consistency"]
            mechanics["status"] = "major_issues"
            mechanics["evidence_ids"] = ["DEFECT-LOCAL"]
            result = calculate(root, locator, missing, structure)
            self.assertEqual(4.5, dimension(result, "mechanics_consistency")["final_rating"])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            locator, missing, structure = base_documents(subject_count=100)
            recurrent = defect("DEFECT-REP", "mechanics_consistency", "MEC", "major", kind="representation_corruption", affected=["NODE-0001", "NODE-0002", "NODE-0003"], structural_sections=["NODE-0001", "NODE-0002"], applicable=100, structural_denominator=100, family="representation")
            structure["v5_scoring_context"]["defects"] = [recurrent]
            structure["defects"] = [copy.deepcopy(recurrent)]
            for node_record in structure["node_judgments"][:3]:
                mechanics = node_record["component_judgments"]["mechanics_consistency"]
                mechanics["status"] = "major_issues"
                mechanics["evidence_ids"] = ["DEFECT-REP"]
            result = calculate(root, locator, missing, structure)
            self.assertEqual(4, dimension(result, "mechanics_consistency")["final_rating"])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            locator, missing, structure = base_documents(subject_count=100)
            for node_record in structure["node_judgments"][:20]:
                node_record["component_judgments"]["mechanics_consistency"]["status"] = "cosmetic_issues"
            result = calculate(root, locator, missing, structure)
            mechanics = dimension(result, "mechanics_consistency")
            self.assertEqual(4, mechanics["final_rating"])
            self.assertEqual("mechanics.aggregate_cosmetic_minor_20_percent", mechanics["applied_cap"]["cap_id"])

    def test_strict_precision_treats_partial_support_as_incorrect(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            locator, missing, structure = base_documents()
            locator["judgments"][1]["judgment"] = "partially_supported"
            result = calculate(root, locator, missing, structure)
        reliability = dimension(result, "page_reference_reliability")
        precision = next(item for item in reliability["components"] if item["component_id"] == "strict_locator_precision")
        self.assertEqual("0.75", precision["normalized_value"])

    def test_score_only_migration_preserves_input_and_gate_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = calculation_files(root, *base_documents())
            historical = root / "historical-v4.json"
            historical_gates = [{"gate_id": "GATE-X", "status": "failed", "metrics": {"rate": 0.125}}]
            historical_value = historical_v4_result(gates=historical_gates, input_root=root)
            historical_value["scorecard"][1]["rating"] = 3.3333
            historical_value["scorecard"][1]["points"] = 10
            write_json(historical, historical_value)
            before = {path.name: digest(path) for path in root.glob("*.json")}
            calculations = root / "dimension-calculations.v1.json"
            migration = root / "score-migration.v2.json"
            result = run_cli("dimension_score_cli.py", "score-only-migration", "--input", config, "--historical-result", historical, "--calculations-output", calculations, "--migration-record-output", migration, *MIGRATION_METADATA_ARGS)
            self.assertFalse(result["input_ledgers_mutated"])
            self.assertFalse(result["historical_result_mutated"])
            self.assertEqual("preserve_identically", result["gate_outcomes_action"])
            for name, value in before.items():
                self.assertEqual(value, digest(root / name))
            migration_record = json.loads(migration.read_text())
            v5.validate_schema_document(migration_record, "score-migration.schema.json", "Score migration record")
            self.assertEqual("subject-index-score-migration-v2", migration_record["schema_version"])
            self.assertEqual(TEST_MIGRATION_TIMESTAMP, migration_record["migration_timestamp"])
            self.assertEqual(TEST_METHODOLOGY_COMMIT, migration_record["methodology"]["commit_sha"])
            self.assertEqual(v5.TOOL_VERSION, migration_record["tool"]["version"])
            self.assertEqual(6, len(migration_record["dimension_comparison"]))
            self.assertEqual(3.3333, migration_record["from"]["scorecard"][1]["rating"])
            self.assertEqual(
                migration_record["to"]["total_score"] - migration_record["from"]["total_score"],
                migration_record["total_delta"],
            )
            portable_paths = [
                migration_record["from"]["historical_result_path"],
                migration_record["to"]["calculation_path"],
                *[item["path"] for item in migration_record["input_lineage"]],
            ]
            for stored_path in portable_paths:
                self.assertFalse(Path(stored_path).is_absolute())
                self.assertNotIn("\\", stored_path)
            lineage = {item["role"]: item for item in migration_record["input_lineage"]}
            self.assertEqual(
                {
                    "historical_v4_result",
                    "dimension_calculation_input",
                    "v5_dimension_calculations",
                    *[item["role"] for item in migration_record["input_ledgers"]],
                },
                set(lineage),
            )
            self.assertEqual("unchanged", lineage["dimension_calculation_input"]["disposition"])
            self.assertEqual(digest(config), lineage["dimension_calculation_input"]["sha256"])
            self.assertEqual("deterministically_derived", lineage["v5_dimension_calculations"]["disposition"])
            gates = migration_record["gate_preservation"]
            self.assertTrue(gates["outcomes_equal"])
            self.assertEqual(gates["historical_gate_outcomes_sha256"], gates["preserved_gate_outcomes_sha256"])
            self.assertEqual({
                "candidate_sha256", "source_sha256", "benchmark_sha256", "policy_sha256",
                "page_map_sha256", "chunk_manifest_sha256", "normalized_candidate_file_sha256",
                "item_inventory_file_sha256", "structure_audit_file_sha256",
                "locator_audit_set_sha256", "missing_access_audit_set_sha256", "audit_mode",
            }, set(gates["identity_checks"]))
            self.assertEqual(digest(calculations), migration_record["to"]["calculation_file_sha256"])
            calculation_value = json.loads(calculations.read_text(encoding="utf-8"))
            self.assertEqual("subject-index-score-migration-v2", calculation_value["migration_context"]["migration_schema_version"])
            self.assertFalse(Path(calculation_value["migration_context"]["migration_record_path"]).is_absolute())
            self.assertEqual(calculation_value["calculation_sha256"], migration_record["to"]["calculation_canonical_sha256"])
            self.assertEqual(
                gates["historical_gate_outcomes_sha256"],
                calculation_value["migration_context"]["historical_gate_outcomes_sha256"],
            )

            item_assessments_path = root / "item-assessments.v1.json"
            write_json(item_assessments_path, minimal_item_assessments(calculation_value, root / "item-inventory.json"))
            evaluation_result = evaluation_projection(
                calculation_value,
                calculations,
                item_assessments_path,
                critical_gates=historical_gates,
                migration_path=migration,
            )
            evaluation_path = root / "evaluation-result.v6.json"
            write_json(evaluation_path, evaluation_result)
            self.assertTrue(v5.validate_projection_artifacts(calculations, evaluation_path)["ok"])

            web_report = web_projection(
                calculation_value,
                calculations,
                item_assessments_path,
                historical_gates,
                migration_path=migration,
            )
            web_path = root / "web-report.v4.json"
            write_json(web_path, web_report)
            self.assertTrue(v5.validate_projection_artifacts(calculations, evaluation_path, web_path)["ok"])
            config_hash_before_receipt = digest(config)
            refused_receipt = run_cli(
                "dimension_score_cli.py",
                "validate-projections",
                "--calculation",
                calculations,
                "--evaluation-result",
                evaluation_path,
                "--web-report",
                web_path,
                "--output",
                config,
                "--methodology-commit",
                TEST_METHODOLOGY_COMMIT,
                "--validation-timestamp",
                TEST_MIGRATION_TIMESTAMP,
                expect_ok=False,
            )
            self.assertEqual("output_aliases_frozen_input", refused_receipt["error"]["code"])
            self.assertEqual(config_hash_before_receipt, digest(config))
            receipt_path = root / "score-migration-validation.v1.json"
            validation = run_cli(
                "dimension_score_cli.py",
                "validate-projections",
                "--calculation",
                calculations,
                "--evaluation-result",
                evaluation_path,
                "--web-report",
                web_path,
                "--output",
                receipt_path,
                "--methodology-commit",
                TEST_METHODOLOGY_COMMIT,
                "--validation-timestamp",
                TEST_MIGRATION_TIMESTAMP,
            )
            self.assertEqual(digest(receipt_path), validation["migration_validation_receipt"]["sha256"])
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            v5.validate_schema_document(receipt, "score-migration-validation.schema.json", "Migration validation receipt")
            self.assertEqual(receipt["validation_sha256"], v5.canonical_hash(receipt, "validation_sha256"))
            self.assertEqual(digest(evaluation_path), receipt["artifacts"]["evaluation_result"]["sha256"])
            self.assertEqual(digest(web_path), receipt["artifacts"]["web_report"]["sha256"])
            for artifact in receipt["artifacts"].values():
                self.assertFalse(Path(artifact["path"]).is_absolute())
                self.assertNotIn("\\", artifact["path"])

            nonportable = copy.deepcopy(migration_record)
            nonportable["from"]["historical_result_path"] = str(historical.resolve())
            with self.assertRaises(v5.CalculationError):
                v5.validate_schema_document(nonportable, "score-migration.schema.json", "Nonportable V2 migration")

            undeclared_v2_context = copy.deepcopy(calculation_value)
            undeclared_v2_context["migration_context"].pop("migration_schema_version")
            undeclared_v2_context["calculation_sha256"] = v5.canonical_hash(undeclared_v2_context, "calculation_sha256")
            undeclared_v2_path = root / "dimension-calculations.undeclared-v2.json"
            write_json(undeclared_v2_path, undeclared_v2_context)
            with self.assertRaises(v5.CalculationError) as caught:
                v5.validate_migration_record_for_calculation(undeclared_v2_context, undeclared_v2_path, migration)
            self.assertEqual("score_migration_binding_mismatch", caught.exception.code)

            legacy_calculation = copy.deepcopy(calculation_value)
            legacy_migration_path = root / "score-migration.v1.json"
            legacy_calculation_path = root / "dimension-calculations.legacy-v1.json"
            legacy_calculation["migration_context"].pop("migration_schema_version")
            legacy_calculation["migration_context"]["migration_record_path"] = str(legacy_migration_path.resolve())
            legacy_calculation["calculation_sha256"] = v5.canonical_hash(legacy_calculation, "calculation_sha256")
            write_json(legacy_calculation_path, legacy_calculation)
            legacy_migration = {
                "schema_version": "subject-index-score-migration-v1",
                "evaluation_id": migration_record["evaluation_id"],
                "from": {
                    "rubric_version": "subject-index-rubric-v4",
                    "historical_result_path": str(historical.resolve()),
                    "historical_result_sha256": digest(historical),
                    "total_score": migration_record["from"]["total_score"],
                },
                "to": {
                    "rubric_version": "subject-index-rubric-v5",
                    "calculation_profile": "subject-index-dimension-calculation-v1",
                    "calculation_path": str(legacy_calculation_path.resolve()),
                    "calculation_file_sha256": digest(legacy_calculation_path),
                    "calculation_canonical_sha256": legacy_calculation["calculation_sha256"],
                    "total_score": legacy_calculation["total_score"],
                },
                "input_ledgers": migration_record["input_ledgers"],
                "input_ledgers_mutated": False,
                "historical_result_mutated": False,
                "gate_preservation": {
                    key: value
                    for key, value in migration_record["gate_preservation"].items()
                    if key not in {"historical_outcomes", "preserved_outcomes"}
                },
                "comparability": "v4_and_v5_totals_are_not_directly_comparable",
            }
            legacy_migration["migration_sha256"] = v5.canonical_hash(legacy_migration, "migration_sha256")
            write_json(legacy_migration_path, legacy_migration)
            self.assertEqual(
                "subject-index-score-migration-v1",
                v5.validate_migration_record_for_calculation(legacy_calculation, legacy_calculation_path)["schema_version"],
            )

            changed_gates = copy.deepcopy(evaluation_result)
            changed_gates["critical_gates"][0]["status"] = "passed"
            changed_gates_path = root / "changed-gates-result.v6.json"
            write_json(changed_gates_path, changed_gates)
            with self.assertRaises(v5.CalculationError) as caught:
                v5.validate_projection_artifacts(calculations, changed_gates_path)
            self.assertEqual("gate_preservation_mismatch", caught.exception.code)

            changed_migration_reference = copy.deepcopy(evaluation_result)
            changed_migration_reference["score_migration"]["migration_sha256"] = "9" * 64
            changed_migration_path = root / "changed-migration-reference.v6.json"
            write_json(changed_migration_path, changed_migration_reference)
            with self.assertRaises(v5.CalculationError) as caught:
                v5.validate_projection_artifacts(calculations, changed_migration_path)
            self.assertEqual("score_migration_binding_mismatch", caught.exception.code)

    def test_representation_adjustment_remains_a_separate_counterfactual_score_view(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            canonical_root = root / "canonical"
            adjusted_root = root / "adjusted"
            locator, missing, structure = base_documents(subject_count=100)
            representation_defect = defect(
                "DEFECT-REPRESENTATION",
                "mechanics_consistency",
                "MEC",
                "major",
                kind="representation_corruption",
                affected=["NODE-0001", "NODE-0002", "NODE-0003"],
                structural_sections=["NODE-0001", "NODE-0002"],
                applicable=100,
                structural_denominator=100,
                family="representation",
            )
            structure["v5_scoring_context"]["defects"] = [representation_defect]
            structure["defects"] = [copy.deepcopy(representation_defect)]
            for node_record in structure["node_judgments"][:3]:
                mechanics = node_record["component_judgments"]["mechanics_consistency"]
                mechanics["status"] = "major_issues"
                mechanics["evidence_ids"] = ["DEFECT-REPRESENTATION"]
            canonical_config = calculation_files(canonical_root, locator, missing, structure)
            historical_path = canonical_root / "historical-v4.json"
            historical_gates = [{"gate_id": "GATE-UNCHANGED", "status": "failed"}]
            write_json(historical_path, historical_v4_result(gates=historical_gates, input_root=canonical_root))
            representation_path = canonical_root / "representation-adjustment.validation.json"
            write_json(representation_path, {
                "schema_version": "subject-index-representation-adjustment-validation-v1",
                "status": "validated",
                "causal_attribution": "representation_only",
            })
            canonical_calculation_path = canonical_root / "dimension-calculations.v1.json"
            migration_path = canonical_root / "score-migration.v2.json"
            run_cli(
                "dimension_score_cli.py",
                "score-only-migration",
                "--input",
                canonical_config,
                "--historical-result",
                historical_path,
                "--calculations-output",
                canonical_calculation_path,
                "--migration-record-output",
                migration_path,
                *MIGRATION_METADATA_ARGS,
                "--representation-adjustment-provenance",
                representation_path,
            )
            canonical_calculation = json.loads(canonical_calculation_path.read_text(encoding="utf-8"))

            adjusted_config = calculation_files(adjusted_root, *base_documents(subject_count=100))
            adjusted_calculation_path = adjusted_root / "dimension-calculations.v1.json"
            run_cli(
                "dimension_score_cli.py",
                "calculate",
                "--input",
                adjusted_config,
                "--output",
                adjusted_calculation_path,
            )
            adjusted_calculation = json.loads(adjusted_calculation_path.read_text(encoding="utf-8"))
            self.assertEqual(4, dimension(canonical_calculation, "mechanics_consistency")["final_rating"])
            self.assertEqual(5, dimension(adjusted_calculation, "mechanics_consistency")["final_rating"])
            self.assertEqual(1, adjusted_calculation["total_score"] - canonical_calculation["total_score"])

            item_path = canonical_root / "item-assessments.v2.json"
            write_json(item_path, minimal_item_assessments(canonical_calculation, canonical_root / "item-inventory.json"))
            evaluation_path = canonical_root / "evaluation-result.v6.json"
            write_json(
                evaluation_path,
                evaluation_projection(
                    canonical_calculation,
                    canonical_calculation_path,
                    item_path,
                    historical_gates,
                    migration_path=migration_path,
                ),
            )
            report = web_projection(
                canonical_calculation,
                canonical_calculation_path,
                item_path,
                historical_gates,
                migration_path=migration_path,
            )
            migration = json.loads(migration_path.read_text(encoding="utf-8"))
            provenance = migration["representation_adjustment"]["provenance_artifacts"][0]
            report["score_views"]["adjustment_status"] = "separate_evidentiary_correction"
            report["score_views"]["views"].append({
                "view_id": "representation_adjusted",
                "label": "Representation-adjusted counterfactual",
                "view_kind": "counterfactual",
                "score": adjusted_calculation["total_score"],
                "maximum": 100,
                "calculation": {
                    "schema_version": adjusted_calculation["schema_version"],
                    "artifact_path": "../adjusted/dimension-calculations.v1.json",
                    "sha256": digest(adjusted_calculation_path),
                    "calculation_sha256": adjusted_calculation["calculation_sha256"],
                    "rubric_version": adjusted_calculation["rubric_version"],
                    "calculation_profile": adjusted_calculation["calculation_profile"],
                },
                "causal_attribution": "separate_evidentiary_correction_not_methodology_effect",
                "provenance_artifacts": [{
                    "role": provenance["role"],
                    "schema_version": provenance["schema_version"],
                    "artifact_path": provenance["path"],
                    "sha256": provenance["sha256"],
                }],
            })
            report_path = canonical_root / "web-report.v4.json"
            write_json(report_path, report)
            self.assertTrue(v5.validate_projection_artifacts(canonical_calculation_path, evaluation_path, report_path)["ok"])

            unbound_adjustment = copy.deepcopy(report)
            unbound_adjustment["score_views"]["views"][1]["provenance_artifacts"] = []
            unbound_path = canonical_root / "unbound-adjustment.web-report.v4.json"
            write_json(unbound_path, unbound_adjustment)
            with self.assertRaises(v5.CalculationError):
                v5.validate_projection_artifacts(canonical_calculation_path, evaluation_path, unbound_path)

    def test_historical_v3_reconciles_frozen_set_hashes_and_builds_projection_safe_items(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            locator, missing, structure = base_documents()
            config_path = calculation_files(root, locator, missing, structure)
            historical = historical_v4_result(input_root=root)
            historical_path = root / "historical-v4.json"

            structure_path = root / "structure.json"
            structure_value = json.loads(structure_path.read_text(encoding="utf-8"))
            scoring_context = structure_value.pop("v5_scoring_context")
            structure_value["schema_version"] = "structure-audit-v3"
            structure_value.pop("audit_mode")
            for chapter in structure_value["density"]["chapter_measurements"]:
                chapter["metric_results"] = {}
                chapter["unit_fit_rating"] = 5
            canonical_locator_sha256 = structure_value["provenance"]["locator_audit_set_sha256"]
            canonical_missing_sha256 = structure_value["provenance"]["missing_access_audit_set_sha256"]
            historical_locator_sha256 = "ce3277a02326112ea94614d61808c9d2d4112a62aad11d2d193c28c1a6c7790f"
            historical_missing_sha256 = "bdbb51482887892d21281e84911cc51e24e6d4286a4257115e8cdcc48436c085"
            structure_value["provenance"] = {
                "benchmark_sha256": structure_value["provenance"]["benchmark_sha256"],
                "normalized_candidate_file_sha256": structure_value["provenance"]["normalized_candidate_file_sha256"],
                "item_inventory_file_sha256": structure_value["provenance"]["item_inventory_file_sha256"],
                "locator_audit_set_sha256": historical_locator_sha256,
                "missing_access_audit_set_sha256": historical_missing_sha256,
            }
            write_json(structure_path, structure_value)
            supplement_path = root / "v5-migration-supplement.json"
            supplement = {
                "schema_version": "subject-index-v5-migration-supplement-v1",
                "evaluation_id": "eval-v5",
                "audit_mode": "full",
                "structure_audit_sha256": digest(structure_path),
                "historical_locator_audit_set_sha256": historical_locator_sha256,
                "historical_missing_access_audit_set_sha256": historical_missing_sha256,
                "locator_audit_set_sha256": canonical_locator_sha256,
                "missing_access_audit_set_sha256": canonical_missing_sha256,
                "audit_set_reconciliation_basis": "same_frozen_files_rehashed_with_subject_index_canonical_audit_set_v1",
                "scoring_context": scoring_context,
            }
            write_json(supplement_path, supplement)
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["inputs"]["structure_audit"]["sha256"] = digest(structure_path)
            config["inputs"]["migration_supplement"] = {"path": supplement_path.name, "sha256": digest(supplement_path)}
            write_json(config_path, config)
            preflight_path = root / "v5-preflight.json"
            preflight = run_cli("dimension_score_cli.py", "preflight", "--input", config_path, "--output", preflight_path)
            self.assertTrue(preflight["sufficient"])
            rejected_native = run_cli("dimension_score_cli.py", "calculate", "--input", config_path, expect_ok=False)
            self.assertEqual("score_only_migration_required", rejected_native["error"]["code"])
            with self.assertRaises(v5.CalculationError) as caught:
                v5.calculate_loaded(v5.load_inputs(config_path))
            self.assertEqual("score_only_migration_required", caught.exception.code)

            bypass_calculation = v5.calculate_loaded(v5.load_inputs(config_path), allow_historical_migration=True)
            bypass_path = root / "unbound-v3-calculation.json"
            write_json(bypass_path, bypass_calculation)
            state = {
                "evaluation_id": "eval-v5",
                "source": {"sha256": "d" * 64},
                "candidate": {"sha256": "a" * 64},
                "configuration": {
                    "audit_mode": "full",
                    "score_profile_history": [{
                        "preflight_path": preflight_path.name,
                        "preflight_sha256": digest(preflight_path),
                        "calculation_input_path": config_path.name,
                        "calculation_input_sha256": digest(config_path),
                    }],
                },
            }
            captured = io.StringIO()
            with redirect_stdout(captured), self.assertRaises(SystemExit) as state_rejection:
                state_manager.require_calculation_matches_state(bypass_calculation, bypass_path, state, root / "evaluation-state.json")
            self.assertEqual(1, state_rejection.exception.code)
            self.assertEqual("score_only_migration_required", json.loads(captured.getvalue())["error"]["code"])

            historical["provenance"]["structure_audit_file_sha256"] = digest(structure_path)
            historical["provenance"]["locator_audit_set_sha256"] = historical_locator_sha256
            historical["provenance"]["missing_access_audit_set_sha256"] = historical_missing_sha256
            write_json(historical_path, historical)
            calculations_path = root / "dimension-calculations.v1.json"
            migration_path = root / "score-migration.v2.json"
            run_cli("dimension_score_cli.py", "score-only-migration", "--input", config_path, "--historical-result", historical_path, "--calculations-output", calculations_path, "--migration-record-output", migration_path, *MIGRATION_METADATA_ARGS)
            migration = json.loads(migration_path.read_text(encoding="utf-8"))
            self.assertFalse(migration["gate_preservation"]["identity_checks"]["locator_audit_set_sha256"]["equal"])
            self.assertEqual("hash_bound_migration_supplement_reconciliation", migration["gate_preservation"]["identity_checks"]["locator_audit_set_sha256"]["comparison_basis"])

            candidate_path = root / "candidate.json"
            write_json(candidate_path, {"candidate_id": "candidate-synthetic", "candidate_sha256": "a" * 64})
            item_path = root / "item-assessments.v2.json"
            item_payload = run_cli(
                "item_grade_cli.py", "build-assessments",
                "--candidate", candidate_path,
                "--inventory", root / "item-inventory.json",
                "--locator-audit", root / "locator.json",
                "--missing-access-audit", root / "missing.json",
                "--structure-audit", structure_path,
                "--audit-mode", "full",
                "--evaluation-id", "eval-v5",
                "--output", item_path,
            )
            self.assertEqual("subject-index-item-assessments-v2", item_payload["schema_version"])
            self.assertEqual(canonical_locator_sha256, item_payload["evidence_identity"]["locator_audit_set_sha256"])
            calculations = json.loads(calculations_path.read_text(encoding="utf-8"))
            evaluation_path = root / "evaluation-result.v6.json"
            write_json(evaluation_path, evaluation_projection(calculations, calculations_path, item_path, historical["critical_gates"], migration_path))
            self.assertTrue(v5.validate_projection_artifacts(calculations_path, evaluation_path)["ok"])

    def test_score_only_migration_rejects_changed_gate_evidence_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = calculation_files(root, *base_documents())
            historical = root / "historical-v4.json"
            historical_value = historical_v4_result(input_root=root)
            historical_value["provenance"]["page_map_sha256"] = "9" * 64
            write_json(historical, historical_value)
            payload = run_cli(
                "dimension_score_cli.py",
                "score-only-migration",
                "--input",
                config,
                "--historical-result",
                historical,
                "--calculations-output",
                root / "dimension-calculations.v1.json",
                "--migration-record-output",
                root / "score-migration.v2.json",
                *MIGRATION_METADATA_ARGS,
                expect_ok=False,
            )
            self.assertEqual("historical_gate_identity_mismatch", payload["error"]["code"])
            self.assertFalse((root / "dimension-calculations.v1.json").exists())
            self.assertFalse((root / "score-migration.v2.json").exists())

    def test_historical_gate_identity_uses_supplement_bound_missing_set(self) -> None:
        historical = historical_v4_result()
        historical["provenance"].update({
            "structure_audit_file_sha256": "5" * 64,
            "locator_audit_set_sha256": "6" * 64,
            "missing_access_audit_set_sha256": "7" * 64,
        })
        identity = {
            "candidate_sha256": "a" * 64,
            "source_sha256": "d" * 64,
            "benchmark_sha256": "b" * 64,
            "policy_sha256": "f" * 64,
            "page_map_sha256": "1" * 64,
            "chunk_manifest_sha256": "2" * 64,
            "normalized_candidate_file_sha256": "3" * 64,
            "item_inventory_file_sha256": "c" * 64,
            "structure_audit_file_sha256": "5" * 64,
            "locator_audit_set_sha256": "6" * 64,
            "missing_access_audit_set_sha256": "7" * 64,
            "audit_mode": "full",
        }
        checks = v5.verify_historical_gate_identity(historical, identity, {"provenance": {}})
        self.assertEqual("7" * 64, checks["missing_access_audit_set_sha256"]["current"])

    def test_canonical_audit_set_hash_is_input_order_independent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            documents = [
                {"chunk_id": "CHUNK-002", "judgments": [{"locator_id": "LOC-002"}]},
                {"chunk_id": "CHUNK-001", "judgments": [{"locator_id": "LOC-001"}]},
            ]
            paths = [root / "second.json", root / "first.json"]
            for path, document in zip(paths, documents, strict=True):
                write_json(path, document)
            hashes = [digest(path) for path in paths]
            forward = v5.canonical_audit_set_hash(documents, paths, hashes, (("judgments", "locator_id", "locator_ids"),))
            reverse = v5.canonical_audit_set_hash(list(reversed(documents)), list(reversed(paths)), list(reversed(hashes)), (("judgments", "locator_id", "locator_ids"),))
        self.assertEqual(forward, reverse)

    def test_score_only_migration_refuses_output_aliasing_a_frozen_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = calculation_files(root, *base_documents())
            historical = root / "historical-v4.json"
            write_json(historical, historical_v4_result(total_score=80, input_root=root))
            before = digest(root / "locator.json")
            payload = run_cli("dimension_score_cli.py", "score-only-migration", "--input", config, "--historical-result", historical, "--calculations-output", root / "locator.json", "--migration-record-output", root / "migration.json", *MIGRATION_METADATA_ARGS, expect_ok=False)
            self.assertEqual("output_aliases_frozen_input", payload["error"]["code"])
            self.assertEqual(before, digest(root / "locator.json"))

    def test_score_only_migration_refuses_hard_link_aliasing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = calculation_files(root, *base_documents())
            historical = root / "historical-v4.json"
            write_json(historical, historical_v4_result(input_root=root))
            ledger = root / "locator.json"
            hard_link = root / "calculation-hard-link.json"
            os.link(ledger, hard_link)
            before = digest(ledger)
            payload = run_cli(
                "dimension_score_cli.py",
                "score-only-migration",
                "--input",
                config,
                "--historical-result",
                historical,
                "--calculations-output",
                hard_link,
                "--migration-record-output",
                root / "migration.json",
                *MIGRATION_METADATA_ARGS,
                expect_ok=False,
            )
            self.assertEqual("output_aliases_frozen_input", payload["error"]["code"])
            self.assertEqual(before, digest(ledger))


class AdversarialAndRegressionTests(unittest.TestCase):
    @staticmethod
    def systemic_boundary_defect(affected_count: int, applicable_count: int) -> dict:
        record = defect(
            "DEFECT-SYSTEMIC-BOUNDARY",
            "mechanics_consistency",
            "MEC",
            "critical",
            affected=[f"NODE-{index:05d}" for index in range(affected_count)],
            source_sections=["CHUNK-001"],
            structural_sections=["NODE-00001"],
            applicable=applicable_count,
            structural_denominator=3,
        )
        record.update({
            "severity_basis": "systemic_nonuse",
            "source_section_denominator": 3,
            "source_section_rate": v5.rounded_rate(1, 3),
        })
        return record

    def test_systemic_threshold_uses_exact_ratios_not_display_rounding(self) -> None:
        just_below = self.systemic_boundary_defect(20_000, 200_001)
        self.assertEqual("0.1", just_below["affected_rate"])
        with self.assertRaises(v5.CalculationError) as caught:
            v5.validate_defect(just_below, 0)
        self.assertEqual("invalid_scoring_context", caught.exception.code)

        exact = self.systemic_boundary_defect(10, 100)
        above = self.systemic_boundary_defect(11, 100)
        self.assertEqual(exact["affected_item_ids"], v5.validate_defect(exact, 0))
        self.assertEqual(above["affected_item_ids"], v5.validate_defect(above, 0))

    def test_adversarial_fixture_manifest_is_complete_and_not_calibration(self) -> None:
        fixture = json.loads((FIXTURES / "v5-adversarial-cases.json").read_text())
        self.assertEqual("synthetic_methodology_stress_tests_not_calibration_targets", fixture["fixture_role"])
        self.assertEqual({
            "empty_index", "concordance_like_overindex", "high_precision_poor_recall",
            "poor_precision_high_recall", "strong_coverage_stance_reversal",
            "low_coverage_conditionally_strong_navigation", "no_cross_references_adequate_direct_access",
            "missing_warranted_access_route", "localized_major_mechanics",
            "recurrent_representation_corruption", "pervasive_minor_or_cosmetic",
        }, {item["case_id"] for item in fixture["required_cases"]})

    def test_concordance_high_precision_poor_recall_and_poor_precision_high_recall(self) -> None:
        # Formula-level adversarial pairs establish that F1 resists compensation.
        self.assertLess(v5.f1(Decimal("0.99"), Decimal("0.20")), Decimal("0.34"))
        self.assertLess(v5.f1(Decimal("0.20"), Decimal("0.99")), Decimal("0.34"))
        cap, triggered, _ = v5.selectivity_cap(Decimal("0.60"), 600, Decimal("1"))
        self.assertTrue(triggered)
        self.assertEqual(Decimal(1), cap)

    def test_published_metric_oxford_regression_expectations_not_calibration(self) -> None:
        fixture = json.loads((FIXTURES / "oxford-published-metrics-regression.v5.json").read_text())
        self.assertEqual("prospective_regression_expectation_not_migration_or_calibration", fixture["fixture_role"])
        coverage = fixture["coverage"]
        coverage_rating = v5.round_half_step(Decimal(5) * Decimal(coverage["weighted_credit"]) / Decimal(coverage["weighted_denominator"]))
        self.assertEqual(Decimal("3.5"), coverage_rating)
        selectivity = fixture["selectivity"]
        substantive_base = Decimal(5) * (Decimal(selectivity["substantive"]) + Decimal("0.5") * Decimal(selectivity["mixed"])) / Decimal(selectivity["applicable"])
        substantive_cap = v5.selectivity_cap(Decimal(selectivity["zero_credit"]) / Decimal(selectivity["applicable"]), selectivity["zero_credit"], Decimal(1))[0]
        substantive = v5.round_half_step(min(substantive_base, substantive_cap))
        selectivity_points = substantive / Decimal(5) * Decimal(10) + Decimal(selectivity["density_rating"])
        self.assertEqual(Decimal(11), selectivity_points)
        reliability = fixture["reliability"]
        p = Decimal(reliability["supported"]) / Decimal(reliability["supported"] + reliability["partially_supported"] + reliability["unsupported"])
        r = Decimal(reliability["found_treatments"]) / Decimal(reliability["found_treatments"] + reliability["missed_treatments"])
        reliability_base = Decimal(5) * v5.f1(p, r)
        pattern_cap = v5.reliability_pattern_cap(reliability["reliability_pattern"], reliability["supported"] + reliability["partially_supported"] + reliability["unsupported"], reliability["source_units_affected"], reliability["source_units"])[0]
        reliability_rating = v5.round_half_step(min(reliability_base, pattern_cap))
        self.assertEqual(Decimal("3.5"), reliability_rating)
        self.assertFalse(v5.high_value_cap(reliability["high_value_found"], reliability["high_value_expected"])[1])

        canonical_ledgers = oxford_regression_ledgers(fixture)
        canonical_dimensions = [
            v5.calculate_coverage(canonical_ledgers, "full"),
            v5.calculate_selectivity(canonical_ledgers, "full"),
            v5.calculate_concept(canonical_ledgers, "full"),
            v5.calculate_reliability(canonical_ledgers, "full"),
            v5.calculate_findability(canonical_ledgers, "full"),
            v5.calculate_mechanics(canonical_ledgers, "full"),
        ]
        canonical_by_id = {item["dimension_id"]: item for item in canonical_dimensions}
        for dimension_id, expected_rating in fixture["expected"]["canonical_dimension_ratings"].items():
            self.assertAlmostEqual(expected_rating, canonical_by_id[dimension_id]["final_rating"], places=12)
        for dimension_id, expected_points in fixture["expected"]["canonical_dimension_points"].items():
            self.assertEqual(Decimal(str(expected_points)), Decimal(str(canonical_by_id[dimension_id]["awarded_points"])))
        canonical_points = sum((Decimal(str(item["awarded_points"])) for item in canonical_dimensions), Decimal(0))

        adjusted_ledgers = oxford_regression_ledgers(fixture, adjusted=True)
        adjusted_dimensions = [
            v5.calculate_coverage(adjusted_ledgers, "full"),
            v5.calculate_selectivity(adjusted_ledgers, "full"),
            v5.calculate_concept(adjusted_ledgers, "full"),
            v5.calculate_reliability(adjusted_ledgers, "full"),
            v5.calculate_findability(adjusted_ledgers, "full"),
            v5.calculate_mechanics(adjusted_ledgers, "full"),
        ]
        adjusted_points = sum((Decimal(str(item["awarded_points"])) for item in adjusted_dimensions), Decimal(0))
        self.assertEqual(Decimal(str(fixture["expected"]["canonical_as_delivered"])), canonical_points)
        self.assertEqual(Decimal(str(fixture["expected"]["representation_adjusted"])), adjusted_points)


class StateIdentityTests(unittest.TestCase):
    def test_score_profile_change_preserves_benchmark_and_audit_stages(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stages = {}
            artifacts = []
            manifest_artifacts = []
            stamp = "2026-08-28T00:00:00Z"
            for stage in v5.WEIGHTS:  # no-op: ensure scoring constants import independently
                self.assertIn(stage, v5.WEIGHTS)
            stage_names = [
                "initialize", "page_mapping", "chunk_definition", "define_policy", "source_chunk_preparation",
                "source_subject_discovery", "benchmark_synthesis", "benchmark_review", "benchmark_freeze",
                "candidate_normalization", "locator_chunk_preparation", "locator_audit", "missing_access_audit",
                "structure_audit", "scoring", "web_report",
            ]
            for index, stage in enumerate(stage_names):
                stages[stage] = {"status": "completed", "updated_at": stamp, "notes": []}
                if stage == "initialize":
                    continue
                path = root / f"{index:02d}-{stage}.json"
                write_json(path, {"stage": stage})
                value = digest(path)
                artifact_id = "ART-" + hashlib.sha256(f"{path.name}\0{value}".encode()).hexdigest()[:12].upper()
                state_record = {"artifact_id": artifact_id, "stage": stage, "artifact_type": stage, "path": path.name, "sha256": value, "visibility": "private", "retention": "required", "frozen": True, "recorded_at": stamp}
                artifacts.append(state_record)
                manifest_artifacts.append({**state_record, "media_type": "application/json"})
            state = {
                "schema_version": "subject-index-evaluation-state-v4",
                "evaluation_id": "eval-v5",
                "artifact_manifest_path": "artifact-manifest.json",
                "created_at": stamp,
                "updated_at": stamp,
                "source": {"title": "Synthetic", "filename": "source.pdf", "sha256": "d" * 64, "document_page_span": [1, 2]},
                "candidate": {"candidate_id": "candidate-synthetic", "sha256": "a" * 64},
                "configuration": {"audit_mode": "full", "index_type": "subject_index", "intended_readership": "researchers", "readership_provenance": {"basis": "inferred", "confidence": "high", "rationale": "Synthetic."}, "output_format": "json", "storage_mode": "local", "publication_profile": "aggregate_only", "policy_profile": "subject-index-standard-policy-v1", "rubric_version": "subject-index-rubric-v4"},
                "stages": stages,
                "artifacts": artifacts,
                "blockers": [],
            }
            hand_edited = copy.deepcopy(state)
            hand_edited["configuration"]["scoring_identity"] = {
                "rubric_version": "subject-index-rubric-v5",
                "dimension_calculation_profile": "subject-index-dimension-calculation-v1",
            }
            hand_edited_errors, _ = state_manager.validate_state(hand_edited, check_files=False)
            self.assertIn("Completed stage has no registered artifact: scoring", hand_edited_errors)
            self.assertIn("Completed stage has no registered artifact: web_report", hand_edited_errors)
            state_path = root / "evaluation-state.json"
            calculation_input = calculation_files(root / "v5-inputs", *base_documents())
            loaded = v5.load_inputs(calculation_input)
            role_registration = {
                "chunk_manifest": ("chunk_definition", "chunk_manifest"),
                "locator_audit": ("locator_audit", "locator_audit"),
                "missing_access_audit": ("missing_access_audit", "missing_access_audit"),
                "structure_audit": ("structure_audit", "structure_audit_v4"),
            }
            for input_artifact, input_path in zip(loaded["input_artifacts"], loaded["input_paths"], strict=True):
                role = input_artifact["role"].split("[", 1)[0]
                stage, artifact_type = role_registration[role]
                relative_path = input_path.relative_to(root).as_posix()
                state_record = {
                    "artifact_id": "ART-" + hashlib.sha256(f"{relative_path}\0{input_artifact['sha256']}".encode()).hexdigest()[:12].upper(),
                    "stage": stage,
                    "artifact_type": artifact_type,
                    "path": relative_path,
                    "sha256": input_artifact["sha256"],
                    "visibility": "private",
                    "retention": "required",
                    "frozen": True,
                    "recorded_at": stamp,
                }
                artifacts.append(state_record)
                manifest_artifacts.append({**state_record, "media_type": "application/json"})
            write_json(state_path, state)
            write_json(root / "artifact-manifest.json", {"schema_version": "subject-index-artifact-manifest-v1", "evaluation_id": "eval-v5", "created_at": stamp, "updated_at": stamp, "artifacts": manifest_artifacts})
            forged_preflight = root / "forged-v5-preflight.json"
            write_json(forged_preflight, {"command": "migration-sufficiency-preflight", "ok": True, "evaluation_id": "eval-v5", "target_rubric_version": "subject-index-rubric-v5", "target_calculation_profile": "subject-index-dimension-calculation-v1", "sufficient": True, "missing_requirements": []})
            rejected = run_cli(
                "state_cli.py",
                "set-score-calculation-profile",
                "--state",
                state_path,
                "--preflight",
                forged_preflight,
                "--calculation-input",
                calculation_input,
                expect_ok=False,
            )
            self.assertEqual("preflight_verification_mismatch", rejected["error"]["code"])

            foreign_input = calculation_files(root / "foreign-v5-inputs", *base_documents())
            foreign_preflight = root / "foreign-v5-preflight.json"
            run_cli("dimension_score_cli.py", "preflight", "--input", foreign_input, "--output", foreign_preflight)
            rejected = run_cli(
                "state_cli.py",
                "set-score-calculation-profile",
                "--state",
                state_path,
                "--preflight",
                foreign_preflight,
                "--calculation-input",
                foreign_input,
                expect_ok=False,
            )
            self.assertEqual("v5_input_artifact_not_registered", rejected["error"]["code"])
            preflight = root / "v5-preflight.json"
            run_cli("dimension_score_cli.py", "preflight", "--input", calculation_input, "--output", preflight)
            before = copy.deepcopy(state["stages"])
            payload = run_cli("state_cli.py", "set-score-calculation-profile", "--state", state_path, "--preflight", preflight, "--calculation-input", calculation_input)
            self.assertEqual(["scoring", "web_report"], payload["invalidated_stages"])
            after = json.loads(state_path.read_text())
            for stage in stage_names[:stage_names.index("scoring")]:
                self.assertEqual(before[stage], after["stages"][stage])
            self.assertEqual("not_started", after["stages"]["scoring"]["status"])
            self.assertEqual("not_started", after["stages"]["web_report"]["status"])
            upstream_artifacts = [item for item in after["artifacts"] if item["stage"] not in {"scoring", "web_report"}]
            self.assertEqual([item for item in artifacts if item["stage"] not in {"scoring", "web_report"}], upstream_artifacts)
            retired = [item for item in after["artifacts"] if item["stage"] in {"scoring", "web_report"}]
            self.assertEqual(2, len(retired))
            self.assertTrue(all(item["active_for_scoring_identity"] is False for item in retired))
            self.assertEqual([], payload["artifacts_deleted"])
            self.assertEqual(sorted(item["path"] for item in retired), payload["artifacts_deactivated"])
            self.assertTrue(run_cli("state_cli.py", "validate", "--state", state_path)["ok"])

            no_fresh_scoring = run_cli("state_cli.py", "set-stage", "--state", state_path, "--stage", "scoring", "--status", "completed", expect_ok=False)
            self.assertEqual("active_profile_artifact_required", no_fresh_scoring["error"]["code"])
            placeholder = root / "placeholder-calculation.json"
            write_json(placeholder, {"schema_version": "subject-index-dimension-calculations-v1", "rubric_version": "subject-index-rubric-v5", "calculation_profile": "subject-index-dimension-calculation-v1"})
            rejected_placeholder = run_cli("state_cli.py", "set-stage", "--state", state_path, "--stage", "scoring", "--status", "in_progress", "--artifact-path", placeholder, expect_ok=False)
            self.assertEqual("invalid_profile_bound_artifact", rejected_placeholder["error"]["code"])

            foreign_locator, foreign_missing, foreign_structure = base_documents()
            for document in (foreign_locator, foreign_missing, foreign_structure):
                document["evaluation_id"] = "eval-foreign"
            foreign_root = root / "foreign-evaluation"
            foreign_config = calculation_files(foreign_root, foreign_locator, foreign_missing, foreign_structure)
            foreign_config_value = json.loads(foreign_config.read_text(encoding="utf-8"))
            foreign_config_value["evaluation_id"] = "eval-foreign"
            write_json(foreign_config, foreign_config_value)
            foreign_calculation = foreign_root / "dimension-calculations.v1.json"
            run_cli("dimension_score_cli.py", "calculate", "--input", foreign_config, "--output", foreign_calculation)
            rejected_foreign = run_cli("state_cli.py", "set-stage", "--state", state_path, "--stage", "scoring", "--status", "in_progress", "--artifact-path", foreign_calculation, expect_ok=False)
            self.assertEqual("scoring_artifact_state_identity_mismatch", rejected_foreign["error"]["code"])

            foreign_calculation_value = json.loads(foreign_calculation.read_text(encoding="utf-8"))
            foreign_item_path = foreign_root / "item-assessments.v2.json"
            write_json(foreign_item_path, minimal_item_assessments(foreign_calculation_value, foreign_root / "item-inventory.json"))
            foreign_result_path = foreign_root / "evaluation-result.v6.json"
            write_json(foreign_result_path, evaluation_projection(foreign_calculation_value, foreign_calculation, foreign_item_path, []))
            rejected_foreign_result = run_cli("state_cli.py", "set-stage", "--state", state_path, "--stage", "scoring", "--status", "completed", "--artifact-path", foreign_result_path, expect_ok=False)
            self.assertEqual("invalid_profile_bound_artifact", rejected_foreign_result["error"]["code"])
            self.assertEqual("active_v5_calculation_required", rejected_foreign_result["error"]["details"]["code"])

            current_calculation = root / "v5-inputs" / "dimension-calculations.v1.json"
            run_cli("dimension_score_cli.py", "calculate", "--input", calculation_input, "--output", current_calculation)
            current_calculation_value = json.loads(current_calculation.read_text(encoding="utf-8"))
            tampered_calculation = copy.deepcopy(current_calculation_value)
            tampered_calculation["total_score"] = 1
            tampered_calculation["calculation_sha256"] = v5.canonical_hash(tampered_calculation, "calculation_sha256")
            tampered_path = root / "v5-inputs" / "tampered-dimension-calculations.v1.json"
            write_json(tampered_path, tampered_calculation)
            rejected_tampered = run_cli("state_cli.py", "set-stage", "--state", state_path, "--stage", "scoring", "--status", "in_progress", "--artifact-path", tampered_path, expect_ok=False)
            self.assertEqual("scoring_artifact_reconstruction_mismatch", rejected_tampered["error"]["code"])
            forged_migration = copy.deepcopy(current_calculation_value)
            forged_migration["migration_context"] = {
                "from_rubric_version": "subject-index-rubric-v4",
                "migration_record_path": "nonexistent-migration.json",
                "historical_result_sha256": "1" * 64,
                "historical_gate_outcomes_sha256": "2" * 64,
                "gate_outcomes_action": "preserve_identically",
            }
            forged_migration["calculation_sha256"] = v5.canonical_hash(forged_migration, "calculation_sha256")
            forged_migration_path = root / "v5-inputs" / "forged-migration-context.json"
            write_json(forged_migration_path, forged_migration)
            rejected_forged_migration = run_cli("state_cli.py", "set-stage", "--state", state_path, "--stage", "scoring", "--status", "in_progress", "--artifact-path", forged_migration_path, expect_ok=False)
            self.assertEqual("invalid_profile_bound_artifact", rejected_forged_migration["error"]["code"])
            self.assertEqual("score_migration_binding_mismatch", rejected_forged_migration["error"]["details"]["code"])
            current_item_path = root / "v5-inputs" / "item-assessments.v2.json"
            write_json(current_item_path, minimal_item_assessments(current_calculation_value, root / "v5-inputs" / "item-inventory.json"))
            current_result_path = root / "v5-inputs" / "evaluation-result.v6.json"
            write_json(current_result_path, evaluation_projection(current_calculation_value, current_calculation, current_item_path, []))
            run_cli("state_cli.py", "set-stage", "--state", state_path, "--stage", "scoring", "--status", "in_progress", "--artifact-path", current_calculation, "--artifact-type", "dimension_calculations")
            completed_scoring = run_cli("state_cli.py", "set-stage", "--state", state_path, "--stage", "scoring", "--status", "completed", "--artifact-path", current_result_path, "--artifact-type", "evaluation_result_v6")
            self.assertIn("scoring", completed_scoring["completed_stages"])
            current_web_path = root / "v5-inputs" / "web-report.v4.json"
            write_json(current_web_path, web_projection(current_calculation_value, current_calculation, current_item_path, []))
            completed_web = run_cli("state_cli.py", "set-stage", "--state", state_path, "--stage", "web_report", "--status", "completed", "--artifact-path", current_web_path, "--artifact-type", "web_report_v4")
            self.assertIn("web_report", completed_web["completed_stages"])
            self.assertTrue(run_cli("state_cli.py", "validate", "--state", state_path)["ok"])


if __name__ == "__main__":
    unittest.main()
