#!/usr/bin/env python3
"""Convert common subject-index exports to the evaluator's layout contract.

This standalone utility stops at layout evidence. It does not repair editorial
content, inspect a source benchmark, or belong to the evaluation skill. PyMuPDF
is imported only for PDF input.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
import sys
import unicodedata
import urllib.request
from collections import Counter, defaultdict
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "candidate-layout-extraction-v1"
ADAPTER_VERSIONS = {
    "auto": "1.0.0",
    "generic-pdf-layout": "1.0.0",
    "indexerlabs-two-column": "1.0.0",
    "indexia-html": "1.0.0",
    "markdown-list": "1.0.0",
    "plain-text": "1.0.0",
}
ADAPTER_IDS = tuple(ADAPTER_VERSIONS)

_CONTINUATION_VALUES = {
    "standalone",
    "continues_previous",
    "continued_from_previous_column",
    "continued_from_previous_page",
    "continues_next_column",
    "continues_next_page",
}
_BOUNDARY_VALUES = {"main_entry", "subentry", "continuation", "header_footer", "unknown"}
_PAGE_TOKEN = re.compile(r"^[\s\-\u2010-\u2015]*(?:\d+|[ivxlcdm]+)[\s\-\u2010-\u2015]*$", re.I)


def list_adapter_ids() -> tuple[str, ...]:
    """Return the adapter identifiers accepted by :func:`extract_candidate_layout`."""

    return ADAPTER_IDS


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _stable_id(prefix: str, *parts: Any) -> str:
    encoded = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{prefix}-{hashlib.sha256(encoded.encode('utf-8')).hexdigest()[:20]}"


def _bbox(value: Any) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError(f"bbox must contain four numbers, got {value!r}")
    result = [round(float(item), 3) for item in value]
    if not all(math.isfinite(item) for item in result):
        raise ValueError(f"bbox contains a non-finite value: {value!r}")
    if result[2] < result[0] or result[3] < result[1]:
        raise ValueError(f"bbox is inverted: {value!r}")
    return result


def _bbox_union(values: Iterable[list[float]]) -> list[float]:
    boxes = list(values)
    if not boxes:
        return [0.0, 0.0, 0.0, 0.0]
    return [
        round(min(value[0] for value in boxes), 3),
        round(min(value[1] for value in boxes), 3),
        round(max(value[2] for value in boxes), 3),
        round(max(value[3] for value in boxes), 3),
    ]


def _line_text_from_spans(spans: list[dict[str, Any]]) -> str:
    pieces: list[str] = []
    previous: dict[str, Any] | None = None
    for span in sorted(spans, key=lambda item: (item["bbox"][0], item["bbox"][1])):
        text = str(span.get("text", ""))
        if not text:
            continue
        if previous is not None and pieces and not pieces[-1].endswith((" ", "\t")) and not text.startswith((" ", "\t")):
            gap = span["bbox"][0] - previous["bbox"][2]
            size = max(float(span.get("size", 0.0)), float(previous.get("size", 0.0)), 8.0)
            if gap > max(1.2, size * 0.16):
                pieces.append(" ")
        pieces.append(text)
        previous = span
    return "".join(pieces).strip()


def _coalesce_pdf_fragments(lines: list[dict[str, Any]], page_width: float) -> list[dict[str, Any]]:
    """Merge adjacent same-baseline fragments without joining separate columns."""

    merged: list[dict[str, Any]] = []
    for line in sorted(lines, key=lambda item: (item["bbox"][1], item["bbox"][0], item["source_order"])):
        target: dict[str, Any] | None = None
        line_box = line["bbox"]
        line_height = max(1.0, line_box[3] - line_box[1])
        for candidate in reversed(merged[-8:]):
            box = candidate["bbox"]
            height = max(1.0, box[3] - box[1])
            center_delta = abs((line_box[1] + line_box[3]) / 2 - (box[1] + box[3]) / 2)
            gap = line_box[0] - box[2]
            same_half = (line_box[0] < page_width / 2) == (box[0] < page_width / 2)
            if same_half and center_delta <= max(2.0, min(line_height, height) * 0.3) and -1.0 <= gap <= max(18.0, height * 1.6):
                target = candidate
                break
        if target is None:
            merged.append(dict(line))
            continue
        target["spans"] = sorted(target.get("spans", []) + line.get("spans", []), key=lambda item: item["bbox"][0])
        target["bbox"] = _bbox_union([target["bbox"], line["bbox"]])
        target["font_size"] = max(float(target.get("font_size", 0.0)), float(line.get("font_size", 0.0)))
        target["original_displayed_form"] = _line_text_from_spans(target["spans"])
        target["source_order"] = min(target["source_order"], line["source_order"])
    return merged


def _extract_pdf_geometry(path: Path) -> dict[str, Any]:
    try:
        import pymupdf as fitz  # type: ignore[import-not-found]  # lazy by design
    except ImportError as exc:  # pragma: no cover - depends on runtime packaging
        raise RuntimeError("PyMuPDF is required to extract candidate PDF geometry") from exc

    if not path.is_file():
        raise FileNotFoundError(f"Candidate PDF does not exist: {path}")
    try:
        document = fitz.open(str(path))
    except Exception as exc:
        raise ValueError(f"Could not open candidate PDF {path.name}: {exc}") from exc
    try:
        if document.needs_pass:
            raise ValueError("Candidate PDF is encrypted and requires a password")
        metadata = dict(document.metadata or {})
        pages: list[dict[str, Any]] = []
        for page_index, page in enumerate(document):
            page_dict = page.get_text("dict", sort=False)
            raw_lines: list[dict[str, Any]] = []
            source_order = 0
            for block in page_dict.get("blocks", []):
                if block.get("type", 0) != 0:
                    continue
                for source_line in block.get("lines", []):
                    spans: list[dict[str, Any]] = []
                    for source_span in source_line.get("spans", []):
                        text = str(source_span.get("text", ""))
                        if not text:
                            continue
                        spans.append(
                            {
                                "text": text,
                                "bbox": _bbox(source_span.get("bbox", source_line.get("bbox"))),
                                "size": float(source_span.get("size", 0.0)),
                            }
                        )
                    if not spans:
                        continue
                    source_order += 1
                    raw_lines.append(
                        {
                            "bbox": _bbox(source_line.get("bbox", _bbox_union([span["bbox"] for span in spans]))),
                            "spans": spans,
                            "font_size": statistics.median([span["size"] for span in spans if span["size"] > 0])
                            if any(span["size"] > 0 for span in spans)
                            else 10.0,
                            "original_displayed_form": _line_text_from_spans(spans),
                            "source_order": source_order,
                            "extraction_warnings": [],
                        }
                    )
            width = float(page.rect.width)
            pages.append(
                {
                    "candidate_pdf_page": page_index + 1,
                    "width": round(width, 3),
                    "height": round(float(page.rect.height), 3),
                    "lines": _coalesce_pdf_fragments(raw_lines, width),
                }
            )
        return {
            "metadata": metadata,
            "pages": pages,
            "file_name": path.name,
            "sha256": _sha256_file(path),
            "byte_length": path.stat().st_size,
            "is_pdf": bool(document.is_pdf),
            "is_encrypted": bool(document.is_encrypted),
        }
    finally:
        document.close()


def _read_text(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"Candidate index does not exist: {path}")
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(f"Candidate index is not valid UTF-8: {path.name}") from exc


def _text_raw(path: Path, adapter_id: str, entries: list[tuple[int, str]]) -> dict[str, Any]:
    if not entries:
        raise ValueError(f"No index entries were found in {path.name}")
    lines: list[dict[str, Any]] = []
    for source_order, (indent, displayed) in enumerate(entries, 1):
        x0 = 50.0 + indent * 18.0
        y0 = 50.0 + len(lines) * 14.0
        lines.append(
            {
                "bbox": [x0, y0, min(600.0, x0 + max(20.0, len(displayed) * 5.0)), y0 + 10.0],
                "spans": [],
                "font_size": 10.0,
                "original_displayed_form": displayed,
                "source_order": source_order,
                "extraction_warnings": [],
            }
        )
    format_names = {
        "indexia-html": "Indexia HTML",
        "markdown-list": "Markdown",
        "plain-text": "Plain text",
    }
    limitations = ["Non-PDF inputs use one logical candidate page for provenance."]
    if adapter_id == "plain-text":
        limitations.append("Plain text preserves only hierarchy expressed with leading whitespace.")
    return {
        "metadata": {"format": format_names[adapter_id]},
        "pages": [{
            "candidate_pdf_page": 1,
            "width": 612.0,
            "height": max(792.0, 72.0 + len(lines) * 14.0),
            "lines": lines,
        }],
        "file_name": path.name,
        "sha256": _sha256_file(path),
        "byte_length": path.stat().st_size,
        "is_pdf": False,
        "is_encrypted": False,
        "text_adapter": adapter_id,
        "limitations": limitations,
    }


def _extract_markdown_geometry(path: Path) -> dict[str, Any]:
    entries: list[tuple[int, str]] = []
    for original in _read_text(path).splitlines():
        if not original.strip() or re.match(r"^\s{0,3}#{1,6}\s+", original):
            continue
        match = re.match(r"^(\s*)[-+*]\s+(.*)$", original)
        if not match:
            continue
        leading, displayed = match.groups()
        displayed = re.sub(r"(?i)\*(see(?:\s+also)?(?:\s+under)?)\*", r"\1", displayed).strip()
        if displayed:
            entries.append((len(leading.expandtabs(4)) // 4, displayed))
    return _text_raw(path, "markdown-list", entries)


def _extract_plain_text_geometry(path: Path) -> dict[str, Any]:
    entries: list[tuple[int, str]] = []
    first_content = True
    for original in _read_text(path).splitlines():
        if not original.strip():
            continue
        displayed = original.strip()
        if first_content and displayed.casefold() in {"index", "subject index"}:
            first_content = False
            continue
        first_content = False
        leading = len(original.expandtabs(4)) - len(original.expandtabs(4).lstrip())
        entries.append((leading // 4, displayed))
    return _text_raw(path, "plain-text", entries)


class _ScriptCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_script = False
        self.scripts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() == "script":
            self.in_script = True
            self.scripts.append("")

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "script":
            self.in_script = False

    def handle_data(self, data: str) -> None:
        if self.in_script:
            self.scripts[-1] += data


def _find_initial_data(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        initial = value.get("initialData")
        if isinstance(initial, dict) and isinstance(initial.get("terms"), list):
            return initial
        for child in value.values():
            found = _find_initial_data(child)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_initial_data(child)
            if found is not None:
                return found
    return None


def _indexia_initial_data(html: str) -> dict[str, Any]:
    parser = _ScriptCollector()
    parser.feed(html)
    for script in parser.scripts:
        match = re.fullmatch(r"\s*self\.__next_f\.push\((.*)\)\s*", script, re.S)
        if not match:
            continue
        try:
            wrapper = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if not isinstance(wrapper, list) or len(wrapper) < 2 or not isinstance(wrapper[1], str):
            continue
        payload = wrapper[1]
        separator = payload.find(":")
        if separator < 0 or "initialData" not in payload:
            continue
        try:
            decoded = json.loads(payload[separator + 1:].strip())
        except json.JSONDecodeError:
            continue
        initial = _find_initial_data(decoded)
        if initial is not None:
            return initial
    raise ValueError("Indexia initialData.terms was not found in the HTML snapshot")


def _extract_indexia_html_geometry(path: Path) -> dict[str, Any]:
    terms = _indexia_initial_data(_read_text(path))["terms"]
    terms = [term for term in terms if isinstance(term, dict)]
    by_id = {term.get("termId"): term for term in terms if isinstance(term.get("termId"), str)}
    children: dict[str, list[dict[str, Any]]] = defaultdict(list)
    mains: list[dict[str, Any]] = []
    orphans: list[dict[str, Any]] = []
    for term in terms:
        parent_id = term.get("parentTermId")
        if term.get("isSubentry") is True and isinstance(parent_id, str) and parent_id in by_id:
            children[parent_id].append(term)
        elif term.get("isSubentry") is True:
            orphans.append(term)
        else:
            mains.append(term)

    def printable(term: dict[str, Any]) -> bool:
        return bool(term.get("pages") or term.get("crossReferences") or children.get(str(term.get("termId"))))

    def compact_pages(values: list[Any]) -> list[str]:
        result: list[str] = []
        index = 0
        while index < len(values):
            value = values[index]
            if not isinstance(value, int) or isinstance(value, bool):
                result.append(str(value))
                index += 1
                continue
            end = index
            while end + 1 < len(values) and isinstance(values[end + 1], int) and values[end + 1] == values[end] + 1:
                end += 1
            if end == index:
                result.append(str(value))
            else:
                last = values[end]
                end_display = f"{last % 100:02d}" if value >= 100 and value // 100 == last // 100 else str(last)
                result.append(f"{value}–{end_display}")
            index = end + 1
        return result

    def displayed(term: dict[str, Any], include_pages: bool = True) -> str:
        heading = str(term.get("termName", "")).strip()
        pages = term.get("pages") if include_pages and isinstance(term.get("pages"), list) else []
        locators = compact_pages([page for page in pages if isinstance(page, (str, int)) and not isinstance(page, bool)])
        references: list[str] = []
        for reference in term.get("crossReferences", []) if isinstance(term.get("crossReferences"), list) else []:
            if not isinstance(reference, dict) or reference.get("source_id") != term.get("termId"):
                continue
            target = by_id.get(reference.get("target_id"))
            target_name = str(target.get("termName", "")).strip() if target else ""
            if target_name:
                label = "see also" if reference.get("reference_type") == "see_also" else "see"
                references.append(f"{label} {target_name}")
        payload = ", ".join(locators)
        if references:
            payload = "; ".join(filter(None, [payload, *references]))
        return ", ".join(filter(None, [heading, payload]))

    entries: list[tuple[int, str]] = []
    for main in mains:
        if not printable(main):
            continue
        main_children = children.get(str(main.get("termId")), [])
        child_pages = {
            page
            for child in main_children
            for page in (child.get("pages") if isinstance(child.get("pages"), list) else [])
            if isinstance(page, (str, int)) and not isinstance(page, bool)
        }
        main_pages = {
            page
            for page in (main.get("pages") if isinstance(main.get("pages"), list) else [])
            if isinstance(page, (str, int)) and not isinstance(page, bool)
        }
        text = displayed(main, include_pages=not child_pages or main_pages != child_pages)
        if text:
            entries.append((0, text))
        for child in main_children:
            if not printable(child):
                continue
            text = displayed(child)
            if text:
                entries.append((1, text))
    for orphan in orphans:
        if not printable(orphan):
            continue
        text = displayed(orphan)
        if text:
            entries.append((0, text))
    raw = _text_raw(path, "indexia-html", entries)
    if orphans:
        raw["limitations"].append(f"{len(orphans)} orphaned Indexia subentries were retained at top level.")
    return raw


def _input_adapter(path: Path, requested: str) -> str:
    if requested != "auto":
        return requested
    suffix = path.suffix.casefold()
    if suffix in {".html", ".htm"}:
        return "indexia-html"
    if suffix in {".md", ".markdown"}:
        return "markdown-list"
    if suffix == ".txt":
        return "plain-text"
    if path.is_file() and path.read_bytes()[:5] == b"%PDF-":
        return "generic-pdf-layout"
    raise ValueError("Could not detect candidate format; use PDF, .html/.htm, .md/.markdown, or .txt")


def _raw_line_from_geometry(value: dict[str, Any], source_order: int) -> dict[str, Any]:
    spans: list[dict[str, Any]] = []
    for source_span in value.get("spans", []) if isinstance(value.get("spans", []), list) else []:
        if not isinstance(source_span, dict):
            continue
        spans.append(
            {
                "text": str(source_span.get("text", "")),
                "bbox": _bbox(source_span.get("bbox", value.get("bbox"))),
                "size": float(source_span.get("size", value.get("font_size", 10.0))),
            }
        )
    original = value.get("original_displayed_form")
    if original is None:
        original = value.get("text", value.get("displayed_line_text"))
    if original is None and spans:
        original = _line_text_from_spans(spans)
    if not isinstance(original, str):
        raise ValueError(f"Synthetic geometry line {source_order} has no text")
    box_value = value.get("bbox")
    if box_value is None and spans:
        box_value = _bbox_union([span["bbox"] for span in spans])
    warnings = value.get("extraction_warnings", [])
    if not isinstance(warnings, list) or not all(isinstance(item, str) for item in warnings):
        raise ValueError("Synthetic extraction_warnings must be an array of strings")
    return {
        "bbox": _bbox(box_value),
        "spans": spans,
        "font_size": float(value.get("font_size", statistics.median([span["size"] for span in spans]) if spans else 10.0)),
        "original_displayed_form": original.strip("\r\n"),
        "source_order": int(value.get("source_order", source_order)),
        "extraction_warnings": list(warnings),
        "continuation_status_hint": value.get("continuation_status"),
        "inferred_boundary_hint": value.get("inferred_boundary"),
        "confidence_hint": value.get("confidence"),
    }


def _normalize_geometry(geometry: dict[str, Any], candidate_path: Path) -> dict[str, Any]:
    if not isinstance(geometry, dict):
        raise TypeError("geometry must be a dictionary")
    page_values = geometry.get("pages")
    if not isinstance(page_values, list):
        raise ValueError("geometry.pages must be an array")
    pages: list[dict[str, Any]] = []
    seen_pages: set[int] = set()
    for page_index, value in enumerate(page_values):
        if not isinstance(value, dict):
            raise ValueError("Every synthetic geometry page must be an object")
        page_number = value.get("candidate_pdf_page", value.get("page_number", page_index + 1))
        if not isinstance(page_number, int) or isinstance(page_number, bool) or page_number < 1:
            raise ValueError("Synthetic candidate PDF page numbers must be positive integers")
        if page_number in seen_pages:
            raise ValueError(f"Duplicate synthetic candidate PDF page: {page_number}")
        seen_pages.add(page_number)
        line_values = value.get("lines", [])
        if not isinstance(line_values, list):
            raise ValueError("Synthetic geometry page lines must be an array")
        if not all(isinstance(item, dict) for item in line_values):
            raise ValueError("Every synthetic geometry line must be an object")
        lines = [_raw_line_from_geometry(item, index + 1) for index, item in enumerate(line_values)]
        max_x = max((line["bbox"][2] for line in lines), default=612.0)
        max_y = max((line["bbox"][3] for line in lines), default=792.0)
        pages.append(
            {
                "candidate_pdf_page": page_number,
                "width": round(float(value.get("width", max_x)), 3),
                "height": round(float(value.get("height", max_y)), 3),
                "lines": lines,
            }
        )
    pages.sort(key=lambda item: item["candidate_pdf_page"])
    metadata = geometry.get("metadata", geometry.get("pdf_metadata", {}))
    if not isinstance(metadata, dict):
        raise ValueError("geometry metadata must be an object")
    if isinstance(metadata.get("metadata"), dict):
        metadata = {**metadata["metadata"], **{key: item for key, item in metadata.items() if key != "metadata"}}
    supplied_sha = geometry.get("sha256")
    if isinstance(supplied_sha, str) and re.fullmatch(r"[a-f0-9]{64}", supplied_sha):
        candidate_sha = supplied_sha
    elif candidate_path.is_file():
        candidate_sha = _sha256_file(candidate_path)
    else:
        canonical_geometry = json.dumps(geometry, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        candidate_sha = hashlib.sha256(canonical_geometry.encode("utf-8")).hexdigest()
    byte_length = geometry.get("byte_length")
    if byte_length is None and candidate_path.is_file():
        byte_length = candidate_path.stat().st_size
    return {
        "metadata": metadata,
        "pages": pages,
        "file_name": str(geometry.get("file_name", candidate_path.name)),
        "sha256": candidate_sha,
        "byte_length": byte_length,
        "is_pdf": bool(geometry.get("is_pdf", True)),
        "is_encrypted": bool(geometry.get("is_encrypted", False)),
    }


def _signature(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold().strip()
    normalized = re.sub(r"\s+", " ", normalized)
    if sum(character.isalpha() for character in normalized) >= 4:
        normalized = re.sub(r"\d+", "#", normalized)
    return normalized


def _exclude_headers_and_footers(pages: list[dict[str, Any]], candidate_id: str) -> list[dict[str, Any]]:
    signatures: Counter[tuple[str, str]] = Counter()
    for page in pages:
        height = page["height"]
        per_page: set[tuple[str, str]] = set()
        for line in page["lines"]:
            band = "top" if line["bbox"][1] <= height * 0.12 else "bottom" if line["bbox"][3] >= height * 0.88 else "body"
            if band != "body":
                per_page.add((band, _signature(line["original_displayed_form"])))
        signatures.update(per_page)

    excluded: list[dict[str, Any]] = []
    page_count = max(1, len(pages))
    for page in pages:
        retained: list[dict[str, Any]] = []
        for occurrence, line in enumerate(page["lines"], 1):
            height = page["height"]
            band = "top" if line["bbox"][1] <= height * 0.12 else "bottom" if line["bbox"][3] >= height * 0.88 else "body"
            text = line["original_displayed_form"]
            reason: str | None = None
            if band == "bottom" and _PAGE_TOKEN.fullmatch(text.strip()):
                reason = "page_number_footer"
            elif band != "body" and signatures[(band, _signature(text))] >= 2 and signatures[(band, _signature(text))] / page_count >= 0.5:
                reason = "repeated_page_header" if band == "top" else "repeated_page_footer"
            if reason is None:
                retained.append(line)
                continue
            excluded.append(
                {
                    "excluded_line_id": _stable_id(
                        "excluded", candidate_id, page["candidate_pdf_page"], line["bbox"], text, occurrence
                    ),
                    "candidate_pdf_page": page["candidate_pdf_page"],
                    "bbox": line["bbox"],
                    "original_displayed_form": text,
                    "reason": reason,
                    "confidence": 0.99 if reason == "page_number_footer" else 0.96,
                }
            )
        page["lines"] = retained
    return excluded


def _column_split(page: dict[str, Any], profile: str) -> tuple[bool, float, float]:
    lines = page["lines"]
    width = page["width"]
    if len(lines) < 2:
        return False, width / 2, 0.0
    starts = sorted(set(round(line["bbox"][0], 2) for line in lines))
    if len(starts) < 2:
        return False, width / 2, 0.0
    gaps = [(starts[index + 1] - starts[index], index) for index in range(len(starts) - 1)]
    largest_gap, gap_index = max(gaps)
    threshold = (starts[gap_index] + starts[gap_index + 1]) / 2
    left = [line for line in lines if line["bbox"][0] < threshold]
    right = [line for line in lines if line["bbox"][0] >= threshold]
    minimum_gap = width * (0.12 if profile == "indexerlabs-two-column" else 0.17)
    balanced_enough = bool(left and right) and min(len(left), len(right)) / len(lines) >= (0.10 if profile == "indexerlabs-two-column" else 0.18)
    plausible_position = threshold >= width * 0.30 and threshold <= width * 0.70
    detected = largest_gap >= minimum_gap and balanced_enough and plausible_position
    confidence = min(0.99, 0.60 + largest_gap / max(width, 1.0)) if detected else 0.0
    return detected, threshold if detected else width / 2, round(confidence, 3)


def _select_adapter(requested: str, raw: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    if requested not in ADAPTER_VERSIONS:
        raise ValueError(f"Unknown adapter {requested!r}; expected one of {', '.join(ADAPTER_IDS)}")
    text_adapter = raw.get("text_adapter")
    if text_adapter:
        return str(text_adapter), "explicit_adapter" if requested != "auto" else "file_extension", {
            "input_format": raw.get("metadata", {}).get("format"),
            "file_extension": Path(str(raw.get("file_name", ""))).suffix.casefold(),
            "content_vocabulary_used": False,
        }
    producer = str(raw.get("metadata", {}).get("producer", ""))
    detected_pages = 0
    nonempty_pages = 0
    for page in raw["pages"]:
        if page["lines"]:
            nonempty_pages += 1
            if _column_split(page, "indexerlabs-two-column")[0]:
                detected_pages += 1
    ratio = detected_pages / nonempty_pages if nonempty_pages else 0.0
    evidence = {
        "producer_reportlab": "reportlab" in producer.casefold(),
        "two_column_pages": detected_pages,
        "nonempty_pages": nonempty_pages,
        "two_column_page_ratio": round(ratio, 3),
        "content_vocabulary_used": False,
    }
    if requested != "auto":
        return requested, "explicit_adapter", evidence
    if evidence["producer_reportlab"]:
        return "indexerlabs-two-column", "reportlab_producer_metadata", evidence
    if nonempty_pages and ratio >= 0.5:
        return "indexerlabs-two-column", "two_column_geometry", evidence
    return "generic-pdf-layout", "generic_geometry", evidence


def _glyph_token(value: str) -> tuple[str, str, str] | None:
    match = re.fullmatch(r"([\(\[\{\"\u201c\u2018]*)(.)([,.;:\)\]\}\"\u201d\u2019!?]*)", value)
    if not match:
        return None
    prefix, core, suffix = match.groups()
    category = unicodedata.category(core)
    if not (category.startswith("L") or core in {"'", "\u2019", "\u02bc", "-", "\u2010", "\u2011"}):
        return None
    return prefix, core, suffix


def _repair_glyph_spacing(text: str) -> tuple[str, bool]:
    matches = list(re.finditer(r"\S+", text))
    replacements: list[tuple[int, int, str]] = []
    index = 0
    while index < len(matches):
        token = _glyph_token(matches[index].group())
        if token is None:
            index += 1
            continue
        run = [index]
        next_index = index + 1
        while next_index < len(matches):
            separator = text[matches[next_index - 1].end() : matches[next_index].start()]
            if len(separator) != 1 or not separator.isspace() or _glyph_token(matches[next_index].group()) is None:
                break
            run.append(next_index)
            next_index += 1
        letters = sum(unicodedata.category(_glyph_token(matches[item].group())[1]).startswith("L") for item in run)  # type: ignore[index]
        if len(run) >= 4 and letters >= 4:
            joined = "".join(matches[item].group() for item in run)
            replacements.append((matches[run[0]].start(), matches[run[-1]].end(), joined))
        index = max(index + 1, next_index)
    repaired = text
    for start, end, replacement in reversed(replacements):
        repaired = repaired[:start] + replacement + repaired[end:]
    return repaired, bool(replacements)


def _indent_levels(lines: list[dict[str, Any]]) -> None:
    if not lines:
        return
    sizes = [float(line.get("font_size", 10.0)) for line in lines]
    tolerance = max(3.0, statistics.median(sizes) * 0.35)
    clusters: list[float] = []
    for start in sorted(line["bbox"][0] for line in lines):
        if not clusters or start - clusters[-1] > tolerance:
            clusters.append(start)
        else:
            clusters[-1] = (clusters[-1] + start) / 2
    for line in lines:
        line["indentation_level"] = min(range(len(clusters)), key=lambda index: abs(clusters[index] - line["bbox"][0]))


def _hint_continuation(value: Any) -> str | None:
    if isinstance(value, dict):
        incoming = value.get("incoming", "none")
        outgoing = value.get("outgoing", "none")
        if incoming in {"column", "page"}:
            return f"continued_from_previous_{incoming}"
        if outgoing in {"column", "page"}:
            return f"continues_next_{outgoing}"
    if isinstance(value, str):
        mapping = {
            "none": "standalone",
            "from_previous_column": "continued_from_previous_column",
            "to_next_column": "continues_next_column",
            "from_previous_page": "continued_from_previous_page",
            "to_next_page": "continues_next_page",
        }
        mapped = mapping.get(value, value)
        return mapped if mapped in _CONTINUATION_VALUES else None
    return None


def _looks_like_continuation(text: str) -> bool:
    stripped = text.lstrip()
    if not stripped:
        return False
    first = stripped[0]
    return first.islower() or first.isdigit() or first in {",", ";", ":", "-", "\u2013", "\u2014", ")", "]"}


def _build_document(
    raw: dict[str, Any],
    candidate_id: str,
    requested: str,
    selected: str,
    reason: str,
    evidence: dict[str, Any],
    excluded: list[dict[str, Any]],
) -> dict[str, Any]:
    regions: list[dict[str, Any]] = []
    all_lines: list[dict[str, Any]] = []
    page_summaries: list[dict[str, Any]] = []
    global_order = 0

    for page in raw["pages"]:
        two_columns, threshold, column_confidence = _column_split(page, selected)
        grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for line in page["lines"]:
            column = 1 if not two_columns or line["bbox"][0] < threshold else 2
            grouped[column].append(line)
        page_region_ids: list[str] = []
        page_line_ids: list[str] = []
        for region_order, column in enumerate(sorted(grouped), 1):
            source_lines = sorted(grouped[column], key=lambda item: (item["bbox"][1], item["bbox"][0], item["source_order"]))
            _indent_levels(source_lines)
            region_id = _stable_id("region", candidate_id, page["candidate_pdf_page"], region_order, column)
            page_region_ids.append(region_id)
            region_line_ids: list[str] = []
            identity_counts: Counter[str] = Counter()
            for line in source_lines:
                global_order += 1
                original = line["original_displayed_form"]
                displayed, repaired = _repair_glyph_spacing(original)
                warnings = list(line.get("extraction_warnings", []))
                if repaired and "repaired_visual_character_spacing" not in warnings:
                    warnings.append("repaired_visual_character_spacing")
                identity_key = json.dumps([line["bbox"], original], ensure_ascii=False, separators=(",", ":"))
                identity_counts[identity_key] += 1
                line_id = _stable_id(
                    "line",
                    candidate_id,
                    page["candidate_pdf_page"],
                    region_order,
                    line["bbox"],
                    original,
                    identity_counts[identity_key],
                )
                continuation = _hint_continuation(line.get("continuation_status_hint")) or "standalone"
                boundary_hint = line.get("inferred_boundary_hint")
                boundary = boundary_hint if boundary_hint in _BOUNDARY_VALUES else (
                    "main_entry" if line["indentation_level"] == 0 else "subentry"
                )
                confidence_hint = line.get("confidence_hint")
                confidence = float(confidence_hint) if isinstance(confidence_hint, (int, float)) and not isinstance(confidence_hint, bool) else (
                    0.98 if line["indentation_level"] == 0 else 0.94
                )
                confidence -= min(0.24, len(warnings) * 0.08)
                record = {
                    "line_id": line_id,
                    "region_id": region_id,
                    "candidate_pdf_page": page["candidate_pdf_page"],
                    "reading_order_region": region_order,
                    "column": column,
                    "reading_order": global_order,
                    "bbox": line["bbox"],
                    "indentation_level": line["indentation_level"],
                    "displayed_line_text": displayed,
                    "continuation_status": continuation,
                    "inferred_boundary": boundary,
                    "confidence": round(max(0.0, min(1.0, confidence)), 3),
                    "extraction_warnings": warnings,
                    "original_displayed_form": original,
                }
                all_lines.append(record)
                region_line_ids.append(line_id)
                page_line_ids.append(line_id)
            regions.append(
                {
                    "region_id": region_id,
                    "candidate_pdf_page": page["candidate_pdf_page"],
                    "reading_order_region": region_order,
                    "column": column,
                    "bbox": _bbox_union([line["bbox"] for line in source_lines]),
                    "line_ids": region_line_ids,
                    "line_count": len(region_line_ids),
                    "column_detection_confidence": column_confidence if two_columns else 1.0,
                }
            )
        page_summaries.append(
            {
                "candidate_pdf_page": page["candidate_pdf_page"],
                "width": page["width"],
                "height": page["height"],
                "two_column_layout": two_columns,
                "column_split_x": round(threshold, 3) if two_columns else None,
                "region_ids": page_region_ids,
                "line_ids": page_line_ids,
            }
        )

    # Infer only cross-region continuations.  Semantic parsing belongs downstream.
    for previous_region, current_region in zip(regions, regions[1:]):
        if not previous_region["line_ids"] or not current_region["line_ids"]:
            continue
        previous = next(item for item in all_lines if item["line_id"] == previous_region["line_ids"][-1])
        current = next(item for item in all_lines if item["line_id"] == current_region["line_ids"][0])
        boundary = "column" if previous["candidate_pdf_page"] == current["candidate_pdf_page"] else "page"
        incoming = f"continued_from_previous_{boundary}"
        outgoing = f"continues_next_{boundary}"
        inferred = current["indentation_level"] > 0 or _looks_like_continuation(current["displayed_line_text"])
        if current["continuation_status"] in {incoming, "continues_previous"}:
            if previous["continuation_status"] == "standalone":
                previous["continuation_status"] = outgoing
            current["inferred_boundary"] = "continuation"
        elif previous["continuation_status"] == outgoing and current["continuation_status"] == "standalone":
            current["continuation_status"] = incoming
            current["inferred_boundary"] = "continuation"
        elif current["continuation_status"] == "standalone" and inferred:
            current["continuation_status"] = incoming
            if previous["continuation_status"] == "standalone":
                previous["continuation_status"] = outgoing
            current["inferred_boundary"] = "continuation"
            current["confidence"] = min(current["confidence"], 0.84)

    # Nest regions and lines under each page. Header/footer lines remain in the
    # extraction evidence, but are explicitly excluded from index normalization.
    line_lookup = {line["line_id"]: line for line in all_lines}
    nested_pages: list[dict[str, Any]] = []
    global_order = 0
    for page_summary in page_summaries:
        page_number = page_summary["candidate_pdf_page"]
        height = page_summary["height"]
        page_excluded = [item for item in excluded if item["candidate_pdf_page"] == page_number]
        header_items = [item for item in page_excluded if item["bbox"][1] < height / 2]
        footer_items = [item for item in page_excluded if item["bbox"][1] >= height / 2]
        nested_regions: list[dict[str, Any]] = []

        def append_excluded_region(items: list[dict[str, Any]], role_suffix: str) -> None:
            if not items:
                return
            region_id = _stable_id("region", candidate_id, page_number, "header_footer", role_suffix)
            records: list[dict[str, Any]] = []
            for item in sorted(items, key=lambda value: (value["bbox"][1], value["bbox"][0])):
                records.append(
                    {
                        "line_id": item["excluded_line_id"],
                        "region_id": region_id,
                        "candidate_pdf_page": page_number,
                        "column": 0,
                        "bbox": item["bbox"],
                        "indentation_level": 0,
                        "displayed_line_text": item["original_displayed_form"],
                        "continuation_status": "standalone",
                        "inferred_boundary": "header_footer",
                        "confidence": item["confidence"],
                        "extraction_warnings": [f"excluded_{item['reason']}"],
                        "original_displayed_form": item["original_displayed_form"],
                        "excluded_from_index": True,
                        "exclusion_reason": item["reason"],
                    }
                )
            nested_regions.append(
                {
                    "region_id": region_id,
                    "candidate_pdf_page": page_number,
                    "column": 0,
                    "role": "header_footer",
                    "bbox": _bbox_union([record["bbox"] for record in records]),
                    "line_ids": [record["line_id"] for record in records],
                    "line_count": len(records),
                    "column_detection_confidence": 1.0,
                    "lines": records,
                }
            )

        append_excluded_region(header_items, "header")
        for region in [item for item in regions if item["candidate_pdf_page"] == page_number]:
            records = [line_lookup[line_id] for line_id in region["line_ids"]]
            nested_regions.append({**region, "role": "index_column", "lines": records})
        append_excluded_region(footer_items, "footer")

        page_region_ids: list[str] = []
        page_line_ids: list[str] = []
        for region_order, region in enumerate(nested_regions, 1):
            region["region_order"] = region_order
            region["reading_order_region"] = region_order
            page_region_ids.append(region["region_id"])
            for line in region["lines"]:
                global_order += 1
                line["region_id"] = region["region_id"]
                line["candidate_pdf_page"] = page_number
                line["reading_order_region"] = region_order
                line["reading_order"] = global_order
                page_line_ids.append(line["line_id"])
        nested_pages.append(
            {
                **page_summary,
                "region_ids": page_region_ids,
                "line_ids": page_line_ids,
                "regions": nested_regions,
            }
        )

    metadata = raw.get("metadata", {})
    pdf_metadata = {
        "file_name": raw.get("file_name"),
        "sha256": raw.get("sha256"),
        "byte_length": raw.get("byte_length"),
        "page_count": len(raw["pages"]),
        "is_pdf": raw.get("is_pdf", True),
        "is_encrypted": raw.get("is_encrypted", False),
        "title": metadata.get("title", ""),
        "author": metadata.get("author", ""),
        "subject": metadata.get("subject", ""),
        "keywords": metadata.get("keywords", ""),
        "creator": metadata.get("creator", ""),
        "producer": metadata.get("producer", ""),
        "format": metadata.get("format", "PDF"),
        "creation_date": metadata.get("creationDate", metadata.get("creation_date", "")),
        "modification_date": metadata.get("modDate", metadata.get("modification_date", "")),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "candidate_id": candidate_id,
        "candidate_sha256": raw.get("sha256"),
        "adapter_id": selected,
        "adapter_version": ADAPTER_VERSIONS[selected],
        "adapter": {
            "requested_id": requested,
            "id": selected,
            "version": ADAPTER_VERSIONS[selected],
            "selection_reason": reason,
            "selection_evidence": evidence,
        },
        "pdf": {
            "page_count": len(raw["pages"]),
            "producer": metadata.get("producer", ""),
            "has_embedded_text": bool(all_lines or excluded),
        },
        "pdf_metadata": pdf_metadata,
        "pages": nested_pages,
        "limitations": list(raw.get("limitations", [])),
    }


def extract_candidate_layout(
    candidate_path: Path,
    candidate_id: str,
    adapter_id: str = "auto",
    geometry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract a candidate index into the vendor-neutral layout-line contract.

    ``geometry`` is intended for deterministic PDF-layout tests.
    When present, ``candidate_path`` is used only for its safe basename.
    """

    if not isinstance(candidate_id, str) or not candidate_id.strip():
        raise ValueError("candidate_id must be a nonempty string")
    candidate_path = Path(candidate_path)
    if geometry is not None:
        raw = _normalize_geometry(geometry, candidate_path)
    else:
        input_adapter = _input_adapter(candidate_path, adapter_id)
        if input_adapter == "indexia-html":
            raw = _extract_indexia_html_geometry(candidate_path)
        elif input_adapter == "markdown-list":
            raw = _extract_markdown_geometry(candidate_path)
        elif input_adapter == "plain-text":
            raw = _extract_plain_text_geometry(candidate_path)
        else:
            raw = _extract_pdf_geometry(candidate_path)
    excluded = _exclude_headers_and_footers(raw["pages"], candidate_id) if raw.get("is_pdf", True) else []
    selected, reason, evidence = _select_adapter(adapter_id, raw)
    document = _build_document(raw, candidate_id, adapter_id, selected, reason, evidence, excluded)
    document["excluded_lines"] = excluded
    regions = [region for page in document["pages"] for region in page["regions"]]
    lines = [line for region in regions for line in region["lines"]]
    incoming_column = sum(line["continuation_status"] == "continued_from_previous_column" for line in lines)
    incoming_page = sum(line["continuation_status"] == "continued_from_previous_page" for line in lines)
    document["counts"] = {
        "pages": len(document["pages"]),
        "regions": len(regions),
        "lines": len(lines),
        "index_lines": sum(not line.get("excluded_from_index", False) for line in lines),
        "excluded_lines": len(excluded),
        "excluded_repeated_headers": sum(item["reason"] == "repeated_page_header" for item in excluded),
        "excluded_repeated_footers": sum(item["reason"] == "repeated_page_footer" for item in excluded),
        "excluded_page_number_footers": sum(item["reason"] == "page_number_footer" for item in excluded),
        "lines_with_extraction_warnings": sum(bool(line["extraction_warnings"]) for line in lines),
        "column_continuations": incoming_column,
        "page_continuations": incoming_page,
    }
    errors = validate_layout_contract(document)
    if errors:
        raise ValueError("Generated candidate layout violates its contract: " + "; ".join(errors))
    return document


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _validate_box(value: Any, label: str, errors: list[str]) -> None:
    if not isinstance(value, list) or len(value) != 4 or not all(_is_number(item) for item in value):
        errors.append(f"{label} must be a four-number bbox")
    elif value[2] < value[0] or value[3] < value[1]:
        errors.append(f"{label} must not be inverted")


