#!/usr/bin/env python3
"""Synthetic contract tests for collision-safe parallel candidate auditing."""

from __future__ import annotations

import argparse
import copy
import contextlib
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from typing import Any
from unittest import mock

from pypdf import PdfReader, PdfWriter


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import parallel_candidate_audit_cli as parallel  # noqa: E402
from candidate_preparation_cli import PreparationError  # noqa: E402


HEX_A = "a" * 64
HEX_B = "b" * 64
HEX_C = "c" * 64


def frozen_fixture(*, locator_complete: bool = True) -> dict[str, Any]:
    chunks = {
        "schema_version": "chunk-manifest-v1",
        "chunk_manifest_sha256": "3" * 64,
        "chunks": [
            {
                "chunk_id": "CHUNK-001",
                "title": "Clockwork orchard",
                "source_units": ["Synthetic chapter one"],
                "owned_document_page_ranges": [[1, 2]],
                "context_document_page_ranges": [],
                "packet_order": 1,
            },
            {
                "chunk_id": "CHUNK-002",
                "title": "Paper observatory",
                "source_units": ["Synthetic chapter two"],
                "owned_document_page_ranges": [[3, 4]],
                "context_document_page_ranges": [],
                "packet_order": 2,
            },
        ],
    }
    candidate = {
        "schema_version": "candidate-index-v2",
        "candidate_id": "synthetic-candidate",
        "candidate_sha256": HEX_B,
        "records": [
            {
                "path_id": "PATH-001",
                "heading_path": ["Clockwork orchard", "Aerial kites"],
                "locator_assignments": [
                    {"locator_id": "LOC-001", "mapping_status": "resolved", "document_page": 1, "source_page_label": "11"},
                    {"locator_id": "LOC-002", "mapping_status": "resolved", "document_page": 1, "source_page_label": "12"},
                    {"locator_id": "LOC-003", "mapping_status": "resolved", "document_page": 2, "source_page_label": "13"},
                    {"locator_id": "LOC-004", "mapping_status": "resolved", "document_page": 2, "source_page_label": "14"},
                ],
            },
            {
                "path_id": "PATH-002",
                "heading_path": ["Paper observatory", "Moon gears"],
                "locator_assignments": [
                    {"locator_id": "LOC-005", "mapping_status": "resolved", "document_page": 3, "source_page_label": "15"},
                ],
            },
        ],
    }
    benchmark = {
        "schema_version": "source-subject-benchmark-v2",
        "version": 1,
        "benchmark_sha256": HEX_C,
        "subjects": [
            {
                "subject_id": "SUBJECT-001",
                "priority": "essential",
                "evidence": [
                    {"evidence_id": "BENCH-EVID-001", "document_page": 1, "locator_class": "principal"},
                    {"evidence_id": "BENCH-EVID-002", "document_page": 3, "locator_class": "supporting"},
                    {"evidence_id": "BENCH-EVID-003", "document_page": 2, "locator_class": "synthesis_or_conclusion"},
                ],
            },
            {
                "subject_id": "SUBJECT-002",
                "priority": "major",
                "evidence": [{"evidence_id": "BENCH-EVID-004", "document_page": 3, "locator_class": "principal"}],
            },
        ],
        "reader_tasks": [
            {"task_id": "TASK-001", "subject_ids": ["SUBJECT-001", "SUBJECT-002"]},
            {"task_id": "TASK-002", "subject_ids": ["SUBJECT-002"]},
        ],
    }
    state = {
        "evaluation_id": "EVAL-SYNTHETIC",
        "stages": {
            "locator_audit": {"status": "completed" if locator_complete else "in_progress"},
            "missing_access_audit": {"status": "not_started"},
        },
    }
    return {
        "state": state,
        "candidate": candidate,
        "inventory": {"paths": [{"path_id": "PATH-001"}, {"path_id": "PATH-002"}]},
        "benchmark": benchmark,
        "benchmark_lock": {"lock_sha256": "e" * 64},
        "policy": {"policy_sha256": "1" * 64},
        "page_map": {
            "page_map_sha256": "2" * 64,
            "pages": [
                {"document_page": page, "source_page_label": f"S-{page}"}
                for page in range(1, 5)
            ],
        },
        "chunk_manifest": chunks,
        "chunks": parallel.chunk_records(chunks),
        "candidate_id": candidate["candidate_id"],
        "candidate_sha256": candidate["candidate_sha256"],
        "identities": {
            "source_sha256": HEX_A,
            "candidate_sha256": HEX_B,
            "benchmark_sha256": HEX_C,
            "benchmark_file_sha256": "d" * 64,
            "benchmark_lock_sha256": "e" * 64,
            "benchmark_lock_file_sha256": "f" * 64,
            "policy_sha256": "1" * 64,
            "page_map_sha256": "2" * 64,
            "chunk_manifest_sha256": "3" * 64,
            "normalized_candidate_file_sha256": "4" * 64,
            "item_inventory_file_sha256": "5" * 64,
        },
        "benchmark_file_sha256": "d" * 64,
        "policy_file_sha256": "7" * 64,
        "page_map_file_sha256": "8" * 64,
        "chunk_manifest_file_sha256": "9" * 64,
        "candidate_file_sha256": "4" * 64,
        "inventory_file_sha256": "5" * 64,
    }


def locator_packet() -> dict[str, Any]:
    assignments = {
        f"LOC-00{index}": {
            "locator_id": f"LOC-00{index}",
            "path_id": "PATH-001",
            "heading_path": ["Clockwork orchard", "Aerial kites"],
            "mapping_status": "resolved",
            "document_page": 1 if index <= 2 else 2,
            "source_page_label": str(10 + index),
        }
        for index in range(1, 5)
    }
    return {
        "document": {"chunk_id": "CHUNK-001"},
        "sha256": "6" * 64,
        "assignments": assignments,
        "paths": {"PATH-001": ["Clockwork orchard", "Aerial kites"]},
    }


def locator_packet_two() -> dict[str, Any]:
    assignment = {
        "locator_id": "LOC-005",
        "path_id": "PATH-002",
        "heading_path": ["Paper observatory", "Moon gears"],
        "mapping_status": "resolved",
        "document_page": 3,
        "source_page_label": "15",
    }
    return {
        "document": {"chunk_id": "CHUNK-002"},
        "sha256": "7" * 64,
        "assignments": {"LOC-005": assignment},
        "paths": {"PATH-002": ["Paper observatory", "Moon gears"]},
    }


def locator_audit() -> dict[str, Any]:
    statuses = ("supported", "partially_supported", "unsupported", "uninspectable")
    packet = locator_packet()
    judgments = []
    for index, (locator_id, assignment) in enumerate(packet["assignments"].items()):
        judgments.append(
            {
                "locator_id": locator_id,
                "path_id": assignment["path_id"],
                "complete_heading_path": assignment["heading_path"],
                "document_page": assignment["document_page"],
                "source_page_label": assignment["source_page_label"],
                "source_scope_status": "indexable" if index < 3 else "unavailable",
                "treatment_class": "substantive" if index < 3 else "unavailable",
                "judgment": statuses[index],
                "confidence": "high" if index < 2 else "low",
                "severity": ("none", "minor", "major", "critical")[index],
                "evidence_summary": "Synthetic paraphrase without source wording.",
                "evidence_ids": [f"EVIDENCE-{index + 1}"],
                "error_codes": [] if index == 0 else ["SCP"],
            }
        )
    return {
        "schema_version": "locator-audit-v1",
        "evaluation_id": "EVAL-SYNTHETIC",
        "candidate_sha256": HEX_B,
        "chunk_id": "CHUNK-001",
        "provenance": {
            "source_sha256": HEX_A,
            "benchmark_sha256": HEX_C,
            "benchmark_lock_sha256": "e" * 64,
            "policy_sha256": "1" * 64,
            "page_map_sha256": "2" * 64,
            "chunk_manifest_sha256": "3" * 64,
            "normalized_candidate_file_sha256": "4" * 64,
            "item_inventory_file_sha256": "5" * 64,
            "locator_packet_file_sha256": "6" * 64,
        },
        "expected_locator_ids": list(packet["assignments"]),
        "judgments": judgments,
        "completion": {"expected": 4, "judged": 4, "unique": True, "complete": True},
    }


def locator_audit_two() -> dict[str, Any]:
    return {
        "schema_version": "locator-audit-v1",
        "evaluation_id": "EVAL-SYNTHETIC",
        "candidate_sha256": HEX_B,
        "chunk_id": "CHUNK-002",
        "provenance": {
            "source_sha256": HEX_A,
            "benchmark_sha256": HEX_C,
            "benchmark_lock_sha256": "e" * 64,
            "policy_sha256": "1" * 64,
            "page_map_sha256": "2" * 64,
            "chunk_manifest_sha256": "3" * 64,
            "normalized_candidate_file_sha256": "4" * 64,
            "item_inventory_file_sha256": "5" * 64,
            "locator_packet_file_sha256": "7" * 64,
        },
        "expected_locator_ids": ["LOC-005"],
        "judgments": [
            {
                "locator_id": "LOC-005",
                "path_id": "PATH-002",
                "complete_heading_path": ["Paper observatory", "Moon gears"],
                "document_page": 3,
                "source_page_label": "15",
                "source_scope_status": "indexable",
                "treatment_class": "substantive",
                "judgment": "supported",
                "confidence": "high",
                "severity": "none",
                "evidence_summary": "Synthetic paraphrase without source wording.",
                "evidence_ids": ["EVIDENCE-5"],
                "error_codes": [],
            }
        ],
        "completion": {"expected": 1, "judged": 1, "unique": True, "complete": True},
    }


