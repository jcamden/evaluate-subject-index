from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
TESTS = ROOT / "tests"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(TESTS))

import dimension_score_cli as v5  # noqa: E402
import dimension_score_v6_cli as v6  # noqa: E402
from test_dimension_scoring_v5 import (  # noqa: E402
    base_documents,
    calculation_files,
    defect,
    digest,
    run_cli,
    write_json,
)
from test_dimension_scoring_v6 import v6_items  # noqa: E402


def normalized_candidate(locator: dict) -> dict:
    records = []
    path_ids = sorted({item["path_id"] for item in locator["judgments"]})
    for path_index, path_id in enumerate(path_ids, start=1):
        judgments = [item for item in locator["judgments"] if item["path_id"] == path_id]
        displays = []
        assignments = []
        for display_index, judgment in enumerate(judgments, start=1):
            display_id = f"DISPLAY-{path_index:04d}-{display_index:04d}"
            assignments.append(
                {
                    "locator_id": judgment["locator_id"],
                    "display_id": display_id,
                    "displayed_locator": judgment["source_page_label"],
                    "source_page_label": judgment["source_page_label"],
                    "normalized_locator_key": judgment["source_page_label"],
                    "document_page": judgment["document_page"],
                    "mapping_status": "resolved",
                    "range_id": None,
                }
            )
            displays.append(
                {
                    "display_id": display_id,
                    "displayed_locator": judgment["source_page_label"],
                    "kind": "point",
                    "range_id": None,
                    "mapping_status": "resolved",
                    "locator_ids": [judgment["locator_id"]],
                }
            )
        records.append(
            {
                "record_id": f"REC-{path_index:04d}",
                "record_type": "page_bearing",
                "path_id": path_id,
                "heading_path": [f"Heading {path_index}"],
                "original_displayed_form": "Frozen candidate line.",
                "locator_displays": displays,
                "locator_assignments": assignments,
                "cross_references": [],
            }
        )
    return {
        "schema_version": "candidate-index-v2",
        "candidate_id": "candidate-synthetic",
        "candidate_sha256": locator["candidate_sha256"],
        "page_map_sha256": "1" * 64,
        "records": records,
        "normalization": {
            "engine": "synthetic-test",
            "engine_version": "1",
            "record_count": len(records),
            "editorial_corrections_applied": False,
            "benchmark_content_used": False,
        },
    }


def prepare_v6_projection(
    root: Path,
    documents: tuple[dict, dict, dict] | None = None,
    candidate_document: dict | None = None,
) -> dict[str, Path]:
    locator, missing, structure = documents or base_documents()
    candidate_path = root / "candidate-index.json"
    write_json(candidate_path, candidate_document or normalized_candidate(locator))
    candidate_file_sha = digest(candidate_path)
    for document in (locator, missing):
        document["provenance"]["normalized_candidate_file_sha256"] = candidate_file_sha
    structure["provenance"]["normalized_candidate_file_sha256"] = candidate_file_sha
    config_path = calculation_files(root, locator, missing, structure)
    loaded = v5.load_inputs(config_path)
    calculation = v6.calculate_loaded(loaded)
    calculation_path = root / "dimension-calculations.v6.json"
    v6.write_json(calculation_path, calculation)
    items = v6_items(calculation, root, locator, structure)
    items_path = root / "item-assessments.v6.json"
    v6.write_json(items_path, items)
    metadata_path = root / "projection-metadata.v6.json"
    v6.write_json(
        metadata_path,
        {
            "schema_version": "subject-index-v6-projection-metadata-v1",
            "candidate_label": "Synthetic",
            "inclusion_policy": "standard",
            "uncertainty_policy": "v6_bounds",
            "critical_gates": [{"gate_id": "publication", "status": "passed"}],
        },
    )
    result_path = root / "evaluation-result.v6.json"
    web_path = root / "web-report.v6.json"
    result, web = v6.build_projections(
        calculation_path,
        items_path,
        metadata_path,
        result_path,
        web_path,
    )
    v6.write_json(result_path, result)
    v6.write_json(web_path, web)
    v6.validate_projection_artifacts(calculation_path, result_path, web_path)
    return {
        "config": config_path,
        "candidate": candidate_path,
        "inventory": root / "item-inventory.json",
        "calculation": calculation_path,
        "result": result_path,
        "items": items_path,
        "web": web_path,
        "metadata": metadata_path,
    }


