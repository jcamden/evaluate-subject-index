#!/usr/bin/env python3
"""Synthetic tests for vendor-neutral candidate layout adapters."""

from __future__ import annotations

import copy
import hashlib
import re
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from candidate_layout_adapters import (  # noqa: E402
    ADAPTER_IDS,
    extract_candidate_layout,
    list_adapter_ids,
    validate_layout_contract,
)


def layout_regions(layout: dict) -> list[dict]:
    return [region for page in layout["pages"] for region in page["regions"]]


def layout_lines(layout: dict, include_excluded: bool = True) -> list[dict]:
    lines = [line for region in layout_regions(layout) for line in region["lines"]]
    return lines if include_excluded else [line for line in lines if not line.get("excluded_from_index", False)]


def synthetic_two_page_geometry(producer: str = "ReportLab PDF Library - synthetic") -> dict:
    return {
        "file_name": "synthetic-candidate.pdf",
        "metadata": {"producer": producer, "title": "Synthetic layout fixture"},
        "pages": [
            {
                "page_number": 1,
                "width": 600,
                "height": 800,
                "lines": [
                    {"bbox": [220, 20, 380, 35], "text": "Synthetic Index"},
                    {"bbox": [50, 100, 250, 112], "text": "Café society, 11–13"},
                    {"bbox": [68, 120, 285, 132], "text": "L'école, 14; see also Élan vital"},
                    {"bbox": [68, 680, 240, 692], "text": "continued discussion,"},
                    {"bbox": [338, 100, 520, 112], "text": "and later examples, 15"},
                    {"bbox": [320, 120, 500, 132], "text": "O’Connor, 20"},
                    {"bbox": [320, 140, 540, 152], "text": "M a r í a ’ s, 21–23"},
                    {"bbox": [295, 780, 305, 791], "text": "1"},
                ],
            },
            {
                "page_number": 2,
                "width": 600,
                "height": 800,
                "lines": [
                    {"bbox": [220, 20, 380, 35], "text": "Synthetic Index"},
                    {"bbox": [68, 100, 285, 112], "text": "continued on next page, 24"},
                    {"bbox": [50, 120, 230, 132], "text": "Zulu, 25"},
                    {"bbox": [320, 100, 500, 112], "text": "Beta, 26"},
                    {"bbox": [320, 120, 500, 132], "text": "Gamma, 27"},
                    {"bbox": [295, 780, 305, 791], "text": "2"},
                ],
            },
        ],
    }


