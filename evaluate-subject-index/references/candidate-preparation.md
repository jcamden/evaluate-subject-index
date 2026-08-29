# Parallel candidate preparation

Candidate preparation converts one delivered candidate into a faithful, machine-readable representation before candidate evaluation begins. It is an isolated mechanical lane inside Evaluate Subject Index, not a source-discovery method and not a quality review.

## Contents

- [Authorities and dependency boundary](#authorities-and-dependency-boundary)
- [Commands](#commands)
- [Adapter contract](#adapter-contract)
- [Canonical normalization model](#canonical-normalization-model)
- [Provenance and fidelity](#provenance-and-fidelity)
- [Private artifacts and recovery](#private-artifacts-and-recovery)
- [Full normalization QA gate](#full-normalization-qa-gate)
- [Public worker pull request](#public-worker-pull-request)
- [Worker receipt](#worker-receipt)
- [Coordinator integration](#coordinator-integration)

## Authorities and dependency boundary

The preparation worker may start when these identities are frozen:

- source SHA-256 and edition identity;
- expanded page-map SHA-256;
- chunk-manifest SHA-256;
- policy profile and policy SHA-256;
- legacy preparation-compatibility marker (`subject-index-rubric-v4`) and audit mode; and
- immutable benchmark-repository preparation base commit.

The final benchmark content, commit, and canonical hash are deliberately absent. The worker records `benchmark_lock_status: pending_final_benchmark`. It may register and hash the candidate, assess provenance and internal continuity, extract layout, normalize every delivered item, expand locators through the ordered page map, build the item inventory, perform full normalization QA, create a private recovery bundle, and propose a public-safe pull request.

It must not inspect benchmark subjects; judge locator support, omissions, hierarchy, terminology, cross-reference utility, selectivity, density, or mechanics; calculate scores; build an evaluation report; change canonical evaluation state; or change the benchmark repository. Candidate-preparation artifacts must never be supplied to source-discovery, synthesis, or benchmark-review workers.

The coordinator may integrate preparation only after `benchmark_freeze` is complete. Integration pins a compatible final benchmark commit and canonical hash, completes the existing `candidate_normalization` stage, and unlocks locator-packet preparation. No new state stage or state-schema migration is required.

## Commands

```text
worker-candidate-preparation <candidate-id>
  --project <candidate-evaluation-repository>
  --benchmark-project <benchmark-repository>
  [--benchmark-ref <preparation-base-commit>]
  [--adapter auto|generic-pdf-layout|indexerlabs-two-column]
```

When `--benchmark-ref` is omitted, resolve the benchmark repository's default-branch head once and record the immutable commit before work begins. The default adapter is `auto`.

```text
integrate-candidate-preparation
  --project <candidate-evaluation-repository>
  --benchmark-project <benchmark-repository>
  --benchmark-ref <final-canonical-commit>
  <pull-request-or-branch>
```

Integration always requires exactly one explicit proposal. Never sweep open pull requests, branches, worker directories, checkpoints, or Library content.

These are high-level prompt commands. During `worker-candidate-preparation`, the orchestrator obtains GitHub API evidence after opening the pull request and must pass it to the deterministic helper as `bind-publication --publication-evidence <file>`. Before merge, both `preflight-integration` and `integrate` require an open-PR snapshot acquired directly for the current integration attempt as `--publication-evidence <file>` plus final-benchmark proof as `--benchmark-proof <file>`. After merge, `integrate` additionally requires the closed-and-merged snapshot as `--merge-evidence <file>`. Materialize every evidence file directly from GitHub connector/API output; do not accept user-authored JSON, attestations, or command-line assertions as evidence.

The helper can validate evidence structure, chronology, object identities, Git blob hashes, file hashes, and cross-artifact consistency, but a local JSON file has no intrinsic authenticated provenance. The orchestrator's direct connector/API observation is therefore the trust boundary. Do not use a user- or worker-supplied evidence file, and do not interpret `evidence_source: github_api` as a signature. The synthetic fixture builders used by tests model connector responses only; they are not an evidence-acquisition mechanism.

The publication evidence recorded in the immutable receipt remains valid historical proof of what the worker bound and does not expire. It is distinct from the coordinator's current-attempt snapshot required at preflight/integration, whose SHA-256 becomes `premerge_evidence_sha256`, and from the post-merge snapshot, whose SHA-256 becomes `merge_evidence_sha256`. No evidence or immutable benchmark proof expires because a fixed number of hours elapsed; `observed_at` is used only for provenance and chronology.

The evidence-bearing deterministic helper syntax is:

```text
candidate_preparation_cli.py preflight-integration ...
  --publication-evidence <current-open-pr-api.json>
  --benchmark-proof <final-benchmark-api.json>

candidate_preparation_cli.py integrate ...
  --publication-evidence <current-open-pr-api.json>
  --benchmark-proof <final-benchmark-api.json>
  --merge-evidence <post-merge-pr-api.json>
```

## Adapter contract

Adapters stop at layout evidence. They do not repair wording or infer editorial quality. Every adapter emits `candidate-layout-extraction-v1` with:

- candidate PDF page and technical metadata;
- reading-order region and column;
- bounding box;
- indentation level;
- displayed line text and original displayed form;
- incoming and outgoing continuation status;
- inferred entry, subentry, continuation, or unknown boundary;
- extraction confidence and warnings; and
- complete accounting for excluded headers and footers.

`auto` records both the requested selector and the selected concrete adapter, its version, confidence/evidence, and limitations. `generic-pdf-layout` uses embedded text geometry without assuming a vendor. `indexerlabs-two-column` is a ReportLab/two-column geometry profile beneath the same contract; it must not hard-code book content, heading vocabulary, or vendor-specific index semantics. Future Indexia, IndexPDF, OCR, or other adapters must emit the same intermediate representation.

Initial adapters support embedded-text PDFs. Image-only, encrypted, or geometrically untrustworthy inputs stop as incomplete or blocked; they are not silently OCRed or described as complete.

## Canonical normalization model

Preparation emits `candidate-index-v2` and `subject-index-item-inventory-v2` only.

When exactly one preparation already exists for the candidate and no candidate judgment has begun, regenerate that preparation in place under the v2 contracts, re-run full QA, and replace its pending receipt and recovery bundle. Keep only the v2 candidate and inventory contracts. If locator auditing or any later candidate judgment has begun, refuse the in-place update and start a new candidate evaluation identity instead.

Candidate v2 preserves:

- every record and its original displayed form;
- every hierarchy level, including impermissible third or deeper levels;
- complete heading paths and stable `PATH-*` identities;
- every displayed locator or range with a stable display identity;
- every expanded atomic `LOC-*` assignment;
- every `see` and `see also` as an individual `XREF-*` record;
- locators and cross-references mixed on the same delivered record;
- page, column, and line evidence references;
- punctuation, capitalization, accents, apostrophes, spelling, and diacritics;
- unresolved or malformed records and their exception IDs; and
- normalization and extraction confidence without editorial judgment.

Do not flatten a third-level heading to satisfy the evaluation policy. Do not merge duplicate paths, correct filing, rewrite wording, change a locator, or repair a cross-reference target. Preserve the delivered form and record a normalization exception where needed. The later structure audit owns quality judgments and publication-readiness gates.

Resolve a point locator through the frozen page map. For a range, resolve both displayed endpoints and walk the intervening ordered page-map records within the same `mapping_id`; never use a global Arabic offset. An abbreviated numeric endpoint may be completed only when it uniquely identifies a later acceptable label in that same mapping segment. Retain the displayed range and record ambiguous, reversed, cross-segment, or unresolved endpoints explicitly.

## Provenance and fidelity

`candidate-ref-v1` records six independent findings, each with a status and rationale:

1. candidate bytes verified by SHA-256;
2. internal PDF completeness;
3. alphabetical or structural continuity;
4. source-edition compatibility;
5. locator/page-map compatibility; and
6. independently verified fidelity to an authoritative copy.

Allowed statuses are `verified`, `not_independently_verified`, `incomplete`, `conflicting_evidence`, and `not_applicable`. Internal completeness never implies authoritative-copy fidelity. A transcription or reconstructed PDF must not claim to be an original publisher PDF. A publisher index is one candidate, not the benchmark or presumed ground truth.

Classify file origin only as `delivered_pdf`, `reconstructed_pdf`, or `transcription`. `delivered_pdf` means the bytes were delivered for evaluation; it does not itself assert publisher authority or fidelity. Use the separate authoritative-copy finding for that claim.

## Private artifacts and recovery

Use candidate-isolated versioned paths:

```text
candidates/<candidate-id>/
├── candidate-ref.json
├── layout-profile.json
├── candidate-layout-extraction.v1.json
├── candidate-index.draft.v2.json
├── item-inventory.draft.v2.json
└── normalization-exceptions.v1.json
validation/
├── candidate-normalization-report.<candidate-id>.v1.json
├── candidate-normalization-qa.<candidate-id>.v1.json
├── candidate-preparation-publication-evidence.<candidate-id>.v1.json
├── candidate-benchmark-git-proof.<candidate-id>.v1.json
├── candidate-preparation-merge-evidence.<candidate-id>.v1.json
└── candidate-preparation-receipt.<candidate-id>.json
exports/
└── <candidate-id>-preparation-portable.zip
```

The untouched candidate PDF is restricted and never enters the recovery ZIP or GitHub. Layout extraction, coordinates, normalized records, item inventory, exception detail, full QA, and the recovery ZIP are private. A preparation recovery ZIP may contain private JSON even though it excludes restricted inputs; it is a recovery artifact, not a publication artifact.

Package the recovery ZIP before finalizing the receipt so the receipt can bind its SHA-256 without a hash cycle. The ZIP uses its own preparation-bundle metadata and need not mutate or complete canonical evaluation state.

## Full normalization QA gate

Full mode requires exact ID accounting—not only matching counts—for every:

- candidate PDF page;
- reading-order region and extracted/excluded line;
- main heading and subheading;
- complete heading path;
- displayed locator or range;
- expanded locator assignment;
- cross-reference; and
- extraction or normalization exception.

Every page review records regions and lines, first and last record identities, item counts, continuation handling, corrections, unresolved items, and confirmation that corrections reproduce the candidate rather than improve it. Corrections create new versioned draft bytes and invalidate the previous QA hash; never silently edit a reviewed draft.

The deterministic validator rejects missing pages, missing or duplicate IDs, unaccounted regions or lines, malformed references not represented in exceptions, unresolved locators omitted from exceptions, item-inventory parity failures, expansions outside the page map, candidate/source/page-map hash mismatches, incomplete denominators, undispositioned exceptions, and changed normalized bytes. Extraction confidence remains distinct from later editorial confidence.

## Public worker pull request

The default branch is `candidate-preparation/<normalized-candidate-id>`. Refuse an existing branch. The branch diff has an exact allowlist:

```text
candidate/candidate-ref.json
candidate/layout-profile.json
validation/candidate-preparation-report.json
```

These files are strict aggregate projections. They include candidate/source identities and hashes, source edition, status-only provenance, adapter identity/version, page count and embedded-text status, an aggregate index-column histogram, a limitation count, aggregate normalization and QA denominators, aggregate exception counts, and pending benchmark-lock status. Provenance rationales, adapter evidence, producer strings, per-page column arrays, limitation text, and private artifact hashes remain private.

They must not include PDFs, images, ZIPs, raw or substantially reconstructable index text, headings, locator lists, record arrays, item inventory, page-level QA, coordinates, long quotation, secrets, absolute paths, Library IDs, or private checkpoint contents. Validate strict public schemas, scan recursively for restricted keys and values, verify the exact path allowlist, and manually inspect the outgoing JSON before publication.

If the target repository is completely empty, one root bootstrap commit on `main` must contain exactly `README.md` and `.gitignore`. GitHub-API evidence must record the preceding empty-repository observation, the root commit with no parents, and the complete two-blob tree with blob and file hashes. Bind that evidence hash and bootstrap commit in the receipt. Do not use the exception when a default branch already exists.

Create one worker commit and one pull request. Do not merge it. Query the GitHub API after the pull request opens and persist schema-valid `candidate-preparation-publication-evidence-v1`; do not accept caller-supplied branch, commit, state, merge, or file-list assertions as proof. The evidence must show the expected repository, URL/number, open and unmerged state, base/head branches and 40-character commits, exactly one worker commit, and exactly the three allowlisted files with Git blob and recomputed file SHA-256 identities. Bind it with `candidate_preparation_cli.py bind-publication --publication-evidence <file>`. Record its hash and observation time in the private receipt. After one explicit denial, preserve private recovery work and stop retrying.

At coordinator preflight, query the GitHub API again and pass that current-attempt open/unmerged observation as `--publication-evidence <file>` to both `preflight-integration` and `integrate`. It must be a distinct byte artifact observed strictly later than the receipt-binding snapshot. The immutable receipt's original evidence is historical and does not become invalid merely because its observation time is old, but it cannot stand in for the current-attempt premerge observation. The post-merge observation must be at least as late as that premerge snapshot. If work resumes after an interruption, reacquire the open-PR and benchmark observations instead of deciding reuse from timestamp age.

## Worker receipt

`candidate-preparation-receipt-v1` binds:

- candidate ID and candidate SHA-256;
- source SHA-256 and edition identity;
- page-map, chunk-manifest, policy, legacy preparation-marker, and audit-mode identities;
- benchmark repository and preparation base commit;
- adapter ID/version;
- exact private artifact paths and hashes;
- exact public paths and hashes;
- worker branch and pull-request identity;
- GitHub-observed base/head, exact public file/blob hashes, publication-evidence hash, and observation time;
- recovery ZIP hash;
- preparation and normalization-QA status;
- pending benchmark-lock status;
- bootstrap facts; and
- limitations.

The receipt is private. It is a handoff record, not a canonical evaluation artifact and not the public report.

## Coordinator integration

Before any merge, the coordinator must:

1. create schema-valid `candidate-preparation-publication-evidence-v1` directly from GitHub connector/API output acquired for the current integration attempt, pass it through `--publication-evidence`, and verify the explicit PR/branch is open, unchanged, and targets the expected base;
2. verify its exact three-path allowlist and public-safety scan;
3. resolve the explicitly supplied private receipt/recovery root by candidate ID and SHA-256;
4. validate every private artifact and full QA denominator;
5. resolve the explicit final benchmark commit, require a schema-valid `candidate-benchmark-git-proof-v1` observed from the GitHub API, verify its repository/path/commit/blob/file hashes against the selected benchmark bytes, and recompute the benchmark canonical hash;
6. require matching source, edition, page map, chunks, policy, preparation marker, audit mode, and uncertainty rules;
7. reject an incompatible final page map or changed candidate normalization;
8. after validating the Git proof, validate every final-benchmark and compatibility field intended for `candidate-benchmark-lock.json`, but do not write or finalize the lock before merged-PR evidence exists; and
9. validate the complete integration plan without mutating canonical state.

Only after all checks pass may the coordinator merge the public-safe pull request. Query the GitHub API after merge and create strict `candidate-preparation-merge-evidence-v1` directly from the connector response; never accept a user-authored merged-state assertion. Pass it to `candidate_preparation_cli.py integrate --merge-evidence <file>`. It must prove the same repository, PR number/URL, base/head branches and commits, closed-and-merged state, one worker commit, merge commit, and the exact three changed paths with matching Git blob and file SHA-256 identities. The benchmark lock records the current-attempt premerge and merge evidence hashes, exact public blob map, and final-benchmark proof identity; the integration report records all three evidence hashes.

Then materialize the exact private worker bytes at versioned canonical paths, register the candidate reference, layout profile, normalized candidate, inventory, exceptions, reports, QA, receipt, and benchmark lock. Write artifacts first, update the artifact manifest, update `evaluation-state.json` last, run complete validation, and create a cumulative private recovery checkpoint. A failure before manifest/state update leaves recoverable unregistered files, not a falsely completed stage.

Do not update the benchmark repository. Do not allow locator packets, locator audits, missing-access work, structure audit, density, scoring, or reporting until the final benchmark lock validates.
