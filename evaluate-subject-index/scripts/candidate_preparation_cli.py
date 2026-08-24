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


def require_timestamp(value: Any, field: str, max_age_hours: int | None = None) -> datetime:
    require(isinstance(value, str) and value, "invalid_timestamp", f"{field} must be an ISO-8601 timestamp.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PreparationError("invalid_timestamp", f"{field} must be an ISO-8601 timestamp.") from exc
    require(parsed.tzinfo is not None, "invalid_timestamp", f"{field} must include a timezone.")
    parsed = parsed.astimezone(timezone.utc)
    if max_age_hours is not None:
        age_seconds = (datetime.now(timezone.utc) - parsed).total_seconds()
        require(age_seconds >= -300, "evidence_from_future", f"{field} is implausibly far in the future.")
        require(age_seconds <= max_age_hours * 3600, "stale_evidence", f"{field} is older than {max_age_hours} hours; refresh the GitHub evidence.")
    return parsed


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
    normalized = re.sub(r"[‐‑‒–—−]", "-", normalized)
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
            f"{field}: {record['status']} — {record['rationale']}"
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
    require(isinstance(receipt.get("candidate_id"), str) and bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", receipt["candidate_id"])), "receipt_identity", "Receipt candidate_id must be a bounded safe identifier.")
    require_sha256(receipt.get("candidate_sha256"), "receipt.candidate_sha256")
    source_identity = exact(receipt.get("source_identity"), {"sha256", "edition"}, "receipt.source_identity")
    require_sha256(source_identity.get("sha256"), "receipt.source_identity.sha256")
    require(isinstance(source_identity.get("edition"), str) and bool(source_identity["edition"].strip()), "receipt_identity", "Receipt source edition is required.")
    for field in ("page_map_sha256", "chunk_manifest_sha256"):
        require_sha256(receipt.get(field), f"receipt.{field}")
    policy_identity = exact(receipt.get("policy_identity"), {"profile", "sha256", "rubric_version", "audit_mode"}, "receipt.policy_identity")
    require(isinstance(policy_identity.get("profile"), str) and bool(policy_identity["profile"].strip()), "receipt_schema", "Receipt policy profile is required.")
    require_sha256(policy_identity.get("sha256"), "receipt.policy_identity.sha256")
    require(policy_identity.get("rubric_version") == "subject-index-rubric-v4" and policy_identity.get("audit_mode") in {"full", "pilot"}, "receipt_schema", "Receipt policy rubric or audit mode is invalid.")
    adapter = exact(receipt.get("adapter_identity"), {"requested_id", "id", "version", "selection_reason", "selection_evidence"}, "receipt.adapter_identity")
    require(
        isinstance(adapter.get("requested_id"), str) and bool(re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", adapter["requested_id"]))
        and isinstance(adapter.get("id"), str) and bool(re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", adapter["id"]))
        and isinstance(adapter.get("version"), str) and bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,31}", adapter["version"]))
        and isinstance(adapter.get("selection_reason"), str) and bool(re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", adapter["selection_reason"]))
        and isinstance(adapter.get("selection_evidence"), dict),
        "receipt_schema",
        "Receipt adapter identity is invalid.",
    )
    provenance = receipt.get("provenance")
    exact(provenance, set(PROVENANCE_FIELDS), "receipt.provenance")
    for field in PROVENANCE_FIELDS:
        finding = provenance[field]
        require(isinstance(finding, dict) and {"status", "rationale"}.issubset(finding) and set(finding).issubset({"status", "rationale", "evidence", "claimed_original_publisher_pdf"}), "receipt_schema", f"receipt.provenance.{field} has an invalid shape.")
        if "evidence" in finding:
            require(isinstance(finding["evidence"], list) and all(isinstance(item, str) for item in finding["evidence"]), "receipt_schema", f"receipt.provenance.{field}.evidence must be an array of strings.")
        if "claimed_original_publisher_pdf" in finding:
            require(field == "authoritative_copy_fidelity" and isinstance(finding["claimed_original_publisher_pdf"], bool), "receipt_schema", "Only authoritative_copy_fidelity may carry a boolean claimed_original_publisher_pdf field.")
    private_artifacts = receipt.get("private_artifacts")
    require(isinstance(private_artifacts, list) and len(private_artifacts) == len(PRIVATE_ARTIFACT_KEYS), "receipt_private_inventory", "Receipt must list exactly eight private artifacts.")
    for item in private_artifacts:
        exact(item, {"artifact", "archive_path", "sha256"}, "receipt.private_artifacts[]")
        require(item.get("artifact") in PRIVATE_ARTIFACT_KEYS, "receipt_private_inventory", "Receipt private artifact name is invalid.")
        safe_relative_path(str(item.get("archive_path", "")))
        require_sha256(item.get("sha256"), f"receipt.private_artifacts[{item.get('artifact')}].sha256")
    require({item["artifact"] for item in private_artifacts} == set(PRIVATE_ARTIFACT_KEYS), "receipt_private_inventory", "Receipt private artifacts must identify every allowed artifact exactly once.")
    private_recovery = exact(receipt.get("private_recovery"), {"purpose", "sha256", "byte_length", "bundle_metadata_sha256", "checkpoint_ref"}, "receipt.private_recovery")
    require(private_recovery.get("purpose") == "candidate_preparation_recovery_only", "receipt_schema", "Receipt private recovery purpose is invalid.")
    require_sha256(private_recovery.get("sha256"), "receipt.private_recovery.sha256")
    require_sha256(private_recovery.get("bundle_metadata_sha256"), "receipt.private_recovery.bundle_metadata_sha256")
    require(isinstance(private_recovery.get("byte_length"), int) and not isinstance(private_recovery.get("byte_length"), bool) and 0 <= private_recovery["byte_length"] <= MAX_RECOVERY_ARCHIVE_BYTES, "receipt_schema", "Receipt recovery byte length is invalid.")
    require(isinstance(private_recovery.get("checkpoint_ref"), str) and bool(private_recovery["checkpoint_ref"].strip()), "receipt_schema", "Receipt recovery checkpoint reference is required.")
    public = exact(receipt.get("public_projection"), {"changed_paths", "hashes", "outgoing_safety_scan"}, "receipt.public_projection")
    require(set(public.get("changed_paths", [])) == PUBLIC_PATHS, "receipt_public_inventory", "Receipt public changed paths differ from the exact allowlist.")
    exact(public.get("hashes"), set(PUBLIC_PATHS), "receipt.public_projection.hashes")
    require(public.get("outgoing_safety_scan") == "passed", "receipt_schema", "Receipt public outgoing scan status is invalid.")
    for relative, digest in public.get("hashes", {}).items():
        require_sha256(digest, f"receipt.public_projection.hashes[{relative}]")
    require(receipt.get("file_origin") in {"delivered_pdf", "reconstructed_pdf", "transcription"}, "receipt_provenance", "Receipt file_origin is invalid.")
    provenance_errors = validate_provenance(receipt.get("provenance", {}), receipt["file_origin"])
    require(not provenance_errors, "receipt_provenance", "Receipt provenance is invalid.", provenance_errors)
    require(receipt.get("provenance", {}).get("candidate_bytes", {}).get("status") == "verified", "receipt_candidate_bytes", "Receipt must bind verified candidate bytes.")
    repositories = receipt.get("repositories")
    repository_keys = {
        "candidate_project", "benchmark_project", "candidate_base_commit", "candidate_default_branch",
        "worker_branch", "repository_mode", "bootstrap_exception", "benchmark_preparation_base_commit",
    }
    if receipt.get("status") == "published_unmerged" and isinstance(repositories, dict) and repositories.get("bootstrap_exception"):
        repository_keys.update({"bootstrap_commit", "bootstrap_evidence_sha256"})
    exact(repositories, repository_keys, "receipt.repositories")
    require(isinstance(repositories.get("bootstrap_exception"), bool), "receipt_schema", "receipt.repositories.bootstrap_exception must be boolean.")
    require_github_project(repositories.get("candidate_project"), "receipt.repositories.candidate_project")
    require_github_project(repositories.get("benchmark_project"), "receipt.repositories.benchmark_project")
    require_commit(repositories.get("benchmark_preparation_base_commit"), "receipt.repositories.benchmark_preparation_base_commit")
    require(repositories.get("worker_branch") == default_worker_branch(receipt["candidate_id"]), "receipt_branch", "Receipt worker branch is invalid.")
    require(isinstance(repositories.get("candidate_default_branch"), str) and bool(repositories["candidate_default_branch"].strip()), "receipt_schema", "Receipt candidate default branch is required.")
    expected_mode = "bootstrap_main_readme_gitignore_then_worker_branch" if repositories.get("bootstrap_exception") else "branch_from_existing_default_head"
    require(repositories.get("repository_mode") == expected_mode, "receipt_schema", "Receipt repository mode is inconsistent with bootstrap_exception.")
    if repositories.get("bootstrap_exception"):
        require(repositories.get("candidate_default_branch") == "main", "receipt_schema", "Bootstrap receipts must target main.")
    if repositories.get("bootstrap_exception") and receipt.get("status") == "ready_for_pull_request":
        require(repositories.get("candidate_base_commit") is None, "receipt_schema", "Unpublished bootstrap receipt must not claim a base commit.")
    elif not repositories.get("bootstrap_exception"):
        require_commit(repositories.get("candidate_base_commit"), "receipt.repositories.candidate_base_commit")
    benchmark_lock = exact(receipt.get("benchmark_lock"), {"status", "final_commit", "benchmark_sha256"}, "receipt.benchmark_lock")
    require(benchmark_lock.get("status") == "pending_final_benchmark", "premature_benchmark_lock", "Worker receipt must retain a pending benchmark lock.")
    require(benchmark_lock.get("final_commit") is None and benchmark_lock.get("benchmark_sha256") is None, "premature_benchmark_lock", "Pending worker receipt must not contain final benchmark content or hash.")
    qa = exact(receipt.get("qa"), {"mode", "exact_set_gate", "candidate_quality_judgments_performed"}, "receipt.qa")
    require(qa == {"mode": "full", "exact_set_gate": "passed", "candidate_quality_judgments_performed": False}, "receipt_schema", "Receipt QA gate is invalid.")
    require(isinstance(receipt.get("limitations"), list) and all(isinstance(item, str) for item in receipt["limitations"]), "receipt_schema", "Receipt limitations must be an array of strings.")
    publication = receipt.get("publication")
    if receipt.get("status") == "ready_for_pull_request":
        exact(publication, {"status", "pull_request", "head_commit"}, "receipt.publication")
        require(publication == {"status": "not_yet_published", "pull_request": None, "head_commit": None}, "receipt_schema", "Ready receipt publication state is invalid.")
    if receipt.get("status") == "published_unmerged":
        publication = exact(publication, {"status", "pull_request", "pull_request_url", "branch", "base_branch", "base_commit", "head_commit", "changed_paths", "file_sha256", "blob_sha", "commit_count", "evidence_sha256", "observed_at", "outgoing_safety_scan"}, "receipt.publication")
        require(publication.get("status") == "open_unmerged", "receipt_publication", "Published receipt must describe an open unmerged pull request.")
        require_commit(publication.get("head_commit"), "receipt.publication.head_commit")
        require_commit(publication.get("base_commit"), "receipt.publication.base_commit")
        require(isinstance(publication.get("pull_request"), int) and not isinstance(publication.get("pull_request"), bool) and publication["pull_request"] > 0, "receipt_publication", "Published receipt pull request is invalid.")
        require(publication.get("branch") == repositories.get("worker_branch"), "receipt_publication", "Published receipt branch differs from repository identity.")
        require(publication.get("base_branch") == repositories.get("candidate_default_branch"), "receipt_publication", "Published receipt base branch differs from repository identity.")
        require(publication.get("base_commit") == repositories.get("candidate_base_commit"), "receipt_publication", "Published receipt base commit differs from repository identity.")
        require(isinstance(publication.get("commit_count"), int) and not isinstance(publication.get("commit_count"), bool) and publication.get("commit_count") == 1, "receipt_publication", "Published receipt must bind exactly one worker commit.")
        require(set(publication.get("changed_paths", [])) == PUBLIC_PATHS, "receipt_publication", "Published receipt changed paths differ from the exact allowlist.")
        require(publication.get("file_sha256") == public.get("hashes"), "receipt_publication", "Published receipt file hashes differ from the public projection.")
        exact(publication.get("blob_sha"), set(PUBLIC_PATHS), "receipt.publication.blob_sha")
        for relative, blob_sha in publication.get("blob_sha", {}).items():
            require(isinstance(blob_sha, str) and bool(re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", blob_sha)), "receipt_publication", f"Published receipt blob identity is invalid for {relative}.")
        require_sha256(publication.get("evidence_sha256"), "receipt.publication.evidence_sha256")
        require_timestamp(publication.get("observed_at"), "receipt.publication.observed_at")
        require(publication.get("outgoing_safety_scan") == "passed", "receipt_publication", "Published receipt outgoing scan status is invalid.")
        expected_url = f"https://github.com/{repositories.get('candidate_project')}/pull/{publication['pull_request']}"
        require(publication.get("pull_request_url") == expected_url, "receipt_publication", "Published receipt pull request URL is inconsistent.")
        if repositories.get("bootstrap_exception"):
            require_commit(repositories.get("bootstrap_commit"), "receipt.repositories.bootstrap_commit")
            require_sha256(repositories.get("bootstrap_evidence_sha256"), "receipt.repositories.bootstrap_evidence_sha256")
            require(repositories.get("bootstrap_commit") == repositories.get("candidate_base_commit"), "receipt_publication", "Bootstrap commit differs from the recorded candidate base commit.")
    return receipt


def load_receipt(path: Path, allowed_statuses: set[str] | None = None) -> dict[str, Any]:
    receipt = load_json(path, "Candidate preparation receipt")
    return validate_receipt_document(receipt, allowed_statuses)


def command_bind_publication(args: argparse.Namespace) -> None:
    receipt_path = Path(args.receipt).resolve()
    receipt = load_receipt(receipt_path, {"ready_for_pull_request"})
    documents, public_bytes, actual_hashes = load_public_directory_snapshot(Path(args.public_dir))
    errors = validate_public_documents(documents)
    require(not errors, "public_projection_invalid", "Public projection failed its final outgoing scan.", errors)
    require(actual_hashes == receipt.get("public_projection", {}).get("hashes"), "public_hash_mismatch", "Published public files differ from the worker receipt.")
    evidence, _, evidence_sha256 = load_json_snapshot(Path(args.publication_evidence), "GitHub publication evidence")
    require(evidence.get("schema_version") == "candidate-preparation-publication-evidence-v1", "publication_evidence_schema", "Expected candidate-preparation-publication-evidence-v1.")
    required_evidence_keys = {
        "schema_version", "evidence_source", "candidate_project", "pull_request", "pull_request_url",
        "state", "merged", "base_branch", "base_commit", "head_branch", "head_commit",
        "commit_count", "changed_files", "bootstrap", "observed_at",
    }
    require(set(evidence) == required_evidence_keys, "publication_evidence_shape", "GitHub publication evidence has missing or unexpected properties.")
    require(evidence.get("evidence_source") == "github_api", "publication_evidence_source", "Publication evidence must be derived from the GitHub API.")
    require(evidence.get("candidate_project") == receipt.get("repositories", {}).get("candidate_project"), "publication_project_mismatch", "Published repository differs from the worker receipt.")
    require(evidence.get("state") == "open" and evidence.get("merged") is False, "publication_state", "Worker pull request must be open and unmerged when bound.")
    require(evidence.get("base_branch") == receipt.get("repositories", {}).get("candidate_default_branch"), "publication_base_branch", "Pull request targets the wrong base branch.")
    expected_branch = receipt.get("repositories", {}).get("worker_branch")
    require(evidence.get("head_branch") == expected_branch, "publication_branch_mismatch", "Published branch differs from the worker receipt.")
    require(isinstance(evidence.get("commit_count"), int) and not isinstance(evidence.get("commit_count"), bool) and evidence.get("commit_count") == 1, "publication_commit_count", "Worker branch must contain exactly one preparation commit above its base.")
    head_commit = require_commit(evidence.get("head_commit"), "publication_evidence.head_commit")
    base_commit = receipt.get("repositories", {}).get("candidate_base_commit")
    if receipt.get("repositories", {}).get("bootstrap_exception"):
        base_commit = require_commit(evidence.get("base_commit"), "publication_evidence.base_commit")
        bootstrap_evidence_sha256 = validate_bootstrap_evidence(evidence.get("bootstrap"), receipt, base_commit, evidence.get("observed_at"))
        receipt["repositories"]["candidate_base_commit"] = base_commit
        receipt["repositories"]["bootstrap_commit"] = base_commit
        receipt["repositories"]["bootstrap_evidence_sha256"] = bootstrap_evidence_sha256
    else:
        require(require_commit(evidence.get("base_commit"), "publication_evidence.base_commit") == base_commit, "base_commit_mismatch", "Published base commit differs from the worker plan.")
        validate_bootstrap_evidence(evidence.get("bootstrap"), receipt, base_commit, evidence.get("observed_at"))
    require(head_commit != base_commit, "empty_worker_commit", "Worker head commit must differ from the base commit.")
    pull_request = evidence.get("pull_request")
    require(isinstance(pull_request, int) and not isinstance(pull_request, bool) and pull_request > 0, "invalid_pull_request", "Pull request number must be positive.")
    expected_url = f"https://github.com/{evidence['candidate_project']}/pull/{pull_request}"
    require(evidence.get("pull_request_url") == expected_url, "invalid_pull_request_url", "Pull request URL does not match the evidenced repository and number.")
    changed_files = evidence.get("changed_files")
    require(isinstance(changed_files, list) and len(changed_files) == len(PUBLIC_PATHS), "public_allowlist_mismatch", "GitHub publication evidence must contain exactly three changed files.")
    changed_paths: list[str] = []
    blob_hashes: dict[str, str] = {}
    evidenced_hashes: dict[str, str] = {}
    for item in changed_files:
        require(isinstance(item, dict) and set(item) == {"path", "blob_sha", "file_sha256"}, "publication_evidence_shape", "Every changed-file evidence record must contain path, blob_sha, and file_sha256 only.")
        relative = safe_relative_path(str(item.get("path", "")))
        require(isinstance(item.get("blob_sha"), str) and bool(re.fullmatch(r"[a-fA-F0-9]{40}|[a-fA-F0-9]{64}", item["blob_sha"])), "publication_blob_sha", f"Git blob identity is invalid for {relative}.")
        digest = require_sha256(item.get("file_sha256"), f"publication_evidence.changed_files[{relative}].file_sha256")
        changed_paths.append(relative)
        blob_hashes[relative] = item["blob_sha"].lower()
        evidenced_hashes[relative] = digest
    require(len(set(changed_paths)) == len(PUBLIC_PATHS) and set(changed_paths) == PUBLIC_PATHS, "public_allowlist_mismatch", "The pull request changed paths must equal the exact allowlist.", {"expected": sorted(PUBLIC_PATHS), "actual": sorted(changed_paths)})
    for relative, blob_sha in blob_hashes.items():
        require(git_blob_sha_bytes(public_bytes[relative], blob_sha) == blob_sha, "publication_blob_sha", f"Git blob identity does not recompute from the exact public bytes for {relative}.")
    require(evidenced_hashes == actual_hashes, "publication_file_hash_mismatch", "GitHub-evidenced file bytes differ from the validated public projection.")
    require_timestamp(evidence.get("observed_at"), "publication_evidence.observed_at", max_age_hours=24)
    receipt["status"] = "published_unmerged"
    receipt["publication"] = {
        "status": "open_unmerged",
        "pull_request": pull_request,
        "pull_request_url": evidence["pull_request_url"],
        "branch": expected_branch,
        "base_branch": evidence["base_branch"],
        "base_commit": base_commit,
        "head_commit": head_commit,
        "changed_paths": sorted(changed_paths),
        "file_sha256": evidenced_hashes,
        "blob_sha": blob_hashes,
        "commit_count": evidence["commit_count"],
        "evidence_sha256": evidence_sha256,
        "observed_at": evidence["observed_at"],
        "outgoing_safety_scan": "passed",
    }
    receipt["receipt_sha256"] = canonical_hash(receipt, "receipt_sha256")
    output = Path(args.output).resolve()
    require(not output.exists() or args.force or output == receipt_path, "output_exists", f"Refusing to overwrite {output}")
    save_json(output, receipt)
    emit({
        "command": "bind-candidate-preparation-publication",
        "ok": True,
        "candidate_id": receipt["candidate_id"],
        "branch": expected_branch,
        "pull_request": pull_request,
        "head_commit": head_commit,
        "changed_paths": changed_paths,
        "receipt": {"path": str(output), "sha256": sha256_file(output), "canonical_sha256": receipt["receipt_sha256"]},
        "merge_performed": False,
        "next_actions": ["preflight-integration"],
        "warnings": receipt.get("limitations", []),
    })


def _zip_member_is_symlink(info: zipfile.ZipInfo) -> bool:
    return ((info.external_attr >> 16) & 0o170000) == 0o120000


def validate_recovery_zip(path: Path, receipt: dict[str, Any]) -> dict[str, bytes]:
    path = path.resolve()
    require(path.is_file() and not path.is_symlink(), "recovery_file_type", "Private recovery ZIP must be a regular file.")
    expected_records = receipt.get("private_artifacts") if isinstance(receipt.get("private_artifacts"), list) else []
    require(
        len(expected_records) == len(PRIVATE_ARTIFACT_KEYS)
        and {item.get("artifact") for item in expected_records if isinstance(item, dict)} == set(PRIVATE_ARTIFACT_KEYS),
        "receipt_private_inventory",
        "Receipt must identify every private preparation artifact exactly once.",
    )
    expected = {item.get("archive_path"): item for item in expected_records if isinstance(item, dict)}
    expected_archive_paths = {
        template.format(candidate_id=normalize_candidate_id(receipt["candidate_id"]))
        for template in PRIVATE_ARCHIVE_PATHS.values()
    }
    require(set(expected) == expected_archive_paths, "receipt_private_inventory", "Receipt private archive paths differ from the purpose-specific allowlist.")
    metadata_name = "candidate-preparation-bundle-metadata.json"
    expected_names = set(expected) | {metadata_name}
    members: dict[str, bytes] = {}
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as recovery_handle:
        file_status = os.fstat(recovery_handle.fileno())
        require(stat.S_ISREG(file_status.st_mode), "recovery_file_type", "Private recovery ZIP must be a regular file.")
        archive_size = file_status.st_size
        require(archive_size <= MAX_RECOVERY_ARCHIVE_BYTES, "recovery_archive_too_large", "Private recovery ZIP exceeds the compressed archive-size limit.")
        require(archive_size == receipt.get("private_recovery", {}).get("byte_length"), "recovery_length_mismatch", "Private recovery ZIP byte length differs from the receipt.")
        digest = hashlib.sha256()
        for block in iter(lambda: recovery_handle.read(1024 * 1024), b""):
            digest.update(block)
        require(digest.hexdigest() == receipt.get("private_recovery", {}).get("sha256"), "recovery_hash_mismatch", "Private recovery ZIP does not match the selected receipt.")
        recovery_handle.seek(0)
        with zipfile.ZipFile(recovery_handle, "r") as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            require(len(names) == len(set(names)), "duplicate_recovery_member", "Private recovery ZIP contains duplicate members.")
            require(set(names) == expected_names, "recovery_inventory_mismatch", "Private recovery ZIP inventory differs from the receipt.", {"expected": sorted(expected_names), "actual": sorted(names)})
            total_uncompressed = 0
            for info in infos:
                safe_relative_path(info.filename)
                require(not info.is_dir() and not _zip_member_is_symlink(info), "unsafe_recovery_member", f"Unsupported recovery member: {info.filename}")
                require(info.filename.endswith(".json"), "unsafe_recovery_member", "Private recovery ZIP may contain JSON artifacts only.")
                require(info.file_size <= MAX_RECOVERY_MEMBER_BYTES, "recovery_member_too_large", f"Private recovery member exceeds the size limit: {info.filename}")
                total_uncompressed += info.file_size
                require(total_uncompressed <= MAX_RECOVERY_TOTAL_BYTES, "recovery_bundle_too_large", "Private recovery ZIP exceeds the total uncompressed-size limit.")
                if info.file_size:
                    require(info.compress_size > 0, "unsafe_recovery_compression", f"Private recovery member has an invalid compressed size: {info.filename}")
                    require(info.file_size / info.compress_size <= MAX_RECOVERY_COMPRESSION_RATIO, "unsafe_recovery_compression", f"Private recovery member exceeds the compression-ratio limit: {info.filename}")
                members[info.filename] = archive.read(info.filename)
    for name, record in expected.items():
        require(sha256_bytes(members[name]) == record.get("sha256"), "private_artifact_hash_mismatch", f"Private recovery artifact differs from receipt: {name}")
    try:
        metadata = json.loads(members[metadata_name].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PreparationError("invalid_recovery_metadata", f"Private recovery metadata is invalid: {exc}") from exc
    require(isinstance(metadata, dict) and metadata.get("schema_version") == "candidate-preparation-recovery-bundle-v1", "recovery_metadata_schema", "Private recovery metadata schema is invalid.")
    metadata_keys = {
        "schema_version", "bundle_metadata_sha256", "candidate_id", "candidate_sha256",
        "source_sha256", "source_edition", "page_map_sha256", "chunk_manifest_sha256",
        "policy_sha256", "rubric_version", "audit_mode", "checkpoint_ref", "artifacts", "excluded",
    }
    require(set(metadata) == metadata_keys, "recovery_metadata_schema", "Private recovery metadata has missing or unexpected properties.", {"expected": sorted(metadata_keys), "actual": sorted(metadata)})
    validate_self_hash(metadata, "bundle_metadata_sha256", "Private recovery metadata")
    require(metadata.get("bundle_metadata_sha256") == receipt.get("private_recovery", {}).get("bundle_metadata_sha256"), "recovery_metadata_hash_mismatch", "Recovery metadata differs from the receipt.")
    for field in ("candidate_id", "candidate_sha256", "page_map_sha256", "chunk_manifest_sha256"):
        if metadata.get(field) != receipt.get(field):
            raise PreparationError("recovery_identity_mismatch", f"Recovery metadata {field} differs from the receipt.")
    require(metadata.get("source_sha256") == receipt.get("source_identity", {}).get("sha256"), "recovery_identity_mismatch", "Recovery source hash differs from the receipt.")
    require(metadata.get("source_edition") == receipt.get("source_identity", {}).get("edition"), "recovery_identity_mismatch", "Recovery edition differs from the receipt.")
    for metadata_field, receipt_value in (
        ("policy_sha256", receipt.get("policy_identity", {}).get("sha256")),
        ("rubric_version", receipt.get("policy_identity", {}).get("rubric_version")),
        ("audit_mode", receipt.get("policy_identity", {}).get("audit_mode")),
        ("checkpoint_ref", receipt.get("private_recovery", {}).get("checkpoint_ref")),
    ):
        require(metadata.get(metadata_field) == receipt_value, "recovery_identity_mismatch", f"Recovery metadata {metadata_field} differs from the receipt.")
    expected_excluded = {"candidate PDF bytes", "source PDF bytes", "benchmark content", "secrets"}
    require(isinstance(metadata.get("excluded"), list) and len(metadata["excluded"]) == 4 and set(metadata["excluded"]) == expected_excluded, "recovery_metadata_schema", "Private recovery metadata exclusions differ from the exact restricted-content contract.")
    metadata_records = metadata.get("artifacts")
    require(isinstance(metadata_records, list) and len(metadata_records) == len(PRIVATE_ARTIFACT_KEYS), "recovery_metadata_inventory_mismatch", "Recovery metadata must list exactly eight artifacts.")
    metadata_artifacts: dict[str, dict[str, Any]] = {}
    seen_artifact_names: set[str] = set()
    for item in metadata_records:
        require(isinstance(item, dict) and set(item) == {"artifact", "path", "sha256", "byte_length"}, "recovery_metadata_schema", "Every recovery metadata artifact record must contain artifact, path, sha256, and byte_length only.")
        artifact_name = item.get("artifact")
        require(artifact_name in PRIVATE_ARTIFACT_KEYS and artifact_name not in seen_artifact_names, "recovery_metadata_inventory_mismatch", "Recovery metadata artifact names must identify each private artifact exactly once.")
        seen_artifact_names.add(artifact_name)
        expected_path = PRIVATE_ARCHIVE_PATHS[artifact_name].format(candidate_id=normalize_candidate_id(receipt["candidate_id"]))
        require(item.get("path") == expected_path, "recovery_metadata_inventory_mismatch", f"Recovery metadata path is invalid for {artifact_name}.")
        require_sha256(item.get("sha256"), f"recovery_metadata.artifacts[{artifact_name}].sha256")
        require(isinstance(item.get("byte_length"), int) and not isinstance(item.get("byte_length"), bool) and item["byte_length"] >= 0, "recovery_metadata_schema", f"Recovery metadata byte length is invalid for {artifact_name}.")
        metadata_artifacts[item["path"]] = {"sha256": item["sha256"], "byte_length": item["byte_length"]}
    require(seen_artifact_names == set(PRIVATE_ARTIFACT_KEYS), "recovery_metadata_inventory_mismatch", "Recovery metadata artifact names differ from the exact private allowlist.")
    expected_metadata_artifacts = {
        name: {"sha256": record.get("sha256"), "byte_length": len(members[name])}
        for name, record in expected.items()
    }
    require(metadata_artifacts == expected_metadata_artifacts, "recovery_metadata_inventory_mismatch", "Recovery metadata artifact inventory or byte lengths differ from the receipt and archive.")
    return members


def validate_receipt_private_bindings(receipt: dict[str, Any], private: dict[str, Any]) -> None:
    candidate_ref = private["documents"]["candidate_ref"]
    layout = private["documents"]["layout_extraction"]
    for field, private_value in (
        ("candidate_id", candidate_ref.get("candidate_id")),
        ("candidate_sha256", candidate_ref.get("candidate_sha256")),
        ("file_origin", candidate_ref.get("file_origin")),
        ("page_map_sha256", candidate_ref.get("page_map_sha256")),
        ("chunk_manifest_sha256", candidate_ref.get("chunk_manifest_sha256")),
    ):
        require(receipt.get(field) == private_value, "receipt_private_identity_mismatch", f"Receipt {field} differs from the recovered private candidate reference.")
    require(receipt.get("source_identity") == candidate_ref.get("source"), "receipt_private_identity_mismatch", "Receipt source/edition identity differs from the recovered private candidate reference.")
    require(receipt.get("policy_identity") == candidate_ref.get("policy"), "receipt_private_identity_mismatch", "Receipt policy/rubric/audit identity differs from the recovered private candidate reference.")
    require(receipt.get("provenance") == candidate_ref.get("provenance"), "receipt_private_identity_mismatch", "Receipt provenance differs from the recovered private candidate reference.")
    require(receipt.get("adapter_identity") == layout.get("adapter"), "receipt_private_identity_mismatch", "Receipt adapter identity differs from the recovered layout extraction.")
    receipt_hashes = {
        item.get("artifact"): item.get("sha256")
        for item in receipt.get("private_artifacts", [])
        if isinstance(item, dict)
    }
    require(receipt_hashes == private.get("hashes"), "receipt_private_hash_mismatch", "Receipt private artifact hashes differ from the fully revalidated recovery artifacts.")


def materialize_recovery(members: dict[str, bytes], destination: Path) -> None:
    for relative, payload in members.items():
        if relative == "candidate-preparation-bundle-metadata.json":
            continue
        target = destination.joinpath(*PurePosixPath(relative).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)


def selected_publication(receipt: dict[str, Any], pull_request: int | None, branch: str | None) -> dict[str, Any]:
    require((pull_request is None) != (branch is None), "explicit_selection_required", "Select exactly one published pull request or worker branch.")
    publication = receipt.get("publication") if isinstance(receipt.get("publication"), dict) else {}
    if pull_request is not None:
        require(publication.get("pull_request") == pull_request, "selection_mismatch", "Selected pull request differs from the receipt.")
        selector = {"type": "pull_request", "value": pull_request}
    else:
        require(publication.get("branch") == branch, "selection_mismatch", "Selected branch differs from the receipt.")
        selector = {"type": "branch", "value": branch}
    return {"selector": selector, "publication": publication}


def validate_current_publication_evidence(
    evidence_path: Path,
    receipt: dict[str, Any],
    public_bytes: dict[str, bytes],
) -> dict[str, Any]:
    evidence, evidence_bytes, evidence_sha256 = load_json_snapshot(evidence_path, "Fresh GitHub publication evidence")
    required = {
        "schema_version", "evidence_source", "candidate_project", "pull_request", "pull_request_url",
        "state", "merged", "base_branch", "base_commit", "head_branch", "head_commit",
        "commit_count", "changed_files", "bootstrap", "observed_at",
    }
    require(
        evidence.get("schema_version") == "candidate-preparation-publication-evidence-v1" and set(evidence) == required,
        "publication_evidence_schema",
        "Fresh GitHub publication evidence schema is invalid.",
    )
    publication = receipt.get("publication", {})
    repositories = receipt.get("repositories", {})
    require(evidence.get("evidence_source") == "github_api", "publication_evidence_source", "Fresh publication evidence must be derived from the GitHub API by the coordinator.")
    require(evidence.get("candidate_project") == repositories.get("candidate_project"), "publication_project_mismatch", "Fresh publication evidence names the wrong repository.")
    require(evidence.get("state") == "open" and evidence.get("merged") is False, "publication_state", "Selected preparation pull request must remain open and unmerged at preflight.")
    require(isinstance(evidence.get("pull_request"), int) and not isinstance(evidence.get("pull_request"), bool) and evidence.get("pull_request") > 0, "publication_changed", "Fresh publication pull request number is invalid.")
    require(isinstance(evidence.get("commit_count"), int) and not isinstance(evidence.get("commit_count"), bool) and evidence.get("commit_count") == 1, "publication_changed", "Fresh publication commit count is invalid.")
    for evidence_field, publication_field in (
        ("pull_request", "pull_request"),
        ("pull_request_url", "pull_request_url"),
        ("base_branch", "base_branch"),
        ("head_branch", "branch"),
        ("commit_count", "commit_count"),
    ):
        require(evidence.get(evidence_field) == publication.get(publication_field), "publication_changed", f"Fresh publication {evidence_field} differs from the bound receipt.")
    require(require_commit(evidence.get("base_commit"), "publication_evidence.base_commit") == publication.get("base_commit"), "publication_changed", "Fresh publication base commit differs from the bound receipt.")
    bootstrap_hash = validate_bootstrap_evidence(evidence.get("bootstrap"), receipt, publication.get("base_commit"), evidence.get("observed_at"))
    if repositories.get("bootstrap_exception"):
        require(bootstrap_hash == repositories.get("bootstrap_evidence_sha256"), "bootstrap_evidence_changed", "Fresh publication evidence changed the bound initialization evidence.")
    require(require_commit(evidence.get("head_commit"), "publication_evidence.head_commit") == publication.get("head_commit"), "publication_changed", "Fresh publication head commit differs from the bound receipt.")
    changed_files = evidence.get("changed_files")
    require(isinstance(changed_files, list) and len(changed_files) == len(PUBLIC_PATHS), "publication_changed", "Fresh publication evidence must retain exactly three changed files.")
    file_hashes: dict[str, str] = {}
    blob_hashes: dict[str, str] = {}
    changed_paths: list[str] = []
    for item in changed_files:
        require(isinstance(item, dict) and set(item) == {"path", "blob_sha", "file_sha256"}, "publication_evidence_schema", "Every fresh changed-file record must contain path, blob_sha, and file_sha256 only.")
        relative = safe_relative_path(str(item.get("path", "")))
        blob_sha = item.get("blob_sha")
        require(isinstance(blob_sha, str) and bool(re.fullmatch(r"[a-fA-F0-9]{40}|[a-fA-F0-9]{64}", blob_sha)), "publication_blob_sha", f"Fresh Git blob identity is invalid for {relative}.")
        digest = require_sha256(item.get("file_sha256"), f"publication_evidence.changed_files[{relative}].file_sha256")
        changed_paths.append(relative)
        file_hashes[relative] = digest
        blob_hashes[relative] = blob_sha.lower()
    require(len(set(changed_paths)) == len(PUBLIC_PATHS) and set(changed_paths) == PUBLIC_PATHS, "publication_changed", "Fresh publication paths differ from the exact allowlist.")
    for relative, blob_sha in blob_hashes.items():
        require(git_blob_sha_bytes(public_bytes[relative], blob_sha) == blob_sha, "publication_blob_sha", f"Fresh Git blob identity does not recompute from the exact public bytes for {relative}.")
    require(file_hashes == receipt.get("public_projection", {}).get("hashes"), "publication_changed", "Fresh publication file hashes differ from the bound receipt.")
    require(blob_hashes == publication.get("blob_sha"), "publication_changed", "Fresh publication blob identities differ from the bound receipt.")
    observed_at = require_timestamp(evidence.get("observed_at"), "publication_evidence.observed_at", max_age_hours=24)
    bound_observed_at = require_timestamp(publication.get("observed_at"), "receipt.publication.observed_at")
    require(observed_at > bound_observed_at, "publication_evidence_not_fresh", "Preflight requires a distinct GitHub observation later than the receipt-binding observation.")
    require(evidence_sha256 != publication.get("evidence_sha256"), "publication_evidence_not_fresh", "Preflight cannot reuse the historical receipt-binding evidence bytes.")
    return {**evidence, "evidence_sha256": evidence_sha256, "evidence_bytes": evidence_bytes}


def validate_benchmark_git_proof(
    proof_path: Path,
    benchmark_bytes: bytes,
    benchmark_file_sha256: str,
    benchmark_project: str,
    benchmark_ref: str,
    expected_repository_path: str,
) -> dict[str, Any]:
    proof, evidence_bytes, evidence_sha256 = load_json_snapshot(proof_path, "GitHub final-benchmark evidence")
    required = {"schema_version", "evidence_source", "benchmark_project", "final_commit", "benchmark_path", "blob_sha", "file_sha256", "observed_at"}
    require(proof.get("schema_version") == "candidate-benchmark-git-proof-v1" and set(proof) == required, "benchmark_proof_schema", "Final-benchmark GitHub evidence schema is invalid.")
    require(proof.get("evidence_source") == "github_api", "benchmark_proof_source", "Final-benchmark evidence must be derived from the GitHub API.")
    require(proof.get("benchmark_project") == benchmark_project, "benchmark_proof_repository", "Final-benchmark evidence repository differs from the selected project.")
    require(require_commit(proof.get("final_commit"), "benchmark_proof.final_commit") == require_commit(benchmark_ref, "benchmark_ref"), "benchmark_proof_commit", "Final-benchmark evidence commit differs from the explicit ref.")
    evidenced_path = safe_relative_path(str(proof.get("benchmark_path", "")))
    require(evidenced_path == expected_repository_path, "benchmark_proof_path", "Final-benchmark evidence path differs from the unique canonical benchmark-freeze artifact path.")
    require(isinstance(proof.get("blob_sha"), str) and bool(re.fullmatch(r"[a-fA-F0-9]{40}|[a-fA-F0-9]{64}", proof["blob_sha"])), "benchmark_proof_blob", "Final-benchmark Git blob identity is invalid.")
    require(require_sha256(proof.get("file_sha256"), "benchmark_proof.file_sha256") == benchmark_file_sha256, "benchmark_proof_file_hash", "Final-benchmark bytes differ from the GitHub-evidenced blob.")
    require(git_blob_sha_bytes(benchmark_bytes, proof["blob_sha"]) == proof["blob_sha"].lower(), "benchmark_proof_blob", "Final-benchmark Git blob identity does not recompute from the exact benchmark bytes.")
    require_timestamp(proof.get("observed_at"), "benchmark_proof.observed_at", max_age_hours=24)
    return {**proof, "evidence_sha256": evidence_sha256, "evidence_bytes": evidence_bytes}


def validate_final_benchmark(
    path: Path,
    receipt: dict[str, Any],
    benchmark_project: str,
    benchmark_ref: str,
    proof_path: Path,
    state: dict[str, Any],
    state_path: Path,
) -> dict[str, Any]:
    benchmark, benchmark_bytes, file_sha = load_json_snapshot(path, "Final frozen benchmark")
    require(benchmark.get("schema_version") == "source-subject-benchmark-v2", "benchmark_schema", "Expected a final source-subject-benchmark-v2 artifact.")
    required = {
        "schema_version", "benchmark_id", "version", "source_sha256", "policy_sha256",
        "page_map_sha256", "chunk_manifest_sha256", "candidate_blindness", "subjects",
        "relationships", "reader_tasks", "freeze", "benchmark_sha256",
    }
    require(required.issubset(benchmark), "benchmark_schema", "Final benchmark is missing required fields.", sorted(required - set(benchmark)))
    shared_structure_errors = final_benchmark_structure_errors(benchmark)
    require(not shared_structure_errors, "benchmark_schema", "Final benchmark fails the shared frozen content contract.", shared_structure_errors)
    require(
        isinstance(benchmark.get("benchmark_id"), str)
        and benchmark["benchmark_id"]
        and isinstance(benchmark.get("version"), int)
        and not isinstance(benchmark.get("version"), bool)
        and benchmark["version"] >= 1,
        "benchmark_schema",
        "Final benchmark identity/version is invalid.",
    )
    for field in ("source_sha256", "policy_sha256", "page_map_sha256", "chunk_manifest_sha256"):
        require_sha256(benchmark.get(field), f"benchmark.{field}")
    for field in ("subjects", "relationships", "reader_tasks"):
        require(isinstance(benchmark.get(field), list), "benchmark_schema", f"Final benchmark {field} must be an array.")
    subject_ids: list[str] = []
    for subject in benchmark["subjects"]:
        require(
            isinstance(subject, dict)
            and isinstance(subject.get("subject_id"), str) and subject["subject_id"].startswith("SUBJ-")
            and isinstance(subject.get("label"), str) and bool(subject["label"].strip())
            and subject.get("priority") in {"essential", "major", "optional", "exclude_by_default"}
            and isinstance(subject.get("meaning"), str) and bool(subject["meaning"].strip())
            and isinstance(subject.get("stance"), str) and bool(subject["stance"].strip())
            and isinstance(subject.get("acceptable_access"), list) and bool(subject["acceptable_access"])
            and all(isinstance(access, str) and bool(access.strip()) for access in subject["acceptable_access"])
            and isinstance(subject.get("evidence"), list) and bool(subject["evidence"])
            and all(isinstance(evidence, dict) for evidence in subject["evidence"]),
            "benchmark_schema",
            "Every final benchmark subject must satisfy the source-benchmark-v2 subject contract.",
        )
        subject_ids.append(subject["subject_id"])
    require(not _duplicate_values(subject_ids), "benchmark_schema", "Final benchmark subject IDs must be unique.")
    relationship_ids: list[str] = []
    for relationship in benchmark["relationships"]:
        require(
            isinstance(relationship, dict)
            and isinstance(relationship.get("relationship_id"), str)
            and relationship["relationship_id"].startswith("REL-")
            and isinstance(relationship.get("source_subject_id"), str)
            and relationship["source_subject_id"] in subject_ids
            and isinstance(relationship.get("relationship_type"), str)
            and bool(relationship["relationship_type"].strip())
            and isinstance(relationship.get("resolution_status"), str)
            and bool(relationship["resolution_status"].strip()),
            "benchmark_schema",
            "Every final benchmark relationship must identify its source, type, and resolution status.",
        )
        relationship_id = relationship.get("relationship_id")
        relationship_ids.append(relationship_id)
        if relationship.get("target_subject_id") is not None:
            require(relationship["target_subject_id"] in subject_ids, "benchmark_schema", "Final benchmark relationship references an unknown target_subject_id.")
        else:
            require(
                isinstance(relationship.get("target_label"), str) and bool(relationship["target_label"].strip()),
                "benchmark_schema",
                "A relationship without target_subject_id must retain a nonempty target_label.",
            )
    require(not _duplicate_values(relationship_ids), "benchmark_schema", "Final benchmark relationship IDs must be unique.")
    task_ids: list[str] = []
    for task in benchmark["reader_tasks"]:
        require(
            isinstance(task, dict)
            and isinstance(task.get("task_id"), str) and task["task_id"].startswith("TASK-")
            and isinstance(task.get("question"), str) and bool(task["question"].strip())
            and isinstance(task.get("subject_ids"), list) and bool(task["subject_ids"])
            and all(isinstance(subject_id, str) for subject_id in task["subject_ids"])
            and set(task["subject_ids"]).issubset(set(subject_ids)),
            "benchmark_schema",
            "Every final benchmark reader task must satisfy the source-benchmark-v2 contract and reference known subjects.",
        )
        task_ids.append(task["task_id"])
    require(not _duplicate_values(task_ids), "benchmark_schema", "Final benchmark task IDs must be unique.")
    freeze = benchmark.get("freeze")
    require(
        isinstance(freeze, dict)
        and isinstance(freeze.get("frozen_at"), str)
        and freeze.get("synthesis_pass_complete") is True
        and freeze.get("page_coverage_complete") is True,
        "benchmark_not_final",
        "Final benchmark freeze attestations are incomplete.",
    )
    require_timestamp(freeze["frozen_at"], "benchmark.freeze.frozen_at")
    validate_self_hash(benchmark, "benchmark_sha256", "Final benchmark")
    require(benchmark.get("candidate_blindness") == "preserved", "benchmark_blindness", "Final benchmark must preserve candidate blindness.")
    repositories = receipt.get("repositories", {})
    require(benchmark_project == repositories.get("benchmark_project"), "benchmark_repository_mismatch", "Selected benchmark project differs from the receipt.")
    final_commit = require_commit(benchmark_ref, "benchmark_ref")
    for field, expected in (
        ("source_sha256", receipt.get("source_identity", {}).get("sha256")),
        ("page_map_sha256", receipt.get("page_map_sha256")),
        ("chunk_manifest_sha256", receipt.get("chunk_manifest_sha256")),
        ("policy_sha256", receipt.get("policy_identity", {}).get("sha256")),
    ):
        require(benchmark.get(field) == expected, "benchmark_identity_mismatch", f"Final benchmark {field} is incompatible with the preparation receipt.")
    canonical_matches = [
        record for record in state.get("artifacts", [])
        if isinstance(record, dict)
        and record.get("stage") == "benchmark_freeze"
        and record.get("frozen") is True
        and record.get("sha256") == file_sha
    ]
    require(len(canonical_matches) == 1, "benchmark_not_canonical", "Final benchmark bytes must match exactly one frozen benchmark-freeze artifact registered in canonical state.")
    canonical_repository_path = safe_relative_path(canonical_matches[0]["path"])
    registered_path = state_path.resolve().parent.joinpath(*PurePosixPath(canonical_repository_path).parts)
    require(sha256_file(registered_path) == file_sha, "benchmark_not_canonical", "Registered canonical benchmark artifact bytes are unavailable or changed.")
    proof = validate_benchmark_git_proof(
        proof_path,
        benchmark_bytes,
        file_sha,
        benchmark_project,
        final_commit,
        canonical_repository_path,
    )
    return {"artifact": benchmark, "bytes": benchmark_bytes, "commit": final_commit, "sha256": benchmark["benchmark_sha256"], "file_sha256": file_sha, "proof": proof, "registered_path": canonical_matches[0]["path"]}


def preflight_integration(
    receipt_path: Path,
    recovery_zip: Path,
    public_dir: Path,
    state_path: Path,
    page_map_path: Path,
    chunk_manifest_path: Path,
    policy_path: Path,
    benchmark_file: Path,
    publication_evidence: Path,
    benchmark_proof: Path,
    benchmark_project: str,
    benchmark_ref: str,
    pull_request: int | None,
    branch: str | None,
) -> dict[str, Any]:
    receipt_path = receipt_path.resolve()
    recovery_zip = recovery_zip.resolve()
    public_dir = public_dir.resolve()
    state_path = state_path.resolve()
    page_map_path = page_map_path.resolve()
    chunk_manifest_path = chunk_manifest_path.resolve()
    policy_path = policy_path.resolve()
    benchmark_file = benchmark_file.resolve()
    publication_evidence = publication_evidence.resolve()
    benchmark_proof = benchmark_proof.resolve()
    receipt, receipt_bytes, receipt_file_sha256 = load_json_snapshot(receipt_path, "Candidate preparation receipt")
    receipt = validate_receipt_document(receipt, {"published_unmerged"})
    state, state_bytes, state_file_sha256 = load_json_snapshot(state_path, "Canonical evaluation state")
    page_map, page_map_bytes, page_map_file_sha256 = load_json_snapshot(page_map_path, "Page map")
    chunk_manifest, chunk_manifest_bytes, chunk_manifest_file_sha256 = load_json_snapshot(chunk_manifest_path, "Chunk manifest")
    policy, policy_bytes, policy_file_sha256 = load_json_snapshot(policy_path, "Evaluation policy")
    manifest_relative = safe_relative_path(str(state.get("artifact_manifest_path", "artifact-manifest.json")))
    manifest_path = state_path.parent.joinpath(*PurePosixPath(manifest_relative).parts)
    manifest, manifest_bytes, manifest_file_sha256 = load_json_snapshot(manifest_path, "Canonical artifact manifest")
    selection = selected_publication(receipt, pull_request, branch)
    public_documents, public_bytes, public_hashes = load_public_directory_snapshot(public_dir)
    public_errors = validate_public_documents(public_documents)
    require(not public_errors, "public_projection_invalid", "Published public projection failed revalidation.", public_errors)
    require(public_hashes == receipt.get("public_projection", {}).get("hashes"), "public_hash_mismatch", "Published public projection differs from the receipt.")
    publication = selection["publication"]
    require(set(publication.get("changed_paths", [])) == PUBLIC_PATHS and publication.get("commit_count") == 1, "publication_surface_mismatch", "Receipt publication is not the required one-commit exact-allowlist pull request.")
    current_publication = validate_current_publication_evidence(publication_evidence, receipt, public_bytes)
    members = validate_recovery_zip(recovery_zip, receipt)
    with tempfile.TemporaryDirectory(prefix="candidate-preflight-") as temporary_name:
        temporary = Path(temporary_name)
        materialize_recovery(members, temporary)
        candidate_id = receipt["candidate_id"]
        qa_path = temporary / PRIVATE_ARCHIVE_PATHS["normalization_qa"].format(candidate_id=normalize_candidate_id(candidate_id))
        private = validate_private_preparation(
            temporary, candidate_id, None, state_path, page_map_path, chunk_manifest_path, policy_path,
            qa_path, receipt.get("source_identity", {}).get("edition"),
            {
                "state": state,
                "page_map": page_map,
                "chunk_manifest": chunk_manifest,
                "policy": policy,
            },
        )
    validate_receipt_private_bindings(receipt, private)
    require(public_documents == public_projection_documents(private), "public_private_projection_mismatch", "Published aggregate files are not the exact safe projection of the recovered private preparation.")
    for field in ("internal_pdf_completeness", "structural_continuity", "source_edition_compatibility", "locator_page_map_compatibility"):
        require(receipt.get("provenance", {}).get(field, {}).get("status") == "verified", "integration_provenance_incomplete", f"Integration requires verified {field} provenance.")
    require(state.get("schema_version") == STATE_V4, "integration_state_version", "Candidate preparation integration requires state v4.")
    state_errors, _ = validate_state(state, state_path=state_path, check_files=True, manifest_document=manifest)
    require(not state_errors, "canonical_state_invalid", "Canonical evaluation state must validate before integration.", state_errors)
    require(state.get("stages", {}).get("benchmark_freeze", {}).get("status") == "completed", "benchmark_stage_incomplete", "Canonical benchmark_freeze must be complete before integration.")
    benchmark = validate_final_benchmark(
        benchmark_file,
        receipt,
        benchmark_project,
        benchmark_ref,
        benchmark_proof,
        state,
        state_path,
    )
    stage_order = STAGES
    require("candidate_normalization" in stage_order, "state_shape", "State has no candidate_normalization stage.")
    start = stage_order.index("candidate_normalization")
    later_started = [name for name in stage_order[start:] if state["stages"][name].get("status") != "not_started"]
    require(not later_started, "candidate_stage_already_started", "Candidate normalization or a later stage has already started.", later_started)
    input_hashes = {
        "receipt": {"path": str(receipt_path), "sha256": receipt_file_sha256},
        "recovery_zip": {"path": str(recovery_zip), "sha256": receipt["private_recovery"]["sha256"]},
        "state": {"path": str(state_path), "sha256": state_file_sha256},
        "manifest": {"path": str(manifest_path), "sha256": manifest_file_sha256},
        "page_map": {"path": str(page_map_path), "sha256": page_map_file_sha256},
        "chunk_manifest": {"path": str(chunk_manifest_path), "sha256": chunk_manifest_file_sha256},
        "policy": {"path": str(policy_path), "sha256": policy_file_sha256},
        "benchmark_file": {"path": str(benchmark_file), "sha256": benchmark["file_sha256"]},
        "publication_evidence": {"path": str(publication_evidence), "sha256": current_publication["evidence_sha256"]},
        "benchmark_proof": {"path": str(benchmark_proof), "sha256": benchmark["proof"]["evidence_sha256"]},
        **{
            f"public:{relative}": {"path": str(public_dir / relative), "sha256": public_hashes[relative]}
            for relative in sorted(PUBLIC_PATHS)
        },
    }
    result = {
        "receipt": receipt,
        "receipt_bytes": receipt_bytes,
        "receipt_file_sha256": receipt_file_sha256,
        "selection": selection["selector"],
        "publication": publication,
        "current_publication": current_publication,
        "public_documents": public_documents,
        "public_bytes": public_bytes,
        "public_hashes": public_hashes,
        "members": members,
        "private": private,
        "benchmark": benchmark,
        "state": state,
        "state_bytes": state_bytes,
        "manifest": manifest,
        "manifest_bytes": manifest_bytes,
        "manifest_path": manifest_path,
        "input_hashes": input_hashes,
        "merge_authorized": True,
    }
    validate_preflight_input_hashes(result)
    return result


def command_preflight_integration(args: argparse.Namespace) -> None:
    result = preflight_integration(
        Path(args.receipt), Path(args.recovery_zip), Path(args.public_dir), Path(args.state),
        Path(args.page_map), Path(args.chunk_manifest), Path(args.policy), Path(args.benchmark_file),
        Path(args.publication_evidence), Path(args.benchmark_proof), args.benchmark_project, args.benchmark_ref, args.pull_request, args.branch,
    )
    emit({
        "command": "preflight-candidate-preparation-integration",
        "ok": True,
        "candidate_id": result["receipt"]["candidate_id"],
        "selection": result["selection"],
        "worker_head_commit": result["publication"]["head_commit"],
        "publication_evidence_sha256": result["current_publication"]["evidence_sha256"],
        "benchmark_commit": result["benchmark"]["commit"],
        "benchmark_sha256": result["benchmark"]["sha256"],
        "validated_public_paths": sorted(PUBLIC_PATHS),
        "validated_private_artifact_count": len(PRIVATE_ARTIFACT_KEYS),
        "merge_authorized": True,
        "merge_performed": False,
        "canonical_state_mutated": False,
        "next_actions": ["merge_only_the_selected_public_pull_request", "run-integrate-after-merged-head-verification"],
        "warnings": result["receipt"].get("limitations", []),
    })


def validate_preflight_input_hashes(preflight: dict[str, Any]) -> None:
    changed: list[str] = []
    for name, record in preflight.get("input_hashes", {}).items():
        path = Path(record["path"])
        if not path.is_file() or sha256_file(path) != record.get("sha256"):
            changed.append(name)
    require(not changed, "preflight_input_changed", "One or more integration inputs changed after preflight; rerun preflight under the canonical evaluation lock.", sorted(changed))


def validate_merge_evidence(
    path: Path,
    preflight: dict[str, Any],
) -> dict[str, Any]:
    evidence, evidence_bytes, evidence_sha256 = load_json_snapshot(path, "GitHub merged-pull-request evidence")
    required = {
        "schema_version", "evidence_source", "candidate_project", "pull_request", "pull_request_url",
        "state", "merged", "base_branch", "base_commit", "head_branch", "head_commit",
        "merge_commit", "commit_count", "changed_files", "observed_at",
    }
    require(
        evidence.get("schema_version") == "candidate-preparation-merge-evidence-v1" and set(evidence) == required,
        "merge_evidence_schema",
        "Merged-pull-request GitHub evidence schema is invalid.",
    )
    require(evidence.get("evidence_source") == "github_api", "merge_evidence_source", "Merge evidence must be derived from the GitHub API by the coordinator.")
    receipt = preflight["receipt"]
    publication = preflight["publication"]
    repositories = receipt["repositories"]
    require(evidence.get("candidate_project") == repositories.get("candidate_project"), "merge_repository_mismatch", "Merged pull request belongs to a different candidate repository.")
    require(evidence.get("state") == "closed" and evidence.get("merged") is True, "pull_request_not_merged", "Selected pull request must be closed and merged before canonical integration.")
    require(isinstance(evidence.get("pull_request"), int) and not isinstance(evidence.get("pull_request"), bool) and evidence.get("pull_request") > 0, "merge_selection_mismatch", "Merged pull request number is invalid.")
    require(evidence.get("pull_request") == publication.get("pull_request"), "merge_selection_mismatch", "Merged pull request differs from the selected published receipt.")
    require(evidence.get("pull_request_url") == publication.get("pull_request_url"), "merge_selection_mismatch", "Merged pull request URL differs from the selected published receipt.")
    require(evidence.get("base_branch") == publication.get("base_branch"), "merge_base_mismatch", "Merged pull request base branch changed after preflight.")
    require(require_commit(evidence.get("base_commit"), "merge_evidence.base_commit") == publication.get("base_commit"), "merge_base_mismatch", "Merged pull request base commit changed after preflight.")
    require(evidence.get("head_branch") == publication.get("branch"), "merge_head_mismatch", "Merged pull request head branch changed after preflight.")
    merged_head = require_commit(evidence.get("head_commit"), "merge_evidence.head_commit")
    require(merged_head == publication.get("head_commit"), "merge_head_mismatch", "Merged pull request head commit changed after preflight.")
    merge_commit = require_commit(evidence.get("merge_commit"), "merge_evidence.merge_commit")
    require(isinstance(evidence.get("commit_count"), int) and not isinstance(evidence.get("commit_count"), bool) and evidence.get("commit_count") == 1, "merge_commit_count", "Merged candidate-preparation pull request must contain exactly one worker commit.")
    changed_files = evidence.get("changed_files")
    require(isinstance(changed_files, list) and len(changed_files) == len(PUBLIC_PATHS), "merged_diff_mismatch", "Merged pull request must retain the exact three-file public diff.")
    changed_paths: list[str] = []
    file_hashes: dict[str, str] = {}
    blob_hashes: dict[str, str] = {}
    for item in changed_files:
        require(isinstance(item, dict) and set(item) == {"path", "blob_sha", "file_sha256"}, "merge_evidence_schema", "Every merged changed-file record must contain path, blob_sha, and file_sha256 only.")
        relative = safe_relative_path(str(item.get("path", "")))
        blob_sha = item.get("blob_sha")
        require(isinstance(blob_sha, str) and bool(re.fullmatch(r"[a-fA-F0-9]{40}|[a-fA-F0-9]{64}", blob_sha)), "merge_blob_sha", f"Merged Git blob identity is invalid for {relative}.")
        file_sha = require_sha256(item.get("file_sha256"), f"merge_evidence.changed_files[{relative}].file_sha256")
        changed_paths.append(relative)
        file_hashes[relative] = file_sha
        blob_hashes[relative] = blob_sha.lower()
    require(len(set(changed_paths)) == len(PUBLIC_PATHS) and set(changed_paths) == PUBLIC_PATHS, "merged_diff_mismatch", "Merged pull request paths differ from the exact public allowlist.")
    for relative, blob_sha in blob_hashes.items():
        require(git_blob_sha_bytes(preflight["public_bytes"][relative], blob_sha) == blob_sha, "merge_blob_sha", f"Merged Git blob identity does not recompute from the exact public bytes for {relative}.")
    require(file_hashes == receipt.get("public_projection", {}).get("hashes"), "merged_diff_mismatch", "Merged public file bytes differ from the validated receipt.")
    require(blob_hashes == publication.get("blob_sha"), "merged_diff_mismatch", "Merged Git blob identities differ from the pre-merge GitHub evidence.")
    merge_observed_at = require_timestamp(evidence.get("observed_at"), "merge_evidence.observed_at", max_age_hours=24)
    premerge_observed_at = require_timestamp(preflight.get("current_publication", {}).get("observed_at"), "preflight.current_publication.observed_at")
    require(merge_observed_at >= premerge_observed_at, "merge_evidence_order", "Merged-pull-request evidence cannot predate the fresh open premerge observation.")
    return {
        **evidence,
        "head_commit": merged_head,
        "merge_commit": merge_commit,
        "evidence_sha256": evidence_sha256,
        "evidence_bytes": evidence_bytes,
        "file_sha256": file_hashes,
        "blob_sha": blob_hashes,
    }


def _artifact_record(root: Path, path: Path, artifact_type: str, stamp: str) -> dict[str, Any]:
    relative = path.resolve().relative_to(root.resolve()).as_posix()
    digest = sha256_file(path)
    return {
        "artifact_id": artifact_id(relative, digest),
        "stage": "candidate_normalization",
        "artifact_type": artifact_type,
        "path": relative,
        "sha256": digest,
        "media_type": "application/json",
        "visibility": "private",
        "retention": "required",
        "frozen": True,
        "recorded_at": stamp,
    }


def _replace_json_atomic(path: Path, value: dict[str, Any]) -> None:
    payload = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    replace_bytes_atomic(path, payload)


def create_integration_checkpoint(
    output: Path,
    state_path: Path,
    manifest_path: Path,
    artifact_paths: list[Path],
    integration_report: dict[str, Any],
    force: bool,
) -> dict[str, Any]:
    protected = {state_path.resolve(), manifest_path.resolve(), *[path.resolve() for path in artifact_paths]}
    require(output.resolve() not in protected, "unsafe_checkpoint_output", "Checkpoint output must be distinct from canonical state, manifest, and integration artifacts.")
    require(output.suffix.lower() == ".zip", "unsafe_checkpoint_output", "Integration checkpoint output must use a .zip filename.")
    require(not output.exists() or force, "checkpoint_exists", f"Refusing to overwrite {output}")
    root = state_path.resolve().parent
    if path_is_within(output, root):
        require_safe_output_path(output, root, "Integration checkpoint")
    else:
        require_no_symlink_components(output.parent, "Integration checkpoint parent")
        require(not output.is_symlink(), "unsafe_output_symlink", f"Integration checkpoint cannot be a symlink: {output}")
    members: dict[str, bytes] = {
        "evaluation-state.json": state_path.read_bytes(),
        "artifact-manifest.json": manifest_path.read_bytes(),
    }
    for path in artifact_paths:
        relative = path.resolve().relative_to(root).as_posix()
        members[relative] = path.read_bytes()
    metadata = {
        "schema_version": "candidate-integration-checkpoint-v1",
        "evaluation_id": integration_report["evaluation_id"],
        "candidate_id": integration_report["candidate_id"],
        "candidate_sha256": integration_report["candidate_sha256"],
        "benchmark_lock_sha256": integration_report["benchmark_lock_sha256"],
        "included_paths": sorted(members),
        "included_hashes": {name: sha256_bytes(payload) for name, payload in sorted(members.items())},
        "excluded": ["candidate PDF bytes", "source PDF bytes", "benchmark repository content", "secrets"],
    }
    metadata["checkpoint_metadata_sha256"] = canonical_hash(metadata, "checkpoint_metadata_sha256")
    members["checkpoint-metadata.json"] = (json.dumps(metadata, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    write_zip_atomic(output, members)
    return {"path": str(output), "sha256": sha256_file(output), "metadata_sha256": metadata["checkpoint_metadata_sha256"]}


def _integrate_transaction(
    args: argparse.Namespace,
    preflight: dict[str, Any],
    merge_evidence: dict[str, Any],
) -> None:
    publication = preflight["publication"]
    merged_head = merge_evidence["head_commit"]
    merged_commit = merge_evidence["merge_commit"]

    receipt = preflight["receipt"]
    state_path = Path(args.state).resolve()
    root = state_path.parent
    manifest_path = preflight["manifest_path"]
    manifest = deepcopy(preflight["manifest"])
    require(manifest.get("schema_version") == "subject-index-artifact-manifest-v1", "manifest_schema", "Canonical artifact manifest schema is invalid.")
    require(manifest.get("evaluation_id") == preflight["state"].get("evaluation_id"), "manifest_identity", "Manifest and evaluation state identities differ.")
    require(sha256_file(state_path) == preflight["input_hashes"]["state"]["sha256"], "preflight_input_changed", "Canonical state changed after locked preflight validation.")
    require(sha256_file(manifest_path) == preflight["input_hashes"]["manifest"]["sha256"], "preflight_input_changed", "Canonical manifest changed after locked preflight validation.")

    stamp = now()
    candidate_slug = normalize_candidate_id(receipt["candidate_id"])
    canonical_dir = root / "candidate" / candidate_slug
    canonical_private_outputs = {
        "candidate_ref": canonical_dir / "candidate-ref.json",
        "layout_profile": canonical_dir / "layout-profile.json",
        "layout_extraction": canonical_dir / "candidate-layout-extraction.v1.json",
        "candidate_index": canonical_dir / "candidate-index.v2.json",
        "item_inventory": canonical_dir / "item-inventory.v2.json",
        "normalization_exceptions": canonical_dir / "normalization-exceptions.v1.json",
        "normalization_report": root / "validation" / f"candidate-normalization-report.{candidate_slug}.v1.json",
        "normalization_qa": root / "validation" / f"candidate-normalization-qa.{candidate_slug}.v1.json",
    }
    candidate_output = canonical_private_outputs["candidate_index"]
    inventory_output = canonical_private_outputs["item_inventory"]
    lock_output = canonical_dir / "candidate-benchmark-lock.json"
    receipt_output = canonical_dir / "candidate-preparation-receipt.json"
    integration_output = root / "validation" / f"candidate-preparation-integration.{candidate_slug}.v1.json"
    canonical_evidence_outputs = {
        "publication_evidence": root / "validation" / f"candidate-preparation-publication-evidence.{candidate_slug}.v1.json",
        "benchmark_proof": root / "validation" / f"candidate-benchmark-git-proof.{candidate_slug}.v1.json",
        "merge_evidence": root / "validation" / f"candidate-preparation-merge-evidence.{candidate_slug}.v1.json",
    }
    outputs = [*canonical_private_outputs.values(), *canonical_evidence_outputs.values(), lock_output, receipt_output, integration_output]
    require_safe_output_path(manifest_path, root, "Canonical artifact manifest")
    require_safe_output_path(state_path, root, "Canonical evaluation state")
    for output_path in outputs:
        require_safe_output_path(output_path, root, "Canonical candidate integration output")
    existing = [str(path) for path in outputs if path.exists()]
    require(not existing, "canonical_candidate_exists", "Refusing to overwrite existing canonical candidate artifacts.", existing)

    member_paths = {item["artifact"]: item["archive_path"] for item in receipt["private_artifacts"]}
    private_bytes = {key: preflight["members"][member_paths[key]] for key in PRIVATE_ARTIFACT_KEYS}
    candidate_bytes = private_bytes["candidate_index"]
    inventory_bytes = private_bytes["item_inventory"]
    require(sha256_bytes(candidate_bytes) == preflight["private"]["hashes"]["candidate_index"], "normalized_bytes_mismatch", "Recovered normalized candidate bytes changed after preflight.")
    require(sha256_bytes(inventory_bytes) == preflight["private"]["hashes"]["item_inventory"], "inventory_bytes_mismatch", "Recovered item inventory bytes changed after preflight.")
    evidence_bytes = {
        "publication_evidence": preflight["current_publication"]["evidence_bytes"],
        "benchmark_proof": preflight["benchmark"]["proof"]["evidence_bytes"],
        "merge_evidence": merge_evidence["evidence_bytes"],
    }
    require(sha256_bytes(evidence_bytes["publication_evidence"]) == preflight["current_publication"]["evidence_sha256"], "preflight_input_changed", "Fresh publication evidence bytes changed after validation.")
    require(sha256_bytes(evidence_bytes["benchmark_proof"]) == preflight["benchmark"]["proof"]["evidence_sha256"], "preflight_input_changed", "Benchmark proof bytes changed after validation.")
    require(sha256_bytes(evidence_bytes["merge_evidence"]) == merge_evidence["evidence_sha256"], "preflight_input_changed", "Merge evidence bytes changed after validation.")
    benchmark = preflight["benchmark"]
    lock = {
        "schema_version": "candidate-benchmark-lock-v1",
        "status": "locked",
        "locked_at": stamp,
        "candidate_id": receipt["candidate_id"],
        "candidate_sha256": receipt["candidate_sha256"],
        "preparation_receipt_sha256": receipt["receipt_sha256"],
        "candidate_repository": {
            "project": receipt["repositories"]["candidate_project"],
            "merged_commit": merged_commit,
            "worker_head_commit": merged_head,
            "pull_request": publication.get("pull_request"),
            "premerge_evidence_sha256": preflight["current_publication"]["evidence_sha256"],
            "merge_evidence_sha256": merge_evidence["evidence_sha256"],
            "public_blob_sha": merge_evidence["blob_sha"],
        },
        "benchmark_repository": {
            "project": receipt["repositories"]["benchmark_project"],
            "preparation_base_commit": receipt["repositories"]["benchmark_preparation_base_commit"],
            "final_commit": benchmark["commit"],
            "benchmark_sha256": benchmark["sha256"],
            "benchmark_file_sha256": benchmark["file_sha256"],
            "benchmark_path": benchmark["proof"]["benchmark_path"],
            "blob_sha": benchmark["proof"]["blob_sha"],
            "proof_evidence_sha256": benchmark["proof"]["evidence_sha256"],
            "proof_observed_at": benchmark["proof"]["observed_at"],
        },
        "compatibility": {
            "source_sha256": receipt["source_identity"]["sha256"],
            "source_edition": receipt["source_identity"]["edition"],
            "page_map_sha256": receipt["page_map_sha256"],
            "chunk_manifest_sha256": receipt["chunk_manifest_sha256"],
            "policy_sha256": receipt["policy_identity"]["sha256"],
            "policy_profile": receipt["policy_identity"]["profile"],
            "rubric_version": receipt["policy_identity"]["rubric_version"],
            "audit_mode": receipt["policy_identity"]["audit_mode"],
        },
    }
    lock["lock_sha256"] = canonical_hash(lock, "lock_sha256")
    integration_report = {
        "schema_version": "candidate-preparation-integration-v1",
        "status": "integrated",
        "integrated_at": stamp,
        "evaluation_id": preflight["state"]["evaluation_id"],
        "candidate_id": receipt["candidate_id"],
        "candidate_sha256": receipt["candidate_sha256"],
        "preparation_receipt_sha256": receipt["receipt_sha256"],
        "benchmark_lock_sha256": lock["lock_sha256"],
        "selection": preflight["selection"],
        "merged_commit": merged_commit,
        "worker_head_commit": merged_head,
        "premerge_evidence_sha256": preflight["current_publication"]["evidence_sha256"],
        "merge_evidence_sha256": merge_evidence["evidence_sha256"],
        "benchmark_proof_sha256": benchmark["proof"]["evidence_sha256"],
        "public_changed_paths": sorted(PUBLIC_PATHS),
        "normalized_candidate_file_sha256": sha256_bytes(candidate_bytes),
        "item_inventory_file_sha256": sha256_bytes(inventory_bytes),
        "transaction_order": ["copy_exact_normalized_bytes", "write_benchmark_lock_and_integration_evidence", "update_manifest", "update_state_last", "validate_complete_state", "create_cumulative_checkpoint"],
        "benchmark_repository_modified": False,
    }

    state = deepcopy(preflight["state"])
    state["candidate"] = {
        "candidate_id": receipt["candidate_id"],
        "sha256": receipt["candidate_sha256"],
        "schema_version": "candidate-index-v2",
        "normalized_path": candidate_output.relative_to(root).as_posix(),
        "item_inventory_path": inventory_output.relative_to(root).as_posix(),
        "candidate_ref_path": canonical_private_outputs["candidate_ref"].relative_to(root).as_posix(),
        "layout_profile_path": canonical_private_outputs["layout_profile"].relative_to(root).as_posix(),
        "normalization_qa_path": canonical_private_outputs["normalization_qa"].relative_to(root).as_posix(),
        "preparation_receipt_path": receipt_output.relative_to(root).as_posix(),
        "preparation_receipt_sha256": receipt["receipt_sha256"],
        "benchmark_lock_path": lock_output.relative_to(root).as_posix(),
        "benchmark_lock_sha256": lock["lock_sha256"],
    }
    state["stages"]["candidate_normalization"] = {
        "status": "completed",
        "updated_at": stamp,
        "notes": ["Integrated exact worker-normalized bytes after final benchmark compatibility lock and selected-PR validation."],
    }
    state["updated_at"] = stamp

    original_state = preflight["state_bytes"]
    original_manifest = preflight["manifest_bytes"]
    original_state_sha256 = sha256_bytes(original_state)
    original_manifest_sha256 = sha256_bytes(original_manifest)
    require(sha256_bytes(original_state) == preflight["input_hashes"]["state"]["sha256"], "preflight_input_changed", "Canonical state changed immediately before integration mutation.")
    require(sha256_bytes(original_manifest) == preflight["input_hashes"]["manifest"]["sha256"], "preflight_input_changed", "Canonical manifest changed immediately before integration mutation.")
    written: list[Path] = []
    checkpoint_output: Path | None = None
    previous_checkpoint_bytes: bytes | None = None
    previous_checkpoint_existed = False
    checkpoint_attempted = False
    manifest_replaced = False
    state_replaced = False
    try:
        candidate_output.parent.mkdir(parents=True, exist_ok=True)
        integration_output.parent.mkdir(parents=True, exist_ok=True)
        for key in PRIVATE_ARTIFACT_KEYS:
            output_path = canonical_private_outputs[key]
            output_path.parent.mkdir(parents=True, exist_ok=True)
            written.append(output_path)
            replace_bytes_atomic(output_path, private_bytes[key])
        written.append(lock_output)
        _replace_json_atomic(lock_output, lock)
        written.append(receipt_output)
        replace_bytes_atomic(receipt_output, preflight["receipt_bytes"])
        written.append(integration_output)
        _replace_json_atomic(integration_output, integration_report)
        for key, output_path in canonical_evidence_outputs.items():
            written.append(output_path)
            replace_bytes_atomic(output_path, evidence_bytes[key])

        private_artifact_types = {
            "candidate_ref": "candidate-ref",
            "layout_profile": "candidate-layout-profile",
            "layout_extraction": "candidate-layout-extraction",
            "candidate_index": "candidate-index-v2",
            "item_inventory": "item-inventory-v2",
            "normalization_exceptions": "candidate-normalization-exceptions",
            "normalization_report": "candidate-normalization-report",
            "normalization_qa": "candidate-normalization-qa",
        }
        records = [
            *[
                _artifact_record(root, canonical_private_outputs[key], private_artifact_types[key], stamp)
                for key in PRIVATE_ARTIFACT_KEYS
            ],
            _artifact_record(root, lock_output, "candidate-benchmark-lock", stamp),
            _artifact_record(root, receipt_output, "candidate-preparation-receipt", stamp),
            _artifact_record(root, integration_output, "candidate-preparation-integration", stamp),
            _artifact_record(root, canonical_evidence_outputs["publication_evidence"], "candidate-preparation-publication-evidence", stamp),
            _artifact_record(root, canonical_evidence_outputs["benchmark_proof"], "candidate-benchmark-git-proof", stamp),
            _artifact_record(root, canonical_evidence_outputs["merge_evidence"], "candidate-preparation-merge-evidence", stamp),
        ]
        new_paths = {record["path"] for record in records}
        require(not new_paths.intersection({item.get("path") for item in manifest.get("artifacts", [])}), "manifest_path_collision", "Canonical manifest already contains a candidate integration path.")
        manifest.setdefault("artifacts", []).extend(records)
        manifest["artifacts"].sort(key=lambda item: item["path"])
        manifest["updated_at"] = stamp
        state.setdefault("artifacts", []).extend(records)
        state["artifacts"].sort(key=lambda item: item["path"])
        intended_manifest_sha256 = sha256_bytes((json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
        intended_state_sha256 = sha256_bytes((json.dumps(state, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
        require(sha256_file(manifest_path) == original_manifest_sha256, "preflight_input_changed", "Canonical manifest changed during integration artifact staging.")
        require(sha256_file(state_path) == original_state_sha256, "preflight_input_changed", "Canonical state changed during integration artifact staging.")
        _replace_json_atomic(manifest_path, manifest)
        manifest_replaced = True
        require(sha256_file(state_path) == original_state_sha256, "preflight_input_changed", "Canonical state changed before the state-last commit.")
        _replace_json_atomic(state_path, state)
        state_replaced = True
        persisted_state = load_json(state_path, "Integrated canonical evaluation state")
        require(persisted_state == state, "post_integration_state_mismatch", "Persisted canonical state differs from the intended integrated state.")
        errors, warnings = validate_state(persisted_state, state_path=state_path, check_files=True)
        require(not errors, "post_integration_state_invalid", "Integrated state failed full validation; transaction was rolled back.", errors)
        next_action = next_stage(persisted_state)
        require(next_action is not None and next_action.get("stage") == "locator_chunk_preparation", "unexpected_next_stage", "Integration did not advance exactly to locator_chunk_preparation.", next_action)
        checkpoint_requested = Path(args.checkpoint_output) if args.checkpoint_output else root / "exports" / f"{state['evaluation_id']}-candidate-{candidate_slug}-integration-checkpoint.zip"
        require_no_symlink_components(checkpoint_requested, "Integration checkpoint output")
        checkpoint_output = checkpoint_requested.resolve()
        protected_inputs = {
            Path(value).resolve()
            for value in (
                args.receipt, args.recovery_zip, args.state, args.page_map, args.chunk_manifest,
                args.policy, args.benchmark_file, args.publication_evidence, args.benchmark_proof, args.merge_evidence,
            )
        }
        protected_inputs.update((Path(args.public_dir).resolve() / relative).resolve() for relative in PUBLIC_PATHS)
        require(checkpoint_output not in protected_inputs, "unsafe_checkpoint_output", "Checkpoint output must be distinct from every integration input.")
        previous_checkpoint_existed = checkpoint_output.exists()
        if previous_checkpoint_existed:
            previous_checkpoint_bytes = checkpoint_output.read_bytes()
        checkpoint_attempted = True
        checkpoint = create_integration_checkpoint(checkpoint_output, state_path, manifest_path, written, integration_report, args.force_checkpoint)
        persisted_after_checkpoint = load_json(state_path, "Canonical evaluation state after checkpoint")
        require(persisted_after_checkpoint == state, "checkpoint_corrupted_state", "Canonical state changed while creating the checkpoint; transaction was rolled back.")
        checkpoint_errors, checkpoint_warnings = validate_state(persisted_after_checkpoint, state_path=state_path, check_files=True)
        require(not checkpoint_errors, "checkpoint_corrupted_state", "Canonical state changed while creating the checkpoint; transaction was rolled back.", checkpoint_errors)
        warnings = list(dict.fromkeys([*warnings, *checkpoint_warnings]))
    except Exception:
        if state_replaced or not state_path.exists() or sha256_file(state_path) == locals().get("intended_state_sha256"):
            replace_bytes_atomic(state_path, original_state)
        if manifest_replaced or not manifest_path.exists() or sha256_file(manifest_path) == locals().get("intended_manifest_sha256"):
            replace_bytes_atomic(manifest_path, original_manifest)
        for path in reversed(written):
            if path.exists():
                path.unlink()
        if checkpoint_attempted and checkpoint_output is not None:
            if previous_checkpoint_existed and previous_checkpoint_bytes is not None:
                checkpoint_output.parent.mkdir(parents=True, exist_ok=True)
                checkpoint_output.write_bytes(previous_checkpoint_bytes)
            elif checkpoint_output.exists():
                checkpoint_output.unlink()
        raise

    emit({
        "command": "integrate-candidate-preparation",
        "ok": True,
        "evaluation_id": state["evaluation_id"],
        "candidate_id": receipt["candidate_id"],
        "candidate_sha256": receipt["candidate_sha256"],
        "benchmark_lock": {"path": str(lock_output), "sha256": lock["lock_sha256"], "benchmark_commit": benchmark["commit"], "benchmark_sha256": benchmark["sha256"]},
        "artifacts_written": [{"path": str(path), "sha256": sha256_file(path)} for path in written],
        "checkpoint": checkpoint,
        "transaction_order": integration_report["transaction_order"],
        "full_state_validation": "passed",
        "benchmark_repository_modified": False,
        "next_actions": [next_action],
        "warnings": warnings,
    })


def command_integrate(args: argparse.Namespace) -> None:
    preflight = preflight_integration(
        Path(args.receipt), Path(args.recovery_zip), Path(args.public_dir), Path(args.state),
        Path(args.page_map), Path(args.chunk_manifest), Path(args.policy), Path(args.benchmark_file),
        Path(args.publication_evidence), Path(args.benchmark_proof), args.benchmark_project, args.benchmark_ref, args.pull_request, args.branch,
    )
    merge_evidence_path = Path(args.merge_evidence).resolve()
    merge_evidence = validate_merge_evidence(merge_evidence_path, preflight)
    with evaluation_integration_lock(Path(args.state)):
        validate_preflight_input_hashes(preflight)
        require(
            sha256_file(merge_evidence_path) == merge_evidence["evidence_sha256"],
            "preflight_input_changed",
            "Merged-pull-request evidence changed after validation.",
        )
        _integrate_transaction(args, preflight, merge_evidence)


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


def _add_integration_inputs(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--recovery-zip", required=True)
    parser.add_argument("--public-dir", required=True)
    _add_frozen_inputs(parser)
    parser.add_argument("--benchmark-file", required=True)
    parser.add_argument("--publication-evidence", required=True)
    parser.add_argument("--benchmark-proof", required=True)
    parser.add_argument("--benchmark-project", required=True)
    parser.add_argument("--benchmark-ref", required=True)
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--pull-request", type=int)
    selector.add_argument("--branch")


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

    validate_public = subparsers.add_parser("validate-public", help="Validate the exact three-file public projection")
    validate_public.add_argument("--public-dir", required=True)
    validate_public.set_defaults(func=command_validate_public)

    build_worker = subparsers.add_parser("build-worker", help="Create public projection, private recovery ZIP, and pending receipt")
    _add_private_inputs(build_worker)
    build_worker.add_argument("--project", required=True)
    build_worker.add_argument("--benchmark-project", required=True)
    build_worker.add_argument("--benchmark-ref", required=True)
    build_worker.add_argument("--repository-state", required=True)
    build_worker.add_argument("--branch")
    build_worker.add_argument("--checkpoint-ref", required=True)
    build_worker.add_argument("--public-output", required=True)
    build_worker.add_argument("--recovery-zip", required=True)
    build_worker.add_argument("--receipt-output", required=True)
    build_worker.add_argument("--force", action="store_true")
    build_worker.set_defaults(func=command_build_worker)

    bind = subparsers.add_parser("bind-publication", help="Bind the one-commit open PR to a worker receipt")
    bind.add_argument("--receipt", required=True)
    bind.add_argument("--public-dir", required=True)
    bind.add_argument("--publication-evidence", required=True)
    bind.add_argument("--output", required=True)
    bind.add_argument("--force", action="store_true")
    bind.set_defaults(func=command_bind_publication)

    preflight = subparsers.add_parser("preflight-integration", help="Validate everything before merging the selected public PR")
    _add_integration_inputs(preflight)
    preflight.set_defaults(func=command_preflight_integration)

    integrate = subparsers.add_parser("integrate", help="Integrate exact private bytes after the selected public PR is merged")
    _add_integration_inputs(integrate)
    integrate.add_argument("--merge-evidence", required=True)
    integrate.add_argument("--checkpoint-output")
    integrate.add_argument("--force-checkpoint", action="store_true")
    integrate.set_defaults(func=command_integrate)
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
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        emit({"ok": False, "error": {"code": "candidate_preparation_failure", "message": str(exc)}}, 1)


if __name__ == "__main__":
    main()
