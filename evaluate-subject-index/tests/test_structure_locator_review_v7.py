from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
SCHEMAS = ROOT / "references" / "schemas"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import item_projection_core as items  # noqa: E402
from structure_locator_review import (  # noqa: E402
    StructureReviewError,
    canonical_hash,
    derive_structure_locator_review,
    validate_structure_locator_review_semantics,
)


SHA = "a" * 64


def candidate_from_specs(specs: list[tuple[str, int]]) -> dict:
    """Build one normalized path from (singleton|range, span) display specs."""

    displays = []
    assignments = []
    next_page = 1
    for index, (kind, span) in enumerate(specs, start=1):
        display_id = f"DISPLAY-{index:04d}"
        count = 1 if kind == "singleton" else span
        locator_ids = [f"LOC-{len(assignments) + offset + 1:04d}" for offset in range(count)]
        range_id = f"RANGE-{index:04d}" if kind == "range" else None
        for offset, locator_id in enumerate(locator_ids):
            page = next_page + offset
            assignments.append(
                {
                    "locator_id": locator_id,
                    "display_id": display_id,
                    "displayed_locator": str(page) if kind == "singleton" else f"{next_page}–{next_page + span - 1}",
                    "source_page_label": str(page),
                    "normalized_locator_key": str(page),
                    "document_page": page,
                    "mapping_status": "resolved",
                    "range_id": range_id,
                }
            )
        display = {
            "display_id": display_id,
            "displayed_locator": str(next_page) if kind == "singleton" else f"{next_page}–{next_page + span - 1}",
            "kind": "point" if kind == "singleton" else "range",
            "range_id": range_id,
            "mapping_status": "resolved",
            "locator_ids": locator_ids,
        }
        if kind == "range":
            display |= {"start_display": str(next_page), "end_display": str(next_page + span - 1)}
        displays.append(display)
        next_page += count + 2
    return {
        "schema_version": "candidate-index-v2",
        "candidate_id": "CAND-V7-STRUCTURE",
        "candidate_sha256": SHA,
        "page_map_sha256": "b" * 64,
        "records": [
            {
                "record_id": "REC-0001",
                "record_type": "page_bearing",
                "path_id": "PATH-0001",
                "heading_path": ["agriculture", "pre-Revolutionary"],
                "original_displayed_form": "frozen but never parsed",
                "locator_displays": displays,
                "locator_assignments": assignments,
                "cross_references": [],
            }
        ],
        "normalization": {
            "engine": "synthetic",
            "engine_version": "1",
            "record_count": 1,
            "editorial_corrections_applied": False,
            "benchmark_content_used": False,
        },
    }


def structure_for(candidate: dict, inventory: dict, defects: list[dict] | None = None, decisions: list[dict] | None = None) -> dict:
    node_id = inventory["paths"][0]["node_ids"][-1]
    result = {
        "schema_version": "structure-audit-v5",
        "evaluation_id": "EVAL-V7-STRUCTURE",
        "candidate_sha256": candidate["candidate_sha256"],
        "v5_scoring_context": {"defects": defects or []},
        "node_judgments": [
            {
                "node_id": node_id,
                "component_judgments": {
                    "heading_access_architecture": {
                        "status": "minor_issues" if defects else "passes",
                        "summary": "Explanation text is not a mapping input.",
                        "evidence_ids": [],
                    }
                },
            }
        ],
    }
    if decisions is not None:
        result["v7_architecture_review_decisions"] = decisions
    return result


def defect(inventory: dict, family: str, *, defect_id: str = "DEFECT-STRUCT-1") -> dict:
    return {
        "defect_id": defect_id,
        "code": "SUB",
        "dimension_owner": "findability_navigation",
        "severity": "minor",
        "root_cause_family": family,
        "affected_item_ids": [inventory["paths"][0]["node_ids"][-1]],
    }


