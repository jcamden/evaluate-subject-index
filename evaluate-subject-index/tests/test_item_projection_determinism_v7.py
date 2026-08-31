from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
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
import item_grade_cli as item_grades  # noqa: E402
from test_dimension_scoring_v5 import (  # noqa: E402
    base_documents,
    calculation_files,
    defect,
    digest,
    write_json,
)
from test_score_migration_v7 import (  # noqa: E402
    migration_manifest,
    normalized_candidate,
)


FIXTURE_PATH = TESTS / "v7-item-projection-multidefect.fixture.json"
HASH_SEEDS = (1, 2, 3, 5, 8, 13)


def load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def fixture_documents() -> tuple[dict, dict, dict]:
    locator, missing, structure = base_documents(subject_count=1)
    records = []
    for spec in load_fixture()["defects"]:
        records.append(
            defect(
                spec["defect_id"],
                spec["dimension_owner"],
                spec["code"],
                spec["severity"],
                kind=spec["defect_kind"],
                affected=list(spec["affected_item_ids"]),
                applicable=spec["applicable_count"],
                structural_denominator=2,
                family="synthetic-multidefect-ordering",
            )
        )
    structure["defects"] = copy.deepcopy(records)
    structure["v5_scoring_context"]["defects"] = copy.deepcopy(records)
    return locator, missing, structure