def grouped_candidate(locator: dict, groups: list[int]) -> dict:
    """Return a candidate whose first path keeps exact display-to-atom grouping."""

    candidate = normalized_candidate(locator)
    record = next(item for item in candidate["records"] if item["path_id"] == "PATH-0001")
    source_assignments = record["locator_assignments"]
    if sum(groups) != len(source_assignments):
        raise AssertionError("group sizes must cover PATH-0001 exactly")
    displays = []
    assignments = []
    cursor = 0
    for index, count in enumerate(groups, start=1):
        owned = copy.deepcopy(source_assignments[cursor : cursor + count])
        display_id = f"DISPLAY-0001-{index:04d}"
        range_id = f"RANGE-0001-{index:04d}" if count > 1 else None
        start = owned[0]["source_page_label"]
        end = owned[-1]["source_page_label"]
        delivered = start if count == 1 else f"{start}–{end}"
        locator_ids = []
        for assignment in owned:
            assignment.update(
                display_id=display_id,
                displayed_locator=delivered,
                range_id=range_id,
            )
            locator_ids.append(assignment["locator_id"])
        display = {
            "display_id": display_id,
            "displayed_locator": delivered,
            "kind": "point" if count == 1 else "range",
            "range_id": range_id,
            "mapping_status": "resolved",
            "locator_ids": locator_ids,
        }
        if count > 1:
            display |= {"start_display": start, "end_display": end}
        displays.append(display)
        assignments.extend(owned)
        cursor += count
    record["locator_displays"] = displays
    record["locator_assignments"] = assignments
    return candidate


def expanded_path_documents(
    count: int,
    *,
    historical_atomic_threshold_defect: bool = False,
) -> tuple[dict, dict, dict]:
    locator, missing, structure = base_documents()
    template = next(item for item in locator["judgments"] if item["path_id"] == "PATH-0001")
    path_one = []
    for index in range(1, count + 1):
        record = copy.deepcopy(template)
        record.update(
            locator_id=f"LOC-RANGE-{index:04d}",
            document_page=index,
            source_page_label=str(index),
        )
        path_one.append(record)
    path_two = [
        item for item in locator["judgments"] if item["path_id"] == "PATH-0002"
    ]
    locator["judgments"] = [*path_one, *path_two]
    locator["expected_locator_ids"] = [item["locator_id"] for item in locator["judgments"]]
    locator["completion"].update(
        expected=len(locator["judgments"]),
        judged=len(locator["judgments"]),
    )
    structure["metrics"]["expanded_locators"] = len(locator["judgments"])
    structure["density"]["chapter_measurements"][0]["locator_occurrences"] = len(
        locator["judgments"]
    )
    if historical_atomic_threshold_defect:
        historical = defect(
            "DEFECT-ATOMIC-THRESHOLD",
            "findability_navigation",
            "SUB",
            "minor",
            affected=["NODE-0001"],
            applicable=2,
            structural_denominator=2,
            family="long_locator_string_atomic_assignment_threshold_only",
        )
        structure["defects"] = [copy.deepcopy(historical)]
        structure["v5_scoring_context"]["defects"] = [copy.deepcopy(historical)]
        architecture = structure["node_judgments"][0]["component_judgments"][
            "heading_access_architecture"
        ]
        architecture.update(
            status="minor_issues",
            summary="Historical atomic-threshold judgment retained as frozen history.",
            evidence_ids=[historical["defect_id"]],
        )
        structure["node_judgments"][0]["evidence_ids"] = [historical["defect_id"]]
    return locator, missing, structure