class GeometryAdapterTests(unittest.TestCase):
    def test_adapter_ids_are_exposed(self) -> None:
        self.assertEqual(
            ("auto", "generic-pdf-layout", "indexerlabs-two-column"),
            ADAPTER_IDS,
        )
        self.assertEqual(ADAPTER_IDS, list_adapter_ids())

    def test_reportlab_profile_preserves_layout_evidence(self) -> None:
        layout = extract_candidate_layout(
            Path("never-opened.pdf"),
            "synthetic-two-column",
            geometry=synthetic_two_page_geometry(),
        )
        self.assertEqual([], validate_layout_contract(layout))
        self.assertEqual("candidate-layout-extraction-v1", layout["schema_version"])
        self.assertRegex(layout["candidate_sha256"], re.compile(r"^[a-f0-9]{64}$"))
        self.assertEqual(layout["candidate_sha256"], layout["pdf_metadata"]["sha256"])
        self.assertEqual("indexerlabs-two-column", layout["adapter_id"])
        self.assertEqual("reportlab_producer_metadata", layout["adapter"]["selection_reason"])
        self.assertFalse(layout["adapter"]["selection_evidence"]["content_vocabulary_used"])
        self.assertEqual(2, layout["pdf_metadata"]["page_count"])
        self.assertEqual("ReportLab PDF Library - synthetic", layout["pdf_metadata"]["producer"])

        page_one = [line for line in layout_lines(layout, include_excluded=False) if line["candidate_pdf_page"] == 1]
        self.assertEqual(
            [
                "Café society, 11–13",
                "L'école, 14; see also Élan vital",
                "continued discussion,",
                "and later examples, 15",
                "O’Connor, 20",
                "María’s, 21–23",
            ],
            [line["displayed_line_text"] for line in page_one],
        )
        self.assertEqual([1, 1, 1, 2, 2, 2], [line["column"] for line in page_one])

        by_text = {line["displayed_line_text"]: line for line in layout_lines(layout, include_excluded=False)}
        self.assertEqual(0, by_text["Café society, 11–13"]["indentation_level"])
        self.assertEqual(1, by_text["L'école, 14; see also Élan vital"]["indentation_level"])
        self.assertEqual("continued_from_previous_column", by_text["and later examples, 15"]["continuation_status"])
        self.assertEqual("continues_next_column", by_text["continued discussion,"]["continuation_status"])
        self.assertEqual("continued_from_previous_page", by_text["continued on next page, 24"]["continuation_status"])
        self.assertEqual("continuation", by_text["continued on next page, 24"]["inferred_boundary"])

        repaired = by_text["María’s, 21–23"]
        self.assertEqual("M a r í a ’ s, 21–23", repaired["original_displayed_form"])
        self.assertIn("repaired_visual_character_spacing", repaired["extraction_warnings"])
        self.assertEqual(4, layout["counts"]["excluded_lines"])
        self.assertEqual(2, layout["counts"]["excluded_repeated_headers"])
        self.assertEqual(2, layout["counts"]["excluded_page_number_footers"])
        headers = [line for line in layout_lines(layout) if line.get("inferred_boundary") == "header_footer"]
        self.assertEqual(4, len(headers))
        self.assertTrue(all(line["excluded_from_index"] for line in headers))
        self.assertNotIn("Synthetic Index", [line["displayed_line_text"] for line in layout_lines(layout, False)])

    def test_auto_uses_geometry_and_never_index_vocabulary(self) -> None:
        geometry = synthetic_two_page_geometry(producer="Unrelated PDF engine")
        layout = extract_candidate_layout(Path("unused.pdf"), "geometry-auto", geometry=geometry)
        self.assertEqual("indexerlabs-two-column", layout["adapter_id"])
        self.assertEqual("two_column_geometry", layout["adapter"]["selection_reason"])

        single_column = {
            "metadata": {"producer": "Unrelated PDF engine"},
            "pages": [
                {
                    "width": 600,
                    "height": 800,
                    "lines": [
                        {"bbox": [50, 100, 400, 112], "text": "Index entry, 1; see also Another"},
                        {"bbox": [50, 120, 400, 132], "text": "Locator-rich heading, 2–4"},
                    ],
                }
            ],
        }
        generic = extract_candidate_layout(Path("unused.pdf"), "vocabulary-proof", geometry=single_column)
        self.assertEqual("generic-pdf-layout", generic["adapter_id"])
        self.assertEqual("generic_geometry", generic["adapter"]["selection_reason"])

        explicit = extract_candidate_layout(
            Path("unused.pdf"),
            "explicit-reportlab-profile",
            adapter_id="indexerlabs-two-column",
            geometry=geometry,
        )
        self.assertEqual("indexerlabs-two-column", explicit["adapter_id"])
        self.assertEqual("explicit_adapter", explicit["adapter"]["selection_reason"])

    def test_geometry_path_does_not_import_pymupdf(self) -> None:
        real_import = __import__

        def guarded_import(name: str, *args, **kwargs):
            if name == "fitz":
                raise AssertionError("geometry extraction must not import PyMuPDF")
            return real_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=guarded_import):
            layout = extract_candidate_layout(
                Path("never-opened.pdf"), "lazy-import", geometry=synthetic_two_page_geometry()
            )
        self.assertEqual([], validate_layout_contract(layout))

    def test_explicit_generic_is_geometry_aware_and_ids_are_stable(self) -> None:
        geometry = synthetic_two_page_geometry(producer="Neutral producer")
        first = extract_candidate_layout(
            Path("unused.pdf"), "stable-candidate", adapter_id="generic-pdf-layout", geometry=geometry
        )
        second = extract_candidate_layout(
            Path("unused.pdf"), "stable-candidate", adapter_id="generic-pdf-layout", geometry=geometry
        )
        self.assertEqual("generic-pdf-layout", first["adapter_id"])
        self.assertEqual(
            [line["line_id"] for line in layout_lines(first)],
            [line["line_id"] for line in layout_lines(second)],
        )
        self.assertEqual(
            [region["region_id"] for region in layout_regions(first)],
            [region["region_id"] for region in layout_regions(second)],
        )
        self.assertTrue(all(page["two_column_layout"] for page in first["pages"]))

    def test_geometry_candidate_hash_sources_are_deterministic(self) -> None:
        geometry = synthetic_two_page_geometry()
        first = extract_candidate_layout(Path("absent.pdf"), "hash-a", geometry=geometry)
        second = extract_candidate_layout(Path("absent.pdf"), "hash-b", geometry=geometry)
        self.assertEqual(first["candidate_sha256"], second["candidate_sha256"])

        supplied = copy.deepcopy(geometry)
        supplied["sha256"] = "a" * 64
        supplied_layout = extract_candidate_layout(Path("absent.pdf"), "hash-supplied", geometry=supplied)
        self.assertEqual("a" * 64, supplied_layout["candidate_sha256"])
        self.assertEqual("a" * 64, supplied_layout["pdf_metadata"]["sha256"])

        with tempfile.TemporaryDirectory() as directory:
            candidate_path = Path(directory) / "candidate.pdf"
            candidate_path.write_bytes(b"synthetic candidate bytes")
            byte_layout = extract_candidate_layout(candidate_path, "hash-bytes", geometry=geometry)
            self.assertEqual(hashlib.sha256(candidate_path.read_bytes()).hexdigest(), byte_layout["candidate_sha256"])

    def test_unknown_extraction_adapter_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown adapter"):
            extract_candidate_layout(
                Path("unused.pdf"), "bad-adapter", adapter_id="future-adapter", geometry=synthetic_two_page_geometry()
            )