def missing_audit(frozen: dict[str, Any], chunk_id: str) -> dict[str, Any]:
    workset = parallel.build_missing_worksets(frozen)[chunk_id]
    subject_index = {item["subject_id"]: item for item in frozen["benchmark"]["subjects"]}
    task_index = {item["task_id"]: item for item in frozen["benchmark"]["reader_tasks"]}
    treatment_judgments = []
    treatments_by_subject: dict[str, list[dict[str, Any]]] = {}
    for index, item in enumerate(workset["treatments"]):
        status = "missed" if item["locator_class"] == "supporting" else "found"
        judgment = {
            "treatment_id": item["treatment_id"],
            "subject_id": item["subject_id"],
            "document_page": item["document_page"],
            "locator_class": item["locator_class"],
            "status": status,
            "evidence_ids": [*item["evidence_ids"], f"MA-TREAT-{index + 1}"],
        }
        treatment_judgments.append(judgment)
        treatments_by_subject.setdefault(item["subject_id"], []).append(judgment)
    subject_judgments = []
    for subject_id in workset["subject_ids"]:
        pages = sorted({item["document_page"] for item in subject_index[subject_id]["evidence"]})
        treatments = treatments_by_subject[subject_id]
        found = sorted({item["document_page"] for item in treatments if item["status"] == "found"})
        missed = sorted({item["document_page"] for item in treatments if item["status"] != "found"})
        direct = subject_id == "SUBJECT-001"
        cross = not direct
        treatment_recall: dict[str, dict[str, list[int]]] = {}
        missed_treatments = []
        for locator_class in ("principal", "supporting", "synthesis_or_conclusion"):
            class_items = [item for item in treatments if item["locator_class"] == locator_class]
            class_found = sorted(item["document_page"] for item in class_items if item["status"] == "found")
            class_missed = sorted(item["document_page"] for item in class_items if item["status"] != "found")
            treatment_recall[locator_class] = {
                "expected_document_pages": sorted(item["document_page"] for item in class_items),
                "found_document_pages": class_found,
                "missed_document_pages": class_missed,
                "uninspectable_document_pages": [],
            }
            missed_treatments.extend(
                {
                    "document_page": page,
                    "locator_class": locator_class,
                    "reason_code": "synthetic_route_gap",
                    "evidence_ids": [f"MA-MISSED-{subject_id}-{page}"],
                }
                for page in class_missed
            )
        missing_routes = []
        if not direct:
            missing_routes.append(
                {
                    "route_type": "direct",
                    "reason_code": "synthetic_direct_route_absent",
                    "evidence_ids": [f"MA-ROUTE-DIRECT-{subject_id}"],
                }
            )
        if not cross:
            missing_routes.append(
                {
                    "route_type": "cross_reference",
                    "reason_code": "synthetic_cross_route_absent",
                    "evidence_ids": [f"MA-ROUTE-XREF-{subject_id}"],
                }
            )
        subject_judgments.append(
            {
                "subject_id": subject_id,
                "priority": subject_index[subject_id]["priority"],
                "coverage": "complete",
                "direct_access": direct,
                "cross_reference_access": cross,
                "realistic_first_lookup_success": "yes" if not missed else "partly",
                "stance_preserved": "yes" if not missed else "partly",
                "severity": "none" if not missed else "minor",
                "confidence": "high",
                "evidence_ids": [f"MA-{subject_id}"],
                "matched_path_ids": ["PATH-001"] if direct else ["PATH-002"],
                "expected_document_pages": pages,
                "found_document_pages": found,
                "missed_document_pages": missed,
                "locator_recall": {
                    "expected": len(pages),
                    "found": len(found),
                    "missed": len(missed),
                    "rate": len(found) / len(pages),
                },
                "treatment_recall": treatment_recall,
                "missing_routes": missing_routes,
                "missed_treatments": missed_treatments,
                "uncertainty": {"status": "none"},
                "error_codes": [] if not missed else ["COV"],
            }
        )
    task_results = [
        {
            "task_id": task_id,
            "subject_ids": task_index[task_id]["subject_ids"],
            "result": "succeeds",
            "access_mode": "direct" if chunk_id == "CHUNK-001" else "cross_reference",
            "matched_path_ids": ["PATH-001"] if chunk_id == "CHUNK-001" else ["PATH-002"],
            "severity": "none",
            "confidence": "high",
            "evidence_ids": [f"MA-{task_id}"],
        }
        for task_id in workset["reader_task_ids"]
    ]
    dependency_locator = "LOC-001" if chunk_id == "CHUNK-001" else "LOC-005"
    dependency_subject = workset["subject_ids"][0]
    return {
        "schema_version": "missing-access-audit-v1",
        "evaluation_id": "EVAL-SYNTHETIC",
        "candidate_sha256": HEX_B,
        "benchmark_sha256": HEX_C,
        "chunk_id": chunk_id,
        "missing_access_ownership_sha256": workset["workset_sha256"],
        "provenance": {
            "source_sha256": frozen["identities"]["source_sha256"],
            "benchmark_file_sha256": frozen["benchmark_file_sha256"],
            "benchmark_lock_sha256": frozen["benchmark_lock"]["lock_sha256"],
            "policy_sha256": frozen["policy"]["policy_sha256"],
            "page_map_sha256": frozen["page_map"]["page_map_sha256"],
            "chunk_manifest_sha256": frozen["chunk_manifest"]["chunk_manifest_sha256"],
            "normalized_candidate_file_sha256": frozen["candidate_file_sha256"],
            "item_inventory_file_sha256": frozen["inventory_file_sha256"],
            "missing_access_ownership_sha256": workset["workset_sha256"],
        },
        "expected_subject_ids": list(workset["subject_ids"]),
        "expected_reader_task_ids": list(workset["reader_task_ids"]),
        "expected_treatment_ids": list(workset["treatment_ids"]),
        "subject_judgments": subject_judgments,
        "reader_task_results": task_results,
        "treatment_judgments": treatment_judgments,
        "dependency_defects": [
            {
                "defect_id": f"DEFECT-{chunk_id}",
                "dependency_type": "locator_audit",
                "disposition": "reported_without_reinterpretation",
                "locator_id": dependency_locator,
                "coverage_subject_ids": [dependency_subject],
                "observed_conflict": "Synthetic locator dependency requires coordinator review.",
                "confidence": "high",
                "required_adjudication": "Review the frozen locator judgment without reinterpretation.",
                "evidence_ids": [f"MA-DEFECT-{chunk_id}"],
            }
        ],
        "completion": {
            "expected": len(workset["subject_ids"]),
            "judged": len(workset["subject_ids"]),
            "unique": True,
            "complete": True,
        },
        "reader_task_completion": {
            "expected": len(workset["reader_task_ids"]),
            "judged": len(workset["reader_task_ids"]),
            "unique": True,
            "complete": True,
        },
        "treatment_completion": {
            "expected": len(workset["treatment_ids"]),
            "judged": len(workset["treatment_ids"]),
            "unique": True,
            "complete": True,
        },
    }


class ErrorAssertionsMixin:
    def assert_error(self, code: str, function: Any, *args: Any, **kwargs: Any) -> PreparationError:
        with self.assertRaises(PreparationError) as caught:
            function(*args, **kwargs)
        self.assertEqual(code, caught.exception.code)
        return caught.exception


class LocatorWorkerContractTests(ErrorAssertionsMixin, unittest.TestCase):
    def setUp(self) -> None:
        self.frozen = frozen_fixture()
        self.packet = locator_packet()
        self.audit = locator_audit()

    def test_exact_ownership_complete_paths_all_statuses_and_denominators(self) -> None:
        summary = parallel.validate_locator_audit(
            self.audit, self.frozen, self.packet, "CHUNK-001"
        )
        self.assertEqual(
            {
                "partially_supported": 1,
                "supported": 1,
                "uninspectable": 1,
                "unsupported": 1,
            },
            summary["judgment_counts"],
        )
        self.assertEqual(4, summary["completion"]["expected"])
        self.assertEqual(["PATH-001"], summary["path_ids"])

    def test_public_canonical_locator_contract_is_exact_and_item_linked(self) -> None:
        result = parallel.validate_public_canonical_audit(
            self.audit, "locator", "CHUNK-001"
        )
        self.assertEqual("locator", result["audit_kind"])
        self.assertEqual("LOC-001", self.audit["judgments"][0]["locator_id"])
        self.assertEqual("PATH-001", self.audit["judgments"][0]["path_id"])
        unexpected = copy.deepcopy(self.audit)
        unexpected["judgments"][0]["raw_text"] = "not publishable"
        self.assert_error(
            "public_audit_shape",
            parallel.validate_public_canonical_audit,
            unexpected,
            "locator",
            "CHUNK-001",
        )

    def test_publication_profile_paths_are_deterministic(self) -> None:
        self.assertEqual(
            "validation/locator-audit-worker.CHUNK-001.json",
            parallel.public_path_for("locator", "CHUNK-001", "aggregate_only"),
        )
        canonical = "candidate/locator-audits/locator-audit.CHUNK-001.v1.json"
        self.assertEqual(
            canonical,
            parallel.public_path_for(
                "locator", "CHUNK-001", "public_evaluation_artifacts"
            ),
        )
        self.assertEqual(
            "public_evaluation_artifacts",
            parallel.publication_profile_from_path("locator", "CHUNK-001", canonical),
        )

    def test_public_canonical_writer_preserves_source_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "audit.json"
            compact = json.dumps(self.audit, separators=(",", ":")).encode("utf-8")
            parallel.write_public_artifact(
                output,
                self.audit,
                compact,
                "public_evaluation_artifacts",
            )
            self.assertEqual(compact, output.read_bytes())

    def test_foreign_assignment_is_rejected(self) -> None:
        audit = copy.deepcopy(self.audit)
        audit["judgments"][0]["locator_id"] = "LOC-005"
        self.assert_error(
            "foreign_chunk_assignment",
            parallel.validate_locator_audit,
            audit,
            self.frozen,
            self.packet,
            "CHUNK-001",
        )

    def test_missing_and_duplicate_assignments_are_rejected(self) -> None:
        missing = copy.deepcopy(self.audit)
        missing["judgments"].pop()
        self.assert_error(
            "missing_locator_assignment",
            parallel.validate_locator_audit,
            missing,
            self.frozen,
            self.packet,
            "CHUNK-001",
        )
        duplicate = copy.deepcopy(self.audit)
        duplicate["judgments"][-1] = copy.deepcopy(duplicate["judgments"][0])
        self.assert_error(
            "duplicate_locator_assignment",
            parallel.validate_locator_audit,
            duplicate,
            self.frozen,
            self.packet,
            "CHUNK-001",
        )

    def test_complete_path_and_candidate_identity_are_bound(self) -> None:
        path_changed = copy.deepcopy(self.audit)
        path_changed["judgments"][0]["complete_heading_path"] = ["Aerial kites"]
        self.assert_error(
            "complete_path_mismatch",
            parallel.validate_locator_audit,
            path_changed,
            self.frozen,
            self.packet,
            "CHUNK-001",
        )
        candidate_changed = copy.deepcopy(self.audit)
        candidate_changed["candidate_sha256"] = HEX_A
        self.assert_error(
            "audit_identity_mismatch",
            parallel.validate_locator_audit,
            candidate_changed,
            self.frozen,
            self.packet,
            "CHUNK-001",
        )

    def test_unresolved_packet_assignment_is_rejected_before_audit(self) -> None:
        document = {
            "schema_version": "candidate-locator-chunk-v1",
            "paths": [
                {
                    "path_id": "PATH-001",
                    "heading_path": ["Synthetic heading"],
                    "locator_assignments": [
                        {
                            "locator_id": "LOC-X",
                            "mapping_status": "unresolved",
                            "document_page": None,
                            "source_page_label": "unknown",
                        }
                    ],
                }
            ],
            "summary": {"path_count": 1, "locator_assignment_count": 1},
        }
        self.assert_error("unresolved_locator_assignment", parallel.packet_assignment_index, document)


