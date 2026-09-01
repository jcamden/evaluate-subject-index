from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
TESTS = ROOT / "tests"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(TESTS))

import dimension_score_cli as v5  # noqa: E402
import dimension_score_v6_cli as v6  # noqa: E402
import dimension_score_v7_cli as v7  # noqa: E402
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
    *,
    legacy_structure_defects: list[dict] | None = None,
) -> dict[str, Path]:
    locator, missing, structure = documents or base_documents()
    candidate_path = root / "candidate-index.json"
    write_json(candidate_path, candidate_document or normalized_candidate(locator))
    candidate_file_sha = digest(candidate_path)
    for document in (locator, missing):
        document["provenance"]["normalized_candidate_file_sha256"] = candidate_file_sha
    structure["provenance"]["normalized_candidate_file_sha256"] = candidate_file_sha
    config_path = calculation_files(root, locator, missing, structure)
    migration_supplement_path: Path | None = None
    if legacy_structure_defects is not None:
        structure_path = root / "structure.json"
        historical = json.loads(structure_path.read_text())
        scoring_context = historical.pop("v5_scoring_context")
        historical["schema_version"] = "structure-audit-v3"
        historical.pop("audit_mode")
        historical["defects"] = copy.deepcopy(legacy_structure_defects)
        for chapter in historical["density"]["chapter_measurements"]:
            chapter["metric_results"] = {}
            chapter["unit_fit_rating"] = 5
        canonical_locator_set_sha256 = historical["provenance"][
            "locator_audit_set_sha256"
        ]
        canonical_missing_set_sha256 = historical["provenance"][
            "missing_access_audit_set_sha256"
        ]
        historical_locator_set_sha256 = "8" * 64
        historical_missing_set_sha256 = "9" * 64
        historical["provenance"] = {
            "benchmark_sha256": historical["provenance"]["benchmark_sha256"],
            "normalized_candidate_file_sha256": historical["provenance"][
                "normalized_candidate_file_sha256"
            ],
            "item_inventory_file_sha256": historical["provenance"][
                "item_inventory_file_sha256"
            ],
            "locator_audit_set_sha256": historical_locator_set_sha256,
            "missing_access_audit_set_sha256": historical_missing_set_sha256,
        }
        write_json(structure_path, historical)
        migration_supplement_path = root / "v5-migration-supplement.json"
        write_json(
            migration_supplement_path,
            {
                "schema_version": "subject-index-v5-migration-supplement-v1",
                "evaluation_id": locator["evaluation_id"],
                "audit_mode": "full",
                "structure_audit_sha256": digest(structure_path),
                "historical_locator_audit_set_sha256": historical_locator_set_sha256,
                "historical_missing_access_audit_set_sha256": historical_missing_set_sha256,
                "locator_audit_set_sha256": canonical_locator_set_sha256,
                "missing_access_audit_set_sha256": canonical_missing_set_sha256,
                "audit_set_reconciliation_basis": "same_frozen_files_rehashed_with_subject_index_canonical_audit_set_v1",
                "scoring_context": scoring_context,
            },
        )
        config = json.loads(config_path.read_text())
        config["inputs"]["structure_audit"]["sha256"] = digest(structure_path)
        config["inputs"]["migration_supplement"] = {
            "path": migration_supplement_path.name,
            "sha256": digest(migration_supplement_path),
        }
        write_json(config_path, config)
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
    paths = {
        "config": config_path,
        "candidate": candidate_path,
        "inventory": root / "item-inventory.json",
        "structure": root / "structure.json",
        "calculation": calculation_path,
        "result": result_path,
        "items": items_path,
        "web": web_path,
        "metadata": metadata_path,
    }
    if migration_supplement_path is not None:
        paths["migration_supplement"] = migration_supplement_path
    return paths


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
    calculation = json.loads(paths["calculation"].read_text())
    write_json(
        manifest_path,
        {
            "schema_version": "subject-index-v6-to-v7-migration-input-v1",
            "methodology": {
                "repository": "https://github.com/jcamden/evaluate-subject-index",
                "base_commit": "1" * 40,
                "implementation_commit": "2" * 40,
            },
            "repository_state": {
                "evaluation_repository": "https://github.com/example/evaluation",
                "evaluation_base_commit": "3" * 40,
                "benchmark_repository": "https://github.com/example/benchmark",
                "benchmark_head_commit": "4" * 40,
                "frozen_benchmark_commit": "5" * 40,
                "frozen_benchmark_sha256": calculation["evidence_identity"][
                    "benchmark_sha256"
                ],
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


def finalize_locator_fit_supplement(document: dict) -> dict:
    document = copy.deepcopy(document)
    for decision in document["decisions"]:
        decision["decision_id"] = ""
        decision["decision_id"] = (
            f"FITDEC-{v5.canonical_hash(decision)[:12].upper()}"
        )
    document["supplement_id"] = ""
    document["supplement_sha256"] = ""
    document["supplement_id"] = (
        f"FITSUP-{v5.canonical_hash(document)[:12].upper()}"
    )
    document["supplement_sha256"] = v5.canonical_hash(
        document, "supplement_sha256"
    )
    return document


def locator_fit_supplement(
    root: Path,
    paths: dict[str, Path],
    *,
    filename: str = "locator-fit-supplement.v7.json",
    categories: dict[str, str] | None = None,
    representation_provenance: list[dict] | None = None,
) -> tuple[Path, dict, dict]:
    loaded = v7.load_v7_inputs(paths["config"])
    ledgers, missing = v5.preflight_loaded(loaded)
    if ledgers is None or missing:
        raise AssertionError(f"synthetic V6 inputs are incomplete: {missing}")
    fit_preflight = v7.locator_fit_preflight(
        ledgers,
        loaded["config"]["audit_mode"],
        legacy_defects=v7.historical_locator_fit_defects(loaded["structure"]),
    )
    identities = sorted(
        (
            {
                "role": item["role"],
                "schema_version": item["schema_version"],
                "file_sha256": item["sha256"],
            }
            for item in loaded["input_artifacts"]
        ),
        key=lambda item: (item["role"], item["file_sha256"]),
    )

    def selected(prefix: str) -> list[dict]:
        return [item for item in identities if item["role"].startswith(prefix)]

    def exact(role: str) -> dict:
        matches = [item for item in identities if item["role"] == role]
        if len(matches) != 1:
            raise AssertionError(f"expected one {role}, found {matches}")
        return matches[0]

    migration_supplements = [
        item for item in identities if item["role"] == "migration_supplement"
    ]
    provenance_bindings = sorted(
        (
            {
                "role": item["role"],
                "schema_version": item["schema_version"],
                "file_sha256": digest(item["path"]),
            }
            for item in representation_provenance or []
        ),
        key=lambda item: (item["role"], item["file_sha256"]),
    )
    old_calculation = json.loads(paths["calculation"].read_text())
    candidate = json.loads(paths["candidate"].read_text())
    categories = categories or {}
    decisions = [
        {
            "decision_id": "",
            "locator_id": item["locator_id"],
            "path_id": item["path_id"],
            "fit_category": categories.get(item["locator_id"], "material_partial_fit"),
            "evidence_ids": [item["locator_id"]],
        }
        for item in fit_preflight["unresolved_complete_path_fit"]
    ]
    document = finalize_locator_fit_supplement(
        {
            "schema_version": "subject-index-v7-locator-fit-supplement-v1",
            "supplement_id": "",
            "evaluation_id": loaded["config"]["evaluation_id"],
            "candidate_identity": {
                "candidate_id": candidate["candidate_id"],
                "candidate_sha256": candidate["candidate_sha256"],
            },
            "audit_mode": loaded["config"]["audit_mode"],
            "bindings": {
                "v6_dimension_calculation_input_file_sha256": digest(paths["config"]),
                "normalized_candidate_file_sha256": digest(paths["candidate"]),
                "item_inventory_file_sha256": digest(paths["inventory"]),
                "historical_v6_calculation_file_sha256": digest(paths["calculation"]),
                "historical_v6_calculation_sha256": old_calculation[
                    "calculation_sha256"
                ],
                "locator_audit_artifacts": selected("locator_audit["),
                "missing_access_audit_artifacts": selected(
                    "missing_access_audit["
                ),
                "historical_structure_audit": exact("structure_audit"),
                "chunk_manifest": exact("chunk_manifest"),
                "migration_supplement": (
                    migration_supplements[0] if migration_supplements else None
                ),
                "representation_correction_provenance_artifacts": provenance_bindings,
                "calculation_input_artifact_set_sha256": v5.canonical_hash(
                    {"artifacts": identities}
                ),
            },
            "scope": {
                "rule_id": "FIT-V7-EXACT-UNRESOLVED-LOCATOR-SET-V1",
                "unresolved_locator_ids": [
                    item["locator_id"]
                    for item in fit_preflight["unresolved_complete_path_fit"]
                ],
                "unresolved_set_sha256": fit_preflight["unresolved_set_sha256"],
            },
            "decisions": decisions,
            "provenance": {
                "authorization_id": "AUTH-SYNTHETIC-LOCATOR-FIT",
                "authorization_scope": "supplemental_complete_path_fit_only",
                "decision_origin": "separately_authorized_semantic_adjudication",
                "supplement_transports_authorized_decisions_only": True,
                "score_only_migration_inspected_source_pages": False,
                "score_only_migration_used_prose": False,
                "historical_artifacts_modified": False,
                "page_treatment_modified": False,
                "judgment_modified": False,
                "treatment_class_modified": False,
                "source_scope_status_modified": False,
                "defects_modified": False,
                "gates_modified": False,
                "non_fit_dimensions_modified": False,
                "numerical_fit_credit_supplied": False,
                "combined_credit_supplied": False,
                "grade_supplied": False,
                "dimension_score_supplied": False,
                "total_score_supplied": False,
            },
            "supplement_sha256": "",
        }
    )
    path = root / filename
    write_json(path, document)
    return path, fit_preflight, document


def bare_loc_pos_documents(*, count: int = 1) -> tuple[dict, dict, dict]:
    documents = base_documents()
    for judgment in documents[0]["judgments"][:count]:
        judgment.update(
            judgment="unsupported",
            treatment_class="substantive",
            error_codes=["LOC_POS"],
            severity="minor",
            rationale="Synthetic prose must never select the fit category.",
            evidence_summary="Synthetic display text is deliberately non-classifying.",
        )
    return documents


def legacy_structure_defect(
    locator_id: str,
    *,
    code: str = "STA",
    severity: str = "major",
    defect_id: str = "DEFECT-SYNTHETIC-LEGACY-FIT",
) -> dict:
    return {
        "defect_id": defect_id,
        "code": code,
        "severity": severity,
        "summary": "Synthetic historical prose is preserved but never interpreted.",
        "affected_ids": [locator_id],
    }


def legacy_fit_conflict_documents(
    *, treatment_derived: bool = False
) -> tuple[tuple[dict, dict, dict], list[dict]]:
    documents = base_documents()
    target = documents[0]["judgments"][0]
    if treatment_derived:
        target.update(
            judgment="unsupported",
            treatment_class="passing_mention",
            error_codes=[],
            severity="minor",
        )
        historical = [
            legacy_structure_defect(
                target["locator_id"], code="HED", severity="minor"
            )
        ]
    else:
        target.update(
            judgment="unsupported",
            treatment_class="substantive",
            error_codes=["CON"],
            severity="minor",
        )
        historical = [legacy_structure_defect(target["locator_id"])]
    return documents, historical


def absent_legacy_fit_conflict_documents() -> tuple[
    tuple[dict, dict, dict], list[dict]
]:
    documents, historical = legacy_fit_conflict_documents()
    documents[0]["judgments"][0]["treatment_class"] = "absent"
    return documents, historical


def counterfactual_manifest(
    root: Path,
    canonical: dict[str, Path],
    adjusted: dict[str, Path],
) -> tuple[Path, dict]:
    provenance_path = root / "representation-correction-ledger.json"
    provenance = {
        "role": "character_fidelity_correction_ledger",
        "schema_version": "synthetic-representation-correction-v1",
        "path": provenance_path,
    }
    write_json(
        provenance_path,
        {
            "schema_version": provenance["schema_version"],
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
                    "role": provenance["role"],
                    "schema_version": provenance["schema_version"],
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
    write_json(manifest_path, manifest)
    return manifest_path, provenance


class V7ScoreOnlyMigrationTests(unittest.TestCase):
    def _migrate_documents(
        self, root: Path, documents: tuple[dict, dict, dict]
    ) -> tuple[dict, dict, dict, dict]:
        paths = prepare_v6_projection(root, documents=documents)
        manifest = migration_manifest(root, paths)
        output = root / "v7"
        run_cli(
            "dimension_score_v7_cli.py",
            "migrate-v6-to-v7",
            "--manifest",
            manifest,
            "--output-directory",
            output,
        )
        return (
            json.loads((output / "dimension-calculations.v7.json").read_text()),
            json.loads((output / "item-assessments.v7.json").read_text()),
            json.loads((output / "web-report.v7.json").read_text()),
            json.loads((output / "evaluation-result.v7.json").read_text()),
        )

    def test_locator_specific_two_axis_explanations_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            documents = base_documents(subject_count=1)
            locator = documents[0]
            locator["schema_version"] = "locator-audit-v2"
            aachen = locator["judgments"][0]
            aachen.update(
                judgment="unsupported",
                treatment_class="passing_mention",
                evidence_summary=(
                    "Aachen appears only as the place where Gustavus III hoped to "
                    "welcome Louis XVI, without independent treatment of the place."
                ),
                fit_rationale=(
                    "The mention is genuinely about Aachen; the limitation concerns "
                    "depth of treatment rather than a mismatch with the heading path."
                ),
                error_codes=[],
                severity="none",
            )
            invalid_audit = copy.deepcopy(locator)
            invalid_audit["judgments"][0].pop("fit_rationale")
            with self.assertRaises(v5.CalculationError):
                v5.validate_schema_document(
                    invalid_audit,
                    "locator-audit-v2.schema.json",
                    "Divergent-axis audit without fit rationale",
                )
            empty_evidence = copy.deepcopy(locator)
            empty_evidence["judgments"][0]["evidence_summary"] = ""
            with self.assertRaises(v5.CalculationError):
                v5.validate_schema_document(
                    empty_evidence,
                    "locator-audit-v2.schema.json",
                    "Measured audit with empty evidence summary",
                )
            _, items, web, _ = self._migrate_documents(Path(temporary), documents)
            assessment = next(
                item
                for item in items["locator_assessments"]
                if item["locator_id"] == aachen["locator_id"]
            )
            explanation = assessment["locator_explanation"]
            self.assertEqual(aachen["evidence_summary"], explanation["evidence_summary"])
            self.assertEqual("weak_presence", explanation["page_treatment"]["category"])
            self.assertEqual(25, explanation["page_treatment"]["score"])
            self.assertTrue(explanation["page_treatment"]["rule_id"].startswith("T-"))
            self.assertEqual("exact_fit", explanation["complete_path_fit"]["category"])
            self.assertEqual(100, explanation["complete_path_fit"]["score"])
            self.assertEqual(aachen["fit_rationale"], explanation["complete_path_fit"]["rationale"])
            self.assertEqual("authored_locator_audit", explanation["complete_path_fit"]["rationale_source"])
            self.assertEqual("min(25, 100) = 25", explanation["combined_locator_utility"]["calculation"])
            self.assertEqual(
                explanation,
                next(
                    item
                    for item in web["locator_explanations"]
                    if item["locator_id"] == aachen["locator_id"]
                ),
            )
            visible = json.dumps({"items": items, "web": web})
            self.assertNotIn("Derived only from frozen treatment class", visible)
            self.assertNotIn("Derived only from frozen judgment", visible)

    def test_routine_perfect_fit_needs_no_duplicate_authored_prose(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            documents = base_documents(subject_count=1)
            documents[0]["schema_version"] = "locator-audit-v2"
            _, items, _, _ = self._migrate_documents(Path(temporary), documents)
            for assessment in items["locator_assessments"]:
                explanation = assessment["locator_explanation"]
                self.assertFalse(explanation["fit_rationale_required"])
                self.assertEqual(
                    "mechanical_structured_category_rule",
                    explanation["complete_path_fit"]["rationale_source"],
                )
                self.assertIn(
                    explanation["complete_path_fit"]["rule_id"],
                    explanation["complete_path_fit"]["rationale"],
                )

    def test_explanation_changes_cannot_change_scores_grades_or_gates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first_documents = base_documents(subject_count=1)
            first_documents[0]["schema_version"] = "locator-audit-v2"
            for judgment in first_documents[0]["judgments"]:
                judgment.update(
                    judgment="unsupported",
                    treatment_class="passing_mention",
                    error_codes=[],
                    severity="none",
                    fit_rationale="First public-safe fit explanation.",
                )
            second_documents = copy.deepcopy(first_documents)
            for judgment in second_documents[0]["judgments"]:
                judgment["evidence_summary"] = "A different public-safe evidence explanation."
                judgment["fit_rationale"] = "A different public-safe fit explanation."

            first = self._migrate_documents(root / "first", first_documents)
            second = self._migrate_documents(root / "second", second_documents)
            first_calculation, first_items, _, first_result = first
            second_calculation, second_items, _, second_result = second
            def calculation_snapshot(calculation: dict) -> tuple[list, list]:
                dimensions = [
                    (
                        item["dimension_id"],
                        item["status"],
                        item["base_rating"],
                        item["final_rating"],
                        item["awarded_points"],
                        item["applied_cap"],
                    )
                    for item in calculation["dimensions"]
                ]
                reliability = next(
                    item
                    for item in calculation["dimensions"]
                    if item["dimension_id"] == "page_reference_reliability"
                )["reliability_provenance"]["locator_utility_assignments"]
                categories = [
                    (
                        item["locator_id"],
                        item["treatment_category"],
                        item["treatment_score"],
                        item["fit_category"],
                        item["fit_score"],
                        item["combined_credit"],
                        item["diagnostic_grade"],
                    )
                    for item in reliability
                ]
                return dimensions, categories

            self.assertEqual(
                calculation_snapshot(first_calculation),
                calculation_snapshot(second_calculation),
            )
            self.assertEqual(first_calculation["total_score"], second_calculation["total_score"])
            self.assertEqual(first_result["critical_gates"], second_result["critical_gates"])
            self.assertEqual(first_result["total_score"], second_result["total_score"])
            grade_snapshot = lambda items: [
                (
                    item["locator_id"],
                    item["grade"],
                    item["locator_utility"]["treatment_category"],
                    item["locator_utility"]["fit_category"],
                    item["locator_utility"]["combined_credit"],
                )
                for item in items["locator_assessments"]
            ]
            self.assertEqual(grade_snapshot(first_items), grade_snapshot(second_items))

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
            self.assertEqual("subject-index-score-migration-v6-to-v7-v2", migration["schema_version"])
            self.assertEqual(
                "3" * 40,
                migration["repository_state"]["evaluation_base_commit"],
            )
            self.assertTrue(migration["gate_preservation"]["outcomes_equal"])
            self.assertFalse(migration["frozen_evidence"]["prose_inference_used"])
            self.assertEqual("subject-index-item-assessments-v5", items["schema_version"])
            self.assertEqual("subject-index-web-report-v7", report["schema_version"])
            self.assertEqual(
                [item["locator_explanation"] for item in items["locator_assessments"]],
                report["locator_explanations"],
            )
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

    def test_frozen_benchmark_binding_drift_remains_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = prepare_v6_projection(root)
            manifest_path = migration_manifest(root, paths)
            manifest = json.loads(manifest_path.read_text())
            manifest["repository_state"]["frozen_benchmark_sha256"] = "6" * 64
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
                "frozen_benchmark_identity_mismatch", failure["error"]["code"]
            )
            self.assertFalse((root / "v7" / "dimension-calculations.v7.json").exists())

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
            preflight = run_cli(
                "dimension_score_v7_cli.py",
                "preflight",
                "--input",
                paths["config"],
            )
            self.assertFalse(preflight["sufficient"])
            fit_preflight = preflight["locator_fit_preflight"]
            self.assertEqual(
                "bare_loc_pos_without_fit_cause",
                fit_preflight["unresolved_complete_path_fit"][0]["reason_code"],
            )
            self.assertNotIn(
                "rationale",
                json.dumps(fit_preflight["unresolved_complete_path_fit"]),
            )
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
            self.assertEqual("v7_locator_fit_unresolved", failure["error"]["code"])
            unresolved = failure["error"]["details"]["unresolved_complete_path_fit"]
            self.assertEqual(1, len(unresolved))
            self.assertEqual(
                "bare_loc_pos_without_fit_cause", unresolved[0]["reason_code"]
            )
            self.assertEqual("complete_path_fit_category", unresolved[0]["missing_classifier_category"])
            public_details = json.dumps(failure["error"]["details"])
            self.assertNotIn("Prose claims", public_details)
            self.assertNotIn("favorable nonzero", public_details)
            self.assertNotIn("rationale", public_details)
            self.assertFalse((root / "v7" / "dimension-calculations.v7.json").exists())

    def test_legacy_fit_conflict_routes_to_exact_scope_supplement_deterministically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            documents, historical_defects = legacy_fit_conflict_documents()
            frozen_locator = copy.deepcopy(documents[0]["judgments"][0])
            frozen_defects = copy.deepcopy(historical_defects)
            paths = prepare_v6_projection(
                root,
                documents,
                legacy_structure_defects=historical_defects,
            )
            loaded = v7.load_v7_inputs(paths["config"])
            ledgers, missing = v5.preflight_loaded(loaded)
            self.assertEqual([], missing)
            candidate = json.loads(paths["candidate"].read_text())
            inventory = json.loads(paths["inventory"].read_text())
            fit_preflight = v7.locator_fit_preflight(
                ledgers,
                loaded["config"]["audit_mode"],
                legacy_defects=v7.historical_locator_fit_defects(
                    loaded["structure"]
                ),
                candidate=candidate,
                inventory=inventory,
            )
            public_preflight = v7.public_locator_fit_preflight(fit_preflight)
            v5.validate_schema_document(
                public_preflight,
                "v7-locator-fit-preflight.schema.json",
                "Synthetic migration legacy-fit conflict preflight",
            )
            self.assertEqual(
                {
                    "deterministically_compatible": 3,
                    "unresolved_complete_path_fit": 1,
                    "invalid_or_contradictory_state": 0,
                },
                public_preflight["group_counts"],
            )
            unresolved = public_preflight["unresolved_complete_path_fit"]
            self.assertEqual([frozen_locator["locator_id"]], [item["locator_id"] for item in unresolved])
            self.assertEqual(
                {
                    "legacy_structured_fit_classification_conflict_requires_adjudication": 1
                },
                public_preflight["unresolved_reason_counts"],
            )
            self.assertEqual(
                {
                    "locator_audit": "material_mismatch",
                    "historical_structure_audit": "severe_mismatch",
                },
                {
                    item["source_artifact_role"]: item["implied_fit_category"]
                    for item in unresolved[0]["structured_classifiers"]
                },
            )
            self.assertFalse(public_preflight["aggregate_v7_score_available"])
            self.assertNotIn("total_score", public_preflight)

            manifest_path = migration_manifest(root, paths)
            failure = run_cli(
                "dimension_score_v7_cli.py",
                "migrate-v6-to-v7",
                "--manifest",
                manifest_path,
                "--output-directory",
                root / "v7-unsupplemented",
                expect_ok=False,
            )
            self.assertEqual("v7_locator_fit_unresolved", failure["error"]["code"])
            self.assertEqual(
                "legacy_structured_fit_classification_conflict_requires_adjudication",
                failure["error"]["details"]["unresolved_complete_path_fit"][0][
                    "reason_code"
                ],
            )
            self.assertNotIn(
                "invalid_or_contradictory_state",
                failure["error"]["details"],
            )

            supplement_path, supplement_preflight, supplement = locator_fit_supplement(
                root,
                paths,
                categories={frozen_locator["locator_id"]: "material_partial_fit"},
            )
            self.assertEqual(
                fit_preflight["unresolved_set_sha256"],
                supplement_preflight["unresolved_set_sha256"],
            )
            self.assertEqual(
                [frozen_locator["locator_id"]],
                supplement["scope"]["unresolved_locator_ids"],
            )

            prohibited_numerical_keys = {
                "fit_credit",
                "treatment_credit",
                "page_treatment_credit",
                "combined_credit",
                "grade",
                "dimension_score",
                "total_score",
            }

            def all_keys(value: object) -> set[str]:
                if isinstance(value, dict):
                    return set(value) | set().union(
                        *(all_keys(item) for item in value.values())
                    )
                if isinstance(value, list):
                    return set().union(*(all_keys(item) for item in value))
                return set()

            self.assertFalse(prohibited_numerical_keys & all_keys(supplement))
            manifest = json.loads(manifest_path.read_text())
            manifest["canonical"]["locator_fit_supplement"] = {
                "path": supplement_path.name,
                "sha256": digest(supplement_path),
            }
            write_json(manifest_path, manifest)
            frozen_hashes = {key: digest(path) for key, path in paths.items()}

            first_dir = root / "v7-conflict-a"
            second_dir = root / "v7-conflict-b"
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
                frozen_hashes, {key: digest(path) for key, path in paths.items()}
            )
            relative_files = sorted(
                path.relative_to(first_dir) for path in first_dir.rglob("*.json")
            )
            self.assertEqual(
                relative_files,
                sorted(path.relative_to(second_dir) for path in second_dir.rglob("*.json")),
            )
            for relative in relative_files:
                self.assertEqual(
                    (first_dir / relative).read_bytes(),
                    (second_dir / relative).read_bytes(),
                    relative,
                )

            calculation = json.loads(
                (first_dir / "dimension-calculations.v7.json").read_text()
            )
            reliability = next(
                item
                for item in calculation["dimensions"]
                if item["dimension_id"] == "page_reference_reliability"
            )
            assignment = next(
                item
                for item in reliability["reliability_provenance"][
                    "locator_utility_assignments"
                ]
                if item["locator_id"] == frozen_locator["locator_id"]
            )
            self.assertEqual("material_partial_fit", assignment["fit_category"])
            self.assertEqual("0.7", assignment["fit_score"])
            self.assertEqual("0.7", assignment["combined_credit"])
            self.assertEqual(70, assignment["diagnostic_grade"])
            self.assertEqual(
                [
                    "F-COMPAT-LEGACY-CODE-SEVERITY-ONLY-V1",
                    "F-COMPAT-LEGACY-FIT-CONFLICT-TO-SUPPLEMENT-V1",
                ],
                assignment["compatibility_rule_ids"],
            )
            invalid_calculation = copy.deepcopy(calculation)
            invalid_reliability = next(
                item
                for item in invalid_calculation["dimensions"]
                if item["dimension_id"] == "page_reference_reliability"
            )
            invalid_compatibility = next(
                item
                for item in invalid_reliability["reliability_provenance"][
                    "compatibility_classifications"
                ]
                if item["locator_id"] == frozen_locator["locator_id"]
            )
            invalid_compatibility["fit_rule_id"] = "F-SUPPLEMENTAL-EXACT-100"
            with self.assertRaises(v5.CalculationError):
                v5.validate_schema_document(
                    invalid_calculation,
                    "dimension-calculations-v3.schema.json",
                    "Synthetic mismatched conflict fit rule",
                )
            for field in (
                "judgment",
                "treatment_class",
                "source_scope_status",
                "error_codes",
            ):
                self.assertEqual(frozen_locator[field], assignment[field])

            migration = json.loads(
                (first_dir / "score-migration.v6-to-v7.json").read_text()
            )
            self.assertEqual(
                "dimension-score-cli-v7.1.0", migration["tool"]["version"]
            )
            view = migration["locator_fit_supplementation"]["views"][0]
            self.assertEqual(
                [frozen_locator["locator_id"]], view["conflict_routed_locator_ids"]
            )
            self.assertEqual(
                public_preflight["unresolved_set_sha256"],
                view["unresolved_set_sha256"],
            )
            self.assertFalse(
                migration["invariants"]["historical_fit_classifier_records_modified"]
            )
            self.assertTrue(
                migration["invariants"]["legacy_fit_conflicts_routed_without_precedence"]
            )
            self.assertFalse(
                migration["invariants"]["invalid_states_supplement_eligible"]
            )
            receipt = json.loads(
                (first_dir / "validation-receipt.v7.json").read_text()
            )
            self.assertTrue(receipt["validation"]["legacy_fit_conflict_routing_valid"])
            self.assertTrue(
                receipt["validation"]["legacy_fit_conflict_provenance_complete"]
            )
            self.assertTrue(
                receipt["validation"]["invalid_states_excluded_from_unresolved_set"]
            )
            self.assertTrue(
                receipt["validation"][
                    "aggregate_score_absent_during_preflight_and_adjudication"
                ]
            )
            self.assertEqual(frozen_locator, documents[0]["judgments"][0])
            self.assertEqual(frozen_defects, historical_defects)

    def test_absent_fit_conflict_preflight_and_migration_use_v705_schema_alignment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            documents, historical_defects = absent_legacy_fit_conflict_documents()
            frozen_locator = copy.deepcopy(documents[0]["judgments"][0])
            frozen_defects = copy.deepcopy(historical_defects)
            paths = prepare_v6_projection(
                root,
                documents,
                legacy_structure_defects=historical_defects,
            )

            command_preflight = run_cli(
                "dimension_score_v7_cli.py",
                "preflight",
                "--input",
                paths["config"],
            )
            self.assertFalse(command_preflight["sufficient"])
            self.assertFalse(command_preflight["aggregate_v7_score_available"])
            public_preflight = command_preflight["locator_fit_preflight"]
            self.assertEqual(
                {
                    "deterministically_compatible": 3,
                    "unresolved_complete_path_fit": 1,
                    "invalid_or_contradictory_state": 0,
                },
                public_preflight["group_counts"],
            )
            self.assertEqual([], public_preflight["invalid_or_contradictory_state"])
            unresolved = public_preflight["unresolved_complete_path_fit"]
            self.assertEqual(1, len(unresolved))
            self.assertEqual(frozen_locator["locator_id"], unresolved[0]["locator_id"])
            self.assertEqual(frozen_locator["path_id"], unresolved[0]["path_id"])
            self.assertEqual("unsupported", unresolved[0]["present_judgment"])
            self.assertEqual("absent", unresolved[0]["treatment_class"])
            self.assertEqual("indexable", unresolved[0]["source_scope_status"])
            self.assertEqual(
                "legacy_structured_fit_classification_conflict_requires_adjudication",
                unresolved[0]["reason_code"],
            )
            self.assertEqual(
                "F-COMPAT-LEGACY-FIT-CONFLICT-TO-SUPPLEMENT-V1",
                unresolved[0]["conflict_rule_id"],
            )
            self.assertEqual(2, len(unresolved[0]["structured_classifiers"]))
            self.assertEqual(
                public_preflight["unresolved_set_sha256"],
                v5.canonical_hash({"unresolved_locator_fit": unresolved}),
            )
            v5.validate_schema_document(
                public_preflight,
                "v7-locator-fit-preflight.schema.json",
                "Synthetic absent migration preflight",
            )

            prohibited_preflight_keys = {
                "fit_credit",
                "treatment_credit",
                "fit_score",
                "treatment_score",
                "combined_credit",
                "diagnostic_grade",
                "grade",
                "dimension_score",
                "total_score",
            }

            def all_keys(value: object) -> set[str]:
                if isinstance(value, dict):
                    return set(value) | set().union(
                        *(all_keys(item) for item in value.values())
                    )
                if isinstance(value, list):
                    return set().union(*(all_keys(item) for item in value))
                return set()

            self.assertFalse(prohibited_preflight_keys & all_keys(public_preflight))

            manifest_path = migration_manifest(root, paths)
            failure = run_cli(
                "dimension_score_v7_cli.py",
                "migrate-v6-to-v7",
                "--manifest",
                manifest_path,
                "--output-directory",
                root / "v7-unsupplemented",
                expect_ok=False,
            )
            self.assertEqual("v7_locator_fit_unresolved", failure["error"]["code"])
            self.assertNotIn(
                failure["error"]["code"],
                {"input_schema_validation_failed", "v7_inputs_insufficient"},
            )
            self.assertEqual(
                "absent",
                failure["error"]["details"]["unresolved_complete_path_fit"][0][
                    "treatment_class"
                ],
            )

            supplement_path, supplement_preflight, supplement = locator_fit_supplement(
                root,
                paths,
                categories={frozen_locator["locator_id"]: "material_partial_fit"},
            )
            self.assertEqual(
                public_preflight["unresolved_set_sha256"],
                supplement_preflight["unresolved_set_sha256"],
            )
            self.assertEqual(
                [frozen_locator["locator_id"]],
                supplement["scope"]["unresolved_locator_ids"],
            )
            self.assertEqual(1, len(supplement["decisions"]))
            self.assertEqual(
                "material_partial_fit", supplement["decisions"][0]["fit_category"]
            )
            prohibited_supplement_keys = prohibited_preflight_keys | {
                "page_treatment_credit",
                "historical_judgment",
            }
            self.assertFalse(prohibited_supplement_keys & all_keys(supplement))
            v5.validate_schema_document(
                supplement,
                "v7-locator-fit-supplement.schema.json",
                "Synthetic absent conflict supplement",
            )

            manifest = json.loads(manifest_path.read_text())
            manifest["canonical"]["locator_fit_supplement"] = {
                "path": supplement_path.name,
                "sha256": digest(supplement_path),
            }
            write_json(manifest_path, manifest)
            frozen_hashes = {key: digest(path) for key, path in paths.items()}

            first_dir = root / "v7-absent-a"
            second_dir = root / "v7-absent-b"
            for output in (first_dir, second_dir):
                run_cli(
                    "dimension_score_v7_cli.py",
                    "migrate-v6-to-v7",
                    "--manifest",
                    manifest_path,
                    "--output-directory",
                    output,
                )
            self.assertEqual(
                frozen_hashes, {key: digest(path) for key, path in paths.items()}
            )
            first_files = sorted(
                path.relative_to(first_dir)
                for path in first_dir.rglob("*")
                if path.is_file()
            )
            second_files = sorted(
                path.relative_to(second_dir)
                for path in second_dir.rglob("*")
                if path.is_file()
            )
            self.assertEqual(first_files, second_files)
            for relative in first_files:
                self.assertEqual(
                    (first_dir / relative).read_bytes(),
                    (second_dir / relative).read_bytes(),
                    relative,
                )

            calculation = json.loads(
                (first_dir / "dimension-calculations.v7.json").read_text()
            )
            reliability = next(
                item
                for item in calculation["dimensions"]
                if item["dimension_id"] == "page_reference_reliability"
            )
            assignment = next(
                item
                for item in reliability["reliability_provenance"][
                    "locator_utility_assignments"
                ]
                if item["locator_id"] == frozen_locator["locator_id"]
            )
            self.assertEqual("unsupported", assignment["judgment"])
            self.assertEqual("absent", assignment["treatment_class"])
            self.assertEqual("indexable", assignment["source_scope_status"])
            self.assertEqual(frozen_locator["error_codes"], assignment["error_codes"])
            self.assertEqual(frozen_locator["severity"], assignment["locator_severity"])
            self.assertEqual("0", assignment["treatment_score"])
            self.assertEqual("material_partial_fit", assignment["fit_category"])
            self.assertEqual("0.7", assignment["fit_score"])
            self.assertEqual("0", assignment["combined_credit"])
            self.assertEqual(0, assignment["diagnostic_grade"])
            self.assertEqual(
                min(
                    Decimal(assignment["treatment_score"]),
                    Decimal(assignment["fit_score"]),
                ),
                Decimal(assignment["combined_credit"]),
            )
            self.assertEqual(
                [
                    "F-COMPAT-LEGACY-CODE-SEVERITY-ONLY-V1",
                    "F-COMPAT-LEGACY-FIT-CONFLICT-TO-SUPPLEMENT-V1",
                ],
                assignment["compatibility_rule_ids"],
            )

            migration = json.loads(
                (first_dir / "score-migration.v6-to-v7.json").read_text()
            )
            self.assertEqual(
                "dimension-score-cli-v7.1.0", migration["tool"]["version"]
            )
            migration_view = migration["locator_fit_supplementation"]["views"][0]
            self.assertEqual(
                "absent",
                migration_view["unresolved_records_without_supplement"][0][
                    "treatment_class"
                ],
            )
            self.assertEqual(
                [frozen_locator["locator_id"]],
                migration_view["conflict_routed_locator_ids"],
            )
            receipt = json.loads(
                (first_dir / "validation-receipt.v7.json").read_text()
            )
            self.assertTrue(receipt["validation"]["all_schemas_valid"])
            self.assertTrue(
                receipt["validation"]["locator_fit_supplement_scope_exact"]
            )
            self.assertTrue(
                receipt["validation"][
                    "locator_fit_supplement_non_fit_fields_unchanged"
                ]
            )
            self.assertEqual(frozen_locator, documents[0]["judgments"][0])
            self.assertEqual(frozen_defects, historical_defects)

    def test_conflict_with_cross_artifact_path_drift_remains_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            documents, historical_defects = legacy_fit_conflict_documents()
            candidate = normalized_candidate(documents[0])
            candidate["records"][0]["path_id"] = "PATH-SYNTHETIC-DRIFT"
            paths = prepare_v6_projection(
                root,
                documents,
                candidate_document=candidate,
                legacy_structure_defects=historical_defects,
            )
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
            invalid = failure["error"]["details"]
            self.assertTrue(
                any(
                    "complete_path_identity" in error
                    for item in invalid
                    for error in item.get("state_errors", [])
                )
            )
            self.assertNotIn(
                "legacy_structured_fit_classification_conflict_requires_adjudication",
                json.dumps(invalid),
            )
            self.assertFalse((root / "v7" / "dimension-calculations.v7.json").exists())

    def test_conflict_supplement_identity_drift_remains_ineligible(self) -> None:
        cases = {
            "evaluation": "locator_fit_supplement_identity_mismatch",
            "candidate": "locator_fit_supplement_identity_mismatch",
            "audit_mode": "locator_fit_supplement_identity_mismatch",
            "locator": "locator_fit_supplement_scope_mismatch",
            "path": "locator_fit_supplement_override_forbidden",
        }
        for case, expected_code in cases.items():
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                documents, historical_defects = legacy_fit_conflict_documents()
                paths = prepare_v6_projection(
                    root,
                    documents,
                    legacy_structure_defects=historical_defects,
                )
                manifest_path = migration_manifest(root, paths)
                supplement_path, _, supplement = locator_fit_supplement(
                    root, paths
                )
                if case == "evaluation":
                    supplement["evaluation_id"] = "eval-synthetic-drift"
                elif case == "candidate":
                    supplement["candidate_identity"]["candidate_sha256"] = "7" * 64
                elif case == "audit_mode":
                    supplement["audit_mode"] = "pilot"
                elif case == "locator":
                    supplement["decisions"][0]["locator_id"] = "LOC-SYNTHETIC-DRIFT"
                else:
                    supplement["decisions"][0]["path_id"] = "PATH-0002"
                supplement = finalize_locator_fit_supplement(supplement)
                write_json(supplement_path, supplement)
                manifest = json.loads(manifest_path.read_text())
                manifest["canonical"]["locator_fit_supplement"] = {
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
                self.assertEqual(expected_code, failure["error"]["code"])
                self.assertFalse(
                    (root / "v7" / "dimension-calculations.v7.json").exists()
                )

    def test_hash_bound_locator_fit_supplement_resolves_exact_set_in_memory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            documents = bare_loc_pos_documents()
            frozen_locator = copy.deepcopy(documents[0]["judgments"][0])
            paths = prepare_v6_projection(root, documents)
            manifest_path = migration_manifest(root, paths)
            supplement_path, preflight, supplement = locator_fit_supplement(
                root, paths
            )
            manifest = json.loads(manifest_path.read_text())
            manifest["canonical"]["locator_fit_supplement"] = {
                "path": supplement_path.name,
                "sha256": digest(supplement_path),
            }
            write_json(manifest_path, manifest)
            frozen_hashes = {
                key: digest(path) for key, path in paths.items()
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
                frozen_hashes, {key: digest(path) for key, path in paths.items()}
            )
            relative_files = sorted(
                path.relative_to(first_dir) for path in first_dir.rglob("*.json")
            )
            for relative in relative_files:
                self.assertEqual(
                    (first_dir / relative).read_bytes(),
                    (second_dir / relative).read_bytes(),
                    relative,
                )

            calculation = json.loads(
                (first_dir / "dimension-calculations.v7.json").read_text()
            )
            reliability = next(
                item
                for item in calculation["dimensions"]
                if item["dimension_id"] == "page_reference_reliability"
            )
            assignment = next(
                item
                for item in reliability["reliability_provenance"][
                    "locator_utility_assignments"
                ]
                if item["locator_id"] == frozen_locator["locator_id"]
            )
            self.assertEqual("1", assignment["treatment_score"])
            self.assertEqual("0.7", assignment["fit_score"])
            self.assertEqual("0.7", assignment["combined_credit"])
            self.assertEqual(70, assignment["diagnostic_grade"])
            self.assertEqual(
                "supplemental_locator_fit", assignment["fit_classification_source"]
            )
            for field in (
                "judgment",
                "treatment_class",
                "source_scope_status",
                "error_codes",
            ):
                self.assertEqual(frozen_locator[field], assignment[field])
            self.assertEqual(
                len(preflight["unresolved_complete_path_fit"]),
                calculation["locator_fit_compatibility"][
                    "unresolved_before_supplement"
                ],
            )
            self.assertEqual(
                0,
                calculation["locator_fit_compatibility"][
                    "unresolved_after_supplement"
                ],
            )
            self.assertEqual(
                supplement["supplement_sha256"],
                calculation["locator_fit_supplement"]["supplement_sha256"],
            )

            items = json.loads(
                (first_dir / "item-assessments.v7.json").read_text()
            )
            migration = json.loads(
                (first_dir / "score-migration.v6-to-v7.json").read_text()
            )
            result = json.loads(
                (first_dir / "evaluation-result.v7.json").read_text()
            )
            web = json.loads((first_dir / "web-report.v7.json").read_text())
            metadata = json.loads(
                (first_dir / "projection-metadata.v7.json").read_text()
            )
            receipt = json.loads(
                (first_dir / "validation-receipt.v7.json").read_text()
            )
            self.assertEqual(
                supplement["supplement_id"],
                items["locator_fit_supplement"]["supplement_id"],
            )
            self.assertEqual(
                supplement["supplement_id"],
                result["locator_fit_supplement"]["supplement_id"],
            )
            self.assertEqual(
                supplement["supplement_id"],
                web["locator_fit_supplement"]["supplement_id"],
            )
            self.assertEqual(
                supplement["supplement_id"],
                metadata["canonical_locator_fit_supplement"]["supplement_id"],
            )
            supplementation = migration["locator_fit_supplementation"]
            self.assertTrue(supplementation["supplemental_judgments_added"])
            self.assertEqual("complete_path_fit_only", supplementation["scope"])
            self.assertEqual(1, supplementation["views"][0]["unresolved_set_count_before_supplementation"])
            self.assertEqual(0, supplementation["views"][0]["unresolved_set_count_after_supplementation"])
            self.assertTrue(supplementation["historical_artifacts_unchanged"])
            self.assertTrue(supplementation["non_fit_judgments_unchanged"])
            self.assertFalse(supplementation["numerical_fit_credit_manually_supplied"])
            self.assertEqual(
                "supplemental_locator_fit_only",
                migration["frozen_evidence"]["semantic_judgment_scope"],
            )
            self.assertEqual(
                supplement["supplement_id"],
                receipt["supplemental_locator_fit_supplements"][0]["artifact"][
                    "supplement_id"
                ],
            )
            self.assertTrue(receipt["validation"]["locator_fit_supplement_hash_valid"])
            self.assertTrue(receipt["validation"]["locator_fit_supplement_scope_exact"])
            self.assertEqual(
                supplement["supplement_sha256"],
                v5.canonical_hash(supplement, "supplement_sha256"),
            )
            self.assertEqual(
                calculation["calculation_sha256"],
                v5.canonical_hash(calculation, "calculation_sha256"),
            )
            self.assertEqual(
                migration["migration_sha256"],
                v5.canonical_hash(migration, "migration_sha256"),
            )
            self.assertEqual(
                receipt["receipt_sha256"],
                v5.canonical_hash(receipt, "receipt_sha256"),
            )

    def test_locator_fit_supplement_exact_set_and_order_failures(self) -> None:
        cases = ("missing", "extra", "duplicate", "reordered", "path", "deterministic")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                documents = bare_loc_pos_documents(count=2)
                paths = prepare_v6_projection(root, documents)
                manifest_path = migration_manifest(root, paths)
                supplement_path, preflight, supplement = locator_fit_supplement(
                    root, paths
                )
                self.assertEqual(2, len(preflight["unresolved_complete_path_fit"]))
                deterministic = next(
                    item
                    for item in documents[0]["judgments"]
                    if item["locator_id"]
                    not in supplement["scope"]["unresolved_locator_ids"]
                )
                if case == "missing":
                    supplement["decisions"] = supplement["decisions"][:-1]
                elif case == "extra":
                    supplement["decisions"].append(
                        {
                            "decision_id": "",
                            "locator_id": "LOC-EXTRA-SYNTHETIC",
                            "path_id": supplement["decisions"][0]["path_id"],
                            "fit_category": "exact_fit",
                            "evidence_ids": [supplement["decisions"][0]["path_id"]],
                        }
                    )
                elif case == "duplicate":
                    duplicate = copy.deepcopy(supplement["decisions"][0])
                    duplicate["fit_category"] = "no_fit"
                    supplement["decisions"].insert(1, duplicate)
                elif case == "reordered":
                    supplement["decisions"].reverse()
                elif case == "path":
                    supplement["decisions"][0]["path_id"] = deterministic[
                        "path_id"
                    ]
                else:
                    supplement["decisions"].append(
                        {
                            "decision_id": "",
                            "locator_id": deterministic["locator_id"],
                            "path_id": deterministic["path_id"],
                            "fit_category": "exact_fit",
                            "evidence_ids": [deterministic["locator_id"]],
                        }
                    )
                    supplement["decisions"].sort(
                        key=lambda item: item["locator_id"]
                    )
                supplement = finalize_locator_fit_supplement(supplement)
                write_json(supplement_path, supplement)
                manifest = json.loads(manifest_path.read_text())
                manifest["canonical"]["locator_fit_supplement"] = {
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
                expected = (
                    "locator_fit_supplement_decision_order_invalid"
                    if case in {"duplicate", "reordered"}
                    else "locator_fit_supplement_override_forbidden"
                    if case == "path"
                    else "locator_fit_supplement_scope_mismatch"
                )
                self.assertEqual(expected, failure["error"]["code"])

    def test_locator_fit_supplement_schema_rejects_manual_numerical_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = prepare_v6_projection(root, bare_loc_pos_documents())
            _, _, supplement = locator_fit_supplement(root, paths)
            for field in (
                "fit_credit",
                "page_treatment_credit",
                "combined_credit",
                "grade",
                "dimension_score",
                "total_score",
            ):
                with self.subTest(field=field):
                    invalid = copy.deepcopy(supplement)
                    invalid["decisions"][0][field] = 1
                    invalid = finalize_locator_fit_supplement(invalid)
                    with self.assertRaises(v5.CalculationError):
                        v5.validate_schema_document(
                            invalid,
                            "v7-locator-fit-supplement.schema.json",
                            "Synthetic invalid locator-fit supplement",
                        )

    def test_new_fit_supplement_requires_public_rationale_or_validated_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = prepare_v6_projection(root, documents=bare_loc_pos_documents())
            supplement_path, _, supplement = locator_fit_supplement(root, paths)
            supplement["schema_version"] = "subject-index-v7-locator-fit-supplement-v2"
            supplement["rationale_ledgers"] = []
            for decision in supplement["decisions"]:
                decision["public_safe_rationale"] = (
                    "The complete heading path is only partly supported by the frozen "
                    "structured adjudication."
                )
            supplement = finalize_locator_fit_supplement(supplement)
            write_json(supplement_path, supplement)
            v5.validate_schema_document(
                supplement,
                "v7-locator-fit-supplement-v2.schema.json",
                "Synthetic V2 locator-fit supplement",
            )
            resolved = v7._resolve_locator_fit_rationales(
                supplement, supplement_path
            )
            self.assertEqual(
                "authored_supplement",
                next(iter(resolved.values()))["source"],
            )
            manifest_path = migration_manifest(root, paths)
            manifest = json.loads(manifest_path.read_text())
            manifest["canonical"]["locator_fit_supplement"] = {
                "path": supplement_path.name,
                "sha256": digest(supplement_path),
            }
            write_json(manifest_path, manifest)
            output = root / "v7-with-rationale"
            run_cli(
                "dimension_score_v7_cli.py",
                "migrate-v6-to-v7",
                "--manifest",
                manifest_path,
                "--output-directory",
                output,
            )
            items = json.loads((output / "item-assessments.v7.json").read_text())
            projected = next(
                item["locator_explanation"]
                for item in items["locator_assessments"]
                if item["locator_id"] == supplement["decisions"][0]["locator_id"]
            )
            self.assertEqual(
                supplement["decisions"][0]["public_safe_rationale"],
                projected["complete_path_fit"]["rationale"],
            )
            self.assertEqual(
                "authored_supplement",
                projected["complete_path_fit"]["rationale_source"],
            )

            invalid = copy.deepcopy(supplement)
            invalid["decisions"][0].pop("public_safe_rationale")
            invalid = finalize_locator_fit_supplement(invalid)
            with self.assertRaises(v5.CalculationError):
                v5.validate_schema_document(
                    invalid,
                    "v7-locator-fit-supplement-v2.schema.json",
                    "Synthetic V2 supplement without rationale",
                )

    def test_fit_supplement_resolves_hash_bound_rationale_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = prepare_v6_projection(root, documents=bare_loc_pos_documents())
            supplement_path, _, supplement = locator_fit_supplement(root, paths)
            decision = supplement["decisions"][0]
            rationale = {
                "rationale_id": "FITRAT-000000000001",
                "locator_id": decision["locator_id"],
                "path_id": decision["path_id"],
                "public_safe_rationale": "The adjudicated treatment only partly fits the complete path.",
                "evidence_ids": decision["evidence_ids"],
                "rationale_sha256": "",
            }
            rationale["rationale_sha256"] = v5.canonical_hash(
                rationale, "rationale_sha256"
            )
            ledger = {
                "schema_version": "subject-index-v7-locator-fit-rationale-ledger-v1",
                "ledger_id": "FITRATLED-000000000001",
                "evaluation_id": supplement["evaluation_id"],
                "candidate_identity": supplement["candidate_identity"],
                "audit_mode": supplement["audit_mode"],
                "records": [rationale],
                "ledger_sha256": "",
            }
            ledger["ledger_sha256"] = v5.canonical_hash(
                ledger, "ledger_sha256"
            )
            ledger_path = root / "fit-rationale-ledger.v7.json"
            write_json(ledger_path, ledger)
            supplement["schema_version"] = "subject-index-v7-locator-fit-supplement-v2"
            supplement["rationale_ledgers"] = [
                {
                    "schema_version": ledger["schema_version"],
                    "artifact_path": ledger_path.name,
                    "file_sha256": digest(ledger_path),
                    "ledger_id": ledger["ledger_id"],
                    "ledger_sha256": ledger["ledger_sha256"],
                }
            ]
            for record in supplement["decisions"]:
                record["rationale_reference"] = {
                    "ledger_id": ledger["ledger_id"],
                    "ledger_sha256": ledger["ledger_sha256"],
                    "rationale_id": rationale["rationale_id"],
                    "rationale_sha256": rationale["rationale_sha256"],
                }
            supplement = finalize_locator_fit_supplement(supplement)
            write_json(supplement_path, supplement)
            loaded = v7._load_locator_fit_supplement(
                supplement_path, label="Synthetic ledger-referenced supplement"
            )
            resolved = v7._resolve_locator_fit_rationales(
                loaded, supplement_path
            )
            self.assertEqual(
                {
                    "rationale": rationale["public_safe_rationale"],
                    "source": "validated_rationale_ledger",
                },
                resolved[decision["locator_id"]],
            )
            for field, value in (
                ("judgment", "supported"),
                ("treatment_class", "substantive"),
                ("source_scope_status", "indexable"),
                ("error_codes", ["CON"]),
                ("severity", "minor"),
                ("defects", []),
                ("historical_artifacts", []),
                ("gates", []),
                ("page_treatment", "substantive"),
                ("rationale", "Prose cannot classify fit."),
            ):
                with self.subTest(field=field):
                    invalid = copy.deepcopy(supplement)
                    invalid["decisions"][0][field] = value
                    invalid = finalize_locator_fit_supplement(invalid)
                    with self.assertRaises(v5.CalculationError):
                        v5.validate_schema_document(
                            invalid,
                            "v7-locator-fit-supplement.schema.json",
                            "Synthetic non-fit override attempt",
                        )

    def test_locator_fit_supplement_rejects_out_of_scope_evidence_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = prepare_v6_projection(root, bare_loc_pos_documents())
            manifest_path = migration_manifest(root, paths)
            supplement_path, _, supplement = locator_fit_supplement(root, paths)
            supplement["decisions"][0]["evidence_ids"] = [
                "LOC-OUTSIDE-AFFECTED-PATH"
            ]
            supplement = finalize_locator_fit_supplement(supplement)
            write_json(supplement_path, supplement)
            manifest = json.loads(manifest_path.read_text())
            manifest["canonical"]["locator_fit_supplement"] = {
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
                "locator_fit_supplement_evidence_scope_mismatch",
                failure["error"]["code"],
            )

    def test_migration_paths_aliases_and_substitution_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as outside_temporary:
            root = Path(temporary)
            outside = Path(outside_temporary)
            paths = prepare_v6_projection(root, bare_loc_pos_documents())
            manifest_path = migration_manifest(root, paths)
            supplement_path, preflight, supplement = locator_fit_supplement(
                root, paths
            )

            for case in ("absolute", "traversal", "symlink_escape"):
                with self.subTest(case=case):
                    manifest = json.loads(manifest_path.read_text())
                    if case == "absolute":
                        manifest["canonical"]["normalized_candidate"]["path"] = str(
                            paths["candidate"].resolve()
                        )
                    elif case == "traversal":
                        manifest["canonical"]["normalized_candidate"]["path"] = (
                            "../candidate-index.json"
                        )
                    else:
                        escaped = outside / "candidate-index.json"
                        escaped.write_bytes(paths["candidate"].read_bytes())
                        link = root / "escaped-candidate.json"
                        link.symlink_to(escaped)
                        manifest["canonical"]["normalized_candidate"] = {
                            "path": link.name,
                            "sha256": digest(escaped),
                        }
                    write_json(manifest_path, manifest)
                    failure = run_cli(
                        "dimension_score_v7_cli.py",
                        "migrate-v6-to-v7",
                        "--manifest",
                        manifest_path,
                        "--output-directory",
                        root / f"v7-{case}",
                        expect_ok=False,
                    )
                    self.assertIn(
                        failure["error"]["code"],
                        {
                            "input_schema_validation_failed",
                            "nonportable_artifact_path",
                            "migration_input_artifact_escape",
                        },
                    )
                    manifest_path = migration_manifest(root, paths)

            manifest = json.loads(manifest_path.read_text())
            manifest["canonical"]["locator_fit_supplement"] = {
                "path": supplement_path.name,
                "sha256": digest(supplement_path),
            }
            write_json(manifest_path, manifest)
            substituted = copy.deepcopy(supplement)
            substituted["provenance"]["authorization_id"] = "AUTH-SUBSTITUTED"
            substituted = finalize_locator_fit_supplement(substituted)
            write_json(supplement_path, substituted)
            failure = run_cli(
                "dimension_score_v7_cli.py",
                "migrate-v6-to-v7",
                "--manifest",
                manifest_path,
                "--output-directory",
                root / "v7-substitution",
                expect_ok=False,
            )
            self.assertEqual("input_hash_mismatch", failure["error"]["code"])

            loaded = v7.load_v7_inputs(paths["config"])
            ledgers, missing = v5.preflight_loaded(loaded)
            self.assertIsNotNone(ledgers)
            self.assertFalse(missing)
            candidate = json.loads(paths["candidate"].read_text())
            inventory = json.loads(paths["inventory"].read_text())
            old_calculation = json.loads(paths["calculation"].read_text())
            hard_link = root / "hard-link-alias.json"
            hard_link.hardlink_to(paths["config"])
            with self.assertRaises(v5.CalculationError) as raised:
                v7._validate_locator_fit_supplement(
                    supplement,
                    supplement_path=hard_link,
                    loaded=loaded,
                    config_path=paths["config"],
                    candidate=candidate,
                    candidate_path=paths["candidate"],
                    inventory=inventory,
                    inventory_path=paths["inventory"],
                    old_calculation=old_calculation,
                    old_calculation_path=paths["calculation"],
                    fit_preflight=preflight,
                    representation_provenance_artifacts=[],
                )
            self.assertEqual(
                "locator_fit_supplement_aliases_historical_artifact",
                raised.exception.code,
            )

    def test_pre_v703_v7_artifact_shapes_remain_schema_valid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = prepare_v6_projection(root)
            manifest = migration_manifest(root, paths)
            output = root / "v7"
            run_cli(
                "dimension_score_v7_cli.py",
                "migrate-v6-to-v7",
                "--manifest",
                manifest,
                "--output-directory",
                output,
            )
            calculation = json.loads(
                (output / "dimension-calculations.v7.json").read_text()
            )
            calculation.pop("locator_fit_compatibility", None)
            calculation.pop("locator_fit_supplement", None)
            reliability = next(
                item
                for item in calculation["dimensions"]
                if item["dimension_id"] == "page_reference_reliability"
            )
            reliability["reliability_provenance"].pop(
                "compatibility_classifications", None
            )
            reliability["reliability_provenance"].pop(
                "supplemental_fit_decision_count", None
            )
            for assignment in reliability["reliability_provenance"][
                "locator_utility_assignments"
            ]:
                for field in (
                    "fit_classification_source",
                    "compatibility_rule_ids",
                    "supplemental_fit_decision_id",
                    "supplemental_fit_evidence_ids",
                ):
                    assignment.pop(field, None)
            calculation["calculation_sha256"] = v5.canonical_hash(
                calculation, "calculation_sha256"
            )

            items = json.loads((output / "item-assessments.v7.json").read_text())
            result = json.loads((output / "evaluation-result.v7.json").read_text())
            web = json.loads((output / "web-report.v7.json").read_text())
            for document in (items, result, web):
                document.pop("locator_fit_compatibility", None)
                document.pop("locator_fit_supplement", None)
            metadata = json.loads(
                (output / "projection-metadata.v7.json").read_text()
            )
            migration = json.loads(
                (output / "score-migration.v6-to-v7.json").read_text()
            )
            historical_schema_versions = {
                "subject-index-dimension-calculations-v4": "subject-index-dimension-calculations-v3",
                "subject-index-item-assessments-v5": "subject-index-item-assessments-v4",
                "subject-index-evaluation-result-v9": "subject-index-evaluation-result-v8",
                "subject-index-web-report-v7": "subject-index-web-report-v6",
                "subject-index-v7-projection-metadata-v2": "subject-index-v7-projection-metadata-v1",
                "subject-index-score-migration-v6-to-v7-v2": "subject-index-score-migration-v6-to-v7-v1",
                "subject-index-score-migration-v6-to-v7-validation-v2": "subject-index-score-migration-v6-to-v7-validation-v1",
            }

            def historicalize(value: object) -> None:
                if isinstance(value, dict):
                    if value.get("schema_version") in historical_schema_versions:
                        value["schema_version"] = historical_schema_versions[
                            value["schema_version"]
                        ]
                    for nested in value.values():
                        historicalize(nested)
                elif isinstance(value, list):
                    for nested in value:
                        historicalize(nested)

            for document in (calculation, items, result, web, metadata, migration):
                historicalize(document)
            calculation["migration_context"]["migration_schema_version"] = (
                "subject-index-score-migration-v6-to-v7-v1"
            )
            items.pop("explanation_contract", None)
            for locator in items["locator_assessments"]:
                locator.pop("locator_explanation", None)
            web.pop("locator_explanations", None)
            for historical_version in (
                "dimension-score-cli-v7.0.3",
                "dimension-score-cli-v7.0.4",
                "dimension-score-cli-v7.0.5",
                "dimension-score-cli-v7.0.6",
            ):
                historical_migration = copy.deepcopy(migration)
                historical_migration["tool"]["version"] = historical_version
                historical_migration["migration_sha256"] = v5.canonical_hash(
                    historical_migration, "migration_sha256"
                )
                v5.validate_schema_document(
                    historical_migration,
                    "score-migration-v6-to-v7.schema.json",
                    f"Synthetic {historical_version} migration contract",
                )
            migration["tool"]["version"] = "dimension-score-cli-v7.0.2"
            migration.pop("locator_fit_supplementation", None)
            migration["frozen_evidence"].pop(
                "supplemental_locator_fit_supplements", None
            )
            for field in (
                "locator_fit_supplement_applied_in_memory_only",
                "legacy_fit_conflict_rule_id",
                "legacy_fit_conflicts_routed_without_precedence",
                "historical_fit_classifier_records_modified",
                "invalid_states_supplement_eligible",
                "bare_loc_pos_automatically_mapped",
                "evaluation_specific_fit_rule_added",
                "evaluation_result_used_as_target",
            ):
                migration["invariants"].pop(field, None)
            migration["migration_sha256"] = v5.canonical_hash(
                migration, "migration_sha256"
            )
            receipt = json.loads(
                (output / "validation-receipt.v7.json").read_text()
            )
            historicalize(receipt)
            receipt.pop("supplemental_locator_fit_supplements", None)
            for field in (
                "locator_fit_supplement_hash_valid",
                "locator_fit_supplement_scope_exact",
                "locator_fit_supplement_non_fit_fields_unchanged",
                "locator_fit_supplement_contains_no_manual_numerical_credit_or_score",
                "legacy_fit_conflict_routing_valid",
                "legacy_fit_conflict_provenance_complete",
                "invalid_states_excluded_from_unresolved_set",
                "aggregate_score_absent_during_preflight_and_adjudication",
            ):
                receipt["validation"].pop(field, None)
            receipt["receipt_sha256"] = v5.canonical_hash(
                receipt, "receipt_sha256"
            )

            for document, schema in (
                (calculation, "dimension-calculations-v3.schema.json"),
                (items, "item-assessments-v4.schema.json"),
                (result, "evaluation-result-v8.schema.json"),
                (web, "web-report-v6.schema.json"),
                (metadata, "v7-projection-metadata.schema.json"),
                (migration, "score-migration-v6-to-v7.schema.json"),
                (receipt, "score-migration-v6-to-v7-validation.schema.json"),
            ):
                with self.subTest(schema=schema):
                    v5.validate_schema_document(
                        document, schema, f"Synthetic pre-v7.0.3 {schema}"
                    )
                    self.assertEqual(
                        v7.validate_v7_artifact_compatibility(
                            document, label=f"Compatibility reader {schema}"
                        ),
                        schema,
                    )

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

    def test_canonical_and_counterfactual_fit_supplements_are_independently_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            canonical = prepare_v6_projection(root, bare_loc_pos_documents())
            adjusted_root = root / "adjusted"
            adjusted_root.mkdir()
            adjusted_documents = bare_loc_pos_documents()
            adjusted_documents[0]["judgments"][0]["treatment_class"] = "mixed"
            adjusted = prepare_v6_projection(adjusted_root, adjusted_documents)
            manifest_path, provenance = counterfactual_manifest(
                root, canonical, adjusted
            )
            canonical_supplement, _, canonical_document = locator_fit_supplement(
                root,
                canonical,
                filename="canonical-locator-fit-supplement.v7.json",
            )
            adjusted_supplement, _, adjusted_document = locator_fit_supplement(
                root,
                adjusted,
                filename="adjusted-locator-fit-supplement.v7.json",
                representation_provenance=[provenance],
            )
            self.assertNotEqual(
                canonical_document["bindings"], adjusted_document["bindings"]
            )
            manifest = json.loads(manifest_path.read_text())
            manifest["canonical"]["locator_fit_supplement"] = {
                "path": canonical_supplement.relative_to(root).as_posix(),
                "sha256": digest(canonical_supplement),
            }
            manifest["counterfactuals"][0]["locator_fit_supplement"] = {
                "path": canonical_supplement.relative_to(root).as_posix(),
                "sha256": digest(canonical_supplement),
            }
            write_json(manifest_path, manifest)
            failure = run_cli(
                "dimension_score_v7_cli.py",
                "migrate-v6-to-v7",
                "--manifest",
                manifest_path,
                "--output-directory",
                root / "v7-cross-view-reuse",
                expect_ok=False,
            )
            self.assertEqual(
                "locator_fit_supplement_binding_mismatch",
                failure["error"]["code"],
            )

            manifest["counterfactuals"][0]["locator_fit_supplement"] = {
                "path": adjusted_supplement.relative_to(root).as_posix(),
                "sha256": digest(adjusted_supplement),
            }
            write_json(manifest_path, manifest)
            output = root / "v7-independent"
            response = run_cli(
                "dimension_score_v7_cli.py",
                "migrate-v6-to-v7",
                "--manifest",
                manifest_path,
                "--output-directory",
                output,
            )
            self.assertEqual(1, response["counterfactual_view_count"])
            migration = json.loads(
                (output / "score-migration.v6-to-v7.json").read_text()
            )
            refs = migration["frozen_evidence"][
                "supplemental_locator_fit_supplements"
            ]
            self.assertEqual(
                ["canonical_as_delivered", "representation_adjusted"],
                [item["view_id"] for item in refs],
            )
            self.assertEqual(
                [
                    canonical_document["supplement_id"],
                    adjusted_document["supplement_id"],
                ],
                [item["artifact"]["supplement_id"] for item in refs],
            )
            web = json.loads((output / "web-report.v7.json").read_text())
            counterfactual = web["score_views"]["views"][1]
            self.assertEqual(
                adjusted_document["supplement_id"],
                counterfactual["locator_fit_supplement"]["supplement_id"],
            )
            self.assertEqual(
                "separate_evidentiary_correction_not_methodology_effect",
                counterfactual["causal_attribution"],
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
