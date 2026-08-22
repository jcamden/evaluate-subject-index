# Storage and checkpoints

## Authority and durability

The authoritative run is the validated artifact set named by `evaluation-state.json` and `artifact-manifest.json`. Chat prose, attachment presence, temporary paths, Library identity, and downloaded filenames are storage conveniences, not evaluation authority.

For every generated artifact:

1. Write it beneath the evaluation directory.
2. Validate syntax, schema, counts, and dependencies as applicable.
3. Compute SHA-256.
4. Register its relative POSIX path, visibility, retention class, and frozen status.
5. Persist the artifact and manifest.
6. Update `evaluation-state.json` last.
7. Return the registered path and hash in the command response.

Never store absolute workspace paths in portable state. Source and candidate references retain filename, content hash, edition/identity metadata, and optional user-facing storage notes. Runtime paths may appear in command output but not in canonical artifacts.

## Storage modes

| Mode | Behavior |
| --- | --- |
| `local` | Keep the active directory locally. Produce a checkpoint before any conversation or environment boundary. |
| `library` | Save validated artifacts to a dedicated ChatGPT Library study folder. Also export checkpoints at frozen milestones. |
| `hybrid` | Keep the active directory, persist it to Library when available, and export portable checkpoints. This is the ChatGPT default. |

Library is optional. Do not make artifact meaning, identifiers, comparison keys, or resume behavior depend on Library-specific IDs. When Library is used, preserve each file's Library identity on replacement and keep the Library folder structure aligned with the canonical relative paths.

## Study layout

Use one root for a source study and reuse the source package for independently evaluated candidates:

```text
study-root/
├── evaluation-state.json
├── artifact-manifest.json
├── study-manifest.json                 optional multi-candidate registry
├── source/
│   ├── source-ref.json
│   ├── page-map.json
│   ├── chunk-manifest.json
│   ├── evaluation-policy.json
│   ├── chunks/                         restricted PDFs and sidecars
│   ├── source-subjects/
│   └── source-benchmark.v1.json
├── candidates/
│   └── candidate-id/
│       ├── candidate-ref.json
│       ├── candidate-index.json
│       ├── item-inventory.json
│       ├── locator-packets/
│       ├── locator-audits/
│       ├── missing-access-audits/
│       ├── structure-audit.json
│       ├── item-assessments.json
│       ├── evaluation-result.json
│       └── web-report.json
├── validation/
└── exports/
```

The source benchmark, mapping, chunks, and policy are source-level artifacts. Candidate normalization, audits, scores, and web reports are candidate-level artifacts. Never duplicate or rebuild the source benchmark merely to evaluate another candidate.

## Visibility and retention

- `public`: safe for a customer-facing web report or public repository.
- `private`: audit evidence and normalized data that belong in a portable private audit bundle but not a public page.
- `restricted`: copyrighted source/candidate files, derived chunk PDFs, or long excerpts. Excluded from portable bundles by default.

Retention classes:

- `required`: needed to validate, resume, reproduce, or defend the evaluation.
- `cache`: deterministically regenerable packets or derivatives. Keep during active work; an export may omit them only when bundle metadata records the omission.

`web-report.json` must not embed restricted text. `item-assessments.json` uses short paraphrases and evidence IDs but may also reproduce candidate headings and locator labels, so register it as private by default. Register a public copy only after confirming both public-safety and authority to redistribute the candidate display. `item-inventory.json` remains private because it reproduces the complete normalized candidate structure. Public publishing is a separate action and never follows automatically from creating a bundle.

## Frozen artifacts

Do not overwrite a frozen artifact with different bytes. Create a versioned filename, record `supersedes`, recompute dependent artifacts, and invalidate affected stages. The state and artifact manifest may be replaced because they are control files; their hashes are recorded in checkpoint metadata rather than inside themselves.

## Checkpoint milestones

Create a checkpoint at minimum:

1. after page mapping, chunks, and policy are frozen;
2. after the source benchmark is frozen;
3. after each candidate's complete audit and score;
4. after the final web report; and
5. before a conversation, environment, or operator handoff.

Use `checkpoint` for an in-progress snapshot and `export-bundle` for a named delivery. Both run the same deterministic packaging logic.

- `portable`: includes control files plus public/private registered artifacts and excludes restricted files.
- `private-complete`: includes restricted registered artifacts when the user requests it and has authority to retain them.

Every ZIP contains `bundle-metadata.json` with the profile, evaluation ID, state and manifest hashes, included paths, excluded paths and reasons, and creation time. ZIP member paths are relative and deterministic.

## Import and resume

`import-bundle` must reject absolute paths, `..` traversal, duplicate members, and symlink-like entries. Extract into a new or empty directory, validate the state and manifest, and report excluded or missing artifacts. Never treat a successful ZIP extraction as successful evaluation validation.

After import:

1. run `validate`;
2. reconnect any excluded restricted source/candidate file by matching SHA-256, not filename alone;
3. run `status` and `next`; and
4. do not continue a blocked stage until changed or missing dependencies are resolved.

## Command response

Persistence-related responses include:

```json
{
  "command": "checkpoint",
  "ok": true,
  "evaluation_id": "example",
  "storage_mode": "hybrid",
  "artifacts_written": [
    {
      "path": "exports/example-benchmark.zip",
      "sha256": "..."
    }
  ],
  "included_count": 12,
  "excluded_count": 3,
  "next_actions": [],
  "warnings": []
}
```
