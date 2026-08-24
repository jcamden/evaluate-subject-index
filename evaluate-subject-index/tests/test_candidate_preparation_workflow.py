#!/usr/bin/env python3
"""End-to-end and gate tests for parallel candidate preparation."""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import candidate_preparation_cli as preparation  # noqa: E402
from candidate_layout_adapters import extract_candidate_layout  # noqa: E402
from item_grade_cli import build_inventory  # noqa: E402
from state_cli import next_stage  # noqa: E402

from candidate_preparation_test_support import (  # noqa: E402
    BASE_COMMIT,
    BENCHMARK_COMMIT,
    MERGED_COMMIT,
    PUBLIC_PATHS,
    SyntheticStudy,
    git_blob_sha,
    read_json,
    run_cli,
    sha256_file,
    synthetic_geometry,
    write_json,
)


class CurrentFormatRegressionTests(unittest.TestCase):
    def test_current_v2_fixture_builds_expected_inventory_and_assessments(self) -> None:
        candidate_path = SKILL_ROOT / "tests" / "candidate-index.valid.json"
        candidate = read_json(candidate_path)
        inventory = build_inventory(candidate)
        self.assertEqual("candidate-index-v2", candidate["schema_version"])
        self.assertEqual("subject-index-item-inventory-v2", inventory["schema_version"])
        self.assertEqual(["XREF-675042835077"], inventory["paths"][2]["reference_ids"])

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "item-inventory.json"
            write_json(output, inventory)
            self.assertEqual(
                "2b3032cb85387728e20a454b5ced845b319e499148a4fdb6b8f97819112b3fe8",
                sha256_file(output),
            )
            command = [
                sys.executable,
                str(SCRIPTS / "item_grade_cli.py"),
                "build-assessments",
                "--candidate", str(candidate_path),
                "--inventory", str(output),
                "--locator-audit", str(SKILL_ROOT / "tests" / "locator-audit.item-grading.valid.json"),
                "--missing-access-audit", str(SKILL_ROOT / "tests" / "missing-access-audit.item-grading.valid.json"),
                "--structure-audit", str(SKILL_ROOT / "tests" / "structure-audit.item-grading.valid.json"),
                "--audit-mode", "full",
                "--output", str(Path(directory) / "item-assessments.json"),
            ]
            completed = subprocess.run(command, text=True, capture_output=True, check=False)
            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(3, payload["summary"]["locators"]["total"])
            self.assertEqual(1, payload["summary"]["cross_references"]["total"])

    def test_current_v2_fixture_still_routes_through_existing_page_chunk_cli(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            page_map = root / "page-map.json"
            chunks = root / "chunk-manifest.json"
            benchmark_lock = root / "candidate-benchmark-lock.json"
            packet_dir = root / "packets"
            commands = [
                [
                    "expand-page-map",
                    "--input", str(SKILL_ROOT / "tests" / "page-map-input.valid.json"),
                    "--output", str(page_map),
                ],
                [
                    "validate-chunks",
                    "--input", str(SKILL_ROOT / "tests" / "chunk-manifest.input.json"),
                    "--page-map", str(page_map),
                    "--output", str(chunks),
                ],
                [
                    "filter-candidate",
                    "--candidate", str(SKILL_ROOT / "tests" / "candidate-index.valid.json"),
                    "--page-map", str(page_map),
                    "--chunks", str(chunks),
                    "--benchmark-lock", str(benchmark_lock),
                    "--output-dir", str(packet_dir),
                ],
            ]
            payload = None
            for command_index, arguments in enumerate(commands):
                if command_index == 2:
                    candidate = read_json(SKILL_ROOT / "tests" / "candidate-index.valid.json")
                    expanded_page_map = read_json(page_map)
                    chunk_manifest = read_json(chunks)
                    lock = {
                        "schema_version": "candidate-benchmark-lock-v1",
                        "status": "locked",
                        "locked_at": "2026-08-24T00:00:00Z",
                        "candidate_id": candidate["candidate_id"],
                        "candidate_sha256": candidate["candidate_sha256"],
                        "preparation_receipt_sha256": "b" * 64,
                        "candidate_repository": {
                            "project": "synthetic-candidate",
                            "merged_commit": "c" * 40,
                            "worker_head_commit": "d" * 40,
                            "pull_request": 17,
                        },
                        "benchmark_repository": {
                            "project": "synthetic-benchmark",
                            "final_commit": "e" * 40,
                            "benchmark_sha256": "f" * 64,
                            "benchmark_file_sha256": "1" * 64,
                        },
                        "compatibility": {
                            "source_sha256": expanded_page_map["source_sha256"],
                            "source_edition": "Synthetic edition",
                            "page_map_sha256": expanded_page_map["page_map_sha256"],
                            "chunk_manifest_sha256": chunk_manifest["chunk_manifest_sha256"],
                            "policy_sha256": "2" * 64,
                            "policy_profile": "standard",
                            "rubric_version": "subject-index-rubric-v4",
                            "audit_mode": "full",
                        },
                    }
                    lock["lock_sha256"] = preparation.canonical_hash(lock, "lock_sha256")
                    write_json(benchmark_lock, lock)
                completed = subprocess.run(
                    [sys.executable, str(SCRIPTS / "page_chunk_cli.py"), *arguments],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
                payload = json.loads(completed.stdout)
            self.assertIsNotNone(payload)
            self.assertEqual(0, payload["exception_count"])
            self.assertEqual([1, 2], [item["locator_assignment_count"] for item in payload["chunks"]])


class NormalizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.study = SyntheticStudy(Path(self.temporary.name))
        self.study.extract_and_normalize()

    def test_arbitrary_depth_mixed_references_and_irregular_ranges(self) -> None:
        candidate = read_json(self.study.paths["candidate_index"])
        records = candidate["records"]
        by_leaf = {record["heading_path"][-1]: record for record in records}

        aerial = by_leaf["Aërial Kites"]
        self.assertEqual(["Clockwork Orchard", "Aërial Kites"], aerial["heading_path"])
        self.assertEqual(["iv", "v", "A-1"], [item["source_page_label"] for item in aerial["locator_assignments"]])
        self.assertEqual("iv–A-1", aerial["locator_displays"][0]["displayed_locator"])

        rigging = by_leaf["brass rigging"]
        self.assertEqual(["Clockwork Orchard", "Aërial Kites", "brass rigging"], rigging["heading_path"])
        self.assertEqual("mixed", rigging["record_type"])
        self.assertEqual(["120", "121", "122", "123"], [item["source_page_label"] for item in rigging["locator_assignments"]])
        self.assertEqual(["see also", "see"], [item["type"] for item in rigging["cross_references"]])
        self.assertEqual(["Zephyr Engines", "Flying Looms"], [item["target"] for item in rigging["cross_references"]])
        self.assertIn("Aërial", aerial["original_displayed_form"])

        broken = by_leaf["Broken Compass"]
        self.assertEqual("unresolved", broken["locator_assignments"][0]["mapping_status"])
        exceptions = read_json(self.study.paths["normalization_exceptions"])
        self.assertTrue(any(item["type"] == "locator_unresolved_or_malformed" for item in exceptions["exceptions"]))

        inventory = read_json(self.study.paths["item_inventory"])
        deepest = next(node for node in inventory["heading_nodes"] if node["heading_path"][-1] == "brass rigging")
        self.assertEqual(3, deepest["level"])
        mixed_path = next(path for path in inventory["paths"] if path["path_id"] == rigging["path_id"])
        self.assertEqual(2, len(mixed_path["reference_ids"]))

    def test_normalization_is_deterministic_and_candidate_blind(self) -> None:
        layout = read_json(self.study.paths["layout_extraction"])
        page_map = read_json(self.study.page_map_path)
        first = preparation.normalize_layout(layout, page_map)
        second = preparation.normalize_layout(copy.deepcopy(layout), copy.deepcopy(page_map))
        self.assertEqual(first, second)
        candidate = first[0]
        self.assertFalse(candidate["normalization"]["benchmark_content_used"])
        encoded = json.dumps(first, ensure_ascii=False).casefold()
        self.assertNotIn("benchmark_subjects", encoded)
        for record in candidate["records"]:
            self.assertRegex(record["record_id"], r"^REC-")
            self.assertRegex(record["path_id"], r"^PATH-")

    def test_abbreviated_endpoint_unique_and_ambiguous(self) -> None:
        page_map = read_json(self.study.page_map_path)
        lookup, index_by_page, pages = preparation.page_map_lookup(page_map)
        assignments, display, exceptions = preparation.locator_assignments_for_display(
            "120–23", "DISPLAY-UNIQUE", self.study.candidate_sha256, lookup, index_by_page, pages
        )
        self.assertEqual("resolved", display["mapping_status"])
        self.assertEqual(["120", "121", "122", "123"], [item["source_page_label"] for item in assignments])
        self.assertEqual([], exceptions)

        ambiguous_pages = copy.deepcopy(pages)
        ambiguous_pages.append(
            {
                "document_page": 9,
                "source_page_label": "123",
                "normalized_locator_key": "123",
                "label_style": "literal",
                "mapping_id": "main",
                "in_evaluation_scope": True,
                "accepts_index_locators": True,
            }
        )
        ambiguous_index = {**index_by_page, 9: len(ambiguous_pages) - 1}
        assignments, display, exceptions = preparation.locator_assignments_for_display(
            "120–23",
            "DISPLAY-AMBIGUOUS",
            self.study.candidate_sha256,
            lookup,
            ambiguous_index,
            ambiguous_pages,
        )
        self.assertEqual("unresolved", display["mapping_status"])
        self.assertEqual("unresolved", assignments[0]["mapping_status"])
        self.assertEqual("abbreviated_endpoint_ambiguous", exceptions[0]["type"])

    def test_provenance_statuses_are_independent_and_reconstruction_claim_is_rejected(self) -> None:
        for status in preparation.PROVENANCE_STATUSES:
            provenance = preparation.default_provenance()
            provenance["internal_pdf_completeness"] = {"status": "verified", "rationale": "Synthetic review."}
            provenance["authoritative_copy_fidelity"] = {"status": status, "rationale": "Independent status."}
            self.assertEqual([], preparation.validate_provenance(provenance, "delivered_pdf"), status)

        provenance = preparation.default_provenance()
        provenance["internal_pdf_completeness"] = {"status": "verified", "rationale": "Internally complete."}
        provenance["authoritative_copy_fidelity"] = {
            "status": "not_independently_verified",
            "rationale": "No authoritative copy was compared.",
        }
        self.assertEqual([], preparation.validate_provenance(provenance, "delivered_pdf"))

        invalid = preparation.default_provenance()
        invalid["structural_continuity"]["status"] = "probably"
        self.assertTrue(any("status is invalid" in item for item in preparation.validate_provenance(invalid, "delivered_pdf")))

        reconstructed = preparation.default_provenance()
        reconstructed["authoritative_copy_fidelity"]["claimed_original_publisher_pdf"] = True
        self.assertTrue(any("original publisher PDF" in item for item in preparation.validate_provenance(reconstructed, "reconstructed_pdf")))

    def test_bare_see_also_is_retained_as_a_malformed_reference(self) -> None:
        layout = read_json(self.study.paths["layout_extraction"])
        target = next(
            line
            for page in layout["pages"]
            for region in page["regions"]
            for line in region["lines"]
            if line.get("displayed_line_text") == "Wind-up Beacons, 122"
        )
        target["displayed_line_text"] = "Frayed Signal, see also"
        target["original_displayed_form"] = "Frayed Signal, see also"
        candidate, _, exceptions, _ = preparation.normalize_layout(
            layout, read_json(self.study.page_map_path)
        )
        record = next(item for item in candidate["records"] if item["heading_path"][-1] == "Frayed Signal")
        self.assertEqual([], record["cross_references"])
        self.assertEqual("container", record["record_type"])
        malformed = [
            item
            for item in exceptions["exceptions"]
            if item["type"] == "malformed_cross_reference" and item["record_id"] == record["record_id"]
        ]
        self.assertEqual(1, len(malformed))
        self.assertEqual("Frayed Signal, see also", malformed[0]["displayed_form"])

    def test_page_continuation_text_remains_part_of_the_heading(self) -> None:
        geometry = synthetic_geometry()
        geometry["pages"][0]["lines"].insert(
            -1, {"bbox": [320, 160, 530, 172], "text": "Tidal Almanac,"}
        )
        harmonic = next(
            line
            for line in geometry["pages"][1]["lines"]
            if line["text"] == "Harmonic Gears, 121"
        )
        harmonic["text"] = "continued mechanisms, 121"
        layout = extract_candidate_layout(
            self.study.candidate_file,
            self.study.candidate_id,
            geometry=geometry,
        )
        candidate, _, _, _ = preparation.normalize_layout(
            layout, read_json(self.study.page_map_path)
        )
        record = next(
            item
            for item in candidate["records"]
            if "Tidal Almanac" in item["original_displayed_form"]
        )
        self.assertEqual(["Tidal Almanac, continued mechanisms"], record["heading_path"])
        self.assertEqual(["121"], [item["displayed_locator"] for item in record["locator_displays"]])
        self.assertEqual([1, 2], record["private_evidence"]["candidate_pdf_pages"])
        self.assertEqual(
            ["continues_next_page", "continued_from_previous_page"],
            record["private_evidence"]["continuation_statuses"],
        )
        self.assertEqual("Tidal Almanac,\ncontinued mechanisms, 121", record["original_displayed_form"])


class ExactSetQaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.study = SyntheticStudy(Path(self.temporary.name) / "study")
        self.study.extract_and_normalize()
        self.study.complete_qa_and_provenance()

    def validate_root(self, root: Path) -> None:
        preparation.validate_private_preparation(
            root,
            self.study.candidate_id,
            self.study.candidate_file,
            self.study.state_path,
            self.study.page_map_path,
            self.study.chunk_manifest_path,
            self.study.policy_path,
        )

    def mutated_copy(self, name: str) -> Path:
        destination = Path(self.temporary.name) / "mutations" / name
        shutil.copytree(self.study.preparation_dir, destination)
        return destination

    def assert_invalid(self, root: Path, text: str) -> None:
        with self.assertRaises(preparation.PreparationError) as caught:
            self.validate_root(root)
        self.assertEqual("private_preparation_invalid", caught.exception.code)
        details = "\n".join(map(str, caught.exception.details or []))
        self.assertIn(text, details)

    def path(self, root: Path, key: str) -> Path:
        relative = self.study.paths[key].relative_to(self.study.preparation_dir)
        return root / relative

    def test_complete_exact_set_gate_passes(self) -> None:
        result = preparation.validate_private_preparation(
            self.study.preparation_dir,
            self.study.candidate_id,
            self.study.candidate_file,
            self.study.state_path,
            self.study.page_map_path,
            self.study.chunk_manifest_path,
            self.study.policy_path,
        )
        self.assertEqual("candidate-index-v2", result["documents"]["candidate_index"]["schema_version"])
        self.assertTrue(result["documents"]["normalization_qa"]["completion"]["complete"])
        self.assertFalse(result["documents"]["normalization_qa"]["completion"]["editorial_quality_judgments_performed"])

    def test_exact_set_and_hash_mutations_are_rejected(self) -> None:
        cases = []

        baseline_qa = read_json(self.study.paths["normalization_qa"])
        for denominator in sorted(baseline_qa["reviewed"]):
            root = self.mutated_copy(f"reviewed-{denominator}")
            qa = read_json(self.path(root, "normalization_qa"))
            qa["reviewed"][denominator].pop()
            write_json(self.path(root, "normalization_qa"), qa)
            cases.append(
                (root, f"reviewed.{denominator} is not the exact expected set")
            )

        root = self.mutated_copy("duplicate-id")
        candidate = read_json(self.path(root, "candidate_index"))
        candidate["records"][1]["record_id"] = candidate["records"][0]["record_id"]
        write_json(self.path(root, "candidate_index"), candidate)
        cases.append((root, "Duplicate record_id"))

        root = self.mutated_copy("missing-exception")
        exceptions = read_json(self.path(root, "normalization_exceptions"))
        exceptions["exceptions"] = []
        write_json(self.path(root, "normalization_exceptions"), exceptions)
        cases.append((root, "has no exception-ledger record"))

        root = self.mutated_copy("outside-map")
        candidate = read_json(self.path(root, "candidate_index"))
        assignment = next(
            item
            for record in candidate["records"]
            for item in record["locator_assignments"]
            if item["mapping_status"] == "resolved"
        )
        assignment["document_page"] = 999
        write_json(self.path(root, "candidate_index"), candidate)
        cases.append((root, "outside the indexable page map"))

        root = self.mutated_copy("inventory-parity")
        inventory = read_json(self.path(root, "item_inventory"))
        inventory["locators"].pop()
        inventory["counts"]["locators"] -= 1
        write_json(self.path(root, "item_inventory"), inventory)
        cases.append((root, "Item inventory is not the exact deterministic projection"))

        root = self.mutated_copy("missing-page-review")
        qa = read_json(self.path(root, "normalization_qa"))
        qa["page_reviews"].pop()
        write_json(self.path(root, "normalization_qa"), qa)
        cases.append((root, "does not cover every candidate PDF page exactly once"))

        root = self.mutated_copy("completion")
        qa = read_json(self.path(root, "normalization_qa"))
        qa["completion"]["all_denominators_complete"] = False
        write_json(self.path(root, "normalization_qa"), qa)
        cases.append((root, "completion.all_denominators_complete must be true"))

        root = self.mutated_copy("silent-byte-change")
        candidate_path = self.path(root, "candidate_index")
        candidate_path.write_text(candidate_path.read_text(encoding="utf-8") + " \n", encoding="utf-8")
        cases.append((root, "normalized_candidate_file_sha256 does not match"))

        for root, expected in cases:
            with self.subTest(case=root.name):
                self.assert_invalid(root, expected)


class FrozenIdentityAndAuditLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.study = SyntheticStudy(Path(self.temporary.name))

    def load_identities(
        self,
        *,
        state: Path | None = None,
        page_map: Path | None = None,
        chunks: Path | None = None,
    ) -> dict:
        return preparation.load_source_identities(
            state or self.study.state_path,
            page_map or self.study.page_map_path,
            chunks or self.study.chunk_manifest_path,
            self.study.policy_path,
            None,
        )

    def test_current_v4_state_is_supported_and_older_state_is_rejected(self) -> None:
        identities = self.load_identities()
        self.assertEqual("subject-index-evaluation-state-v4", identities["state"]["schema_version"])

        old_state = read_json(self.study.state_path)
        old_state["schema_version"] = "subject-index-evaluation-state-v3"
        old_state_path = self.study.root / "evaluation-state.v3.json"
        write_json(old_state_path, old_state)
        with self.assertRaises(preparation.PreparationError) as caught:
            self.load_identities(state=old_state_path)
        self.assertEqual("unsupported_state", caught.exception.code)

    def test_candidate_source_and_page_map_hash_mismatches_are_rejected(self) -> None:
        source_mismatch = read_json(self.study.state_path)
        source_mismatch["source"]["sha256"] = "f" * 64
        source_mismatch_path = self.study.root / "state-source-mismatch.json"
        write_json(source_mismatch_path, source_mismatch)
        with self.assertRaises(preparation.PreparationError) as source_error:
            self.load_identities(state=source_mismatch_path)
        self.assertEqual("source_hash_mismatch", source_error.exception.code)

        chunk_mismatch = read_json(self.study.chunk_manifest_path)
        chunk_mismatch["page_map_sha256"] = "e" * 64
        chunk_mismatch["chunk_manifest_sha256"] = preparation.canonical_hash(
            chunk_mismatch, "chunk_manifest_sha256"
        )
        chunk_mismatch_path = self.study.root / "chunk-page-map-mismatch.json"
        write_json(chunk_mismatch_path, chunk_mismatch)
        with self.assertRaises(preparation.PreparationError) as page_map_error:
            self.load_identities(chunks=chunk_mismatch_path)
        self.assertEqual("page_map_mismatch", page_map_error.exception.code)

        self.study.extract_and_normalize()
        different_candidate = self.study.root / "restricted" / "different-candidate.pdf"
        different_candidate.write_bytes(self.study.candidate_file.read_bytes() + b"different")
        _, payload = run_cli(
            "normalize",
            "--candidate-id", self.study.candidate_id,
            "--candidate-file", str(different_candidate),
            "--state", str(self.study.state_path),
            "--page-map", str(self.study.page_map_path),
            "--chunk-manifest", str(self.study.chunk_manifest_path),
            "--policy", str(self.study.policy_path),
            "--layout", str(self.study.layout_path),
            "--output-dir", str(self.study.root / "candidate-hash-mismatch"),
            ok=False,
        )
        self.assertEqual("candidate_hash_mismatch", payload["error"]["code"])

    def test_locator_routing_is_blocked_until_benchmark_lock_is_final(self) -> None:
        self.study.extract_and_normalize()
        candidate = read_json(self.study.paths["candidate_index"])
        page_map = read_json(self.study.page_map_path)
        chunks = read_json(self.study.chunk_manifest_path)
        lock = {
            "schema_version": "candidate-benchmark-lock-v1",
            "status": "pending_final_benchmark",
            "candidate_id": candidate["candidate_id"],
            "candidate_sha256": candidate["candidate_sha256"],
            "benchmark_repository": {
                "final_commit": BENCHMARK_COMMIT,
                "benchmark_sha256": "a" * 64,
            },
            "compatibility": {
                "page_map_sha256": page_map["page_map_sha256"],
                "chunk_manifest_sha256": chunks["chunk_manifest_sha256"],
            },
        }
        lock["lock_sha256"] = preparation.canonical_hash(lock, "lock_sha256")
        lock_path = self.study.root / "pending-benchmark-lock.json"
        write_json(lock_path, lock)
        output_dir = self.study.root / "locator-packets"
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "page_chunk_cli.py"),
                "filter-candidate",
                "--candidate", str(self.study.paths["candidate_index"]),
                "--page-map", str(self.study.page_map_path),
                "--chunks", str(self.study.chunk_manifest_path),
                "--benchmark-lock", str(lock_path),
                "--output-dir", str(output_dir),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(0, completed.returncode)
        payload = json.loads(completed.stdout)
        self.assertEqual("benchmark_lock_pending", payload["error"]["code"])
        self.assertFalse(output_dir.exists())


class PublicAndRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.study = SyntheticStudy(Path(self.temporary.name))
        self.study.extract_and_normalize()
        self.study.complete_qa_and_provenance()
        self.result = preparation.validate_private_preparation(
            self.study.preparation_dir,
            self.study.candidate_id,
            self.study.candidate_file,
            self.study.state_path,
            self.study.page_map_path,
            self.study.chunk_manifest_path,
            self.study.policy_path,
        )

    def test_public_projection_exact_allowlist_and_leak_scan(self) -> None:
        documents = preparation.public_projection_documents(self.result)
        self.assertEqual(set(PUBLIC_PATHS), set(documents))
        self.assertEqual([], preparation.validate_public_documents(documents))
        encoded = json.dumps(documents, ensure_ascii=False)
        self.assertNotIn("Clockwork Orchard", encoded)
        self.assertNotIn("Aërial Kites", encoded)
        self.assertNotIn("locator_assignments", encoded)

        mutations = []
        extra = copy.deepcopy(documents)
        extra["unexpected.json"] = {}
        mutations.append(("unexpected path", extra))
        headings = copy.deepcopy(documents)
        headings["validation/candidate-preparation-report.json"]["headings"] = ["Clockwork Orchard"]
        mutations.append(("heading list", headings))
        absolute = copy.deepcopy(documents)
        absolute["candidate/layout-profile.json"]["limitations"] = ["/workspace/private/index.pdf"]
        mutations.append(("absolute path", absolute))
        library = copy.deepcopy(documents)
        library["candidate/layout-profile.json"]["limitations"] = ["libfile_deadbeefcafebabe"]
        mutations.append(("Library id", library))
        secret = copy.deepcopy(documents)
        secret["candidate/layout-profile.json"]["limitations"] = ["ghp_1234567890abcdef"]
        mutations.append(("secret", secret))
        scalar_bypass = copy.deepcopy(documents)
        scalar_bypass["candidate/layout-profile.json"]["adapter"]["selection_reason"] = [
            "Clockwork Orchard, 1",
            "Aërial Kites, 2",
        ]
        mutations.append(("non-scalar adapter field", scalar_bypass))
        for index, unsafe_id in enumerate((
            "/var/lib/private/candidate.pdf",
            "../private/recovery.zip",
            "file:///etc/passwd",
            "C:\\work\\secret.pdf",
            "gho_1234567890abcdef",
            "AIza1234567890abcdefghijklmnop",
            "postgres://user:pass@example.invalid/db",
        )):
            unsafe = copy.deepcopy(documents)
            for document in unsafe.values():
                document["candidate_id"] = unsafe_id
            mutations.append((f"unsafe candidate id {index}", unsafe))
        for label, mutation in mutations:
            with self.subTest(label=label):
                self.assertTrue(preparation.validate_public_documents(mutation))

    def test_public_projection_rejects_symlinked_output_components_before_write(self) -> None:
        public_root = Path(self.temporary.name) / "symlink-public"
        outside = Path(self.temporary.name) / "outside"
        public_root.mkdir()
        outside.mkdir()
        (public_root / "candidate").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(preparation.PreparationError) as caught:
            preparation.write_public_projection(
                public_root,
                preparation.public_projection_documents(self.result),
            )
        self.assertEqual("unsafe_output_symlink", caught.exception.code)
        self.assertFalse((outside / "candidate-ref.json").exists())

    def test_branch_collision_and_empty_repository_bootstrap_rules(self) -> None:
        normal = preparation.validate_publication_plan(
            {
                "is_empty": False,
                "default_branch": "main",
                "base_commit": BASE_COMMIT,
                "branches": ["main"],
                "bootstrap_files": [],
            },
            self.study.candidate_id,
            None,
        )
        self.assertEqual("branch_from_existing_default_head", normal["repository_mode"])
        self.assertFalse(normal["bootstrap_exception"])

        empty = preparation.validate_publication_plan(
            {
                "is_empty": True,
                "default_branch": "main",
                "base_commit": None,
                "branches": [],
                "bootstrap_files": ["README.md", ".gitignore"],
            },
            self.study.candidate_id,
            None,
        )
        self.assertTrue(empty["bootstrap_exception"])
        self.assertEqual([".gitignore", "README.md"], empty["allowed_bootstrap_files"])

        with self.assertRaises(preparation.PreparationError) as collision:
            preparation.validate_publication_plan(
                {
                    "is_empty": False,
                    "default_branch": "main",
                    "base_commit": BASE_COMMIT,
                    "branches": ["main", f"candidate-preparation/{self.study.candidate_id}"],
                    "bootstrap_files": [],
                },
                self.study.candidate_id,
                None,
            )
        self.assertEqual("worker_branch_collision", collision.exception.code)

        with self.assertRaises(preparation.PreparationError) as unsafe:
            preparation.validate_publication_plan(
                {
                    "is_empty": True,
                    "default_branch": "main",
                    "base_commit": None,
                    "branches": [],
                    "bootstrap_files": ["README.md", "candidate/candidate-ref.json"],
                },
                self.study.candidate_id,
                None,
            )
        self.assertEqual("unsafe_empty_repository_bootstrap", unsafe.exception.code)

    def test_worker_outputs_must_be_pairwise_disjoint(self) -> None:
        collision = Path(self.temporary.name) / "receipt-and-recovery.json"
        _, payload = run_cli(
            "build-worker",
            "--candidate-id", self.study.candidate_id,
            "--candidate-file", str(self.study.candidate_file),
            "--preparation-dir", str(self.study.preparation_dir),
            "--state", str(self.study.state_path),
            "--page-map", str(self.study.page_map_path),
            "--chunk-manifest", str(self.study.chunk_manifest_path),
            "--policy", str(self.study.policy_path),
            "--project", self.study.candidate_project,
            "--benchmark-project", self.study.benchmark_project,
            "--benchmark-ref", BASE_COMMIT,
            "--repository-state", str(self.study.repo_state_path),
            "--checkpoint-ref", "source-identities-frozen-v1",
            "--public-output", str(Path(self.temporary.name) / "public"),
            "--recovery-zip", str(collision),
            "--receipt-output", str(collision),
            ok=False,
        )
        self.assertEqual("output_path_collision", payload["error"]["code"])
        self.assertFalse(collision.exists())

    def test_recovery_zip_is_deterministic_restricted_safe_and_tamper_evident(self) -> None:
        first = Path(self.temporary.name) / "first.zip"
        second = Path(self.temporary.name) / "second.zip"
        first_result = preparation.build_private_recovery_zip(first, self.result, "checkpoint-one")
        second_result = preparation.build_private_recovery_zip(second, self.result, "checkpoint-one")
        self.assertEqual(first_result["sha256"], second_result["sha256"])
        with zipfile.ZipFile(first) as archive:
            names = set(archive.namelist())
            self.assertFalse(any(name.lower().endswith(".pdf") for name in names))
            self.assertNotIn(str(self.study.candidate_file), names)
            self.assertIn("candidate-preparation-bundle-metadata.json", names)

        public_dir = Path(self.temporary.name) / "projection"
        public_hashes = preparation.write_public_projection(
            public_dir, preparation.public_projection_documents(self.result)
        )
        plan = preparation.validate_publication_plan(
            {
                "is_empty": False,
                "default_branch": "main",
                "base_commit": BASE_COMMIT,
                "branches": ["main"],
                "bootstrap_files": [],
            },
            self.study.candidate_id,
            None,
        )
        receipt = preparation.build_worker_receipt(
            self.result,
            public_hashes,
            first_result,
            self.study.candidate_project,
            self.study.benchmark_project,
            BASE_COMMIT,
            plan,
        )
        members = preparation.validate_recovery_zip(first, receipt)
        self.assertEqual(len(preparation.PRIVATE_ARTIFACT_KEYS) + 1, len(members))

        malformed_receipt = copy.deepcopy(receipt)
        malformed_receipt.pop("qa")
        malformed_receipt["unexpected_benchmark_subjects"] = ["must not be accepted"]
        malformed_receipt["receipt_sha256"] = preparation.canonical_hash(malformed_receipt, "receipt_sha256")
        with self.assertRaises(preparation.PreparationError) as receipt_error:
            preparation.validate_receipt_document(malformed_receipt)
        self.assertEqual("receipt_schema", receipt_error.exception.code)

        victim = Path(self.temporary.name) / "zip-temp-victim.txt"
        victim.write_bytes(b"must remain unchanged")
        safe_output = Path(self.temporary.name) / "exclusive-temp.zip"
        predictable_old_temp = safe_output.with_suffix(safe_output.suffix + ".tmp")
        predictable_old_temp.symlink_to(victim)
        preparation.build_private_recovery_zip(safe_output, self.result, "checkpoint-exclusive")
        self.assertEqual(b"must remain unchanged", victim.read_bytes())
        self.assertTrue(safe_output.is_file())
        self.assertFalse(safe_output.is_symlink())

        wrong_length = copy.deepcopy(receipt)
        wrong_length["private_recovery"]["byte_length"] += 1
        wrong_length["receipt_sha256"] = preparation.canonical_hash(wrong_length, "receipt_sha256")
        with self.assertRaises(preparation.PreparationError) as length_error:
            preparation.validate_recovery_zip(first, wrong_length)
        self.assertEqual("recovery_length_mismatch", length_error.exception.code)

        tampered = Path(self.temporary.name) / "tampered.zip"
        tampered.write_bytes(first.read_bytes() + b"tamper")
        with self.assertRaises(preparation.PreparationError) as caught:
            preparation.validate_recovery_zip(tampered, receipt)
        self.assertEqual("recovery_length_mismatch", caught.exception.code)


class WorkerIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.study = SyntheticStudy(Path(self.temporary.name))
        self.original_state = self.study.state_path.read_bytes()
        self.original_manifest = self.study.manifest_path.read_bytes()
        self.study.extract_and_normalize()
        self.study.complete_qa_and_provenance()
        self.study.validate_private()
        self.worker_payload = self.study.build_worker()
        self.study.bind_publication()
        self.study.make_final_benchmark()

    def test_worker_is_pre_freeze_and_integration_locks_then_advances(self) -> None:
        self.assertEqual(self.original_state, self.study.state_path.read_bytes())
        self.assertEqual(self.original_manifest, self.study.manifest_path.read_bytes())
        receipt = read_json(self.study.receipt_path)
        self.assertEqual("pending_final_benchmark", receipt["benchmark_lock"]["status"])
        self.assertFalse(self.worker_payload["canonical_state_mutated"])
        self.assertEqual(set(PUBLIC_PATHS), {
            path.relative_to(self.study.public_dir).as_posix()
            for path in self.study.public_dir.rglob("*")
            if path.is_file()
        })

        _, blocked = run_cli("preflight-integration", *self.study.preflight_arguments(), ok=False)
        self.assertEqual("benchmark_stage_incomplete", blocked["error"]["code"])
        self.assertEqual(self.original_state, self.study.state_path.read_bytes())

        source_hashes = {
            path: sha256_file(path)
            for path in (self.study.page_map_path, self.study.chunk_manifest_path, self.study.policy_path, self.study.benchmark_path)
        }
        self.study.freeze_benchmark_state()
        _, preflight = run_cli("preflight-integration", *self.study.preflight_arguments())
        self.assertTrue(preflight["merge_authorized"])
        self.assertFalse(preflight["merge_performed"])

        integrated = self.study.integrate()
        self.assertTrue(integrated["ok"])
        self.assertEqual("passed", integrated["full_state_validation"])
        self.assertFalse(integrated["benchmark_repository_modified"])
        self.assertEqual("locator_chunk_preparation", integrated["next_actions"][0]["stage"])
        self.assertEqual(
            [
                "copy_exact_normalized_bytes",
                "write_benchmark_lock_and_integration_evidence",
                "update_manifest",
                "update_state_last",
                "validate_complete_state",
                "create_cumulative_checkpoint",
            ],
            integrated["transaction_order"],
        )

        canonical_dir = self.study.root / "candidate" / self.study.candidate_id
        lock = read_json(canonical_dir / "candidate-benchmark-lock.json")
        self.assertEqual("locked", lock["status"])
        self.assertEqual(BENCHMARK_COMMIT, lock["benchmark_repository"]["final_commit"])
        self.assertEqual(MERGED_COMMIT, lock["candidate_repository"]["merged_commit"])
        self.assertEqual(
            self.study.paths["candidate_index"].read_bytes(),
            (canonical_dir / "candidate-index.v2.json").read_bytes(),
        )
        state = read_json(self.study.state_path)
        self.assertEqual("completed", state["stages"]["candidate_normalization"]["status"])
        self.assertEqual("locator_chunk_preparation", next_stage(state)["stage"])
        self.assertTrue(self.study.checkpoint_path.is_file())
        for path, digest in source_hashes.items():
            self.assertEqual(digest, sha256_file(path), path)

    def test_preflight_requires_a_distinct_later_publication_observation(self) -> None:
        self.study.freeze_benchmark_state()
        arguments = self.study.preflight_arguments()
        self.study.make_publication_evidence(observed_at="2026-08-24T12:00:00Z")
        _, payload = run_cli("preflight-integration", *arguments, ok=False)
        self.assertEqual("publication_evidence_not_fresh", payload["error"]["code"])

    def test_merge_evidence_cannot_predate_the_fresh_open_snapshot(self) -> None:
        self.study.freeze_benchmark_state()
        evidence = self.study.make_merge_evidence()
        evidence["observed_at"] = "2026-08-24T11:59:00Z"
        early = self.study.root / "early-merge-evidence.json"
        write_json(early, evidence)
        _, payload = run_cli(
            *self.study.integration_arguments(merge_evidence=early),
            ok=False,
        )
        self.assertEqual("merge_evidence_order", payload["error"]["code"])

    def test_benchmark_identity_mismatches_are_rejected(self) -> None:
        receipt = read_json(self.study.bound_receipt_path)
        original = read_json(self.study.benchmark_path)
        state = read_json(self.study.state_path)
        fields = ("source_sha256", "page_map_sha256", "chunk_manifest_sha256", "policy_sha256")
        for field in fields:
            with self.subTest(field=field):
                mutated = copy.deepcopy(original)
                mutated[field] = "f" * 64
                mutated["benchmark_sha256"] = preparation.canonical_hash(mutated, "benchmark_sha256")
                path = self.study.root / f"benchmark-mismatch-{field}.json"
                write_json(path, mutated)
                proof = read_json(self.study.benchmark_proof_path)
                proof["benchmark_path"] = path.name
                proof["blob_sha"] = git_blob_sha(path)
                proof["file_sha256"] = sha256_file(path)
                proof_path = self.study.root / f"benchmark-proof-mismatch-{field}.json"
                write_json(proof_path, proof)
                with self.assertRaises(preparation.PreparationError) as caught:
                    preparation.validate_final_benchmark(
                        path,
                        receipt,
                        self.study.benchmark_project,
                        BENCHMARK_COMMIT,
                        proof_path,
                        state,
                        self.study.state_path,
                    )
                self.assertEqual("benchmark_identity_mismatch", caught.exception.code)

        with self.assertRaises(preparation.PreparationError) as repository:
            preparation.validate_final_benchmark(
                self.study.benchmark_path,
                receipt,
                "example/wrong-benchmark",
                BENCHMARK_COMMIT,
                self.study.benchmark_proof_path,
                state,
                self.study.state_path,
            )
        self.assertEqual("benchmark_repository_mismatch", repository.exception.code)

    def test_publication_requires_exact_changed_paths_and_one_commit_binding(self) -> None:
        evidence = read_json(self.study.publication_evidence_path)
        evidence["changed_files"] = [
            *evidence["changed_files"][:2],
            {
                "path": "unexpected.json",
                "blob_sha": "9" * 40,
                "file_sha256": "8" * 64,
            },
        ]
        bad_evidence = self.study.root / "bad-publication-evidence.json"
        write_json(bad_evidence, evidence)
        arguments = [
            "bind-publication",
            "--receipt", str(self.study.receipt_path),
            "--public-dir", str(self.study.public_dir),
            "--publication-evidence", str(bad_evidence),
            "--output", str(self.study.root / "bad-bound-receipt.json"),
        ]
        _, payload = run_cli(*arguments, ok=False)
        self.assertEqual("public_allowlist_mismatch", payload["error"]["code"])

    def test_publication_evidence_is_github_observed_and_hash_bound(self) -> None:
        original = read_json(self.study.publication_evidence_path)
        mutations = []

        evidence = copy.deepcopy(original)
        evidence["evidence_source"] = "worker_claim"
        mutations.append(("source", evidence, "publication_evidence_source"))

        evidence = copy.deepcopy(original)
        evidence["commit_count"] = 2
        mutations.append(("commit-count", evidence, "publication_commit_count"))

        evidence = copy.deepcopy(original)
        evidence["changed_files"][0]["file_sha256"] = "7" * 64
        mutations.append(("file-hash", evidence, "publication_file_hash_mismatch"))

        evidence = copy.deepcopy(original)
        evidence["state"] = "closed"
        evidence["merged"] = True
        mutations.append(("state", evidence, "publication_state"))

        for label, evidence, code in mutations:
            with self.subTest(label=label):
                evidence_path = self.study.root / f"publication-evidence-{label}.json"
                write_json(evidence_path, evidence)
                _, payload = run_cli(
                    "bind-publication",
                    "--receipt", str(self.study.receipt_path),
                    "--public-dir", str(self.study.public_dir),
                    "--publication-evidence", str(evidence_path),
                    "--output", str(self.study.root / f"bound-{label}.json"),
                    ok=False,
                )
                self.assertEqual(code, payload["error"]["code"])

    def test_benchmark_proof_is_github_observed_commit_and_hash_bound(self) -> None:
        self.study.freeze_benchmark_state()
        original = read_json(self.study.benchmark_proof_path)
        mutations = []

        proof = copy.deepcopy(original)
        proof["evidence_source"] = "worker_claim"
        mutations.append(("source", proof, "benchmark_proof_source"))

        proof = copy.deepcopy(original)
        proof["final_commit"] = "6" * 40
        mutations.append(("commit", proof, "benchmark_proof_commit"))

        proof = copy.deepcopy(original)
        proof["file_sha256"] = "5" * 64
        mutations.append(("file-hash", proof, "benchmark_proof_file_hash"))

        for label, proof, code in mutations:
            with self.subTest(label=label):
                proof_path = self.study.root / f"benchmark-proof-{label}.json"
                write_json(proof_path, proof)
                arguments = self.study.preflight_arguments()
                arguments[arguments.index("--benchmark-proof") + 1] = str(proof_path)
                _, payload = run_cli("preflight-integration", *arguments, ok=False)
                self.assertEqual(code, payload["error"]["code"])

    def test_fake_or_changed_merge_evidence_is_rejected(self) -> None:
        self.study.freeze_benchmark_state()
        frozen_state = self.study.state_path.read_bytes()
        frozen_manifest = self.study.manifest_path.read_bytes()
        original = self.study.make_merge_evidence()
        mutations = []

        evidence = copy.deepcopy(original)
        evidence["evidence_source"] = "worker_claim"
        mutations.append(("source", evidence, "merge_evidence_source"))

        evidence = copy.deepcopy(original)
        evidence["state"] = "open"
        evidence["merged"] = False
        mutations.append(("not-merged", evidence, "pull_request_not_merged"))

        evidence = copy.deepcopy(original)
        evidence["head_commit"] = "4" * 40
        mutations.append(("head", evidence, "merge_head_mismatch"))

        evidence = copy.deepcopy(original)
        evidence["commit_count"] = 2
        mutations.append(("commit-count", evidence, "merge_commit_count"))

        evidence = copy.deepcopy(original)
        evidence["changed_files"][0]["blob_sha"] = "3" * 40
        mutations.append(("blob", evidence, "merge_blob_sha"))

        evidence = copy.deepcopy(original)
        evidence["changed_files"][0]["file_sha256"] = "2" * 64
        mutations.append(("file-hash", evidence, "merged_diff_mismatch"))

        for label, evidence, code in mutations:
            with self.subTest(label=label):
                evidence_path = self.study.root / f"merge-evidence-{label}.json"
                write_json(evidence_path, evidence)
                _, payload = run_cli(
                    *self.study.integration_arguments(
                        merge_evidence=evidence_path,
                        checkpoint_output=self.study.root / f"checkpoint-{label}.zip",
                    ),
                    ok=False,
                )
                self.assertEqual(code, payload["error"]["code"])
        self.assertEqual(frozen_state, self.study.state_path.read_bytes())
        self.assertEqual(frozen_manifest, self.study.manifest_path.read_bytes())

    def test_receipt_compare_and_swap_rejects_change_after_preflight(self) -> None:
        self.study.freeze_benchmark_state()
        frozen_state = self.study.state_path.read_bytes()
        arguments = self.study.integration_arguments()
        parser = preparation.build_parser()
        args = parser.parse_args(arguments)
        real_preflight = preparation.preflight_integration
        changed_bytes = self.study.bound_receipt_path.read_bytes() + b" \n"

        def preflight_then_change_receipt(*call_args, **call_kwargs):
            result = real_preflight(*call_args, **call_kwargs)
            self.study.bound_receipt_path.write_bytes(changed_bytes)
            return result

        with mock.patch.object(
            preparation,
            "preflight_integration",
            side_effect=preflight_then_change_receipt,
        ):
            with self.assertRaises(preparation.PreparationError) as caught:
                args.func(args)
        self.assertEqual("preflight_input_changed", caught.exception.code)
        self.assertIn("receipt", caught.exception.details)
        self.assertEqual(changed_bytes, self.study.bound_receipt_path.read_bytes())
        self.assertEqual(frozen_state, self.study.state_path.read_bytes())

    def test_state_compare_and_swap_preserves_concurrent_change(self) -> None:
        self.study.freeze_benchmark_state()
        frozen_state = self.study.state_path.read_bytes()
        arguments = self.study.integration_arguments()
        parser = preparation.build_parser()
        args = parser.parse_args(arguments)
        real_preflight = preparation.preflight_integration
        changed_bytes = frozen_state + b" \n"

        def preflight_then_change_state(*call_args, **call_kwargs):
            result = real_preflight(*call_args, **call_kwargs)
            self.study.state_path.write_bytes(changed_bytes)
            return result

        with mock.patch.object(
            preparation,
            "preflight_integration",
            side_effect=preflight_then_change_state,
        ):
            with self.assertRaises(preparation.PreparationError) as caught:
                args.func(args)
        self.assertEqual("preflight_input_changed", caught.exception.code)
        self.assertIn("state", caught.exception.details)
        self.assertEqual(changed_bytes, self.study.state_path.read_bytes())
        candidate_root = self.study.root / "candidate" / self.study.candidate_id
        self.assertFalse(any(candidate_root.rglob("*")) if candidate_root.exists() else False)

    def test_persisted_state_is_reloaded_and_disk_divergence_rolls_back(self) -> None:
        self.study.freeze_benchmark_state()
        original_state = self.study.state_path.read_bytes()
        original_manifest = self.study.manifest_path.read_bytes()
        parser = preparation.build_parser()
        args = parser.parse_args(self.study.integration_arguments())
        real_replace = preparation._replace_json_atomic

        def diverge_persisted_state(path: Path, value: dict) -> None:
            real_replace(path, value)
            if path.resolve() == self.study.state_path.resolve():
                changed = read_json(path)
                changed["synthetic_disk_divergence"] = True
                write_json(path, changed)

        with mock.patch.object(
            preparation,
            "_replace_json_atomic",
            side_effect=diverge_persisted_state,
        ):
            with self.assertRaises(preparation.PreparationError) as caught:
                args.func(args)
        self.assertEqual("post_integration_state_mismatch", caught.exception.code)
        self.assertEqual(original_state, self.study.state_path.read_bytes())
        self.assertEqual(original_manifest, self.study.manifest_path.read_bytes())
        self.assertFalse(self.study.checkpoint_path.exists())
        candidate_root = self.study.root / "candidate" / self.study.candidate_id
        self.assertFalse(any(candidate_root.rglob("*")) if candidate_root.exists() else False)

    def test_checkpoint_failure_removes_new_partial_checkpoint(self) -> None:
        self.study.freeze_benchmark_state()
        original_state = self.study.state_path.read_bytes()
        original_manifest = self.study.manifest_path.read_bytes()
        parser = preparation.build_parser()
        args = parser.parse_args(self.study.integration_arguments())

        def fail_after_partial_checkpoint(output: Path, *_args, **_kwargs):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"synthetic partial checkpoint")
            raise OSError("synthetic checkpoint failure")

        with mock.patch.object(
            preparation,
            "create_integration_checkpoint",
            side_effect=fail_after_partial_checkpoint,
        ):
            with self.assertRaisesRegex(OSError, "checkpoint failure"):
                args.func(args)
        self.assertEqual(original_state, self.study.state_path.read_bytes())
        self.assertEqual(original_manifest, self.study.manifest_path.read_bytes())
        self.assertFalse(self.study.checkpoint_path.exists())

    def test_checkpoint_failure_restores_preexisting_checkpoint(self) -> None:
        self.study.freeze_benchmark_state()
        original_state = self.study.state_path.read_bytes()
        original_manifest = self.study.manifest_path.read_bytes()
        prior_checkpoint = b"synthetic prior checkpoint bytes"
        self.study.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        self.study.checkpoint_path.write_bytes(prior_checkpoint)
        parser = preparation.build_parser()
        args = parser.parse_args(
            self.study.integration_arguments(force_checkpoint=True)
        )

        def fail_after_replacing_checkpoint(output: Path, *_args, **_kwargs):
            output.write_bytes(b"synthetic replacement checkpoint")
            raise OSError("synthetic checkpoint replacement failure")

        with mock.patch.object(
            preparation,
            "create_integration_checkpoint",
            side_effect=fail_after_replacing_checkpoint,
        ):
            with self.assertRaisesRegex(OSError, "replacement failure"):
                args.func(args)
        self.assertEqual(original_state, self.study.state_path.read_bytes())
        self.assertEqual(original_manifest, self.study.manifest_path.read_bytes())
        self.assertEqual(prior_checkpoint, self.study.checkpoint_path.read_bytes())

    def test_transaction_rolls_back_if_state_last_write_fails(self) -> None:
        self.study.freeze_benchmark_state()
        self.study.make_merge_evidence()
        original_state = self.study.state_path.read_bytes()
        original_manifest = self.study.manifest_path.read_bytes()
        parser = preparation.build_parser()
        arguments = [
            "integrate",
            *self.study.preflight_arguments(),
            "--merge-evidence", str(self.study.merge_evidence_path),
            "--checkpoint-output", str(self.study.checkpoint_path),
        ]
        args = parser.parse_args(arguments)
        real_replace = preparation._replace_json_atomic

        def fail_on_state(path: Path, value: dict) -> None:
            if path.resolve() == self.study.state_path.resolve():
                raise OSError("synthetic state-last failure")
            real_replace(path, value)

        with mock.patch.object(preparation, "_replace_json_atomic", side_effect=fail_on_state):
            with self.assertRaisesRegex(OSError, "state-last"):
                args.func(args)
        self.assertEqual(original_state, self.study.state_path.read_bytes())
        self.assertEqual(original_manifest, self.study.manifest_path.read_bytes())
        candidate_root = self.study.root / "candidate" / self.study.candidate_id
        self.assertFalse(any(candidate_root.rglob("*")) if candidate_root.exists() else False)
        self.assertFalse(self.study.checkpoint_path.exists())


