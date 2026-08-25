#!/usr/bin/env python3
"""Prepare candidate indexes mechanically, validate privacy gates, and integrate them safely."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import stat
import tempfile
import unicodedata
import zipfile
from copy import deepcopy
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from candidate_layout_adapters import extract_candidate_layout, validate_layout_contract
from benchmark_review_cli import final_benchmark_structure_errors
from item_grade_cli import build_inventory
from state_cli import STAGES, next_stage, validate_state


STATE_V4 = "subject-index-evaluation-state-v4"
SUPPORTED_STATES = {STATE_V4}
PUBLIC_PATHS = {
    "candidate/candidate-ref.json",
    "candidate/layout-profile.json",
    "validation/candidate-preparation-report.json",
}
BOOTSTRAP_PATHS = {".gitignore", "README.md"}
PROVENANCE_FIELDS = (
    "candidate_bytes",
    "internal_pdf_completeness",
    "structural_continuity",
    "source_edition_compatibility",
    "locator_page_map_compatibility",
    "authoritative_copy_fidelity",
)
PROVENANCE_STATUSES = {
    "verified",
    "not_independently_verified",
    "incomplete",
    "conflicting_evidence",
    "not_applicable",
}
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
PRIVATE_ARCHIVE_PATHS = {
    "candidate_ref": "candidates/{candidate_id}/candidate-ref.json",
    "layout_profile": "candidates/{candidate_id}/layout-profile.json",
    "layout_extraction": "candidates/{candidate_id}/candidate-layout-extraction.v1.json",
    "candidate_index": "candidates/{candidate_id}/candidate-index.draft.v2.json",
    "item_inventory": "candidates/{candidate_id}/item-inventory.draft.v2.json",
    "normalization_exceptions": "candidates/{candidate_id}/normalization-exceptions.v1.json",
    "normalization_report": "validation/candidate-normalization-report.{candidate_id}.v1.json",
    "normalization_qa": "validation/candidate-normalization-qa.{candidate_id}.v1.json",
}
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
MAX_RECOVERY_MEMBER_BYTES = 128 * 1024 * 1024
MAX_RECOVERY_TOTAL_BYTES = 512 * 1024 * 1024
MAX_RECOVERY_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_RECOVERY_COMPRESSION_RATIO = 200


class PreparationError(ValueError):
    def __init__(self, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def require_timestamp(value: Any, field: str) -> datetime:
    require(isinstance(value, str) and value, "invalid_timestamp", f"{field} must be an ISO-8601 timestamp.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PreparationError("invalid_timestamp", f"{field} must be an ISO-8601 timestamp.") from exc
    require(parsed.tzinfo is not None, "invalid_timestamp", f"{field} must include a timezone.")
    return parsed.astimezone(timezone.utc)


def require(condition: bool, code: str, message: str, details: Any = None) -> None:
    if not condition:
        raise PreparationError(code, message, details)


def emit(payload: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    raise SystemExit(exit_code)


@contextmanager
def evaluation_integration_lock(state_path: Path):
    """Serialize every cooperative mutation for one canonical evaluation root."""
    lock_path = state_path.resolve().parent / ".candidate-preparation-integration.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise PreparationError("integration_lock_busy", "Another candidate integration owns the canonical evaluation lock.") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


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


def git_blob_sha(path: Path, advertised_sha: str) -> str:
    """Recompute the Git blob object identity for the exact local bytes."""
    return git_blob_sha_bytes(path.read_bytes(), advertised_sha)


def git_blob_sha_bytes(payload: bytes, advertised_sha: str) -> str:
    """Recompute a Git blob identity from an immutable byte snapshot."""
    framed = f"blob {len(payload)}\0".encode("ascii") + payload
    if len(advertised_sha) == 40:
        return hashlib.sha1(framed).hexdigest()  # GitHub's current object format.
    if len(advertised_sha) == 64:
        return hashlib.sha256(framed).hexdigest()
    return ""


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


def default_worker_branch(candidate_id: str) -> str:
    return f"candidate-preparation/{normalize_candidate_id(candidate_id)}"


def require_sha256(value: Any, field: str) -> str:
    require(isinstance(value, str) and bool(re.fullmatch(r"[a-f0-9]{64}", value)), "invalid_sha256", f"{field} must be a lowercase SHA-256 digest.")
    return value


def require_commit(value: Any, field: str) -> str:
    require(isinstance(value, str) and bool(re.fullmatch(r"[a-fA-F0-9]{40}", value)), "invalid_commit", f"{field} must be a 40-character Git commit SHA.")
    return value.lower()


def require_github_project(value: Any, field: str) -> str:
    require(
        isinstance(value, str)
        and bool(re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,98})/[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,98})", value))
        and not any(part in {".", ".."} for part in value.split("/")),
        "invalid_github_project",
        f"{field} must be a GitHub owner/repository identifier.",
    )
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
    normalized = re.sub(r"[â€â€‘â€’â€“â€”âˆ’]", "-", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    if re.fullmatch(r"[0-9]+", normalized):
        normalized = str(int(normalized))
    return normalized.casefold()


def validate_self_hash(value: dict[str, Any], field: str, label: str) -> None:
    recorded = require_sha256(value.get(field), f"{label}.{field}")
    require(recorded == canonical_hash(value, field), "canonical_hash_mismatch", f"{label} canonical hash does not recompute.")


def validate_provenance(provenance: dict[str, Any], file_origin: str) -> list[str]:
    errors: list[str] = []
    for field in PROVENANCE_FIELDS:
        record = provenance.get(field)
        if not isinstance(record, dict):
            errors.append(f"provenance.{field} must be an object")
            continue
        if record.get("status") not in PROVENANCE_STATUSES:
            errors.append(f"provenance.{field}.status is invalid")
        if not isinstance(record.get("rationale"), str) or not record.get("rationale"):
            errors.append(f"provenance.{field}.rationale must be non-empty")
    if file_origin in {"reconstructed_pdf", "transcription"} and provenance.get("authoritative_copy_fidelity", {}).get("claimed_original_publisher_pdf"):
        errors.append("A reconstructed PDF or transcription cannot claim to be an original publisher PDF")
    return errors


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
    require(state.get("schema_version") in SUPPORTED_STATES, "unsupported_state", "Candidate preparation requires subject-index-evaluation-state-v4.")
    page_map = documents.get("page_map") or load_json(page_map_path, "Page map")
    chunks = documents.get("chunk_manifest") or load_json(chunk_manifest_path, "Chunk manifest")
    policy = documents.get("policy") or load_json(policy_path, "Evaluation policy")
    require(page_map.get("schema_version") == "page-map-v1", "invalid_page_map", "Expected page-map-v1.")
    require(chunks.get("schema_version") == "chunk-manifest-v1", "invalid_chunk_manifest", "Expected chunk-manifest-v1.")
    require(policy.get("schema_version") == "subject-index-evaluation-policy-v2", "invalid_policy", "Expected subject-index-evaluation-policy-v2.")
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
    rubric_version = policy.get("rubric", {}).get("version")
    audit_mode = policy.get("audit_design", {}).get("mode")
    require(configuration.get("policy_profile") in {None, policy_profile}, "policy_identity_mismatch", "State and policy profile identities differ.")
    require(configuration.get("rubric_version") in {None, rubric_version}, "rubric_identity_mismatch", "State and policy rubric identities differ.")
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
    for separator in re.finditer(r"(?:â€“|â€”|â€‘|â€’|âˆ’|--|-)", first):
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
            r"(?:[0-9]+|[ivxlcdm]+)(?:\s*[â€“â€”â€‘â€’âˆ’-]\s*(?:[0-9]+|[ivxlcdm]+))?",
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
    for separator in re.finditer(r"(?:â€“|â€”|â€‘|â€’|âˆ’|--|-)", token):
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
    layout_errors = validate_layout_contract(layout)
    require(not layout_errors, "invalid_layout_extraction", "Layout extraction failed the common adapter contract.", layout_errors)
    candidate_id = str(layout.get("candidate_id", ""))
    candidate_sha = require_sha256(layout.get("candidate_sha256"), "layout.candidate_sha256")
    require(candidate_id, "candidate_identity", "Layout extraction requires candidate_id.")
    require(layout.get("schema_version") == "candidate-layout-extraction-v1", "layout_schema", "Expected candidate-layout-extraction-v1.")
    require(page_map.get("schema_version") == "page-map-v1", "page_map_schema", "Expected page-map-v1.")
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
        "benchmark_lock_status": "pending_final_benchmark",
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
    errors = validate_provenance(provenance, file_origin)
    require(not errors, "invalid_provenance", "Candidate provenance is invalid.", errors)
    candidate_sha = sha256_file(candidate_path)
    require(candidate_sha == layout.get("candidate_sha256"), "candidate_hash_mismatch", "Candidate bytes do not match the layout extraction hash.")
    require(provenance["candidate_bytes"]["status"] == "verified", "candidate_bytes_unverified", "A worker receipt requires verified candidate bytes.")
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
    save_json(paths["normalization_qa"], qa)
    emit({
        "command": "normalize-candidate-layout",
        "ok": True,
        "candidate_id": args.candidate_id,
        "candidate_sha256": candidate.get("candidate_sha256"),
        "benchmark_lock_status": "pending_final_benchmark",
        "canonical_state_mutated": False,
        "artifacts_written": [
            {"artifact": key, "path": str(path), "sha256": sha256_file(path)}
            for key, path in paths.items()
        ],
        "next_actions": ["perform_full_normalization_qa", "validate-private-preparation"],
        "warnings": ["The QA file is a template and cannot authorize integration until every denominator is reviewed."],
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
    if not isinstance(correction_id, str) or not correction_id:
        errors.append("Every correction requires correction_id")
    before = correction.get("before")
    after = correction.get("after")
    if not isinstance(before, str) or before not in layout_texts:
        errors.append(f"Correction {correction_id} before text is not present in the delivered layout")
    if not isinstance(after, str) or after not in candidate_texts:
        errors.append(f"Correction {correction_id} after text is not present in the normalized candidate")
    if correction.get("reproduction_only") is not True:
        errors.append(f"Correction {correction_id} must attest reproduction_only=true")
    if correction.get("editorial_improvement") is not False:
        errors.append(f"Correction {correction_id} must attest editorial_improvement=false")
    if not isinstance(correction.get("reason"), str) or not correction.get("reason"):
        errors.append(f"Correction {correction_id} requires a reason")
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

    expected_schemas = {
        "candidate_ref": "candidate-ref-v1",
        "layout_profile": "candidate-layout-profile-v1",
        "layout_extraction": "candidate-layout-extraction-v1",
        "candidate_index": "candidate-index-v2",
        "item_inventory": "subject-index-item-inventory-v2",
        "normalization_exceptions": "candidate-normalization-exceptions-v1",
        "normalization_report": "candidate-normalization-report-v1",
        "normalization_qa": "candidate-normalization-qa-v1",
    }
    for key, schema in expected_schemas.items():
        if documents[key].get("schema_version") != schema:
            errors.append(f"{key} must use {schema}")
    errors.extend(validate_layout_contract(layout))
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
    if candidate_ref.get("file_origin") not in {"delivered_pdf", "reconstructed_pdf", "transcription"}:
        errors.append("Candidate file_origin is invalid")
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
    errors.extend(validate_provenance(candidate_ref.get("provenance", {}), str(candidate_ref.get("file_origin", ""))))

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
        if any(not isinstance(value, str) or not value for value in values):
            errors.append(f"Every {label} must be a non-empty string")
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
    reviewed = qa.get("reviewed") if isinstance(qa.get("reviewed"), dict) else {}
    for key, values in expected.items():
        actual = reviewed.get(key)
        if not isinstance(actual, list):
            errors.append(f"QA reviewed.{key} must be an array")
            continue
        try:
            duplicates = _duplicate_values(actual)
            actual_set = set(actual)
        except TypeError:
            errors.append(f"QA reviewed.{key} contains a non-scalar value")
            continue
        if duplicates:
            errors.append(f"QA reviewed.{key} contains duplicates")
        if actual_set != set(values):
            errors.append(f"QA reviewed.{key} is not the exact expected set")

    expected_pages = expected_page_reviews(layout, candidate, exceptions)
    actual_pages = qa.get("page_reviews") if isinstance(qa.get("page_reviews"), list) else []
    if _duplicate_values([item.get("candidate_pdf_page") for item in actual_pages if isinstance(item, dict)]):
        errors.append("QA page_reviews contains duplicate pages")
    if {item.get("candidate_pdf_page") for item in actual_pages if isinstance(item, dict)} != {item["candidate_pdf_page"] for item in expected_pages}:
        errors.append("QA page_reviews does not cover every candidate PDF page exactly once")
    page_expected_by_id = {item["candidate_pdf_page"]: item for item in expected_pages}
    for review in actual_pages:
        if not isinstance(review, dict) or review.get("candidate_pdf_page") not in page_expected_by_id:
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
    top_corrections = qa.get("corrections") if isinstance(qa.get("corrections"), list) else []
    page_corrections = [item for page in actual_pages if isinstance(page, dict) for item in page.get("corrections", []) if isinstance(item, dict)]
    correction_ids = [item.get("correction_id") for item in top_corrections]
    if _duplicate_values(correction_ids):
        errors.append("QA corrections contains duplicate correction_id values")
    if set(correction_ids) != {item.get("correction_id") for item in page_corrections}:
        errors.append("Per-page corrections do not exactly match the top-level correction ledger")
    for correction in top_corrections:
        errors.extend(_validate_correction(correction, layout_texts, candidate_texts))

    dispositions = qa.get("exception_dispositions") if isinstance(qa.get("exception_dispositions"), list) else []
    disposition_ids = [item.get("exception_id") for item in dispositions if isinstance(item, dict)]
    if _duplicate_values(disposition_ids) or set(disposition_ids) != set(expected["exception_ids"]):
        errors.append("QA exception dispositions are not the exact exception set")
    for disposition in dispositions:
        if not isinstance(disposition, dict) or disposition.get("disposition") not in {"confirmed_unresolved", "confirmed_malformed", "confirmed_faithful", "resolved_by_reproduction_correction"}:
            errors.append("Every QA exception requires an allowed explicit disposition")

    expected_hashes = {
        "normalized_candidate_file_sha256": sha256_file(paths["candidate_index"]),
        "item_inventory_file_sha256": sha256_file(paths["item_inventory"]),
        "layout_extraction_file_sha256": sha256_file(paths["layout_extraction"]),
    }
    for field, digest in expected_hashes.items():
        if qa.get(field) != digest:
            errors.append(f"QA {field} does not match the reviewed bytes")
    completion = qa.get("completion") if isinstance(qa.get("completion"), dict) else {}
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
        "benchmark_lock_status": "pending_final_benchmark",
        "candidate_quality_judgments_performed": False,
        "warnings": [],
    })


PUBLIC_FORBIDDEN_KEYS = {
    "records", "headings", "heading_path", "locators", "locator_displays", "locator_assignments",
    "cross_references", "pages", "regions", "lines", "bbox", "bboxes", "coordinates", "raw",
    "raw_text", "original_displayed_form", "displayed_line_text", "private_evidence", "item_inventory",
    "normalization_qa", "checkpoint", "local_path", "library_file_id", "candidate_filename",
}
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat|sk_live|sk_test)_[A-Za-z0-9_\-]{12,}\b"),
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{12,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{12,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}\b", re.I),
    re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s/:@]+:[^\s/@]+@", re.I),
    re.compile(r"\bfile://", re.I),
    re.compile(r"(?:^|[\\/])\.\.(?:[\\/]|$)"),
    re.compile(r"\blibfile_[a-f0-9]{8,}\b", re.I),
    re.compile(r"(?:^|[\s\"'])/(?:root|home|workspace|tmp|Users|var|etc|opt|srv|mnt|private|Volumes)/[^\s\"']*", re.I),
    re.compile(r"(?:^|[\s\"'])[A-Za-z]:[\\/][^\s\"']*"),
)


def public_projection_documents(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    documents = result["documents"]
    candidate_ref = documents["candidate_ref"]
    layout_profile = documents["layout_profile"]
    report = documents["normalization_report"]
    qa = documents["normalization_qa"]
    candidate = documents["candidate_index"]
    provenance = {field: {"status": candidate_ref["provenance"][field]["status"]} for field in PROVENANCE_FIELDS}
    adapter = layout_profile["adapter"]
    private_layout_summary = layout_profile["layout"]
    column_counts = private_layout_summary.get("index_columns_per_page", [])
    column_histogram = {
        str(value): sum(item == value for item in column_counts)
        for value in sorted(set(column_counts))
        if isinstance(value, int)
    }
    public_adapter = {
        "requested_id": adapter.get("requested_id"),
        "id": adapter.get("id"),
        "version": adapter.get("version"),
        "selection_reason": adapter.get("selection_reason"),
    }
    public_ref = {
        "schema_version": "candidate-preparation-public-ref-v1",
        "candidate_id": candidate_ref["candidate_id"],
        "candidate_sha256": candidate_ref["candidate_sha256"],
        "file_origin": candidate_ref["file_origin"],
        "source_identity": candidate_ref["source"],
        "page_map_sha256": candidate_ref["page_map_sha256"],
        "chunk_manifest_sha256": candidate_ref["chunk_manifest_sha256"],
        "policy_identity": candidate_ref["policy"],
        "provenance": provenance,
        "benchmark_lock_status": "pending_final_benchmark",
    }
    public_profile = {
        "schema_version": "candidate-preparation-public-layout-profile-v1",
        "candidate_id": layout_profile["candidate_id"],
        "candidate_sha256": layout_profile["candidate_sha256"],
        "adapter": public_adapter,
        "pdf_summary": {
            "page_count": layout_profile["pdf"].get("page_count"),
            "has_embedded_text": layout_profile["pdf"].get("has_embedded_text"),
        },
        "layout_summary": {
            "reading_order": private_layout_summary.get("reading_order"),
            "page_count": private_layout_summary.get("page_count"),
            "region_count": private_layout_summary.get("region_count"),
            "line_count": private_layout_summary.get("line_count"),
            "header_footer_lines": private_layout_summary.get("header_footer_lines"),
            "continuation_lines": private_layout_summary.get("continuation_lines"),
            "index_column_count_histogram": column_histogram,
        },
        "limitation_count": len(layout_profile.get("limitations", [])),
        "content_included": False,
    }
    public_report = {
        "schema_version": "candidate-preparation-public-report-v1",
        "candidate_id": report["candidate_id"],
        "candidate_sha256": report["candidate_sha256"],
        "source_sha256": report["source_sha256"],
        "page_map_sha256": report["page_map_sha256"],
        "adapter_identity": public_adapter,
        "aggregate_counts": report["counts"],
        "exception_count": len(documents["normalization_exceptions"].get("exceptions", [])),
        "qa": {
            "mode": qa.get("review_mode"),
            "exact_set_gate_complete": qa.get("completion", {}).get("complete") is True,
            "candidate_reproduction_confirmed": qa.get("completion", {}).get("candidate_reproduction_confirmed") is True,
            "editorial_quality_judgments_performed": False,
        },
        "normalization": {
            "editorial_corrections_applied": candidate.get("normalization", {}).get("editorial_corrections_applied"),
            "benchmark_content_used": candidate.get("normalization", {}).get("benchmark_content_used"),
        },
        "benchmark_lock_status": "pending_final_benchmark",
        "private_artifacts_published": False,
        "status": "ready_for_private_receipt",
    }
    return {
        "candidate/candidate-ref.json": public_ref,
        "candidate/layout-profile.json": public_profile,
        "validation/candidate-preparation-report.json": public_report,
    }


def scan_public_value(value: Any, path: str = "$") -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = key.casefold().replace("-", "_")
            if normalized in PUBLIC_FORBIDDEN_KEYS:
                errors.append(f"{path}.{key} is prohibited in the public projection")
            errors.extend(scan_public_value(item, f"{path}.{key}"))
    elif isinstance(value, list):
        errors.append(f"{path} contains an array; the strict aggregate public projection permits no arrays")
    elif isinstance(value, str):
        if len(value) > 2000:
            errors.append(f"{path} exceeds the public string limit")
        for pattern in SECRET_PATTERNS:
            if pattern.search(value):
                errors.append(f"{path} contains a path, Library identifier, or secret-like value")
                break
    return errors


def validate_public_documents(documents: dict[str, dict[str, Any]]) -> list[str]:
    errors: list[str] = []

    def bounded_string(value: Any, label: str, maximum: int = 256, pattern: str | None = None) -> bool:
        valid = isinstance(value, str) and 0 < len(value) <= maximum
        if valid and pattern is not None:
            valid = bool(re.fullmatch(pattern, value))
        if not valid:
            errors.append(f"{label} must be a bounded scalar string")
        return valid

    def sha256_value(value: Any, label: str) -> None:
        if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
            errors.append(f"{label} must be a lowercase SHA-256")

    def nonnegative_integer(value: Any, label: str) -> None:
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            errors.append(f"{label} must be a nonnegative integer")

    def adapter_value(value: Any, label: str) -> None:
        record = exact_keys(value, {"requested_id", "id", "version", "selection_reason"}, label)
        bounded_string(record.get("requested_id"), f"{label}.requested_id", 64, r"[a-z0-9][a-z0-9._-]*")
        bounded_string(record.get("id"), f"{label}.id", 64, r"[a-z0-9][a-z0-9._-]*")
        bounded_string(record.get("version"), f"{label}.version", 32, r"[A-Za-z0-9][A-Za-z0-9._+-]*")
        bounded_string(record.get("selection_reason"), f"{label}.selection_reason", 96, r"[a-z0-9][a-z0-9._-]*")

    if set(documents) != PUBLIC_PATHS:
        errors.append(f"Public changed paths must equal the exact allowlist: {sorted(PUBLIC_PATHS)}")
    schemas = {
        "candidate/candidate-ref.json": "candidate-preparation-public-ref-v1",
        "candidate/layout-profile.json": "candidate-preparation-public-layout-profile-v1",
        "validation/candidate-preparation-report.json": "candidate-preparation-public-report-v1",
    }
    candidate_id: str | None = None
    candidate_sha: str | None = None
    exact_top_level = {
        "candidate/candidate-ref.json": {
            "schema_version", "candidate_id", "candidate_sha256", "file_origin", "source_identity",
            "page_map_sha256", "chunk_manifest_sha256", "policy_identity", "provenance", "benchmark_lock_status",
        },
        "candidate/layout-profile.json": {
            "schema_version", "candidate_id", "candidate_sha256", "adapter", "pdf_summary",
            "layout_summary", "limitation_count", "content_included",
        },
        "validation/candidate-preparation-report.json": {
            "schema_version", "candidate_id", "candidate_sha256", "source_sha256", "page_map_sha256",
            "adapter_identity", "aggregate_counts", "exception_count", "qa", "normalization",
            "benchmark_lock_status", "private_artifacts_published", "status",
        },
    }

    def exact_keys(value: Any, expected: set[str], label: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            errors.append(f"{label} must be an object")
            return {}
        if set(value) != expected:
            errors.append(f"{label} has missing or unexpected properties")
        return value

    for path, document in documents.items():
        if not isinstance(document, dict):
            errors.append(f"{path} must contain a JSON object")
            continue
        if document.get("schema_version") != schemas.get(path):
            errors.append(f"{path} has the wrong public projection schema")
        if set(document) != exact_top_level.get(path, set()):
            errors.append(f"{path} has missing or unexpected top-level properties")
        if candidate_id is None:
            candidate_id = document.get("candidate_id")
            candidate_sha = document.get("candidate_sha256")
        elif document.get("candidate_id") != candidate_id or document.get("candidate_sha256") != candidate_sha:
            errors.append("Public projection candidate identities differ")
        errors.extend(f"{path}:{item}" for item in scan_public_value(document))
        if document.get("benchmark_lock_status") not in {None, "pending_final_benchmark"}:
            errors.append(f"{path} claims a benchmark lock before integration")
    public_ref = documents.get("candidate/candidate-ref.json", {})
    bounded_string(public_ref.get("candidate_id"), "Public candidate_id", 128, r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
    sha256_value(public_ref.get("candidate_sha256"), "Public candidate_sha256")
    if public_ref.get("file_origin") not in {"delivered_pdf", "reconstructed_pdf", "transcription"}:
        errors.append("Public file_origin is invalid")
    source_identity = exact_keys(public_ref.get("source_identity"), {"sha256", "edition"}, "Public source_identity")
    sha256_value(source_identity.get("sha256"), "Public source_identity.sha256")
    bounded_string(source_identity.get("edition"), "Public source_identity.edition", 256)
    sha256_value(public_ref.get("page_map_sha256"), "Public page_map_sha256")
    sha256_value(public_ref.get("chunk_manifest_sha256"), "Public chunk_manifest_sha256")
    policy_identity = exact_keys(public_ref.get("policy_identity"), {"profile", "sha256", "rubric_version", "audit_mode"}, "Public policy_identity")
    bounded_string(policy_identity.get("profile"), "Public policy_identity.profile", 96, r"[A-Za-z0-9][A-Za-z0-9._-]*")
    sha256_value(policy_identity.get("sha256"), "Public policy_identity.sha256")
    if policy_identity.get("rubric_version") != "subject-index-rubric-v4":
        errors.append("Public policy_identity.rubric_version must use the current rubric")
    if policy_identity.get("audit_mode") not in {"full", "pilot"}:
        errors.append("Public policy_identity.audit_mode is invalid")
    if public_ref.get("benchmark_lock_status") != "pending_final_benchmark":
        errors.append("Public candidate reference must retain a pending benchmark lock")
    provenance = public_ref.get("provenance")
    if not isinstance(provenance, dict) or set(provenance) != set(PROVENANCE_FIELDS):
        errors.append("Public candidate provenance must contain exactly the six independent status fields")
    else:
        for field, record in provenance.items():
            if not isinstance(record, dict) or set(record) != {"status"} or record.get("status") not in PROVENANCE_STATUSES:
                errors.append(f"Public provenance {field} must contain only a valid status")
    profile = documents.get("candidate/layout-profile.json", {})
    bounded_string(profile.get("candidate_id"), "Public layout candidate_id", 128)
    sha256_value(profile.get("candidate_sha256"), "Public layout candidate_sha256")
    adapter_value(profile.get("adapter"), "Public layout adapter")
    pdf_summary = exact_keys(profile.get("pdf_summary"), {"page_count", "has_embedded_text"}, "Public PDF summary")
    nonnegative_integer(pdf_summary.get("page_count"), "Public PDF page_count")
    if not isinstance(pdf_summary.get("has_embedded_text"), bool):
        errors.append("Public PDF has_embedded_text must be boolean")
    layout_summary = exact_keys(
        profile.get("layout_summary"),
        {"reading_order", "page_count", "region_count", "line_count", "header_footer_lines", "continuation_lines", "index_column_count_histogram"},
        "Public layout summary",
    )
    histogram = layout_summary.get("index_column_count_histogram")
    if not isinstance(histogram, dict) or any(not re.fullmatch(r"[0-9]+", str(key)) or not isinstance(value, int) or isinstance(value, bool) or value < 0 for key, value in (histogram.items() if isinstance(histogram, dict) else [])):
        errors.append("Public index-column histogram must contain only nonnegative integer aggregate counts")
    if layout_summary.get("reading_order") != "page_then_region_then_line":
        errors.append("Public layout reading_order is invalid")
    for field in ("page_count", "region_count", "line_count", "header_footer_lines", "continuation_lines"):
        nonnegative_integer(layout_summary.get(field), f"Public layout_summary.{field}")
    nonnegative_integer(profile.get("limitation_count"), "Public limitation_count")
    if profile.get("content_included") is not False:
        errors.append("Public layout profile must attest content_included=false")
    report = documents.get("validation/candidate-preparation-report.json", {})
    bounded_string(report.get("candidate_id"), "Public report candidate_id", 128)
    for field in ("candidate_sha256", "source_sha256", "page_map_sha256"):
        sha256_value(report.get(field), f"Public report {field}")
    adapter_value(report.get("adapter_identity"), "Public report adapter")
    aggregate_counts = exact_keys(
        report.get("aggregate_counts"),
        {
            "engine", "engine_version", "record_count", "main_heading_count", "subheading_count",
            "complete_heading_path_count", "displayed_locator_count", "expanded_locator_assignment_count",
            "cross_reference_count", "unresolved_locator_count", "editorial_corrections_applied",
            "benchmark_content_used", "candidate_pdf_pages", "reading_order_regions", "extracted_lines",
            "normalization_exceptions",
        },
        "Public aggregate_counts",
    )
    if aggregate_counts.get("engine") != "candidate-preparation-cli":
        errors.append("Public normalization engine is invalid")
    bounded_string(aggregate_counts.get("engine_version"), "Public normalization engine_version", 32, r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?")
    for field in (
        "record_count", "main_heading_count", "subheading_count", "complete_heading_path_count",
        "displayed_locator_count", "expanded_locator_assignment_count", "cross_reference_count",
        "unresolved_locator_count", "candidate_pdf_pages", "reading_order_regions", "extracted_lines",
        "normalization_exceptions",
    ):
        nonnegative_integer(aggregate_counts.get(field), f"Public aggregate_counts.{field}")
    if aggregate_counts.get("editorial_corrections_applied") is not False or aggregate_counts.get("benchmark_content_used") is not False:
        errors.append("Public aggregate counts must attest mechanical benchmark-blind normalization")
    nonnegative_integer(report.get("exception_count"), "Public exception_count")
    qa_summary = exact_keys(report.get("qa"), {"mode", "exact_set_gate_complete", "candidate_reproduction_confirmed", "editorial_quality_judgments_performed"}, "Public QA summary")
    if qa_summary != {"mode": "full", "exact_set_gate_complete": True, "candidate_reproduction_confirmed": True, "editorial_quality_judgments_performed": False}:
        errors.append("Public QA summary does not attest the complete fidelity gate")
    normalization_summary = exact_keys(report.get("normalization"), {"editorial_corrections_applied", "benchmark_content_used"}, "Public normalization summary")
    if normalization_summary != {"editorial_corrections_applied": False, "benchmark_content_used": False}:
        errors.append("Public normalization summary is invalid")
    if report.get("private_artifacts_published") is not False:
        errors.append("Public report must attest private_artifacts_published=false")
    if report.get("qa", {}).get("editorial_quality_judgments_performed") is not False:
        errors.append("Public report cannot claim editorial quality judgments")
    if report.get("normalization", {}).get("benchmark_content_used") is not False:
        errors.append("Public report must attest benchmark_content_used=false")
    if report.get("benchmark_lock_status") != "pending_final_benchmark" or report.get("status") != "ready_for_private_receipt":
        errors.append("Public report preparation/benchmark status is invalid")
    return errors


def load_public_directory_snapshot(root: Path) -> tuple[dict[str, dict[str, Any]], dict[str, bytes], dict[str, str]]:
    root = root.resolve()
    actual: set[str] = set()
    for path in root.rglob("*"):
        require(not path.is_symlink(), "public_symlink", f"Public projection cannot contain a symlink: {path}")
        if path.is_file():
            actual.add(path.relative_to(root).as_posix())
    require(actual == PUBLIC_PATHS, "public_allowlist_mismatch", "Public output directory does not contain the exact three-file allowlist.", {"expected": sorted(PUBLIC_PATHS), "actual": sorted(actual)})
    documents: dict[str, dict[str, Any]] = {}
    payloads: dict[str, bytes] = {}
    hashes: dict[str, str] = {}
    for relative in sorted(PUBLIC_PATHS):
        document, payload, digest = load_json_snapshot(root / relative, relative)
        documents[relative] = document
        payloads[relative] = payload
        hashes[relative] = digest
    return documents, payloads, hashes


def load_public_directory(root: Path) -> dict[str, dict[str, Any]]:
    documents, _, _ = load_public_directory_snapshot(root)
    return documents


def write_public_projection(root: Path, documents: dict[str, dict[str, Any]], force: bool = False) -> dict[str, str]:
    errors = validate_public_documents(documents)
    require(not errors, "public_projection_invalid", "Public projection failed its schema/content safety gate.", errors)
    require_no_symlink_components(root, "Public output root")
    root = root.resolve()
    require(root != root.parent, "unsafe_public_output", "Public output root cannot be a filesystem root.")
    if root.exists():
        existing = [path for path in root.rglob("*") if path.is_file()]
        existing_relatives = {path.relative_to(root).as_posix() for path in existing}
        unexpected = existing_relatives - PUBLIC_PATHS
        require(not unexpected, "public_output_contains_unexpected_files", "Public output root contains files outside the exact allowlist; none were changed.", sorted(unexpected))
        require(not existing or force, "public_output_exists", "Refusing to overwrite existing public projection files without --force.", [str(path) for path in existing])
    for relative, document in documents.items():
        target = root / relative
        require_safe_output_path(target, root, f"Public output {relative}")
        payload = (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        replace_bytes_atomic(target, payload)
    reloaded, _, hashes = load_public_directory_snapshot(root)
    errors = validate_public_documents(reloaded)
    require(not errors, "public_projection_invalid", "Written public projection failed its safety rescan.", errors)
    return hashes


def command_validate_public(args: argparse.Namespace) -> None:
    documents, _, hashes = load_public_directory_snapshot(Path(args.public_dir))
    errors = validate_public_documents(documents)
    require(not errors, "public_projection_invalid", "Public projection failed validation.", errors)
    emit({
        "command": "validate-public-preparation",
        "ok": True,
        "changed_paths": sorted(PUBLIC_PATHS),
        "file_hashes": hashes,
        "outgoing_safety_scan": "passed",
        "warnings": [],
    })


def validate_publication_plan(repo_state: dict[str, Any], candidate_id: str, requested_branch: str | None) -> dict[str, Any]:
    branch = requested_branch or default_worker_branch(candidate_id)
    require(branch == default_worker_branch(candidate_id), "invalid_worker_branch", f"Worker branch must be {default_worker_branch(candidate_id)}")
    branches = repo_state.get("branches", [])
    require(isinstance(branches, list) and all(isinstance(value, str) for value in branches), "invalid_repository_state", "repository-state.branches must be an array of branch names.")
    require(branch not in branches, "worker_branch_collision", f"Refusing to reuse existing worker branch {branch}.")
    is_empty = repo_state.get("is_empty") is True
    base_commit = repo_state.get("base_commit")
    bootstrap_files = repo_state.get("bootstrap_files", [])
    if is_empty:
        require(base_commit in {None, ""}, "empty_repository_base", "An empty repository must not claim an existing base commit.")
        require(isinstance(bootstrap_files, list) and len(bootstrap_files) == 2 and set(bootstrap_files) == BOOTSTRAP_PATHS, "unsafe_empty_repository_bootstrap", "Empty-repository bootstrap must add exactly README.md and .gitignore.")
        mode = "bootstrap_main_readme_gitignore_then_worker_branch"
    else:
        base_commit = require_commit(base_commit, "repository_state.base_commit")
        require(not bootstrap_files, "unexpected_bootstrap", "An initialized repository must not request bootstrap files.")
        mode = "branch_from_existing_default_head"
    default_branch = repo_state.get("default_branch") or "main"
    require(isinstance(default_branch, str) and bool(default_branch), "invalid_repository_state", "Repository default branch is required.")
    if is_empty:
        require(default_branch == "main", "unsafe_empty_repository_bootstrap", "Empty-repository bootstrap is permitted only on main.")
    return {
        "branch": branch,
        "base_commit": base_commit,
        "default_branch": default_branch,
        "repository_mode": mode,
        "bootstrap_exception": is_empty,
        "allowed_bootstrap_files": sorted(BOOTSTRAP_PATHS) if is_empty else [],
    }


def validate_bootstrap_evidence(value: Any, receipt: dict[str, Any], base_commit: str, observation_time: Any) -> str | None:
    """Validate the narrow, GitHub-observed empty-repository initialization exception."""
    repositories = receipt.get("repositories", {})
    if not repositories.get("bootstrap_exception"):
        require(value is None, "unexpected_bootstrap_evidence", "Initialized repositories must use bootstrap=null in publication evidence.")
        return None
    required = {
        "repository_was_empty", "empty_observed_at", "initialization_commit",
        "parent_commits", "default_branch", "tree_entries",
    }
    require(isinstance(value, dict) and set(value) == required, "bootstrap_evidence_schema", "Empty-repository bootstrap evidence is missing or malformed.")
    require(value.get("repository_was_empty") is True, "bootstrap_evidence_schema", "Bootstrap evidence must record the preceding empty-repository observation.")
    require(value.get("default_branch") == "main", "bootstrap_evidence_schema", "Empty-repository bootstrap is allowed only on main.")
    require(value.get("parent_commits") == [], "bootstrap_evidence_schema", "The initialization commit must be a root commit with no parents.")
    require(require_commit(value.get("initialization_commit"), "bootstrap.initialization_commit") == base_commit, "bootstrap_commit_mismatch", "The evidenced initialization commit differs from the pull-request base commit.")
    empty_observed_at = require_timestamp(value.get("empty_observed_at"), "bootstrap.empty_observed_at")
    publication_observed_at = require_timestamp(observation_time, "publication_evidence.observed_at")
    require(empty_observed_at <= publication_observed_at, "bootstrap_evidence_order", "The empty-repository observation cannot postdate publication evidence.")
    entries = value.get("tree_entries")
    require(isinstance(entries, list) and len(entries) == 2, "bootstrap_tree_mismatch", "The root initialization commit must contain exactly README.md and .gitignore.")
    paths: list[str] = []
    for entry in entries:
        require(isinstance(entry, dict) and set(entry) == {"path", "type", "blob_sha", "file_sha256"}, "bootstrap_evidence_schema", "Every bootstrap tree entry must contain path, type, blob_sha, and file_sha256 only.")
        relative = safe_relative_path(str(entry.get("path", "")))
        require(entry.get("type") == "blob", "bootstrap_tree_mismatch", "Bootstrap tree entries must be regular Git blobs.")
        require(isinstance(entry.get("blob_sha"), str) and bool(re.fullmatch(r"[a-fA-F0-9]{40}|[a-fA-F0-9]{64}", entry["blob_sha"])), "bootstrap_tree_mismatch", f"Bootstrap Git blob identity is invalid for {relative}.")
        require_sha256(entry.get("file_sha256"), f"bootstrap.tree_entries[{relative}].file_sha256")
        paths.append(relative)
    require(len(set(paths)) == 2 and set(paths) == BOOTSTRAP_PATHS, "bootstrap_tree_mismatch", "Bootstrap root tree paths must equal README.md and .gitignore exactly.")
    return canonical_hash(value, "_no_own_hash")


def zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100600 << 16
    return info


def write_zip_atomic(output: Path, members: dict[str, bytes]) -> None:
    """Write a deterministic ZIP through an exclusive random temporary file."""
    require_no_symlink_components(output.parent, "ZIP output parent")
    require(not output.is_symlink(), "unsafe_output_symlink", f"ZIP output cannot be a symlink: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    require_no_symlink_components(output.parent, "ZIP output parent")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".tmp", dir=output.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w+b") as handle:
            with zipfile.ZipFile(handle, "w") as archive:
                for name in sorted(members):
                    archive.writestr(zip_info(name), members[name])
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()


def build_private_recovery_zip(
    output: Path,
    result: dict[str, Any],
    checkpoint_ref: str,
    force: bool = False,
) -> dict[str, Any]:
    require(not output.exists() or force, "output_exists", f"Refusing to overwrite {output}")
    require(isinstance(checkpoint_ref, str) and checkpoint_ref.strip(), "checkpoint_ref_required", "A private checkpoint/recovery reference is required.")
    candidate_id = normalize_candidate_id(result["documents"]["candidate_ref"]["candidate_id"])
    members: dict[str, bytes] = {}
    artifact_records: list[dict[str, Any]] = []
    for key in PRIVATE_ARTIFACT_KEYS:
        source = result["paths"][key]
        require(source.suffix.lower() == ".json", "private_bundle_member_type", "Private recovery ZIP accepts JSON preparation artifacts only.")
        relative = PRIVATE_ARCHIVE_PATHS[key].format(candidate_id=candidate_id)
        payload = source.read_bytes()
        members[relative] = payload
        artifact_records.append({"artifact": key, "path": relative, "sha256": sha256_bytes(payload), "byte_length": len(payload)})
    metadata = {
        "schema_version": "candidate-preparation-recovery-bundle-v1",
        "candidate_id": result["documents"]["candidate_ref"]["candidate_id"],
        "candidate_sha256": result["candidate_sha256"],
        "source_sha256": result["identities"]["source_sha256"],
        "source_edition": result["identities"]["source_edition"],
        "page_map_sha256": result["identities"]["page_map_sha256"],
        "chunk_manifest_sha256": result["identities"]["chunk_manifest_sha256"],
        "policy_sha256": result["identities"]["policy_sha256"],
        "rubric_version": result["identities"]["rubric_version"],
        "audit_mode": result["identities"]["audit_mode"],
        "checkpoint_ref": checkpoint_ref,
        "artifacts": sorted(artifact_records, key=lambda item: item["path"]),
        "excluded": ["candidate PDF bytes", "source PDF bytes", "benchmark content", "secrets"],
    }
    metadata["bundle_metadata_sha256"] = canonical_hash(metadata, "bundle_metadata_sha256")
    metadata_bytes = (json.dumps(metadata, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    members["candidate-preparation-bundle-metadata.json"] = metadata_bytes
    write_zip_atomic(output, members)
    return {"path": str(output), "sha256": sha256_file(output), "byte_length": output.stat().st_size, "metadata": metadata}


def build_worker_receipt(
    result: dict[str, Any],
    public_hashes: dict[str, str],
    recovery: dict[str, Any],
    project: str,
    benchmark_project: str,
    benchmark_preparation_base_commit: str,
    plan: dict[str, Any],
) -> dict[str, Any]:
    candidate_ref = result["documents"]["candidate_ref"]
    receipt = {
        "schema_version": "candidate-preparation-receipt-v1",
        "receipt_id": stable_id("CPR", result["candidate_sha256"], {"project": project, "branch": plan["branch"], "checkpoint_ref": recovery["metadata"]["checkpoint_ref"]}),
        "created_at": now(),
        "status": "ready_for_pull_request",
        "candidate_id": candidate_ref["candidate_id"],
        "candidate_sha256": result["candidate_sha256"],
        "file_origin": candidate_ref["file_origin"],
        "source_identity": {"sha256": result["identities"]["source_sha256"], "edition": result["identities"]["source_edition"]},
        "page_map_sha256": result["identities"]["page_map_sha256"],
        "chunk_manifest_sha256": result["identities"]["chunk_manifest_sha256"],
        "policy_identity": {
            "profile": result["identities"]["policy_profile"],
            "sha256": result["identities"]["policy_sha256"],
            "rubric_version": result["identities"]["rubric_version"],
            "audit_mode": result["identities"]["audit_mode"],
        },
        "adapter_identity": result["documents"]["layout_extraction"]["adapter"],
        "provenance": candidate_ref["provenance"],
        "private_artifacts": [
            {"artifact": key, "archive_path": PRIVATE_ARCHIVE_PATHS[key].format(candidate_id=normalize_candidate_id(candidate_ref["candidate_id"])), "sha256": result["hashes"][key]}
            for key in PRIVATE_ARTIFACT_KEYS
        ],
        "private_recovery": {
            "purpose": "candidate_preparation_recovery_only",
            "sha256": recovery["sha256"],
            "byte_length": recovery["byte_length"],
            "bundle_metadata_sha256": recovery["metadata"]["bundle_metadata_sha256"],
            "checkpoint_ref": recovery["metadata"]["checkpoint_ref"],
        },
        "public_projection": {"changed_paths": sorted(PUBLIC_PATHS), "hashes": public_hashes, "outgoing_safety_scan": "passed"},
        "repositories": {
            "candidate_project": project,
            "benchmark_project": benchmark_project,
            "candidate_base_commit": plan["base_commit"],
            "candidate_default_branch": plan["default_branch"],
            "worker_branch": plan["branch"],
            "repository_mode": plan["repository_mode"],
            "bootstrap_exception": plan["bootstrap_exception"],
            "benchmark_preparation_base_commit": benchmark_preparation_base_commit,
        },
        "publication": {"status": "not_yet_published", "pull_request": None, "head_commit": None},
        "benchmark_lock": {"status": "pending_final_benchmark", "final_commit": None, "benchmark_sha256": None},
        "qa": {"mode": "full", "exact_set_gate": "passed", "candidate_quality_judgments_performed": False},
        "limitations": [
            f"{field}: {record['status']} â€” {record['rationale']}"
            for field, record in candidate_ref["provenance"].items()
            if record["status"] != "verified"
        ],
    }
    receipt["receipt_sha256"] = canonical_hash(receipt, "receipt_sha256")
    return receipt


def command_build_worker(args: argparse.Namespace) -> None:
    require_github_project(args.project, "project")
    require_github_project(args.benchmark_project, "benchmark_project")
    benchmark_preparation_base_commit = require_commit(args.benchmark_ref, "benchmark_ref")
    for raw_path, label in (
        (args.public_output, "Public output root"),
        (args.recovery_zip, "Private recovery output"),
        (args.receipt_output, "Worker receipt output"),
        (args.preparation_dir, "Private preparation root"),
    ):
        require_no_symlink_components(Path(raw_path), label)
    public_output = Path(args.public_output).resolve()
    recovery_output = Path(args.recovery_zip).resolve()
    receipt_output = Path(args.receipt_output).resolve()
    preparation_root = Path(args.preparation_dir).resolve()
    public_members = {public_output / relative for relative in PUBLIC_PATHS}
    for member in public_members:
        require_safe_output_path(member, public_output, "Public projection member")
    output_files = {*public_members, recovery_output, receipt_output}
    require(len(output_files) == len(PUBLIC_PATHS) + 2, "output_path_collision", "Every worker output path must be distinct.")
    require(not path_is_within(recovery_output, public_output) and not path_is_within(receipt_output, public_output), "output_path_collision", "Private recovery and receipt outputs must be outside the public projection root.")
    require(
        not path_is_within(public_output, preparation_root) and not path_is_within(preparation_root, public_output),
        "private_public_path_overlap",
        "The private preparation root and public projection root must be disjoint.",
    )
    require(
        not path_is_within(recovery_output, preparation_root) and not path_is_within(receipt_output, preparation_root),
        "output_path_collision",
        "Recovery and receipt outputs must be outside the validated preparation artifact root.",
    )
    input_files = {
        Path(value).resolve()
        for value in (
            args.candidate_file, args.state, args.page_map, args.chunk_manifest,
            args.policy, args.repository_state, *( [args.qa] if args.qa else [] ),
        )
    }
    require(not output_files.intersection(input_files), "output_path_collision", "Worker outputs must not overwrite any input artifact.")
    require(
        not any(path_is_within(path, public_output) for path in input_files),
        "private_public_path_overlap",
        "No worker input may be stored beneath the public projection root.",
    )
    for path in (recovery_output, receipt_output):
        require(not path.exists() or (args.force and path.is_file() and not path.is_symlink()), "output_exists", f"Refusing to overwrite {path}")
    if public_output.exists():
        require(public_output.is_dir() and not public_output.is_symlink(), "unsafe_public_output", "Public output root must be a real directory.")
        existing_files = [path for path in public_output.rglob("*") if path.is_file()]
        existing_relatives = {path.relative_to(public_output).as_posix() for path in existing_files}
        require(not (existing_relatives - PUBLIC_PATHS), "public_output_contains_unexpected_files", "Public output root contains files outside the exact allowlist; none were changed.", sorted(existing_relatives - PUBLIC_PATHS))
        require(not existing_files or args.force, "public_output_exists", "Refusing to overwrite existing public projection files without --force.", [str(path) for path in existing_files])
    result = validate_private_preparation(
        Path(args.preparation_dir), args.candidate_id, Path(args.candidate_file), Path(args.state),
        Path(args.page_map), Path(args.chunk_manifest), Path(args.policy),
        Path(args.qa) if args.qa else None, args.source_edition,
    )
    repo_state = load_json(Path(args.repository_state), "Candidate repository state")
    plan = validate_publication_plan(repo_state, args.candidate_id, args.branch)
    public_documents = public_projection_documents(result)
    snapshots = {path: path.read_bytes() if path.is_file() else None for path in output_files}
    receipt_path = receipt_output
    try:
        public_hashes = write_public_projection(public_output, public_documents, args.force)
        recovery = build_private_recovery_zip(recovery_output, result, args.checkpoint_ref, args.force)
        receipt = build_worker_receipt(result, public_hashes, recovery, args.project, args.benchmark_project, benchmark_preparation_base_commit, plan)
        save_json(receipt_path, receipt)
    except Exception:
        for path, previous in snapshots.items():
            if previous is None:
                if path.is_file() or path.is_symlink():
                    path.unlink()
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(previous)
        raise
    emit({
        "command": "build-candidate-preparation-worker",
        "ok": True,
        "candidate_id": args.candidate_id,
        "candidate_sha256": result["candidate_sha256"],
        "branch": plan["branch"],
        "base_commit": plan["base_commit"],
        "repository_mode": plan["repository_mode"],
        "public_changed_paths": sorted(PUBLIC_PATHS),
        "public_hashes": public_hashes,
        "receipt": {"path": str(receipt_path), "sha256": sha256_file(receipt_path), "canonical_sha256": receipt["receipt_sha256"]},
        "private_recovery": {"path": recovery["path"], "sha256": recovery["sha256"]},
        "canonical_state_mutated": False,
        "next_actions": ["create_one_commit_on_worker_branch", "open_one_pull_request_without_merge", "bind-publication"],
        "warnings": receipt["limitations"],
    })


def validate_receipt_document(receipt: dict[str, Any], allowed_statuses: set[str] | None = None) -> dict[str, Any]:
    """Validate one already-snapshotted receipt document."""
    def exact(value: Any, keys: set[str], label: str) -> dict[str, Any]:
        require(isinstance(value, dict) and set(value) == keys, "receipt_schema", f"{label} has missing or unexpected properties.", {"expected": sorted(keys), "actual": sorted(value) if isinstance(value, dict) else None})
        return value

    top_level = {
        "schema_version", "receipt_id", "receipt_sha256", "created_at", "status",
        "candidate_id", "candidate_sha256", "file_origin", "source_identity",
        "page_map_sha256", "chunk_manifest_sha256", "policy_identity", "adapter_identity",
        "provenance", "private_artifacts", "private_recovery", "public_projection",
        "repositories", "publication", "benchmark_lock", "qa", "limitations",
    }
    exact(receipt, top_level, "Candidate preparation receipt")
    require(receipt.get("schema_version") == "candidate-preparation-receipt-v1", "receipt_schema", "Expected candidate-preparation-receipt-v1.")
    validate_self_hash(receipt, "receipt_sha256", "Candidate preparation receipt")
    require(receipt.get("status") in {"ready_for_pull_request", "published_unmerged"}, "receipt_status", "Receipt status is invalid.")
    if allowed_statuses is not None:
        require(receipt.get("status") in allowed_statuses, "receipt_status", f"Receipt status must be one of {sorted(allowed_statuses)}.")
    require(isinstance(receipt.get("receipt_id"), str) and bool(re.fullmatch(r"CPR-[A-F0-9]{12}", receipt["receipt_id"])), "receipt_schema", "Receipt receipt_id is invalid.")
    require_timestamp(receipt.get("created_at"), "receipt.created_at")
    require(isinstance(receipt.get("candidate_id"), str) and bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", receipt["candidate_id"])), "receipt_identity", "Rg­µçkh‘éì¶»§q«^tôâ–bVF—Eö¶–æBÓÒ&Æö6F÷""VÇ6RÔ•54”äuôTD•EõdU%4”ôâÀ¢Ð¢–bVF—Eö¶–æBÓÒ&Æö6F÷"# ¢&—fFUö'F–f7BçWFFR‡²&W‡V7FVEö6÷VçB#¢&W7VÇE²&6ö×ÆWF–öâ%Õ²&W‡V7FVB%ÒÂ&§VFvVEö6÷VçB#¢&W7VÇE²&6ö×ÆWF–öâ%Õ²&§VFvVB%×Ò¢VÇ6S ¢&—fFUö'F–f7BçWFFR‡°¢&W‡V7FVE÷7V&¦V7Eö6÷VçB#¢&W7VÇE²&6ö×ÆWF–öâ%Õ²'7V&¦V7G2%Õ²&W‡V7FVB%ÒÀ¢&§VFvVE÷7V&¦V7Eö6÷VçB#¢&W7VÇE²&6ö×ÆWF–öâ%Õ²'7V&¦V7G2%Õ²&§VFvVB%ÒÀ¢&W‡V7FVE÷&VFW%÷F6µö6÷VçB#¢&W7VÇE²&6ö×ÆWF–öâ%Õ²'&VFW%÷F6·2%Õ²&W‡V7FVB%ÒÀ¢&§VFvVE÷&VFW%÷F6µö6÷VçB#¢&W7VÇE²&6ö×ÆWF–öâ%Õ²'&VFW%÷F6·2%Õ²&§VFvVB%ÒÀ¢&W‡V7FVE÷G&VFÖVçEö6÷VçB#¢&W7VÇE²&6ö×ÆWF–öâ%Õ²'G&VFÖVçG2%Õ²&W‡V7FVB%ÒÀ¢&§VFvVE÷G&VFÖVçEö6÷VçB#¢&W7VÇE²&6ö×ÆWF–öâ%Õ²'G&VFÖVçG2%Õ²&§VFvVB%ÒÀ¢Ò¢&V6V—BÒ°¢'66†VÖ÷fW'6–öâ#¢&V6V—E÷fW'6–öâ†VF—Eö¶–æB’À¢'&V6V—Eö–B#¢7F&ÆUö–FVçF–f–W"‡&Vf—‚Â²&WfÇVF–öåö–B#¢g&÷¦Vå²'7FFR%Õ²&WfÇVF–öåö–B%ÒÂ&6æF–FFUö–B#¢g&÷¦Vå²&6æF–FFUö–B%ÒÂ&6‡Væµö–B#¢6‡Væµö–BÂ&VF—Eö¶–æB#¢VF—Eö¶–æBÂ&&6Uö6öÖÖ—B#¢&6Uö6öÖÖ—BÂ'&—fFUö'F–f7E÷6†#Sb#¢&—fFUö'F–f7E²'6†#Sb%×Ò’À¢'&V6V—E÷6†#Sb#¢""À¢&7&VFVEöB#¢æ÷r‚’À¢'7FGW2#¢'&VG•öf÷%÷VÆÅ÷&WVW7B"À¢&VF—Eö¶–æB#¢6W&–Æ—¦VEöVF—Eö¶–æB†VF—Eö¶–æB’À¢&WfÇVF–öåö–B#¢g&÷¦Vå²'7FFR%Õ²&WfÇVF–öåö–B%ÒÀ¢&6æF–FFUö–B#¢g&÷¦Vå²&6æF–FFUö–B%ÒÀ¢&6‡Væ²#¢²&6‡Væµö–B#¢6‡Væµö–BÂ'6÷W&6U÷Væ—EöÆ&VÂ#¢6÷W&6U÷Væ—EöÆ&VÂ†6‡Væ²’Â&÷væVEöFö7VÖVçE÷vU÷&ævW2#¢6‡Væµ²&÷væVEöFö7VÖVçE÷vU÷&ævW2%×ÒÀ¢'&W÷6—F÷&–W2#¢°¢&6æF–FFU÷&ö¦V7B#¢&ö¦V7BÀ¢&6æF–FFUö&6Uö'&æ6‚#¢&6Uö'&æ6‚À¢&–Ö×WF&ÆU÷v÷&¶W%ö&6Uö6öÖÖ—B#¢&6Uö6öÖÖ—BÀ¢'v÷&¶W%ö'&æ6‚#¢v÷&¶W%ö'&æ6‚À¢'V&Æ–5÷&W÷'E÷F‚#¢V&Æ–5÷F‚À¢ÒÀ¢&–FVçF—F–W2#¢–FVçF—F–W2À¢'6÷W&6U÷&V6öææV7F–öâ#¢&V6V—E÷6÷W&6U÷&V6öææV7F–öâ‚’À¢'&—fFUö'F–f7B#¢&—fFUö'F–f7BÀ¢'&—fFU÷&V6÷fW'’#¢°¢'&ö÷E÷&Vb#¢6fU÷&VÆF—fU÷F‚‡&V6÷fW'•÷&ö÷E÷&Vb’À¢&&6†—fU÷F‚#¢6fU÷&VÆF—fU÷F‚‡&V6÷fW'•²&&6†—fU÷F‚%ÒææÖR’À¢'6†#Sb#¢&V6÷fW'•²&&6†—fU÷6†#Sb%ÒÀ¢&'—FUöÆVæwF‚#¢&V6÷fW'•²&&6†—fUö'—FUöÆVæwF‚%ÒÀ¢&ÖWFFF÷6†#Sb#¢&V6÷fW'•²&ÖWFFF÷6†#Sb%ÒÀ¢&6†V6·ö–çE÷&Vb#¢&V6÷fW'•²&6†V6·ö–çE÷&Vb%ÒÀ¢ÒÀ¢'V&Æ–5÷&ö¦V7F–öâ#¢²'F‚#¢V&Æ–5÷F‚Â'6†#Sb#¢6†#Seö'—FW2‡V&Æ–5÷–ÆöB’Â&÷WFvö–æu÷6fWG•÷66â#¢'76VB'ÒÀ¢'fÆ–FF–öâ#¢fÆ–FF–öåövFW2†VF—Eö¶–æB’À¢'V&Æ–6F–öâ#¢²'7FGW2#¢&æ÷E÷–WE÷V&Æ—6†VB"Â'VÆÅ÷&WVW7B#¢æöæRÂ&†VEö6öÖÖ—B#¢æöæWÒÀ¢&Æ–Ö—FF–öç2#¢²$v—D‡V"V&Æ–6F–öâæBVÆÂ×&WVW7B7&VF–öâ&R÷&6†W7G&F÷"÷W&F–öç2â%ÒÀ¢Ð¢&V6V—E²'&V6V—E÷6†#Sb%ÒÒ6æöæ–6Åö†6‚‡&V6V—BÂ'&V6V—E÷6†#Sb"¢V&Æ–6F–öå÷&öf–ÆRÒg&÷¦VâævWB‚'V&Æ–6F–öå÷&öf–ÆR"ÂV&Æ–6F–öå÷&öf–ÆUöf÷"†g&÷¦Vå²'7FFR%Ò’¢fÆ–FFU÷&V6V—B‡&V6V—BÂVF—Eö¶–æBÂV&Æ–6F–öå÷&öf–ÆR¢&WGW&â&V6V—@  ¦FVbfÆ–FFU÷&V6V—B‡&V6V—C¢F–7E·7G"Âç•ÒÂVF—Eö¶–æC¢7G"ÂæöæRÒæöæRÂV&Æ–6F–öå÷&öf–ÆS¢7G"ÂæöæRÒæöæR’Óâ7G# ¢W†7Eö¶W—2‡&V6V—BÂ$T4T•Eõ$UT•$TBÂ%v÷&¶W"&V6V—B"¢–æfW'&VBÒ&Æö6F÷""–b&V6V—BævWB‚&VF—Eö¶–æB"’ÓÒ&Æö6F÷%öVF—B"VÇ6R&Ö—76–æuö66W72"–b&V6V—BævWB‚&VF—Eö¶–æB"’ÓÒ&Ö—76–æuö66W72"VÇ6RæöæP¢&WV—&R†–æfW'&VB—2æ÷BæöæRæB†VF—Eö¶–æB—2æöæR÷"–æfW'&VBÓÒVF—Eö¶–æB’Â'&V6V—Eö¶–æB"Â%v÷&¶W"&V6V—BVF—B¶–æB—2–çfÆ–Bâ"¢&WV—&R‡&V6V—E²'66†VÖ÷fW'6–öâ%ÒÓÒ&V6V—E÷fW'6–öâ†–æfW'&VB’Â'&V6V—E÷66†VÖ"Â%v÷&¶W"&V6V—B66†VÖfW'6–öâ—2–çfÆ–Bâ"¢fÆ–FFU÷6VÆeö†6‚‡&V6V—BÂ'&V6V—E÷6†#Sb"Â%v÷&¶W"&V6V—B"¢&WV—&U÷F–ÖW7F×‡&V6V—E²&7&VFVEöB%ÒÂ'&V6V—Bæ7&VFVEöB"¢6‡Væµö–BÒfÆ–FFUö6‡Væµö–B‡&V6V—BævWB‚&6‡Væ²"Â·Ò’ævWB‚&6‡Væµö–B"’¢W‡V7FVEö'&æ6‚Ò'&æ6…öf÷"†–æfW'&VBÂ6‡Væµö–B¢&W÷6—F÷&–W2Ò&V6V—BævWB‚'&W÷6—F÷&–W2"Â·Ò¢&WV—&Uöv—F‡V%÷&ö¦V7B‡&W÷6—F÷&–W2ævWB‚&6æF–FFU÷&ö¦V7B"’Â'&V6V—Bç&W÷6—F÷&–W2æ6æF–FFU÷&ö¦V7B"¢&WV—&R‡&W÷6—F÷&–W2ævWB‚'v÷&¶W%ö'&æ6‚"’ÓÒW‡V7FVEö'&æ6‚Â'&V6V—Eö'&æ6‚"Â%v÷&¶W"&V6V—B'&æ6‚—2æ÷BF†RFWFW&Ö–æ—7F–26‡Væ²'&æ6‚â"¢–æfW'&VE÷&öf–ÆRÒV&Æ–6F–öå÷&öf–ÆUög&öÕ÷F‚†–æfW'&VBÂ6‡Væµö–BÂ&W÷6—F÷&–W2ævWB‚'V&Æ–5÷&W÷'E÷F‚"’¢&WV—&R‡V&Æ–6F–öå÷&öf–ÆR—2æöæR÷"–æfW'&VE÷&öf–ÆRÓÒV&Æ–6F–öå÷&öf–ÆRÂ'V&Æ–6F–öå÷&öf–ÆUöÖ—6ÖF6‚"Â%v÷&¶W"&V6V—BV&Æ–6F–öâF‚F–ffW'2g&öÒF†Rg&÷¦VâWfÇVF–öâ&öf–ÆRâ"¢W‡V7FVE÷V&Æ–2ÒV&Æ–5÷F…öf÷"†–æfW'&VBÂ6‡Væµö–BÂ–æfW'&VE÷&öf–ÆR¢&WV—&Uö6öÖÖ—B‡&W÷6—F÷&–W2ævWB‚&–Ö×WF&ÆU÷v÷&¶W%ö&6Uö6öÖÖ—B"’Â'&V6V—Bç&W÷6—F÷&–W2æ–Ö×WF&ÆU÷v÷&¶W%ö&6Uö6öÖÖ—B"¢&WV—&U÷6†#Sb‡&V6V—BævWB‚'&—fFUö'F–f7B"Â·Ò’ævWB‚'6†#Sb"’Â'&V6V—Bç&—fFUö'F–f7Bç6†#Sb"¢&WV—&U÷6†#Sb‡&V6V—BævWB‚'&—fFU÷&V6÷fW'’"Â·Ò’ævWB‚'6†#Sb"’Â'&V6V—Bç&—fFU÷&V6÷fW'’ç6†#Sb"¢&WV—&U÷6†#Sb‡&V6V—BævWB‚'V&Æ–5÷&ö¦V7F–öâ"Â·Ò’ævWB‚'6†#Sb"’Â'&V6V—BçV&Æ–5÷&ö¦V7F–öâç6†#Sb"¢&WV—&R‡&V6V—E²'V&Æ–5÷&ö¦V7F–öâ%ÒævWB‚'F‚"’ÓÒW‡V7FVE÷V&Æ–2Â'&V6V—E÷V&Æ–5÷F‚"Â%&V6V—BV&Æ–2&ö¦V7F–öâF‚F–ffW'2â"¢&WV—&R‡&V6V—BævWB‚'7FGW2"’–â²'&VG•öf÷%÷VÆÅ÷&WVW7B"Â'V&Æ—6†VE÷VæÖW&vVB"Â'V&Æ–6F–öåö&Æö6¶VB'ÒÂ'&V6V—E÷7FGW2"Â%v÷&¶W"&V6V—B7FGW2—2–çfÆ–Bâ"¢–FVçF—G•öf–VÆG2Ò°¢'6÷W&6U÷6†#Sb"Â&6æF–FFU÷6†#Sb"Â&&Væ6†Ö&µ÷fW'6–öâ"Â&&Væ6†Ö&µ÷6†#Sb"Â&&Væ6†Ö&µöf–ÆU÷6†#Sb"À¢&&Væ6†Ö&µöÆö6µ÷6†#Sb"Â'öÆ–7•÷6†#Sb"Â'öÆ–7•öf–ÆU÷6†#Sb"Â'vUöÖ÷6†#Sb"Â'vUöÖöf–ÆU÷6†#Sb"À¢&6‡VæµöÖæ–fW7E÷6†#Sb"Â&6‡VæµöÖæ–fW7Eöf–ÆU÷6†#Sb"Â&æ÷&ÖÆ—¦VEö6æF–FFUöf–ÆU÷6†#Sb"Â&—FVÕö–çfVçF÷'•öf–ÆU÷6†#Sb"À¢'6÷W&6Uö6‡Væµöf–ÆU÷6†#Sb"Â'6÷W&6U÷6–FV6%öf–ÆU÷6†#Sb"À¢Ð¢–FVçF—G•öf–VÆG2æFB‚&Æö6F÷%÷6¶WEöf–ÆU÷6†#Sb"–b–æfW'&VBÓÒ&Æö6F÷""VÇ6R&Ö—76–æuö66W75ö÷væW'6†—÷6†#Sb"¢–b–æfW'&VBÓÒ&Ö—76–æuö66W72# ¢–FVçF—G•öf–VÆG2æFB‚&Æö6F÷%öVF—E÷6WE÷6†#Sb"¢&WV—&R‡6WB‡&V6V—BævWB‚&–FVçF—F–W2"Â·Ò’’ÓÒ–FVçF—G•öf–VÆG2Â'&V6V—Eö–FVçF—G’"Â%v÷&¶W"&V6V—B–FVçF—F–W2Fòæ÷BÖF6‚F†RW†7B&ÆÆVÂ×v÷&¶W"ÆÆ÷vÆ—7Bâ"¢f÷"f–VÆBÂfÇVR–â&V6V—E²&–FVçF—F–W2%Òæ—FV×2‚“ ¢–bf–VÆBÓÒ&&Væ6†Ö&µ÷fW'6–öâ# ¢&WV—&R†—6–ç7Fæ6R‡fÇVRÂ–çB’æBfÇVRâÂ'&V6V—Eö–FVçF—G’"Â%&V6V—B&Væ6†Ö&²fW'6–öâ×W7B&R÷6—F—fRâ"¢VÇ6S ¢&WV—&U÷6†#Sb‡fÇVRÂb'&V6V—Bæ–FVçF—F–W2ç¶f–VÆGÒ"¢&WV—&R‡&V6V—BævWB‚'6÷W&6U÷&V6öææV7F–öâ"’ÓÒ&V6V—E÷6÷W&6U÷&V6öææV7F–öâ‚’Â'&V6V—E÷&V6öææV7F–öâ"Â%v÷&¶W"&V6V—B6÷W&6Rö6æF–FFR&V6öææV7F–öâvFR—2–æ6ö×ÆWFRâ"¢&WV—&R‡&V6V—BævWB‚'fÆ–FF–öâ"’ÓÒfÆ–FF–öåövFW2†–æfW'&VB’Â'&V6V—E÷fÆ–FF–öâ"Â%v÷&¶W"&V6V—BfÆ–FF–öâvFW2F–ffW"g&öÒF†R7G&–7B&öf–ÆRâ"¢&WGW&â–æfW'&V@  ¦FVb6æöæ–6Å÷V&Æ–6F–öåöÖ–w&F–öå÷F‚†g&÷¦Vã¢F–7E·7G"Âç•ÒÂVF—Eö¶–æC¢7G"Â6‡Væµö–C¢7G"’ÓâFƒ ¢&VçBÒ6æöæ–6Åö6æF–FFU÷&VçB†g&÷¦Vâ¢F—&V7F÷'’Ò&VçBò‚&Æö6F÷"ÖVF—G2"–bVF—Eö¶–æBÓÒ&Æö6F÷""VÇ6R&Ö—76–ærÖ66W72ÖVF—G2"’ò'&÷fVææ6R ¢7FVÒÒ&Æö6F÷"ÖVF—B"–bVF—Eö¶–æBÓÒ&Æö6F÷""VÇ6R&Ö—76–ærÖ66W72ÖVF—B ¢&WGW&âF—&V7F÷'’òb'·7FV×Ò×V&Æ–6F–öâÖÖ–w&F–öâç¶6‡Væµö–GÒæ§6öâ   ¦FVbfÆ–FFU÷V&Æ–6F–öåöÖ–w&F–öâ€¢Ö–w&F–öã¢F–7E·7G"Âç•ÒÀ¢VF—Eö¶–æC¢7G"À¢6‡Væµö–C¢7G"À¢g&÷¦Vã¢F–7E·7G"Âç•ÒÀ¢&V6V—C¢F–7E·7G"Âç•ÒÀ¢6æöæ–6ÅöVF—E÷6†#Sc¢7G"À¢6æöæ–6ÅöVF—Eö'—FUöÆVæwFƒ¢–çBÀ¢’ÓâæöæS ¢W†7Eö¶W—2€¢Ö–w&F–öâÀ¢°¢'66†VÖ÷fW'6–öâ"Â&Ö–w&F–öå÷6†#Sb"Â&WfÇVF–öåö–B"Â&6æF–FFUö–B"Â&VF—Eö¶–æB"Â&6‡Væµö–B"À¢&Ö–w&FVEöB"Â'G&ç6—F–öâ"Â&ÆVv7•÷&V6V—B"Â&6æöæ–6Å÷V&Æ–5ö'F–f7B"Â&æ÷&ÖÆ—¦F–öâ"À¢ÒÀ¢%V&Æ–6F–öâÖ–w&F–öâ"À¢¢&WV—&R†Ö–w&F–öå²'66†VÖ÷fW'6–öâ%ÒÓÒT$Ä”4D”ôåôÔ”u$D”ôåõdU%4”ôâÂ'V&Æ–6F–öåöÖ–w&F–öå÷66†VÖ"Âb$W‡V7FVBµT$Ä”4D”ôåôÔ”u$D”ôåõdU%4”ôçÒâ"¢fÆ–FFU÷6VÆeö†6‚†Ö–w&F–öâÂ&Ö–w&F–öå÷6†#Sb"Â%V&Æ–6F–öâÖ–w&F–öâ"¢&WV—&U÷F–ÖW7F×†Ö–w&F–öå²&Ö–w&FVEöB%ÒÂ'V&Æ–6F–öåöÖ–w&F–öâæÖ–w&FVEöB"¢&WV—&R†Ö–w&F–öå²&WfÇVF–öåö–B%ÒÓÒg&÷¦Vå²'7FFR%ÒævWB‚&WfÇVF–öåö–B"’Â'V&Æ–6F–öåöÖ–w&F–öåö–FVçF—G’"Â%V&Æ–6F–öâÖ–w&F–öâWfÇVF–öâ–FVçF—G’F–ffW'2â"¢&WV—&R†Ö–w&F–öå²&6æF–FFUö–B%ÒÓÒg&÷¦Vå²'7FFR%ÒævWB‚&6æF–FFR"Â·Ò’ævWB‚&6æF–FFUö–B"’Â'V&Æ–6F–öåöÖ–w&F–öåö–FVçF—G’"Â%V&Æ–6F–öâÖ–w&F–öâ6æF–FFR–FVçF—G’F–ffW'2â"¢&WV—&R†Ö–w&F–öå²&VF—Eö¶–æB%ÒÓÒ6W&–Æ—¦VEöVF—Eö¶–æB†VF—Eö¶–æB’æBÖ–w&F–öå²&6‡Væµö–B%ÒÓÒ6‡Væµö–BÂ'V&Æ–6F–öåöÖ–w&F–öåö–FVçF—G’"Â%V&Æ–6F–öâÖ–w&F–öâ¶–æB÷"6‡Væ²F–ffW'2â"¢&WV—&R†Ö–w&F–öå²'G&ç6—F–öâ%ÒÓÒ²&g&öÒ#¢tu$TtDUôôäÅ’Â'Fò#¢T$Ä”5ôUdÅTD”ôåô%D”d5E7ÒÂ'V&Æ–6F–öåöÖ–w&F–öå÷G&ç6—F–öâ"Â%V&Æ–6F–öâÖ–w&F–öâ×W7B&Rvw&VvFUööæÇ’FòV&Æ–5öWfÇVF–öåö'F–f7G2â" ¢ÆVv7’ÒW†7Eö¶W—2†Ö–w&F–öå²&ÆVv7•÷&V6V—B%ÒÂ²'&V6V—E÷6†#Sb"Â'&—fFUö'F–f7E÷6†#Sb"Â'V&Æ–5÷&W÷'E÷6†#Sb'ÒÂ%V&Æ–6F–öâÖ–w&F–öâÆVv7’&V6V—B"¢&WV—&R†ÆVv7•²'&V6V—E÷6†#Sb%ÒÓÒ&V6V—E²'&V6V—E÷6†#Sb%ÒÂ'V&Æ–6F–öåöÖ–w&F–öå÷&V6V—B"Â%V&Æ–6F–öâÖ–w&F–öâ&–æG2F–ffW&VçBÆVv7’&V6V—Bâ"¢&WV—&R†ÆVv7•²'&—fFUö'F–f7E÷6†#Sb%ÒÓÒ&V6V—E²'&—fFUö'F–f7B%Õ²'6†#Sb%ÒÂ'V&Æ–6F–öåöÖ–w&F–öå÷&V6V—B"Â%V&Æ–6F–öâÖ–w&F–öâ&–æG2F–ffW&VçBÆVv7’&—fFRVF—Bâ"¢&WV—&R†ÆVv7•²'V&Æ–5÷&W÷'E÷6†#Sb%ÒÓÒ&V6V—E²'V&Æ–5÷&ö¦V7F–öâ%Õ²'6†#Sb%ÒÂ'V&Æ–6F–öåöÖ–w&F–öå÷&V6V—B"Â%V&Æ–6F–öâÖ–w&F–öâ&–æG2F–ffW&VçBÆVv7’vw&VvFR&W÷'Bâ" ¢V&Æ–2ÒW†7Eö¶W—2†Ö–w&F–öå²&6æöæ–6Å÷V&Æ–5ö'F–f7B%ÒÂ²'&W÷6—F÷'•÷F‚"Â'6†#Sb"Â&'—FUöÆVæwF‚"Â&6öÖÖ—B"Â&&Æö%÷6†'ÒÂ%V&Æ–6F–öâÖ–w&F–öâ6æöæ–6ÂV&Æ–2'F–f7B"¢&WV—&R‡V&Æ–5²'&W÷6—F÷'•÷F‚%ÒÓÒV&Æ–5÷F…öf÷"†VF—Eö¶–æBÂ6‡Væµö–BÂT$Ä”5ôUdÅTD”ôåô%D”d5E2’Â'V&Æ–6F–öåöÖ–w&F–öå÷F‚"Â%V&Æ–6F–öâÖ–w&F–öâæÖW2F†Rw&öær6æöæ–6ÂV&Æ–2F‚â"¢&WV—&U÷6†#Sb‡V&Æ–5²'6†#Sb%ÒÂ'V&Æ–6F–öåöÖ–w&F–öâæ6æöæ–6Å÷V&Æ–5ö'F–f7Bç6†#Sb"¢&WV—&Uö6öÖÖ—B‡V&Æ–5²&6öÖÖ—B%ÒÂ'V&Æ–6F–öåöÖ–w&F–öâæ6æöæ–6Å÷V&Æ–5ö'F–f7Bæ6öÖÖ—B"¢&WV—&Uö6öÖÖ—B‡V&Æ–5²&&Æö%÷6†%ÒÂ'V&Æ–6F–öåöÖ–w&F–öâæ6æöæ–6Å÷V&Æ–5ö'F–f7Bæ&Æö%÷6†"¢&WV—&R‡V&Æ–5²'6†#Sb%ÒÓÒ6æöæ–6ÅöVF—E÷6†#SbæBV&Æ–5²&'—FUöÆVæwF‚%ÒÓÒ6æöæ–6ÅöVF—Eö'—FUöÆVæwF‚Â'V&Æ–6F–öåöÖ–w&F–öå÷V&Æ–5ö&–æF–ær"Â%V&Æ–6F–öâÖ–w&F–öâFöW2æ÷B&–æBF†R6æöæ–6ÂVF—B'—FW2â" ¢æ÷&ÖÆ—¦F–öâÒW†7Eö¶W—2†Ö–w&F–öå²&æ÷&ÖÆ—¦F–öâ%ÒÂ²&ÖWF†öB"Â&§VFvÖVçEö6÷VçB"Â'6VÖçF–5öf–VÆG5÷&W6W'fVB"Â&ÆVv7•ö'F–f7E÷&WF–æVEö–å÷&V6÷fW'’'ÒÂ%V&Æ–6F–öâÖ–w&F–öâæ÷&ÖÆ—¦F–öâ"¢&WV—&R†æ÷&ÖÆ—¦F–öå²&ÖWF†öB%ÒÓÒ'7G&–7E÷V&Æ–5öÆÆ÷vÆ—7E÷c"Â'V&Æ–6F–öåöÖ–w&F–öåöæ÷&ÖÆ—¦F–öâ"Â%V&Æ–6F–öâÖ–w&F–öâæ÷&ÖÆ—¦F–öâÖWF†öBF–ffW'2â"¢&WV—&R†—6–ç7Fæ6R†æ÷&ÖÆ—¦F–öå²&§VFvÖVçEö6÷VçB%ÒÂ–çB’æBæ÷&ÖÆ—¦F–öå²&§VFvÖVçEö6÷VçB%ÒãÒÂ'V&Æ–6F–öåöÖ–w&F–öåöæ÷&ÖÆ—¦F–öâ"Â%V&Æ–6F–öâÖ–w&F–öâ§VFvÖVçB6÷VçB—2–çfÆ–Bâ"¢&WV—&R†æ÷&ÖÆ—¦F–öå²'6VÖçF–5öf–VÆG5÷&W6W'fVB%Ò—2G'VRæBæ÷&ÖÆ—¦F–öå²&ÆVv7•ö'F–f7E÷&WF–æVEö–å÷&V6÷fW'’%Ò—2G'VRÂ'V&Æ–6F–öåöÖ–w&F–öåöæ÷&ÖÆ—¦F–öâ"Â%V&Æ–6F–öâÖ–w&F–öâ×W7B&W6W'fR6VÖçF–2f–VÆG2æBÆVv7’&V6÷fW'’'—FW2â"  ¦FVb6öÖÖæEö'V–ÆE÷v÷&¶W"†&w3¢&w'6RäæÖW76RÂVF—Eö¶–æC¢7G"’ÓâæöæS ¢&ö¦V7BÒ&WV—&Uöv—F‡V%÷&ö¦V7B†&w2ç&ö¦V7BÂ'&ö¦V7B"¢6‡Væµö–BÒfÆ–FFUö6‡Væµö–B†&w2æ6‡Væµö–B¢v÷&¶W%ö'&æ6‚Ò&w2æ'&æ6‚÷"'&æ6…öf÷"†VF—Eö¶–æBÂ6‡Væµö–B¢&WV—&R‡v÷&¶W%ö'&æ6‚ÓÒ'&æ6…öf÷"†VF—Eö¶–æBÂ6‡Væµö–B’Â'v÷&¶W%ö'&æ6…ö–çfÆ–B"Â%&ÆÆVÂ6æF–FFRÖVF—B'&æ6†W2W6RF†RFWFW&Ö–æ—7F–2¶–æBö6‡Væ²'&æ6‚W†7FÇ’â"¢&W÷6—F÷'•÷7FFRÒfÆ–FFU÷&W÷6—F÷'•÷7FFR…F‚†&w2ç&W÷6—F÷'•÷7FFR’Â&ö¦V7BÂ&w2æ&6Uö'&æ6‚Âv÷&¶W%ö'&æ6‚¢g&÷¦VâÒÆöEög&÷¦Våö–çWG2†&w2ÂVF—Eö¶–æB¢&WV—&R†6‡Væµö–B–âg&÷¦Vå²&6‡Væ·2%ÒÂ'Væ¶æ÷våö6‡Væ²"Âb$6‡Væ²¶6‡Væµö–GÒ—2'6VçBg&öÒF†Rg&÷¦VâÖæ–fW7Bâ"¢&V6öææV7BÒfÆ–FFU÷6÷W&6U÷&V6öææV7F–öâ†&w2Âg&÷¦VâÂ6‡Væµö–B¢VF—BÂVF—E÷–ÆöBÂVF—E÷6†#SbÒÆöEö§6öå÷6æ6†÷B…F‚†&w2æVF—B’ç&W6öÇfR‚’Â%&—fFR6æF–FFRVF—B"¢–bVF—Eö¶–æBÓÒ&Æö6F÷"# ¢6¶WBÒfÆ–FFUöÆö6F÷%÷6¶WB…F‚†&w2æÆö6F÷%÷6¶WB’ç&W6öÇfR‚’Âg&÷¦VâÂ6‡Væµö–B¢6ö×&U÷6¶WE÷Fõö6æF–FFR‡6¶WBÂg&÷¦Vâ¢&W7VÇBÒfÆ–FFUöÆö6F÷%öVF—B†VF—BÂg&÷¦VâÂ6¶WBÂ6‡Væµö–BÂ&ÆÆVÃÕG'VR¢–FVçF—F–W2Ò²¢¦6öÖÖöå÷&W÷'Eö–FVçF—F–W2†g&÷¦VâÂ&V6öææV7B’Â&Æö6F÷%÷6¶WEöf–ÆU÷6†#Sb#¢6¶WE²'6†#Sb%×Ð¢&W÷'BÒ'V–ÆEöÆö6F÷%÷&W÷'B†g&÷¦VâÂ6‡Væµö–BÂ&W÷6—F÷'•÷7FFU²&&6Uö6öÖÖ—B%ÒÂ&V6öææV7BÂ6¶WBÂ&W7VÇBÂVF—E÷6†#Sb¢÷væW'6†—Ò²'66†VÖ÷fW'6–öâ#¢&Æö6F÷"Ö76–væÖVçB×Æâ×c"Â&6‡Væµö–B#¢6‡Væµö–BÂ&Æö6F÷%÷6¶WEöf–ÆU÷6†#Sb#¢6¶WE²'6†#Sb%ÒÂ&76–væÖVçEö–G2#¢6÷'FVB‡6¶WE²&76–væÖVçG2%Ò’Â&76–væÖVçEö6÷VçB#¢ÆVâ‡6¶WE²&76–væÖVçG2%Ò—Ð¢VF—EöæÖRÒb&Æö6F÷"ÖVF—Bç¶6‡Væµö–GÒæ§6öâ ¢VÇ6S ¢Æö6F÷%÷6WBÒÆöEöÆö6F÷%öVF—E÷6WB†&w2æÆö6F÷%öVF—BÂg&÷¦Vâ¢v÷&·6WG2Ò'V–ÆEöÖ—76–æu÷v÷&·6WG2†g&÷¦Vâ¢v÷&·6WBÒv÷&·6WG5¶6‡Væµö–EÐ¢&WV—&R†VF—BævWB‚&Ö—76–æuö66W75ö÷væW'6†—÷6†#Sb"’ÓÒv÷&·6WE²'v÷&·6WE÷6†#Sb%ÒÂ&Ö—76–æuö66W75ö÷væW'6†—öÖ—6ÖF6‚"Â%&—fFRÖ—76–ærÖ66W72VF—B—2æ÷B&÷VæBFòF†RFWFW&Ö–æ—7F–2v÷&·6WBâ"¢&W7VÇBÒfÆ–FFUöÖ—76–æuö66W75öVF—B†VF—BÂg&÷¦VâÂv÷&·6WBÂ6‡Væµö–BÂ&ÆÆVÃÕG'VRÂÆö6F÷%öVF—E÷6WE÷6†#ScÖÆö6F÷%÷6WE²'6†#Sb%Ò¢–FVçF—F–W2Ò²¢¦6öÖÖöå÷&W÷'Eö–FVçF—F–W2†g&÷¦VâÂ&V6öææV7B’Â&Ö—76–æuö66W75ö÷væW'6†—÷6†#Sb#¢v÷&·6WE²'v÷&·6WE÷6†#Sb%ÒÂ&Æö6F÷%öVF—E÷6WE÷6†#Sb#¢Æö6F÷%÷6WE²'6†#Sb%×Ð¢&W÷'BÒ'V–ÆEöÖ—76–æu÷&W÷'B†g&÷¦VâÂ6‡Væµö–BÂ&W÷6—F÷'•÷7FFU²&&6Uö6öÖÖ—B%ÒÂ&V6öææV7BÂv÷&·6WBÂÆö6F÷%÷6WBÂ&W7VÇBÂVF—BÂVF—E÷6†#Sb¢÷væW'6†—Ò²'66†VÖ÷fW'6–öâ#¢&Ö—76–ærÖ66W72Ö÷væW'6†—×Æâ×c"Â¢§v÷&·6WBÂ&Æö6F÷%öVF—E÷6WE÷6†#Sb#¢Æö6F÷%÷6WE²'6†#Sb%×Ð¢VF—EöæÖRÒb&Ö—76–ærÖ66W72ÖVF—Bç¶6‡Væµö–GÒæ§6öâ ¢V&Æ–6F–öå÷&öf–ÆRÒg&÷¦VâævWB‚'V&Æ–6F–öå÷&öf–ÆR"ÂV&Æ–6F–öå÷&öf–ÆUöf÷"†g&÷¦Vå²'7FFR%Ò’¢–bV&Æ–6F–öå÷&öf–ÆRÓÒT$Ä”5ôUdÅTD”ôåô%D”d5E3 ¢fÆ–FFU÷V&Æ–5ö6æöæ–6ÅöVF—B†VF—BÂVF—Eö¶–æBÂ6‡Væµö–B¢V&Æ–5öFö7VÖVçBÒVF—@¢V&Æ–5÷–ÆöBÒVF—E÷–Æö@¢VÇ6S ¢V&Æ–5öFö7VÖVçBÒ&W÷'@¢V&Æ–5÷–ÆöBÒ§6öåö'—FW2‡&W÷'B¢W‡V7FVE÷V&Æ–5÷F‚ÒV&Æ–5÷F…öf÷"†VF—Eö¶–æBÂ6‡Væµö–BÂV&Æ–6F–öå÷&öf–ÆR¢V&Æ–5ö÷WGWBÒF‚†&w2çV&Æ–5ö÷WGWB’ç&W6öÇfR‚¢&WV—&R‡V&Æ–5ö÷WGWBæ5÷÷6—‚‚’æVæG7v—F‚‚"ò"²W‡V7FVE÷V&Æ–5÷F‚’÷"V&Æ–5ö÷WGWBæ5÷÷6—‚‚’ÓÒW‡V7FVE÷V&Æ–5÷F‚Â'V&Æ–5ö÷WGWE÷F‚"Âb%V&Æ–2÷WGWB×W7BVæB–â¶W‡V7FVE÷V&Æ–5÷F‡Òâ"¢&V6÷fW'•÷&ö÷BÒF‚†&w2ç&V6÷fW'•÷&ö÷B’ç&W6öÇfR‚¢&V6÷fW'•÷¦—ÒF‚†&w2ç&V6÷fW'•÷¦—’ç&W6öÇfR‚’–b&w2ç&V6÷fW'•÷¦—VÇ6R&V6÷fW'•÷&ö÷Bò‚‚&Æö6F÷"ÖVF—B×v÷&¶W""–bVF—Eö¶–æBÓÒ&Æö6F÷""VÇ6R&Ö—76–ærÖ66W72×v÷&¶W""’²"×&V6÷fW'’ç¦—"¢&V6V—Eö÷WGWBÒF‚†&w2ç&V6V—Eö÷WGWB’ç&W6öÇfR‚’–b&w2ç&V6V—Eö÷WGWBVÇ6R&V6÷fW'•÷&ö÷Bò‚‚&Æö6F÷"ÖVF—B×v÷&¶W"×&V6V—Bæ§6öâ"–bVF—Eö¶–æBÓÒ&Æö6F÷""VÇ6R&Ö—76–ærÖ66W72×v÷&¶W"×&V6V—Bæ§6öâ"’¢&WV—&R†ÆVâ‡·V&Æ–5ö÷WGWBÂ&V6÷fW'•÷¦—Â&V6V—Eö÷WGWGÒ’ÓÒ2Â'v÷&¶W%ö÷WGWEö6öÆÆ—6–öâ"Â%V&Æ–2&W÷'BÂ&—fFR&V6V—BÂæB&V6÷fW'’¤•÷WGWG2×W7B&RF—7F–æ7Bâ"¢&WV—&R†æ÷BF…ö—5÷v—F†–â‡V&Æ–5ö÷WGWBÂ&V6÷fW'•÷&ö÷B’Â'&—f7•ö&÷VæF'•ö6öÆÆ—6–öâ"Â%V&Æ–26æF–FFR×&W÷6—F÷'’&W÷'B×W7B&R÷WG6–FRF†R&—fFRv÷&¶W"&V6÷fW'’&ö÷Bâ"¢&WV—&R‡F…ö—5÷v—F†–â‡&V6÷fW'•÷¦—Â&V6÷fW'•÷&ö÷B’æBF…ö—5÷v—F†–â‡&V6V—Eö÷WGWBÂ&V6÷fW'•÷&ö÷B’Â'&—f7•ö&÷VæF'•ö6öÆÆ—6–öâ"Â%&—fFR&V6÷fW'’¤•æBv÷&¶W"&V6V—B×W7B&VÖ–â&VæVF‚F†R—6öÆFVB&V6÷fW'’&ö÷Bâ"¢f÷"F‚ÂÆ&VÂ–â‚‡V&Æ–5ö÷WGWBÂ%V&Æ–2&W÷'B"’Â‡&V6V—Eö÷WGWBÂ%v÷&¶W"&V6V—B"’“ ¢&WV—&R†æ÷BF‚æW†—7G2‚’Â&÷WGWEöW†—7G2"Âb%&VgW6–ærFò÷fW'w&—FR¶Æ&VÇÓ¢·F‡Ò"¢&WV—&Uöæõ÷7–ÖÆ–æµö6ö×öæVçG2‡F‚ç&VçBÂb'¶Æ&VÇÒ&VçB"¢&V6÷fW'’Ò'V–ÆE÷&V6÷fW'’‡&V6÷fW'•÷&ö÷BÂ&V6÷fW'•÷¦—ÂVF—Eö¶–æBÂg&÷¦VâÂ6‡Væµö–BÂ–FVçF—F–W2ÂVF—EöæÖRÂVF—E÷–ÆöBÂV&Æ–5÷–ÆöBÂ÷væW'6†—¢&V6V—BÒÖ¶U÷&V6V—B€¢VF—Eö¶–æBÂg&÷¦VâÂ6‡Væµö–BÂ&ö¦V7BÂ&w2æ&6Uö'&æ6‚Â&W÷6—F÷'•÷7FFU²&&6Uö6öÖÖ—B%ÒÂv÷&¶W%ö'&æ6‚À¢–FVçF—F–W2ÂVF—EöæÖRÂVF—E÷–ÆöBÂ&W7VÇBÂ&V6÷fW'’À¢b'v÷&¶W'2÷²vÆö6F÷"ÖVF—Br–bVF—Eö¶–æBÓÒvÆö6F÷"rVÇ6RvÖ—76–ærÖ66W72ÖVF—BwÒ÷¶6‡Væµö–GÒ"ÂV&Æ–5÷–ÆöBÀ¢¢w&—FU÷V&Æ–5ö'F–f7B‡V&Æ–5ö÷WGWBÂV&Æ–5öFö7VÖVçBÂV&Æ–5÷–ÆöBÂV&Æ–6F–öå÷&öf–ÆR¢w&—FUö§6öåöFöÖ–2‡&V6V—Eö÷WGWBÂ&V6V—B¢fÆ–FFU÷&V6÷fW'•ö&6†—fR‡&V6÷fW'•÷&ö÷BÂ&V6÷fW'•÷¦—Â&V6V—B¢VÖ—B‡²&ö²#¢G'VRÂ&÷W&F–öâ#¢b&'V–ÆB×¶VF—Eö¶–æGÒ×v÷&¶W""Â&6‡Væµö–B#¢6‡Væµö–BÂ&'&æ6‚#¢v÷&¶W%ö'&æ6‚Â&&6Uö6öÖÖ—B#¢&W÷6—F÷'•÷7FFU²&&6Uö6öÖÖ—B%ÒÂ'V&Æ–6F–öå÷&öf–ÆR#¢V&Æ–6F–öå÷&öf–ÆRÂ'V&Æ–5ö'F–f7B#¢7G"‡V&Æ–5ö÷WGWB’Â'V&Æ–5÷&W÷'B#¢7G"‡V&Æ–5ö÷WGWB’Â'&V6V—B#¢7G"‡&V6V—Eö÷WGWB’Â'&V6÷fW'•ö&6†—fR#¢7G"‡&V6÷fW'•÷¦—’Â'V&Æ—6…öÆÆ÷vÆ—7B#¢¶W‡V7FVE÷V&Æ–5÷F…ÒÂ&6æöæ–6Å÷7FFU÷WFFVB#¢fÇ6WÒ  ¦FVbWf–FVæ6U÷6†#Sb‡fÇVS¢F–7E·7G"Âç•Ò’Óâ7G# ¢&WGW&â6†#Seö'—FW2†§6öâæGV×2‡fÇVRÂVç7W&Uö66–“ÔfÇ6RÂ6÷'Eö¶W—3ÕG'VRÂ6W&F÷'3Ò‚"Â"Â#¢"’’æVæ6öFR‚'WFbÓ‚"’  ¦FVbfÆ–FFU÷V&Æ–6F–öåöWf–FVæ6R€¢Wf–FVæ6S¢F–7E·7G"Âç•ÒÂ&V6V—C¢F–7E·7G"Âç•ÒÂV&Æ–5÷–ÆöC¢'—FW2À¢ÖW&vVC¢&ööÂÂ&–÷%ö÷Vã¢F–7E·7G"Âç•ÒÂæöæRÒæöæRÀ¢’ÓâF–7E·7G"Âç•Ó ¢VF—Eö¶–æBÒfÆ–FFU÷&V6V—B‡&V6V—B¢&WV—&VBÒ°¢'66†VÖ÷fW'6–öâ"Â&Wf–FVæ6U÷6÷W&6R"Â&VF—Eö¶–æB"Â&6æF–FFU÷&ö¦V7B"Â'VÆÅ÷&WVW7B"À¢'VÆÅ÷&WVW7E÷W&Â"Â'7FFR"Â&ÖW&vVB"Â&&6Uö'&æ6‚"Â&ö'6W'fVEö&6Uö†VEö6öÖÖ—B"À¢&†VEö'&æ6‚"Â&†VEö6öÖÖ—B"Â'v÷&¶W%ö&6Uö6öÖÖ—B"Â&ÖW&vUö&6Uö6öÖÖ—B"Â&6öÖÖ—Eö6÷VçB"À¢&6†ævVEöf–ÆW2"Â&ö'6W'fVEöB"À¢Ð¢–bÖW&vVC ¢&WV—&VBæFB‚&ÖW&vUö6öÖÖ—B"¢W†7Eö¶W—2†Wf–FVæ6RÂ&WV—&VBÂ$v—D‡V"V&Æ–6F–öâWf–FVæ6R"¢W‡V7FVE÷66†VÖÒÔU$tUôUd”DTä4UõdU%4”ôâ–bÖW&vVBVÇ6RõTåôUd”DTä4UõdU%4”ôà¢&WV—&R†Wf–FVæ6U²'66†VÖ÷fW'6–öâ%ÒÓÒW‡V7FVE÷66†VÖÂ'V&Æ–6F–öåöWf–FVæ6U÷66†VÖ"Âb$W‡V7FVB¶W‡V7FVE÷66†VÖÒâ"¢2Wf–FVæ6U÷6÷W&6R—2–çFVçF–öæÆÇ’öæÇ’f÷&ÖBF—67&–Ö–æF÷"âWF†VçF–6F–öà¢2&VÆöæw2FòF†R÷&6†W7G&F÷"F†B6GW&W2F†—2F—&V7Bv—D‡V"’6æ6†÷Bà¢&WV—&R†Wf–FVæ6U²&Wf–FVæ6U÷6÷W&6R%ÒÓÒ&v—F‡V%ö’"Â'V&Æ–6F–öåöWf–FVæ6U÷6÷W&6R"Â$v—D‡V"Wf–FVæ6R×W7B†fRF—&V7B’6†Râ"¢&W÷6—F÷&–W2Ò&V6V—E²'&W÷6—F÷&–W2%Ð¢&WV—&R†Wf–FVæ6U²&VF—Eö¶–æB%ÒÓÒ6W&–Æ—¦VEöVF—Eö¶–æB†VF—Eö¶–æB’Â'V&Æ–6F–öåöWf–FVæ6Uö¶–æB"Â$v—D‡V"Wf–FVæ6RVF—B¶–æBF–ffW'2g&öÒ&V6V—Bâ"¢&WV—&R†Wf–FVæ6U²&6æF–FFU÷&ö¦V7B%ÒÓÒ&W÷6—F÷&–W5²&6æF–FFU÷&ö¦V7B%ÒÂ'V&Æ–6F–öå÷&ö¦V7EöÖ—6ÖF6‚"Â$v—D‡V"Wf–FVæ6RæÖW2F–ffW&VçB6æF–FFR&ö¦V7Bâ"¢&WV—&R†Wf–FVæ6U²&&6Uö'&æ6‚%ÒÓÒ&W÷6—F÷&–W5²&6æF–FFUö&6Uö'&æ6‚%ÒÂ'V&Æ–6F–öåö&6UöÖ—6ÖF6‚"Â$v—D‡V"Wf–FVæ6RF&vWG2F–ffW&VçB&6R'&æ6‚â"¢&WV—&R†Wf–FVæ6U²&†VEö'&æ6‚%ÒÓÒ&W÷6—F÷&–W5²'v÷&¶W%ö'&æ6‚%ÒÂ'V&Æ–6F–öåö'&æ6…öÖ—6ÖF6‚"Â$v—D‡V"Wf–FVæ6RæÖW2F–ffW&VçBv÷&¶W"'&æ6‚â"¢v÷&¶W%ö&6RÒ&W÷6—F÷&–W5²&–Ö×WF&ÆU÷v÷&¶W%ö&6Uö6öÖÖ—B%Ð¢&WV—&R‡&WV—&Uö6öÖÖ—B†Wf–FVæ6U²'v÷&¶W%ö&6Uö6öÖÖ—B%ÒÂ'V&Æ–6F–öåöWf–FVæ6Rçv÷&¶W%ö&6Uö6öÖÖ—B"’ÓÒv÷&¶W%ö&6RÂ'V&Æ–6F–öåö&6UöÖ—6ÖF6‚"Â%v÷&¶W"&6R6öÖÖ—BF–ffW'2g&öÒ&V6V—Bâ"¢&WV—&R‡&WV—&Uö6öÖÖ—B†Wf–FVæ6U²&ÖW&vUö&6Uö6öÖÖ—B%ÒÂ'V&Æ–6F–öåöWf–FVæ6RæÖW&vUö&6Uö6öÖÖ—B"’ÓÒv÷&¶W%ö&6RÂ'V&Æ–6F–öåö&6UöÖ—6ÖF6‚"Â%"ÖW&vR&6RF–ffW'2g&öÒ–Ö×WF&ÆRv÷&¶W"&6Râ"¢2F†Rö'6W'fVBF&vWB†VBÖ’Gfæ6R2V&Æ–W"W‡Æ–6—B&F6†W2ÖW&vRà¢2v÷&¶W"æ6W7G'’&VÖ–ç2g&÷¦Vâ'’v÷&¶W%ö&6Uö6öÖÖ—BæBÖW&vUö&6Uö6öÖÖ—C°¢2&–æF–ærF&vWBÖ†VBWVÆ—G’†W&Rv÷VÆBÖ¶R6öÆÆ—6–öâ×6fR&F6†W2–×÷76–&ÆRà¢&WV—&Uö6öÖÖ—B†Wf–FVæ6U²&ö'6W'fVEö&6Uö†VEö6öÖÖ—B%ÒÂ'V&Æ–6F–öåöWf–FVæ6Ræö'6W'fVEö&6Uö†VEö6öÖÖ—B"¢&WV—&Uö6öÖÖ—B†Wf–FVæ6U²&†VEö6öÖÖ—B%ÒÂ'V&Æ–6F–öåöWf–FVæ6Ræ†VEö6öÖÖ—B"¢–bÖW&vVC ¢&WV—&R†Wf–FVæ6U²'7FFR%ÒÓÒ&6Æ÷6VB"æBWf–FVæ6U²&ÖW&vVB%Ò—2G'VRÂ'VÆÅ÷&WVW7Eöæ÷EöÖW&vVB"Â$g&W6‚Wf–FVæ6RFöW2æ÷B6†÷rÖW&vVBVÆÂ&WVW7Bâ"¢&WV—&Uö6öÖÖ—B†Wf–FVæ6U²&ÖW&vUö6öÖÖ—B%ÒÂ'V&Æ–6F–öåöWf–FVæ6RæÖW&vUö6öÖÖ—B"¢VÇ6S ¢&WV—&R†Wf–FVæ6U²'7FFR%ÒÓÒ&÷Vâ"æBWf–FVæ6U²&ÖW&vVB%Ò—2fÇ6RÂ'VÆÅ÷&WVW7Eöæ÷Eö÷Vâ"Â$g&W6‚Wf–FVæ6RFöW2æ÷B6†÷râ÷VâÂVæÖW&vVBVÆÂ&WVW7Bâ"¢&WV—&R†Wf–FVæ6U²&6öÖÖ—Eö6÷VçB%ÒÓÒÂ'V&Æ–6F–öåö6öÖÖ—Eö6÷VçB"Â%v÷&¶W"'&æ6‚×W7B6öçF–âW†7FÇ’öæR6öÖÖ—Bâ"¢VÆÅ÷&WVW7BÒWf–FVæ6U²'VÆÅ÷&WVW7B%Ð¢&WV—&R†—6–ç7Fæ6R‡VÆÅ÷&WVW7BÂ–çB’æBæ÷B—6–ç7Fæ6R‡VÆÅ÷&WVW7BÂ&ööÂ’æBVÆÅ÷&WVW7BâÂ'V&Æ–6F–öå÷""Â%VÆÂ×&WVW7BçVÖ&W"—2–çfÆ–Bâ"¢W‡V7FVE÷W&ÂÒb&‡GG3¢òöv—F‡V"æ6öÒ÷·&W÷6—F÷&–W5²v6æF–FFU÷&ö¦V7Bu×Ò÷VÆÂ÷·VÆÅ÷&WVW7GÒ ¢&WV—&R†Wf–FVæ6U²'VÆÅ÷&WVW7E÷W&Â%ÒÓÒW‡V7FVE÷W&ÂÂ'V&Æ–6F–öå÷%÷W&Â"Â%VÆÂ×&WVW7BU$ÂFöW2æ÷BÖF6‚&ö¦V7BæBçVÖ&W"â"¢6†ævVBÒWf–FVæ6U²&6†ævVEöf–ÆW2%Ð¢&WV—&R†—6–ç7Fæ6R†6†ævVBÂÆ—7B’æBÆVâ†6†ævVB’ÓÒæB—6–ç7Fæ6R†6†ævVE³ÒÂF–7B’æB6WB†6†ævVE³Ò’ÓÒ²'F‚"Â&&Æö%÷6†"Â&f–ÆU÷6†#Sb'ÒÂ'V&Æ–6F–öåöÆÆ÷vÆ—7B"Â%v÷&¶W""×W7B6†ævRW†7FÇ’öæR&VwVÆ"&W÷'Bf–ÆRâ"¢f–ÆU÷&V6÷&BÒ6†ævVE³Ð¢&WV—&R†f–ÆU÷&V6÷&E²'F‚%ÒÓÒ&W÷6—F÷&–W5²'V&Æ–5÷&W÷'E÷F‚%ÒÂ'V&Æ–6F–öåöÆÆ÷vÆ—7B"Â%v÷&¶W""6†ævW2âVæW‡V7FVBV&Æ–2F‚â"¢V&Æ–5öf–ÆU÷6†Ò6†#Seö'—FW2‡V&Æ–5÷–ÆöB¢&WV—&R†f–ÆU÷&V6÷&E²&f–ÆU÷6†#Sb%ÒÓÒV&Æ–5öf–ÆU÷6†ÓÒ&V6V—E²'V&Æ–5÷&ö¦V7F–öâ%Õ²'6†#Sb%ÒÂ'V&Æ–6F–öåöf–ÆUöÖ—6ÖF6‚"Â%V&Æ—6†VB&W÷'B'—FW2F–ffW"g&öÒ&V6V—B÷V&Æ–2&ö¦V7F–öââ"¢&Æö%÷6†Ò7G"†f–ÆU÷&V6÷&E²&&Æö%÷6†%Ò’æÆ÷vW"‚¢&WV—&R†&ööÂ‡&RægVÆÆÖF6‚‡"%¶ÖcÓ•×³C×Å¶ÖcÓ•×³cGÒ"Â&Æö%÷6†’’Â'V&Æ–6F–öåö&Æö""Â%V&Æ—6†VBv—B&Æö"–FVçF—G’—2–çfÆ–Bâ"¢&WV—&R†v—Eö&Æö%÷6†ö'—FW2‡V&Æ–5÷–ÆöBÂ&Æö%÷6†’ÓÒ&Æö%÷6†Â'V&Æ–6F–öåö&Æö%öÖ—6ÖF6‚"Â%V&Æ—6†VBv—B&Æö"FöW2æ÷BÖF6‚W†7BV&Æ–2&W÷'B'—FW2â"¢ö'6W'fVEöBÒ&WV—&U÷F–ÖW7F×†Wf–FVæ6U²&ö'6W'fVEöB%ÒÂ'V&Æ–6F–öåöWf–FVæ6Ræö'6W'fVEöB"¢–b&–÷%ö÷Vâ—2æ÷BæöæS ¢&WV—&R†Wf–FVæ6U²'VÆÅ÷&WVW7B%ÒÓÒ&–÷%ö÷VâævWB‚'VÆÅ÷&WVW7B"’æBWf–FVæ6U²&†VEö6öÖÖ—B%ÒÓÒ&–÷%ö÷VâævWB‚&†VEö6öÖÖ—B"’Â&ÖW&vUöWf–FVæ6Uö–FVçF—G’"Â$ÖW&vVBWf–FVæ6RFöW2æ÷B–FVçF–g’F†R6ÖR"ö†VB6öÖÖ—Bâ"¢&WV—&R†Wf–FVæ6U²&6†ævVEöf–ÆW2%ÒÓÒ&–÷%ö÷VâævWB‚&6†ævVEöf–ÆW2"’Â&ÖW&vUöWf–FVæ6Uö–FVçF—G’"Â$ÖW&vVBWf–FVæ6R6†ævVBF†R&Wf–WvVBf–ÆR–FVçF—G’â"¢&WV—&R†ö'6W'fVEöBãÒ&WV—&U÷F–ÖW7F×‡&–÷%ö÷VâævWB‚&ö'6W'fVEöB"’Â&÷Vå÷%öWf–FVæ6Ræö'6W'fVEöB"’Â&ÖW&vUöWf–FVæ6Uö6‡&öæöÆöw’"Â$ÖW&vVBWf–FVæ6R&VFFW2÷VâÕ"Wf–FVæ6Râ"¢&WGW&â²&VF—Eö¶–æB#¢VF—Eö¶–æBÂ&6‡Væµö–B#¢&V6V—E²&6‡Væ²%Õ²&6‡Væµö–B%ÒÂ&Wf–FVæ6U÷6†#Sb#¢Wf–FVæ6U÷6†#Sb†Wf–FVæ6R’Â&ö'6W'fVEöB#¢ö'6W'fVEöGÐ  ¦FVb6öÖÖæE÷fÆ–FFU÷V&Æ–2†&w3¢&w'6RäæÖW76R’ÓâæöæS ¢Fö7VÖVçBÂ–ÆöBÂf–ÆU÷6†ÒÆöEö§6öå÷6æ6†÷B…F‚†&w2ç&W÷'B’ç&W6öÇfR‚’Â%V&Æ–2v÷&¶W"'F–f7B"¢W‡V7FVBÒ&w2æVF—Eö¶–æ@¢–bW‡V7FVB—2æöæS ¢W‡V7FVBÒ&Æö6F÷""–bFö7VÖVçBævWB‚'66†VÖ÷fW'6–öâ"’–â´Äô4Dõ%ôTD•EõdU%4”ôâÂÄô4Dõ%õ$Uõ%EõdU%4”ôçÒVÇ6R&Ö—76–æuö66W72 ¢6‡Væµö–BÒ&w2æ6‡Væµö–B÷"Fö7VÖVçBævWB‚&6‡Væµö–B"¢6‡Væµö–BÒfÆ–FFUö6‡Væµö–B†6‡Væµö–B¢&öf–ÆRÒ&w2çV&Æ–6F–öå÷&öf–ÆP¢–b&öf–ÆR—2æöæRæB&w2æW‡V7FVE÷Fƒ ¢&öf–ÆRÒV&Æ–6F–öå÷&öf–ÆUög&öÕ÷F‚†W‡V7FVBÂ6‡Væµö–BÂ6fU÷&VÆF—fU÷F‚†&w2æW‡V7FVE÷F‚’¢–b&öf–ÆR—2æöæS ¢&öf–ÆRÒT$Ä”5ôUdÅTD”ôåô%D”d5E2–bFö7VÖVçBævWB‚'66†VÖ÷fW'6–öâ"’–â´Äô4Dõ%ôTD•EõdU%4”ôâÂÔ•54”äuôTD•EõdU%4”ôçÒVÇ6Rtu$TtDUôôäÅ¢&W7VÇBÒfÆ–FFU÷V&Æ–5ö'F–f7B†Fö7VÖVçBÂW‡V7FVBÂ6‡Væµö–BÂ&öf–ÆR¢–b&w2æW‡V7FVE÷Fƒ ¢&WV—&R‡6fU÷&VÆF—fU÷F‚†&w2æW‡V7FVE÷F‚’ÓÒV&Æ–5÷F…öf÷"†W‡V7FVBÂ6‡Væµö–BÂ&öf–ÆR’Â'V&Æ–5ö÷WGWE÷F‚"Â$W‡V7FVBV&Æ–2F‚—2æ÷BF†RW†7BÆÆ÷vÆ—7FVBF‚â"¢VÖ—B‡²&ö²#¢G'VRÂ&÷W&F–öâ#¢'fÆ–FFR×V&Æ–2"Â'V&Æ–6F–öå÷&öf–ÆR#¢&öf–ÆRÂ¢§&W7VÇBÂ&f–ÆU÷6†#Sb#¢f–ÆU÷6†Â&'—FUöÆVæwF‚#¢ÆVâ‡–ÆöB—Ò  ¦FVb6öÖÖæE÷fÆ–FFU÷v÷&¶W"†&w3¢&w'6RäæÖW76R’ÓâæöæS ¢&V6V—E÷F‚ÒF‚†&w2ç&V6V—B’ç&W6öÇfR‚¢V&Æ–5÷F‚ÒF‚†&w2çV&Æ–5÷&W÷'B’ç&W6öÇfR‚¢&V6V—BÂòÂòÒÆöEö§6öå÷6æ6†÷B‡&V6V—E÷F‚Â%&—fFRv÷&¶W"&V6V—B"¢VF—Eö¶–æBÒfÆ–FFU÷&V6V—B‡&V6V—BÂ&w2æVF—Eö¶–æB¢6‡Væµö–BÒ&V6V—E²&6‡Væ²%Õ²&6‡Væµö–B%Ð¢&öf–ÆRÒV&Æ–6F–öå÷&öf–ÆUög&öÕ÷F‚†VF—Eö¶–æBÂ6‡Væµö–BÂ&V6V—E²'V&Æ–5÷&ö¦V7F–öâ%Õ²'F‚%Ò¢V&Æ–5öFö7VÖVçBÂV&Æ–5÷–ÆöBÂV&Æ–5÷6†ÒÆöEö§6öå÷6æ6†÷B‡V&Æ–5÷F‚Â%V&Æ–2v÷&¶W"'F–f7B"¢&W7VÇBÒfÆ–FFU÷V&Æ–5ö'F–f7B‡V&Æ–5öFö7VÖVçBÂVF—Eö¶–æBÂ6‡Væµö–BÂ&öf–ÆR¢&WV—&R‡V&Æ–5÷6†ÓÒ&V6V—E²'V&Æ–5÷&ö¦V7F–öâ%Õ²'6†#Sb%ÒÂ'V&Æ–5÷&ö¦V7F–öåö†6…öÖ—6ÖF6‚"Â%V&Æ–2'F–f7Bf–ÆR†6‚F–ffW'2g&öÒ&V6V—Bâ"¢–b&öf–ÆRÓÒtu$TtDUôôäÅ“ ¢&WV—&R‡V&Æ–5öFö7VÖVçE²'&—fFUö'F–f7E÷6†#Sb%ÒÓÒ&V6V—E²'&—fFUö'F–f7B%Õ²'6†#Sb%ÒÂ'&—fFU÷V&Æ–5ö&–æF–æuöÖ—6ÖF6‚"Â%V&Æ–2&W÷'B—2æ÷B&÷VæBFòF†R&V6V—Bw2&—fFR'F–f7Bâ"¢VÇ6S ¢&WV—&R‡V&Æ–5÷6†ÓÒ&V6V—E²'&—fFUö'F–f7B%Õ²'6†#Sb%ÒÂ'&—fFU÷V&Æ–5ö&–æF–æuöÖ—6ÖF6‚"Â%V&Æ—6†VB6æöæ–6ÂVF—B—2æ÷BF†RW†7BfÆ–FFVBVF—B&÷VæB'’F†R&V6V—Bâ"¢&ö÷BÒF‚†&w2ç&V6÷fW'•÷&ö÷B’ç&W6öÇfR‚¢&6†—fRÒF‚†&w2ç&V6÷fW'•÷¦—’ç&W6öÇfR‚’–b&w2ç&V6÷fW'•÷¦—VÇ6R&ö÷Bò&V6V—E²'&—fFU÷&V6÷fW'’%Õ²&&6†—fU÷F‚%Ð¢&V6÷fW'’ÒfÆ–FFU÷&V6÷fW'•ö&6†—fR‡&ö÷BÂ&6†—fRÂ&V6V—B¢ÖWFFFÒ&V6÷fW'•²&ÖWFFF%Ð¢&WV—&R†ÖWFFF²&VF—Eö¶–æB%ÒÓÒ&V6V—E²&VF—Eö¶–æB%ÒæBÖWFFF²&6‡Væµö–B%ÒÓÒ&V6V—E²&6‡Væ²%Õ²&6‡Væµö–B%ÒÂ'&V6÷fW'•÷&V6V—Eö–FVçF—G’"Â%&V6÷fW'’ÖWFFFF–ffW'2g&öÒ&V6V—Bâ"¢&—fFU÷&V6÷&G2Ò¶—FVÒf÷"—FVÒ–âÖWFFF²&'F–f7G2%Ò–b—FVÒævWB‚&'F–f7B"’ÓÒ'&—fFUöVF—B%Ð¢&WV—&R†ÆVâ‡&—fFU÷&V6÷&G2’ÓÒæB&—fFU÷&V6÷&G5³Õ²'6†#Sb%ÒÓÒ&V6V—E²'&—fFUö'F–f7B%Õ²'6†#Sb%ÒÂ'&V6÷fW'•÷&—fFUö'F–f7EöÖ—6ÖF6‚"Â%&V6÷fW'’&6†—fR—2æ÷B&÷VæBFòF†RW†7B&—fFRVF—Bâ"¢VÖ—B‡²&ö²#¢G'VRÂ&÷W&F–öâ#¢'fÆ–FFR×v÷&¶W""Â&VF—Eö¶–æB#¢VF—Eö¶–æBÂ&6‡Væµö–B#¢&W7VÇE²&6‡Væµö–B%ÒÂ'V&Æ–6F–öå÷&öf–ÆR#¢&öf–ÆRÂ'&V6V—E÷6†#Sb#¢&V6V—E²'&V6V—E÷6†#Sb%ÒÂ'V&Æ–5öf–ÆU÷6†#Sb#¢V&Æ–5÷6†Â'&V6÷fW'•÷6†#Sb#¢&V6÷fW'•²&&6†—fU÷6†#Sb%×Ò  ¦FVb6öÖÖæEö&–æE÷V&Æ–6F–öâ†&w3¢&w'6RäæÖW76R’ÓâæöæS ¢&V6V—E÷F‚ÒF‚†&w2ç&V6V—B’ç&W6öÇfR‚¢&W÷'E÷F‚ÒF‚†&w2çV&Æ–5÷&W÷'B’ç&W6öÇfR‚¢Wf–FVæ6U÷F‚ÒF‚†&w2çV&Æ–6F–öåöWf–FVæ6R’ç&W6öÇfR‚¢÷WGWBÒF‚†&w2æ÷WGWB’ç&W6öÇfR‚¢&WV—&R†æ÷B÷WGWBæW†—7G2‚’Â&÷WGWEöW†—7G2"Âb%&VgW6–ærFò÷fW'w&—FR¶÷WGWGÒâ"¢&V6V—BÂòÂ&V6V—Eöf–ÆU÷6†ÒÆöEö§6öå÷6æ6†÷B‡&V6V—E÷F‚Â%&—fFRv÷&¶W"&V6V—B"¢VF—Eö¶–æBÒfÆ–FFU÷&V6V—B‡&V6V—B¢6‡Væµö–BÒ&V6V—E²&6‡Væ²%Õ²&6‡Væµö–B%Ð¢&öf–ÆRÒV&Æ–6F–öå÷&öf–ÆUög&öÕ÷F‚†VF—Eö¶–æBÂ6‡Væµö–BÂ&V6V—E²'V&Æ–5÷&ö¦V7F–öâ%Õ²'F‚%Ò¢V&Æ–5öFö7VÖVçBÂV&Æ–5÷–ÆöBÂV&Æ–5öf–ÆU÷6†ÒÆöEö§6öå÷6æ6†÷B‡&W÷'E÷F‚Â%V&Æ–2v÷&¶W"'F–f7B"¢fÆ–FFU÷V&Æ–5ö'F–f7B‡V&Æ–5öFö7VÖVçBÂVF—Eö¶–æBÂ6‡Væµö–BÂ&öf–ÆR¢&WV—&R‡V&Æ–5öf–ÆU÷6†ÓÒ&V6V—E²'V&Æ–5÷&ö¦V7F–öâ%Õ²'6†#Sb%ÒÂ'V&Æ–5÷&ö¦V7F–öåö†6…öÖ—6ÖF6‚"Â%V&Æ–2'F–f7BF–ffW'2g&öÒ&V6V—Bâ"¢Wf–FVæ6RÂòÂWf–FVæ6Uöf–ÆU÷6†ÒÆöEö§6öå÷6æ6†÷B†Wf–FVæ6U÷F‚Â$7W'&VçBÖGFV×B÷VâÕ"Wf–FVæ6R"¢Wf–FVæ6U÷&W7VÇBÒfÆ–FFU÷V&Æ–6F–öåöWf–FVæ6R†Wf–FVæ6RÂ&V6V—BÂV&Æ–5÷–ÆöBÂÖW&vVCÔfÇ6R¢&V6÷fW'•÷&ö÷BÒF‚†&w2ç&V6÷fW'•÷&ö÷B’ç&W6öÇfR‚¢&V6÷fW'•÷¦—ÒF‚†&w2ç&V6÷fW'•÷¦—’ç&W6öÇfR‚’–b&w2ç&V6÷fW'•÷¦—VÇ6R&V6÷fW'•÷&ö÷Bò&V6V—E²'&—fFU÷&V6÷fW'’%Õ²&&6†—fU÷F‚%Ð¢&V6÷fW'’ÒfÆ–FFU÷&V6÷fW'•ö&6†—fR‡&V6÷fW'•÷&ö÷BÂ&V6÷fW'•÷¦—Â&V6V—B¢–b&w2ç6VÆV7F–öã ¢6VÆV7F–öâÒ'6U÷6VÆV7F–öâ†&w2ç6VÆV7F–öâÂ&V6V—E²'&W÷6—F÷&–W2%Õ²&6æF–FFU÷&ö¦V7B%ÒÂVF—Eö¶–æB¢–b6VÆV7F–öå²'G—R%ÒÓÒ&'&æ6‚# ¢&WV—&R‡6VÆV7F–öå²&'&æ6‚%ÒÓÒ&V6V—E²'&W÷6—F÷&–W2%Õ²'v÷&¶W%ö'&æ6‚%ÒÂ&&–æF–æu÷6VÆV7F–öâ"Â%6VÆV7FVB'&æ6‚F–ffW'2g&öÒ&V6V—BöWf–FVæ6R†VB'&æ6‚â"¢VÇ6S ¢&WV—&R‡6VÆV7F–öå²'VÆÅ÷&WVW7B%ÒÓÒWf–FVæ6U²'VÆÅ÷&WVW7B%ÒÂ&&–æF–æu÷6VÆV7F–öâ"Â%6VÆV7FVB"F–ffW'2g&öÒWf–FVæ6Râ"¢VÇ6S ¢6VÆV7F–öâÒ²'G—R#¢'VÆÅ÷&WVW7B"Â'VÆÅ÷&WVW7B#¢Wf–FVæ6U²'VÆÅ÷&WVW7B%ÒÂ'VÆÅ÷&WVW7E÷W&Â#¢Wf–FVæ6U²'VÆÅ÷&WVW7E÷W&Â%×Ð¢&–æF–ærÒ°¢'66†VÖ÷fW'6–öâ#¢$”äD”äuõdU%4”ôâÀ¢&VF—Eö¶–æB#¢&V6V—E²&VF—Eö¶–æB%ÒÀ¢&6æF–FFU÷&ö¦V7B#¢&V6V—E²'&W÷6—F÷&–W2%Õ²&6æF–FFU÷&ö¦V7B%ÒÀ¢'6VÆV7F–öâ#¢6VÆV7F–öâÀ¢'&V6V—B#¢²'F‚#¢7G"‡&V6V—E÷F‚’Â'6†#Sb#¢&V6V—Eöf–ÆU÷6†ÒÀ¢'&V6÷fW'’#¢²'&ö÷B#¢7G"‡&V6÷fW'•÷&ö÷B’Â&&6†—fU÷F‚#¢7G"‡&V6÷fW'•÷¦—’Â&&6†—fU÷6†#Sb#¢&V6÷fW'•²&&6†—fU÷6†#Sb%×ÒÀ¢'V&Æ–5÷&W÷'B#¢²'F‚#¢7G"‡&W÷'E÷F‚’Â'6†#Sb#¢V&Æ–5öf–ÆU÷6†ÒÀ¢&÷Vå÷%öWf–FVæ6R#¢²'F‚#¢7G"†Wf–FVæ6U÷F‚’Â'6†#Sb#¢Wf–FVæ6Uöf–ÆU÷6†ÒÀ¢Ð¢w&—FUö§6öåöFöÖ–2†÷WGWBÂ&–æF–ær¢VÖ—B‡²&ö²#¢G'VRÂ&÷W&F–öâ#¢&&–æB×V&Æ–6F–öâ"Â&&–æF–ær#¢7G"†÷WGWB’Â&VF—Eö¶–æB#¢VF—Eö¶–æBÂ&6‡Væµö–B#¢6‡Væµö–BÂ'V&Æ–6F–öå÷&öf–ÆR#¢&öf–ÆRÂ'VÆÅ÷&WVW7B#¢Wf–FVæ6U²'VÆÅ÷&WVW7B%ÒÂ'&V6V—E÷6†#Sb#¢&V6V—E²'&V6V—E÷6†#Sb%ÒÂ&÷VåöWf–FVæ6U÷6†#Sb#¢Wf–FVæ6U÷&W7VÇE²&Wf–FVæ6U÷6†#Sb%ÒÂ'&V6÷fW'•÷&ö÷EöW‡Æ–6—B#¢G'VWÒ  ¦FVb&W6öÇfUö&÷VæE÷F‚†&–æF–æu÷Fƒ¢F‚ÂfÇVS¢ç’Âf–VÆC¢7G"’ÓâFƒ ¢&WV—&R†—6–ç7Fæ6R‡fÇVRÂ7G"’æB&ööÂ‡fÇVR’Â&&–æF–æu÷F‚"Âb'¶f–VÆGÒ×W7BW‡Æ–6—FÇ’–FVçF–g’öæRF‚â"¢6æF–FFRÒF‚‡fÇVR¢&WGW&â6æF–FFRç&W6öÇfR‚’–b6æF–FFRæ—5ö'6öÇWFR‚’VÇ6R†&–æF–æu÷F‚ç&VçBò6æF–FFR’ç&W6öÇfR‚  ¦FVbÆöEöf–ÆUö&–æF–ær†&–æF–æu÷Fƒ¢F‚Â&V6÷&C¢ç’Âf–VÆC¢7G"’ÓâGWÆU¶F–7E·7G"Âç•ÒÂ'—FW2Â7G"ÂF…Ó ¢&WV—&R†—6–ç7Fæ6R‡&V6÷&BÂF–7B’æB6WB‡&V6÷&B’ÓÒ²'F‚"Â'6†#Sb'ÒÂ&&–æF–æu÷6†R"Âb'¶f–VÆGÒ×W7B6öçF–âF‚æB6†#SböæÇ’â"¢F‚Ò&W6öÇfUö&÷VæE÷F‚†&–æF–æu÷F‚Â&V6÷&E²'F‚%ÒÂb'¶f–VÆGÒçF‚"¢Fö7VÖVçBÂ–ÆöBÂF–vW7BÒÆöEö§6öå÷6æ6†÷B‡F‚Âf–VÆB¢&WV—&R†F–vW7BÓÒ&WV—&U÷6†#Sb‡&V6÷&E²'6†#Sb%ÒÂb'¶f–VÆGÒç6†#Sb"’Â&&–æF–æuöf–ÆUö†6…öÖ—6ÖF6‚"Âb'¶f–VÆGÒ'—FW2F–ffW"g&öÒW‡Æ–6—B&–æF–ærâ"¢&WGW&âFö7VÖVçBÂ–ÆöBÂF–vW7BÂF€  ¦FVb'6U÷6VÆV7F–öâ‡fÇVS¢7G"Â&ö¦V7C¢7G"ÂVF—Eö¶–æC¢7G"’ÓâF–7E·7G"Âç•Ó ¢ÖF6‚Ò&RægVÆÆÖF6‚‡"&‡GG3¢òöv—F‡V%Âæ6öÒò…µâõÒ²õµâõÒ²’÷VÆÂò…³Ó•Õ³Ó•Ò¢’"ÂfÇVR¢–bÖF6ƒ ¢&WV—&R†ÖF6‚æw&÷Wƒ’æ66VföÆB‚’ÓÒ&ö¦V7Bæ66VföÆB‚’Â'6VÆV7F–öå÷&ö¦V7EöÖ—6ÖF6‚"Â%6VÆV7FVBVÆÂ&WVW7B&VÆöæw2FòF–ffW&VçB&ö¦V7Bâ"¢&WGW&â²'G—R#¢'VÆÅ÷&WVW7B"Â'VÆÅ÷&WVW7B#¢–çB†ÖF6‚æw&÷Wƒ"’’Â'VÆÅ÷&WVW7E÷W&Â#¢fÇVWÐ¢&WV—&R‡fÇVRç7F'G7v—F‚‚‚&Æö6F÷"ÖVF—Bò"–bVF—Eö¶–æBÓÒ&Æö6F÷""VÇ6R&Ö—76–ærÖ66W72ÖVF—Bò"’’Â'6VÆV7F–öåö–çfÆ–B"Â%6VÆV7F–öâ×W7B&RâW‡Æ–6—B"U$Â÷"VF—BÖ¶–æBv÷&¶W"'&æ6‚â"¢&WGW&â²'G—R#¢&'&æ6‚"Â&'&æ6‚#¢fÇVWÐ  ¦FVb6æöæ–6Åö6æF–FFU÷&VçB†g&÷¦Vã¢F–7E·7G"Âç•Ò’ÓâFƒ ¢æ÷&ÖÆ—¦VBÒg&÷¦Vå²'7FFR%ÒævWB‚&6æF–FFR"Â·Ò’ævWB‚&æ÷&ÖÆ—¦VE÷F‚"¢&WV—&R†—6–ç7Fæ6R†æ÷&ÖÆ—¦VBÂ7G"’Â&6æF–FFU÷7FFU÷6†R"Â%7FFR6æF–FFRææ÷&ÖÆ—¦VE÷F‚—2&WV—&VBâ"¢&WGW&â&W6öÇfUöÖæ–fW7E÷F‚†g&÷¦Vå²'&ö÷B%ÒÂæ÷&ÖÆ—¦VB’ç&Vç@  ¦FVb6æöæ–6Å÷v÷&¶W%÷F‡2†g&÷¦Vã¢F–7E·7G"Âç•ÒÂVF—Eö¶–æC¢7G"Â6‡Væµö–C¢7G"’ÓâF–7E·7G"ÂF…Ó ¢&VçBÒ6æöæ–6Åö6æF–FFU÷&VçB†g&÷¦Vâ¢F—&V7F÷'’Ò&VçBò‚&Æö6F÷"ÖVF—G2"–bVF—Eö¶–æBÓÒ&Æö6F÷""VÇ6R&Ö—76–ærÖ66W72ÖVF—G2"¢7FVÒÒ&Æö6F÷"ÖVF—B"–bVF—Eö¶–æBÓÒ&Æö6F÷""VÇ6R&Ö—76–ærÖ66W72ÖVF—B ¢&WGW&â°¢&VF—B#¢F—&V7F÷'’òb'·7FV×Òç¶6‡Væµö–GÒçcæ§6öâ"À¢'&V6V—B#¢F—&V7F÷'’ò'&÷fVææ6R"òb'·7FV×Ò×v÷&¶W"×&V6V—Bç¶6‡Væµö–GÒæ§6öâ"À¢&÷VåöWf–FVæ6R#¢F—&V7F÷'’ò'&÷fVææ6R"òb'·7FV×ÒÖ÷Vâ×"ÖWf–FVæ6Rç¶6‡Væµö–GÒæ§6öâ"À¢&ÖW&vUöWf–FVæ6R#¢F—&V7F÷'’ò'&÷fVææ6R"òb'·7FV×ÒÖÖW&vRÖWf–FVæ6Rç¶6‡Væµö–GÒæ§6öâ"À¢'V&Æ–5÷&W÷'B#¢F—&V7F÷'’ò'&÷fVææ6R"òb'·7FV×Ò×V&Æ–2×&W÷'Bç¶6‡Væµö–GÒæ§6öâ"À¢Ð  ¦FVb6ö÷&F–æF÷%ö–FVçF—G•÷7V'6WB†g&÷¦Vã¢F–7E·7G"Âç•Ò’ÓâF–7E·7G"Âç•Ó ¢&WGW&â°¢'6÷W&6U÷6†#Sb#¢g&÷¦Vå²&–FVçF—F–W2%Õ²'6÷W&6U÷6†#Sb%ÒÀ¢&6æF–FFU÷6†#Sb#¢g&÷¦Vå²&6æF–FFU÷6†#Sb%ÒÀ¢&&Væ6†Ö&µ÷6†#Sb#¢g&÷¦Vå²&&Væ6†Ö&²%Õ²&&Væ6†Ö&µ÷6†#Sb%ÒÀ¢&&Væ6†Ö&µöÆö6µ÷6†#Sb#¢g&÷¦Vå²&&Væ6†Ö&µöÆö6²%Õ²&Æö6µ÷6†#Sb%ÒÀ¢'öÆ–7•÷6†#Sb#¢g&÷¦Vå²'öÆ–7’%Õ²'öÆ–7•÷6†#Sb%ÒÀ¢'vUöÖ÷6†#Sb#¢g&÷¦Vå²'vUöÖ%Õ²'vUöÖ÷6†#Sb%ÒÀ¢&6‡VæµöÖæ–fW7E÷6†#Sb#¢g&÷¦Vå²&6‡VæµöÖæ–fW7B%Õ²&6‡VæµöÖæ–fW7E÷6†#Sb%ÒÀ¢&æ÷&ÖÆ—¦VEö6æF–FFUöf–ÆU÷6†#Sb#¢g&÷¦Vå²&6æF–FFUöf–ÆU÷6†#Sb%ÒÀ¢&—FVÕö–çfVçF÷'•öf–ÆU÷6†#Sb#¢g&÷¦Vå²&–çfVçF÷'•öf–ÆU÷6†#Sb%ÒÀ¢Ð  ¦FVbÆöE÷6¶WE÷6WB‡F‡3¢Æ—7E·7G%ÒÂg&÷¦Vã¢F–7E·7G"Âç•Ò’ÓâF–7E·7G"Âç•Ó ¢&WV—&R†&ööÂ‡F‡2’Â&Æö6F÷%÷6¶WE÷6WE÷&WV—&VB"Â$6ö÷&F–æF÷"&WV—&W2âW‡Æ–6—BÆö6F÷"6¶WBf÷"WfW'’g&÷¦Vâ6‡Væ²â"¢6¶WG3¢F–7E·7G"ÂF–7E·7G"Âç•ÕÒÒ·Ð¢&V6÷&G3¢Æ—7E¶F–7E·7G"Âç•ÕÒÒµÐ¢Æö6F÷%ö–G3¢Æ—7E·7G%ÒÒµÐ¢f÷"&u÷F‚–âF‡3 ¢Fö7VÖVçBÒÆöEö§6öâ…F‚‡&u÷F‚’Â$Æö6F÷"6¶WB"¢6‡Væµö–BÒfÆ–FFUö6‡Væµö–B†Fö7VÖVçBævWB‚&6‡Væµö–B"’¢&WV—&R†6‡Væµö–Bæ÷B–â6¶WG2Â&GWÆ–6FUöÆö6F÷%÷6¶WB"Âb$GWÆ–6FR6¶WBf÷"¶6‡Væµö–GÒâ"¢6¶WBÒfÆ–FFUöÆö6F÷%÷6¶WB…F‚‡&u÷F‚’ç&W6öÇfR‚’Âg&÷¦VâÂ6‡Væµö–B¢6ö×&U÷6¶WE÷Fõö6æF–FFR‡6¶WBÂg&÷¦Vâ¢6¶WG5¶6‡Væµö–EÒÒ6¶W@¢Æö6F÷%ö–G2æW‡FVæB‡6¶WE²&76–væÖVçG2%Ò¢&V6÷&G2æVæB‡²&6‡Væµö–B#¢6‡Væµö–BÂ&f–ÆU÷6†#Sb#¢6¶WE²'6†#Sb%ÒÂ&76–væÖVçEö–G2#¢6÷'FVB‡6¶WE²&76–væÖVçG2%Ò—Ò¢&WV—&R‡6WB‡6¶WG2’ÓÒ6WB†g&÷¦Vå²&6‡Væ·2%Ò’Â&Æö6F÷%÷6¶WE÷6WEö–æ6ö×ÆWFR"Â$6ö÷&F–æF÷"6¶WB–çWG2Fòæ÷B6÷fW"WfW'’g&÷¦Vâ6‡Væ²W†7FÇ’öæ6Râ"¢&WV—&R†æ÷BGWÆ–6FU÷fÇVW2†Æö6F÷%ö–G2’Â&GWÆ–6FUöÆö6F÷%ö76–væÖVçB"Â$Æö6F÷"6¶WG2&WVB76–væÖVçB”G27&÷726‡Væ·2â"¢&V6÷&G2ç6÷'B†¶W“ÖÆÖ&F—FVÓ¢—FVÕ²&6‡Væµö–B%Ò¢&WGW&â²'6¶WG2#¢6¶WG2Â'6†#Sb#¢6†#Seö'—FW2†§6öâæGV×2‡&V6÷&G2Â6÷'Eö¶W—3ÕG'VRÂ6W&F÷'3Ò‚"Â"Â#¢"’’æVæ6öFR‚'WFbÓ‚"’’Â&76–væÖVçEö–G2#¢6÷'FVB†Æö6F÷%ö–G2—Ð  ¦FVbÆöE÷v÷&¶W%ö&–æF–ær‡Fƒ¢F‚Â6VÆV7F–öã¢F–7E·7G"Âç•ÒÂ&ö¦V7C¢7G"ÂVF—Eö¶–æC¢7G"Âg&÷¦Vã¢F–7E·7G"Âç•ÒÂ¶–æEö–çWG3¢F–7E·7G"Âç•Ò’ÓâF–7E·7G"Âç•Ó ¢F‚ÒF‚ç&W6öÇfR‚¢&–æF–ærÒW†7Eö¶W—2†ÆöEö§6öâ‡F‚Â%v÷&¶W"–çFVw&F–öâ&–æF–ær"’Â²'66†VÖ÷fW'6–öâ"Â&VF—Eö¶–æB"Â&6æF–FFU÷&ö¦V7B"Â'6VÆV7F–öâ"Â'&V6V—B"Â'&V6÷fW'’"Â'V&Æ–5÷&W÷'B"Â&÷Vå÷%öWf–FVæ6R'ÒÂ%v÷&¶W"–çFVw&F–öâ&–æF–ær"¢&WV—&R†&–æF–æu²'66†VÖ÷fW'6–öâ%ÒÓÒ$”äD”äuõdU%4”ôâÂ&&–æF–æu÷66†VÖ"Âb$W‡V7FVB´$”äD”äuõdU%4”ôçÒâ"¢&WV—&R†&–æF–æu²&VF—Eö¶–æB%ÒÓÒ6W&–Æ—¦VEöVF—Eö¶–æB†VF—Eö¶–æB’Â&&–æF–æuö¶–æB"Â%v÷&¶W"&–æF–ærVF—B¶–æBF–ffW'2â"¢&WV—&R†&–æF–æu²&6æF–FFU÷&ö¦V7B%ÒÓÒ&ö¦V7BÂ&&–æF–æu÷&ö¦V7B"Â%v÷&¶W"&–æF–æræÖW2F–ffW&VçB&ö¦V7Bâ"¢&WV—&R†&–æF–æu²'6VÆV7F–öâ%ÒÓÒ6VÆV7F–öâÂ&&–æF–æu÷6VÆV7F–öâ"Â$W‡Æ–6—B6VÆV7F–öâFöW2æ÷BÖF6‚F†Rv÷&¶W"&–æF–ær6VÆV7F–öââ"¢&V6V—BÂ&V6V—E÷–ÆöBÂ&V6V—Eöf–ÆU÷6†Â&V6V—E÷F‚ÒÆöEöf–ÆUö&–æF–ær‡F‚Â&–æF–æu²'&V6V—B%ÒÂ&&–æF–ærç&V6V—B"¢V&Æ–6F–öå÷&öf–ÆRÒg&÷¦VâævWB‚'V&Æ–6F–öå÷&öf–ÆR"ÂV&Æ–6F–öå÷&öf–ÆUöf÷"†g&÷¦Vå²'7FFR%Ò’¢fÆ–FFU÷&V6V—B‡&V6V—BÂVF—Eö¶–æBÂV&Æ–6F–öå÷&öf–ÆR¢6‡Væµö–BÒ&V6V—E²&6‡Væ²%Õ²&6‡Væµö–B%Ð¢–b6VÆV7F–öå²'G—R%ÒÓÒ&'&æ6‚# ¢&WV—&R‡6VÆV7F–öå²&'&æ6‚%ÒÓÒ&V6V—E²'&W÷6—F÷&–W2%Õ²'v÷&¶W%ö'&æ6‚%ÒÂ&&–æF–æu÷6VÆV7F–öâ"Â%6VÆV7FVB'&æ6‚—2æ÷BF†RW†7B&V6V—Bv÷&¶W"'&æ6‚â"¢&W÷'BÂ&W÷'E÷–ÆöBÂ&W÷'Eöf–ÆU÷6†Â&W÷'E÷F‚ÒÆöEöf–ÆUö&–æF–ær‡F‚Â&–æF–æu²'V&Æ–5÷&W÷'B%ÒÂ&&–æF–ærçV&Æ–5÷&W÷'B"¢fÆ–FFU÷V&Æ–5ö'F–f7B‡&W÷'BÂVF—Eö¶–æBÂ6‡Væµö–BÂV&Æ–6F–öå÷&öf–ÆR¢&WV—&R‡&W÷'Eöf–ÆU÷6†ÓÒ&V6V—E²'V&Æ–5÷&ö¦V7F–öâ%Õ²'6†#Sb%ÒÂ&&–æF–æu÷V&Æ–5÷&—fFUöÖ—6ÖF6‚"Â$&÷VæBV&Æ–2'F–f7BFöW2æ÷BÖF6‚&V6V—Bâ"¢–bV&Æ–6F–öå÷&öf–ÆRÓÒtu$TtDUôôäÅ“ ¢&WV—&R‡&W÷'E²'&—fFUö'F–f7E÷6†#Sb%ÒÓÒ&V6V—E²'&—fFUö'F–f7B%Õ²'6†#Sb%ÒÂ&&–æF–æu÷V&Æ–5÷&—fFUöÖ—6ÖF6‚"Â$&÷VæBvw&VvFR&W÷'BFöW2æ÷B–FVçF–g’F†R&—fFRVF—Bâ"¢VÇ6S ¢&WV—&R‡&W÷'Eöf–ÆU÷6†ÓÒ&V6V—E²'&—fFUö'F–f7B%Õ²'6†#Sb%ÒÂ&&–æF–æu÷V&Æ–5÷&—fFUöÖ—6ÖF6‚"Â$&÷VæBV&Æ–26æöæ–6ÂVF—B—2æ÷B'—FRÖ–FVçF–6ÂFòF†RfÆ–FFVBv÷&¶W"VF—Bâ"¢÷VåöWf–FVæ6RÂ÷Vå÷–ÆöBÂ÷Våöf–ÆU÷6†Â÷Vå÷F‚ÒÆöEöf–ÆUö&–æF–ær‡F‚Â&–æF–æu²&÷Vå÷%öWf–FVæ6R%ÒÂ&&–æF–æræ÷Vå÷%öWf–FVæ6R"¢÷Vå÷&W7VÇBÒfÆ–FFU÷V&Æ–6F–öåöWf–FVæ6R†÷VåöWf–FVæ6RÂ&V6V—BÂ&W÷'E÷–ÆöBÂÖW&vVCÔfÇ6R¢–b6VÆV7F–öå²'G—R%ÒÓÒ'VÆÅ÷&WVW7B# ¢&WV—&R‡6VÆV7F–öå²'VÆÅ÷&WVW7B%ÒÓÒ÷VåöWf–FVæ6U²'VÆÅ÷&WVW7B%ÒæB6VÆV7F–öå²'VÆÅ÷&WVW7E÷W&Â%ÒÓÒ÷VåöWf–FVæ6U²'VÆÅ÷&WVW7E÷W&Â%ÒÂ&&–æF–æu÷6VÆV7F–öâ"Â%6VÆV7FVBVÆÂ&WVW7B—2æ÷BF†RW†7BV&Æ–6F–öâWf–FVæ6R"â"¢&V6÷fW'•ö&–æF–ærÒ&–æF–æu²'&V6÷fW'’%Ð¢&WV—&R†—6–ç7Fæ6R‡&V6÷fW'•ö&–æF–ærÂF–7B’æB6WB‡&V6÷fW'•ö&–æF–ær’ÓÒ²'&ö÷B"Â&&6†—fU÷F‚"Â&&6†—fU÷6†#Sb'ÒÂ&&–æF–æu÷6†R"Â$&–æF–ær&V6÷fW'’×W7BW‡Æ–6—FÇ’–FVçF–g’öæR&ö÷BæB&6†—fRâ"¢&V6÷fW'•÷&ö÷BÒ&W6öÇfUö&÷VæE÷F‚‡F‚Â&V6÷fW'•ö&–æF–æu²'&ö÷B%ÒÂ&&–æF–ærç&V6÷fW'’ç&ö÷B"¢&V6÷fW'•ö&6†—fRÒ&W6öÇfUö&÷VæE÷F‚‡F‚Â&V6÷fW'•ö&–æF–æu²&&6†—fU÷F‚%ÒÂ&&–æF–ærç&V6÷fW'’æ&6†—fU÷F‚"¢&WV—&R‡6†#Seöf–ÆR‡&V6÷fW'•ö&6†—fR’ÓÒ&V6÷fW'•ö&–æF–æu²&&6†—fU÷6†#Sb%ÒÂ&&–æF–æu÷&V6÷fW'•ö†6‚"Â$W‡Æ–6—B&V6÷fW'’&6†—fRF–ffW'2g&öÒ&–æF–ærâ"¢&V6÷fW'’ÒfÆ–FFU÷&V6÷fW'•ö&6†—fR‡&V6÷fW'•÷&ö÷BÂ&V6÷fW'•ö&6†—fRÂ&V6V—B¢ÖWFFFÒ&V6÷fW'•²&ÖWFFF%Ð¢&WV—&R†ÖWFFFævWB‚&VF—Eö¶–æB"’ÓÒ&V6V—E²&VF—Eö¶–æB%ÒæBÖWFFFævWB‚&WfÇVF–öåö–B"’ÓÒ&V6V—E²&WfÇVF–öåö–B%ÒæBÖWFFFævWB‚&6æF–FFUö–B"’ÓÒ&V6V—E²&6æF–FFUö–B%ÒæBÖWFFFævWB‚&6‡Væµö–B"’ÓÒ6‡Væµö–BÂ'&V6÷fW'•÷&V6V—Eö–FVçF—G’"Â%&V6÷fW'’ÖWFFFFöW2æ÷B–FVçF–g’F†RW†7B&V6V—Bv÷&¶W"â"¢&WV—&R†ÖWFFFævWB‚&–FVçF—F–W2"’ÓÒ&V6÷fW'•ö–FVçF—G•÷7V'6WB‡&V6V—E²&–FVçF—F–W2%ÒÂVF—Eö¶–æB’Â'&V6÷fW'•÷&V6V—Eö–FVçF—G’"Â%&V6÷fW'’ÖWFFFg&÷¦Vâ–FVçF—F–W2F–ffW"g&öÒ&V6V—Bâ"¢&—fFU÷&V6÷&G2Ò¶—FVÒf÷"—FVÒ–â&V6÷fW'•²&ÖWFFF%Õ²&'F–f7G2%Ò–b—FVÒævWB‚&'F–f7B"’ÓÒ'&—fFUöVF—B%Ð¢&WV—&R†ÆVâ‡&—fFU÷&V6÷&G2’ÓÒÂ'&V6÷fW'•÷&—fFUö'F–f7EöÖ—76–ær"Â%&V6÷fW'’×W7B6öçF–âW†7FÇ’öæR&—fFRVF—Bâ"¢VF—E÷&V6÷&BÒ&—fFU÷&V6÷&G5³Ð¢VF—E÷–ÆöBÒ&V6÷fW'•²&ÖVÖ&W'2%Õ¶VF—E÷&V6÷&E²'F‚%ÕÐ¢&WV—&R‡6†#Seö'—FW2†VF—E÷–ÆöB’ÓÒ&V6V—E²'&—fFUö'F–f7B%Õ²'6†#Sb%ÒÂ'&V6÷fW'•÷&—fFUö'F–f7EöÖ—6ÖF6‚"Â%&V6÷fW&VB&—fFRVF—BF–ffW'2g&öÒ&V6V—Bâ"¢G'“ ¢VF—BÒ§6öâæÆöG2†VF—E÷–ÆöBæFV6öFR‚'WFbÓ‚"’¢W†6WB…Væ–6öFTFV6öFTW'&÷"Â§6öâä¥4ôäFV6öFTW'&÷"’2W†3 ¢&—6R&W&F–öäW'&÷"‚'&—fFUöVF—Eö–çfÆ–B"Â%&V6÷fW&VB&—fFRVF—B—2æ÷BfÆ–BUDbÓ‚¥4ôââ"’g&öÒW†0¢&WV—&R†—6–ç7Fæ6R†VF—BÂF–7B’Â'&—fFUöVF—Eö–çfÆ–B"Â%&V6÷fW&VB&—fFRVF—B×W7B&Râö&¦V7Bâ"¢V&Æ–5÷&V6÷&E÷G—RÒ'V&Æ–5ö6æöæ–6ÅöVF—B"–bV&Æ–6F–öå÷&öf–ÆRÓÒT$Ä”5ôUdÅTD”ôåô%D”d5E2VÇ6R'V&Æ–5÷&W÷'B ¢V&Æ–5÷&V6÷&G2Ò¶—FVÒf÷"—FVÒ–âÖWFFF²&'F–f7G2%Ò–b—FVÒævWB‚&'F–f7B"’ÓÒV&Æ–5÷&V6÷&E÷G—UÐ¢&WV—&R†ÆVâ‡V&Æ–5÷&V6÷&G2’ÓÒÂ'&V6÷fW'•÷V&Æ–5÷&W÷'EöÖ—76–ær"Â%&V6÷fW'’×W7B6öçF–âW†7FÇ’öæRV&Æ–2'F–f7B6æ6†÷Bâ"¢&WV—&R‡&V6÷fW'•²&ÖVÖ&W'2%Õ·V&Æ–5÷&V6÷&G5³Õ²'F‚%ÕÒÓÒ&W÷'E÷–ÆöBÂ'&V6÷fW'•÷V&Æ–5÷&W÷'EöÖ—6ÖF6‚"Â%&V6÷fW&VBV&Æ–2'F–f7BF–ffW'2g&öÒF†RW‡Æ–6—FÇ’&÷VæB'—FW2â"¢W‡V7FVEö6öÖÖöâÒ6öÖÖöå÷&W÷'Eö–FVçF—F–W2†g&÷¦VâÂ²'6÷W&6Uö6‡Væµöf–ÆU÷6†#Sb#¢&V6V—E²&–FVçF—F–W2%Õ²'6÷W&6Uö6‡Væµöf–ÆU÷6†#Sb%ÒÂ'6÷W&6U÷6–FV6%öf–ÆU÷6†#Sb#¢&V6V—E²&–FVçF—F–W2%Õ²'6÷W&6U÷6–FV6%öf–ÆU÷6†#Sb%×Ò¢f÷"f–VÆBÂW‡V7FVB–âW‡V7FVEö6öÖÖöâæ—FV×2‚“ ¢&WV—&R‡&V6V—E²&–FVçF—F–W2%ÒævWB†f–VÆB’ÓÒW‡V7FVBÂ'v÷&¶W%ög&÷¦Våö–FVçF—G•öÖ—6ÖF6‚"Âb%v÷&¶W"&V6V—BF–ffW'2g&öÒ6æöæ–6Â–FVçF—G’¶f–VÆGÒâ"¢–bVF—Eö¶–æBÓÒ&Æö6F÷"# ¢6¶WBÒ¶–æEö–çWG5²'6¶WG2%Õ¶6‡Væµö–EÐ¢&WV—&R‡&V6V—E²&–FVçF—F–W2%ÒævWB‚&Æö6F÷%÷6¶WEöf–ÆU÷6†#Sb"’ÓÒ6¶WE²'6†#Sb%ÒÂ&Æö6F÷%÷6¶WEö†6…öÖ—6ÖF6‚"Â%v÷&¶W"&V6V—BÆö6F÷"6¶WBF–ffW'2g&öÒ6ö÷&F–æF÷"6¶WBâ"¢&W7VÇBÒfÆ–FFUöÆö6F÷%öVF—B†VF—BÂg&÷¦VâÂ6¶WBÂ6‡Væµö–BÂ&ÆÆVÃÕG'VR¢÷væVEö–G2Ò&W7VÇE²&Æö6F÷%ö–G2%Ð¢W‡V7FVE÷&W÷'BÒ'V–ÆEöÆö6F÷%÷&W÷'B€¢g&÷¦VâÂ6‡Væµö–BÂ&V6V—E²'&W÷6—F÷&–W2%Õ²&–Ö×WF&ÆU÷v÷&¶W%ö&6Uö6öÖÖ—B%ÒÀ¢²'6÷W&6Uö6‡Væµöf–ÆU÷6†#Sb#¢&V6V—E²&–FVçF—F–W2%Õ²'6÷W&6Uö6‡Væµöf–ÆU÷6†#Sb%ÒÂ'6÷W&6U÷6–FV6%öf–ÆU÷6†#Sb#¢&V6V—E²&–FVçF—F–W2%Õ²'6÷W&6U÷6–FV6%öf–ÆU÷6†#Sb%×ÒÀ¢6¶WBÂ&W7VÇBÂ6†#Seö'—FW2†VF—E÷–ÆöB’À¢¢VÇ6S ¢v÷&·6WBÒ¶–æEö–çWG5²'v÷&·6WG2%Õ¶6‡Væµö–EÐ¢&WV—&R‡&V6V—E²&–FVçF—F–W2%ÒævWB‚&Ö—76–æuö66W75ö÷væW'6†—÷6†#Sb"’ÓÒv÷&·6WE²'v÷&·6WE÷6†#Sb%ÒÂ&Ö—76–æuö66W75ö÷væW'6†—öÖ—6ÖF6‚"Â%v÷&¶W"&V6V—B÷væW'6†—ÆâF–ffW'2â"¢&WV—&R‡&V6V—E²&–FVçF—F–W2%ÒævWB‚&Æö6F÷%öVF—E÷6WE÷6†#Sb"’ÓÒ¶–æEö–çWG5²&Æö6F÷%÷6WB%Õ²'6†#Sb%ÒÂ&Æö6F÷%öVF—E÷6WEöÖ—6ÖF6‚"Â%v÷&¶W"&V6V—BÆö6F÷"ÖVF—BFWVæFVæ7’6WBF–ffW'2â"¢&WV—&R†VF—BævWB‚&Ö—76–æuö66W75ö÷væW'6†—÷6†#Sb"’ÓÒv÷&·6WE²'v÷&·6WE÷6†#Sb%ÒÂ&Ö—76–æuö66W75ö÷væW'6†—öÖ—6ÖF6‚"Â%&—fFRVF—B÷væW'6†—†6‚F–ffW'2â"¢&W7VÇBÒfÆ–FFUöÖ—76–æuö66W75öVF—B†VF—BÂg&÷¦VâÂv÷&·6WBÂ6‡Væµö–BÂ&ÆÆVÃÕG'VRÂÆö6F÷%öVF—E÷6WE÷6†#ScÖ¶–æEö–çWG5²&Æö6F÷%÷6WB%Õ²'6†#Sb%Ò¢÷væVEö–G2Ò&W7VÇE²'7V&¦V7Eö–G2%Ò²&W7VÇE²'&VFW%÷F6µö–G2%Ò²&W7VÇE²'G&VFÖVçEö–G2%Ð¢W‡V7FVE÷&W÷'BÒ'V–ÆEöÖ—76–æu÷&W÷'B€¢g&÷¦VâÂ6‡Væµö–BÂ&V6V—E²'&W÷6—F÷&–W2%Õ²&–Ö×WF&ÆU÷v÷&¶W%ö&6Uö6öÖÖ—B%ÒÀ¢²'6÷W&6Uö6‡Væµöf–ÆU÷6†#Sb#¢&V6V—E²&–FVçF—F–W2%Õ²'6÷W&6Uö6‡Væµöf–ÆU÷6†#Sb%ÒÂ'6÷W&6U÷6–FV6%öf–ÆU÷6†#Sb#¢&V6V—E²&–FVçF—F–W2%Õ²'6÷W&6U÷6–FV6%öf–ÆU÷6†#Sb%×ÒÀ¢v÷&·6WBÂ¶–æEö–çWG5²&Æö6F÷%÷6WB%ÒÂ&W7VÇBÂVF—BÂ6†#Seö'—FW2†VF—E÷–ÆöB’À¢¢–bV&Æ–6F–öå÷&öf–ÆRÓÒtu$TtDUôôäÅ“ ¢&WV—&R†§6öåö'—FW2†W‡V7FVE÷&W÷'B’ÓÒ&W÷'E÷–ÆöBÂ'V&Æ–5÷&ö¦V7F–öå÷&V6ö×WFUöÖ—6ÖF6‚"Â$&÷VæBV&Æ–2&W÷'B—2æ÷BF†RFWFW&Ö–æ—7F–2&ö¦V7F–öâöbF†R&V6÷fW&VB&—fFRVF—BæBg&÷¦Vâ–çWG2â"¢VÇ6S ¢&WV—&R†VF—E÷–ÆöBÓÒ&W÷'E÷–ÆöBÂ'V&Æ–5÷&ö¦V7F–öå÷&V6ö×WFUöÖ—6ÖF6‚"Â$&÷VæBV&Æ–26æöæ–6ÂVF—B—2æ÷B'—FRÖ–FVçF–6ÂFòF†R&V6÷fW&VBfÆ–FFVBVF—Bâ"¢6æöæ–6ÂÒ6æöæ–6Å÷v÷&¶W%÷F‡2†g&÷¦VâÂVF—Eö¶–æBÂ6‡Væµö–B¢W†—7F–ærÒ¶æÖS¢÷WGWBæ—5öf–ÆR‚’f÷"æÖRÂ÷WGWB–â6æöæ–6Âæ—FV×2‚—Ð¢–bç’†W†—7F–ærçfÇVW2‚’“ ¢&WV—&R†ÆÂ†W†—7F–ærçfÇVW2‚’’Â&–æ6ö×ÆWFUöW†—7F–æuö–çFVw&F–öâ"Âb$6æöæ–6Â6‡Væ²¶6‡Væµö–GÒ†2–æ6ö×ÆWFR&÷fVææ6Râ"¢W‡V7FVE÷–ÆöG2Ò²&VF—B#¢VF—E÷–ÆöBÂ'&V6V—B#¢&V6V—E÷–ÆöBÂ&÷VåöWf–FVæ6R#¢÷Vå÷–ÆöBÂ'V&Æ–5÷&W÷'B#¢&W÷'E÷–ÆöGÐ¢f÷"æÖRÂ–ÆöB–âW‡V7FVE÷–ÆöG2æ—FV×2‚“ ¢&WV—&R‡6†#Seöf–ÆR†6æöæ–6Å¶æÖUÒ’ÓÒ6†#Seö'—FW2‡–ÆöB’Â&6öæfÆ–7F–æu÷&V–çFVw&F–öâ"Âb$6æöæ–6Â6‡Væ²¶6‡Væµö–GÒ6öæfÆ–7G2B¶æÖWÒâ"¢F—7÷6—F–öâÒ&–FV×÷FVçB ¢VÇ6S ¢F—7÷6—F–öâÒ&æWr ¢&WGW&â°¢&&–æF–æu÷F‚#¢F‚Â&&–æF–ær#¢&–æF–ærÂ'6VÆV7F–öâ#¢6VÆV7F–öâÂ&6‡Væµö–B#¢6‡Væµö–BÀ¢'&V6V—B#¢&V6V—BÂ'&V6V—E÷–ÆöB#¢&V6V—E÷–ÆöBÂ'&V6V—Eöf–ÆU÷6†#Sb#¢&V6V—Eöf–ÆU÷6†À¢'&W÷'B#¢&W÷'BÂ'&W÷'E÷–ÆöB#¢&W÷'E÷–ÆöBÂ'&W÷'Eöf–ÆU÷6†#Sb#¢&W÷'Eöf–ÆU÷6†À¢&÷VåöWf–FVæ6R#¢÷VåöWf–FVæ6RÂ&÷Vå÷–ÆöB#¢÷Vå÷–ÆöBÂ&÷Våöf–ÆU÷6†#Sb#¢÷Våöf–ÆU÷6†À¢&÷VåöWf–FVæ6U÷6†#Sb#¢÷Vå÷&W7VÇE²&Wf–FVæ6U÷6†#Sb%ÒÂ'&V6÷fW'’#¢&V6÷fW'’À¢&VF—B#¢VF—BÂ&VF—E÷–ÆöB#¢VF—E÷–ÆöBÂ'&W7VÇB#¢&W7VÇBÂ&÷væVEö–G2#¢÷væVEö–G2À¢&6æöæ–6Â#¢6æöæ–6ÂÂ&F—7÷6—F–öâ#¢F—7÷6—F–öâÀ¢Ð  ¦FVb&VfÆ–v‡Eö&F6‚†&w3¢&w'6RäæÖW76R’ÓâF–7E·7G"Âç•Ó ¢VF—Eö¶–æBÒ&w2æVF—Eö¶–æ@¢&ö¦V7BÒ&WV—&Uöv—F‡V%÷&ö¦V7B†&w2ç&ö¦V7BÂ'&ö¦V7B"¢6VÆV7F–öç2Ò&w2ç6VÆV7F–öâ÷"µÐ¢&–æF–æu÷F‡2Ò&w2çv÷&¶W%ö&–æF–ær÷"µÐ¢&WV—&R†&ööÂ‡6VÆV7F–öç2’æBÆVâ‡6VÆV7F–öç2’ÓÒÆVâ†&–æF–æu÷F‡2’Â&W‡Æ–6—Eö&F6…÷&WV—&VB"Â%&÷f–FRöæRÒ×6VÆV7F–öâæBöæRÒ×v÷&¶W"Ö&–æF–ærf÷"WfW'’6VÆV7FVBv÷&¶W"â"¢g&÷¦VâÒÆöEög&÷¦Våö–çWG2†&w2ÂVF—Eö¶–æB¢–bVF—Eö¶–æBÓÒ&Æö6F÷"# ¢6¶WE÷6WBÒÆöE÷6¶WE÷6WB†&w2æÆö6F÷%÷6¶WB÷"µÒÂg&÷¦Vâ¢¶–æEö–çWG3¢F–7E·7G"Âç•ÒÒ²¢§6¶WE÷6WGÐ¢VÇ6S ¢Æö6F÷%÷6WBÒÆöEöÆö6F÷%öVF—E÷6WB†&w2æÆö6F÷%öVF—B÷"µÒÂg&÷¦Vâ¢¶–æEö–çWG2Ò²&Æö6F÷%÷6WB#¢Æö6F÷%÷6WBÂ'v÷&·6WG2#¢'V–ÆEöÖ—76–æu÷v÷&·6WG2†g&÷¦Vâ—Ð¢'6VBÒ·'6U÷6VÆV7F–öâ‡fÇVRÂ&ö¦V7BÂVF—Eö¶–æB’f÷"fÇVR–â6VÆV7F–öç5Ð¢&WV—&R†æ÷BGWÆ–6FU÷fÇVW2†§6öâæGV×2†—FVÒÂ6÷'Eö¶W—3ÕG'VR’f÷"—FVÒ–â'6VB’Â&GWÆ–6FU÷6VÆV7F–öâ"Â%6VÆV7FVB&F6‚&WVG2"÷"'&æ6‚â"¢v÷&¶W'2Ò¶ÆöE÷v÷&¶W%ö&–æF–ær…F‚‡F‚’Â6VÆV7F–öâÂ&ö¦V7BÂVF—Eö¶–æBÂg&÷¦VâÂ¶–æEö–çWG2’f÷"F‚Â6VÆV7F–öâ–â¦—†&–æF–æu÷F‡2Â'6VB•Ð¢6‡Væµö–G2Ò¶—FVÕ²&6‡Væµö–B%Òf÷"—FVÒ–âv÷&¶W'5Ð¢&WV—&R†æ÷BGWÆ–6FU÷fÇVW2†6‡Væµö–G2’Â&GWÆ–6FUö6‡Væ²"Â%6VÆV7FVB&F6‚6öçF–ç2Ö÷&RF†âöæRv÷&¶W"f÷"6‡Væ²â"¢vU÷6WG2Ò·6WB†fÆGFVå÷&ævW2†g&÷¦Vå²&6‡Væ·2%Õ¶6‡Væµö–EÕ²&÷væVEöFö7VÖVçE÷vU÷&ævW2%ÒÂb'¶6‡Væµö–GÒæ÷væVEöFö7VÖVçE÷vU÷&ævW2"’’f÷"6‡Væµö–B–â6‡Væµö–G5Ð¢f÷"ÆVgB–â&ævR†ÆVâ‡vU÷6WG2’“ ¢f÷"&–v‡B–â&ævR†ÆVgB²ÂÆVâ‡vU÷6WG2’“ ¢&WV—&R†æ÷BvU÷6WG5¶ÆVgEÒæ–çFW'6V7F–öâ‡vU÷6WG5·&–v‡EÒ’Â&÷fW&Æ–æu÷v÷&¶W%ö÷væW'6†—"Â%6VÆV7FVBv÷&¶W'2÷fW&ÆFö7VÖVçB×vR÷væW'6†—â"¢÷væVEö–G2Ò¶÷væVBf÷"v÷&¶W"–âv÷&¶W'2f÷"÷væVB–âv÷&¶W%²&÷væVEö–G2%ÕÐ¢&WV—&R†æ÷BGWÆ–6FU÷fÇVW2†÷væVEö–G2’Â&GWÆ–6FUö&F6…ö§VFvÖVçB"Â%6VÆV7FVBv÷&¶W'2GWÆ–6FR÷væVB§VFvÖVçG2â"¢&W÷6—F÷&–W2Ò²‡v÷&¶W%²'&V6V—B%Õ²'&W÷6—F÷&–W2%Õ²&6æF–FFUö&6Uö'&æ6‚%ÒÂv÷&¶W%²'&V6V—B%Õ²'&W÷6—F÷&–W2%Õ²&–Ö×WF&ÆU÷v÷&¶W%ö&6Uö6öÖÖ—B%Ò’f÷"v÷&¶W"–âv÷&¶W'7Ð¢&WV—&R†ÆVâ‡&W÷6—F÷&–W2’ÓÒÂ&&F6…ö&6UöÖ—6ÖF6‚"Â%6VÆV7FVBv÷&¶W'2Fòæ÷B6†&RöæR–Ö×WF&ÆR6æF–FFR&6Râ"¢&WGW&â²&VF—Eö¶–æB#¢VF—Eö¶–æBÂ'&ö¦V7B#¢&ö¦V7BÂ&g&÷¦Vâ#¢g&÷¦VâÂ&¶–æEö–çWG2#¢¶–æEö–çWG2Â'v÷&¶W'2#¢v÷&¶W'2Â&6‡Væµö–G2#¢6÷'FVB†6‡Væµö–G2’Â&&6Uö'&æ6‚#¢æW‡B†—FW"‡&W÷6—F÷&–W2’•³ÒÂ&&6Uö6öÖÖ—B#¢æW‡B†—FW"‡&W÷6—F÷&–W2’•³×Ð  ¦FVb6öÖÖæE÷&VfÆ–v‡Eö&F6‚†&w3¢&w'6RäæÖW76R’ÓâæöæS ¢&F6‚Ò&VfÆ–v‡Eö&F6‚†&w2¢VÖ—B‡²&ö²#¢G'VRÂ&÷W&F–öâ#¢'&VfÆ–v‡BÖ&F6‚"Â&VF—Eö¶–æB#¢&F6…²&VF—Eö¶–æB%ÒÂ&6æF–FFU÷&ö¦V7B#¢&F6…²'&ö¦V7B%ÒÂ'6VÆV7FVEö6‡Væµö–G2#¢&F6…²&6‡Væµö–G2%ÒÂ'6VÆV7FVE÷v÷&¶W'2#¢ÆVâ†&F6…²'v÷&¶W'2%Ò’Â&æWu÷v÷&¶W'2#¢7VÒ†—FVÕ²&F—7÷6—F–öâ%ÒÓÒ&æWr"f÷"—FVÒ–â&F6…²'v÷&¶W'2%Ò’Â&–FV×÷FVçE÷v÷&¶W'2#¢7VÒ†—FVÕ²&F—7÷6—F–öâ%ÒÓÒ&–FV×÷FVçB"f÷"—FVÒ–â&F6…²'v÷&¶W'2%Ò’Â'G&ç67F–öå÷&VG’#¢G'VRÂ&ÖW&vUöæöæUööåöf–ÇW&R#¢G'VWÒ  ¦FVb'F–f7E÷&V6÷&B‡Fƒ¢F‚Â&ö÷C¢F‚Â7FvS¢7G"Â'F–f7E÷G—S¢7G"Âf—6–&–Æ—G“¢7G"Â7F×¢7G"’ÓâF–7E·7G"Âç•Ó ¢&VÆF—fRÒF‚ç&W6öÇfR‚’ç&VÆF—fU÷Fò‡&ö÷Bç&W6öÇfR‚’’æ5÷÷6—‚‚¢F–vW7BÒ6†#Seöf–ÆR‡F‚¢&WGW&â°¢&'F–f7Eö–B#¢'F–f7Eö–B‡&VÆF—fRÂF–vW7B’À¢'7FvR#¢7FvRÀ¢&'F–f7E÷G—R#¢'F–f7E÷G—RÀ¢'F‚#¢&VÆF—fRÀ¢'6†#Sb#¢F–vW7BÀ¢&ÖVF–÷G—R#¢&Æ–6F–öâö§6öâ"À¢'f—6–&–Æ—G’#¢f—6–&–Æ—G’À¢'&WFVçF–öâ#¢'&WV—&VB"À¢&g&÷¦Vâ#¢G'VRÀ¢'&V6÷&FVEöB#¢7F×À¢Ð  ¦FVb7F—fUö6æöæ–6Åö6‡Væ·2†g&÷¦Vã¢F–7E·7G"Âç•ÒÂVF—Eö¶–æC¢7G"’ÓâÆ—7E·7G%Ó ¢7F—fS¢Æ—7E·7G%ÒÒµÐ¢V&Æ–6F–öå÷&öf–ÆRÒg&÷¦VâævWB‚'V&Æ–6F–öå÷&öf–ÆR"ÂV&Æ–6F–öå÷&öf–ÆUöf÷"†g&÷¦Vå²'7FFR%Ò’¢f÷"6‡Væµö–B–âg&÷¦Vå²&6‡Væ·2%Ó ¢F‡2Ò6æöæ–6Å÷v÷&¶W%÷F‡2†g&÷¦VâÂVF—Eö¶–æBÂ6‡Væµö–B¢&W6VçBÒ¶æÖS¢F‚æ—5öf–ÆR‚’f÷"æÖRÂF‚–âF‡2æ—FV×2‚—Ð¢–bæ÷Bç’‡&W6VçBçfÇVW2‚’“ ¢6öçF–çVP¢&WV—&R†ÆÂ‡&W6VçBçfÇVW2‚’’Â&–æ6ö×ÆWFUöW†—7F–æuö–çFVw&F–öâ"Âb$6æöæ–6Â6‡Væ²¶6‡Væµö–GÒÆ6·2—G26ö×ÆWFRVF—B÷&÷fVææ6R6WBâ"Â&W6VçB¢f÷"F‚–âF‡2çfÇVW2‚“ ¢Öæ–fW7E÷&V6÷&Eöf÷%÷F‚†g&÷¦VâÂF‚¢&V6V—BÒÆöEö§6öâ‡F‡5²'&V6V—B%ÒÂ$6æöæ–6Âv÷&¶W"&V6V—B"¢&V6V—E÷&öf–ÆRÒV&Æ–6F–öå÷&öf–ÆUög&öÕ÷F‚†VF—Eö¶–æBÂ6‡Væµö–BÂ&V6V—BævWB‚'&W÷6—F÷&–W2"Â·Ò’ævWB‚'V&Æ–5÷&W÷'E÷F‚"’¢&WV—&R‡fÆ–FFU÷&V6V—B‡&V6V—BÂVF—Eö¶–æBÂ&V6V—E÷&öf–ÆR’ÓÒVF—Eö¶–æBÂ&6æöæ–6Å÷&V6V—Eö¶–æB"Âb$6æöæ–6Â&V6V—B¶–æBF–ffW'2f÷"¶6‡Væµö–GÒâ"¢&WV—&R‡&V6V—E²&6‡Væ²%Õ²&6‡Væµö–B%ÒÓÒ6‡Væµö–BÂ&6æöæ–6Å÷&V6V—Eö6‡Væ²"Âb$6æöæ–6Â&V6V—BæÖW2F–ffW&VçB6‡Væ²B¶6‡Væµö–GÒâ"¢VF—BÂVF—E÷–ÆöBÂVF—E÷6†ÒÆöEö§6öå÷6æ6†÷B‡F‡5²&VF—B%ÒÂ$6æöæ–6Â6æF–FFRVF—B"¢&W÷'BÂ&W÷'E÷–ÆöBÂ&W÷'Eöf–ÆU÷6†ÒÆöEö§6öå÷6æ6†÷B‡F‡5²'V&Æ–5÷&W÷'B%ÒÂ$6æöæ–6ÂV&Æ–2v÷&¶W"&W÷'B"¢fÆ–FFU÷V&Æ–5ö'F–f7B‡&W÷'BÂVF—Eö¶–æBÂ6‡Væµö–BÂ&V6V—E÷&öf–ÆR¢–b&V6V—E÷&öf–ÆRÓÒV&Æ–6F–öå÷&öf–ÆS ¢&WV—&R‡&V6V—E²'&—fFUö'F–f7B%Õ²'6†#Sb%ÒÓÒVF—E÷6†Â&6æöæ–6Å÷&—fFUö&–æF–ær"Âb$6æöæ–6ÂVF—B&–æF–ærF–ffW'2f÷"¶6‡Væµö–GÒâ"¢VÇ6S ¢&WV—&R‡&V6V—E÷&öf–ÆRÓÒtu$TtDUôôäÅ’æBV&Æ–6F–öå÷&öf–ÆRÓÒT$Ä”5ôUdÅTD”ôåô%D”d5E2Â'V&Æ–6F–öå÷&öf–ÆUöÖ—6ÖF6‚"Âb$6æöæ–6Â&V6V—BV&Æ–6F–öâF‚F–ffW'2g&öÒF†Rg&÷¦VâWfÇVF–öâ&öf–ÆRf÷"¶6‡Væµö–GÒâ"¢Ö–w&F–öå÷F‚Ò6æöæ–6Å÷V&Æ–6F–öåöÖ–w&F–öå÷F‚†g&÷¦VâÂVF—Eö¶–æBÂ6‡Væµö–B¢&WV—&R†Ö–w&F–öå÷F‚æ—5öf–ÆR‚’Â'V&Æ–6F–öåöÖ–w&F–öåöÖ—76–ær"Âb$6æöæ–6Â6‡Væ²¶6‡Væµö–GÒÆ6·2—G2V&Æ–6F–öâÖ–w&F–öâ&V6÷&Bâ"¢Öæ–fW7E÷&V6÷&Eöf÷%÷F‚†g&÷¦VâÂÖ–w&F–öå÷F‚¢fÆ–FFU÷V&Æ–5ö'F–f7B†VF—BÂVF—Eö¶–æBÂ6‡Væµö–BÂT$Ä”5ôUdÅTD”ôåô%D”d5E2¢Ö–w&F–öâÒÆöEö§6öâ†Ö–w&F–öå÷F‚Â%V&Æ–6F–öâÖ–w&F–öâ"¢fÆ–FFU÷V&Æ–6F–öåöÖ–w&F–öâ†Ö–w&F–öâÂVF—Eö¶–æBÂ6‡Væµö–BÂg&÷¦VâÂ&V6V—BÂVF—E÷6†ÂÆVâ†VF—E÷–ÆöB’¢&WV—&R†Ö–w&F–öå²&æ÷&ÖÆ—¦F–öâ%Õ²&§VFvÖVçEö6÷VçB%ÒÓÒÆVâ†VF—BævWB‚&§VFvÖVçG2"ÂVF—BævWB‚'7V&¦V7Eö§VFvÖVçG2"ÂµÒ’’’Â'V&Æ–6F–öåöÖ–w&F–öåöæ÷&ÖÆ—¦F–öâ"Âb%V&Æ–6F–öâÖ–w&F–öâ§VFvÖVçB6÷VçBF–ffW'2f÷"¶6‡Væµö–GÒâ"¢–b&V6V—E÷&öf–ÆRÓÒtu$TtDUôôäÅ“ ¢&WV—&R‡&V6V—E²'&—fFUö'F–f7B%Õ²'6†#Sb%ÒÓÒ&W÷'E²'&—fFUö'F–f7E÷6†#Sb%ÒÂ&6æöæ–6Å÷&—fFUö&–æF–ær"Âb$6æöæ–6ÂÆVv7’&—fFRVF—B&–æF–ærF–ffW'2f÷"¶6‡Væµö–GÒâ"¢–b&V6V—E÷&öf–ÆRÓÒV&Æ–6F–öå÷&öf–ÆS ¢&WV—&R†VF—E÷6†ÓÒ&W÷'E²'&—fFUö'F–f7E÷6†#Sb%ÒÂ&6æöæ–6Å÷&—fFUö&–æF–ær"Âb$6æöæ–6Â&—fFRVF—B&–æF–ærF–ffW'2f÷"¶6‡Væµö–GÒâ"¢VÇ6S ¢&WV—&R†VF—E÷6†ÓÒ&W÷'Eöf–ÆU÷6†Â&6æöæ–6Å÷&—fFUö&–æF–ær"Âb$6æöæ–6ÂV&Æ–2VF—B6æ6†÷BF–ffW'2f÷"¶6‡Væµö–GÒâ"¢&WV—&R‡&V6V—E²'V&Æ–5÷&ö¦V7F–öâ%Õ²'6†#Sb%ÒÓÒ&W÷'Eöf–ÆU÷6†Â&6æöæ–6Å÷V&Æ–5ö&–æF–ær"Âb$6æöæ–6ÂV&Æ–2&W÷'B&–æF–ærF–ffW'2f÷"¶6‡Væµö–GÒâ"¢÷VåöWf–FVæ6RÒÆöEö§6öâ‡F‡5²&÷VåöWf–FVæ6R%ÒÂ$6æöæ–6Â÷VâÕ"Wf–FVæ6R"¢ÖW&vUöWf–FVæ6RÒÆöEö§6öâ‡F‡5²&ÖW&vUöWf–FVæ6R%ÒÂ$6æöæ–6ÂÖW&vRWf–FVæ6R"¢fÆ–FFU÷V&Æ–6F–öåöWf–FVæ6R†÷VåöWf–FVæ6RÂ&V6V—BÂ&W÷'E÷–ÆöBÂÖW&vVCÔfÇ6R¢fÆ–FFU÷V&Æ–6F–öåöWf–FVæ6R†ÖW&vUöWf–FVæ6RÂ&V6V—BÂ&W÷'E÷–ÆöBÂÖW&vVCÕG'VRÂ&–÷%ö÷VãÖ÷VåöWf–FVæ6R¢7F—fRæVæB†6‡Væµö–B¢&WGW&â6÷'FVB†7F—fR  ¦FVb'V–ÆEö7V×VÆF—fUö6†V6·ö–çB†÷WGWC¢F‚Âg&÷¦Vã¢F–7E·7G"Âç•Ò’ÓâF–7E·7G"Âç•Ó ¢&WV—&R†æ÷B÷WGWBæW†—7G2‚’Â&÷WGWEöW†—7G2"Âb%&VgW6–ærFò÷fW'w&—FR7V×VÆF—fR6†V6·ö–çB¶÷WGWGÒâ"¢&WV—&U÷6fUö÷WGWE÷F‚†÷WGWBÂg&÷¦Vå²'&ö÷B%ÒÂ$7V×VÆF—fR&—fFR6†V6·ö–çB"¢7FFU÷–ÆöBÒg&÷¦Vå²'7FFU÷F‚%Òç&VEö'—FW2‚¢Öæ–fW7E÷–ÆöBÒg&÷¦Vå²&Öæ–fW7E÷F‚%Òç&VEö'—FW2‚¢ÖVÖ&W'3¢F–7E·7G"Â'—FW5ÒÒ°¢&WfÇVF–öâ×7FFRæ§6öâ#¢7FFU÷–ÆöBÀ¢&'F–f7BÖÖæ–fW7Bæ§6öâ#¢Öæ–fW7E÷–ÆöBÀ¢Ð¢W†6ÇVFVC¢Æ—7E¶F–7E·7G"Â7G%ÕÒÒµÐ¢f÷"&V6÷&B–âg&÷¦Vå²&Öæ–fW7B%ÒævWB‚&'F–f7G2"ÂµÒ“ ¢–bæ÷B—6–ç7Fæ6R‡&V6÷&BÂF–7B“ ¢6öçF–çVP¢&VÆF—fRÒ6fU÷&VÆF—fU÷F‚‡7G"‡&V6÷&BævWB‚'F‚"Â""’’¢6÷W&6RÒ&W6öÇfUöÖæ–fW7E÷F‚†g&÷¦Vå²'&ö÷B%ÒÂ&VÆF—fR¢7Vff—‚Ò6÷W&6Rç7Vff—‚æ66VföÆB‚¢–b&V6÷&BævWB‚'f—6–&–Æ—G’"’ÓÒ'&W7G&–7FVB"÷"7Vff—‚ÓÒ"çFb# ¢W†6ÇVFVBæVæB‡²'F‚#¢&VÆF—fRÂ'&V6öâ#¢'&W7G&–7FVEö÷%÷Fb'Ò¢6öçF–çVP¢–bæ÷B6÷W&6Ræ—5öf–ÆR‚“ ¢W†6ÇVFVBæVæB‡²'F‚#¢&VÆF—fRÂ'&V6öâ#¢&æ÷EöÆö6ÆÇ•ö66W76–&ÆR'Ò¢6öçF–çVP¢–ÆöBÒ6÷W&6Rç&VEö'—FW2‚¢&WV—&R‡&V6÷&BævWB‚'6†#Sb"’ÓÒ6†#Seö'—FW2‡–ÆöB’Â&6†V6·ö–çEö'F–f7Eö†6‚"Âb%&Vv—7FW&VB'F–f7B6†ævVB&Vf÷&R6†V6·ö–çC¢·&VÆF—fWÒ"¢ÖVÖ&W'5¶b&'F–f7G2÷·&VÆF—fWÒ%ÒÒ–Æö@¢ÖWFFFÒ°¢'66†VÖ÷fW'6–öâ#¢&6æF–FFRÖVF—BÖ7V×VÆF—fRÖ6†V6·ö–çB×c"À¢&WfÇVF–öåö–B#¢g&÷¦Vå²'7FFR%Õ²&WfÇVF–öåö–B%ÒÀ¢'7FFU÷6†#Sb#¢6†#Seö'—FW2‡7FFU÷–ÆöB’À¢&Öæ–fW7E÷6†#Sb#¢6†#Seö'—FW2†Öæ–fW7E÷–ÆöB’À¢&ÖVÖ&W'2#¢·²'F‚#¢æÖRÂ'6†#Sb#¢6†#Seö'—FW2‡–ÆöB’Â&'—FUöÆVæwF‚#¢ÆVâ‡–ÆöB—Òf÷"æÖRÂ–ÆöB–â6÷'FVB†ÖVÖ&W'2æ—FV×2‚’•ÒÀ¢&W†6ÇVFVB#¢W†6ÇVFVBÀ¢'&W7G&–7FVE÷Fg5ö–æ6ÇVFVB#¢fÇ6RÀ¢Ð¢ÖVÖ&W'5²&6†V6·ö–çBÖÖWFFFæ§6öâ%ÒÒ§6öåö'—FW2†ÖWFFF¢w&—FU÷¦—öFöÖ–2†÷WGWBÂÖVÖ&W'2¢&WGW&â²'F‚#¢÷WGWBç&W6öÇfR‚’ç&VÆF—fU÷Fò†g&÷¦Vå²'&ö÷B%Òç&W6öÇfR‚’’æ5÷÷6—‚‚’Â'6†#Sb#¢6†#Seöf–ÆR†÷WGWB—Ð  ¦FVb6ö×ÆWF–öåö66÷VçF–ær†g&÷¦Vã¢F–7E·7G"Âç•ÒÂVF—Eö¶–æC¢7G"Â¶–æEö–çWG3¢F–7E·7G"Âç•Ò’ÓâF–7E·7G"Âç•Ó ¢W‡V7FVEö6‡Væ·2Ò6÷'FVB†g&÷¦Vå²&6‡Væ·2%Ò¢7F—fRÒ7F—fUö6æöæ–6Åö6‡Væ·2†g&÷¦VâÂVF—Eö¶–æB¢Ö—76–ærÒ6÷'FVB‡6WB†W‡V7FVEö6‡Væ·2’Ò6WB†7F—fR’¢–bVF—Eö¶–æBÓÒ&Æö6F÷"# ¢W‡V7FVEö–G2Ò6WB†¶–æEö–çWG5²&76–væÖVçEö–G2%Ò¢66WFVC¢Æ—7E·7G%ÒÒµÐ¢f÷"6‡Væµö–B–â7F—fS ¢'F–f7BÒÆöEö§6öâ†6æöæ–6Å÷v÷&¶W%÷F‡2†g&÷¦VâÂVF—Eö¶–æBÂ6‡Væµö–B•²&VF—B%ÒÂ$6æöæ–6ÂÆö6F÷"VF—B"¢6¶WBÒ¶–æEö–çWG5²'6¶WG2%Õ¶6‡Væµö–EÐ¢&W7VÇBÒfÆ–FFUöÆö6F÷%öVF—B†'F–f7BÂg&÷¦VâÂ6¶WBÂ6‡Væµö–BÂ&ÆÆVÃÕG'VR¢66WFVBæW‡FVæB‡&W7VÇE²&Æö6F÷%ö–G2%Ò¢&WV—&R†æ÷BGWÆ–6FU÷fÇVW2†66WFVB’Â&GWÆ–6FUöÆö6F÷%ö76–væÖVçB"Â$6æöæ–6ÂÆö6F÷"VF—G2GWÆ–6FR76–væÖVçG2â"¢&WV—&R‡6WB†66WFVB’æ—77V'6WB†W‡V7FVEö–G2’Â&f÷&V–våö6‡Væµö76–væÖVçB"Â$6æöæ–6ÂÆö6F÷"VF—G26öçF–âf÷&V–vâ76–væÖVçG2â"¢&WGW&â²&W‡V7FVEö6‡Væµö–G2#¢W‡V7FVEö6‡Væ·2Â&7F—fUö6‡Væµö–G2#¢7F—fRÂ&Ö—76–æuö6‡Væµö–G2#¢Ö—76–ærÂ&6ö×ÆWFR#¢æ÷BÖ—76–æræB6WB†66WFVB’ÓÒW‡V7FVEö–G2Â&W‡V7FVEö76–væÖVçG2#¢ÆVâ†W‡V7FVEö–G2’Â&66WFVEö76–væÖVçG2#¢ÆVâ†66WFVB—Ð¢W‡V7FVE÷7V&¦V7G2Ò·7V&¦V7Bf÷"v÷&·6WB–â¶–æEö–çWG5²'v÷&·6WG2%ÒçfÇVW2‚’f÷"7V&¦V7B–âv÷&·6WE²'7V&¦V7Eö–G2%×Ð¢W‡V7FVE÷F6·2Ò·F6²f÷"v÷&·6WB–â¶–æEö–çWG5²'v÷&·6WG2%ÒçfÇVW2‚’f÷"F6²–âv÷&·6WE²'&VFW%÷F6µö–G2%×Ð¢W‡V7FVE÷G&VFÖVçG2Ò·G&VFÖVçBf÷"v÷&·6WB–â¶–æEö–çWG5²'v÷&·6WG2%ÒçfÇVW2‚’f÷"G&VFÖVçB–âv÷&·6WE²'G&VFÖVçEö–G2%×Ð¢7V&¦V7G3¢Æ—7E·7G%ÒÒµÐ¢F6·3¢Æ—7E·7G%ÒÒµÐ¢G&VFÖVçG3¢Æ—7E·7G%ÒÒµÐ¢f÷"6‡Væµö–B–â7F—fS ¢'F–f7BÒÆöEö§6öâ†6æöæ–6Å÷v÷&¶W%÷F‡2†g&÷¦VâÂVF—Eö¶–æBÂ6‡Væµö–B•²&VF—B%ÒÂ$6æöæ–6ÂÖ—76–ærÖ66W72VF—B"¢&W7VÇBÒfÆ–FFUöÖ—76–æuö66W75öVF—B†'F–f7BÂg&÷¦VâÂ¶–æEö–çWG5²'v÷&·6WG2%Õ¶6‡Væµö–EÒÂ6‡Væµö–BÂ&ÆÆVÃÕG'VRÂÆö6F÷%öVF—E÷6WE÷6†#ScÖ¶–æEö–çWG5²&Æö6F÷%÷6WB%Õ²'6†#Sb%Ò¢7V&¦V7G2æW‡FVæB‡&W7VÇE²'7V&¦V7Eö–G2%Ò¢F6·2æW‡FVæB‡&W7VÇE²'&VFW%÷F6µö–G2%Ò¢G&VFÖVçG2æW‡FVæB‡&W7VÇE²'G&VFÖVçEö–G2%Ò¢&WV—&R†æ÷BGWÆ–6FU÷fÇVW2‡7V&¦V7G2²F6·2²G&VFÖVçG2’Â&GWÆ–6FUö&F6…ö§VFvÖVçB"Â$6æöæ–6ÂÖ—76–ærÖ66W72VF—G2GWÆ–6FR§VFvÖVçG2â"¢&WV—&R‡6WB‡7V&¦V7G2’æ—77V'6WB†W‡V7FVE÷7V&¦V7G2’æB6WB‡F6·2’æ—77V'6WB†W‡V7FVE÷F6·2’æB6WB‡G&VFÖVçG2’æ—77V'6WB†W‡V7FVE÷G&VFÖVçG2’Â&f÷&V–våö&F6…ö§VFvÖVçB"Â$6æöæ–6ÂÖ—76–ærÖ66W72VF—G26öçF–âf÷&V–vâ§VFvÖVçG2â"¢6ö×ÆWFRÒæ÷BÖ—76–æræB6WB‡7V&¦V7G2’ÓÒW‡V7FVE÷7V&¦V7G2æB6WB‡F6·2’ÓÒW‡V7FVE÷F6·2æB6WB‡G&VFÖVçG2’ÓÒW‡V7FVE÷G&VFÖVçG0¢&WGW&â²&W‡V7FVEö6‡Væµö–G2#¢W‡V7FVEö6‡Væ·2Â&7F—fUö6‡Væµö–G2#¢7F—fRÂ&Ö—76–æuö6‡Væµö–G2#¢Ö—76–ærÂ&6ö×ÆWFR#¢6ö×ÆWFRÂ&W‡V7FVE÷7V&¦V7G2#¢ÆVâ†W‡V7FVE÷7V&¦V7G2’Â&66WFVE÷7V&¦V7G2#¢ÆVâ‡7V&¦V7G2’Â&W‡V7FVE÷&VFW%÷F6·2#¢ÆVâ†W‡V7FVE÷F6·2’Â&66WFVE÷&VFW%÷F6·2#¢ÆVâ‡F6·2’Â&W‡V7FVE÷G&VFÖVçG2#¢ÆVâ†W‡V7FVE÷G&VFÖVçG2’Â&66WFVE÷G&VFÖVçG2#¢ÆVâ‡G&VFÖVçG2—Ð  ¦FVb–çFVw&FUö&F6‚†&w3¢&w'6RäæÖW76R’ÓâF–7E·7G"Âç•Ó ¢&F6‚Ò&VfÆ–v‡Eö&F6‚†&w2¢ÖW&vU÷F‡2Ò&w2æÖW&vUöWf–FVæ6R÷"µÐ¢&WV—&R†ÆVâ†ÖW&vU÷F‡2’ÓÒÆVâ†&F6…²'v÷&¶W'2%Ò’Â&ÖW&vUöWf–FVæ6Uö6÷VçB"Â%&÷f–FRöæR÷7BÖÖW&vRÒÖÖW&vRÖWf–FVæ6Rf÷"WfW'’6VÆV7FVBv÷&¶W"â"¢ÖW&vW5ö'•÷#¢F–7E¶–çBÂGWÆU¶F–7E·7G"Âç•ÒÂ'—FW2Â7G%ÕÒÒ·Ð¢f÷"&u÷F‚–âÖW&vU÷F‡3 ¢Wf–FVæ6RÂ–ÆöBÂF–vW7BÒÆöEö§6öå÷6æ6†÷B…F‚‡&u÷F‚’ç&W6öÇfR‚’Â$g&W6‚ÖW&vVBÕ"Wf–FVæ6R"¢"ÒWf–FVæ6RævWB‚'VÆÅ÷&WVW7B"¢&WV—&R†—6–ç7Fæ6R‡"Â–çB’æB"æ÷B–âÖW&vW5ö'•÷"Â&GWÆ–6FUöÖW&vUöWf–FVæ6R"Â$ÖW&vVBÕ"Wf–FVæ6R&WVG2VÆÂ&WVW7Bâ"¢ÖW&vW5ö'•÷%·%ÒÒ†Wf–FVæ6RÂ–ÆöBÂF–vW7B¢f÷"v÷&¶W"–â&F6…²'v÷&¶W'2%Ó ¢"Òv÷&¶W%²&÷VåöWf–FVæ6R%Õ²'VÆÅ÷&WVW7B%Ð¢&WV—&R‡"–âÖW&vW5ö'•÷"Â&ÖW&vUöWf–FVæ6UöÖ—76–ær"Âb$Ö—76–ærÖW&vVBÕ"Wf–FVæ6Rf÷""·'Òâ"¢ÖW&vRÂÖW&vU÷–ÆöBÂÖW&vUöf–ÆU÷6†ÒÖW&vW5ö'•÷%·%Ð¢&W7VÇBÒfÆ–FFU÷V&Æ–6F–öåöWf–FVæ6R†ÖW&vRÂv÷&¶W%²'&V6V—B%ÒÂv÷&¶W%²'&W÷'E÷–ÆöB%ÒÂÖW&vVCÕG'VRÂ&–÷%ö÷Vã×v÷&¶W%²&÷VåöWf–FVæ6R%Ò¢v÷&¶W"çWFFR‡²&ÖW&vUöWf–FVæ6R#¢ÖW&vRÂ&ÖW&vU÷–ÆöB#¢ÖW&vU÷–ÆöBÂ&ÖW&vUöf–ÆU÷6†#Sb#¢ÖW&vUöf–ÆU÷6†Â&ÖW&vUöWf–FVæ6U÷6†#Sb#¢&W7VÇE²&Wf–FVæ6U÷6†#Sb%×Ò ¢7FFU÷F‚Ò&F6…²&g&÷¦Vâ%Õ²'7FFU÷F‚%Ð¢v—F‚WfÇVF–öåö–çFVw&F–öåöÆö6²‡7FFU÷F‚“ ¢2&R×'VâWfW'’&VBÖöæÇ’vFRv†–ÆR†öÆF–ærF†R6æöæ–6Â×WFF–öâÆö6²à¢&F6‚Ò&VfÆ–v‡Eö&F6‚†&w2¢f÷"v÷&¶W"–â&F6…²'v÷&¶W'2%Ó ¢"Òv÷&¶W%²&÷VåöWf–FVæ6R%Õ²'VÆÅ÷&WVW7B%Ð¢ÖW&vRÂÖW&vU÷–ÆöBÂÖW&vUöf–ÆU÷6†ÒÖW&vW5ö'•÷%·%Ð¢&W7VÇBÒfÆ–FFU÷V&Æ–6F–öåöWf–FVæ6R†ÖW&vRÂv÷&¶W%²'&V6V—B%ÒÂv÷&¶W%²'&W÷'E÷–ÆöB%ÒÂÖW&vVCÕG'VRÂ&–÷%ö÷Vã×v÷&¶W%²&÷VåöWf–FVæ6R%Ò¢v÷&¶W"çWFFR‡²&ÖW&vUöWf–FVæ6R#¢ÖW&vRÂ&ÖW&vU÷–ÆöB#¢ÖW&vU÷–ÆöBÂ&ÖW&vUöf–ÆU÷6†#Sb#¢ÖW&vUöf–ÆU÷6†Â&ÖW&vUöWf–FVæ6U÷6†#Sb#¢&W7VÇE²&Wf–FVæ6U÷6†#Sb%×Ò¢g&÷¦VâÒ&F6…²&g&÷¦Vâ%Ð¢&ö÷BÒg&÷¦Vå²'&ö÷B%Ð¢÷&–v–æÅ÷7FFRÒg&÷¦Vå²'7FFUö'—FW2%Ð¢÷&–v–æÅöÖæ–fW7BÒg&÷¦Vå²&Öæ–fW7Eö'—FW2%Ð¢7FFUö&Vf÷&U÷6†Òg&÷¦Vå²'7FFUöf–ÆU÷6†#Sb%Ð¢Öæ–fW7Eö&Vf÷&U÷6†Òg&÷¦Vå²&Öæ–fW7Eöf–ÆU÷6†#Sb%Ð¢&Wf–÷W6Ç•ö–çFVw&FVBÒ7F—fUö6æöæ–6Åö6‡Væ·2†g&÷¦VâÂ&F6…²&VF—Eö¶–æB%Ò¢6†V6·ö–çEö÷WGWBÒF‚†&w2æ6†V6·ö–çEö÷WGWB’ç&W6öÇfR‚¢&WV—&R†æ÷B6†V6·ö–çEö÷WGWBæW†—7G2‚’Â&÷WGWEöW†—7G2"Âb%&VgW6–ærFò÷fW'w&—FR¶6†V6·ö–çEö÷WGWGÒâ"¢7F×Òæ÷r‚¢w&—GFVã¢Æ—7EµF…ÒÒµÐ¢Öæ–fW7E÷&WÆ6VBÒfÇ6P¢7FFU÷&WÆ6VBÒfÇ6P¢G'“ ¢f÷"v÷&¶W"–â&F6…²'v÷&¶W'2%Ó ¢–bv÷&¶W%²&F—7÷6—F–öâ%ÒÓÒ&–FV×÷FVçB# ¢6öçF–çVP¢–ÆöG2Ò°¢&VF—B#¢v÷&¶W%²&VF—E÷–ÆöB%ÒÀ¢'&V6V—B#¢v÷&¶W%²'&V6V—E÷–ÆöB%ÒÀ¢&÷VåöWf–FVæ6R#¢v÷&¶W%²&÷Vå÷–ÆöB%ÒÀ¢&ÖW&vUöWf–FVæ6R#¢v÷&¶W%²&ÖW&vU÷–ÆöB%ÒÀ¢'V&Æ–5÷&W÷'B#¢v÷&¶W%²'&W÷'E÷–ÆöB%ÒÀ¢Ð¢f÷"æÖRÂ–ÆöB–â–ÆöG2æ—FV×2‚“ ¢÷WGWBÒv÷&¶W%²&6æöæ–6Â%Õ¶æÖUÐ¢&WV—&U÷6fUö÷WGWE÷F‚†÷WGWBÂ&ö÷BÂ$6æöæ–6Â6æF–FFRÖVF—B'F–f7B"¢&WV—&R†æ÷B÷WGWBæW†—7G2‚’Â&6æöæ–6Åö6‡VæµöW†—7G2"Âb%&VgW6–ærFò÷fW'w&—FR¶÷WGWGÒâ"¢&WÆ6Uö'—FW5öFöÖ–2†÷WGWBÂ–ÆöB¢w&—GFVâæVæB†÷WGWB¢Öæ–fW7BÒFVW6÷’†g&÷¦Vå²&Öæ–fW7B%Ò¢7FFRÒFVW6÷’†g&÷¦Vå²'7FFR%Ò¢ÆÅö–FV×÷FVçBÒÆÂ‡v÷&¶W%²&F—7÷6—F–öâ%ÒÓÒ&–FV×÷FVçB"f÷"v÷&¶W"–â&F6…²'v÷&¶W'2%Ò¢W†—7F–æu÷F‡2Ò¶—FVÒævWB‚'F‚"’f÷"—FVÒ–âÖæ–fW7BævWB‚&'F–f7G2"ÂµÒ’–b—6–ç7Fæ6R†—FVÒÂF–7B—Ð¢f÷"v÷&¶W"–â&F6…²'v÷&¶W'2%Ó ¢f÷"æÖRÂf—6–&–Æ—G’Â'F–f7E÷G—R–â€¢‚&VF—B"Â'V&Æ–2"–bg&÷¦VâævWB‚'V&Æ–6F–öå÷&öf–ÆR"ÂV&Æ–6F–öå÷&öf–ÆUöf÷"†g&÷¦Vå²'7FFR%Ò’’ÓÒT$Ä”5ôUdÅTD”ôåô%D”d5E2VÇ6R'&—fFR"Âb'&ÆÆVÅ÷¶&F6…²vVF—Eö¶–æBu×ÕöVF—B"’À¢‚'&V6V—B"Â'&—fFR"Âb'&ÆÆVÅ÷¶&F6…²vVF—Eö¶–æBu×Õ÷&V6V—B"’À¢‚&÷VåöWf–FVæ6R"Â'&—fFR"Â&v—F‡V%ö÷Vå÷%öWf–FVæ6R"’À¢‚&ÖW&vUöWf–FVæ6R"Â'&—fFR"Â&v—F‡V%öÖW&vUöWf–FVæ6R"’À¢‚'V&Æ–5÷&W÷'B"Â'V&Æ–2"Âb'&ÆÆVÅ÷¶&F6…²vVF—Eö¶–æBu×Õ÷V&Æ–5÷&W÷'B"’À¢“ ¢÷WGWBÒv÷&¶W%²&6æöæ–6Â%Õ¶æÖUÐ¢&VÆF—fRÒ÷WGWBç&VÆF—fU÷Fò‡&ö÷B’æ5÷÷6—‚‚¢–b&VÆF—fR–âW†—7F–æu÷F‡3 ¢6öçF–çVP¢&V6÷&BÒ'F–f7E÷&V6÷&B†÷WGWBÂ&ö÷BÂVF—E÷7FvR†&F6…²&VF—Eö¶–æB%Ò’Â'F–f7E÷G—RÂf—6–&–Æ—G’Â7F×¢Öæ–fW7E²&'F–f7G2%ÒæVæB‡&V6÷&B¢7FFU²&'F–f7G2%ÒæVæB†FVW6÷’‡&V6÷&B’¢W†—7F–æu÷F‡2æFB‡&VÆF—fR¢7F—fUögFW"Ò6÷'FVB‡6WB‡&Wf–÷W6Ç•ö–çFVw&FVB’Â6WB†&F6…²&6‡Væµö–G2%Ò’¢–bÆÅö–FV×÷FVçC ¢7FvU÷7FGW2Ò7FFU²'7FvW2%Õ¶VF—E÷7FvR†&F6…²&VF—Eö¶–æB%Ò•Õ²'7FGW2%Ð¢&WV—&R‡7FvU÷7FGW2–â²&–å÷&öw&W72"Â&6ö×ÆWFVB'ÒÂ&–FV×÷FVçE÷7FvUöÖ—6ÖF6‚"Â$–FVçF–6Â6æöæ–6Â6‡Væ·2W†—7B'WBF†R7FvR—2æ÷B7F—fRö6ö×ÆWFVBâ"¢VÇ6S ¢Öæ–fW7E²&'F–f7G2%ÒÒ6÷'FVB†Öæ–fW7E²&'F–f7G2%ÒÂ¶W“ÖÆÖ&F—FVÓ¢—FVÕ²'F‚%Ò¢7FFU²&'F–f7G2%ÒÒ6÷'FVB‡7FFU²&'F–f7G2%ÒÂ¶W“ÖÆÖ&F—FVÓ¢—FVÕ²'F‚%Ò¢7FvU÷7FGW2Ò&6ö×ÆWFVB"–b6WB†7F—fUögFW"’ÓÒ6WB†g&÷¦Vå²&6‡Væ·2%Ò’VÇ6R&–å÷&öw&W72 ¢7FFU²'7FvW2%Õ¶VF—E÷7FvR†&F6…²&VF—Eö¶–æB%Ò•ÒÒ²'7FGW2#¢7FvU÷7FGW2Â'WFFVEöB#¢7F×Â&æ÷FW2#¢¶b$6ö÷&F–æF÷"Ö–çFVw&FVB¶ÆVâ†&F6…²wv÷&¶W'2uÒ—ÒW‡Æ–6—B&ÆÆVÂv÷&¶W"6VÆV7F–öâ‡2“²¶ÆVâ†7F—fUögFW"—Ò÷¶ÆVâ†g&÷¦Vå²v6‡Væ·2uÒ—Ò6‡Væ·266WFVBâ%×Ð¢7FFU²'WFFVEöB%ÒÒ7F× ¢Öæ–fW7E²'WFFVEöB%ÒÒ7F× ¢26†&VB6öçG&öÂ÷&FW&–ær—2â–çf&–çC¢Öæ–fW7Bf—'7BÂ7FFRÆ7Bà¢&WÆ6Uö'—FW5öFöÖ–2†g&÷¦Vå²&Öæ–fW7E÷F‚%ÒÂ§6öåö'—FW2†Öæ–fW7B’¢Öæ–fW7E÷&WÆ6VBÒG'VP¢&WÆ6Uö'—FW5öFöÖ–2†g&÷¦Vå²'7FFU÷F‚%ÒÂ§6öåö'—FW2‡7FFR’¢7FFU÷&WÆ6VBÒG'VP¢W'&÷'2ÂòÒfÆ–FFU÷7FFR‡7FFRÂ7FFU÷FƒÖg&÷¦Vå²'7FFU÷F‚%ÒÂ6†V6µöf–ÆW3ÕG'VRÂÖæ–fW7EöFö7VÖVçCÖÖæ–fW7B¢&WV—&R†æ÷BW'&÷'2Â&6æöæ–6Å÷fÆ–FF–öåöf–ÆVB"Â$–çFVw&FVB6æöæ–6ÂWfÇVF–öâf–ÆVBfÆ–FF–öââ"ÂW'&÷'2¢&Vg&W6†VBÒ²¢¦g&÷¦VâÂ¢¦ÆöEö6æöæ–6Å÷'Vâ†g&÷¦Vå²'7FFU÷F‚%Ò—Ð¢6†V6·ö–çBÒ'V–ÆEö7V×VÆF—fUö6†V6·ö–çB†6†V6·ö–çEö÷WGWBÂ&Vg&W6†VB¢w&—GFVâæVæB†6†V6·ö–çEö÷WGWB¢66÷VçF–ærÒ6ö×ÆWF–öåö66÷VçF–ær‡&Vg&W6†VBÂ&F6…²&VF—Eö¶–æB%ÒÂ&F6…²&¶–æEö–çWG2%Ò¢&WV—&R†66÷VçF–æu²&6ö×ÆWFR%ÒÓÒ‡7FvU÷7FGW2ÓÒ&6ö×ÆWFVB"’Â'7FvUö6ö×ÆWF–öåöÖ—6ÖF6‚"Â%7FvR7FGW2FöW2æ÷BÖF6‚W†7BgVÆÂÖ6‡Væ²öFVæöÖ–æF÷"66÷VçF–ærâ"¢Öæ–fW7EögFW%÷6†Ò6†#Seöf–ÆR†g&÷¦Vå²&Öæ–fW7E÷F‚%Ò¢7FFUögFW%÷6†Ò6†#Seöf–ÆR†g&÷¦Vå²'7FFU÷F‚%Ò¢–b&F6…²&VF—Eö¶–æB%ÒÓÒ&Æö6F÷"# ¢–FVçF—F–W2Ò²¢¦6ö÷&F–æF÷%ö–FVçF—G•÷7V'6WB†g&÷¦Vâ’Â&Æö6F÷%÷6¶WE÷6WE÷6†#Sb#¢&F6…²&¶–æEö–çWG2%Õ²'6†#Sb%×Ð¢6÷fW&vRÒ²&W‡V7FVEö6‡Væµö–G2#¢66÷VçF–æu²&W‡V7FVEö6‡Væµö–G2%ÒÂ'&Wf–÷W6Ç•ö–çFVw&FVEö6‡Væµö–G2#¢&Wf–÷W6Ç•ö–çFVw&FVBÂ'6VÆV7FVEö6‡Væµö–G2#¢&F6…²&6‡Væµö–G2%ÒÂ&7F—fUö6‡Væµö–G2#¢66÷VçF–æu²&7F—fUö6‡Væµö–G2%ÒÂ&Ö—76–æuö6‡Væµö–G2#¢66÷VçF–æu²&Ö—76–æuö6‡Væµö–G2%ÒÂ&W‡V7FVEö76–væÖVçG2#¢66÷VçF–æu²&W‡V7FVEö76–væÖVçG2%ÒÂ&66WFVEö76–væÖVçG2#¢66÷VçF–æu²&66WFVEö76–væÖVçG2%ÒÂ&GWÆ–6FUö76–væÖVçG2#¢Â&f÷&V–våö76–væÖVçG2#¢Ð¢&Vf—‚Ò$Ä$’ ¢VÇ6S ¢÷væW'6†—÷&V6÷&G2Ò·²&6‡Væµö–B#¢6‡Væ²Â'6†#Sb#¢v÷&·6WE²'v÷&·6WE÷6†#Sb%×Òf÷"6‡Væ²Âv÷&·6WB–â6÷'FVB†&F6…²&¶–æEö–çWG2%Õ²'v÷&·6WG2%Òæ—FV×2‚’•Ð¢÷væW'6†—÷6†Ò6†#Seö'—FW2†§6öâæGV×2†÷væW'6†—÷&V6÷&G2Â6÷'Eö¶W—3ÕG'VRÂ6W&F÷'3Ò‚"Â"Â#¢"’’æVæ6öFR‚'WFbÓ‚"’¢–FVçF—F–W2Ò²¢¦6ö÷&F–æF÷%ö–FVçF—G•÷7V'6WB†g&÷¦Vâ’Â&Ö—76–æuö66W75ö÷væW'6†—÷6†#Sb#¢÷væW'6†—÷6†Â&Æö6F÷%öVF—E÷6WE÷6†#Sb#¢&F6…²&¶–æEö–çWG2%Õ²&Æö6F÷%÷6WB%Õ²'6†#Sb%×Ð¢6÷fW&vRÒ²&W‡V7FVEö6‡Væµö–G2#¢66÷VçF–æu²&W‡V7FVEö6‡Væµö–G2%ÒÂ'&Wf–÷W6Ç•ö–çFVw&FVEö6‡Væµö–G2#¢&Wf–÷W6Ç•ö–çFVw&FVBÂ'6VÆV7FVEö6‡Væµö–G2#¢&F6…²&6‡Væµö–G2%ÒÂ&7F—fUö6‡Væµö–G2#¢66÷VçF–æu²&7F—fUö6‡Væµö–G2%ÒÂ&Ö—76–æuö6‡Væµö–G2#¢66÷VçF–æu²&Ö—76–æuö6‡Væµö–G2%ÒÂ&W‡V7FVE÷7V&¦V7G2#¢66÷VçF–æu²&W‡V7FVE÷7V&¦V7G2%ÒÂ&66WFVE÷7V&¦V7G2#¢66÷VçF–æu²&66WFVE÷7V&¦V7G2%ÒÂ&W‡V7FVE÷&VFW%÷F6·2#¢66÷VçF–æu²&W‡V7FVE÷&VFW%÷F6·2%ÒÂ&66WFVE÷&VFW%÷F6·2#¢66÷VçF–æu²&66WFVE÷&VFW%÷F6·2%ÒÂ&W‡V7FVE÷G&VFÖVçG2#¢66÷VçF–æu²&W‡V7FVE÷G&VFÖVçG2%ÒÂ&66WFVE÷G&VFÖVçG2#¢66÷VçF–æu²&66WFVE÷G&VFÖVçG2%ÒÂ&GWÆ–6FUö§VFvÖVçG2#¢Â&f÷&V–våö§VFvÖVçG2#¢Ð¢&Vf—‚Ò$Ô$’ ¢6VÆV7FVE÷v÷&¶W'2ÒµÐ¢f÷"v÷&¶W"–â&F6…²'v÷&¶W'2%Ó ¢6VÆV7FVE÷v÷&¶W'2æVæB‡°¢'VÆÅ÷&WVW7B#¢v÷&¶W%²&÷VåöWf–FVæ6R%Õ²'VÆÅ÷&WVW7B%ÒÂ'VÆÅ÷&WVW7E÷W&Â#¢v÷&¶W%²&÷VåöWf–FVæ6R%Õ²'VÆÅ÷&WVW7E÷W&Â%ÒÂ&6‡Væµö–B#¢v÷&¶W%²&6‡Væµö–B%ÒÀ¢'&V6V—E÷6†#Sb#¢v÷&¶W%²'&V6V—B%Õ²'&V6V—E÷6†#Sb%ÒÂ'&V6÷fW'•÷6†#Sb#¢v÷&¶W%²'&V6÷fW'’%Õ²&&6†—fU÷6†#Sb%ÒÂ'V&Æ–5÷&W÷'E÷6†#Sb#¢v÷&¶W%²'&W÷'Eöf–ÆU÷6†#Sb%ÒÂ'&—fFUö'F–f7E÷6†#Sb#¢v÷&¶W%²'&V6V—B%Õ²'&—fFUö'F–f7B%Õ²'6†#Sb%ÒÀ¢&÷VåöWf–FVæ6U÷6†#Sb#¢v÷&¶W%²&÷VåöWf–FVæ6U÷6†#Sb%ÒÂ&ÖW&vUöWf–FVæ6U÷6†#Sb#¢v÷&¶W%²&ÖW&vUöWf–FVæ6U÷6†#Sb%ÒÂ&†VEö6öÖÖ—B#¢v÷&¶W%²&÷VåöWf–FVæ6R%Õ²&†VEö6öÖÖ—B%ÒÂ&ÖW&vUö6öÖÖ—B#¢v÷&¶W%²&ÖW&vUöWf–FVæ6R%Õ²&ÖW&vUö6öÖÖ—B%ÒÂ&6æöæ–6Å÷F‚#¢v÷&¶W%²&6æöæ–6Â%Õ²&VF—B%Òç&VÆF—fU÷Fò‡&ö÷B’æ5÷÷6—‚‚’À¢Ò¢&W÷'BÒ°¢'66†VÖ÷fW'6–öâ#¢–çFVw&F–öå÷fW'6–öâ†&F6…²&VF—Eö¶–æB%Ò’Â&–çFVw&F–öåö–B#¢7F&ÆUö–FVçF–f–W"‡&Vf—‚Â²'6VÆV7FVB#¢²†—FVÕ²&6‡Væµö–B%ÒÂ—FVÕ²'&V6V—E÷6†#Sb%ÒÂ—FVÕ²&ÖW&vUöWf–FVæ6U÷6†#Sb%Ò’f÷"—FVÒ–â6VÆV7FVE÷v÷&¶W'5ÒÂ'7FFUö&Vf÷&R#¢7FFUö&Vf÷&U÷6†Ò’Â&–çFVw&F–öå÷6†#Sb#¢""Â&VF—Eö¶–æB#¢6W&–Æ—¦VEöVF—Eö¶–æB†&F6…²&VF—Eö¶–æB%Ò’À¢'7FGW2#¢&–FV×÷FVçB"–bÆÅö–FV×÷FVçBVÇ6R&–çFVw&FVEö6ö×ÆWFR"–b7FvU÷7FGW2ÓÒ&6ö×ÆWFVB"VÇ6R&–çFVw&FVE÷'F–Â"Â&–çFVw&FVEöB#¢7F×À¢&WfÇVF–öåö–B#¢g&÷¦Vå²'7FFR%Õ²&WfÇVF–öåö–B%ÒÂ&6æF–FFUö–B#¢g&÷¦Vå²&6æF–FFUö–B%ÒÂ&6æF–FFU÷&ö¦V7B#¢&F6…²'&ö¦V7B%ÒÂ&&6Uö'&æ6‚#¢&F6…²&&6Uö'&æ6‚%ÒÂ&–FVçF—F–W2#¢–FVçF—F–W2Â'6VÆV7FVE÷v÷&¶W'2#¢6VÆV7FVE÷v÷&¶W'2Â&6÷fW&vR#¢6÷fW&vRÀ¢'G&ç67F–öåö÷&FW"#¢²'fÆ–FFU÷6VÆV7FVEö&F6‚"Â'fW&–g•öÖW&vVE÷VÆÅ÷&WVW7G2"Â&ÖFW&–Æ—¦U÷&—fFUö'F–f7G2"Â'w&—FUö–çFVw&F–öå÷&÷fVææ6R"Â'WFFUöÖæ–fW7B"Â'WFFU÷7FFUöÆ7B"Â'fÆ–FFUö6æöæ–6ÅöWfÇVF–öâ"Â&7&VFUö7V×VÆF—fUö6†V6·ö–çB"Â&6öÖÖ—E÷6†&VEö6öçG&öÅööæ6R%ÒÀ¢&Öæ–fW7Eö&Vf÷&U÷6†#Sb#¢Öæ–fW7Eö&Vf÷&U÷6†Â&Öæ–fW7EögFW%÷6†#Sb#¢Öæ–fW7EögFW%÷6†Â'7FFUö&Vf÷&U÷6†#Sb#¢7FFUö&Vf÷&U÷6†Â'7FFUögFW%÷6†#Sb#¢7FFUögFW%÷6†Â'7FvU÷7FGW2#¢7FvU÷7FGW2Â&6†V6·ö–çB#¢6†V6·ö–çBÂ&&Væ6†Ö&µ÷&W÷6—F÷'•öÖöF–f–VB#¢fÇ6RÀ¢Ð¢&W÷'E²&–çFVw&F–öå÷6†#Sb%ÒÒ6æöæ–6Åö†6‚‡&W÷'BÂ&–çFVw&F–öå÷6†#Sb"¢&W÷'Eö÷WGWBÒF‚†&w2æ–çFVw&F–öå÷&W÷'B’ç&W6öÇfR‚’–b&w2æ–çFVw&F–öå÷&W÷'BVÇ6R&ö÷Bò'fÆ–FF–öâ"òb'¶&F6…²vVF—Eö¶–æBuÒç&WÆ6R‚uòrÂrÒr—ÒÖ&F6‚Ö–çFVw&F–öâç·&W÷'E²v–çFVw&F–öåö–Bu×Òæ§6öâ ¢&WV—&U÷6fUö÷WGWE÷F‚‡&W÷'Eö÷WGWBÂ&ö÷BÂ$&F6‚–çFVw&F–öâ&W÷'B"¢&WV—&R†æ÷B&W÷'Eö÷WGWBæW†—7G2‚’Â&÷WGWEöW†—7G2"Âb%&VgW6–ærFò÷fW'w&—FR·&W÷'Eö÷WGWGÒâ"¢w&—FUö§6öåöFöÖ–2‡&W÷'Eö÷WGWBÂ&W÷'B¢w&—GFVâæVæB‡&W÷'Eö÷WGWB¢&WGW&â²'&W÷'B#¢&W÷'BÂ'&W÷'E÷F‚#¢&W÷'Eö÷WGWBÂ&6†V6·ö–çE÷F‚#¢6†V6·ö–çEö÷WGWGÐ¢W†6WBW†6WF–öã ¢–b7FFU÷&WÆ6VC ¢&WÆ6Uö'—FW5öFöÖ–2†g&÷¦Vå²'7FFU÷F‚%ÒÂ÷&–v–æÅ÷7FFR¢–bÖæ–fW7E÷&WÆ6VC ¢&WÆ6Uö'—FW5öFöÖ–2†g&÷¦Vå²&Öæ–fW7E÷F‚%ÒÂ÷&–v–æÅöÖæ–fW7B¢f÷"÷WGWB–â&WfW'6VB‡w&—GFVâ“ ¢–b÷WGWBæ—5öf–ÆR‚“ ¢÷WGWBçVæÆ–æ²‚¢&—6P  ¦FVb6öÖÖæEö–çFVw&FUö&F6‚†&w3¢&w'6RäæÖW76R’ÓâæöæS ¢&W7VÇBÒ–çFVw&FUö&F6‚†&w2¢&W÷'BÒ&W7VÇE²'&W÷'B%Ð¢VÖ—B‡²&ö²#¢G'VRÂ&÷W&F–öâ#¢&–çFVw&FRÖ&F6‚"Â&VF—Eö¶–æB#¢&w2æVF—Eö¶–æBÂ'7FGW2#¢&W÷'E²'7FGW2%ÒÂ'7FvU÷7FGW2#¢&W÷'E²'7FvU÷7FGW2%ÒÂ'6VÆV7FVEö6‡Væµö–G2#¢&W÷'E²&6÷fW&vR%Õ²'6VÆV7FVEö6‡Væµö–G2%ÒÂ&Ö—76–æuö6‡Væµö–G2#¢&W÷'E²&6÷fW&vR%Õ²&Ö—76–æuö6‡Væµö–G2%ÒÂ&–çFVw&F–öå÷&W÷'B#¢7G"‡&W7VÇE²'&W÷'E÷F‚%Ò’Â&6†V6·ö–çB#¢7G"‡&W7VÇE²&6†V6·ö–çE÷F‚%Ò’Â&Öæ–fW7Eö&Vf÷&U÷7FFR#¢G'VRÂ'6†&VEö6öçG&öÅö6öÖÖ—E÷&WV—&VB#¢G'VWÒ  ¦FVb6öÖÖæEö6ö×ÆWF–öâ†&w3¢&w'6RäæÖW76R’ÓâæöæS ¢&w2æÆÆ÷uö6ö×ÆWFVEö&÷VæF'’ÒG'VP¢g&÷¦VâÒÆöEög&÷¦Våö–çWG2†&w2Â&w2æVF—Eö¶–æB¢–b&w2æVF—Eö¶–æBÓÒ&Æö6F÷"# ¢¶–æEö–çWG2ÒÆöE÷6¶WE÷6WB†&w2æÆö6F÷%÷6¶WB÷"µÒÂg&÷¦Vâ¢VÇ6S ¢¶–æEö–çWG2Ò²&Æö6F÷%÷6WB#¢ÆöEöÆö6F÷%öVF—E÷6WB†&w2æÆö6F÷%öVF—B÷"µÒÂg&÷¦Vâ’Â'v÷&·6WG2#¢'V–ÆEöÖ—76–æu÷v÷&·6WG2†g&÷¦Vâ—Ð¢66÷VçF–ærÒ6ö×ÆWF–öåö66÷VçF–ær†g&÷¦VâÂ&w2æVF—Eö¶–æBÂ¶–æEö–çWG2¢&V6÷&FVBÒg&÷¦Vå²'7FFR%Õ²'7FvW2%Õ¶VF—E÷7FvR†&w2æVF—Eö¶–æB•Õ²'7FGW2%Ð¢&WV—&R‚‡&V6÷&FVBÓÒ&6ö×ÆWFVB"’ÓÒ66÷VçF–æu²&6ö×ÆWFR%ÒÂ'7FvUö6ö×ÆWF–öåöÖ—6ÖF6‚"Â$6æöæ–6Â7FvR7FGW2F–ffW'2g&öÒW†7B6ö×ÆWF–öâ66÷VçF–ærâ"¢VÖ—B‡²&ö²#¢G'VRÂ&÷W&F–öâ#¢&6ö×ÆWF–öâ"Â&VF—Eö¶–æB#¢&w2æVF—Eö¶–æBÂ'&V6÷&FVE÷7FvU÷7FGW2#¢&V6÷&FVBÂ¢¦66÷VçF–æwÒ  ¦FVbFEög&÷¦Våö&wVÖVçG2‡'6W#¢&w'6Rä&wVÖVçE'6W"’ÓâæöæS ¢'6W"æFEö&wVÖVçB‚"Ò×7FFR"Â&WV—&VCÕG'VRÂ†VÇÒ$6æöæ–6ÂWfÇVF–öâ×7FFRæ§6öâ‡cB’â"¢'6W"æFEö&wVÖVçB‚"Ò×vRÖÖ"Â&WV—&VCÕG'VRÂ†VÇÒ$g&÷¦VâvRÖÖ×c¥4ôââ"¢'6W"æFEö&wVÖVçB‚"ÒÖ6‡Væ²ÖÖæ–fW7B"Â&WV—&VCÕG'VRÂ†VÇÒ$g&÷¦Vâ6‡Væ²ÖÖæ–fW7B×c¥4ôââ"¢'6W"æFEö&wVÖVçB‚"Ò×öÆ–7’"Â&WV—&VCÕG'VRÂ†VÇÒ$g&÷¦Vâ7V&¦V7BÖ–æFW‚ÖWfÇVF–öâ×öÆ–7’×c"¥4ôââ"¢'6W"æFEö&wVÖVçB‚"ÒÖ&Væ6†Ö&²"Â&WV—&VCÕG'VRÂ†VÇÒ$g&÷¦Vâ6÷W&6R×7V&¦V7BÖ&Væ6†Ö&²×c"¥4ôââ"¢'6W"æFEö&wVÖVçB‚"ÒÖ&Væ6†Ö&²ÖÆö6²"Â&WV—&VCÕG'VRÂ†VÇÒ$6æF–FFR&Væ6†Ö&²ÖÆö6²¥4ôââ"¢'6W"æFEö&wVÖVçB‚"ÒÖæ÷&ÖÆ—¦VBÖ6æF–FFR"Â&WV—&VCÕG'VRÂ†VÇÒ$–çFVw&FVB6æF–FFRÖ–æFW‚×c"¥4ôââ"¢'6W"æFEö&wVÖVçB‚"ÒÖ—FVÒÖ–çfVçF÷'’"Â&WV—&VCÕG'VRÂ†VÇÒ$–çFVw&FVB—FVÒÖ–çfVçF÷'’×c"¥4ôââ"  ¦FVbFE÷&V6öææV7F–öåö&wVÖVçG2‡'6W#¢&w'6Rä&wVÖVçE'6W"’ÓâæöæS ¢'6W"æFEö&wVÖVçB‚"Ò×6÷W&6RÖf–ÆR"Â&WV—&VCÕG'VRÂ†VÇÒ%&W7G&–7FVB6ö×ÆWFR6÷W&6R&V6öææV7FVB'’4„Ó#Sbâ"¢'6W"æFEö&wVÖVçB‚"Ò×6÷W&6RÖ6‡Væ²"Â&WV—&VCÕG'VRÂ†VÇÒ$W†7B&W7G&–7FVB6÷W&6R6‡Væ²â"¢'6W"æFEö&wVÖVçB‚"Ò×6÷W&6R×6–FV6""Â&WV—&VCÕG'VRÂ†VÇÒ$W†7B6÷W&6RÖ6‡Væ²vR6–FV6"â"  ¦FVbFE÷v÷&¶W%ö&wVÖVçG2‡'6W#¢&w'6Rä&wVÖVçE'6W"ÂVF—Eö¶–æC¢7G"’ÓâæöæS ¢FEög&÷¦Våö&wVÖVçG2‡'6W"¢FE÷&V6öææV7F–öåö&wVÖVçG2‡'6W"¢'6W"æFEö&wVÖVçB‚"ÒÖ6‡Væ²Ö–B"Â&WV—&VCÕG'VRÂ†VÇÒ$öæRW†7B4…Tä²Ò¢–FVçF–f–W"â"¢'6W"æFEö&wVÖVçB‚"ÒÖVF—B"Â&WV—&VCÕG'VRÂ†VÇÒ$ÖöFVÂÖWF†÷&VB6æöæ–6Âc&—fFRVF—B¥4ôââ"¢'6W"æFEö&wVÖVçB‚"Ò×&ö¦V7B"Â&WV—&VCÕG'VRÂ†VÇÒ$W†7BV&Æ–26æF–FFRv—D‡V"÷væW"÷&W÷6—F÷'’â"¢'6W"æFEö&wVÖVçB‚"Ò×&W÷6—F÷'’×7FFR"Â&WV—&VCÕG'VRÂ†VÇÒ$g&W6‚F—&V7Bv—D‡V"&W÷6—F÷'’×7FFRWf–FVæ6R¥4ôââ"¢'6W"æFEö&wVÖVçB‚"ÒÖ&6RÖ'&æ6‚"ÂFVfVÇCÒ&Ö–â"Â†VÇÒ$W‡V7FVB6æF–FFR&W÷6—F÷'’&6R'&æ6‚†FVfVÇC¢Ö–â’â"¢'6W"æFEö&wVÖVçB‚"ÒÖ'&æ6‚"Â†VÇÒ%v÷&¶W"'&æ6ƒ²–b7WÆ–VB—B×W7BWVÂF†RFWFW&Ö–æ—7F–2FVfVÇBâ"¢'6W"æFEö&wVÖVçB‚"Ò×&V6÷fW'’×&ö÷B"Â&WV—&VCÕG'VRÂ†VÇÒ%Væ—VRV×G’&—fFR6æF–FFRö6‡Væ²&V6÷fW'’&ö÷Bâ"¢'6W"æFEö&wVÖVçB‚"Ò×&V6÷fW'’×¦—"Â†VÇÒ%&—fFR&V6÷fW'’¤•÷WGWB†FVfVÇC¢&VæVF‚&V6÷fW'’&ö÷B’â"¢'6W"æFEö&wVÖVçB‚"Ò×&V6V—BÖ÷WGWB"Â†VÇÒ%&—fFR&V6V—B÷WGWB†FVfVÇC¢&VæVF‚&V6÷fW'’&ö÷B’â"¢'6W"æFEö&wVÖVçB‚"Ò×V&Æ–2Ö÷WGWB"Â&WV—&VCÕG'VRÂ†VÇÒ$W†7BÆÆ÷vÆ—7FVBvw&VvFR&W÷'B÷WGWB–â6æF–FFR&W÷6—F÷'’6†V6¶÷WBâ"¢–bVF—Eö¶–æBÓÒ&Æö6F÷"# ¢'6W"æFEö&wVÖVçB‚"ÒÖÆö6F÷"×6¶WB"Â&WV—&VCÕG'VRÂ†VÇÒ$W†7BÆö6F÷"ÖöæÇ’6¶WBf÷"F†—26‡Væ²â"¢VÇ6S ¢'6W"æFEö&wVÖVçB‚"ÒÖÆö6F÷"ÖVF—B"Â7F–öãÒ&VæB"Â&WV—&VCÕG'VRÂ†VÇÒ$6æöæ–6ÂÆö6F÷"VF—C²&WVBöæ6Rf÷"WfW'’g&÷¦Vâ6‡Væ²â"  ¦FVbFEö&F6…ö&wVÖVçG2‡'6W#¢&w'6Rä&wVÖVçE'6W"’ÓâæöæS ¢FEög&÷¦Våö&wVÖVçG2‡'6W"¢'6W"æFEö&wVÖVçB‚"ÒÖVF—BÖ¶–æB"Â6†ö–6W3×6÷'FVB„TD•Eô´”äE2’Â&WV—&VCÕG'VR¢'6W"æFEö&wVÖVçB‚"Ò×&ö¦V7B"Â&WV—&VCÕG'VRÂ†VÇÒ$W†7BV&Æ–26æF–FFRv—D‡V"÷væW"÷&W÷6—F÷'’â"¢'6W"æFEö&wVÖVçB‚"Ò×6VÆV7F–öâ"Â7F–öãÒ&VæB"Â&WV—&VCÕG'VRÂ†VÇÒ$W‡Æ–6—B6VÆV7FVB"U$Â÷"v÷&¶W"'&æ6ƒ²&WVBW"v÷&¶W"â"¢'6W"æFEö&wVÖVçB‚"Ò×v÷&¶W"Ö&–æF–ær"Â"ÒÖ&–æF–ær"ÂFW7CÒ'v÷&¶W%ö&–æF–ær"Â7F–öãÒ&VæB"Â&WV—&VCÕG'VRÂ†VÇÒ$W‡Æ–6—B&—fFR&V6V—B÷&V6÷fW'’÷V&Æ–2öWf–FVæ6R&–æF–æs²&WVBW"v÷&¶W"â"¢'6W"æFEö&wVÖVçB‚"ÒÖÆö6F÷"×6¶WB"Â7F–öãÒ&VæB"Â†VÇÒ$Æö6F÷"6¶WC²Æö6F÷"&F6†W2&WV—&RW†7B6÷fW&vRöbWfW'’g&÷¦Vâ6‡Væ²â"¢'6W"æFEö&wVÖVçB‚"ÒÖÆö6F÷"ÖVF—B"Â7F–öãÒ&VæB"Â†VÇÒ$6æöæ–6ÂÆö6F÷"VF—C²Ö—76–ærÖ66W72&F6†W2&WV—&RW†7B6÷fW&vRöbWfW'’g&÷¦Vâ6‡Væ²â"  ¦FVb'V–ÆE÷'6W"‚’Óâ&w'6Rä&wVÖVçE'6W# ¢'6W"Ò&w'6Rä&wVÖVçE'6W"†FW67&—F–öãÕõöFö5õò¢7V''6W'2Ò'6W"æFE÷7V''6W'2†FW7CÒ&÷W&F–öâ"Â&WV—&VCÕG'VR ¢Æö6F÷"Ò7V''6W'2æFE÷'6W"‚&'V–ÆBÖÆö6F÷"×v÷&¶W""Â†VÇÒ%fÆ–FFRöæR&—fFRÆö6F÷"VF—BæB7&VFR—G2—6öÆFVB&V6÷fW'’÷&V6V—B÷V&Æ–2&ö¦V7F–öââ"¢FE÷v÷&¶W%ö&wVÖVçG2†Æö6F÷"Â&Æö6F÷""¢Æö6F÷"ç6WEöFVfVÇG2††æFÆW#ÖÆÖ&F&w3¢6öÖÖæEö'V–ÆE÷v÷&¶W"†&w2Â&Æö6F÷""’ ¢Ö—76–ærÒ7V''6W'2æFE÷'6W"‚&'V–ÆBÖÖ—76–ærÖ66W72×v÷&¶W""Â†VÇÒ%fÆ–FFRöæR&—fFRÖ—76–ærÖ66W72VF—BgFW"gVÆÂ6æöæ–6ÂÆö6F÷"–çFVw&F–öââ"¢FE÷v÷&¶W%ö&wVÖVçG2†Ö—76–ærÂ&Ö—76–æuö66W72"¢Ö—76–ærç6WEöFVfVÇG2††æFÆW#ÖÆÖ&F&w3¢6öÖÖæEö'V–ÆE÷v÷&¶W"†&w2Â&Ö—76–æuö66W72"’ ¢V&Æ–2Ò7V''6W'2æFE÷'6W"‚'fÆ–FFR×V&Æ–2"Â†VÇÒ%fÆ–FFRF†RÆÆ÷vÆ—7FVBV&Æ–2'F–f7B6VÆV7FVB'’V&Æ–6F–öâ&öf–ÆRâ"¢V&Æ–2æFEö&wVÖVçB‚"Ò×&W÷'B"Â&WV—&VCÕG'VR¢V&Æ–2æFEö&wVÖVçB‚"ÒÖVF—BÖ¶–æB"Â6†ö–6W3×6÷'FVB„TD•Eô´”äE2’¢V&Æ–2æFEö&wVÖVçB‚"ÒÖ6‡Væ²Ö–B"¢V&Æ–2æFEö&wVÖVçB‚"Ò×V&Æ–6F–öâ×&öf–ÆR"Â6†ö–6W3×6÷'FVB…T$Ä”4D”ôåõ$ôd”ÄU2’¢V&Æ–2æFEö&wVÖVçB‚"ÒÖW‡V7FVB×F‚"Â†VÇÒ$W‡V7FVB&W÷6—F÷'’×&VÆF—fRÆÆ÷vÆ—7FVBF‚â"¢V&Æ–2ç6WEöFVfVÇG2††æFÆW#Ö6öÖÖæE÷fÆ–FFU÷V&Æ–2 ¢v÷&¶W"Ò7V''6W'2æFE÷'6W"‚'fÆ–FFR×v÷&¶W""Â†VÇÒ%fÆ–FFRöæR&V6V—BÂW†7BV&Æ–2&W÷'BÂæBW‡Æ–6—FÇ’–FVçF–f–VB&—fFR&V6÷fW'’&ö÷Bö&6†—fRâ"¢v÷&¶W"æFEö&wVÖVçB‚"Ò×&V6V—B"Â&WV—&VCÕG'VR¢v÷&¶W"æFEö&wVÖVçB‚"Ò×&V6÷fW'’×&ö÷B"Â&WV—&VCÕG'VR¢v÷&¶W"æFEö&wVÖVçB‚"Ò×&V6÷fW'’×¦—"¢v÷&¶W"æFEö&wVÖVçB‚"Ò×V&Æ–2×&W÷'B"Â&WV—&VCÕG'VR¢v÷&¶W"æFEö&wVÖVçB‚"ÒÖVF—BÖ¶–æB"Â6†ö–6W3×6÷'FVB„TD•Eô´”äE2’¢v÷&¶W"ç6WEöFVfVÇG2††æFÆW#Ö6öÖÖæE÷fÆ–FFU÷v÷&¶W" ¢&–æBÒ7V''6W'2æFE÷'6W"‚&&–æB×V&Æ–6F–öâ"Â†VÇÒ$&–æBöæRW‡Æ–6—B"ö'&æ6‚6VÆV7F–öâFòöæR&V6V—BÂ&V6÷fW'’&ö÷BÂ&W÷'BÂæB7W'&VçBÖGFV×B÷VâÕ"ö'6W'fF–öââ"¢&–æBæFEö&wVÖVçB‚"Ò×&V6V—B"Â&WV—&VCÕG'VR¢&–æBæFEö&wVÖVçB‚"Ò×&V6÷fW'’×&ö÷B"Â&WV—&VCÕG'VR¢&–æBæFEö&wVÖVçB‚"Ò×&V6÷fW'’×¦—"¢&–æBæFEö&wVÖVçB‚"Ò×V&Æ–2×&W÷'B"Â&WV—&VCÕG'VR¢&–æBæFEö&wVÖVçB‚"Ò×V&Æ–6F–öâÖWf–FVæ6R"Â&WV—&VCÕG'VR¢&–æBæFEö&wVÖVçB‚"Ò×6VÆV7F–öâ"Â†VÇÒ$W‡Æ–6—B"U$Â÷"v÷&¶W"'&æ6‚†FVfVÇC¢"U$Â–âWf–FVæ6R’â"¢&–æBæFEö&wVÖVçB‚"ÒÖ÷WGWB"Â&WV—&VCÕG'VRÂ†VÇÒ%&—fFR6æF–FFRÖVF—BÖ–çFVw&F–öâÖ&–æF–ær×c÷WGWBâ"¢&–æBç6WEöFVfVÇG2††æFÆW#Ö6öÖÖæEö&–æE÷V&Æ–6F–öâ ¢&VfÆ–v‡BÒ7V''6W'2æFE÷'6W"‚'&VfÆ–v‡BÖ&F6‚"Â†VÇÒ%G&ç67F–öæÆÇ’fÆ–FFRâW‡Æ–6—B6VÆV7FVB&F6‚v—F†÷WB×WFF–öâ÷"7vVW–ærâ"¢FEö&F6…ö&wVÖVçG2‡&VfÆ–v‡B¢&VfÆ–v‡Bç6WEöFVfVÇG2††æFÆW#Ö6öÖÖæE÷&VfÆ–v‡Eö&F6‚ ¢–çFVw&FRÒ7V''6W'2æFE÷'6W"‚&–çFVw&FRÖ&F6‚"Â†VÇÒ$–çFVw&FRâÇ&VG’×&VfÆ–v‡FVBW‡Æ–6—B&F6‚gFW"7W'&VçBÖGFV×BÖW&vVBÕ"Wf–FVæ6Râ"¢FEö&F6…ö&wVÖVçG2†–çFVw&FR¢–çFVw&FRæFEö&wVÖVçB‚"ÒÖÖW&vRÖWf–FVæ6R"Â7F–öãÒ&VæB"Â&WV—&VCÕG'VRÂ†VÇÒ$g&W6‚F—&V7BÖW&vVBÕ"Wf–FVæ6S²&WVBW"6VÆV7FVBv÷&¶W"â"¢–çFVw&FRæFEö&wVÖVçB‚"ÒÖ6†V6·ö–çBÖ÷WGWB"Â&WV—&VCÕG'VRÂ†VÇÒ$æWr7V×VÆF—fR&—fFR6†V6·ö–çB¤•&VæVF‚WfÇVF–öâ&ö÷Bâ"¢–çFVw&FRæFEö&wVÖVçB‚"ÒÖ–çFVw&F–öâ×&W÷'B"Â†VÇÒ%&—fFR&F6‚–çFVw&F–öâ&W÷'B÷WGWB&VæVF‚WfÇVF–öâ&ö÷Bâ"¢–çFVw&FRç6WEöFVfVÇG2††æFÆW#Ö6öÖÖæEö–çFVw&FUö&F6‚ ¢6ö×ÆWF–öâÒ7V''6W'2æFE÷'6W"‚&6ö×ÆWF–öâ"Â†VÇÒ%&V6ö×WFRW†7B'F–ÂögVÆÂ6æöæ–6Â7FvR6ö×ÆWF–öâv—F†÷WB×WFF–öââ"¢FEög&÷¦Våö&wVÖVçG2†6ö×ÆWF–öâ¢6ö×ÆWF–öâæFEö&wVÖVçB‚"ÒÖVF—BÖ¶–æB"Â6†ö–6W3×6÷'FVB„TD•Eô´”äE2’Â&WV—&VCÕG'VR¢6ö×ÆWF–öâæFEö&wVÖVçB‚"ÒÖÆö6F÷"×6¶WB"Â7F–öãÒ&VæB"Â†VÇÒ$Æö6F÷"6¶WC²Æö6F÷"6ö×ÆWF–öâ&WV—&W2WfW'’g&÷¦Vâ6‡Væ²â"¢6ö×ÆWF–öâæFEö&wVÖVçB‚"ÒÖÆö6F÷"ÖVF—B"Â7F–öãÒ&VæB"Â†VÇÒ$6æöæ–6ÂÆö6F÷"VF—C²Ö—76–ærÖ66W726ö×ÆWF–öâ&WV—&W2WfW'’g&÷¦Vâ6‡Væ²â"¢6ö×ÆWF–öâç6WEöFVfVÇG2††æFÆW#Ö6öÖÖæEö6ö×ÆWF–öâ¢&WGW&â'6W   ¦FVbÖ–â‚’ÓâæöæS ¢'6W"Ò'V–ÆE÷'6W"‚¢&w2Ò'6W"ç'6Uö&w2‚¢G'“ ¢&w2æ†æFÆW"†&w2¢W†6WB&W&F–öäW'&÷"2W†3 ¢–ÆöC¢F–7E·7G"Âç•ÒÒ²&ö²#¢fÇ6RÂ&W'&÷"#¢²&6öFR#¢W†2æ6öFRÂ&ÖW76vR#¢W†2æÖW76vW×Ð¢–bW†2æFWF–Ç2—2æ÷BæöæS ¢–ÆöE²&W'&÷"%Õ²&FWF–Ç2%ÒÒW†2æFWF–Ç0¢VÖ—B‡–ÆöBÂ  ¦–bõöæÖUõòÓÒ%õöÖ–åõò# ¢Ö–â‚ 