def migration_manifest(root: Path, paths: dict[str, Path]) -> Path:
    manifest_path = root / "migration-input.v7.json"
    canonical = {
        "dimension_calculation_input": {"path": paths["config"].name, "sha256": digest(paths["config"])},
        "normalized_candidate": {"path": paths["candidate"].name, "sha256": digest(paths["candidate"])},
        "item_inventory": {"path": paths["inventory"].name, "sha256": digest(paths["inventory"])},
        "v6_calculation": {"path": paths["calculation"].name, "sha256": digest(paths["calculation"])},
        "v6_evaluation_result": {"path": paths["result"].name, "sha256": digest(paths["result"])},
        "v6_item_assessments": {"path": paths["items"].name, "sha256": digest(paths["items"])},
        "v6_web_report": {"path": paths["web"].name, "sha256": digest(paths["web"])},
        "v6_projection_metadata": {"path": paths["metadata"].name, "sha256": digest(paths["metadata"])},
    }
    write_json(
        manifest_path,
        {
            "schema_version": "subject-index-v6-to-v7-migration-input-v1",
            "methodology": {
                "repository": "https://github.com/jcamden/evaluate-subject-index",
                "base_commit": "1" * 40,
                "implementation_commit": "2" * 40,
            },
            "canonical": canonical,
            "counterfactuals": [],
        },
    )
    return manifest_path


def supplemental_architecture_review(
    root: Path, paths: dict[str, Path], path_ids: list[str]
) -> Path:
    config = json.loads(paths["config"].read_text())
    structure_path = (
        paths["config"].parent / config["inputs"]["structure_audit"]["path"]
    ).resolve()
    candidate = json.loads(paths["candidate"].read_text())
    document = {
        "schema_version": "subject-index-v7-architecture-review-supplement-v1",
        "supplement_id": "",
        "evaluation_id": config["evaluation_id"],
        "audit_mode": config["audit_mode"],
        "bindings": {
            "candidate_sha256": candidate["candidate_sha256"],
            "v6_dimension_calculation_input_file_sha256": digest(
                paths["config"]
            ),
            "normalized_candidate_file_sha256": digest(paths["candidate"]),
            "item_inventory_file_sha256": digest(paths["inventory"]),
            "historical_structure_audit_file_sha256": digest(structure_path),
        },
        "review_scope": {
            "rule_id": "STRUCT-V7-EXACT-UNRESOLVED-TRIGGER-SET",
            "path_ids": sorted(path_ids),
        },
        "decisions": [
            {
                "review_id": f"ARCHREV-{path_id.removeprefix('PATH-')}",
                "path_id": path_id,
                "review_status": "reviewed_no_defect",
                "conceptually_distinguishable_treatments": False,
                "meaningful_subheadings_or_access_routes": False,
                "material_scanning_or_retrieval_impairment": False,
                "subdivision_is_conceptual_not_trivial": False,
                "evidence_ids": [path_id],
                "defect_ids": [],
            }
            for path_id in sorted(path_ids)
        ],
        "provenance": {
            "authorization_scope": "supplemental_architecture_review_only",
            "structured_architecture_evidence_only": True,
            "source_pages_reopened": False,
            "locator_support_reopened": False,
            "missing_access_reopened": False,
            "unrelated_structure_judgments_reopened": False,
            "display_prose_used_for_grouping": False,
            "historical_artifacts_modified": False,
        },
        "supplement_sha256": "",
    }
    document["supplement_id"] = (
        f"ARCHSUP-{v5.canonical_hash(document)[:12].upper()}"
    )
    document["supplement_sha256"] = v5.canonical_hash(
        document, "supplement_sha256"
    )
    path = root / "supplemental-architecture-review.v7.json"
    write_json(path, document)
    return path


