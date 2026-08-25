# JSON artifact contracts

The schemas in `schemas/` are machine-readable contracts. Each schema controls extensibility explicitly: strict preparation, publication, proof, lock, and integration contracts reject unexpected fields, while broader evaluation artifacts may preserve richer evidence where their schema permits it. Required identity, status, score, and provenance fields must remain stable.

| Artifact | Schema | Purpose |
| --- | --- | --- |
| Evaluation state | `evaluation-state.schema.json` | Resume, dependency, hash, and next-action state |
| Artifact manifest | `artifact-manifest.schema.json` | Portable relative paths, hashes, visibility, retention, and freeze state |
| Bundle metadata | `bundle-metadata.schema.json` | Checkpoint profile, control hashes, included paths, and exclusions |
| Compact page-map input | `page-map-input.schema.json` | User-approved document-page to source-label ranges |
| Expanded page map | `page-map.schema.json` | One record per original document page |
| Chunk manifest | `chunk-manifest.schema.json` | User-approved ownership and context ranges |
| Policy build input | `policy-build-input.schema.json` | Source-bound facts used to instantiate the standard policy |
| Policy | `evaluation-policy.schema.json` | Run-specific instance of standard policy v1 with frozen scope, audience provenance, gates, and density rules |
| Source chunk | `source-subject-chunk.schema.json` | Candidate-blind chapter/page discoveries |
| Parallel discovery receipt | `parallel-source-discovery-receipt.schema.json` | Branch base, validation summary, publication scope, and PR handoff for one worker chunk |
| Benchmark draft | `source-benchmark-draft.schema.json` | Unfrozen whole-source synthesis awaiting independent review |
| Benchmark review inventory | `source-benchmark-review-inventory.schema.json` | Deterministic review denominators, queues, and diagnostics |
| Benchmark review | `source-benchmark-review.schema.json` | Independent candidate-blind editorial review and freeze recommendation |
| Benchmark | `source-benchmark.schema.json` | Final frozen whole-source subject graph and evidence denominator |
| Normalized candidate | `candidate-index-v2.schema.json` | Fidelity-preserving arbitrary-depth paths, displayed locators, mixed/multiple references, and private evidence joins |
| Item inventory | `item-inventory-v2.schema.json` | Stable identities for candidate-index-v2, including arbitrary heading depth and multiple references |
| Candidate reference | `candidate-ref.schema.json` | Candidate/source identity plus separate provenance, completeness, compatibility, and authoritative-fidelity findings |
| Layout profile | `candidate-layout-profile.schema.json` | Private aggregate PDF/layout and adapter facts used to derive the minimized public profile |
| Layout extraction | `candidate-layout-extraction.schema.json` | Private adapter-neutral page, region, line, coordinate, continuation, and extraction evidence |
| Normalization exceptions | `candidate-normalization-exceptions.schema.json` | Every malformed, unresolved, or fidelity-sensitive preparation exception |
| Normalization report | `candidate-normalization-report.schema.json` | Private aggregate normalization results and private artifact hashes |
| Normalization QA | `candidate-normalization-qa.schema.json` | Complete review denominators, page accounting, corrections, and fidelity gate |
| Preparation receipt | `candidate-preparation-receipt.schema.json` | Worker, repository, source/candidate, private/public hash, PR, recovery, and pending-lock handoff |
| Publication evidence | `candidate-preparation-publication-evidence.schema.json` | GitHub-API proof of the open unmerged one-commit exact-allowlist worker pull request |
| Merge evidence | `candidate-preparation-merge-evidence.schema.json` | GitHub-API proof that the selected exact-allowlist worker pull request closed and merged unchanged |
| Public preparation projection | `candidate-preparation-public-projection.schema.json` | Strict union of the three allowlisted aggregate public documents |
| Public preparation report | `candidate-preparation-report.schema.json` | Strict aggregate public projection with no reconstructable index content |
| Preparation recovery metadata | `candidate-preparation-bundle-metadata.schema.json` | Deterministic private recovery ZIP inventory and restricted exclusions |
| Candidate benchmark lock | `candidate-benchmark-lock.schema.json` | Final benchmark repository/commit/hash and all comparison identities required before candidate audit |
| Benchmark Git proof | `candidate-benchmark-git-proof.schema.json` | GitHub-API proof binding the selected final benchmark path and bytes to its commit |
| Candidate integration report | `candidate-preparation-integration.schema.json` | Selected proposal, immutable hashes, and transaction ordering for accepted preparation |
| Candidate integration checkpoint | `candidate-integration-checkpoint.schema.json` | Private post-integration bundle inventory and exclusions |
| Candidate locator chunk | `candidate-locator-chunk.schema.json` | Only paths and assignments owned by one audit chunk |
| Locator batch | `locator-audit.schema.json` | One judgment for every expanded candidate locator |
| Parallel locator worker receipt | `parallel-locator-audit-worker-receipt.schema.json` | Private identities, denominators, public binding, recovery inventory, and handoff for one chunk |
| Public locator worker report | `locator-audit-worker-report.schema.json` | Strict aggregate projection used by `aggregate_only` |
| Locator integration batch | `locator-audit-batch-integration.schema.json` | Explicit proposals, accepted private artifacts, provenance, conflicts, and stage-completion accounting |
| Missing-access batch | `missing-access-audit.schema.json` | Source-to-index concept coverage and locator recall |
| Parallel missing-access worker receipt | `parallel-missing-access-worker-receipt.schema.json` | Private frozen dependencies, subject/task denominators, public binding, recovery inventory, and handoff |
| Public missing-access worker report | `missing-access-worker-report.schema.json` | Strict aggregate projection used by `aggregate_only` |
| Missing-access integration batch | `missing-access-batch-integration.schema.json` | Explicit proposals, locator dependencies, accepted private artifacts, provenance, and completion accounting |
| Candidate-audit open-PR evidence | `candidate-audit-open-pr-evidence.schema.json` | Fresh GitHub-API observation of one open exact-allowlist worker pull request |
| Candidate-audit merge evidence | `candidate-audit-merge-evidence.schema.json` | Fresh GitHub-API observation that the selected pull request merged unchanged |
| Candidate-audit recovery metadata | `candidate-audit-worker-recovery.schema.json` | Deterministic private ZIP inventory, artifact hashes, and restricted exclusions |
| Candidate-audit integration binding | `candidate-audit-integration-binding.schema.json` | One-to-one coordinator-private proposal, receipt, recovery-root, report, and evidence binding |
| Candidate-audit repository state | `candidate-audit-repository-state.schema.json` | Immutable base branch/commit and existing-branch collision evidence for worker setup |
| Structure audit | `structure-audit.schema.json` | Global hierarchy, navigation, cross-reference, mechanics, and density evidence |
| Item assessments | `item-assessments.schema.json` | Diagnostic grades, semantic color tokens, popover factors, and evidence joins for every display item |
| Density input | `density-input.schema.json` | Chapter word, path, and locator counts for deterministic density scoring |
| Evaluation result | `evaluation-result.schema.json` | Auditable scores, metrics, gates, and comparison key |
| Web report | `web-report.schema.json` | Display-ready narrative and evidence cards |