class MissingAccessWorkerContractTests(ErrorAssertionsMixin, unittest.TestCase):
    def setUp(self) -> None:
        self.frozen = frozen_fixture()

    def test_deterministic_subject_task_and_treatment_ownership(self) -> None:
        worksets = parallel.build_missing_worksets(self.frozen)
        self.assertEqual(["SUBJECT-001"], worksets["CHUNK-001"]["subject_ids"])
        self.assertEqual(["SUBJECT-002"], worksets["CHUNK-002"]["subject_ids"])
        self.assertEqual(["TASK-001"], worksets["CHUNK-001"]["reader_task_ids"])
        self.assertEqual(["TASK-002"], worksets["CHUNK-002"]["reader_task_ids"])
        # All treatments follow the owning scored subject, including supporting
        # passages that physically lie in another chunk.
        self.assertEqual(3, len(worksets["CHUNK-001"]["treatment_ids"]))
        self.assertEqual(1, len(worksets["CHUNK-002"]["treatment_ids"]))

    def test_repeated_subject_page_class_evidence_coalesces_deterministically(self) -> None:
        frozen = copy.deepcopy(self.frozen)
        evidence = frozen["benchmark"]["subjects"][0]["evidence"]
        evidence.append({
            "evidence_id": "BENCH-EVID-005",
            "source_evidence_id": "SOURCE-EVID-005",
            "document_page": 1,
            "locator_class": "principal",
        })
        first = parallel.build_missing_worksets(frozen)["CHUNK-001"]
        principal = next(
            item for item in first["treatments"]
            if item["subject_id"] == "SUBJECT-001"
            and item["document_page"] == 1
            and item["locator_class"] == "principal"
        )
        self.assertEqual(3, len(first["treatment_ids"]))
        self.assertEqual(["BENCH-EVID-001", "BENCH-EVID-005"], principal["evidence_ids"])
        self.assertEqual(2, principal["evidence_count"])
        evidence.reverse()
        second = parallel.build_missing_worksets(frozen)["CHUNK-001"]
        self.assertEqual(first["workset_sha256"], second["workset_sha256"])

    def test_treatment_judgment_retains_all_coalesced_evidence_ids(self) -> None:
        frozen = copy.deepcopy(self.frozen)
        frozen["benchmark"]["subjects"][0]["evidence"].append({
            "evidence_id": "BENCH-EVID-005",
            "document_page": 1,
            "locator_class": "principal",
        })
        workset = parallel.build_missing_worksets(frozen)["CHUNK-001"]
        audit = missing_audit(frozen, "CHUNK-001")
        judgment = next(
            item for item in audit["treatment_judgments"]
            if item["document_page"] == 1 and item["locator_class"] == "principal"
        )
        judgment["evidence_ids"].remove("BENCH-EVID-005")
        self.assert_error(
            "treatment_evidence_incomplete",
            parallel.validate_missing_access_audit,
            audit,
            frozen,
            workset,
            "CHUNK-001",
        )

    def test_missing_worker_cli_omits_source_inputs_but_locator_requires_them(self) -> None:
        parser = parallel.build_parser()
        choices = parser._subparsers._group_actions[0].choices
        missing_options = {
            option
            for action in choices["build-missing-access-worker"]._actions
            for option in action.option_strings
        }
        locator_options = {
            option
            for action in choices["build-locator-worker"]._actions
            for option in action.option_strings
        }
        self.assertFalse({"--source-file", "--source-chunk", "--source-sidecar"} & missing_options)
        self.assertTrue({"--source-file", "--source-chunk", "--source-sidecar"}.issubset(locator_options))

    def test_direct_cross_reference_coverage_recall_and_dependency_defect(self) -> None:
        audit = missing_audit(self.frozen, "CHUNK-001")
        summary = parallel.validate_missing_access_audit(
            audit,
            self.frozen,
            parallel.build_missing_worksets(self.frozen)["CHUNK-001"],
            "CHUNK-001",
        )
        self.assertEqual(1, summary["access_route_counts"]["direct_only"])
        self.assertEqual(1, summary["concept_coverage_counts"]["complete"])
        self.assertGreater(summary["treatment_recall"]["missed"], 0)
        self.assertEqual(1, summary["dependency_defect_count"])

    def test_public_canonical_missing_access_contract_is_strict(self) -> None:
        audit = missing_audit(self.frozen, "CHUNK-001")
        audit["provenance"]["locator_audit_set_sha256"] = "b" * 64
        result = parallel.validate_public_canonical_audit(
            audit, "missing_access", "CHUNK-001"
        )
        self.assertEqual("missing_access", result["audit_kind"])
        unexpected = copy.deepcopy(audit)
        unexpected["subject_judgments"][0]["source_quote"] = "not allowed"
        self.assert_error(
            "public_audit_shape",
            parallel.validate_public_canonical_audit,
            unexpected,
            "missing_access",
            "CHUNK-001",
        )

    def test_duplicate_missing_and_foreign_subjects_are_rejected(self) -> None:
        workset = parallel.build_missing_worksets(self.frozen)["CHUNK-001"]
        duplicate = missing_audit(self.frozen, "CHUNK-001")
        duplicate["subject_judgments"].append(copy.deepcopy(duplicate["subject_judgments"][0]))
        self.assert_error(
            "duplicate_subject_judgment",
            parallel.validate_missing_access_audit,
            duplicate,
            self.frozen,
            workset,
            "CHUNK-001",
        )
        missing = missing_audit(self.frozen, "CHUNK-001")
        missing["subject_judgments"] = []
        self.assert_error(
            "missing_subject_judgment",
            parallel.validate_missing_access_audit,
            missing,
            self.frozen,
            workset,
            "CHUNK-001",
        )
        foreign = missing_audit(self.frozen, "CHUNK-001")
        foreign["subject_judgments"][0]["subject_id"] = "SUBJECT-002"
        self.assert_error(
            "foreign_chunk_subject",
            parallel.validate_missing_access_audit,
            foreign,
            self.frozen,
            workset,
            "CHUNK-001",
        )

    def test_duplicate_or_missing_reader_tasks_are_rejected(self) -> None:
        workset = parallel.build_missing_worksets(self.frozen)["CHUNK-001"]
        duplicate = missing_audit(self.frozen, "CHUNK-001")
        duplicate["reader_task_results"].append(copy.deepcopy(duplicate["reader_task_results"][0]))
        self.assert_error(
            "duplicate_reader_task_judgment",
            parallel.validate_missing_access_audit,
            duplicate,
            self.frozen,
            workset,
            "CHUNK-001",
        )
        missing = missing_audit(self.frozen, "CHUNK-001")
        missing["reader_task_results"] = []
        self.assert_error(
            "missing_reader_task_judgment",
            parallel.validate_missing_access_audit,
            missing,
            self.frozen,
            workset,
            "CHUNK-001",
        )

    def test_duplicate_missing_and_foreign_treatments_are_rejected(self) -> None:
        workset = parallel.build_missing_worksets(self.frozen)["CHUNK-001"]
        duplicate = missing_audit(self.frozen, "CHUNK-001")
        duplicate["treatment_judgments"].append(copy.deepcopy(duplicate["treatment_judgments"][0]))
        self.assert_error(
            "duplicate_treatment_judgment",
            parallel.validate_missing_access_audit,
            duplicate,
            self.frozen,
            workset,
            "CHUNK-001",
        )
        missing = missing_audit(self.frozen, "CHUNK-001")
        missing["treatment_judgments"].pop()
        self.assert_error(
            "missing_treatment_judgment",
            parallel.validate_missing_access_audit,
            missing,
            self.frozen,
            workset,
            "CHUNK-001",
        )
        foreign = missing_audit(self.frozen, "CHUNK-001")
        foreign["treatment_judgments"][0]["treatment_id"] = "TREAT-FOREIGN"
        self.assert_error(
            "foreign_chunk_treatment",
            parallel.validate_missing_access_audit,
            foreign,
            self.frozen,
            workset,
            "CHUNK-001",
        )

    def test_benchmark_identity_is_bound(self) -> None:
        audit = missing_audit(self.frozen, "CHUNK-001")
        audit["benchmark_sha256"] = HEX_A
        self.assert_error(
            "audit_identity_mismatch",
            parallel.validate_missing_access_audit,
            audit,
            self.frozen,
            parallel.build_missing_worksets(self.frozen)["CHUNK-001"],
            "CHUNK-001",
        )

    def frozen_input_documents(
        self, *, locator_status: str = "completed"
    ) -> tuple[dict[str, Any], list[tuple[dict[str, Any], bytes, str]]]:
        page_map = {"schema_version": "page-map-v1", "page_map_sha256": "2" * 64}
        chunks = copy.deepcopy(self.frozen["chunk_manifest"])
        chunks["page_map_sha256"] = "2" * 64
        policy = {
            "schema_version": "subject-index-evaluation-policy-v2",
            "policy_sha256": "1" * 64,
            "source_scope": {
                "source_sha256": HEX_A,
                "page_map_sha256": "2" * 64,
                "chunk_manifest_sha256": "3" * 64,
            },
        }
        benchmark = {
            **copy.deepcopy(self.frozen["benchmark"]),
            "source_sha256": HEX_A,
            "page_map_sha256": "2" * 64,
            "chunk_manifest_sha256": "3" * 64,
            "policy_sha256": "1" * 64,
            "candidate_blindness": "preserved",
        }
        lock = {
            "schema_version": "candidate-benchmark-lock-v1",
            "lock_sha256": "e" * 64,
            "status": "locked",
            "candidate_id": "synthetic-candidate",
            "candidate_sha256": HEX_B,
            "compatibility": {
                "source_sha256": HEX_A,
                "page_map_sha256": "2" * 64,
                "chunk_manifest_sha256": "3" * 64,
                "policy_sha256": "1" * 64,
            },
            "benchmark_repository": {"benchmark_sha256": HEX_C},
        }
        candidate = {
            **copy.deepcopy(self.frozen["candidate"]),
            "page_map_sha256": "2" * 64,
        }
        inventory = {
            "schema_version": "subject-index-item-inventory-v2",
            "candidate_id": "synthetic-candidate",
            "candidate_sha256": HEX_B,
            "paths": self.frozen["inventory"]["paths"],
        }
        state = {
            "schema_version": "subject-index-evaluation-state-v4",
            "evaluation_id": "EVAL-SYNTHETIC",
            "source": {"sha256": HEX_A},
            "candidate": {
                "candidate_id": "synthetic-candidate",
                "sha256": HEX_B,
                "benchmark_lock_sha256": "e" * 64,
                "normalized_path": "candidate.json",
                "item_inventory_path": "inventory.json",
                "benchmark_lock_path": "lock.json",
            },
            "stages": {
                "candidate_normalization": {"status": "completed"},
                "locator_chunk_preparation": {"status": "completed"},
                "locator_audit": {"status": locator_status},
                "missing_access_audit": {"status": "not_started"},
            },
        }
        run = {
            "state": state,
            "state_path": SKILL_ROOT / "evaluation-state.json",
            "root": SKILL_ROOT,
            "manifest": {"artifacts": []},
        }
        values = [
            (page_map, b"page-map", "8" * 64),
            (chunks, b"chunks", "9" * 64),
            (policy, b"policy", "7" * 64),
            (benchmark, b"benchmark", "d" * 64),
            (lock, b"lock", "f" * 64),
            (candidate, b"candidate", "4" * 64),
            (inventory, b"inventory", "5" * 64),
        ]
        return run, values

    def test_missing_access_worker_gate_requires_full_locator_stage(self) -> None:
        run, values = self.frozen_input_documents(locator_status="in_progress")
        args = argparse.Namespace(
            state="state.json",
            page_map="page-map.json",
            chunk_manifest="chunks.json",
            policy="policy.json",
            benchmark="benchmark.json",
            benchmark_lock=str(SKILL_ROOT / "lock.json"),
            normalized_candidate=str(SKILL_ROOT / "candidate.json"),
            item_inventory=str(SKILL_ROOT / "inventory.json"),
        )
        with mock.patch.object(parallel, "load_canonical_run", return_value=run), mock.patch.object(
            parallel, "validate_json_identity_file", side_effect=values
        ), mock.patch.object(parallel, "manifest_record_for_path", return_value={}):
            self.assert_error(
                "locator_audit_incomplete", parallel.load_frozen_inputs, args, "missing_access"
            )

    def test_missing_access_worker_gate_rejects_mismatched_benchmark_lock(self) -> None:
        run, values = self.frozen_input_documents()
        values[4][0]["compatibility"]["policy_sha256"] = "0" * 64
        args = argparse.Namespace(
            state="state.json",
            page_map="page-map.json",
            chunk_manifest="chunks.json",
            policy="policy.json",
            benchmark="benchmark.json",
            benchmark_lock=str(SKILL_ROOT / "lock.json"),
            normalized_candidate=str(SKILL_ROOT / "candidate.json"),
            item_inventory=str(SKILL_ROOT / "inventory.json"),
        )
        with mock.patch.object(parallel, "load_canonical_run", return_value=run), mock.patch.object(
            parallel, "validate_json_identity_file", side_effect=values
        ), mock.patch.object(parallel, "manifest_record_for_path", return_value={}):
            self.assert_error(
                "benchmark_lock_identity_mismatch",
                parallel.load_frozen_inputs,
                args,
                "missing_access",
            )

    def test_canonical_locator_dependency_set_must_be_complete_and_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frozen = frozen_fixture()
            frozen["root"] = root
            frozen["manifest"] = {"artifacts": []}
            one = root / "locator-one.json"
            two = root / "locator-two.json"
            one.write_bytes(parallel.json_bytes(locator_audit()))
            two.write_bytes(parallel.json_bytes(locator_audit_two()))
            with mock.patch.object(parallel, "manifest_record_for_path", return_value={}):
                result = parallel.load_locator_audit_set(
                    [str(one), str(two)], frozen
                )
                self.assertEqual(5, len(result["locator_ids"]))
                self.assert_error(
                    "locator_audit_set_incomplete",
                    parallel.load_locator_audit_set,
                    [str(one)],
                    frozen,
                )
                incompatible = locator_audit_two()
                incompatible["candidate_sha256"] = HEX_A
                two.write_bytes(parallel.json_bytes(incompatible))
                self.assert_error(
                    "locator_audit_set_identity",
                    parallel.load_locator_audit_set,
                    [str(one), str(two)],
                    frozen,
                )

    def test_canonical_locator_dependency_set_rejects_cross_chunk_id_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frozen = frozen_fixture()
            frozen["root"] = root
            frozen["manifest"] = {"artifacts": []}
            one = root / "locator-one.json"
            two = root / "locator-two.json"
            one.write_bytes(parallel.json_bytes(locator_audit()))
            duplicate = locator_audit_two()
            duplicate["expected_locator_ids"] = ["LOC-001"]
            duplicate["judgments"][0]["locator_id"] = "LOC-001"
            two.write_bytes(parallel.json_bytes(duplicate))
            with mock.patch.object(parallel, "manifest_record_for_path", return_value={}):
                self.assert_error(
                    "locator_denominator_mismatch",
                    parallel.load_locator_audit_set,
                    [str(one), str(two)],
                    frozen,
                )