def run_cli_with_seed(script: str, seed: int, *arguments: object) -> dict:
    environment = os.environ.copy()
    environment["PYTHONHASHSEED"] = str(seed)
    completed = subprocess.run(
        [sys.executable, str(SCRIPTS / script), *map(str, arguments)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env=environment,
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"{script} emitted no JSON under PYTHONHASHSEED={seed}\n"
            f"stdout={completed.stdout}\nstderr={completed.stderr}"
        ) from exc
    if completed.returncode != 0 or payload.get("ok") is not True:
        raise AssertionError(
            f"{script} failed under PYTHONHASHSEED={seed}\n"
            f"stdout={completed.stdout}\nstderr={completed.stderr}"
        )
    return payload


def materialize_inputs(root: Path) -> dict[str, Path]:
    root.mkdir(parents=True, exist_ok=False)
    locator, missing, structure = fixture_documents()
    candidate_path = root / "candidate-index.json"
    write_json(candidate_path, normalized_candidate(locator))
    candidate_file_sha256 = digest(candidate_path)
    for document in (locator, missing):
        document["provenance"]["normalized_candidate_file_sha256"] = (
            candidate_file_sha256
        )
    structure["provenance"]["normalized_candidate_file_sha256"] = (
        candidate_file_sha256
    )
    config_path = calculation_files(root, locator, missing, structure)
    return {
        "config": config_path,
        "candidate": candidate_path,
        "inventory": root / "item-inventory.json",
        "locator": root / "locator.json",
        "missing": root / "missing.json",
        "structure": root / "structure.json",
    }


def build_v6_items(paths: dict[str, Path], output: Path, seed: int) -> dict:
    return run_cli_with_seed(
        "item_grade_cli.py",
        seed,
        "build-assessments",
        "--candidate",
        paths["candidate"],
        "--inventory",
        paths["inventory"],
        "--locator-audit",
        paths["locator"],
        "--missing-access-audit",
        paths["missing"],
        "--structure-audit",
        paths["structure"],
        "--audit-mode",
        "full",
        "--evaluation-id",
        "eval-v5",
        "--grading-policy",
        item_grades.V6_GRADING_POLICY,
        "--output",
        output,
    )


def prepare_v6_projection(root: Path, seed: int) -> dict[str, Path]:
    paths = materialize_inputs(root)
    calculation = v6.calculate_loaded(v5.load_inputs(paths["config"]))
    calculation_path = root / "dimension-calculations.v6.json"
    v6.write_json(calculation_path, calculation)

    items_path = root / "item-assessments.v6.json"
    build_v6_items(paths, items_path, seed)

    metadata_path = root / "projection-metadata.v6.json"
    v6.write_json(
        metadata_path,
        {
            "schema_version": "subject-index-v6-projection-metadata-v1",
            "candidate_label": "Synthetic multi-defect fixture",
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
    paths.update(
        {
            "calculation": calculation_path,
            "result": result_path,
            "items": items_path,
            "web": web_path,
            "metadata": metadata_path,
        }
    )
    return paths


def component(record: dict, dimension_id: str) -> dict:
    return next(
        item
        for item in record["component_results"]
        if item["dimension_id"] == dimension_id
    )


def factor(record: dict, factor_id: str) -> dict:
    return next(
        item
        for item in record["popover"]["factors"]
        if item["factor_id"] == factor_id
    )


def projection_bytes(value: dict) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


class V7ItemProjectionDeterminismTests(unittest.TestCase):
    def test_equivalent_insertion_orders_use_stable_defect_identity_order(self) -> None:
        fixture = load_fixture()
        self.assertNotEqual(
            fixture["expected_defect_id_order"],
            [item["defect_id"] for item in fixture["defects"]],
        )
        self.assertEqual(
            "ITEM-PROJECTION-DEFECT-ID-ASC-V1",
            item_grades.DEFECT_PROJECTION_ORDER_RULE_ID,
        )

        with tempfile.TemporaryDirectory() as temporary:
            paths = materialize_inputs(Path(temporary) / "inputs")
            candidate = json.loads(paths["candidate"].read_text(encoding="utf-8"))
            inventory = json.loads(paths["inventory"].read_text(encoding="utf-8"))
            locator = json.loads(paths["locator"].read_text(encoding="utf-8"))
            missing = json.loads(paths["missing"].read_text(encoding="utf-8"))
            structure = json.loads(paths["structure"].read_text(encoding="utf-8"))
            reordered = copy.deepcopy(structure)
            reordered["defects"].reverse()
            for record in reordered["defects"]:
                record["affected_item_ids"].reverse()
            reordered["v5_scoring_context"]["defects"] = copy.deepcopy(
                reordered["defects"]
            )

            def project(structure_document: dict) -> dict:
                return item_grades.build_assessments(
                    candidate,
                    inventory,
                    [locator],
                    [missing],
                    structure_document,
                    "full",
                    "eval-v5",
                    digest(paths["inventory"]),
                )

            first = project(structure)
            second = project(reordered)
            self.assertEqual(projection_bytes(first), projection_bytes(second))

            path_record = next(
                item
                for item in first["path_assessments"]
                if item["path_id"] == fixture["path_id"]
            )
            path_component = component(path_record, "findability_navigation")
            actual_caps = [
                [item["defect_id"], item["severity"], item["maximum_score"]]
                for item in path_component["severity_caps"]
            ]
            self.assertEqual(fixture["expected_path_cap_order"], actual_caps)
            expected_path_evidence = [
                *fixture["node_ids"],
                *fixture["expected_defect_id_order"],
            ]
            self.assertEqual(expected_path_evidence, path_component["evidence_ids"])
            popover_factor = factor(path_record, "findability_navigation")
            self.assertEqual(
                path_component["severity_caps"], popover_factor["severity_caps"]
            )
            self.assertEqual(
                path_component["evidence_ids"], popover_factor["evidence_ids"]
            )

            node_record = next(
                item
                for item in first["heading_node_assessments"]
                if item["node_id"] == fixture["node_ids"][0]
            )
            node_component = component(node_record, "findability_navigation")
            self.assertEqual(
                fixture["expected_node_defect_id_order"],
                [item["defect_id"] for item in node_component["severity_caps"]],
            )
            self.assertEqual(
                fixture["expected_node_defect_id_order"],
                node_component["evidence_ids"],
            )

    def test_cross_process_hash_seeds_produce_byte_identical_items(self) -> None:
        fixture = load_fixture()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = materialize_inputs(root / "inputs")
            output_bytes = []
            for seed in HASH_SEEDS:
                output = root / f"item-assessments-seed-{seed}.json"
                build_v6_items(paths, output, seed)
                output_bytes.append(output.read_bytes())
            for seed, candidate_bytes in zip(
                HASH_SEEDS[1:], output_bytes[1:], strict=True
            ):
                self.assertEqual(output_bytes[0], candidate_bytes, seed)

            result = json.loads(output_bytes[0])
            path_record = next(
                item
                for item in result["path_assessments"]
                if item["path_id"] == fixture["path_id"]
            )
            self.assertEqual(
                fixture["expected_defect_id_order"],
                [
                    item["defect_id"]
                    for item in component(
                        path_record, "findability_navigation"
                    )["severity_caps"]
                ],
            )

    def test_complete_clean_migrations_are_byte_identical_across_hash_seeds(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repeat_roots = [root / "repeat-a", root / "repeat-b"]
            seeds = (HASH_SEEDS[0], HASH_SEEDS[-1])
            output_roots = []
            frozen_inputs = []
            for repeat_root, seed in zip(repeat_roots, seeds, strict=True):
                paths = prepare_v6_projection(repeat_root, seed)
                manifest = migration_manifest(repeat_root, paths)
                frozen_inputs.append(
                    {
                        key: digest(path)
                        for key, path in paths.items()
                        if path.is_file()
                    }
                )
                output = repeat_root / "v7"
                run_cli_with_seed(
                    "dimension_score_v7_cli.py",
                    seed,
                    "migrate-v6-to-v7",
                    "--manifest",
                    manifest,
                    "--output-directory",
                    output,
                )
                self.assertEqual(
                    frozen_inputs[-1],
                    {
                        key: digest(path)
                        for key, path in paths.items()
                        if path.is_file()
                    },
                )
                output_roots.append(output)

            relative_files = sorted(
                path.relative_to(repeat_roots[0])
                for path in repeat_roots[0].rglob("*.json")
            )
            self.assertEqual(
                relative_files,
                sorted(
                    path.relative_to(repeat_roots[1])
                    for path in repeat_roots[1].rglob("*.json")
                ),
            )
            for relative in relative_files:
                self.assertEqual(
                    (repeat_roots[0] / relative).read_bytes(),
                    (repeat_roots[1] / relative).read_bytes(),
                    relative,
                )

            output_hashes = {
                path.relative_to(output_roots[0]).as_posix(): hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
                for path in sorted(output_roots[0].rglob("*.json"))
            }
            print(
                "synthetic_v7_multidefect_repeat_sha256="
                + json.dumps(output_hashes, sort_keys=True)
            )

            self_hash_fields = {
                "dimension-calculations.v7.json": (
                    "calculation_id",
                    "calculation_sha256",
                ),
                "structure-locator-review.v7.json": (
                    "review_id",
                    "review_sha256",
                ),
                "score-migration.v6-to-v7.json": (
                    "migration_id",
                    "migration_sha256",
                ),
                "projection-metadata.v7.json": (
                    None,
                    "projection_metadata_sha256",
                ),
                "validation-receipt.v7.json": (
                    "receipt_id",
                    "receipt_sha256",
                ),
            }
            identities = []
            for output_root in output_roots:
                identity_snapshot = {}
                for filename, (identity_field, hash_field) in self_hash_fields.items():
                    document = json.loads(
                        (output_root / filename).read_text(encoding="utf-8")
                    )
                    self.assertEqual(
                        document[hash_field],
                        v5.canonical_hash(document, hash_field),
                    )
                    identity_snapshot[hash_field] = document[hash_field]
                    if identity_field is not None:
                        identity_snapshot[identity_field] = document[identity_field]
                identities.append(identity_snapshot)
            self.assertEqual(identities[0], identities[1])

            semantic_snapshots = []
            for output_root in output_roots:
                calculation = json.loads(
                    (output_root / "dimension-calculations.v7.json").read_text(
                        encoding="utf-8"
                    )
                )
                migration = json.loads(
                    (output_root / "score-migration.v6-to-v7.json").read_text(
                        encoding="utf-8"
                    )
                )
                review = json.loads(
                    (output_root / "structure-locator-review.v7.json").read_text(
                        encoding="utf-8"
                    )
                )
                receipt = json.loads(
                    (output_root / "validation-receipt.v7.json").read_text(
                        encoding="utf-8"
                    )
                )
                self.assertTrue(migration["gate_preservation"]["outcomes_equal"])
                self.assertTrue(receipt["validation"]["all_hashes_recomputed"])
                self.assertTrue(receipt["validation"]["all_schemas_valid"])
                self.assertTrue(receipt["validation"]["historical_bytes_unchanged"])
                self.assertTrue(receipt["validation"]["gate_outcomes_equal"])
                semantic_snapshots.append(
                    {
                        "total_score": calculation["total_score"],
                        "dimensions": calculation["dimensions"],
                        "gates": migration["gate_preservation"],
                        "locator_fit": calculation.get(
                            "locator_fit_compatibility"
                        ),
                        "architecture": review["path_reviews"],
                    }
                )
            self.assertEqual(semantic_snapshots[0], semantic_snapshots[1])


if __name__ == "__main__":
    unittest.main()