def validate_layout_contract(document: dict[str, Any]) -> list[str]:
    """Return deterministic contract errors; accept conforming future adapter IDs."""

    if not isinstance(document, dict):
        return ["layout document must be an object"]
    errors: list[str] = []
    if document.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    if not isinstance(document.get("candidate_id"), str) or not document.get("candidate_id", "").strip():
        errors.append("candidate_id must be a nonempty string")
    identity_pattern = r"[a-z0-9][a-z0-9._-]{0,63}"
    version_pattern = r"[A-Za-z0-9][A-Za-z0-9._+-]{0,31}"
    if not isinstance(document.get("adapter_id"), str) or not re.fullmatch(identity_pattern, document.get("adapter_id", "")):
        errors.append("adapter_id must be a bounded lowercase identifier")
    if not isinstance(document.get("adapter_version"), str) or not re.fullmatch(version_pattern, document.get("adapter_version", "")):
        errors.append("adapter_version must be a bounded version identifier")
    adapter = document.get("adapter")
    if not isinstance(adapter, dict):
        errors.append("adapter must be an object")
    else:
        if adapter.get("id") != document.get("adapter_id") or adapter.get("version") != document.get("adapter_version"):
            errors.append("adapter identity must match top-level adapter_id and adapter_version")
        if not isinstance(adapter.get("requested_id"), str) or not re.fullmatch(identity_pattern, adapter.get("requested_id", "")):
            errors.append("adapter.requested_id must be a bounded lowercase identifier")
        if not isinstance(adapter.get("selection_reason"), str) or not re.fullmatch(identity_pattern, adapter.get("selection_reason", "")):
            errors.append("adapter.selection_reason must be a bounded lowercase identifier")

    candidate_sha = document.get("candidate_sha256")
    if not isinstance(candidate_sha, str) or not re.fullmatch(r"[a-f0-9]{64}", candidate_sha):
        errors.append("candidate_sha256 must be a lowercase SHA-256 digest")

    metadata = document.get("pdf_metadata")
    page_count: int | None = None
    if not isinstance(metadata, dict):
        errors.append("pdf_metadata must be an object")
    else:
        value = metadata.get("page_count")
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            errors.append("pdf_metadata.page_count must be a nonnegative integer")
        else:
            page_count = value
        if metadata.get("sha256") != candidate_sha:
            errors.append("pdf_metadata.sha256 must match candidate_sha256")
    pdf = document.get("pdf")
    if not isinstance(pdf, dict):
        errors.append("pdf must be an object")
    elif page_count is not None and pdf.get("page_count") != page_count:
        errors.append("pdf.page_count must match pdf_metadata.page_count")

    pages = document.get("pages")
    if not isinstance(pages, list):
        errors.append("pages must be an array")
        pages = []
    page_numbers: set[int] = set()
    region_ids: set[str] = set()
    line_ids: set[str] = set()
    reading_orders: set[int] = set()
    regions: list[dict[str, Any]] = []
    lines: list[dict[str, Any]] = []
    for page_index, page in enumerate(pages):
        if not isinstance(page, dict):
            errors.append(f"pages[{page_index}] must be an object")
            continue
        number = page.get("candidate_pdf_page")
        if not isinstance(number, int) or isinstance(number, bool) or number < 1:
            errors.append(f"pages[{page_index}].candidate_pdf_page must be a positive integer")
            number = None
        elif number in page_numbers:
            errors.append(f"duplicate candidate PDF page {number}")
        else:
            page_numbers.add(number)
        if not _is_number(page.get("width")) or page.get("width", 0) <= 0:
            errors.append(f"pages[{page_index}].width must be positive")
        if not _is_number(page.get("height")) or page.get("height", 0) <= 0:
            errors.append(f"pages[{page_index}].height must be positive")
        page_regions = page.get("regions")
        if not isinstance(page_regions, list):
            errors.append(f"pages[{page_index}].regions must be an array")
            page_regions = []
        page_region_ids: list[str] = []
        page_line_ids: list[str] = []
        region_orders: set[int] = set()
        for region_index, region in enumerate(page_regions):
            label = f"pages[{page_index}].regions[{region_index}]"
            if not isinstance(region, dict):
                errors.append(f"{label} must be an object")
                continue
            regions.append(region)
            region_id = region.get("region_id")
            if not isinstance(region_id, str) or not region_id:
                errors.append(f"{label}.region_id must be a nonempty string")
            elif region_id in region_ids:
                errors.append(f"duplicate region_id {region_id}")
            else:
                region_ids.add(region_id)
                page_region_ids.append(region_id)
            if number is not None and region.get("candidate_pdf_page") != number:
                errors.append(f"{label}.candidate_pdf_page must match its page")
            region_order = region.get("region_order")
            if not isinstance(region_order, int) or isinstance(region_order, bool) or region_order < 1:
                errors.append(f"{label}.region_order must be a positive integer")
            elif region_order in region_orders:
                errors.append(f"duplicate region_order {region_order} on page {number}")
            else:
                region_orders.add(region_order)
            if region.get("reading_order_region") != region_order:
                errors.append(f"{label}.reading_order_region must equal region_order")
            column = region.get("column")
            if not isinstance(column, int) or isinstance(column, bool) or column < 0:
                errors.append(f"{label}.column must be a nonnegative integer")
            if not isinstance(region.get("role"), str) or not region.get("role"):
                errors.append(f"{label}.role must be a nonempty string")
            _validate_box(region.get("bbox"), f"{label}.bbox", errors)
            region_lines = region.get("lines")
            if not isinstance(region_lines, list):
                errors.append(f"{label}.lines must be an array")
                region_lines = []
            declared_line_ids = region.get("line_ids")
            actual_region_line_ids: list[str] = []
            for line_index, line in enumerate(region_lines):
                line_label = f"{label}.lines[{line_index}]"
                if not isinstance(line, dict):
                    errors.append(f"{line_label} must be an object")
                    continue
                lines.append(line)
                line_id = line.get("line_id")
                if not isinstance(line_id, str) or not line_id:
                    errors.append(f"{line_label}.line_id must be a nonempty string")
                elif line_id in line_ids:
                    errors.append(f"duplicate line_id {line_id}")
                else:
                    line_ids.add(line_id)
                    page_line_ids.append(line_id)
                    actual_region_line_ids.append(line_id)
                if isinstance(region_id, str) and line.get("region_id") != region_id:
                    errors.append(f"{line_label}.region_id must match its region")
                if number is not None and line.get("candidate_pdf_page") != number:
                    errors.append(f"{line_label}.candidate_pdf_page must match its page")
                if line.get("reading_order_region") != region_order:
                    errors.append(f"{line_label}.reading_order_region must match its region")
                if line.get("column") != column:
                    errors.append(f"{line_label}.column must match its region")
                order = line.get("reading_order")
                if not isinstance(order, int) or isinstance(order, bool) or order < 1:
                    errors.append(f"{line_label}.reading_order must be a positive integer")
                elif order in reading_orders:
                    errors.append(f"duplicate reading_order {order}")
                else:
                    reading_orders.add(order)
                indentation = line.get("indentation_level")
                if not isinstance(indentation, int) or isinstance(indentation, bool) or indentation < 0:
                    errors.append(f"{line_label}.indentation_level must be a nonnegative integer")
                _validate_box(line.get("bbox"), f"{line_label}.bbox", errors)
                for field in ("displayed_line_text", "original_displayed_form"):
                    if not isinstance(line.get(field), str):
                        errors.append(f"{line_label}.{field} must be a string")
                if line.get("continuation_status") not in _CONTINUATION_VALUES:
                    errors.append(f"{line_label}.continuation_status is invalid")
                if line.get("inferred_boundary") not in _BOUNDARY_VALUES:
                    errors.append(f"{line_label}.inferred_boundary is invalid")
                if not _is_number(line.get("confidence")) or not 0 <= float(line.get("confidence", -1)) <= 1:
                    errors.append(f"{line_label}.confidence must be between zero and one")
                warnings = line.get("extraction_warnings")
                if not isinstance(warnings, list) or not all(isinstance(item, str) for item in warnings):
                    errors.append(f"{line_label}.extraction_warnings must be an array of strings")
                if line.get("inferred_boundary") == "header_footer" and line.get("excluded_from_index") is not True:
                    errors.append(f"{line_label} header/footer evidence must be excluded_from_index")
            if not isinstance(declared_line_ids, list) or not all(isinstance(item, str) for item in declared_line_ids):
                errors.append(f"{label}.line_ids must be an array of strings")
            elif declared_line_ids != actual_region_line_ids:
                errors.append(f"{label}.line_ids must match nested lines")
            if region.get("line_count") != len(region_lines):
                errors.append(f"{label}.line_count must match nested lines")
        if page.get("region_ids") != page_region_ids:
            errors.append(f"pages[{page_index}].region_ids must match nested regions")
        if page.get("line_ids") != page_line_ids:
            errors.append(f"pages[{page_index}].line_ids must match nested lines")
        if region_orders and region_orders != set(range(1, len(page_regions) + 1)):
            errors.append(f"region_order values on page {number} must be contiguous from one")
    if page_count is not None and len(pages) != page_count:
        errors.append("pages length must match pdf_metadata.page_count")
    if page_count is not None and page_numbers != set(range(1, page_count + 1)):
        errors.append("candidate PDF pages must be contiguous from one through page_count")
    if reading_orders and reading_orders != set(range(1, len(lines) + 1)):
        errors.append("reading_order values must be contiguous from one")

    excluded = document.get("excluded_lines")
    if not isinstance(excluded, list):
        errors.append("excluded_lines must be an array")
        excluded = []
    excluded_ids: set[str] = set()
    for index, item in enumerate(excluded):
        if not isinstance(item, dict):
            errors.append(f"excluded_lines[{index}] must be an object")
            continue
        identity = item.get("excluded_line_id")
        if not isinstance(identity, str) or not identity:
            errors.append(f"excluded_lines[{index}].excluded_line_id must be a nonempty string")
        elif identity in excluded_ids:
            errors.append(f"duplicate excluded_line_id {identity}")
        else:
            excluded_ids.add(identity)
        _validate_box(item.get("bbox"), f"excluded_lines[{index}].bbox", errors)
    if not excluded_ids.issubset(line_ids):
        errors.append("every excluded_line_id must identify nested header/footer evidence")

    counts = document.get("counts")
    if not isinstance(counts, dict):
        errors.append("counts must be an object")
    else:
        expected = {"pages": len(pages), "regions": len(regions), "lines": len(lines), "excluded_lines": len(excluded)}
        for field, value in expected.items():
            if counts.get(field) != value:
                errors.append(f"counts.{field} must equal {value}")
    return errors