class V7ScoreOnlyMigrationTests(unittest.TestCase):
    def test_full_migration_chain_is_hash_bound_and_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = prepare_v6_projection(root)
            manifest = migration_manifest(root, paths)
            frozen = {key: hashlib.sha256(path.read_bytes()).hexdigest() for key, path in paths.items()}
            first_dir = root / "v7-a"
            second_dir = root / "v7-b"
            first = run_cli(
                "dimension_score_v7_cli.py",
                "migrate-v6-to-v7",
                "--manifest",
                manifest,
                "--output-directory",
                first_dir,
            )
            second = run_cli(
                "dimension_score_v7_cli.py",
                "migrate-v6-to-v7",
                "--manifest",
                manifest,
                "--output-directory",
                second_dir,
            )
            self.assertEqual(frozen, {key: hashlib.sha256(path.read_bytes()).hexdigest() for key, path in paths.items()})
            self.assertEqual(0, first["counterfactual_view_count"])
            self.assertEqual(first["v7_total"], second["v7_total"])
            relative_files = sorted(path.relative_to(first_dir) for path in first_dir.rglob("*.json"))
            self.assertEqual(relative_files, sorted(path.relative_to(second_dir) for path in second_dir.rglob("*.json")))
            for relative in relative_files:
                self.assertEqual((first_dir / relative).read_bytes(), (second_dir / relative).read_bytes(), relative)

            calculation = json.loads((first_dir / "dimension-calculations.v7.json").read_text())
            migration = json.loads((first_dir / "score-migration.v6-to-v7.json").read_text())
            items = json.loads((first_dir / "item-assessments.v7.json").read_text())
            report = json.loads((first_dir / "web-report.v7.json").read_text())
            receipt = json.loads((first_dir / "validation-receipt.v7.json").read_text())
            self.assertEqual("subject-index-rubric-v7", calculation["rubric_version"])
            self.assertEqual("subject-index-score-migration-v6-to-v7-v1", migration["schema_version"])
            self.assertTrue(migration["gate_preservation"]["outcomes_equal"])
            self.assertFalse(migration["frozen_evidence"]["prose_inference_used"])
            self.assertEqual("subject-index-item-assessments-v4", items["schema_version"])
            for locator in items["locator_assessments"]:
                credit = locator["locator_utility"]["combined_credit"]
                expected = None if credit is None else float(credit) * 100
                self.assertEqual(expected, locator["grade"]["score"])
            for path in items["path_assessments"]:
                component = next(
                    item
                    for item in path["component_results"]
                    if item["dimension_id"] == "page_reference_reliability"
                )
                factor = next(
                    item
                    for item in path["popover"]["factors"]
                    if item["factor_id"] == "page_reference_reliability"
                )
                self.assertEqual("locator_level_only", component["measurement_status"])
                self.assertIsNone(component["score"])
                self.assertEqual("locator_level_only", factor["status"])
                self.assertIsNone(factor["score"])
            self.assertFalse(report["methodology"]["numeric_trigger_is_automatic_defect"])
            self.assertTrue(receipt["validation"]["decimal_safe_projection_validation"])

    def test_migration_refuses_candidate_grouping_hash_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = prepare_v6_projection(root)
            manifest_path = migration_manifest(root, paths)
            candidate = json.loads(paths["candidate"].read_text())
            candidate["records"][0]["original_displayed_form"] = "Changed bytes"
            write_json(paths["candidate"], candidate)
            manifest = json.loads(manifest_path.read_text())
            manifest["canonical"]["normalized_candidate"]["sha256"] = digest(paths["candidate"])
            write_json(manifest_path, manifest)
            failure = run_cli(
                "dimension_score_v7_cli.py",
                "migrate-v6-to-v7",
                "--manifest",
                manifest_path,
                "--output-directory",
                root / "v7",
                expect_ok=False,
            )
            self.assertEqual("normalized_candidate_binding_mismatch", failure["error"]["code"])

    def test_migration_refuses_fit_mapping_that_would_require_rationale_inference(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            documents = base_documents()
            documents[0]["judgments"][0].update(
                judgment="unsupported",
                treatment_class="substantive",
                error_codes=["LOC_POS"],
                severity="minor",
                rationale="Prose claims a minor relationship mismatch.",
                evidence_summary="Prose would select a favorable nonzero fit tier.",
            )
            paths = prepare_v6_projection(root, documents)
            manifest = migration_manifest(root, paths)
            failure = run_cli(
                "dimension_score_v7_cli.py",
                "migrate-v6-to-v7",
                "--manifest",
                manifest,
                "--output-directory",
                root / "v7",
                expect_ok=False,
            )
            self.assertEqual("v7_inputs_insufficient", failure["error"]["code"])
            self.assertIn(
                "ambiguous:bare_loc_pos_does_not_establish_complete_path_fit",
                json.dumps(failure["error"]["details"]),
            )
            self.assertFalse((root / "v7" / "dimension-calculations.v7.json").exists())

    def test_representation_adjusted_view_is_recalculated_from_own_inputs_and_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            canonical = prepare_v6_projection(root)
            adjusted_root = root / "adjusted"
            adjusted_root.mkdir()
            adjusted_documents = base_documents()
            adjusted_documents[0]["judgments"][0].update(
                judgment="unsupported",
                treatment_class="passing_mention",
                error_codes=[],
                severity="minor",
            )
            adjusted = prepare_v6_projection(adjusted_root, adjusted_documents)
            self.assertEqual(canonical["candidate"].read_bytes(), adjusted["candidate"].read_bytes())
            self.assertEqual(canonical["inventory"].read_bytes(), adjusted["inventory"].read_bytes())

            provenance_path = root / "representation-correction-ledger.json"
            write_json(
                provenance_path,
                {
                    "schema_version": "synthetic-representation-correction-v1",
                    "status": "frozen",
                    "candidate_interpretation_reopened": False,
                },
            )
            metadata = json.loads(canonical["metadata"].read_text())
            adjusted_calculation = json.loads(adjusted["calculation"].read_text())
            metadata["counterfactual_score_views"] = [
                {
                    "view_id": "representation_adjusted",
                    "label": "Representation adjusted",
                    "calculation": {
                        "schema_version": "subject-index-dimension-calculations-v2",
                        "artifact_path": v5.portable_relative_reference(
                            adjusted["calculation"],
                            canonical["metadata"],
                            label="V6 counterfactual calculation",
                        ),
                        "sha256": digest(adjusted["calculation"]),
                        "calculation_sha256": adjusted_calculation["calculation_sha256"],
                        "rubric_version": "subject-index-rubric-v6",
                        "calculation_profile": "subject-index-dimension-calculation-v2",
                    },
                    "provenance_artifacts": [
                        {
                            "role": "character_fidelity_correction_ledger",
                            "schema_version": "synthetic-representation-correction-v1",
                            "artifact_path": v5.portable_relative_reference(
                                provenance_path,
                                canonical["metadata"],
                                label="V6 counterfactual provenance",
                            ),
                            "sha256": digest(provenance_path),
                        }
                    ],
                }
            ]
            v6.write_json(canonical["metadata"], metadata)
            result, web = v6.build_projections(
                canonical["calculation"],
                canonical["items"],
                canonical["metadata"],
                canonical["result"],
                canonical["web"],
            )
            v6.write_json(canonical["result"], result)
            v6.write_json(canonical["web"], web)
            v6.validate_projection_artifacts(
                canonical["calculation"], canonical["result"], canonical["web"]
            )

            manifest_path = migration_manifest(root, canonical)
            manifest = json.loads(manifest_path.read_text())

            def reference(path: Path) -> dict:
                return {
                    "path": path.relative_to(root).as_posix(),
                    "sha256": digest(path),
                }

            manifest["counterfactuals"] = [
                {
                    "view_id": "representation_adjusted",
                    "dimension_calculation_input": reference(adjusted["config"]),
                    "normalized_candidate": reference(adjusted["candidate"]),
                    "item_inventory": reference(adjusted["inventory"]),
                    "v6_calculation": reference(adjusted["calculation"]),
                }
            ]
            for key, path in (
                ("v6_evaluation_result", canonical["result"]),
                ("v6_web_report", canonical["web"]),
                ("v6_projection_metadata", canonical["metadata"]),
            ):
                manifest["canonical"][key] = reference(path)
            write_json(manifest_path, manifest)

            output = root / "v7"
            response = run_cli(
                "dimension_score_v7_cli.py",
                "migrate-v6-to-v7",
                "--manifest",
                manifest_path,
                "--output-directory",
                output,
            )
            self.assertEqual(1, response["counterfactual_view_count"])
            projection = json.loads((output / "projection-metadata.v7.json").read_text())
            migrated_web = json.loads((output / "web-report.v7.json").read_text())
            migration = json.loads((output / "score-migration.v6-to-v7.json").read_text())
            receipt = json.loads((output / "validation-receipt.v7.json").read_text())
            self.assertEqual(
                ["representation_adjusted"],
                [item["view_id"] for item in projection["counterfactual_score_views"]],
            )
            self.assertEqual(
                ["canonical_as_delivered", "representation_adjusted"],
                [item["view_id"] for item in migrated_web["score_views"]["views"]],
            )
            self.assertEqual(
                ["canonical_as_delivered", "representation_adjusted"],
                [
                    item["view_id"]
                    for item in migration["to"]["score_views"]["views"]
                ],
            )
            provenance_hash = digest(provenance_path)
            self.assertEqual(
                provenance_hash,
                migrated_web["score_views"]["views"][1]["provenance_artifacts"][0]["sha256"],
            )
            self.assertTrue(
                migration["invariants"]["representation_views_recalculated_from_own_inputs"]
            )
            self.assertEqual(
                [provenance_hash],
                receipt["counterfactual_projections"][0]["provenance_sha256"],
            )

    def test_atomic_threshold_false_positive_is_removed_only_from_active_v7_projection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            documents = expanded_path_documents(
                12, historical_atomic_threshold_defect=True
            )
            candidate = grouped_candidate(documents[0], [8, 3, 1])
            paths = prepare_v6_projection(root, documents, candidate)
            manifest = migration_manifest(root, paths)
            frozen = {
                key: hashlib.sha256(path.read_bytes()).hexdigest()
                for key, path in paths.items()
            }
            old_calculation = json.loads(paths["calculation"].read_text())
            output = root / "v7"
            run_cli(
                "dimension_score_v7_cli.py",
                "migrate-v6-to-v7",
                "--manifest",
                manifest,
                "--output-directory",
                output,
            )
            self.assertEqual(
                frozen,
                {
                    key: hashlib.sha256(path.read_bytes()).hexdigest()
                    for key, path in paths.items()
                },
            )
            review = json.loads((output / "structure-locator-review.v7.json").read_text())
            path = next(item for item in review["path_reviews"] if item["path_id"] == "PATH-0001")
            self.assertEqual(3, path["displayed_locator_count"])
            self.assertEqual(12, path["atomic_assignment_count"])
            self.assertEqual(8, path["maximum_range_span"])
            self.assertEqual(
                "historical_false_positive_removed",
                path["final_architecture_disposition"],
            )
            self.assertEqual(
                ["DEFECT-ATOMIC-THRESHOLD"], path["removed_structured_defect_ids"]
            )
            new_calculation = json.loads((output / "dimension-calculations.v7.json").read_text())
            old_dimensions = {item["dimension_id"]: item for item in old_calculation["dimensions"]}
            new_dimensions = {item["dimension_id"]: item for item in new_calculation["dimensions"]}
            self.assertNotEqual(
                old_dimensions["findability_navigation"]["components"],
                new_dimensions["findability_navigation"]["components"],
            )
            self.assertEqual(
                {"passes": 2, "uninspectable": 0, "not_measured": 0},
                new_dimensions["findability_navigation"]["raw_status_counts"]["architecture"],
            )
            for dimension_id in old_dimensions:
                if dimension_id in {"page_reference_reliability", "findability_navigation"}:
                    continue
                self.assertEqual(
                    old_dimensions[dimension_id]["awarded_points"],
                    new_dimensions[dimension_id]["awarded_points"],
                    dimension_id,
                )
            migration = json.loads((output / "score-migration.v6-to-v7.json").read_text())
            findability_comparison = next(
                item
                for item in migration["dimension_comparison"]
                if item["dimension_id"] == "findability_navigation"
            )
            self.assertFalse(findability_comparison["value_identical"])
            self.assertEqual(
                "corrected_displayed_locator_unit",
                findability_comparison["change_basis"],
            )
            self.assertEqual(
                ["DEFECT-ATOMIC-THRESHOLD"],
                migration["structure_count_correction"]["removed_historical_defect_ids"],
            )
            migrated_path = next(
                item
                for item in migration["structure_count_correction"]["path_dispositions"]
                if item["path_id"] == "PATH-0001"
            )
            defect_disposition = migrated_path["historical_defect_dispositions"][0]
            self.assertEqual(
                "atomic_assignment_threshold_only",
                defect_disposition["basis_classification"],
            )
            self.assertEqual(
                "removed_from_active_projection",
                defect_disposition["active_v7_defect_disposition"],
            )
            self.assertEqual(
                {
                    "displayed_locator_count": 3,
                    "maximum_range_span": 8,
                    "atomic_assignment_count": 12,
                    "long_displayed_locator_string_review_trigger": False,
                    "long_continuous_range_review_trigger": False,
                },
                defect_disposition["corrected_metrics"],
            )
            self.assertFalse(defect_disposition["prose_used_for_mapping"])
            self.assertFalse(
                migration["structure_count_correction"]["new_defects_created_from_numeric_triggers"]
            )
            items = json.loads((output / "item-assessments.v7.json").read_text())
            rendered = json.dumps(items).lower()
            self.assertNotIn("undivided locator", rendered)
            path_item = next(
                item for item in items["path_assessments"] if item["path_id"] == "PATH-0001"
            )
            factor = next(
                item
                for item in path_item["popover"]["factors"]
                if item["factor_id"] == "locator_string_and_range_review"
            )
            self.assertIn("3 displayed locator(s)", factor["explanation"])
            self.assertIn("12 expanded atomic page assignment(s)", factor["explanation"])
            self.assertIn("longest continuous range 8 page(s)", factor["explanation"])

    def test_newly_exposed_long_string_case_requires_supplemental_review(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            documents = expanded_path_documents(7)
            paths = prepare_v6_projection(root, documents)
            manifest = migration_manifest(root, paths)
            failure = run_cli(
                "dimension_score_v7_cli.py",
                "migrate-v6-to-v7",
                "--manifest",
                manifest,
                "--output-directory",
                root / "v7",
                expect_ok=False,
            )
            self.assertEqual("v7_migration_review_incomplete", failure["error"]["code"])
            self.assertEqual(
                ["PATH-0001"],
                failure["error"]["details"]["review_required_path_ids"],
            )
            self.assertFalse((root / "v7" / "dimension-calculations.v7.json").exists())

    def test_hash_bound_supplement_resolves_exact_unreviewed_trigger_set(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            documents = expanded_path_documents(7)
            paths = prepare_v6_projection(root, documents)
            manifest_path = migration_manifest(root, paths)
            supplement_path = supplemental_architecture_review(
                root, paths, ["PATH-0001"]
            )
            manifest = json.loads(manifest_path.read_text())
            manifest["canonical"]["supplemental_architecture_review"] = {
                "path": supplement_path.name,
                "sha256": digest(supplement_path),
            }
            write_json(manifest_path, manifest)
            frozen = {
                key: hashlib.sha256(path.read_bytes()).hexdigest()
                for key, path in paths.items()
            }

            first_dir = root / "v7-a"
            second_dir = root / "v7-b"
            run_cli(
                "dimension_score_v7_cli.py",
                "migrate-v6-to-v7",
                "--manifest",
                manifest_path,
                "--output-directory",
                first_dir,
            )
            run_cli(
                "dimension_score_v7_cli.py",
                "migrate-v6-to-v7",
                "--manifest",
                manifest_path,
                "--output-directory",
                second_dir,
            )
            self.assertEqual(
                frozen,
                {
                    key: hashlib.sha256(path.read_bytes()).hexdigest()
                    for key, path in paths.items()
                },
            )
            for relative in sorted(
                path.relative_to(first_dir) for path in first_dir.rglob("*.json")
            ):
                self.assertEqual(
                    (first_dir / relative).read_bytes(),
                    (second_dir / relative).read_bytes(),
                    relative,
                )

            review = json.loads(
                (first_dir / "structure-locator-review.v7.json").read_text()
            )
            path_review = next(
                item
                for item in review["path_reviews"]
                if item["path_id"] == "PATH-0001"
            )
            self.assertEqual(
                "reviewed_no_defect",
                path_review["final_architecture_disposition"],
            )
            self.assertEqual([], review["summary"]["review_required_path_ids"])
            self.assertEqual(
                digest(supplement_path),
                review["inputs"][
                    "supplemental_architecture_review_file_sha256"
                ],
            )
            calculation = json.loads(
                (first_dir / "dimension-calculations.v7.json").read_text()
            )
            self.assertIn(
                "supplemental_architecture_review",
                [item["role"] for item in calculation["input_artifacts"]],
            )
            migration = json.loads(
                (first_dir / "score-migration.v6-to-v7.json").read_text()
            )
            self.assertTrue(
                migration["frozen_evidence"]["semantic_judgments_added"]
            )
            self.assertEqual(
                "supplemental_architecture_review_only",
                migration["frozen_evidence"]["semantic_judgment_scope"],
            )
            self.assertEqual(
                ["canonical_as_delivered"],
                [
                    item["view_id"]
                    for item in migration["frozen_evidence"][
                        "supplemental_architecture_reviews"
                    ]
                ],
            )
            receipt = json.loads(
                (first_dir / "validation-receipt.v7.json").read_text()
            )
            self.assertTrue(receipt["validation"]["supplemental_review_hash_valid"])
            self.assertTrue(receipt["validation"]["supplemental_review_scope_exact"])

    def test_supplement_refuses_incomplete_or_extra_trigger_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            documents = expanded_path_documents(7)
            paths = prepare_v6_projection(root, documents)
            manifest_path = migration_manifest(root, paths)
            supplement_path = supplemental_architecture_review(
                root, paths, ["PATH-0002"]
            )
            manifest = json.loads(manifest_path.read_text())
            manifest["canonical"]["supplemental_architecture_review"] = {
                "path": supplement_path.name,
                "sha256": digest(supplement_path),
            }
            write_json(manifest_path, manifest)
            failure = run_cli(
                "dimension_score_v7_cli.py",
                "migrate-v6-to-v7",
                "--manifest",
                manifest_path,
                "--output-directory",
                root / "v7",
                expect_ok=False,
            )
            self.assertEqual(
                "supplemental_architecture_review_scope_mismatch",
                failure["error"]["code"],
            )


if __name__ == "__main__":
    unittest.main()