class CliContractTests(unittest.TestCase):
    def test_help_exposes_all_current_only_subcommands(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(preparation.__file__), "--help"],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, completed.returncode)
        for command in (
            "extract",
            "normalize",
            "validate-private",
            "validate-public",
            "build-worker",
            "bind-publication",
            "preflight-integration",
            "integrate",
        ):
            self.assertIn(command, completed.stdout)

    def test_preflight_requires_exactly_one_pr_or_branch_selector(self) -> None:
        parser = preparation.build_parser()
        required = [
            "preflight-integration",
            "--receipt", "receipt.json",
            "--recovery-zip", "recovery.zip",
            "--public-dir", "public",
            "--state", "state.json",
            "--page-map", "page-map.json",
            "--chunk-manifest", "chunks.json",
            "--policy", "policy.json",
            "--benchmark-file", "benchmark.json",
            "--publication-evidence", "publication-evidence.json",
            "--benchmark-proof", "benchmark-proof.json",
            "--benchmark-project", "example/benchmark",
            "--benchmark-ref", BENCHMARK_COMMIT,
        ]
        with mock.patch.object(argparse.ArgumentParser, "error", side_effect=RuntimeError("selector required")):
            with self.assertRaisesRegex(RuntimeError, "selector required"):
                parser.parse_args(required)


if __name__ == "__main__":
    unittest.main()
