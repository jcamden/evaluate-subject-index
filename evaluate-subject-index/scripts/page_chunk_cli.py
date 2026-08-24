#!/usr/bin/env python3
"""Expand page-label maps, validate chunks, split PDFs, and route candidate locators."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any


def emit(payload: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    raise SystemExit(exit_code)


def fail(code: str, message: str, details: Any = None) -> None:
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    emit({"ok": False, "error": error}, 1)


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail("file_not_found", f"File does not exist: {path}")
    except json.JSONDecodeError as exc:
        fail("invalid_json", f"Could not parse {path}: {exc}")
    if not isinstance(value, dict):
        fail("invalid_root", f"JSON root must be an object: {path}")
    return value


def save_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def canonical_hash(value: dict[str, Any], hash_field: str) -> str:
    copy = dict(value)
    copy.pop(hash_field, None)
    encoded = json.dumps(copy, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize_label(label: str | None, style: str | None = None) -> str | None:
    if label is None:
        return None
    normalized = unicodedata.normalize("NFKC", label).strip()
    normalized = re.sub(r"[‐‑‒–—−]", "-", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    if style == "arabic" and re.fullmatch(r"[0-9]+", normalized):
        return str(int(normalized))
    return normalized.casefold()


def roman_to_int(value: str) -> int:
    symbols = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    text = value.upper()
    if not text or any(char not in symbols for char in text):
        raise ValueError(f"Invalid Roman numeral: {value}")
    total = 0
    previous = 0
    for char in reversed(text):
        current = symbols[char]
        if current < previous:
            total -= current
        else:
            total += current
            previous = current
    if int_to_roman(total) != text:
        raise ValueError(f"Noncanonical Roman numeral: {value}")
    return total


def int_to_roman(value: int) -> str:
    if value < 1 or value > 3999:
        raise ValueError("Roman numeral sequence supports values 1 through 3999")
    pairs = [
        (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"),
        (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
        (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
    ]
    result = []
    remaining = value
    for number, symbol in pairs:
        while remaining >= number:
            result.append(symbol)
            remaining -= number
    return "".join(result)


def alpha_to_int(value: str) -> int:
    if not re.fullmatch(r"[A-Za-z]+", value):
        raise ValueError(f"Invalid alphabetic label: {value}")
    total = 0
    for char in value.upper():
        total = total * 26 + ord(char) - ord("A") + 1
    return total


def int_to_alpha(value: int) -> str:
    if value < 1:
        raise ValueError("Alphabetic sequence starts at 1")
    result = []
    remaining = value
    while remaining:
        remaining, remainder = divmod(remaining - 1, 26)
        result.append(chr(ord("A") + remainder))
    return "".join(reversed(result))


def sequence_value(style: str, start: str, offset: int) -> str:
    if style == "arabic":
        if not re.fullmatch(r"[0-9]+", start):
            raise ValueError(f"Invalid Arabic label_start: {start}")
        return str(int(start) + offset)
    if style in {"roman_lower", "roman_upper"}:
        value = int_to_roman(roman_to_int(start) + offset)
        return value.lower() if style == "roman_lower" else value
    if style in {"alpha_lower", "alpha_upper"}:
        value = int_to_alpha(alpha_to_int(start) + offset)
        return value.lower() if style == "alpha_lower" else value
    raise ValueError(f"Unsupported sequence label_style: {style}")


def parse_range(value: Any, field: str) -> tuple[int, int]:
    if not isinstance(value, list) or len(value) != 2 or not all(isinstance(item, int) for item in value):
        raise ValueError(f"{field} must be [start, end] integers")
    start, end = value
    if start < 1 or end < start:
        raise ValueError(f"{field} must be one-based and ascending")
    return start, end


def expand_ranges(ranges: Any, field: str) -> list[int]:
    if not isinstance(ranges, list):
        raise ValueError(f"{field} must be an array of ranges")
    pages: list[int] = []
    for index, item in enumerate(ranges):
        start, end = parse_range(item, f"{field}[{index}]")
        pages.extend(range(start, end + 1))
    return pages


def command_expand_page_map(args: argparse.Namespace) -> None:
    source = load_json(Path(args.input))
    if source.get("schema_version") != "page-map-input-v1":
        fail("schema_version", "Expected page-map-input-v1")
    count = source.get("document_page_count")
    if not isinstance(count, int) or count < 1:
        fail("document_page_count", "document_page_count must be a positive integer")
    source_sha256 = source.get("source_sha256")
    if not isinstance(source_sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", source_sha256):
        fail("source_sha256", "source_sha256 must be a lowercase SHA-256 digest")
    segments = source.get("segments")
    if not isinstance(segments, list) or not segments:
        fail("segments", "segments must be a nonempty array")

    records: dict[int, dict[str, Any]] = {}
    errors: list[str] = []
    for segment in segments:
        if not isinstance(segment, dict):
            errors.append("Every segment must be an object")
            continue
        mapping_id = str(segment.get("mapping_id", ""))
        mode = segment.get("mode")
        try:
            start, end = parse_range(segment.get("document_page_range"), f"{mapping_id}.document_page_range")
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if end > count:
            errors.append(f"{mapping_id} ends after document_page_count")
            continue
        overlap = [page for page in range(start, end + 1) if page in records]
        if overlap:
            errors.append(f"{mapping_id} overlaps previously mapped document pages: {overlap[:10]}")
            continue
        page_total = end - start + 1
        style = segment.get("label_style", "literal" if mode == "explicit" else None)
        labels: list[str | None]
        if mode == "sequence":
            label_start = segment.get("label_start")
            if not isinstance(label_start, str):
                errors.append(f"{mapping_id}.label_start must be a string")
                continue
            prefix = str(segment.get("prefix", ""))
            suffix = str(segment.get("suffix", ""))
            try:
                labels = [prefix + sequence_value(str(style), label_start, offset) + suffix for offset in range(page_total)]
            except ValueError as exc:
                errors.append(f"{mapping_id}: {exc}")
                continue
        elif mode == "explicit":
            raw_labels = segment.get("labels")
            if not isinstance(raw_labels, list) or len(raw_labels) != page_total:
                errors.append(f"{mapping_id}.labels must contain exactly {page_total} values")
                continue
            if not all(label is None or isinstance(label, str) for label in raw_labels):
                errors.append(f"{mapping_id}.labels values must be strings or null")
                continue
            labels = raw_labels
        else:
            errors.append(f"{mapping_id}.mode must be sequence or explicit")
            continue

        for offset, document_page in enumerate(range(start, end + 1)):
            label = labels[offset]
            records[document_page] = {
                "document_page": document_page,
                "source_page_label": label,
                "normalized_locator_key": normalize_label(label, str(style) if style else None),
                "label_style": style or "literal",
                "mapping_id": mapping_id,
                "in_evaluation_scope": bool(segment.get("in_evaluation_scope")),
                "accepts_index_locators": bool(segment.get("accepts_index_locators")),
            }

    missing = [page for page in range(1, count + 1) if page not in records]
    if missing:
        errors.append(f"Unmapped document pages: {missing[:25]}{'...' if len(missing) > 25 else ''}")

    key_pages: dict[str, list[int]] = {}
    for record in records.values():
        key = record["normalized_locator_key"]
        if record["accepts_index_locators"] and key is not None:
            key_pages.setdefault(key, []).append(record["document_page"])
    duplicates = {key: pages for key, pages in key_pages.items() if len(pages) > 1}
    if duplicates:
        errors.append(f"Ambiguous duplicate indexable labels: {duplicates}")
    if errors:
        fail("invalid_page_map", "Page map could not be expanded.", errors)

    output: dict[str, Any] = {
        "schema_version": "page-map-v1",
        "source_sha256": source_sha256,
        "document_page_count": count,
        "document_page_basis": "one_based_inclusive",
        "pages": [records[page] for page in range(1, count + 1)],
        "validation": {
            "all_document_pages_covered": True,
            "unique_indexable_locator_keys": True,
        },
        "page_map_sha256": None,
    }
    output["page_map_sha256"] = canonical_hash(output, "page_map_sha256")
    output_path = Path(args.output)
    save_json(output_path, output)
    emit({
        "ok": True,
        "command": "expand-page-map",
        "artifact_written": str(output_path.resolve()),
        "page_map_sha256": output["page_map_sha256"],
        "document_pages": count,
        "indexable_labels": len(key_pages),
    })


def command_validate_chunks(args: argparse.Namespace) -> None:
    manifest = load_json(Path(args.input))
    page_map = load_json(Path(args.page_map))
    if manifest.get("schema_version") != "chunk-manifest-v1":
        fail("schema_version", "Expected chunk-manifest-v1")
    if manifest.get("user_approved") is not True:
        fail("approval_required", "chunk manifest must record user_approved: true")
    chunks = manifest.get("chunks")
    if not isinstance(chunks, list) or not chunks:
        fail("chunks", "chunks must be a nonempty array")
    count = page_map.get("document_page_count")
    in_scope = {record["document_page"] for record in page_map.get("pages", []) if record.get("in_evaluation_scope")}
    owners: dict[int, str] = {}
    errors: list[str] = []
    chunk_ids: set[str] = set()
    packet_orders: set[int] = set()
    for chunk in chunks:
        chunk_id = chunk.get("chunk_id")
        if not isinstance(chunk_id, str) or not chunk_id.startswith("CHUNK-"):
            errors.append(f"Invalid chunk_id: {chunk_id}")
            continue
        if chunk_id in chunk_ids:
            errors.append(f"Duplicate chunk_id: {chunk_id}")
        chunk_ids.add(chunk_id)
        packet_order = chunk.get("packet_order")
        if not isinstance(packet_order, int) or packet_order < 1 or packet_order in packet_orders:
            errors.append(f"Invalid or duplicate packet_order for {chunk_id}: {packet_order}")
        else:
            packet_orders.add(packet_order)
        try:
            owned = expand_ranges(chunk.get("owned_document_page_ranges"), f"{chunk_id}.owned_document_page_ranges")
            context = expand_ranges(chunk.get("context_document_page_ranges", []), f"{chunk_id}.context_document_page_ranges")
        except ValueError as exc:
            errors.append(str(exc))
            continue
        for page in owned + context:
            if page > count:
                errors.append(f"{chunk_id} references document page {page} beyond {count}")
        for page in owned:
            if page in owners:
                errors.append(f"Document page {page} is owned by both {owners[page]} and {chunk_id}")
            else:
                owners[page] = chunk_id

    missing_scope = sorted(in_scope - set(owners))
    outside_scope = sorted(set(owners) - in_scope)
    require_full = bool(manifest.get("require_full_scope_coverage"))
    if require_full and missing_scope:
        errors.append(f"In-scope document pages without an owner: {missing_scope[:25]}{'...' if len(missing_scope) > 25 else ''}")
    if outside_scope:
        errors.append(f"Owned document pages are outside evaluation scope: {outside_scope[:25]}{'...' if len(outside_scope) > 25 else ''}")
    if errors:
        fail("invalid_chunk_manifest", "Chunk manifest failed validation.", errors)

    output = dict(manifest)
    output["document_page_basis"] = "one_based_inclusive"
    output["page_map_sha256"] = page_map.get("page_map_sha256")
    output["validation"] = {
        "owned_pages_unique": True,
        "scope_coverage_complete": not missing_scope,
        "owned_document_page_count": len(owners),
        "in_scope_document_page_count": len(in_scope),
    }
    output["chunk_manifest_sha256"] = None
    output["chunk_manifest_sha256"] = canonical_hash(output, "chunk_manifest_sha256")
    output_path = Path(args.output)
    save_json(output_path, output)
    emit({
        "ok": True,
        "command": "validate-chunks",
        "artifact_written": str(output_path.resolve()),
        "chunk_manifest_sha256": output["chunk_manifest_sha256"],
        "chunk_count": len(chunks),
        "owned_document_pages": len(owners),
    })


def command_split_pdf(args: argparse.Namespace) -> None:
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:
        fail("missing_dependency", "pypdf is required for split-pdf")
    source_path = Path(args.source)
    if not source_path.is_file():
        fail("source_not_found", f"Source PDF does not exist: {source_path}")
    page_map = load_json(Path(args.page_map))
    manifest = load_json(Path(args.chunks))
    actual_source_hash = sha256_file(source_path)
    if page_map.get("source_sha256") != actual_source_hash:
        fail("source_hash_mismatch", "Source PDF does not match the source_sha256 frozen in the page map")
    reader = PdfReader(str(source_path))
    expected = page_map.get("document_page_count")
    if len(reader.pages) != expected:
        fail("page_count_mismatch", f"PDF has {len(reader.pages)} pages; page map declares {expected}")
    page_records = {record["document_page"]: record for record in page_map.get("pages", [])}
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    chunk_files: list[dict[str, Any]] = []
    for chunk in sorted(manifest.get("chunks", []), key=lambda item: item["packet_order"]):
        owned = set(expand_ranges(chunk["owned_document_page_ranges"], "owned_document_page_ranges"))
        context = set(expand_ranges(chunk.get("context_document_page_ranges", []), "context_document_page_ranges"))
        selected = sorted(owned | context)
        writer = PdfWriter()
        sidecar_pages: list[dict[str, Any]] = []
        for chunk_page, document_page in enumerate(selected, start=1):
            writer.add_page(reader.pages[document_page - 1])
            mapping = page_records[document_page]
            sidecar_pages.append({
                "chunk_pdf_page": chunk_page,
                "document_page": document_page,
                "source_page_label": mapping.get("source_page_label"),
                "ownership": "owned" if document_page in owned else "context",
            })
        pdf_path = output_dir / f"{chunk['chunk_id']}.pdf"
        with pdf_path.open("wb") as handle:
            writer.write(handle)
        sidecar = {
            "schema_version": "source-chunk-sidecar-v1",
            "chunk_id": chunk["chunk_id"],
            "source_filename": source_path.name,
            "page_map_sha256": page_map.get("page_map_sha256"),
            "chunk_manifest_sha256": manifest.get("chunk_manifest_sha256"),
            "pages": sidecar_pages,
        }
        sidecar_path = output_dir / f"{chunk['chunk_id']}.pages.json"
        save_json(sidecar_path, sidecar)
        chunk_files.append({
            "chunk_id": chunk["chunk_id"],
            "pdf": str(pdf_path.resolve()),
            "sidecar": str(sidecar_path.resolve()),
            "page_count": len(selected),
            "owned_page_count": len(owned),
            "context_page_count": len(context - owned),
        })
    inventory = {
        "schema_version": "source-chunk-inventory-v1",
        "source_filename": source_path.name,
        "page_map_sha256": page_map.get("page_map_sha256"),
        "chunk_manifest_sha256": manifest.get("chunk_manifest_sha256"),
        "chunks": chunk_files,
    }
    inventory_path = output_dir / "source-chunk-inventory.json"
    save_json(inventory_path, inventory)
    emit({
        "ok": True,
        "command": "split-pdf",
        "artifact_written": str(inventory_path.resolve()),
        "chunk_count": len(chunk_files),
        "chunks": chunk_files,
    })


def command_filter_candidate(args: argparse.Namespace) -> None:
    candidate = load_json(Path(args.candidate))
    page_map = load_json(Path(args.page_map))
    manifest = load_json(Path(args.chunks))
    candidate_schema = candidate.get("schema_version")
    if candidate_schema != "candidate-index-v2":
        fail("schema_version", "Expected candidate-index-v2")
    benchmark_lock = load_json(Path(args.benchmark_lock))
    if benchmark_lock.get("schema_version") != "candidate-benchmark-lock-v1":
        fail("invalid_benchmark_lock", "Expected candidate-benchmark-lock-v1")
    if benchmark_lock.get("lock_sha256") != canonical_hash(benchmark_lock, "lock_sha256"):
        fail("invalid_benchmark_lock_hash", "Benchmark lock canonical hash does not recompute")
    if benchmark_lock.get("candidate_id") != candidate.get("candidate_id"):
        fail("benchmark_lock_candidate_mismatch", "Benchmark lock and candidate IDs do not match")
    if benchmark_lock.get("candidate_sha256") != candidate.get("candidate_sha256"):
        fail("benchmark_lock_candidate_mismatch", "Benchmark lock and candidate hashes do not match")
    compatibility = benchmark_lock.get("compatibility", {})
    if compatibility.get("page_map_sha256") != page_map.get("page_map_sha256"):
        fail("benchmark_lock_page_map_mismatch", "Benchmark lock and page-map hashes do not match")
    if compatibility.get("chunk_manifest_sha256") != manifest.get("chunk_manifest_sha256"):
        fail("benchmark_lock_chunk_manifest_mismatch", "Benchmark lock and chunk-manifest hashes do not match")
    if benchmark_lock.get("status") != "locked":
        fail("benchmark_lock_pending", "Benchmark lock must have status=locked before locator routing")
    final_commit = benchmark_lock.get("benchmark_repository", {}).get("final_commit")
    benchmark_sha = benchmark_lock.get("benchmark_repository", {}).get("benchmark_sha256")
    if not isinstance(final_commit, str) or not re.fullmatch(r"[a-fA-F0-9]{40}", final_commit):
        fail("invalid_benchmark_lock", "Benchmark lock requires an immutable final benchmark commit")
    if not isinstance(benchmark_sha, str) or not re.fullmatch(r"[a-f0-9]{64}", benchmark_sha):
        fail("invalid_benchmark_lock", "Benchmark lock requires the final canonical benchmark hash")
    if candidate.get("page_map_sha256") != page_map.get("page_map_sha256"):
        fail("page_map_mismatch", "Candidate and page map hashes do not match")
    owner: dict[int, str] = {}
    chunks_by_id: dict[str, dict[str, Any]] = {}
    for chunk in manifest.get("chunks", []):
        chunks_by_id[chunk["chunk_id"]] = chunk
        for page in expand_ranges(chunk["owned_document_page_ranges"], "owned_document_page_ranges"):
            owner[page] = chunk["chunk_id"]

    routed: dict[str, list[dict[str, Any]]] = {chunk_id: [] for chunk_id in chunks_by_id}
    exceptions: list[dict[str, Any]] = []
    for record in candidate.get("records", []):
        assignments = record.get("locator_assignments", [])
        if not isinstance(assignments, list):
            fail("candidate_shape", f"locator_assignments must be an array for {record.get('record_id')}")
        by_chunk: dict[str, list[dict[str, Any]]] = {}
        resolved_total = 0
        for assignment in assignments:
            if assignment.get("mapping_status") != "resolved" or not isinstance(assignment.get("document_page"), int):
                exceptions.append({
                    "record_id": record.get("record_id"),
                    "path_id": record.get("path_id"),
                    "heading_path": record.get("heading_path"),
                    "locator_assignment": assignment,
                    "reason": "locator_not_resolved_to_one_document_page",
                })
                continue
            resolved_total += 1
            chunk_id = owner.get(assignment["document_page"])
            if chunk_id is None:
                exceptions.append({
                    "record_id": record.get("record_id"),
                    "path_id": record.get("path_id"),
                    "heading_path": record.get("heading_path"),
                    "locator_assignment": assignment,
                    "reason": "mapped_document_page_has_no_chunk_owner",
                })
                continue
            by_chunk.setdefault(chunk_id, []).append(assignment)
        for chunk_id, selected in by_chunk.items():
            routed[chunk_id].append({
                "record_id": record.get("record_id"),
                "path_id": record.get("path_id"),
                "heading_path": record.get("heading_path"),
                "locator_assignments": selected,
                "other_locator_assignment_count": max(resolved_total - len(selected), 0),
            })

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[dict[str, Any]] = []
    for chunk in sorted(manifest.get("chunks", []), key=lambda item: item["packet_order"]):
        chunk_id = chunk["chunk_id"]
        owned_pages = sorted(expand_ranges(chunk["owned_document_page_ranges"], "owned_document_page_ranges"))
        paths = routed[chunk_id]
        packet = {
            "schema_version": "candidate-locator-chunk-v1",
            "candidate_id": candidate.get("candidate_id"),
            "candidate_sha256": candidate.get("candidate_sha256"),
            "page_map_sha256": page_map.get("page_map_sha256"),
            "chunk_manifest_sha256": manifest.get("chunk_manifest_sha256"),
            "chunk_id": chunk_id,
            "owned_document_pages": owned_pages,
            "paths": paths,
            "summary": {
                "path_count": len(paths),
                "locator_assignment_count": sum(len(path["locator_assignments"]) for path in paths),
            },
        }
        packet_path = output_dir / f"candidate-locator-{chunk_id}.json"
        save_json(packet_path, packet)
        written.append({"chunk_id": chunk_id, "path": str(packet_path.resolve()), **packet["summary"]})
    exception_payload = {
        "schema_version": "candidate-locator-routing-exceptions-v1",
        "candidate_id": candidate.get("candidate_id"),
        "exceptions": exceptions,
        "exception_count": len(exceptions),
    }
    exception_path = output_dir / "candidate-locator-routing-exceptions.json"
    save_json(exception_path, exception_payload)
    emit({
        "ok": not exceptions,
        "command": "filter-candidate",
        "chunks": written,
        "exception_ledger": str(exception_path.resolve()),
        "exception_count": len(exceptions),
        "warnings": [] if not exceptions else ["Resolve every routing exception before completing prepare-locator-chunks."],
    }, 0 if not exceptions else 2)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    expand = commands.add_parser("expand-page-map")
    expand.add_argument("--input", required=True)
    expand.add_argument("--output", required=True)
    expand.set_defaults(func=command_expand_page_map)

    chunks = commands.add_parser("validate-chunks")
    chunks.add_argument("--input", required=True)
    chunks.add_argument("--page-map", required=True)
    chunks.add_argument("--output", required=True)
    chunks.set_defaults(func=command_validate_chunks)

    split_pdf = commands.add_parser("split-pdf")
    split_pdf.add_argument("--source", required=True)
    split_pdf.add_argument("--page-map", required=True)
    split_pdf.add_argument("--chunks", required=True)
    split_pdf.add_argument("--output-dir", required=True)
    split_pdf.set_defaults(func=command_split_pdf)

    filter_candidate = commands.add_parser("filter-candidate")
    filter_candidate.add_argument("--candidate", required=True)
    filter_candidate.add_argument("--page-map", required=True)
    filter_candidate.add_argument("--chunks", required=True)
    filter_candidate.add_argument("--benchmark-lock", required=True)
    filter_candidate.add_argument("--output-dir", required=True)
    filter_candidate.set_defaults(func=command_filter_candidate)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
