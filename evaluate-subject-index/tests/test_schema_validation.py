from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from schema_validation import schema_errors


class SharedSchemaValidationTests(unittest.TestCase):
    def test_locator_audit_nested_shape_is_owned_by_schema(self) -> None:
        audit = {
            "schema_version": "locator-audit-v2",
            "evaluation_id": "EVAL-1",
            "candidate_sha256": "0" * 64,
            "chunk_id": "CHUNK-001",
            "expected_locator_ids": ["LOC-1"],
            "judgments": [{
                "locator_id": "LOC-1",
                "path_id": "PATH-1",
                "complete_heading_path": ["Subject"],
                "document_page": 1,
                "source_page_label": "1",
                "source_scope_status": "indexable",
                "treatment_class": "substantive",
                "judgment": "supported",
                "evidence_summary": "Supported by the cited page.",
                "evidence_ids": ["EVID-1"],
                "confidence": "high",
                "error_codes": [],
                "severity": "none",
            }],
            "completion": {"expected": 1, "judged": 1, "unique": True, "complete": True},
        }
        self.assertEqual(schema_errors(audit, "locator-audit-v2.schema.json"), [])
        del audit["judgments"][0]["evidence_ids"]
        self.assertTrue(any("evidence_ids" in error for error in schema_errors(audit, "locator-audit-v2.schema.json")))

    def test_relative_schema_reference_validates_chunk_plan(self) -> None:
        manifest = {
            "schema_version": "chunk-manifest-v1",
            "document_page_basis": "one_based_inclusive",
            "page_map_sha256": "0" * 64,
            "user_approved": True,
            "require_full_scope_coverage": True,
            "chunks": [{
                "chunk_id": "CHUNK-001",
                "title": "Chapter 1",
                "source_units": ["Chapter 1"],
                "owned_document_page_ranges": [[1, 2]],
                "context_document_page_ranges": [],
                "packet_order": 1,
            }],
            "validation": {"owned_pages_unique": True, "scope_coverage_complete": True},
            "chunk_manifest_sha256": "0" * 64,
        }
        self.assertEqual(schema_errors(manifest, "chunk-manifest.schema.json"), [])
        manifest["chunks"][0]["packet_order"] = 0
        self.assertTrue(any("packet_order" in error for error in schema_errors(manifest, "chunk-manifest.schema.json")))


if __name__ == "__main__":
    unittest.main()