## Stable identifiers

Use opaque IDs rather than mutable labels:

- `SUBJ-*` for benchmark subjects;
- `PATH-*` for complete candidate heading paths;
- `DISPLAY-*` for displayed locator or range tokens;
- `RANGE-*` for displayed range groupings;
- `LOC-*` for expanded locator assignments;
- `NODE-*` for unique displayed main-heading and subheading nodes;
- `XREF-*` for individual cross-reference records;
- `CHUNK-*` for page ownership units;
- `TASK-*` for reader tasks; and
- `DEFECT-*` for underlying defects.

Use `subject-index-rubric-v4` for newly created results. Its density payload must preserve both standardized targets, target and broad tolerance bands, chapter-level measurements, source-word-weighted aggregation, and the five-point maximum contribution.

Use `subject-index-item-grading-v1` for diagnostic item grades. Keep it separate from the rubric version. Every item assessment requires a semantic color token, explicit grade scope, evidence IDs, and a public-safe popover with structured factors. A null score must use `grade_neutral` and `not_measured`; never convert unknown or uninspectable evidence to zero.

## Null and missing data

Use explicit measurement states such as `measured`, `not_measured`, `uninspectable`, and `not_applicable`. Do not encode unknown values as zero. Rates contain numerator, denominator, value, and excluded counts.

## Canonical hashes

For frozen JSON artifacts, remove the artifact's own hash field, serialize UTF-8 JSON with keys sorted and compact separators, then compute SHA-256. Drafts also receive a deterministic canonical hash in the review inventory, but that hash does not imply freeze. Record schema version, generator version, timestamp, input hashes, and superseded artifact hash when applicable.

Use relative POSIX paths rooted at the evaluation directory in state and manifests. Never store ephemeral absolute paths or make canonical identity depend on a Library ID. Register each artifact only after validation; update state last. Read [storage-and-checkpoints.md](storage-and-checkpoints.md).

Candidate normalization uses candidate-index-v2 and subject-index-item-inventory-v2 only. V2 preserves any delivered third or deeper hierarchy level and `cross_references[]`; it does not imply that those structures satisfy the standard policy. Preparation artifacts remain benchmark-independent, while `candidate-benchmark-lock.json` binds the accepted normalization to the final compatible benchmark before auditing.

Parallel candidate audits reuse `locator-audit-v1` and `missing-access-audit-v1` as their complete judgment formats. Worker receipts, public artifacts, GitHub evidence, recovery metadata, and batch-integration records wrap and bind those canonical artifacts; they do not define alternative scoring or judgment policies. `aggregate_only` keeps the complete audits private and publishes their strict aggregate reports. `public_evaluation_artifacts` publishes the exact validated audits under an additional exact-key, bounded-text, path, and secret allowlist. Read [publication-profiles.md](publication-profiles.md).

Public worker-report schemas are strict allowlists. Permit only aggregate identities, immutable hashes, owned ranges, denominator and status counts, severity/error-code counts, completion, reconnection status, limitations, the private artifact hash, and a public-safety result. Reject candidate headings or subheadings, complete paths, displayed locators or ranges, cross-reference wording, reconstructable source-subject labels, page-specific comparisons, raw extraction, coordinates, exact or extended source text, detailed evidence tied to candidate records, PDFs, Library identifiers, absolute paths, credentials, and secrets.

Publication and merge evidence schemas validate shape, chronology, freshness, branch/base/commit identities, changed paths, Git blob/file hashes, and cross-artifact bindings. They do not authenticate who created a local JSON file. The coordinator must materialize evidence directly from its own GitHub connector/API output; an `evidence_source` string is a format discriminator, never an attestation.

## Web safety

The web report and item assessments should reference evidence IDs and short paraphrases. Keep exact quotations and long copyrighted passages in a restricted audit artifact when lawful, not in either public payload. Preserve candidate labels separately from any organizer blind key until scores are frozen.
