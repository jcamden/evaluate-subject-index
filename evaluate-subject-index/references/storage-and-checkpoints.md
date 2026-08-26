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
│   ├── source-benchmark.draft.v1.json
│   └── source-benchmark.v1.json
├── candidates/
│   └── candidate-id/
│       ├── candidate-ref.json
│       ├── layout-profile.json
│       ├── candidate-layout-extraction.v1.json
│       ├── candidate-index.v2.json
│       ├── item-inventory.v2.json
│       ├── normalization-exceptions.vN.json
│       ├── candidate-benchmark-lock.json
│       ├── locator-packets/
│       ├── locator-audits/
│       ├── missing-access-audits/
│       ├── structure-audit.json
│       ├── item-assessments.json
│       ├── evaluation-result.json
│       └── web-report.json
├── workers/
│   ├── candidate-preparation/
│   ├── locator-audit/
│   │   └── CHUNK-001/                  private isolated worker recovery
│   └── missing-access-audit/
│       └── CHUNK-001/                  private isolated worker recovery
├── validation/
└── exports/
```

The benchmark draft, independent review inventory and ledger, final source benchmark, mapping, chunks, and policy are source-level artifacts. Candidate normalization, audits, scores, and web reports are candidate-level artifacts. Never duplicate or rebuild the source benchmark merely to evaluate another candidate.

## Visibility and retention

- `public`: safe for a customer-facing web report or public repository.
- `private`: audit evidence and normalized data that belong in a portable private audit bundle but not a public page.
- `restricted`: copyrighted source/candidate files, derived chunk PDFs, or long excerpts. Excluded from portable bundles by default.

Retention classes:

- `required`: needed to validate, resume, reproduce, or defend the evaluation.
- `cache`: deterministically regenerable packets or derivatives. Keep during active work; an export may omit them only when bundle metadata records the omission.

`web-report.json` must not embed restricted text. `item-assessments.json` uses short paraphrases and evidence IDs but may also reproduce candidate headings and locator labels, so register it as private by default. Register a public copy only after confirming both public-safety and authority to redistribute the candidate display. `item-inventory.json` remains private because it reproduces the complete normalized candidate structure. Public publishing is a separate action and never follows automatically from creating a bundle.

Register synthesis drafts, review inventories, and review ledgers as private and required by default. They may contain source-derived analysis, diagnostic queues, and superseded judgments. Publication requires an explicit safety and authority check separate from final benchmark publication.

## Frozen artifacts

Do not overwrite a frozen artifact with different bytes. Create a versioned filename, record `supersedes`, recompute dependent artifacts, and invalidate affected stages. The state and artifact manifest may be replaced because they are control files; their hashes are recorded in checkpoint metadata rather than inside themselves.

## Checkpoint milestones

Create a checkpoint at minimum:

1. after page mapping, chunks, and policy are frozen;
2. after the final source benchmark passes independent review and is frozen;
3. after each candidate's complete audit and score;
4. after the final web report; and
5. before a conversation, environment, or operator handoff.

Use `checkpoint` for an in-progress snapshot and `export-bundle` for a named delivery. Both run the same deterministic packaging logic.

- `portable`: includes control files plus public/private registered artifacts and excludes restricted files.
- `private-complete`: includes restricted registered artifacts when the user requests it and has authority to retain them.

Every ZIP contains `bundle-metadata.json` with the profile, evaluation ID, state and manifest hashes, included paths, excluded paths and reasons, and creation time. ZIP member paths are relative and deterministic.

## Parallel worker storage

Never let parallel workers replace the canonical Library state, manifest, or cumulative checkpoint. Give each worker a unique recovery root such as `workers/CHUNK-003/` beneath the study folder. A worker may retain its isolated state, manifest, receipt, artifact, and portable recovery bundle there.

Treat local construction and durable persistence as two explicit phases:

1. Materialize a unique empty local candidate/chunk directory and pass only that directory as `--recovery-root` to the candidate-audit worker builder. The helper derives the canonical receipt and recovery-ZIP names beneath it; do not select those paths separately.
2. Complete local `bind-publication` and `validate-worker`, then copy or replace the exact final canonical receipt and receipt-bound ZIP in the corresponding durable Library worker folder.

The builder preflights the local root before frozen input loading or substantive audit validation. It rejects a non-directory or nonempty root, symlinked boundary, public output inside the private root, or legacy output override that differs from the canonical derived path. A remote Library path or item identifier is a persistence destination, not a local filesystem path for the builder. When Library has been materialized locally, use only the exact isolated local directory and still perform the normal containment checks.

Worker recovery files are not canonical and do not belong in the benchmark pull request. The branch publishes only the unique chapter artifact. After accepted pull requests are merged, the coordinating run materializes those artifacts into the canonical study, registers their hashes, validates the complete run, and creates one new cumulative checkpoint.

A Git branch and Library worker recovery copy serve different purposes: the branch is the reviewable merge proposal; the Library copy preserves work if branch publication is blocked. Neither supersedes canonical integration.

Candidate-preparation workers use a candidate-specific root such as `workers/candidate-preparation/<candidate-id>/`. Keep the complete layout extraction, normalized candidate, inventory, exception ledger, normalization report, full QA ledger, receipt, and preparation-portable ZIP there. The candidate PDF remains restricted and is excluded from the ZIP. The ZIP may contain private JSON; it is a recovery artifact, not a public bundle.

The public worker branch is a separate aggregate projection containing exactly `candidate/candidate-ref.json`, `candidate/layout-profile.json`, and `validation/candidate-preparation-report.json`. It never contains private recovery artifacts. After the pull request opens, persist GitHub-API publication evidence privately and finalize the receipt so it binds the observed PR state, base/head, exact Git blob/file hashes, and evidence hash. The receipt-bound evidence is immutable historical proof and does not expire. At coordinator preflight/integration, preserve a distinct, strictly later open-PR publication snapshot, the final-benchmark Git proof, and post-merge `candidate-preparation-merge-evidence-v1` that does not predate the open snapshot. Create all three directly from connector/API output, not user-authored assertions.

At integration, require the coordinator to name one receipt and recovery root explicitly. Resolve its files through receipt-relative POSIX paths and exact hashes; never search broadly for a matching candidate. Require `--publication-evidence` and `--benchmark-proof` for both helper preflight and integration, plus `--merge-evidence` after merge. Bind the current-attempt premerge hash, merged evidence hash, public blob identities, and benchmark proof identity in `candidate-benchmark-lock.json`; materialize accepted artifacts at new versioned canonical paths, register them, save the manifest, and save state last.

Locator-audit workers use `workers/locator-audit/<chunk-id>/` within an evaluation-specific recovery root. Keep `locator-audit-worker-receipt.json`, isolated `worker-state.json`, `worker-manifest.json`, and `locator-audit-worker-recovery.zip` private. In `aggregate_only`, keep `locator-audit.<chunk-id>.json` private and publish only `validation/locator-audit-worker.<chunk-id>.json`. In `public_evaluation_artifacts`, publish the exact validated audit at `candidate/locator-audits/locator-audit.<chunk-id>.v1.json` while retaining its private recovery copy.

Missing-access workers use `workers/missing-access-audit/<chunk-id>/` under the same candidate-specific isolation rule. Keep `missing-access-worker-receipt.json`, isolated state and manifest, and `missing-access-worker-recovery.zip` private. In `aggregate_only`, keep `missing-access-audit.<chunk-id>.json` private and publish only `validation/missing-access-audit-worker.<chunk-id>.json`. In `public_evaluation_artifacts`, publish the exact validated audit at `candidate/missing-access-audits/missing-access-audit.<chunk-id>.v1.json` while retaining its private recovery copy.

Persist each worker's complete artifact, preliminary receipt, and recovery bundle before attempting publication. After the pull request opens and `bind-publication` plus `validate-worker` succeed, replace the preliminary Library receipt and ZIP in that same chunk folder with the final publication-bound canonical files. Preserve canonical filenames and verify the exact PR URL/head commit plus public-artifact, audit, and recovery-ZIP hashes before declaring the worker complete. Concurrent workers must never replace canonical Library files, another worker's folder, cumulative checkpoints, or shared controls. Aggregate reports contain counts and identity hashes only. Public canonical audits may contain the item-level fields permitted by [publication-profiles.md](publication-profiles.md), but never raw source material, Library identifiers, absolute local paths, or secrets.

For coordinator fan-in, supply an explicit binding for every selected proposal: one pull request or branch, one receipt, and one recovery root. Resolve only those bindings and reject missing, duplicated, ambiguous, or extra recovery material. Never sweep `workers/`, Library, or open pull requests and never infer a receipt from a candidate ID or chunk ID alone.

When agent-side storage transfer alone prevents materializing a missing-access worker handoff under `public_evaluation_artifacts`, create a new isolated coordinator reconstruction root instead of placing private material in the public repository. The reconstructed receipt and ZIP are private required provenance, and the ZIP must contain the complete public audit snapshot, ownership plan, current open-PR evidence, and reconstruction record. Preserve known original worker hashes as declarations only. Do not use this fallback for inaccessible canonical inputs, incomplete public artifacts, aggregate-only reports, or failed substantive validation.

Accepted complete audit ledgers become canonical required artifacts only after coordinator integration. Their manifest visibility is private in `aggregate_only` and public in `public_evaluation_artifacts`. Cumulative private checkpoints may contain those JSON ledgers while continuing to exclude restricted source and candidate PDFs by default. Public GitHub branches never contain worker receipts or recovery ZIPs. Read [parallel-candidate-audits.md](parallel-candidate-audits.md) and [publication-profiles.md](publication-profiles.md).

## HTTP 502 checkpoint transfer recovery

Treat a ChatGPT Library HTTP 502 during authenticated checkpoint byte transfer as a transport failure, not evidence that the checkpoint is missing, invalid, or out of storage capacity. After one confirmed 502, do not keep retrying the same transfer, replace the canonical Library item, or ask the user to re-upload it to Library. Stop before substantive work and return a resumable blocker containing:

- `blocker: checkpoint_transfer_http_502`;
- `resume_mode: manual_checkpoint_attachment`;
- the canonical Library path and filename;
- the expected archive SHA-256; and
- the expected byte length when known.

Ask the user to attach the exact checkpoint to the same worker conversation. On resume:

1. select the attached conversation file only as the alternate transfer source;
2. compute its SHA-256 before extraction and require the expected archive hash;
3. validate the checkpoint metadata, every declared member hash and byte length, path safety, and archive completeness;
4. import into the same new or isolated worker root required by the original command;
5. run complete canonical validation; and
6. continue the original worker workflow without changing its immutable base, frozen identities, denominators, branch, publication profile, or recovery root.

Do not accept a matching filename, attachment metadata, Library identifier, or user assertion in place of byte verification. A mismatched attachment is an integrity failure, not another 502 recovery. Do not use this fallback for permission denial, missing Library metadata, HTTP 404, invalid archive structure, schema failure, member-hash failure, or canonical-validation failure. This checkpoint-input recovery is separate from the coordinator-only `reconstruct-public-handoff` fallback for unavailable missing-access receipts or recovery ZIPs.

## Import and resume

`import-bundle` must reject absolute paths, `..` traversal, duplicate members, and symlink-like entries. Extract into a new or empty directory, validate the state and manifest, and report excluded or missing artifacts. Never treat a successful ZIP extraction as successful evaluation validation.

After import:

1. run `validate`;
2. reconnect any excluded restricted source/candidate file required by the next operation by matching SHA-256, not filename alone; benchmark-first missing-access workers require neither source PDFs nor sidecars;
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