def derive(specs: list[tuple[str, int]], *, defects: list[dict] | None = None, decisions: list[dict] | None = None) -> tuple[dict, dict, dict, dict]:
    candidate = candidate_from_specs(specs)
    inventory = items.build_inventory(candidate)
    structure = structure_for(candidate, inventory, defects, decisions)
    review = derive_structure_locator_review(
        candidate,
        inventory,
        structure,
        candidate_file_sha256="c" * 64,
        inventory_file_sha256="d" * 64,
        structure_file_sha256="e" * 64,
        audit_mode="full",
    )
    return review, candidate, inventory, structure


class StructureLocatorDerivationTests(unittest.TestCase):
    def path(self, review: dict) -> dict:
        self.assertEqual(1, len(review["path_reviews"]))
        return review["path_reviews"][0]

    def test_oxford_regression_shape_uses_three_distinct_quantities(self) -> None:
        review, *_ = derive([("range", 8), ("range", 3), ("singleton", 1)])
        path = self.path(review)
        self.assertEqual(3, path["displayed_locator_count"])
        self.assertEqual(12, path["atomic_assignment_count"])
        self.assertEqual(8, path["maximum_range_span"])
        self.assertFalse(path["long_displayed_locator_string_review_trigger"])
        self.assertFalse(path["long_continuous_range_review_trigger"])
        self.assertEqual("no_numeric_review_trigger", path["final_architecture_disposition"])
        self.assertEqual([8, 3], [item["inclusive_range_span"] for item in path["displayed_locators"] if item["kind"] == "range"])

    def test_six_and_seven_displayed_singletons_are_exact_boundaries(self) -> None:
        six, *_ = derive([("singleton", 1)] * 6)
        seven, *_ = derive([("singleton", 1)] * 7)
        self.assertFalse(self.path(six)["long_displayed_locator_string_review_trigger"])
        path = self.path(seven)
        self.assertTrue(path["long_displayed_locator_string_review_trigger"])
        self.assertEqual("review_required", path["final_architecture_disposition"])
        self.assertEqual([], path["applicable_structured_defect_ids"])

    def test_ten_and_eleven_page_ranges_are_exact_boundaries(self) -> None:
        ten, *_ = derive([("range", 10)])
        eleven, *_ = derive([("range", 11)])
        path_ten = self.path(ten)
        path_eleven = self.path(eleven)
        self.assertEqual((1, 10), (path_ten["displayed_locator_count"], path_ten["atomic_assignment_count"]))
        self.assertFalse(path_ten["long_continuous_range_review_trigger"])
        self.assertEqual((1, 11), (path_eleven["displayed_locator_count"], path_eleven["atomic_assignment_count"]))
        self.assertTrue(path_eleven["long_continuous_range_review_trigger"])
        self.assertEqual("review_required", path_eleven["final_architecture_disposition"])

    def test_combined_atomic_pages_never_drive_long_string_trigger(self) -> None:
        review, *_ = derive([("range", 4), ("range", 4)])
        path = self.path(review)
        self.assertEqual(2, path["displayed_locator_count"])
        self.assertEqual(8, path["atomic_assignment_count"])
        self.assertFalse(path["long_displayed_locator_string_review_trigger"])

    def test_seven_displayed_ranges_trigger_once_each_regardless_of_size(self) -> None:
        review, *_ = derive([("range", 2)] * 7)
        path = self.path(review)
        self.assertEqual(7, path["displayed_locator_count"])
        self.assertEqual(14, path["atomic_assignment_count"])
        self.assertTrue(path["long_displayed_locator_string_review_trigger"])
        self.assertFalse(path["long_continuous_range_review_trigger"])

    def test_trigger_plus_independent_structured_evidence_can_confirm_defect(self) -> None:
        candidate = candidate_from_specs([("singleton", 1)] * 7)
        inventory = items.build_inventory(candidate)
        structured = defect(inventory, "conceptual_heterogeneity_with_impaired_access")
        review, *_ = derive([("singleton", 1)] * 7, defects=[structured])
        path = self.path(review)
        self.assertEqual("structured_defect_confirmed", path["final_architecture_disposition"])
        self.assertEqual(["DEFECT-STRUCT-1"], path["retained_structured_defect_ids"])
        facts = path["independent_architecture_evidence"]
        self.assertTrue(facts["conceptually_distinguishable_treatments"])
        self.assertTrue(facts["material_scanning_or_retrieval_impairment"])

    def test_trigger_without_semantic_evidence_is_review_required_not_failure(self) -> None:
        review, *_ = derive([("range", 11)])
        path = self.path(review)
        self.assertEqual("review_required", path["final_architecture_disposition"])
        self.assertEqual(["PATH-0001"], review["summary"]["review_required_path_ids"])

    def test_triggered_heading_can_pass_only_after_structured_review(self) -> None:
        decision = {
            "review_id": "ARCHREV-0001",
            "path_id": "PATH-0001",
            "review_status": "reviewed_no_defect",
            "conceptually_distinguishable_treatments": True,
            "meaningful_subheadings_or_access_routes": False,
            "material_scanning_or_retrieval_impairment": False,
            "subdivision_is_conceptual_not_trivial": False,
            "evidence_ids": ["EVID-ARCH-0001"],
            "defect_ids": [],
        }
        review, *_ = derive([("singleton", 1)] * 7, decisions=[decision])
        path = self.path(review)
        self.assertTrue(path["long_displayed_locator_string_review_trigger"])
        self.assertEqual("reviewed_no_defect", path["final_architecture_disposition"])

    def test_range_binding_loss_fails_closed_instead_of_parsing_display_text(self) -> None:
        candidate = candidate_from_specs([("range", 8)])
        candidate["records"][0]["locator_displays"][0]["locator_ids"] = candidate["records"][0]["locator_displays"][0]["locator_ids"][:-1]
        inventory = items.build_inventory(candidate)
        structure = structure_for(candidate, inventory)
        review = derive_structure_locator_review(candidate, inventory, structure, candidate_file_sha256="c" * 64, inventory_file_sha256="d" * 64, structure_file_sha256="e" * 64, audit_mode="full")
        path = self.path(review)
        self.assertFalse(path["derivation_complete"])
        self.assertIsNone(path["atomic_assignment_count"])
        self.assertEqual("derivation_failed", path["final_architecture_disposition"])
        self.assertFalse(review["display_prose_parsed"])

    def test_schema_and_repeated_output_are_byte_identical(self) -> None:
        first, candidate, inventory, structure = derive([("range", 8), ("range", 3), ("singleton", 1)])
        second = derive_structure_locator_review(candidate, inventory, structure, candidate_file_sha256="c" * 64, inventory_file_sha256="d" * 64, structure_file_sha256="e" * 64, audit_mode="full")
        first_bytes = json.dumps(first, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        second_bytes = json.dumps(second, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        self.assertEqual(first_bytes, second_bytes)
        self.assertEqual(first["review_sha256"], canonical_hash(first, "review_sha256"))
        schema = json.loads((SCHEMAS / "structure-locator-review-v1.schema.json").read_text())
        jsonschema.validate(first, schema)

    def test_cross_field_validation_prevents_atomic_count_from_becoming_display_count(self) -> None:
        review, *_ = derive([("range", 8), ("range", 3), ("singleton", 1)])
        tampered = copy.deepcopy(review)
        path = tampered["path_reviews"][0]
        path["displayed_locator_count"] = path["atomic_assignment_count"]
        tampered["review_sha256"] = canonical_hash(tampered, "review_sha256")
        schema = json.loads((SCHEMAS / "structure-locator-review-v1.schema.json").read_text())
        jsonschema.validate(tampered, schema)
        with self.assertRaisesRegex(StructureReviewError, "displayed_locator_count_mismatch"):
            validate_structure_locator_review_semantics(tampered)

    def test_schema_rejects_trigger_only_scored_defect_disposition(self) -> None:
        review, *_ = derive([("singleton", 1)] * 7)
        tampered = copy.deepcopy(review)
        tampered["path_reviews"][0]["final_architecture_disposition"] = (
            "structured_defect_confirmed"
        )
        schema = json.loads((SCHEMAS / "structure-locator-review-v1.schema.json").read_text())
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(tampered, schema)

if __name__ == "__main__":
    unittest.main()