def _write_bytes(path: Path, payload: bytes, force: bool) -> None:
    if path.exists() and not force:
        raise ValueError(f"Refusing to overwrite {path}; pass --force to replace it")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _download_html(url: str, snapshot: Path, force: bool) -> Path:
    if not url.startswith("https://"):
        raise ValueError("--url must use HTTPS")
    request = urllib.request.Request(url, headers={"User-Agent": "subject-index-converter/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = response.read(50 * 1024 * 1024 + 1)
    if len(payload) > 50 * 1024 * 1024:
        raise ValueError("Downloaded HTML exceeds 50 MiB")
    if b"<html" not in payload[:4096].lower():
        raise ValueError("URL did not return HTML")
    _write_bytes(snapshot, payload, force)
    return snapshot


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-id", required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", type=Path)
    source.add_argument("--url")
    parser.add_argument("--snapshot", type=Path, help="Required with --url; preserves the exact downloaded HTML")
    parser.add_argument("--adapter", choices=list_adapter_ids(), default="auto")
    parser.add_argument("--source-sha256", help="Optional frozen source-document SHA-256")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        output = args.output.resolve()
        if output.exists() and not args.force:
            raise ValueError(f"Refusing to overwrite {output}; pass --force to replace it")
        if args.source_sha256 and not re.fullmatch(r"[a-f0-9]{64}", args.source_sha256):
            raise ValueError("--source-sha256 must be a lowercase SHA-256 digest")
        if args.url:
            if args.snapshot is None:
                raise ValueError("--snapshot is required with --url")
            snapshot = args.snapshot.resolve()
            if snapshot == output:
                raise ValueError("--snapshot and --output must be different files")
            candidate_path = _download_html(args.url, snapshot, args.force)
            adapter = "indexia-html" if args.adapter == "auto" else args.adapter
        else:
            if args.snapshot is not None:
                raise ValueError("--snapshot is only valid with --url")
            candidate_path = args.input.resolve()
            adapter = args.adapter
        if candidate_path.resolve() == output:
            raise ValueError("--input and --output must be different files")
        document = extract_candidate_layout(candidate_path, args.candidate_id, adapter)
        if args.source_sha256:
            document["source_sha256"] = args.source_sha256
        errors = validate_layout_contract(document)
        if errors:
            raise ValueError("Generated layout violates its contract: " + "; ".join(errors))
        _write_bytes(output, (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode(), args.force)
        print(json.dumps({
            "ok": True,
            "candidate_id": args.candidate_id,
            "candidate_sha256": document["candidate_sha256"],
            "adapter": document["adapter_id"],
            "artifact_written": str(output),
            "snapshot_written": str(args.snapshot.resolve()) if args.url else None,
            "warnings": document["limitations"],
        }, indent=2, ensure_ascii=False))
    except (OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1) from exc


__all__ = [
    "ADAPTER_IDS",
    "ADAPTER_VERSIONS",
    "SCHEMA_VERSION",
    "extract_candidate_layout",
    "list_adapter_ids",
    "validate_layout_contract",
]


if __name__ == "__main__":
    main()
