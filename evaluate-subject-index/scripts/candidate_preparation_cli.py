#!/usr/bin/env python3
"""Extract, normalize, validate, and register a current candidate index."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
import unicodedata
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from candidate_layout_adapters import extract_candidate_layout
from benchmark_review_cli import final_benchmark_structure_errors
from item_grade_cli import build_inventory
from state_cli import (
    STAGES,
    artifact_id as state_artifact_id,
    evaluation_mutation_lock,
    next_stage,
    portable_relative_path,
    save_state,
    validate_state,
)
from schema_validation import schema_errors


PRIVATE_ARTIFACT_KEYS = (
    "candidate_ref",
    "layout_profile",
    "layout_extraction",
    "candidate_index",
    "item_inventory",
    "normalization_exceptions",
    "normalization_report",
    "normalization_qa",
)
FORBIDDEN_PRELOCK_KEYS = {
    "score",
    "rating",
    "density",
    "judgment",
    "defect",
    "coverage_judgment",
    "locator_support",
    "missing_access",
    "editorial_quality",
}
class PreparationError(ValueError):
    def __init__(self, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def require(condition: bool, code: str, message: str, details: Any = None) -> None:
    if not condition:
        raise PreparationError(code, message, details)


def emit(payload: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    raise SystemExit(exit_code)


def load_json(path: Path, label: str = "JSON artifact") -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PreparationError("file_not_found", f"{label} does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise PreparationError("invalid_json", f"{label} is invalid JSON: {exc}") from exc
    require(isinstance(value, dict), "invalid_document", f"{label} must be a JSON object.")
    return value


def load_json_snapshot(path: Path, label: str = "JSON artifact") -> tuple[dict[str, Any], bytes, str]:
    try:
        payload = path.read_bytes()
    except FileNotFoundError as exc:
        raise PreparationError("file_not_found", f"{label} does not exist: {path}") from exc
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PreparationError("invalid_json", f"{label} is invalid UTF-8 JSON: {exc}") from exc
    require(isinstance(value, dict), "invalid_document", f"{label} must be a JSON object.")
    return value, payload, sha256_bytes(payload)


def save_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    require(path.is_file(), "file_not_found", f"File does not exist: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_hash(value: dict[str, Any], own_hash_field: str) -> str:
    clone = deepcopy(value)
    clone.pop(own_hash_field, None)
    encoded = json.dumps(clone, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def stable_id(prefix: str, candidate_sha256: str, identity: Any) -> str:
    canonical = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(f"{candidate_sha256}\n{canonical}".encode("utf-8")).hexdigest()[:12].upper()
    return f"{prefix}-{digest}"


def artifact_id(path: str, digest: str) -> str:
    value = hashlib.sha256(f"{path}\0{digest}".encode("utf-8")).hexdigest()[:12].upper()
    return f"ART-{value}"


def normalize_candidate_id(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii").lower())
    slug = slug.strip("-")
    require(bool(slug), "invalid_candidate_id", "candidate-id must contain at least one letter or digit.")
    return slug


def require_sha256(value: Any, field: str) -> str:
    require(isinstance(value, str) and bool(re.fullmatch(r"[a-f0-9]{64}", value)), "invalid_sha256", f"{field} must be a lowercase SHA-256 digest.")
    return value


def path_is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def require_no_symlink_components(path: Path, label: str) -> None:
    """Reject every existing symlink component before an output mutation."""
    lexical = Path(os.path.abspath(path))
    current = Path(lexical.anchor)
    for part in lexical.parts[1:]:
        current /= part
        require(not current.is_symlink(), "unsafe_output_symlink", f"{label} contains a symlink component: {current}")


def require_safe_output_path(path: Path, root: Path, label: str) -> None:
    """Require a lexical, symlink-free output path beneath a trusted real root."""
    lexical_root = Path(os.path.abspath(root))
    lexical_path = Path(os.path.abspath(path))
    try:
        lexical_path.relative_to(lexical_root)
    except ValueError as exc:
        raise PreparationError("unsafe_output_path", f"{label} is outside the canonical evaluation root: {lexical_path}") from exc
    require_no_symlink_components(lexical_root, "Canonical evaluation root")
    require_no_symlink_components(lexical_path.parent, label)
    require(not lexical_path.is_symlink(), "unsafe_output_symlink", f"{label} cannot be a symlink: {lexical_path}")
    require(path_is_within(lexical_path.parent, lexical_root), "unsafe_output_path", f"{label} resolves outside the canonical evaluation root: {lexical_path}")


def replace_bytes_atomic(path: Path, payload: bytes) -> None:
    """Replace one regular file using a same-directory temporary file."""
    require_no_symlink_components(path.parent, "Output parent")
    require(not path.is_symlink(), "unsafe_output_symlink", f"Output cannot be a symlink: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    require_no_symlink_components(path.parent, "Output parent")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def safe_relative_path(value: str) -> str:
    path = PurePosixPath(value)
    require(
        not path.is_absolute() and ".." not in path.parts and value not in {"", "."} and "\\" not in value,
        "unsafe_path",
        f"Path is not a safe relative POSIX path: {value}",
    )
    return str(path)


def normalize_locator_key(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = unicodedata.normalize("NFKC", value).strip()
    normalized = re.sub(r"[‐‑‒–—−]", "-", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    if re.fullmatch(r"[0-9]+", normalized):
        normalized = str(int(normalized))
    return normalized.casefold()


def validate_self_hash(value: dict[str, Any], field: str, label: str) -> None:
    recorded = require_sha256(value.get(field), f"{label}.{field}")
    require(recorded == canonical_hash(value, field), "canonical_hash_mismatch", f"{label} canonical hash does not recompute.")


def require_schema(value: Any, schema_name: str, label: str) -> None:
    errors = schema_errors(value, schema_name)
    require(not errors, "schema_validation_failed", f"{label} is structurally invalid.", errors)


def load_source_identities(
    state_path: Path,
    page_map_path: Path,
    chunk_manifest_path: Path,
    policy_path: Path,
    source_edition: str | None,
    documents: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    documents = documents or {}
    state = documents.get("state") or load_json(state_path, "Evaluation state")
    page_map = documents.get("page_map") or load_json(page_map_path, "Page map")
    chunks = documents.get("chunk_manifest") or load_json(chunk_manifest_path, "Chunk manifest")
    policy = documents.get("policy") or load_json(policy_path, "Evaluation policy")
    require_schema(state, "evaluation-state.schema.json", "Evaluation state")
    require_schema(page_map, "page-map.schema.json", "Page map")
    require_schema(chunks, "chunk-manifest.schema.json", "Chunk manifest")
    require_schema(policy, "evaluation-policy-v3.schema.json", "Evaluation policy")
    validate_self_hash(page_map, "page_map_sha256", "Page map")
    validate_self_hash(chunks, "chunk_manifest_sha256", "Chunk manifest")
    validate_self_hash(policy, "policy_sha256", "Evaluation policy")
    source = state.get("source") if isinstance(state.get("source"), dict) else {}
    source_sha = require_sha256(source.get("sha256"), "state.source.sha256")
    edition = source_edition or source.get("edition")
    require(isinstance(edition, str) and edition.strip(), "edition_identity_required", "A frozen source-edition identity is required for candidate preparation.")
    require(page_map.get("source_sha256") == source_sha, "source_hash_mismatch", "Page map source hash does not match the evaluation state.")
    require(chunks.get("page_map_sha256") == page_map.get("page_map_sha256"), "page_map_mismatch", "Chunk manifest does not reference the supplied page map.")
    scope = policy.get("source_scope") if isinstance(policy.get("source_scope"), dict) else {}
    for key, actual in (
        ("source_sha256", source_sha),
        ("page_map_sha256", page_map.get("page_map_sha256")),
        ("chunk_manifest_sha256", chunks.get("chunk_manifest_sha256")),
    ):
        require(scope.get(key) == actual, "policy_identity_mismatch", f"Evaluation policy {key} does not match the frozen source identity.")
    configuration = state.get("configuration") if isinstance(state.get("configuration"), dict) else {}
    policy_profile = policy.get("policy_profile", {}).get("id")
    rubric_version = configuration.get("rubric_version")
    audit_mode = policy.get("audit_design", {}).get("mode")
    require(configuration.get("policy_profile") == policy_profile, "policy_identity_mismatch", "State and policy profile identities differ.")
    require(rubric_version == "subject-index-rubric-v7", "rubric_identity_mismatch", "Candidate preparation requires the current V7 rubric identity.")
    require(configuration.get("audit_mode") == audit_mode, "audit_mode_mismatch", "State and policy audit modes differ.")
    return {
        "state": state,
        "page_map": page_map,
        "chunk_manifest": chunks,
        "policy": policy,
        "source_sha256": source_sha,
        "source_edition": edition.strip(),
        "page_map_sha256": page_map["page_map_sha256"],
        "chunk_manifest_sha256": chunks["chunk_manifest_sha256"],
        "policy_sha256": policy["policy_sha256"],
        "policy_profile": policy_profile,
        "rubric_version": rubric_version,
        "audit_mode": audit_mode,
    }


def flatten_layout(layout: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    pages = layout.get("pages") if isinstance(layout.get("pages"), list) else []
    regions: list[dict[str, Any]] = []
    lines: list[dict[str, Any]] = []
    for page in pages:
        for region in page.get("regions", []):
            region_copy = {**region, "candidate_pdf_page": page.get("candidate_pdf_page")}
            regions.append(region_copy)
            for line in region.get("lines", []):
                lines.append({
                    **line,
                    "candidate_pdf_page": page.get("candidate_pdf_page"),
                    "region_id": region.get("region_id"),
                    "region_order": region.get("region_order"),
                })
    return pages, regions, lines


def merge_continuation_lines(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for line in lines:
        if line.get("inferred_boundary") == "header_footer" or line.get("excluded_from_index") is True:
            continue
        text = str(line.get("displayed_line_text", "")).strip()
        if not text:
            continue
        continuation = line.get("continuation_status") in {
            "continues_previous",
            "continued_from_previous_column",
            "continued_from_previous_page",
        }
        if continuation and groups:
            previous = groups[-1]
            joiner = "" if text[:1] in {",", ";", ":"} else " "
            previous["displayed_line_text"] += joiner + text
            previous["original_displayed_form"] += "\n" + str(line.get("original_displayed_form", text))
            previous["line_ids"].append(line.get("line_id"))
            previous["candidate_pdf_pages"].append(line.get("candidate_pdf_page"))
            previous["region_ids"].append(line.get("region_id"))
            previous["bboxes"].append(line.get("bbox"))
            previous["continuation_statuses"].append(line.get("continuation_status"))
            previous["extraction_warnings"].extend(line.get("extraction_warnings", []))
            continue
        groups.append({
            "displayed_line_text": text,
            "original_displayed_form": str(line.get("original_displayed_form", text)),
            "indentation_level": int(line.get("indentation_level", 0)),
            "line_ids": [line.get("line_id")],
            "candidate_pdf_pages": [line.get("candidate_pdf_page")],
            "region_ids": [line.get("region_id")],
            "bboxes": [line.get("bbox")],
            "continuation_statuses": [line.get("continuation_status")],
            "extraction_warnings": list(line.get("extraction_warnings", [])),
            "confidence": line.get("confidence"),
        })
    return groups


def split_references(payload: str) -> tuple[str, list[dict[str, str]], bool]:
    marker = re.compile(
        r"(?i)(?:^|[;,.]\s*)(see\s+also|see(?!\s+also\b))\s+(.+?)"
        r"(?=(?:\s*[;,.]\s*see(?:\s+also)?\s)|$)"
    )
    matches = list(marker.finditer(payload))
    references: list[dict[str, str]] = []
    for match in matches:
        target = match.group(2).strip(" ,;.")
        references.append({"type": "see also" if "also" in match.group(1).casefold() else "see", "target": target})
    malformed_marker = re.search(r"(?i)\bsee\b", payload) if not matches else None
    locator_text = (
        payload[: matches[0].start()].strip(" ,;.")
        if matches
        else payload[:malformed_marker.start()].strip(" ,;.") if malformed_marker
        else payload.strip()
    )
    malformed = malformed_marker is not None
    return locator_text, references, malformed


def looks_like_locator_payload(value: str, lookup: dict[str, dict[str, Any]]) -> bool:
    stripped = value.strip()
    if re.match(r"(?i)^see(?:\s+also)?\b", stripped):
        return True
    first = re.split(r"[,;]", stripped, maxsplit=1)[0].strip()
    if normalize_locator_key(first) in lookup:
        return True
    for separator in re.finditer(r"(?:–|—|‑|‒|−|--|-)", first):
        start = first[:separator.start()].strip()
        end = first[separator.end():].strip()
        if (
            start
            and end
            and normalize_locator_key(start) in lookup
            and normalize_locator_key(end) in lookup
        ):
            return True
    # Arbitrary alphabetic text is a heading continuation, not a locator.  Any
    # prefixed/alphabetic locator must be present in the frozen page map and is
    # accepted by the exact lookup above.  The fallback is limited to numeric
    # and Roman forms so prose such as ``continued mechanisms`` cannot create a
    # false heading boundary.
    return bool(
        re.fullmatch(
            r"(?:[0-9]+|[ivxlcdm]+)(?:\s*[–—‑‒−-]\s*(?:[0-9]+|[ivxlcdm]+))?",
            first,
            re.I,
        )
    )


def split_heading_and_payload(text: str, lookup: dict[str, dict[str, Any]]) -> tuple[str, str]:
    for match in re.finditer(r"[,;:]", text):
        tail = text[match.end():].strip()
        if looks_like_locator_payload(tail, lookup):
            return text[: match.start()].strip(), tail
    ref = re.search(r"(?i)\bsee(?:\s+also)?\b", text)
    if ref:
        return text[: ref.start()].strip(" ,;:."), text[ref.start():].strip()
    return text.strip(), ""


def page_map_lookup(page_map: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[int, int], list[dict[str, Any]]]:
    pages = page_map.get("pages") if isinstance(page_map.get("pages"), list) else []
    lookup: dict[str, dict[str, Any]] = {}
    index_by_document_page: dict[int, int] = {}
    for index, page in enumerate(pages):
        index_by_document_page[page.get("document_page")] = index
        key = page.get("normalized_locator_key")
        if isinstance(key, str) and page.get("accepts_index_locators"):
            require(key not in lookup, "ambiguous_page_map", f"Indexable locator key appears more than once: {key}")
            lookup[key] = page
    return lookup, index_by_document_page, pages


def resolve_abbreviated_endpoint(
    start: dict[str, Any],
    raw_end: str,
    pages: list[dict[str, Any]],
    index_by_document_page: dict[int, int],
) -> tuple[dict[str, Any] | None, str | None]:
    start_label = str(start.get("source_page_label", ""))
    if not (start_label.isdigit() and raw_end.isdigit() and len(raw_end) < len(start_label)):
        return None, None
    start_index = index_by_document_page[start["document_page"]]
    completed_label = start_label[:-len(raw_end)] + raw_end
    candidates = [
        page for page in pages[start_index + 1:]
        if page.get("mapping_id") == start.get("mapping_id")
        and page.get("accepts_index_locators")
        and str(page.get("source_page_label", "")) == completed_label
    ]
    if len(candidates) == 1:
        return candidates[0], None
    if len(candidates) > 1:
        return None, "abbreviated_endpoint_ambiguous"
    return None, "abbreviated_endpoint_unresolved"


def locator_assignments_for_display(
    displayed: str,
    display_id: str,
    candidate_sha: str,
    lookup: dict[str, dict[str, Any]],
    index_by_document_page: dict[int, int],
    pages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    token = displayed.strip()
    normalized = normalize_locator_key(token)
    exact = lookup.get(normalized or "")
    exceptions: list[dict[str, Any]] = []
    if exact:
        locator_id = stable_id("LOC", candidate_sha, {"display_id": display_id, "document_page": exact["document_page"]})
        assignment = {
            "locator_id": locator_id,
            "display_id": display_id,
            "displayed_locator": token,
            "source_page_label": exact.get("source_page_label"),
            "normalized_locator_key": exact.get("normalized_locator_key"),
            "document_page": exact.get("document_page"),
            "mapping_status": "resolved",
            "range_id": None,
        }
        return [assignment], {"display_id": display_id, "displayed_locator": token, "kind": "point", "range_id": None, "mapping_status": "resolved", "locator_ids": [locator_id]}, []

    split_candidates: list[tuple[str, str, dict[str, Any], dict[str, Any] | None, str | None]] = []
    for separator in re.finditer(r"(?:–|—|‑|‒|−|--|-)", token):
        raw_start = token[:separator.start()].strip()
        raw_end = token[separator.end():].strip()
        if not raw_start or not raw_end:
            continue
        start = lookup.get(normalize_locator_key(raw_start) or "")
        if not start:
            continue
        end = lookup.get(normalize_locator_key(raw_end) or "")
        end_reason = None
        direct_precedes_start = bool(
            end
            and index_by_document_page.get(end.get("document_page"), -1)
            < index_by_document_page.get(start.get("document_page"), -1)
        )
        if not end or direct_precedes_start:
            abbreviated, abbreviated_reason = resolve_abbreviated_endpoint(start, raw_end, pages, index_by_document_page)
            if abbreviated is not None:
                end, end_reason = abbreviated, None
            elif not end:
                end_reason = abbreviated_reason
            else:
                end_reason = "range_endpoint_reversed"
        split_candidates.append((raw_start, raw_end, start, end, end_reason))
    if split_candidates:
        uniquely_resolved = [item for item in split_candidates if item[3] is not None]
        selected_splits = uniquely_resolved if uniquely_resolved else split_candidates
        if len(selected_splits) == 1:
            raw_start, raw_end, start, end, end_reason = selected_splits[0]
        else:
            raw_start, raw_end, start, end, end_reason = selected_splits[0]
            end = None
            end_reason = "range_boundary_ambiguous"
        range_id = stable_id("RANGE", candidate_sha, {"display_id": display_id, "displayed_locator": token})
        if start and end:
            start_index = index_by_document_page[start["document_page"]]
            end_index = index_by_document_page[end["document_page"]]
            between = pages[start_index:end_index + 1] if end_index >= start_index else []
            compatible = bool(between) and all(
                page.get("mapping_id") == start.get("mapping_id") == end.get("mapping_id")
                and page.get("accepts_index_locators")
                for page in between
            )
            if compatible:
                assignments = []
                for page in between:
                    locator_id = stable_id("LOC", candidate_sha, {"display_id": display_id, "document_page": page["document_page"]})
                    assignments.append({
                        "locator_id": locator_id,
                        "display_id": display_id,
                        "displayed_locator": token,
                        "source_page_label": page.get("source_page_label"),
                        "normalized_locator_key": page.get("normalized_locator_key"),
                        "document_page": page.get("document_page"),
                        "mapping_status": "resolved",
                        "range_id": range_id,
                    })
                return assignments, {
                    "display_id": display_id,
                    "displayed_locator": token,
                    "kind": "range",
                    "range_id": range_id,
                    "start_display": raw_start,
                    "end_display": raw_end,
                    "mapping_status": "resolved",
                    "locator_ids": [item["locator_id"] for item in assignments],
                }, []
        reason = end_reason or ("range_mapping_segment_mismatch" if start and end else "range_endpoint_unresolved")
        locator_id = stable_id("LOC", candidate_sha, {"display_id": display_id, "unresolved": token})
        assignment = {
            "locator_id": locator_id,
            "display_id": display_id,
            "displayed_locator": token,
            "source_page_label": None,
            "normalized_locator_key": normalized,
            "document_page": None,
            "mapping_status": "unresolved",
            "range_id": range_id,
        }
        exceptions.append({"type": reason, "related_ids": [display_id, locator_id], "displayed_form": token})
        return [assignment], {"display_id": display_id, "displayed_locator": token, "kind": "range", "range_id": range_id, "mapping_status": "unresolved", "locator_ids": [locator_id]}, exceptions

    locator_id = stable_id("LOC", candidate_sha, {"display_id": display_id, "unresolved": token})
    assignment = {
        "locator_id": locator_id,
        "display_id": display_id,
        "displayed_locator": token,
        "source_page_label": token or None,
        "normalized_locator_key": normalized,
        "document_page": None,
        "mapping_status": "unresolved",
        "range_id": None,
    }
    exceptions.append({"type": "locator_unresolved_or_malformed", "related_ids": [display_id, locator_id], "displayed_form": token})
    return [assignment], {"display_id": display_id, "displayed_locator": token, "kind": "point", "range_id": None, "mapping_status": "unresolved", "locator_ids": [locator_id]}, exceptions


def normalize_layout(layout: dict[str, Any], page_map: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    require_schema(layout, "candidate-layout-extraction.schema.json", "Candidate layout extraction")
    require_schema(page_map, "page-map.schema.json", "Page map")
    candidate_id = layout["candidate_id"]
    candidate_sha = layout["candidate_sha256"]
    lookup, index_by_document_page, pages = page_map_lookup(page_map)
    _, _, lines = flatten_layout(layout)
    groups = merge_continuation_lines(lines)
    records: list[dict[str, Any]] = []
    exceptions: list[dict[str, Any]] = []
    heading_stack: list[str] = []

    for record_index, group in enumerate(groups):
        text = group["displayed_line_text"]
        heading, payload = split_heading_and_payload(text, lookup)
        indent = max(0, int(group.get("indentation_level", 0)))
        if not heading:
            exception_id = stable_id("EXC", candidate_sha, {"record_index": record_index, "type": "missing_heading", "text": text})
            exceptions.append({"exception_id": exception_id, "type": "missing_heading", "status": "unresolved", "related_ids": group["line_ids"], "displayed_form": text, "detail": "No entry or subentry heading could be identified."})
            continue
        indentation_gap = indent > len(heading_stack)
        if indent == 0:
            heading_path = [heading]
            heading_stack = [heading]
        else:
            parent_depth = min(indent, len(heading_stack))
            heading_path = heading_stack[:parent_depth] + [heading]
            heading_stack = heading_path
        path_id = stable_id("PATH", candidate_sha, {"record_index": record_index, "heading_path": heading_path})
        record_id = stable_id("REC", candidate_sha, {"record_index": record_index, "line_ids": group["line_ids"]})
        if indentation_gap:
            exception_id = stable_id("EXC", candidate_sha, {"record_id": record_id, "type": "indentation_gap"})
            exceptions.append({"exception_id": exception_id, "type": "indentation_gap", "status": "unresolved", "related_ids": [record_id, *group["line_ids"]], "displayed_form": text, "detail": "Delivered indentation skipped an available parent level; the available parent chain was preserved without editorial repair."})

        locator_text, reference_specs, malformed_reference = split_references(payload)
        locator_tokens = [item.strip() for item in re.split(r"[,;]", locator_text) if item.strip()]
        locator_displays: list[dict[str, Any]] = []
        locator_assignments: list[dict[str, Any]] = []
        for display_index, token in enumerate(locator_tokens):
            display_id = stable_id("DISPLAY", candidate_sha, {"record_id": record_id, "display_index": display_index, "displayed_locator": token})
            assignments, display, display_exceptions = locator_assignments_for_display(
                token, display_id, candidate_sha, lookup, index_by_document_page, pages
            )
            locator_displays.append(display)
            locator_assignments.extend(assignments)
            for exception in display_exceptions:
                exception_id = stable_id("EXC", candidate_sha, {"record_id": record_id, "display_id": display_id, "type": exception["type"]})
                exceptions.append({
                    "exception_id": exception_id,
                    "status": "unresolved",
                    "record_id": record_id,
                    "line_ids": group["line_ids"],
                    "detail": "The displayed locator was retained exactly and was not guessed or repaired.",
                    **exception,
                })

        cross_references: list[dict[str, Any]] = []
        for reference_index, spec in enumerate(reference_specs):
            reference_id = stable_id("XREF", candidate_sha, {"record_id": record_id, "reference_index": reference_index, **spec})
            cross_references.append({
                "reference_id": reference_id,
                "type": spec["type"],
                "target": spec["target"],
                "target_path_id": None,
                "original_displayed_form": spec["target"],
            })
            if not spec["target"]:
                exception_id = stable_id("EXC", candidate_sha, {"reference_id": reference_id, "type": "malformed_cross_reference"})
                exceptions.append({"exception_id": exception_id, "type": "malformed_cross_reference", "status": "unresolved", "related_ids": [record_id, reference_id], "record_id": record_id, "line_ids": group["line_ids"], "displayed_form": text, "detail": "Cross-reference target is empty."})
        if malformed_reference:
            exception_id = stable_id("EXC", candidate_sha, {"record_id": record_id, "type": "malformed_cross_reference"})
            exceptions.append({"exception_id": exception_id, "type": "malformed_cross_reference", "status": "unresolved", "related_ids": [record_id], "record_id": record_id, "line_ids": group["line_ids"], "displayed_form": text, "detail": "A see marker could not be parsed without changing the delivered text."})
        if cross_references and locator_assignments:
            record_type = "mixed"
        elif cross_references:
            record_type = "cross_reference"
        elif locator_assignments:
            record_type = "page_bearing"
        else:
            record_type = "container"
        records.append({
            "record_id": record_id,
            "record_type": record_type,
            "path_id": path_id,
            "heading_path": heading_path,
            "delivered_indentation_level": indent,
            "original_displayed_form": group["original_displayed_form"],
            "locator_displays": locator_displays,
            "locator_assignments": locator_assignments,
            "cross_references": cross_references,
            "normalization_confidence": group.get("confidence"),
            "extraction_warnings": sorted(set(group.get("extraction_warnings", []))),
            "private_evidence": {
                "layout_line_ids": group["line_ids"],
                "candidate_pdf_pages": sorted(set(group["candidate_pdf_pages"])),
                "region_ids": list(dict.fromkeys(group["region_ids"])),
                "bboxes": group["bboxes"],
                "continuation_statuses": group["continuation_statuses"],
            },
        })

    candidate = {
        "schema_version": "candidate-index-v2",
        "candidate_id": candidate_id,
        "candidate_sha256": candidate_sha,
        "page_map_sha256": page_map.get("page_map_sha256"),
        "records": records,
        "normalization": {
            "engine": "candidate-preparation-cli",
            "engine_version": "1.0.0",
            "record_count": len(records),
            "main_heading_count": sum(len(item["heading_path"]) == 1 for item in records),
            "subheading_count": sum(len(item["heading_path"]) > 1 for item in records),
            "complete_heading_path_count": len(records),
            "displayed_locator_count": sum(len(item["locator_displays"]) for item in records),
            "expanded_locator_assignment_count": sum(len(item["locator_assignments"]) for item in records),
            "cross_reference_count": sum(len(item["cross_references"]) for item in records),
            "unresolved_locator_count": sum(assignment["mapping_status"] != "resolved" for item in records for assignment in item["locator_assignments"]),
            "editorial_corrections_applied": False,
            "benchmark_content_used": False,
        },
    }
    inventory = build_inventory(candidate)
    exception_ledger = {
        "schema_version": "candidate-normalization-exceptions-v1",
        "candidate_id": candidate_id,
        "candidate_sha256": candidate_sha,
        "page_map_sha256": page_map.get("page_map_sha256"),
        "exceptions": exceptions,
        "counts": {
            "total": len(exceptions),
            "unresolved": sum(item.get("status") == "unresolved" for item in exceptions),
            "by_type": {key: sum(item.get("type") == key for item in exceptions) for key in sorted({item.get("type") for item in exceptions})},
        },
    }
    report = {
        "schema_version": "candidate-normalization-report-v1",
        "candidate_id": candidate_id,
        "candidate_sha256": candidate_sha,
        "source_sha256": page_map.get("source_sha256"),
        "page_map_sha256": page_map.get("page_map_sha256"),
        "adapter": layout.get("adapter"),
        "counts": {
            **candidate["normalization"],
            "candidate_pdf_pages": len(layout.get("pages", [])),
            "reading_order_regions": sum(len(page.get("regions", [])) for page in layout.get("pages", [])),
            "extracted_lines": sum(len(region.get("lines", [])) for page in layout.get("pages", []) for region in page.get("regions", [])),
            "normalization_exceptions": len(exceptions),
        },
        "status": "awaiting_full_normalization_qa",
        "candidate_quality_judgments_performed": False,
    }
    return candidate, inventory, exception_ledger, report


def expected_qa_inventory(
    layout: dict[str, Any],
    candidate: dict[str, Any],
    exceptions: dict[str, Any],
) -> dict[str, list[Any]]:
    pages, regions, lines = flatten_layout(layout)
    records = candidate.get("records", [])
    return {
        "candidate_pdf_pages": [page.get("candidate_pdf_page") for page in pages],
        "region_ids": [region.get("region_id") for region in regions],
        "line_ids": [line.get("line_id") for line in lines],
        "excluded_line_ids": [line.get("excluded_line_id") for line in layout.get("excluded_lines", [])],
        "main_heading_record_ids": [item.get("record_id") for item in records if len(item.get("heading_path", [])) == 1],
        "subheading_record_ids": [item.get("record_id") for item in records if len(item.get("heading_path", [])) > 1],
        "path_ids": [item.get("path_id") for item in records],
        "display_ids": [display.get("display_id") for item in records for display in item.get("locator_displays", [])],
        "locator_ids": [locator.get("locator_id") for item in records for locator in item.get("locator_assignments", [])],
        "cross_reference_ids": [reference.get("reference_id") for item in records for reference in item.get("cross_references", [])],
        "exception_ids": [item.get("exception_id") for item in exceptions.get("exceptions", [])],
    }


def expected_page_reviews(layout: dict[str, Any], candidate: dict[str, Any], exceptions: dict[str, Any]) -> list[dict[str, Any]]:
    pages, _, _ = flatten_layout(layout)
    records = candidate.get("records", [])
    exception_records = exceptions.get("exceptions", [])
    result: list[dict[str, Any]] = []
    for page in pages:
        page_number = page.get("candidate_pdf_page")
        page_regions = page.get("regions", [])
        page_lines = [line for region in page_regions for line in region.get("lines", [])]
        page_records = [
            record for record in records
            if page_number in record.get("private_evidence", {}).get("candidate_pdf_pages", [])
        ]
        page_record_ids = [record.get("record_id") for record in page_records]
        page_line_ids = {line.get("line_id") for line in page_lines}
        page_exception_ids = [
            item.get("exception_id") for item in exception_records
            if page_line_ids.intersection(item.get("line_ids", []))
            or page_line_ids.intersection(item.get("related_ids", []))
        ]
        continuation_line_ids = [
            line.get("line_id") for line in page_lines
            if line.get("continuation_status") not in {None, "none", "standalone"}
        ]
        result.append({
            "candidate_pdf_page": page_number,
            "region_ids": [region.get("region_id") for region in page_regions],
            "line_ids": [line.get("line_id") for line in page_lines],
            "first_record_id": page_record_ids[0] if page_record_ids else None,
            "last_record_id": page_record_ids[-1] if page_record_ids else None,
            "first_line_id": page_lines[0].get("line_id") if page_lines else None,
            "last_line_id": page_lines[-1].get("line_id") if page_lines else None,
            "record_count": len(page_record_ids),
            "line_count": len(page_lines),
            "continuation_line_ids": continuation_line_ids,
            "exception_ids": page_exception_ids,
            "corrections": [],
            "continuation_handling_reviewed": False,
            "reproduces_candidate_not_editorial_improvement": False,
        })
    return result


def build_qa_template(
    layout: dict[str, Any],
    candidate: dict[str, Any],
    inventory_path: Path,
    candidate_path: Path,
    layout_path: Path,
    exceptions: dict[str, Any],
) -> dict[str, Any]:
    expected = expected_qa_inventory(layout, candidate, exceptions)
    return {
        "schema_version": "candidate-normalization-qa-v1",
        "candidate_id": candidate.get("candidate_id"),
        "candidate_sha256": candidate.get("candidate_sha256"),
        "source_sha256": layout.get("source_sha256"),
        "page_map_sha256": candidate.get("page_map_sha256"),
        "normalized_candidate_file_sha256": sha256_file(candidate_path),
        "item_inventory_file_sha256": sha256_file(inventory_path),
        "layout_extraction_file_sha256": sha256_file(layout_path),
        "review_mode": "full",
        "expected": expected,
        "reviewed": {key: [] for key in expected},
        "page_reviews": expected_page_reviews(layout, candidate, exceptions),
        "corrections": [],
        "exception_dispositions": [],
        "completion": {
            "all_denominators_complete": False,
            "all_exceptions_dispositioned": False,
            "candidate_reproduction_confirmed": False,
            "editorial_quality_judgments_performed": False,
            "complete": False,
        },
    }


def default_provenance() -> dict[str, Any]:
    return {
        "candidate_bytes": {"status": "verified", "rationale": "The candidate bytes were hashed directly."},
        "internal_pdf_completeness": {"status": "not_independently_verified", "rationale": "PDF page presence does not prove the delivered index is complete."},
        "structural_continuity": {"status": "not_independently_verified", "rationale": "Alphabetical and structural continuity require an explicit preparation review."},
        "source_edition_compatibility": {"status": "not_independently_verified", "rationale": "Edition compatibility requires provenance evidence beyond matching filenames."},
        "locator_page_map_compatibility": {"status": "not_independently_verified", "rationale": "Locator compatibility requires complete normalization QA."},
        "authoritative_copy_fidelity": {"status": "not_independently_verified", "rationale": "Internal completeness is not authoritative-copy fidelity."},
    }


def build_candidate_ref(
    candidate_path: Path,
    layout: dict[str, Any],
    identities: dict[str, Any],
    file_origin: str,
    provenance: dict[str, Any],
) -> dict[str, Any]:
    if file_origin in {"reconstructed_pdf", "transcription"} and provenance.get("authoritative_copy_fidelity", {}).get("claimed_original_publisher_pdf"):
        require(False, "invalid_provenance", "A reconstructed PDF or transcription cannot claim to be an original publisher PDF.")
    candidate_sha = sha256_file(candidate_path)
    require(candidate_sha == layout.get("candidate_sha256"), "candidate_hash_mismatch", "Candidate bytes do not match the layout extraction hash.")
    require(provenance.get("candidate_bytes", {}).get("status") == "verified", "candidate_bytes_unverified", "Candidate preparation requires verified candidate bytes.")
    return {
        "schema_version": "candidate-ref-v1",
        "candidate_id": layout.get("candidate_id"),
        "candidate_sha256": candidate_sha,
        "candidate_filename": candidate_path.name,
        "file_origin": file_origin,
        "source": {
            "sha256": identities["source_sha256"],
            "edition": identities["source_edition"],
        },
        "page_map_sha256": identities["page_map_sha256"],
        "chunk_manifest_sha256": identities["chunk_manifest_sha256"],
        "policy": {
            "profile": identities["policy_profile"],
            "sha256": identities["policy_sha256"],
            "rubric_version": identities["rubric_version"],
            "audit_mode": identities["audit_mode"],
        },
        "pdf": {
            "page_count": layout.get("pdf", {}).get("page_count"),
            "producer": layout.get("pdf", {}).get("producer"),
            "has_embedded_text": layout.get("pdf", {}).get("has_embedded_text"),
        },
        "provenance": provenance,
        "created_at": now(),
    }


def build_layout_profile(layout: dict[str, Any]) -> dict[str, Any]:
    pages, regions, lines = flatten_layout(layout)
    column_counts = [len([region for region in page.get("regions", []) if region.get("role") == "index_column"]) for page in pages]
    return {
        "schema_version": "candidate-layout-profile-v1",
        "candidate_id": layout.get("candidate_id"),
        "candidate_sha256": layout.get("candidate_sha256"),
        "adapter": layout.get("adapter"),
        "pdf": {
            "page_count": layout.get("pdf", {}).get("page_count"),
            "producer": layout.get("pdf", {}).get("producer"),
            "has_embedded_text": layout.get("pdf", {}).get("has_embedded_text"),
        },
        "layout": {
            "reading_order": "page_then_region_then_line",
            "page_count": len(pages),
            "region_count": len(regions),
            "line_count": len(lines),
            "index_columns_per_page": column_counts,
            "header_footer_lines": sum(line.get("inferred_boundary") == "header_footer" for line in lines),
            "continuation_lines": sum(line.get("continuation_status") not in {None, "none", "standalone"} for line in lines),
        },
        "limitations": list(layout.get("limitations", [])),
    }


def paths_for_normalization_output(root: Path, candidate_id: str) -> dict[str, Path]:
    normalized = normalize_candidate_id(candidate_id)
    return {
        "candidate_ref": root / "candidates" / normalized / "candidate-ref.json",
        "layout_profile": root / "candidates" / normalized / "layout-profile.json",
        "layout_extraction": root / "candidates" / normalized / "candidate-layout-extraction.v1.json",
        "candidate_index": root / "candidates" / normalized / "candidate-index.draft.v2.json",
        "item_inventory": root / "candidates" / normalized / "item-inventory.draft.v2.json",
        "normalization_exceptions": root / "candidates" / normalized / "normalization-exceptions.v1.json",
        "normalization_report": root / "validation" / f"candidate-normalization-report.{normalized}.v1.json",
        "normalization_qa": root / "validation" / f"candidate-normalization-qa.{normalized}.v1.template.json",
    }


def command_extract(args: argparse.Namespace) -> None:
    candidate_path = Path(args.candidate_file).resolve()
    source_sha = require_sha256(args.source_sha256, "source_sha256")
    geometry = load_json(Path(args.geometry_input), "Synthetic geometry input") if args.geometry_input else None
    result = extract_candidate_layout(candidate_path, args.candidate_id, args.adapter, geometry)
    result["source_sha256"] = source_sha
    require_schema(result, "candidate-layout-extraction.schema.json", "Candidate layout extraction")
    output = Path(args.output).resolve()
    require(not output.exists() or args.force, "output_exists", f"Refusing to overwrite {output}")
    save_json(output, result)
    emit({
        "command": "extract-candidate-layout",
        "ok": True,
        "candidate_id": args.candidate_id,
        "candidate_sha256": result.get("candidate_sha256"),
        "adapter": result.get("adapter"),
        "artifact_written": str(output),
        "warnings": result.get("limitations", []),
    })


def command_normalize(args: argparse.Namespace) -> None:
    state_path = Path(args.state).resolve()
    page_map_path = Path(args.page_map).resolve()
    chunk_manifest_path = Path(args.chunk_manifest).resolve()
    policy_path = Path(args.policy).resolve()
    candidate_path = Path(args.candidate_file).resolve()
    layout_input_path = Path(args.layout).resolve()
    layout = load_json(layout_input_path, "Candidate layout extraction")
    require_schema(layout, "candidate-layout-extraction.schema.json", "Candidate layout extraction")
    require(layout.get("candidate_id") == args.candidate_id, "candidate_id_mismatch", "Command candidate ID does not match layout extraction.")
    identities = load_source_identities(state_path, page_map_path, chunk_manifest_path, policy_path, args.source_edition)
    require(layout.get("source_sha256") in {None, identities["source_sha256"]}, "source_hash_mismatch", "Layout extraction source identity conflicts with the preparation state.")
    layout["source_sha256"] = identities["source_sha256"]
    page_map = identities["page_map"]
    candidate, inventory, exceptions, report = normalize_layout(layout, page_map)
    provenance = load_json(Path(args.provenance), "Candidate provenance") if args.provenance else default_provenance()
    candidate_ref = build_candidate_ref(candidate_path, layout, identities, args.file_origin, provenance)
    layout_profile = build_layout_profile(layout)
    output_root = Path(args.output_dir).resolve()
    paths = paths_for_normalization_output(output_root, args.candidate_id)
    existing = [str(path) for path in paths.values() if path.exists()]
    require(not existing or args.force, "output_exists", "Refusing to overwrite existing preparation artifacts.", existing)
    for document, schema_name, label in (
        (candidate_ref, "candidate-ref.schema.json", "Candidate reference"),
        (layout_profile, "candidate-layout-profile.schema.json", "Candidate layout profile"),
        (layout, "candidate-layout-extraction.schema.json", "Candidate layout extraction"),
        (candidate, "candidate-index-v2.schema.json", "Normalized candidate"),
        (inventory, "item-inventory-v2.schema.json", "Item inventory"),
        (exceptions, "candidate-normalization-exceptions.schema.json", "Normalization exceptions"),
    ):
        require_schema(document, schema_name, label)
    save_json(paths["candidate_ref"], candidate_ref)
    save_json(paths["layout_profile"], layout_profile)
    save_json(paths["layout_extraction"], layout)
    save_json(paths["candidate_index"], candidate)
    save_json(paths["item_inventory"], inventory)
    save_json(paths["normalization_exceptions"], exceptions)
    report["private_artifact_hashes"] = {
        "layout_extraction": sha256_file(paths["layout_extraction"]),
        "candidate_index": sha256_file(paths["candidate_index"]),
        "item_inventory": sha256_file(paths["item_inventory"]),
        "normalization_exceptions": sha256_file(paths["normalization_exceptions"]),
    }
    require_schema(report, "candidate-normalization-report.schema.json", "Normalization report")
    save_json(paths["normalization_report"], report)
    qa = build_qa_template(
        layout,
        candidate,
        paths["item_inventory"],
        paths["candidate_index"],
        paths["layout_extraction"],
        exceptions,
    )
    qa["source_sha256"] = identities["source_sha256"]
    require_schema(qa, "candidate-normalization-qa.schema.json", "Normalization QA")
    save_json(paths["normalization_qa"], qa)
    emit({
        "command": "normalize-candidate-layout",
        "ok": True,
        "candidate_id": args.candidate_id,
        "candidate_sha256": candidate.get("candidate_sha256"),
        "canonical_state_mutated": False,
        "artifacts_written": [
            {"artifact": key, "path": str(path), "sha256": sha256_file(path)}
            for key, path in paths.items()
        ],
        "next_actions": ["perform_full_normalization_qa", "validate-private"],
        "warnings": ["The QA file is a template; registration requires every denominator to be reviewed."],
    })


def preparation_paths(root: Path, candidate_id: str, qa_path: Path | None = None) -> dict[str, Path]:
    paths = paths_for_normalization_output(root, candidate_id)
    if qa_path is not None:
        paths["normalization_qa"] = qa_path.resolve()
    return paths


def _duplicate_values(values: Iterable[Any]) -> list[Any]:
    seen: set[Any] = set()
    duplicates: list[Any] = []
    for value in values:
        if value in seen and value not in duplicates:
            duplicates.append(value)
        seen.add(value)
    return duplicates


def _walk_object(value: Any, path: str = "$") -> Iterable[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{path}.{key}"
            yield child, item
            yield from _walk_object(item, child)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk_object(item, f"{path}[{index}]")


def _check_prelock_separation(artifacts: dict[str, dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for label, document in artifacts.items():
        for path, _ in _walk_object(document):
            key = path.rsplit(".", 1)[-1].casefold().replace("-", "_")
            if key in FORBIDDEN_PRELOCK_KEYS:
                errors.append(f"{label}:{path} contains a prohibited pre-lock judgment field")
        encoded = json.dumps(document, ensure_ascii=False).casefold()
        if '"benchmark_content"' in encoded or '"benchmark_subjects"' in encoded:
            errors.append(f"{label} contains benchmark content rather than a pending identity")
    return errors


def _validate_correction(
    correction: dict[str, Any],
    layout_texts: set[str],
    candidate_texts: set[str],
) -> list[str]:
    errors: list[str] = []
    correction_id = correction.get("correction_id")
    before = correction.get("before")
    after = correction.get("after")
    if before not in layout_texts:
        errors.append(f"Correction {correction_id} before text is not present in the delivered layout")
    if after not in candidate_texts:
        errors.append(f"Correction {correction_id} after text is not present in the normalized candidate")
    return errors


def validate_private_preparation(
    root: Path,
    candidate_id: str,
    candidate_file: Path | None,
    state_path: Path,
    page_map_path: Path,
    chunk_manifest_path: Path,
    policy_path: Path,
    qa_path: Path | None = None,
    source_edition: str | None = None,
    identity_documents: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    identities = load_source_identities(state_path, page_map_path, chunk_manifest_path, policy_path, source_edition, identity_documents)
    paths = preparation_paths(root.resolve(), candidate_id, qa_path)
    documents = {key: load_json(path, key.replace("_", " ").title()) for key, path in paths.items()}
    candidate_ref = documents["candidate_ref"]
    profile = documents["layout_profile"]
    layout = documents["layout_extraction"]
    candidate = documents["candidate_index"]
    inventory = documents["item_inventory"]
    exceptions = documents["normalization_exceptions"]
    report = documents["normalization_report"]
    qa = documents["normalization_qa"]
    errors: list[str] = []

    schemas = {
        "candidate_ref": "candidate-ref.schema.json",
        "layout_profile": "candidate-layout-profile.schema.json",
        "layout_extraction": "candidate-layout-extraction.schema.json",
        "candidate_index": "candidate-index-v2.schema.json",
        "item_inventory": "item-inventory-v2.schema.json",
        "normalization_exceptions": "candidate-normalization-exceptions.schema.json",
        "normalization_report": "candidate-normalization-report.schema.json",
        "normalization_qa": "candidate-normalization-qa.schema.json",
    }
    for key, schema_name in schemas.items():
        errors.extend(f"{key}: {error}" for error in schema_errors(documents[key], schema_name))
    require(not errors, "schema_validation_failed", "Candidate preparation artifacts are structurally invalid.", errors)
    normalized_id = normalize_candidate_id(candidate_id)
    for key, document in documents.items():
        if document.get("candidate_id") not in {None, candidate_id, normalized_id}:
            errors.append(f"{key}.candidate_id differs from the selected candidate")

    candidate_sha = require_sha256(candidate_ref.get("candidate_sha256"), "candidate_ref.candidate_sha256")
    actual_candidate_sha = sha256_file(candidate_file.resolve()) if candidate_file is not None else candidate_sha
    if candidate_file is not None and actual_candidate_sha != candidate_sha:
        errors.append("Candidate bytes do not match candidate-ref.json")
    for key in ("layout_extraction", "layout_profile", "candidate_index", "item_inventory", "normalization_exceptions", "normalization_report", "normalization_qa"):
        if documents[key].get("candidate_sha256") != candidate_sha:
            errors.append(f"{key}.candidate_sha256 differs from the verified candidate bytes")
    source_ref = candidate_ref.get("source", {})
    if source_ref.get("sha256") != identities["source_sha256"]:
        errors.append("Candidate source hash differs from the evaluation state")
    if source_ref.get("edition") != identities["source_edition"]:
        errors.append("Candidate source-edition identity differs from the frozen evaluation identity")
    for key, expected in (
        ("page_map_sha256", identities["page_map_sha256"]),
        ("chunk_manifest_sha256", identities["chunk_manifest_sha256"]),
    ):
        if candidate_ref.get(key) != expected:
            errors.append(f"Candidate reference {key} differs from the frozen input")
    policy_ref = candidate_ref.get("policy", {})
    for key, expected in (
        ("profile", identities["policy_profile"]),
        ("sha256", identities["policy_sha256"]),
        ("rubric_version", identities["rubric_version"]),
        ("audit_mode", identities["audit_mode"]),
    ):
        if policy_ref.get(key) != expected:
            errors.append(f"Candidate policy {key} differs from the frozen input")
    expected_pdf_reference = {
        "page_count": layout.get("pdf", {}).get("page_count"),
        "producer": layout.get("pdf", {}).get("producer"),
        "has_embedded_text": layout.get("pdf", {}).get("has_embedded_text"),
    }
    if candidate_ref.get("pdf") != expected_pdf_reference:
        errors.append("Candidate PDF aggregate metadata differs from the common layout projection")
    if layout.get("source_sha256") != identities["source_sha256"]:
        errors.append("Layout extraction source identity differs from the frozen state")
    if report.get("source_sha256") != identities["source_sha256"]:
        errors.append("Normalization report source identity differs from the frozen state")
    if candidate_ref["file_origin"] in {"reconstructed_pdf", "transcription"} and candidate_ref["provenance"]["authoritative_copy_fidelity"].get("claimed_original_publisher_pdf"):
        errors.append("A reconstructed PDF or transcription cannot claim to be an original publisher PDF")

    if candidate.get("page_map_sha256") != identities["page_map_sha256"]:
        errors.append("Normalized candidate does not identify the frozen page map")
    try:
        regenerated_inventory = build_inventory(candidate)
    except SystemExit:
        regenerated_inventory = None
        errors.append("Normalized candidate cannot regenerate a valid deterministic item inventory")
    if regenerated_inventory is not None and regenerated_inventory != inventory:
        errors.append("Item inventory is not the exact deterministic projection of the normalized candidate")

    id_groups = {
        "record_id": [record.get("record_id") for record in candidate.get("records", [])],
        "path_id": [record.get("path_id") for record in candidate.get("records", [])],
        "display_id": [display.get("display_id") for record in candidate.get("records", []) for display in record.get("locator_displays", [])],
        "locator_id": [locator.get("locator_id") for record in candidate.get("records", []) for locator in record.get("locator_assignments", [])],
        "reference_id": [reference.get("reference_id") for record in candidate.get("records", []) for reference in record.get("cross_references", [])],
        "exception_id": [item.get("exception_id") for item in exceptions.get("exceptions", [])],
    }
    for label, values in id_groups.items():
        duplicates = _duplicate_values(values)
        if duplicates:
            errors.append(f"Duplicate {label} values: {duplicates}")

    records = candidate.get("records", [])
    recomputed_counts = {
        "record_count": len(records),
        "main_heading_count": sum(len(item.get("heading_path", [])) == 1 for item in records),
        "subheading_count": sum(len(item.get("heading_path", [])) > 1 for item in records),
        "complete_heading_path_count": len(records),
        "displayed_locator_count": sum(len(item.get("locator_displays", [])) for item in records),
        "expanded_locator_assignment_count": sum(len(item.get("locator_assignments", [])) for item in records),
        "cross_reference_count": sum(len(item.get("cross_references", [])) for item in records),
        "unresolved_locator_count": sum(
            assignment.get("mapping_status") != "resolved"
            for item in records
            for assignment in item.get("locator_assignments", [])
        ),
        "editorial_corrections_applied": False,
        "benchmark_content_used": False,
    }
    if candidate.get("normalization") != {"engine": "candidate-preparation-cli", "engine_version": "1.0.0", **recomputed_counts}:
        errors.append("Normalized candidate aggregate counts or preparation attestations do not recompute exactly")
    exception_items = exceptions.get("exceptions", [])
    recomputed_exception_counts = {
        "total": len(exception_items),
        "unresolved": sum(item.get("status") == "unresolved" for item in exception_items),
        "by_type": {
            key: sum(item.get("type") == key for item in exception_items)
            for key in sorted({item.get("type") for item in exception_items})
        },
    }
    if exceptions.get("counts") != recomputed_exception_counts:
        errors.append("Normalization exception counts do not recompute exactly")

    lookup, index_by_document_page, mapped_pages = page_map_lookup(identities["page_map"])
    exception_related = {
        related
        for item in exceptions.get("exceptions", [])
        for related in item.get("related_ids", []) + item.get("line_ids", [])
        if isinstance(related, str)
    }
    for record in candidate.get("records", []):
        displays = {item.get("display_id"): item for item in record.get("locator_displays", [])}
        assignments_by_display: dict[str, list[dict[str, Any]]] = {}
        for assignment in record.get("locator_assignments", []):
            assignments_by_display.setdefault(assignment.get("display_id"), []).append(assignment)
            if assignment.get("mapping_status") == "resolved":
                mapped = next((page for page in mapped_pages if page.get("document_page") == assignment.get("document_page")), None)
                if not mapped or not mapped.get("accepts_index_locators"):
                    errors.append(f"Resolved locator {assignment.get('locator_id')} is outside the indexable page map")
                elif assignment.get("source_page_label") != mapped.get("source_page_label") or assignment.get("normalized_locator_key") != mapped.get("normalized_locator_key"):
                    errors.append(f"Resolved locator {assignment.get('locator_id')} does not reproduce its page-map record")
            elif assignment.get("locator_id") not in exception_related:
                errors.append(f"Unresolved locator {assignment.get('locator_id')} has no exception-ledger record")
        for display_id, display in displays.items():
            regenerated_assignments, regenerated_display, _ = locator_assignments_for_display(
                str(display.get("displayed_locator", "")), str(display_id), str(candidate_sha), lookup, index_by_document_page, mapped_pages
            )
            if display != regenerated_display or assignments_by_display.get(display_id, []) != regenerated_assignments:
                errors.append(f"Displayed locator {display_id} does not reproduce the frozen page-map expansion")

    expected = expected_qa_inventory(layout, candidate, exceptions)
    if qa.get("expected") != expected:
        errors.append("QA expected inventory is not the exact current normalization inventory")
    reviewed = qa["reviewed"]
    for key, values in expected.items():
        if set(reviewed[key]) != set(values):
            errors.append(f"QA reviewed.{key} is not the exact expected set")

    expected_pages = expected_page_reviews(layout, candidate, exceptions)
    actual_pages = qa["page_reviews"]
    if _duplicate_values([item["candidate_pdf_page"] for item in actual_pages]):
        errors.append("QA page_reviews contains duplicate pages")
    if {item["candidate_pdf_page"] for item in actual_pages} != {item["candidate_pdf_page"] for item in expected_pages}:
        errors.append("QA page_reviews does not cover every candidate PDF page exactly once")
    page_expected_by_id = {item["candidate_pdf_page"]: item for item in expected_pages}
    for review in actual_pages:
        if review["candidate_pdf_page"] not in page_expected_by_id:
            continue
        baseline = page_expected_by_id[review["candidate_pdf_page"]]
        for field in ("region_ids", "line_ids", "first_record_id", "last_record_id", "first_line_id", "last_line_id", "record_count", "line_count", "continuation_line_ids", "exception_ids"):
            if review.get(field) != baseline.get(field):
                errors.append(f"QA page {review['candidate_pdf_page']} {field} differs from the exact extraction inventory")
        if review.get("continuation_handling_reviewed") is not True:
            errors.append(f"QA page {review['candidate_pdf_page']} has not reviewed continuation handling")
        if review.get("reproduces_candidate_not_editorial_improvement") is not True:
            errors.append(f"QA page {review['candidate_pdf_page']} lacks the fidelity-not-improvement attestation")

    _, _, layout_lines = flatten_layout(layout)
    layout_texts = {str(line.get("original_displayed_form")) for line in layout_lines}
    candidate_texts = {str(record.get("original_displayed_form")) for record in candidate.get("records", [])}
    top_corrections = qa["corrections"]
    page_corrections = [item for page in actual_pages for item in page["corrections"]]
    correction_ids = [item.get("correction_id") for item in top_corrections]
    if _duplicate_values(correction_ids):
        errors.append("QA corrections contains duplicate correction_id values")
    if set(correction_ids) != {item.get("correction_id") for item in page_corrections}:
        errors.append("Per-page corrections do not exactly match the top-level correction ledger")
    for correction in top_corrections:
        errors.extend(_validate_correction(correction, layout_texts, candidate_texts))

    dispositions = qa["exception_dispositions"]
    disposition_ids = [item["exception_id"] for item in dispositions]
    if _duplicate_values(disposition_ids) or set(disposition_ids) != set(expected["exception_ids"]):
        errors.append("QA exception dispositions are not the exact exception set")
    expected_hashes = {
        "normalized_candidate_file_sha256": sha256_file(paths["candidate_index"]),
        "item_inventory_file_sha256": sha256_file(paths["item_inventory"]),
        "layout_extraction_file_sha256": sha256_file(paths["layout_extraction"]),
    }
    for field, digest in expected_hashes.items():
        if qa.get(field) != digest:
            errors.append(f"QA {field} does not match the reviewed bytes")
    completion = qa["completion"]
    for field in ("all_denominators_complete", "all_exceptions_dispositioned", "candidate_reproduction_confirmed", "complete"):
        if completion.get(field) is not True:
            errors.append(f"QA completion.{field} must be true")
    if completion.get("editorial_quality_judgments_performed") is not False:
        errors.append("Candidate preparation QA must not perform editorial quality judgments")
    if candidate.get("normalization", {}).get("editorial_corrections_applied") is not False or candidate.get("normalization", {}).get("benchmark_content_used") is not False:
        errors.append("Normalization must preserve delivered content and remain benchmark-content blind")

    report_hashes = report.get("private_artifact_hashes", {})
    for key in ("layout_extraction", "candidate_index", "item_inventory", "normalization_exceptions"):
        if report_hashes.get(key) != sha256_file(paths[key]):
            errors.append(f"Normalization report hash for {key} does not match")
    expected_report_counts = {
        **candidate["normalization"],
        "candidate_pdf_pages": len(layout.get("pages", [])),
        "reading_order_regions": sum(len(page.get("regions", [])) for page in layout.get("pages", [])),
        "extracted_lines": sum(len(region.get("lines", [])) for page in layout.get("pages", []) for region in page.get("regions", [])),
        "normalization_exceptions": len(exception_items),
    }
    if report.get("counts") != expected_report_counts:
        errors.append("Normalization report counts do not recompute exactly")
    if profile != build_layout_profile(layout):
        errors.append("Layout profile is not the exact aggregate projection of the extraction")
    errors.extend(_check_prelock_separation(documents))
    require(not errors, "private_preparation_invalid", "Candidate preparation failed the private full-QA gate.", errors)
    return {
        "identities": identities,
        "paths": paths,
        "documents": documents,
        "hashes": {key: sha256_file(path) for key, path in paths.items()},
        "candidate_sha256": actual_candidate_sha,
        "counts": candidate.get("normalization", {}),
    }


def command_validate_private(args: argparse.Namespace) -> None:
    result = validate_private_preparation(
        Path(args.preparation_dir), args.candidate_id, Path(args.candidate_file), Path(args.state),
        Path(args.page_map), Path(args.chunk_manifest), Path(args.policy),
        Path(args.qa) if args.qa else None, args.source_edition,
    )
    emit({
        "command": "validate-private-preparation",
        "ok": True,
        "candidate_id": args.candidate_id,
        "candidate_sha256": result["candidate_sha256"],
        "artifact_hashes": result["hashes"],
        "qa_gate": "complete_exact_set",
        "candidate_quality_judgments_performed": False,
        "warnings": [],
    })


def command_register(args: argparse.Namespace) -> None:
    """Register a validated local preparation directly; no PR or evidence ceremony."""
    state_path = Path(args.state).resolve()
    result = validate_private_preparation(
        Path(args.preparation_dir), args.candidate_id, Path(args.candidate_file), state_path,
        Path(args.page_map), Path(args.chunk_manifest), Path(args.policy),
        Path(args.qa) if args.qa else None, args.source_edition,
    )
    benchmark_path = Path(args.benchmark).resolve()
    benchmark = load_json(benchmark_path, "Final benchmark")
    errors = final_benchmark_structure_errors(benchmark)
    require(not errors, "benchmark_invalid", "Final benchmark is invalid.", errors)
    with evaluation_mutation_lock(state_path):
        state = load_json(state_path, "Canonical evaluation state")
        errors, _ = validate_state(state, state_path=state_path)
        require(not errors, "canonical_state_invalid", "Canonical evaluation state failed validation.", errors)
        require(state.get("stages", {}).get("benchmark_freeze", {}).get("status") == "completed", "benchmark_stage_incomplete", "Freeze the benchmark before registering a candidate.")
        require(benchmark.get("evaluation_id") == state.get("evaluation_id"), "benchmark_identity_mismatch", "Benchmark and evaluation IDs differ.")
        require(benchmark.get("source_sha256") == state.get("source", {}).get("sha256"), "benchmark_identity_mismatch", "Benchmark and source identities differ.")
        require(benchmark.get("candidate_blindness") == "preserved", "candidate_blindness", "The benchmark must remain candidate-blind.")
        root = state_path.parent
        artifact_types = {
            "candidate_ref": "candidate_ref",
            "layout_profile": "candidate_layout_profile",
            "layout_extraction": "candidate_layout_extraction",
            "candidate_index": "candidate_index",
            "item_inventory": "item_inventory",
            "normalization_exceptions": "candidate_normalization_exceptions",
            "normalization_report": "candidate_normalization_report",
            "normalization_qa": "candidate_normalization_qa",
        }
        stamp = now()
        new_records = []
        for name, path in result["paths"].items():
            relative = portable_relative_path(path, root)
            digest = sha256_file(path)
            document = result["documents"].get(name, {})
            record = {
                "artifact_id": state_artifact_id(relative, digest),
                "stage": "candidate_normalization",
                "artifact_type": artifact_types[name],
                "path": relative,
                "sha256": digest,
                "media_type": "application/json",
                "visibility": "private",
                "retention": "required",
                "frozen": True,
                "recorded_at": stamp,
                **({"schema_version": document["schema_version"]} if isinstance(document, dict) and isinstance(document.get("schema_version"), str) else {}),
            }
            new_records.append(record)
        paths = {record["path"] for record in new_records}
        state["artifacts"] = [record for record in state.get("artifacts", []) if record.get("path") not in paths]
        state["artifacts"].extend(new_records)
        state["artifacts"].sort(key=lambda record: record["path"])
        state["candidate"] = {
            "candidate_id": args.candidate_id,
            "sha256": result["candidate_sha256"],
            "schema_version": "candidate-index-v2",
            "normalized_path": next(record["path"] for record in new_records if record["artifact_type"] == "candidate_index"),
            "item_inventory_path": next(record["path"] for record in new_records if record["artifact_type"] == "item_inventory"),
            "benchmark_path": portable_relative_path(benchmark_path, root),
            "benchmark_sha256": benchmark.get("benchmark_sha256"),
        }
        state["stages"]["candidate_normalization"] = {"status": "completed", "updated_at": stamp, "notes": ["Validated and registered directly from local preparation outputs."]}
        state["updated_at"] = stamp
        validation_errors, warnings = validate_state(state, state_path=state_path)
        require(not validation_errors, "canonical_state_invalid", "Candidate registration would leave invalid state.", validation_errors)
        save_state(state_path, state)
    action = next_stage(state)
    emit({
        "command": "register-candidate-preparation", "ok": True,
        "evaluation_id": state["evaluation_id"], "candidate_id": args.candidate_id,
        "artifacts_written": [record["path"] for record in new_records],
        "next_actions": [] if action is None else [action], "warnings": warnings,
    })


def _add_frozen_inputs(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--state", required=True)
    parser.add_argument("--page-map", required=True)
    parser.add_argument("--chunk-manifest", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--source-edition")


def _add_private_inputs(parser: argparse.ArgumentParser, include_candidate_file: bool = True) -> None:
    parser.add_argument("--candidate-id", required=True)
    if include_candidate_file:
        parser.add_argument("--candidate-file", required=True)
    parser.add_argument("--preparation-dir", required=True)
    parser.add_argument("--qa")
    _add_frozen_inputs(parser)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    extract = subparsers.add_parser("extract", help="Extract candidate PDF layout without using benchmark content")
    extract.add_argument("--candidate-id", required=True)
    extract.add_argument("--candidate-file", required=True)
    extract.add_argument("--source-sha256", required=True)
    extract.add_argument("--adapter", choices=["auto", "generic-pdf-layout", "indexerlabs-two-column"], default="auto")
    extract.add_argument("--geometry-input", help="Deterministic synthetic geometry for tests")
    extract.add_argument("--output", required=True)
    extract.add_argument("--force", action="store_true")
    extract.set_defaults(func=command_extract)

    normalize = subparsers.add_parser("normalize", help="Normalize extracted layout into current candidate v2 artifacts")
    normalize.add_argument("--candidate-id", required=True)
    normalize.add_argument("--candidate-file", required=True)
    _add_frozen_inputs(normalize)
    normalize.add_argument("--layout", required=True)
    normalize.add_argument("--output-dir", required=True)
    normalize.add_argument("--file-origin", choices=["delivered_pdf", "reconstructed_pdf", "transcription"], default="delivered_pdf")
    normalize.add_argument("--provenance")
    normalize.add_argument("--force", action="store_true")
    normalize.set_defaults(func=command_normalize)

    validate_private = subparsers.add_parser("validate-private", help="Enforce full exact-set normalization QA")
    _add_private_inputs(validate_private)
    validate_private.set_defaults(func=command_validate_private)

    register = subparsers.add_parser("register", help="Register validated local preparation outputs in canonical state")
    _add_private_inputs(register)
    register.add_argument("--benchmark", required=True)
    register.set_defaults(func=command_register)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except PreparationError as exc:
        payload: dict[str, Any] = {"ok": False, "error": {"code": exc.code, "message": exc.message}}
        if exc.details is not None:
            payload["error"]["details"] = exc.details
        emit(payload, 1)
    except (OSError, ValueError) as exc:
        emit({"ok": False, "error": {"code": "candidate_preparation_failure", "message": str(exc)}}, 1)


if __name__ == "__main__":
    main()