class PublicProjectionAndRepositoryTests(ErrorAssertionsMixin, unittest.TestCase):
    def setUp(self) -> None:
        self.frozen = frozen_fixture()
        self.reconnect = {
            "source_chunk_file_sha256": "a" * 64,
            "source_sidecar_file_sha256": "b" * 64,
        }

    def test_locator_projection_is_aggregate_only_and_hash_bound(self) -> None:
        packet = locator_packet()
        audit = locator_audit()
        result = parallel.validate_locator_audit(
            audit, self.frozen, packet, "CHUNK-001"
        )
        report = parallel.build_locator_report(
            self.frozen,
            "CHUNK-001",
            "1" * 40,
            self.reconnect,
            packet,
            result,
            "c" * 64,
        )
        self.assertEqual("c" * 64, report["private_artifact_sha256"])
        self.assertEqual(4, report["denominators"]["packet_assignments"])
        encoded = json.dumps(report, sort_keys=True)
        self.assertNotIn("Aerial kites", encoded)
        self.assertNotIn("LOC-001", encoded)
        self.assertEqual(
            "passed", report["public_safety"]["result"]
        )
        validated = parallel.validate_public_report(report, "locator", "CHUNK-001")
        self.assertEqual(report["report_sha256"], validated["report_sha256"])

    def test_missing_projection_separates_coverage_and_locator_recall(self) -> None:
        workset = parallel.build_missing_worksets(self.frozen)["CHUNK-001"]
        audit = missing_audit(self.frozen, "CHUNK-001")
        result = parallel.validate_missing_access_audit(
            audit, self.frozen, workset, "CHUNK-001"
        )
        report = parallel.build_missing_report(
            self.frozen,
            "CHUNK-001",
            "1" * 40,
            workset,
            {"sha256": "d" * 64},
            result,
            audit,
            "e" * 64,
        )
        self.assertEqual(1, report["concept_coverage_counts"]["complete"])
        self.assertEqual(3, report["locator_recall"]["expected"])
        self.assertIn("principal", report["treatment_recall"])
        self.assertNotIn("SUBJECT-001", json.dumps(report, sort_keys=True))
        parallel.validate_public_report(report, "missing_access", "CHUNK-001")

    def test_forbidden_private_content_paths_and_secret_shapes_are_rejected(self) -> None:
        self.assert_error(
            "public_forbidden_key",
            parallel.public_scan,
            {"summary": {"heading_path": ["private"]}},
        )
        self.assert_error(
            "public_absolute_path",
            parallel.public_scan,
            {"note": "/" + "root/private/recovery"},
        )
        self.assert_error(
            "public_secret",
            parallel.public_scan,
            {"note": "gh" + "p_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"},
        )

    def repository_state(self, **overrides: Any) -> dict[str, Any]:
        record = {
            "schema_version": "candidate-audit-repository-state-v1",
            "candidate_project": "example/synthetic-candidate",
            "is_empty": False,
            "default_branch": "main",
            "base_commit": "1" * 40,
            "branches": ["main"],
            "observed_at": parallel.now(),
        }
        record.update(overrides)
        return record

    def validate_repository(self, record: dict[str, Any]) -> dict[str, Any]:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "repository-state.json"
            path.write_text(json.dumps(record), encoding="utf-8")
            return parallel.validate_repository_state(
                path,
                "example/synthetic-candidate",
                "main",
                "locator-audit/chunk-001",
            )

    def test_existing_worker_branch_is_refused(self) -> None:
        record = self.repository_state(
            branches=["main", "locator-audit/chunk-001"]
        )
        self.assert_error("worker_branch_exists", self.validate_repository, record)

    def test_incorrect_base_or_repository_identity_is_refused(self) -> None:
        self.assert_error(
            "invalid_commit",
            self.validate_repository,
            self.repository_state(base_commit="moving-main"),
        )
        self.assert_error(
            "repository_identity_mismatch",
            self.validate_repository,
            self.repository_state(candidate_project="example/other-candidate"),
        )

    def test_historical_repository_observation_has_no_ttl(self) -> None:
        result = self.validate_repository(
            self.repository_state(observed_at="2020-01-01T00:00:00Z")
        )
        self.assertEqual("1" * 40, result["base_commit"])

    def source_reconnection_files(
        self, directory: Path
    ) -> tuple[argparse.Namespace, dict[str, Any]]:
        source = directory / "restricted-source.pdf"
        chunk = directory / "source-chunk.CHUNK-001.pdf"
        sidecar = directory / "source-chunk.CHUNK-001.pages.json"
        source_writer = PdfWriter()
        for page in range(1, 5):
            source_writer.add_blank_page(width=400 + page, height=600 + page)
        with source.open("wb") as handle:
            source_writer.write(handle)
        source_reader = PdfReader(str(source), strict=True)
        chunk_writer = PdfWriter()
        chunk_writer.add_page(source_reader.pages[0])
        chunk_writer.add_page(source_reader.pages[1])
        with chunk.open("wb") as handle:
            chunk_writer.write(handle)
        frozen = frozen_fixture()
        frozen["identities"]["source_sha256"] = parallel.sha256_file(source)
        sidecar.write_text(
            json.dumps(
                {
                    "schema_version": "source-chunk-sidecar-v1",
                    "chunk_id": "CHUNK-001",
                    "page_map_sha256": "2" * 64,
                    "chunk_manifest_sha256": "3" * 64,
                    "pages": [
                        {
                            "chunk_pdf_page": 1,
                            "document_page": 1,
                            "source_page_label": "S-1",
                            "ownership": "owned",
                        },
                        {
                            "chunk_pdf_page": 2,
                            "document_page": 2,
                            "source_page_label": "S-2",
                            "ownership": "owned",
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        return (
            argparse.Namespace(
                source_file=str(source),
                source_chunk=str(chunk),
                source_sidecar=str(sidecar),
            ),
            frozen,
        )

    def test_exact_source_reconnection_is_hash_and_sidecar_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args, frozen = self.source_reconnection_files(Path(directory))
            result = parallel.validate_source_reconnection(args, frozen, "CHUNK-001")
            self.assertEqual("verified", result["status"])
            self.assertEqual([1, 2], result["owned_document_pages"])

    def test_missing_or_mismatched_source_reconnection_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args, frozen = self.source_reconnection_files(Path(directory))
            Path(args.source_file).unlink()
            self.assert_error(
                "source_reconnection_missing",
                parallel.validate_source_reconnection,
                args,
                frozen,
                "CHUNK-001",
            )
        with tempfile.TemporaryDirectory() as directory:
            args, frozen = self.source_reconnection_files(Path(directory))
            Path(args.source_file).write_bytes(b"different synthetic source")
            self.assert_error(
                "source_reconnection_mismatch",
                parallel.validate_source_reconnection,
                args,
                frozen,
                "CHUNK-001",
            )


class RecoveryAndReceiptTests(ErrorAssertionsMixin, unittest.TestCase):
    def build_locator_worker_private(
        self, directory: Path
    ) -> tuple[Path, Path, dict[str, Any], dict[str, Any], bytes, bytes]:
        frozen = frozen_fixture()
        packet = locator_packet()
        audit = locator_audit()
        result = parallel.validate_locator_audit(
            audit, frozen, packet, "CHUNK-001"
        )
        reconnect = {
            "source_chunk_file_sha256": "a" * 64,
            "source_sidecar_file_sha256": "b" * 64,
        }
        audit_payload = parallel.json_bytes(audit)
        report = parallel.build_locator_report(
            frozen,
            "CHUNK-001",
            "1" * 40,
            reconnect,
            packet,
            result,
            parallel.sha256_bytes(audit_payload),
        )
        public_payload = parallel.json_bytes(report)
        root = directory / "workers" / "locator-audit" / "CHUNK-001"
        archive = directory / "locator-audit-worker-recovery.zip"
        recovery = parallel.build_recovery(
            root,
            archive,
            "locator",
            frozen,
            "CHUNK-001",
            report["identities"],
            "locator-audit.CHUNK-001.json",
            audit_payload,
            public_payload,
            {
                "schema_version": "locator-assignment-plan-v1",
                "chunk_id": "CHUNK-001",
                "locator_packet_file_sha256": packet["sha256"],
                "assignment_ids": sorted(packet["assignments"]),
                "assignment_count": len(packet["assignments"]),
            },
        )
        receipt = parallel.make_receipt(
            "locator",
            frozen,
            "CHUNK-001",
            "example/synthetic-candidate",
            "main",
            "1" * 40,
            "locator-audit/chunk-001",
            report["identities"],
            "locator-audit.CHUNK-001.json",
            audit_payload,
            result,
            recovery,
            "workers/locator-audit/CHUNK-001",
            public_payload,
        )
        return root, archive, receipt, recovery, audit_payload, public_payload

    def publication_evidence(
        self,
        receipt: dict[str, Any],
        public_payload: bytes,
        *,
        merged: bool = False,
        **overrides: Any,
    ) -> dict[str, Any]:
        record = {
            "schema_version": (
                "candidate-audit-merge-evidence-v1"
                if merged
                else "candidate-audit-open-pr-evidence-v1"
            ),
            "evidence_source": "github_api",
            "audit_kind": "locator_audit",
            "candidate_project": "example/synthetic-candidate",
            "pull_request": 17,
            "pull_request_url": "https://github.com/example/synthetic-candidate/pull/17",
            "state": "closed" if merged else "open",
            "merged": merged,
            "base_branch": "main",
            "observed_base_head_commit": "1" * 40,
            "head_branch": "locator-audit/chunk-001",
            "head_commit": "2" * 40,
            "worker_base_commit": "1" * 40,
            "merge_base_commit": "1" * 40,
            "commit_count": 1,
            "changed_files": [
                {
                    "path": "validation/locator-audit-worker.CHUNK-001.json",
                    "blob_sha": parallel.git_blob_sha_bytes(public_payload, "0" * 40),
                    "file_sha256": parallel.sha256_bytes(public_payload),
                }
            ],
            "observed_at": parallel.now(),
        }
        if merged:
            record["merge_commit"] = "3" * 40
        record.update(overrides)
        return record

    def materialize_binding(
        self, directory: Path
    ) -> tuple[Path, dict[str, Any], dict[str, Any]]:
        root, archive, receipt, _, _, public_payload = self.build_locator_worker_private(
            directory
        )
        receipt_path = directory / "locator-receipt.json"
        report_path = directory / "locator-public.json"
        evidence_path = directory / "open-pr-evidence.json"
        binding_path = directory / "worker-binding.json"
        receipt_path.write_bytes(parallel.json_bytes(receipt))
        report_path.write_bytes(public_payload)
        evidence = self.publication_evidence(receipt, public_payload)
        evidence_path.write_bytes(parallel.json_bytes(evidence))
        receipt = parallel.finalize_publication_receipt(
            receipt,
            evidence,
            parallel.sha256_file(evidence_path),
        )
        receipt_path.write_bytes(parallel.json_bytes(receipt))
        binding = {
            "schema_version": "candidate-audit-integration-binding-v1",
            "audit_kind": "locator_audit",
            "candidate_project": "example/synthetic-candidate",
            "selection": {
                "type": "pull_request",
                "pull_request": 17,
                "pull_request_url": "https://github.com/example/synthetic-candidate/pull/17",
            },
            "receipt": {
                "path": str(receipt_path),
                "sha256": parallel.sha256_file(receipt_path),
            },
            "recovery": {
                "root": str(root),
                "archive_path": str(archive),
                "archive_sha256": parallel.sha256_file(archive),
            },
            "public_report": {
                "path": str(report_path),
                "sha256": parallel.sha256_file(report_path),
            },
            "open_pr_evidence": {
                "path": str(evidence_path),
                "sha256": parallel.sha256_file(evidence_path),
            },
        }
        binding_path.write_bytes(parallel.json_bytes(binding))
        frozen = frozen_fixture()
        frozen["root"] = directory / "canonical"
        frozen["state"]["candidate"] = {
            "normalized_path": "candidate/synthetic-candidate/candidate-index.v2.json"
        }
        return binding_path, frozen, binding

    def test_private_public_receipt_and_recovery_hashes_are_exactly_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, archive, receipt, recovery, audit_payload, public_payload = (
                self.build_locator_worker_private(Path(directory))
            )
            self.assertEqual(
                parallel.sha256_bytes(audit_payload),
                receipt["private_artifact"]["sha256"],
            )
            self.assertEqual(
                parallel.sha256_bytes(public_payload),
                receipt["public_projection"]["sha256"],
            )
            self.assertEqual(recovery["archive_sha256"], receipt["private_recovery"]["sha256"])

    def test_bind_publication_finalizes_receipt_and_recovery_for_missing_access(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            frozen = frozen_fixture()
            frozen["state"]["configuration"] = {
                "publication_profile": "public_evaluation_artifacts"
            }
            frozen["publication_profile"] = "public_evaluation_artifacts"
            workset = parallel.build_missing_worksets(frozen)["CHUNK-001"]
            audit = missing_audit(frozen, "CHUNK-001")
            audit["provenance"]["locator_audit_set_sha256"] = "d" * 64
            result = parallel.validate_missing_access_audit(
                audit,
                frozen,
                workset,
                "CHUNK-001",
                locator_audit_set_sha256="d" * 64,
            )
            audit_payload = parallel.json_bytes(audit)
            locator_set = {"sha256": "d" * 64}
            report = parallel.build_missing_report(
                frozen,
                "CHUNK-001",
                "1" * 40,
                workset,
                locator_set,
                result,
                audit,
                parallel.sha256_bytes(audit_payload),
            )
            public_payload = audit_payload
            root = directory_path / "workers" / "missing-access-audit" / "CHUNK-001"
            archive = root / "missing-access-worker-recovery.zip"
            recovery = parallel.build_recovery(
                root,
                archive,
                "missing_access",
                frozen,
                "CHUNK-001",
                report["identities"],
                "missing-access-audit.CHUNK-001.json",
                audit_payload,
                public_payload,
                {
                    "schema_version": "missing-access-ownership-plan-v1",
                    "chunk_id": "CHUNK-001",
                    "workset_sha256": workset["workset_sha256"],
                    "subject_ids": workset["subject_ids"],
                    "reader_task_ids": workset["reader_task_ids"],
                    "treatment_ids": workset["treatment_ids"],
                },
            )
            receipt = parallel.make_receipt(
                "missing_access",
                frozen,
                "CHUNK-001",
                "example/synthetic-candidate",
                "main",
                "1" * 40,
                "missing-access-audit/chunk-001",
                report["identities"],
                "missing-access-audit.CHUNK-001.json",
                audit_payload,
                result,
                recovery,
                "workers/missing-access-audit/CHUNK-001",
                public_payload,
            )
            receipt_path = root / "missing-access-worker-receipt.json"
            preliminary_recovery_sha = parallel.sha256_file(archive)
            report_path = directory_path / "missing-access-public.json"
            evidence_path = directory_path / "open-pr-evidence.json"
            binding_path = directory_path / "worker-binding.json"
            receipt_path.write_bytes(parallel.json_bytes(receipt))
            report_path.write_bytes(public_payload)
            evidence = self.publication_evidence(receipt, public_payload)
            evidence.update({
                "audit_kind": "missing_access",
                "head_branch": "missing-access-audit/chunk-001",
            })
            evidence["changed_files"][0]["path"] = "candidate/missing-access-audits/missing-access-audit.CHUNK-001.v1.json"
            evidence_path.write_bytes(parallel.json_bytes(evidence))
            args = argparse.Namespace(
                receipt=str(receipt_path),
                recovery_root=str(root),
                recovery_zip=str(archive),
                public_report=str(report_path),
                publication_evidence=str(evidence_path),
                selection=None,
                output=str(binding_path),
            )
            with contextlib.redirect_stdout(sys.stderr), self.assertRaises(SystemExit) as emitted:
                parallel.command_bind_publication(args)
            self.assertEqual(0, emitted.exception.code)
            finalized = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual("published_unmerged", finalized["status"])
            self.assertEqual("open_unmerged", finalized["publication"]["status"])
            self.assertEqual(17, finalized["publication"]["pull_request"])
            self.assertEqual("2" * 40, finalized["publication"]["head_commit"])
            self.assertEqual(
                parallel.sha256_bytes(public_payload),
                finalized["publication"]["file_sha256"],
            )
            self.assertEqual(
                parallel.sha256_file(archive),
                finalized["private_recovery"]["sha256"],
            )
            self.assertNotEqual(preliminary_recovery_sha, parallel.sha256_file(archive))
            parallel.validate_receipt(finalized, "missing_access")
            final_recovery = parallel.validate_recovery_archive(root, archive, finalized)
            evidence_records = [
                item for item in final_recovery["metadata"]["artifacts"]
                if item["artifact"] == "open_pr_evidence"
            ]
            self.assertEqual(1, len(evidence_records))
            self.assertEqual(
                parallel.sha256_file(evidence_path), evidence_records[0]["sha256"]
            )
            binding = json.loads(binding_path.read_text(encoding="utf-8"))
            self.assertEqual(parallel.sha256_file(receipt_path), binding["receipt"]["sha256"])

    def test_coordinator_rejects_preliminary_receipt_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            root, archive, receipt, _, _, public_payload = self.build_locator_worker_private(
                directory_path
            )
            receipt_path = directory_path / "locator-receipt.json"
            report_path = directory_path / "locator-public.json"
            evidence_path = directory_path / "open-pr-evidence.json"
            binding_path = directory_path / "worker-binding.json"
            receipt_path.write_bytes(parallel.json_bytes(receipt))
            report_path.write_bytes(public_payload)
            evidence = self.publication_evidence(receipt, public_payload)
            evidence_path.write_bytes(parallel.json_bytes(evidence))
            binding = {
                "schema_version": "candidate-audit-integration-binding-v1",
                "audit_kind": "locator_audit",
                "candidate_project": "example/synthetic-candidate",
                "selection": {
                    "type": "pull_request",
                    "pull_request": 17,
                    "pull_request_url": "https://github.com/example/synthetic-candidate/pull/17",
                },
                "receipt": {"path": str(receipt_path), "sha256": parallel.sha256_file(receipt_path)},
                "recovery": {"root": str(root), "archive_path": str(archive), "archive_sha256": parallel.sha256_file(archive)},
                "public_report": {"path": str(report_path), "sha256": parallel.sha256_file(report_path)},
                "open_pr_evidence": {"path": str(evidence_path), "sha256": parallel.sha256_file(evidence_path)},
            }
            binding_path.write_bytes(parallel.json_bytes(binding))
            frozen = frozen_fixture()
            frozen["root"] = directory_path / "canonical"
            selection = parallel.parse_selection(
                "https://github.com/example/synthetic-candidate/pull/17",
                "example/synthetic-candidate",
                "locator",
            )
            self.assert_error(
                "receipt_not_publication_bound",
                parallel.load_worker_binding,
                binding_path,
                selection,
                "example/synthetic-candidate",
                "locator",
                frozen,
                {"packets": {"CHUNK-001": locator_packet()}},
            )

    def test_fresh_coordinator_observation_matches_immutable_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, _, receipt, _, _, public_payload = self.build_locator_worker_private(
                Path(directory)
            )
            worker_evidence = self.publication_evidence(receipt, public_payload)
            finalized = parallel.finalize_publication_receipt(
                receipt, worker_evidence, "a" * 64
            )
            fresh = copy.deepcopy(worker_evidence)
            fresh["observed_base_head_commit"] = "4" * 40
            fresh["observed_at"] = "2030-01-01T00:00:00Z"
            parallel.require_receipt_matches_current_proposal(finalized, fresh)
            fresh["head_commit"] = "5" * 40
            self.assert_error(
                "receipt_publication_mismatch",
                parallel.require_receipt_matches_current_proposal,
                finalized,
                fresh,
            )

    def test_public_evaluation_receipt_binds_exact_audit_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            frozen = frozen_fixture()
            frozen["state"]["configuration"] = {
                "publication_profile": "public_evaluation_artifacts"
            }
            frozen["publication_profile"] = "public_evaluation_artifacts"
            packet = locator_packet()
            audit = locator_audit()
            result = parallel.validate_locator_audit(
                audit, frozen, packet, "CHUNK-001"
            )
            parallel.validate_public_canonical_audit(audit, "locator", "CHUNK-001")
            audit_payload = parallel.json_bytes(audit)
            reconnect = {
                "source_chunk_file_sha256": "a" * 64,
                "source_sidecar_file_sha256": "b" * 64,
            }
            report = parallel.build_locator_report(
                frozen,
                "CHUNK-001",
                "1" * 40,
                reconnect,
                packet,
                result,
                parallel.sha256_bytes(audit_payload),
            )
            root = Path(directory) / "worker"
            archive = Path(directory) / "worker.zip"
            recovery = parallel.build_recovery(
                root,
                archive,
                "locator",
                frozen,
                "CHUNK-001",
                report["identities"],
                "locator-audit.CHUNK-001.json",
                audit_payload,
                audit_payload,
                {
                    "schema_version": "locator-assignment-plan-v1",
                    "chunk_id": "CHUNK-001",
                    "locator_packet_file_sha256": packet["sha256"],
                    "assignment_ids": sorted(packet["assignments"]),
                    "assignment_count": len(packet["assignments"]),
                },
            )
            receipt = parallel.make_receipt(
                "locator",
                frozen,
                "CHUNK-001",
                "example/synthetic-candidate",
                "main",
                "1" * 40,
                "locator-audit/chunk-001",
                report["identities"],
                "locator-audit.CHUNK-001.json",
                audit_payload,
                result,
                recovery,
                "workers/locator-audit/CHUNK-001",
                audit_payload,
            )
            self.assertEqual(
                "candidate/locator-audits/locator-audit.CHUNK-001.v1.json",
                receipt["public_projection"]["path"],
            )
            self.assertEqual(
                receipt["private_artifact"]["sha256"],
                receipt["public_projection"]["sha256"],
            )
            metadata = parallel.validate_recovery_archive(root, archive, receipt)["metadata"]
            self.assertEqual(
                1,
                sum(
                    item["artifact"] == "public_canonical_audit"
                    for item in metadata["artifacts"]
                ),
            )
            validated = parallel.validate_recovery_archive(root, archive, receipt)
            self.assertEqual(recovery["archive_sha256"], validated["archive_sha256"])

    def test_incomplete_recovery_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, archive, receipt, _, _, _ = self.build_locator_worker_private(Path(directory))
            (root / "worker-state.json").unlink()
            self.assert_error(
                "recovery_root_incomplete",
                parallel.validate_recovery_archive,
                root,
                archive,
                receipt,
            )

    def test_nonisolated_recovery_root_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = parent / "workers" / "locator-audit" / "CHUNK-001"
            root.mkdir(parents=True)
            (root / "unrelated.json").write_text("{}", encoding="utf-8")
            self.assert_error(
                "recovery_root_not_isolated",
                parallel.build_recovery,
                root,
                parent / "recovery.zip",
                "locator",
                frozen_fixture(),
                "CHUNK-001",
                {
                    **frozen_fixture()["identities"],
                    "locator_packet_file_sha256": "6" * 64,
                },
                "locator-audit.CHUNK-001.json",
                b"{}",
                b"{}",
                {},
            )

    def test_receipt_rejects_nondeterministic_branch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, _, receipt, _, _, _ = self.build_locator_worker_private(Path(directory))
            receipt["repositories"]["worker_branch"] = "locator-audit/shared"
            receipt["receipt_sha256"] = parallel.canonical_hash(receipt, "receipt_sha256")
            self.assert_error("receipt_branch", parallel.validate_receipt, receipt, "locator")

    def test_publication_denial_preserves_valid_private_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, archive, receipt, _, _, _ = self.build_locator_worker_private(Path(directory))
            receipt["status"] = "publication_blocked"
            receipt["publication"] = {
                "status": "publication_blocked",
                "pull_request": None,
                "head_commit": None,
            }
            receipt["receipt_sha256"] = parallel.canonical_hash(receipt, "receipt_sha256")
            self.assertEqual("locator", parallel.validate_receipt(receipt, "locator"))
            self.assertEqual(
                receipt["private_recovery"]["sha256"],
                parallel.validate_recovery_archive(root, archive, receipt)["archive_sha256"],
            )

    def test_fresh_open_and_merged_github_evidence_bind_same_pr_and_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, _, receipt, _, _, public_payload = self.build_locator_worker_private(
                Path(directory)
            )
            opened = self.publication_evidence(receipt, public_payload)
            result = parallel.validate_publication_evidence(
                opened, receipt, public_payload, merged=False
            )
            self.assertEqual("CHUNK-001", result["chunk_id"])
            merged = self.publication_evidence(receipt, public_payload, merged=True)
            result = parallel.validate_publication_evidence(
                merged,
                receipt,
                public_payload,
                merged=True,
                prior_open=opened,
            )
            self.assertEqual("locator", result["audit_kind"])

    def test_unexpected_or_private_publication_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, _, receipt, _, _, public_payload = self.build_locator_worker_private(
                Path(directory)
            )
            for path in (
                "validation/unrelated.json",
                "workers/locator-audit/CHUNK-001/locator-audit.CHUNK-001.json",
            ):
                evidence = self.publication_evidence(receipt, public_payload)
                evidence["changed_files"][0]["path"] = path
                self.assert_error(
                    "publication_allowlist",
                    parallel.validate_publication_evidence,
                    evidence,
                    receipt,
                    public_payload,
                    False,
                )

    def test_historical_exact_evidence_has_no_ttl_but_caller_shape_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, _, receipt, _, _, public_payload = self.build_locator_worker_private(
                Path(directory)
            )
            historical = self.publication_evidence(
                receipt, public_payload, observed_at="2020-01-01T00:00:00Z"
            )
            result = parallel.validate_publication_evidence(
                historical,
                receipt,
                public_payload,
                False,
            )
            self.assertEqual("locator", result["audit_kind"])
            caller = self.publication_evidence(
                receipt, public_payload, evidence_source="caller_supplied"
            )
            self.assert_error(
                "publication_evidence_source",
                parallel.validate_publication_evidence,
                caller,
                receipt,
                public_payload,
                False,
            )

    def test_advanced_target_head_is_allowed_but_worker_ancestry_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, _, receipt, _, _, public_payload = self.build_locator_worker_private(
                Path(directory)
            )
            advanced = self.publication_evidence(
                receipt, public_payload, observed_base_head_commit="4" * 40
            )
            result = parallel.validate_publication_evidence(
                advanced,
                receipt,
                public_payload,
                False,
            )
            self.assertEqual("locator", result["audit_kind"])
            wrong_worker_base = self.publication_evidence(
                receipt, public_payload, worker_base_commit="4" * 40
            )
            self.assert_error(
                "publication_base_mismatch",
                parallel.validate_publication_evidence,
                wrong_worker_base,
                receipt,
                public_payload,
                False,
            )
            wrong_merge_base = self.publication_evidence(
                receipt, public_payload, merge_base_commit="4" * 40
            )
            self.assert_error(
                "publication_base_mismatch",
                parallel.validate_publication_evidence,
                wrong_merge_base,
                receipt,
                public_payload,
                False,
            )

    def test_explicit_binding_resolves_one_receipt_recovery_and_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            binding_path, frozen, _ = self.materialize_binding(Path(directory))
            selection = parallel.parse_selection(
                "https://github.com/example/synthetic-candidate/pull/17",
                "example/synthetic-candidate",
                "locator",
            )
            worker = parallel.load_worker_binding(
                binding_path,
                selection,
                "example/synthetic-candidate",
                "locator",
                frozen,
                {"packets": {"CHUNK-001": locator_packet()}},
            )
            self.assertEqual("CHUNK-001", worker["chunk_id"])
            self.assertEqual("new", worker["disposition"])

    def test_binding_refuses_missing_recovery_root_and_packet_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            binding_path, frozen, binding = self.materialize_binding(Path(directory))
            selection = parallel.parse_selection(
                "https://github.com/example/synthetic-candidate/pull/17",
                "example/synthetic-candidate",
                "locator",
            )
            binding["recovery"]["root"] = ""
            binding_path.write_bytes(parallel.json_bytes(binding))
            self.assert_error(
                "binding_path",
                parallel.load_worker_binding,
                binding_path,
                selection,
                "example/synthetic-candidate",
                "locator",
                frozen,
                {"packets": {"CHUNK-001": locator_packet()}},
            )
        with tempfile.TemporaryDirectory() as directory:
            binding_path, frozen, _ = self.materialize_binding(Path(directory))
            mismatched = locator_packet()
            mismatched["sha256"] = "0" * 64
            self.assert_error(
                "locator_packet_hash_mismatch",
                parallel.load_worker_binding,
                binding_path,
                selection,
                "example/synthetic-candidate",
                "locator",
                frozen,
                {"packets": {"CHUNK-001": mismatched}},
            )

    def test_identical_canonical_chunk_is_idempotent_but_conflict_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            binding_path, frozen, _ = self.materialize_binding(Path(directory))
            selection = parallel.parse_selection(
                "https://github.com/example/synthetic-candidate/pull/17",
                "example/synthetic-candidate",
                "locator",
            )
            first = parallel.load_worker_binding(
                binding_path,
                selection,
                "example/synthetic-candidate",
                "locator",
                frozen,
                {"packets": {"CHUNK-001": locator_packet()}},
            )
            payloads = {
                "audit": first["audit_payload"],
                "receipt": first["receipt_payload"],
                "open_evidence": first["open_payload"],
                "merge_evidence": b"{}\n",
                "public_report": first["report_payload"],
            }
            for name, payload in payloads.items():
                parallel.replace_bytes_atomic(first["canonical"][name], payload)
            second = parallel.load_worker_binding(
                binding_path,
                selection,
                "example/synthetic-candidate",
                "locator",
                frozen,
                {"packets": {"CHUNK-001": locator_packet()}},
            )
            self.assertEqual("idempotent", second["disposition"])
            parallel.replace_bytes_atomic(first["canonical"]["audit"], b"{}\n")
            self.assert_error(
                "conflicting_reintegration",
                parallel.load_worker_binding,
                binding_path,
                selection,
                "example/synthetic-candidate",
                "locator",
                frozen,
                {"packets": {"CHUNK-001": locator_packet()}},
            )


class BatchPreflightTests(ErrorAssertionsMixin, unittest.TestCase):
    project = "example/synthetic-candidate"

    def args(
        self,
        selections: list[str],
        bindings: list[str],
    ) -> argparse.Namespace:
        return argparse.Namespace(
            audit_kind="locator",
            project=self.project,
            selection=selections,
            worker_binding=bindings,
            locator_packet=["packet-1.json", "packet-2.json"],
            locator_audit=None,
        )

    @staticmethod
    def worker(
        chunk_id: str,
        owned_ids: list[str],
        *,
        base_commit: str = "1" * 40,
    ) -> dict[str, Any]:
        return {
            "chunk_id": chunk_id,
            "owned_ids": owned_ids,
            "disposition": "new",
            "receipt": {
                "repositories": {
                    "candidate_base_branch": "main",
                    "immutable_worker_base_commit": base_commit,
                }
            },
        }

    def run_preflight(
        self,
        args: argparse.Namespace,
        workers: list[dict[str, Any]],
    ) -> dict[str, Any]:
        with mock.patch.object(
            parallel, "load_frozen_inputs", return_value=frozen_fixture()
        ), mock.patch.object(
            parallel,
            "load_packet_set",
            return_value={"packets": {}, "sha256": "a" * 64, "assignment_ids": []},
        ), mock.patch.object(
            parallel, "load_worker_binding", side_effect=workers
        ):
            return parallel.preflight_batch(args)

    def test_explicit_single_worker_partial_batch_is_valid(self) -> None:
        args = self.args(
            ["https://github.com/example/synthetic-candidate/pull/17"],
            ["binding-17.json"],
        )
        result = self.run_preflight(args, [self.worker("CHUNK-001", ["LOC-001"])])
        self.assertEqual(["CHUNK-001"], result["chunk_ids"])
        self.assertEqual("1" * 40, result["base_commit"])

    def test_three_worker_wave_uses_complete_seventeen_packet_set(self) -> None:
        chunk_ids = [f"CHUNK-{index:03d}" for index in range(1, 18)]
        frozen = frozen_fixture()
        frozen["chunks"] = {
            chunk_id: {
                "chunk_id": chunk_id,
                "owned_document_page_ranges": [[index, index]],
            }
            for index, chunk_id in enumerate(chunk_ids, start=1)
        }
        args = self.args(
            [f"https://github.com/example/synthetic-candidate/pull/{index}" for index in range(1, 4)],
            [f"binding-{index}.json" for index in range(1, 4)],
        )
        args.locator_packet = [f"candidate-locator-{chunk_id}.json" for chunk_id in chunk_ids]
        workers = [
            self.worker("CHUNK-001", ["LOC-001"]),
            self.worker("CHUNK-002", ["LOC-002"]),
            self.worker("CHUNK-003", ["LOC-003"]),
        ]

        def complete_packet_set(paths: list[str], loaded_frozen: dict[str, Any]) -> dict[str, Any]:
            self.assertEqual(17, len(paths))
            self.assertEqual(set(chunk_ids), set(loaded_frozen["chunks"]))
            return {
                "packets": {chunk_id: {"assignments": {}} for chunk_id in chunk_ids},
                "sha256": "a" * 64,
                "assignment_ids": [],
            }

        with mock.patch.object(
            parallel, "load_frozen_inputs", return_value=frozen
        ), mock.patch.object(
            parallel, "load_packet_set", side_effect=complete_packet_set
        ), mock.patch.object(
            parallel, "load_worker_binding", side_effect=workers
        ):
            result = parallel.preflight_batch(args)

        self.assertEqual(["CHUNK-001", "CHUNK-002", "CHUNK-003"], result["chunk_ids"])
        self.assertEqual(17, len(result["kind_inputs"]["packets"]))

    def test_missing_or_unpaired_explicit_selection_is_rejected(self) -> None:
        for selections, bindings in (([], []), (["locator-audit/chunk-001"], [])):
            args = self.args(selections, bindings)
            with mock.patch.object(
                parallel, "load_frozen_inputs", return_value=frozen_fixture()
            ):
                self.assert_error("explicit_batch_required", parallel.preflight_batch, args)

    def test_duplicate_pr_selection_and_duplicate_chunk_are_rejected(self) -> None:
        url = "https://github.com/example/synthetic-candidate/pull/17"
        args = self.args([url, url], ["one.json", "two.json"])
        with mock.patch.object(
            parallel, "load_frozen_inputs", return_value=frozen_fixture()
        ), mock.patch.object(parallel, "load_packet_set", return_value={"packets": {}}):
            self.assert_error("duplicate_selection", parallel.preflight_batch, args)

        args = self.args(
            [url, "https://github.com/example/synthetic-candidate/pull/18"],
            ["one.json", "two.json"],
        )
        duplicate = self.worker("CHUNK-001", ["LOC-001"])
        self.assert_error(
            "duplicate_chunk",
            self.run_preflight,
            args,
            [duplicate, copy.deepcopy(duplicate)],
        )

    def test_duplicate_owned_judgment_and_base_conflict_are_rejected(self) -> None:
        args = self.args(
            [
                "https://github.com/example/synthetic-candidate/pull/17",
                "https://github.com/example/synthetic-candidate/pull/18",
            ],
            ["one.json", "two.json"],
        )
        self.assert_error(
            "duplicate_batch_judgment",
            self.run_preflight,
            args,
            [
                self.worker("CHUNK-001", ["LOC-DUP"]),
                self.worker("CHUNK-002", ["LOC-DUP"]),
            ],
        )
        self.assert_error(
            "batch_base_mismatch",
            self.run_preflight,
            args,
            [
                self.worker("CHUNK-001", ["LOC-001"]),
                self.worker("CHUNK-002", ["LOC-005"], base_commit="2" * 40),
            ],
        )

    def test_selected_batch_fails_before_any_mutation_if_one_binding_fails(self) -> None:
        args = self.args(
            [
                "https://github.com/example/synthetic-candidate/pull/17",
                "https://github.com/example/synthetic-candidate/pull/18",
            ],
            ["one.json", "two.json"],
        )
        with mock.patch.object(
            parallel, "load_frozen_inputs", return_value=frozen_fixture()
        ), mock.patch.object(
            parallel, "load_packet_set", return_value={"packets": {}}
        ), mock.patch.object(
            parallel,
            "load_worker_binding",
            side_effect=[
                self.worker("CHUNK-001", ["LOC-001"]),
                PreparationError("binding_file_hash_mismatch", "synthetic failure"),
            ],
        ), mock.patch.object(parallel, "replace_bytes_atomic") as mutate:
            self.assert_error("binding_file_hash_mismatch", parallel.preflight_batch, args)
            mutate.assert_not_called()


class CompletionAccountingTests(ErrorAssertionsMixin, unittest.TestCase):
    def canonical_frozen(self, root: Path) -> dict[str, Any]:
        frozen = frozen_fixture()
        frozen["root"] = root
        frozen["state"]["candidate"] = {
            "normalized_path": "candidate/synthetic-candidate/candidate-index.v2.json"
        }
        frozen["manifest"] = {"artifacts": []}
        return frozen

    def publication_evidence(
        self,
        receipt: dict[str, Any],
        payload: bytes,
        chunk_id: str,
        audit_kind: str,
        *,
        merged: bool,
    ) -> dict[str, Any]:
        pr = 17 if chunk_id == "CHUNK-001" else 18
        path = parallel.public_path_for(audit_kind, chunk_id)
        record = {
            "schema_version": (
                "candidate-audit-merge-evidence-v1"
                if merged
                else "candidate-audit-open-pr-evidence-v1"
            ),
            "evidence_source": "github_api",
            "audit_kind": parallel.serialized_audit_kind(audit_kind),
            "candidate_project": "example/synthetic-candidate",
            "pull_request": pr,
            "pull_request_url": f"https://github.com/example/synthetic-candidate/pull/{pr}",
            "state": "closed" if merged else "open",
            "merged": merged,
            "base_branch": "main",
            "observed_base_head_commit": "9" * 40 if merged else "1" * 40,
            "head_branch": parallel.branch_for(audit_kind, chunk_id),
            "head_commit": ("2" if chunk_id == "CHUNK-001" else "4") * 40,
            "worker_base_commit": "1" * 40,
            "merge_base_commit": "1" * 40,
            "commit_count": 1,
            "changed_files": [
                {
                    "path": path,
                    "blob_sha": parallel.git_blob_sha_bytes(payload, "0" * 40),
                    "file_sha256": parallel.sha256_bytes(payload),
                }
            ],
            "observed_at": "2026-08-24T12:00:00Z",
        }
        if merged:
            record["merge_commit"] = ("3" if chunk_id == "CHUNK-001" else "5") * 40
        return record

    def materialize_canonical(
        self, frozen: dict[str, Any], audit_kind: str, chunk_id: str
    ) -> None:
        audit = (
            locator_audit()
            if audit_kind == "locator" and chunk_id == "CHUNK-001"
            else locator_audit_two()
            if audit_kind == "locator"
            else missing_audit(frozen, chunk_id)
        )
        if audit_kind == "missing_access":
            audit["provenance"]["locator_audit_set_sha256"] = "b" * 64
        audit_payload = parallel.json_bytes(audit)
        reconnect = {
            "source_chunk_file_sha256": "a" * 64,
            "source_sidecar_file_sha256": "b" * 64,
        }
        if audit_kind == "locator":
            packet = locator_packet() if chunk_id == "CHUNK-001" else locator_packet_two()
            result = parallel.validate_locator_audit(
                audit, frozen, packet, chunk_id
            )
            report = parallel.build_locator_report(
                frozen,
                chunk_id,
                "1" * 40,
                reconnect,
                packet,
                result,
                parallel.sha256_bytes(audit_payload),
            )
        else:
            workset = parallel.build_missing_worksets(frozen)[chunk_id]
            result = parallel.validate_missing_access_audit(
                audit,
                frozen,
                workset,
                chunk_id,
                locator_audit_set_sha256="b" * 64,
            )
            report = parallel.build_missing_report(
                frozen,
                chunk_id,
                "1" * 40,
                workset,
                {"sha256": "b" * 64},
                result,
                audit,
                parallel.sha256_bytes(audit_payload),
            )
        public_payload = parallel.json_bytes(report)
        recovery = {
            "archive_sha256": "6" * 64,
            "archive_byte_length": 100,
            "metadata_sha256": "7" * 64,
            "checkpoint_ref": f"RECOVERY-{chunk_id}",
            "archive_path": frozen["root"] / f"recovery-{chunk_id}.zip",
        }
        receipt = parallel.make_receipt(
            audit_kind,
            frozen,
            chunk_id,
            "example/synthetic-candidate",
            "main",
            "1" * 40,
            parallel.branch_for(audit_kind, chunk_id),
            report["identities"],
            f"{audit_kind}-audit.{chunk_id}.json",
            audit_payload,
            result,
            recovery,
            f"workers/{audit_kind}/{chunk_id}",
            public_payload,
        )
        opened = self.publication_evidence(
            receipt, public_payload, chunk_id, audit_kind, merged=False
        )
        merged = self.publication_evidence(
            receipt, public_payload, chunk_id, audit_kind, merged=True
        )
        paths = parallel.canonical_worker_paths(frozen, audit_kind, chunk_id)
        payloads = {
            "audit": audit_payload,
            "receipt": parallel.json_bytes(receipt),
            "open_evidence": parallel.json_bytes(opened),
            "merge_evidence": parallel.json_bytes(merged),
            "public_report": public_payload,
        }
        for name, payload in payloads.items():
            parallel.replace_bytes_atomic(paths[name], payload)
            frozen["manifest"]["artifacts"].append(
                parallel.artifact_record(
                    paths[name],
                    frozen["root"],
                    parallel.audit_stage(audit_kind),
                    f"synthetic_{name}",
                    "public" if name == "public_report" else "private",
                    "2026-08-24T12:00:00Z",
                )
            )

    def test_locator_stage_is_partial_then_complete_only_at_exact_full_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            frozen = self.canonical_frozen(Path(directory))
            kind_inputs = {
                "packets": {
                    "CHUNK-001": locator_packet(),
                    "CHUNK-002": locator_packet_two(),
                },
                "assignment_ids": ["LOC-001", "LOC-002", "LOC-003", "LOC-004", "LOC-005"],
                "sha256": "a" * 64,
            }
            self.materialize_canonical(frozen, "locator", "CHUNK-001")
            partial = parallel.completion_accounting(frozen, "locator", kind_inputs)
            self.assertFalse(partial["complete"])
            self.assertEqual(["CHUNK-002"], partial["missing_chunk_ids"])
            self.assertEqual(4, partial["accepted_assignments"])

            self.materialize_canonical(frozen, "locator", "CHUNK-002")
            complete = parallel.completion_accounting(frozen, "locator", kind_inputs)
            self.assertTrue(complete["complete"])
            self.assertEqual([], complete["missing_chunk_ids"])
            self.assertEqual(5, complete["accepted_assignments"])

    def test_stray_private_audit_without_complete_provenance_never_counts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            frozen = self.canonical_frozen(Path(directory))
            path = parallel.canonical_worker_paths(
                frozen, "locator", "CHUNK-001"
            )["audit"]
            parallel.replace_bytes_atomic(path, parallel.json_bytes(locator_audit()))
            self.assert_error(
                "incomplete_existing_integration",
                parallel.completion_accounting,
                frozen,
                "locator",
                {
                    "packets": {
                        "CHUNK-001": locator_packet(),
                        "CHUNK-002": locator_packet_two(),
                    },
                    "assignment_ids": [
                        "LOC-001",
                        "LOC-002",
                        "LOC-003",
                        "LOC-004",
                        "LOC-005",
                    ],
                },
            )

    def test_missing_access_stage_is_partial_then_complete_at_all_denominators(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            frozen = self.canonical_frozen(Path(directory))
            worksets = parallel.build_missing_worksets(frozen)
            kind_inputs = {
                "locator_set": {"sha256": "b" * 64},
                "worksets": worksets,
            }
            self.materialize_canonical(frozen, "missing_access", "CHUNK-001")
            partial = parallel.completion_accounting(
                frozen, "missing_access", kind_inputs
            )
            self.assertFalse(partial["complete"])
            self.assertEqual(1, partial["accepted_subjects"])
            self.assertEqual(["CHUNK-002"], partial["missing_chunk_ids"])

            self.materialize_canonical(frozen, "missing_access", "CHUNK-002")
            complete = parallel.completion_accounting(
                frozen, "missing_access", kind_inputs
            )
            self.assertTrue(complete["complete"])
            self.assertEqual(2, complete["accepted_subjects"])
            self.assertEqual(2, complete["accepted_reader_tasks"])
            self.assertEqual(4, complete["accepted_treatments"])


class IntegrationTransactionTests(ErrorAssertionsMixin, unittest.TestCase):
    @staticmethod
    def accounting(*, complete: bool) -> dict[str, Any]:
        return {
            "expected_chunk_ids": ["CHUNK-001", "CHUNK-002"],
            "active_chunk_ids": ["CHUNK-001", "CHUNK-002"] if complete else ["CHUNK-001"],
            "missing_chunk_ids": [] if complete else ["CHUNK-002"],
            "complete": complete,
            "expected_assignments": 5,
            "accepted_assignments": 5 if complete else 4,
        }

    def canonical_frozen(self, root: Path) -> dict[str, Any]:
        state_path = root / "evaluation-state.json"
        manifest_path = root / "artifact-manifest.json"
        state = {
            "schema_version": "subject-index-evaluation-state-v4",
            "evaluation_id": "EVAL-SYNTHETIC",
            "artifact_manifest_path": "artifact-manifest.json",
            "updated_at": "2026-08-24T12:00:00Z",
            "candidate": {
                "candidate_id": "synthetic-candidate",
                "normalized_path": "candidate/synthetic-candidate/candidate-index.v2.json",
            },
            "stages": {
                "locator_audit": {
                    "status": "not_started",
                    "updated_at": None,
                    "notes": [],
                },
                "missing_access_audit": {
                    "status": "not_started",
                    "updated_at": None,
                    "notes": [],
                },
            },
            "artifacts": [],
        }
        manifest = {
            "schema_version": "subject-index-artifact-manifest-v1",
            "evaluation_id": "EVAL-SYNTHETIC",
            "updated_at": "2026-08-24T12:00:00Z",
            "artifacts": [],
        }
        state_path.write_bytes(parallel.json_bytes(state))
        manifest_path.write_bytes(parallel.json_bytes(manifest))
        frozen = frozen_fixture()
        frozen.update(
            {
                "root": root,
                "state_path": state_path,
                "state": state,
                "state_bytes": state_path.read_bytes(),
                "state_file_sha256": parallel.sha256_file(state_path),
                "manifest_path": manifest_path,
                "manifest": manifest,
                "manifest_bytes": manifest_path.read_bytes(),
                "manifest_file_sha256": parallel.sha256_file(manifest_path),
            }
        )
        return frozen

    def worker(self, frozen: dict[str, Any], chunk_id: str) -> dict[str, Any]:
        audit = locator_audit() if chunk_id == "CHUNK-001" else locator_audit_two()
        audit_payload = parallel.json_bytes(audit)
        pr = 17 if chunk_id == "CHUNK-001" else 18
        canonical = parallel.canonical_worker_paths(frozen, "locator", chunk_id)
        return {
            "chunk_id": chunk_id,
            "disposition": "new",
            "audit": audit,
            "audit_payload": audit_payload,
            "receipt": {
                "receipt_sha256": ("a" if chunk_id == "CHUNK-001" else "b") * 64,
                "private_artifact": {"sha256": parallel.sha256_bytes(audit_payload)},
            },
            "receipt_payload": parallel.json_bytes({"private": "synthetic receipt"}),
            "report_payload": parallel.json_bytes({"aggregate": chunk_id}),
            "report_file_sha256": ("c" if chunk_id == "CHUNK-001" else "d") * 64,
            "open_evidence": {
                "pull_request": pr,
                "pull_request_url": f"https://github.com/example/synthetic-candidate/pull/{pr}",
                "head_commit": ("2" if chunk_id == "CHUNK-001" else "4") * 40,
            },
            "open_payload": parallel.json_bytes({"open": pr}),
            "open_evidence_sha256": ("e" if chunk_id == "CHUNK-001" else "f") * 64,
            "recovery": {"archive_sha256": ("6" if chunk_id == "CHUNK-001" else "7") * 64},
            "canonical": canonical,
            "owned_ids": list(audit["expected_locator_ids"]),
        }

    def batch(self, frozen: dict[str, Any], workers: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "audit_kind": "locator",
            "project": "example/synthetic-candidate",
            "frozen": frozen,
            "kind_inputs": {
                "packets": {
                    "CHUNK-001": locator_packet(),
                    "CHUNK-002": locator_packet_two(),
                },
                "assignment_ids": [
                    "LOC-001",
                    "LOC-002",
                    "LOC-003",
                    "LOC-004",
                    "LOC-005",
                ],
                "sha256": "8" * 64,
            },
            "workers": workers,
            "chunk_ids": sorted(worker["chunk_id"] for worker in workers),
            "base_branch": "main",
            "base_commit": "1" * 40,
        }

    def merge_files(self, root: Path, workers: list[dict[str, Any]]) -> list[str]:
        paths = []
        for worker in workers:
            pr = worker["open_evidence"]["pull_request"]
            path = root / f"merge-{pr}.json"
            path.write_bytes(
                parallel.json_bytes(
                    {
                        "pull_request": pr,
                        "merge_commit": ("3" if pr == 17 else "5") * 40,
                    }
                )
            )
            paths.append(str(path))
        return paths

    def refreshed_run(self, frozen: dict[str, Any]) -> dict[str, Any]:
        refreshed = dict(frozen)
        refreshed["state"] = json.loads(frozen["state_path"].read_text(encoding="utf-8"))
        refreshed["state_bytes"] = frozen["state_path"].read_bytes()
        refreshed["state_file_sha256"] = parallel.sha256_file(frozen["state_path"])
        refreshed["manifest"] = json.loads(
            frozen["manifest_path"].read_text(encoding="utf-8")
        )
        refreshed["manifest_bytes"] = frozen["manifest_path"].read_bytes()
        refreshed["manifest_file_sha256"] = parallel.sha256_file(
            frozen["manifest_path"]
        )
        return refreshed

    def args(
        self, root: Path, merge_paths: list[str]
    ) -> argparse.Namespace:
        return argparse.Namespace(
            audit_kind="locator",
            merge_evidence=merge_paths,
            checkpoint_output=str(root / "checkpoints" / "cumulative.zip"),
            integration_report=str(root / "validation" / "integration.json"),
        )

    def test_partial_integration_writes_manifest_before_state_and_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frozen = self.canonical_frozen(root)
            workers = [self.worker(frozen, "CHUNK-001")]
            batch = self.batch(frozen, workers)
            args = self.args(root, self.merge_files(root, workers))
            writes: list[Path] = []
            original_replace = parallel.replace_bytes_atomic

            def record_replace(path: Path, payload: bytes) -> None:
                writes.append(Path(path))
                original_replace(Path(path), payload)

            with mock.patch.object(
                parallel, "preflight_batch", side_effect=[batch, batch]
            ), mock.patch.object(
                parallel,
                "validate_publication_evidence",
                return_value={"evidence_sha256": "9" * 64},
            ), mock.patch.object(
                parallel,
                "evaluation_integration_lock",
                return_value=contextlib.nullcontext(),
            ), mock.patch.object(
                parallel, "validate_state", return_value=([], [])
            ), mock.patch.object(
                parallel,
                "load_canonical_run",
                side_effect=lambda _: self.refreshed_run(frozen),
            ), mock.patch.object(
                parallel,
                "completion_accounting",
                return_value=self.accounting(complete=False),
            ), mock.patch.object(
                parallel, "replace_bytes_atomic", side_effect=record_replace
            ):
                result = parallel.integrate_batch(args)

            self.assertEqual("integrated_partial", result["report"]["status"])
            self.assertEqual("in_progress", result["report"]["stage_status"])
            self.assertEqual(["CHUNK-002"], result["report"]["coverage"]["missing_chunk_ids"])
            self.assertLess(writes.index(frozen["manifest_path"]), writes.index(frozen["state_path"]))
            state = json.loads(frozen["state_path"].read_text(encoding="utf-8"))
            self.assertEqual("in_progress", state["stages"]["locator_audit"]["status"])
            checkpoint = Path(args.checkpoint_output)
            self.assertTrue(checkpoint.is_file())
            with zipfile.ZipFile(checkpoint) as archive:
                metadata = json.loads(archive.read("checkpoint-metadata.json"))
            self.assertFalse(metadata["restricted_pdfs_included"])
            self.assertEqual(
                "update_manifest",
                result["report"]["transaction_order"][4],
            )
            self.assertEqual(
                "update_state_last",
                result["report"]["transaction_order"][5],
            )

    def test_full_batch_marks_stage_complete_only_after_all_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frozen = self.canonical_frozen(root)
            workers = [
                self.worker(frozen, "CHUNK-001"),
                self.worker(frozen, "CHUNK-002"),
            ]
            batch = self.batch(frozen, workers)
            args = self.args(root, self.merge_files(root, workers))
            with mock.patch.object(
                parallel, "preflight_batch", side_effect=[batch, batch]
            ), mock.patch.object(
                parallel,
                "validate_publication_evidence",
                return_value={"evidence_sha256": "9" * 64},
            ), mock.patch.object(
                parallel,
                "evaluation_integration_lock",
                return_value=contextlib.nullcontext(),
            ), mock.patch.object(
                parallel, "validate_state", return_value=([], [])
            ), mock.patch.object(
                parallel,
                "load_canonical_run",
                side_effect=lambda _: self.refreshed_run(frozen),
            ), mock.patch.object(
                parallel,
                "completion_accounting",
                return_value=self.accounting(complete=True),
            ):
                result = parallel.integrate_batch(args)
            self.assertEqual("integrated_complete", result["report"]["status"])
            self.assertEqual("completed", result["report"]["stage_status"])
            self.assertEqual([], result["report"]["coverage"]["missing_chunk_ids"])
            state = json.loads(frozen["state_path"].read_text(encoding="utf-8"))
            self.assertEqual("completed", state["stages"]["locator_audit"]["status"])

    def test_canonical_validation_failure_rolls_back_selected_batch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frozen = self.canonical_frozen(root)
            workers = [self.worker(frozen, "CHUNK-001")]
            batch = self.batch(frozen, workers)
            args = self.args(root, self.merge_files(root, workers))
            original_state = frozen["state_path"].read_bytes()
            original_manifest = frozen["manifest_path"].read_bytes()
            with mock.patch.object(
                parallel, "preflight_batch", side_effect=[batch, batch]
            ), mock.patch.object(
                parallel,
                "validate_publication_evidence",
                return_value={"evidence_sha256": "9" * 64},
            ), mock.patch.object(
                parallel,
                "evaluation_integration_lock",
                return_value=contextlib.nullcontext(),
            ), mock.patch.object(
                parallel,
                "validate_state",
                return_value=(["synthetic canonical validation failure"], []),
            ):
                self.assert_error("canonical_validation_failed", parallel.integrate_batch, args)
            self.assertEqual(original_state, frozen["state_path"].read_bytes())
            self.assertEqual(original_manifest, frozen["manifest_path"].read_bytes())
            self.assertFalse(workers[0]["canonical"]["audit"].exists())
            self.assertFalse(Path(args.checkpoint_output).exists())
class UtilityContractTests(ErrorAssertionsMixin, unittest.TestCase):
    def test_publication_migration_binds_legacy_and_canonical_histories(self) -> None:
        frozen = frozen_fixture()
        frozen["state"]["candidate"] = {"candidate_id": "synthetic-candidate"}
        receipt = {
            "receipt_sha256": "4" * 64,
            "private_artifact": {"sha256": "5" * 64},
            "public_projection": {"sha256": "6" * 64},
        }
        migration = {
            "schema_version": parallel.PUBLICATION_MIGRATION_VERSION,
            "migration_sha256": "",
            "evaluation_id": "EVAL-SYNTHETIC",
            "candidate_id": "synthetic-candidate",
            "audit_kind": "locator_audit",
            "chunk_id": "CHUNK-001",
            "migrated_at": "2026-08-25T12:00:00Z",
            "transition": {"from": "aggregate_only", "to": "public_evaluation_artifacts"},
            "legacy_receipt": {
                "receipt_sha256": "4" * 64,
                "private_artifact_sha256": "5" * 64,
                "public_report_sha256": "6" * 64,
            },
            "canonical_public_artifact": {
                "repository_path": "candidate/locator-audits/locator-audit.CHUNK-001.v1.json",
                "sha256": "7" * 64,
                "byte_length": 123,
                "commit": "8" * 40,
                "blob_sha": "9" * 40,
            },
            "normalization": {
                "method": "strict_public_allowlist_v1",
                "judgment_count": 4,
                "semantic_fields_preserved": True,
                "legacy_artifact_retained_in_recovery": True,
            },
        }
        migration["migration_sha256"] = parallel.canonical_hash(migration, "migration_sha256")
        parallel.validate_publication_migration(
            migration, "locator", "CHUNK-001", frozen, receipt, "7" * 64, 123
        )

    def test_legacy_state_defaults_to_aggregate_only(self) -> None:
        self.assertEqual("aggregate_only", parallel.publication_profile_for({}))
        self.assertEqual(
            "public_evaluation_artifacts",
            parallel.publication_profile_for(
                {"configuration": {"publication_profile": "public_evaluation_artifacts"}}
            ),
        )
        self.assert_error(
            "publication_profile",
            parallel.publication_profile_for,
            {"configuration": {"publication_profile": "unknown"}},
        )

    def test_branch_and_public_paths_are_kind_and_chunk_specific(self) -> None:
        self.assertEqual("locator-audit/chunk-001", parallel.branch_for("locator", "CHUNK-001"))
        self.assertEqual(
            "missing-access-audit/chunk-001",
            parallel.branch_for("missing_access", "CHUNK-001"),
        )
        self.assertEqual(
            "validation/locator-audit-worker.CHUNK-001.json",
            parallel.public_path_for("locator", "CHUNK-001"),
        )

    def test_chunk_ownership_overlap_is_rejected(self) -> None:
        frozen = frozen_fixture()
        frozen["chunk_manifest"]["chunks"][1]["owned_document_page_ranges"] = [[2, 4]]
        self.assert_error(
            "overlapping_chunk_ownership", parallel.page_owner_map, frozen["chunk_manifest"]
        )

if __name__ == "__main__":
    unittest.main()