class PdfRuntimeTests(unittest.TestCase):
    def test_two_page_pdf_is_generated_and_extracted_at_runtime(self) -> None:
        try:
            import fitz
        except ImportError:  # pragma: no cover - runtime dependency is expected
            self.skipTest("PyMuPDF is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic-layout.pdf"
            document = fitz.open()
            document.set_metadata(
                {"producer": "ReportLab PDF Library - synthetic runtime fixture", "title": "Synthetic candidate"}
            )
            for page_number in (1, 2):
                page = document.new_page(width=612, height=792)
                page.insert_text((225, 28), "Synthetic Index", fontsize=9)
                page.insert_text((50, 100), "Alpha, 10-12" if page_number == 1 else "continued, 16", fontsize=10)
                page.insert_text((68 if page_number == 1 else 50, 120), "Beta, 13" if page_number == 1 else "Café d'Arc, 17", fontsize=10)
                page.insert_text((338 if page_number == 1 else 320, 100), "and more, 14" if page_number == 1 else "Delta, 18", fontsize=10)
                page.insert_text((320, 120), "Gamma, 15" if page_number == 1 else "Echo, 19", fontsize=10)
                page.insert_text((300, 780), str(page_number), fontsize=8)
            document.save(path)
            document.close()

            layout = extract_candidate_layout(path, "runtime-pdf")
            self.assertEqual([], validate_layout_contract(layout))
            self.assertEqual("indexerlabs-two-column", layout["adapter_id"])
            self.assertEqual(2, layout["counts"]["pages"])
            self.assertRegex(layout["pdf_metadata"]["sha256"], re.compile(r"^[a-f0-9]{64}$"))
            self.assertEqual(path.stat().st_size, layout["pdf_metadata"]["byte_length"])
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), layout["candidate_sha256"])
            self.assertEqual(4, layout["counts"]["excluded_lines"])
            texts = [line["displayed_line_text"] for line in layout_lines(layout, include_excluded=False)]
            self.assertIn("Café d'Arc, 17", texts)
            page_one = [line for line in layout_lines(layout, include_excluded=False) if line["candidate_pdf_page"] == 1]
            self.assertEqual([1, 1, 2, 2], [line["column"] for line in page_one])
            self.assertEqual(["Alpha, 10-12", "Beta, 13", "and more, 14", "Gamma, 15"], [line["displayed_line_text"] for line in page_one])


class ContractValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.layout = extract_candidate_layout(
            Path("unused.pdf"), "contract-candidate", geometry=synthetic_two_page_geometry()
        )

    def test_future_adapter_can_emit_the_same_contract(self) -> None:
        future = copy.deepcopy(self.layout)
        future["adapter_id"] = "future-xml-layout"
        future["adapter_version"] = "9.1.0"
        future["adapter"]["id"] = "future-xml-layout"
        future["adapter"]["version"] = "9.1.0"
        future["adapter"]["requested_id"] = "future-xml-layout"
        self.assertEqual([], validate_layout_contract(future))

    def test_contract_catches_duplicate_ids_and_count_drift(self) -> None:
        invalid = copy.deepcopy(self.layout)
        lines = layout_lines(invalid, include_excluded=False)
        lines[1]["line_id"] = lines[0]["line_id"]
        invalid["counts"]["lines"] += 1
        errors = validate_layout_contract(invalid)
        self.assertTrue(any("duplicate line_id" in error for error in errors))
        self.assertTrue(any("counts.lines" in error for error in errors))
        self.assertTrue(any("line_ids must match nested lines" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
