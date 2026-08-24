# Parallel candidate audits

This reference defines collision-safe chapter workers and transactional coordinator integration for locator and missing-access auditing. The parallel lanes use the same substantive judgment contracts as `audit-locators` and `audit-missing-access`; they change ownership and persistence, not policy or scoring.

## Contents

- [State compatibility and schedule](#state-compatibility-and-schedule)
- [Shared worker rules](#shared-worker-rules)
- [Locator-audit worker](#locator-audit-worker)
- [Locator-audit integration](#locator-audit-integration)
- [Missing-access ownership](#missing-access-ownership)
- [Missing-access worker](#missing-access-worker)
- [Missing-access integration](#missing-access-integration)
- [Private and public boundary](#private-and-public-boundary)
- [Recovery and explicit proposal binding](#recovery-and-explicit-proposal-binding)
- [GitHub evidence](#github-evidence)
- [Deterministic helper](#deterministic-helper)
- [Help, status, next, and resume](#help-status-next-and-resume)
- [Failure and rerun rules](#failure-and-rerun-rules)

## State compatibility and schedule

Keep `subject-index-evaluation-state-v4` and the existing 16 numbered stages. Do not add worker or integration stages. Successful fan-in fulfills `locator_audit` or `missing_access_audit`.

Use this order:

```text
candidate preparation worker
        ↓
integrate candidate preparation
        ↓
prepare locator chunks
        ↓
17 locator-audit workers in parallel
        ↓
integrate locator-audit PRs in one or more explicit validated batches
        ↓
17 missing-access workers in parallel
        ↓
integrate missing-access PRs in one or more explicit validated batches
        ↓
single global structure audit
        ↓
item assessments and scoring
        ↓
web report
```

Use the actual frozen chunk count when it is not 17. Do not run missing-access workers while any locator chunk remains unintegrated. A per-chunk locator result cannot bypass the full canonical locator-audit gate because missing-access review may need another candidate route.

Sequential operation remains valid:

- `audit-locators [chunk-id]` writes the same canonical locator judgment format.
- `audit-missing-access [chunk-id]` writes the same canonical missing-access format.
- Parallel integration may accept only nonconflicting artifacts under the same frozen identities and completion rules.

## Shared worker rules

One worker owns one candidate, one audit type, and one exact chunk. Require:

- an immutable candidate-repository base commit and recorded base branch;
- an isolated candidate- and chunk-specific recovery root;
- exact frozen source, candidate, benchmark, policy, page-map, and chunk-manifest identities;
- the normalized candidate and item inventory identities;
- the exact restricted source chunk and sidecar reconnected by source SHA-256;
- all stage-specific packets, locks, and canonical dependencies; and
- a branch name derived from the audit type and lowercase chunk ID.

Import the compatible validated checkpoint into isolation. Validate every input before substantive work. Never use conversational memory, a filename, a Library identifier, or a candidate ID in place of a content hash and explicit artifact binding.

Workers may write only their isolated private state. They never update canonical:

- `evaluation-state.json`;
- `artifact-manifest.json`;
- benchmark locks;
- cumulative checkpoints;
- shared integration records;
- another worker's folder; or
- structure, scoring, item-assessment, or web-report artifacts.

Persist complete private work before attempting GitHub publication. Create one commit and one open, unmerged pull request. Refuse to overwrite an existing worker branch and never merge the worker's own pull request.

## Locator-audit worker

Invoke:

```text
worker-locator-audit [chunk-id] --project [candidate-evaluation-repository]
```

Default the branch to:

```text
locator-audit/<lowercase-chunk-id>
```

Require completed validated candidate normalization, a final frozen candidate benchmark lock, complete locator-packet preparation, and the exact locator-only packet for the selected chunk. Verify source, candidate, benchmark, policy, page-map, chunk-manifest, normalized-candidate, inventory, packet, base-commit, and recovery identities.

The locator packet is the complete denominator. For every owned expanded assignment:

1. preserve its complete heading path;
2. inspect the exact mapped source page and allowed context;
3. judge it exactly once as `supported`, `partially_supported`, `unsupported`, or `uninspectable`;
4. record a short public-safe evidence paraphrase, evidence IDs, error codes, severity, and confidence; and
5. retain any restricted quotation or extended evidence only in a private evidence ledger.

Reject duplicate assignment IDs, missing assignments, foreign-chunk assignments, changed paths, wrong owned pages, or a packet whose recorded hash does not match. Do not treat unresolved routing exceptions as owned assignments. Use `uninspectable` only for an owned assignment whose source or mapping genuinely cannot be inspected under the frozen policy.

Private worker layout:

```text
workers/locator-audit/<chunk-id>/
├── locator-audit.<chunk-id>.json
├── locator-audit-worker-receipt.json
├── worker-state.json
├── worker-manifest.json
└── locator-audit-worker-recovery.zip
```

Publish exactly:

```text
validation/locator-audit-worker.<chunk-id>.json
```

Do not perform missing-access judgments, global structure judgments, density calculations, scoring, item assessments, or web reporting. Do not modify normalized candidate content or the benchmark repository.

## Locator-audit integration

Invoke:

```text
integrate-locator-audits --project [candidate-evaluation-repository] [pull-request-or-branch ...]
```

This command is the sole coordinator authority. Require an explicit nonempty proposal list. Bind every selected proposal to exactly one explicitly identified private receipt and recovery root before preflight.

Before merging anything:

1. obtain fresh open-PR evidence directly from the GitHub connector/API for every selected proposal;
2. verify it is open, targets the expected base, originates from `locator-audit/<chunk-id>`, and changes exactly the allowed aggregate report;
3. reject control files, checkpoints, PDFs, private audit data, receipts, recovery bundles, and unrelated paths;
4. require one unique chunk per selected worker;
5. validate each receipt, recovery inventory, private artifact hash, and public/private hash binding;
6. require identical frozen source, candidate, benchmark, policy, page-map, chunk-manifest, normalized-candidate, inventory, and packet identities;
7. verify exact owned pages and packet assignment denominators;
8. require the batch assignment union to contain every selected packet assignment exactly once; and
9. reject overlap, missing IDs, duplicates, foreign assignments, stale evidence, and conflicting prior integration.

Run preflight for the complete selected batch in a disposable integration area. If any member fails, merge none.

After preflight passes:

1. merge only the selected public-safe proposals;
2. obtain fresh merged-PR evidence directly from the connector/API;
3. materialize the exact accepted private audit bytes at versioned canonical paths;
4. preserve worker, proposal, base/head/merge commit, receipt, recovery, evidence, and artifact hashes;
5. register private required artifacts and integration provenance in the artifact manifest;
6. save the manifest before changing state;
7. mark `locator_audit` complete only when every frozen locator packet has one accepted audit and the global assignment union is exact;
8. otherwise leave the stage `in_progress` with validated partial completion;
9. validate the complete canonical evaluation;
10. create a cumulative private checkpoint; and
11. create one shared-control commit.

GitHub does not provide a transaction that atomically merges several pull requests. The coordinator's all-or-none guarantee therefore applies to deterministic preflight and canonical private integration. Merge selected PRs only after the whole batch passes; if any external merge then fails, stop before canonical integration, preserve the already-observed GitHub state, and require an explicit reconciliation preflight for the still-selected proposals.

Recognize an identical already-integrated chunk idempotently. Reject a different artifact, receipt, packet, or proposal for the same chunk as a conflict requiring explicit adjudication; never overwrite it silently.

## Missing-access ownership

The helper computes one deterministic ownership plan from the frozen benchmark and chunk manifest. Bind its canonical hash into every missing-access receipt.

For a scored subject:

1. use `owner_chunk_id` when it names a valid frozen chunk;
2. otherwise use the chunk owning the subject's first principal evidence page, ordered by document page and then chunk order; or
3. when there is no principal evidence, use the first non-incidental scored evidence by the same order.

For a reader task:

1. use `owner_chunk_id` when it names a valid frozen chunk; or
2. otherwise use the owner of the first subject in the task's frozen `subject_ids` order.

Do not let a model choose or rebalance owners. Reject an ownership plan that omits a required scored subject or task, assigns one more than once, points outside the frozen chunks, or changes under identical inputs.

## Missing-access worker

Invoke:

```text
worker-missing-access-audit [chunk-id] --project [candidate-evaluation-repository]
```

Default the branch to:

```text
missing-access-audit/<lowercase-chunk-id>
```

Block the worker until candidate normalization and locator packets are complete, every locator audit is canonically integrated, and the canonical evaluation validates. Require the frozen final benchmark, complete normalized candidate, inventory, complete canonical locator-audit set, source/candidate identities, policy, page map, chunk manifest, exact source chunk and sidecar, immutable base commit, isolated private storage, and deterministic ownership-plan hash.

For every required scored subject owned by the chunk, test:

- plausible direct access;
- valid cross-reference access;
- preservation of distinctions and stance;
- principal, supporting, and synthesis/conclusion treatment coverage;
- realistic first-lookup success;
- concept coverage and locator recall as separate denominators;
- missed treatments and missing routes; and
- severity, confidence, uncertainty, and evidence IDs.

For every owned reader task, record one result with the tested routes, success state, confidence, and evidence IDs. Require exact subject-ID and task-ID accounting. Preserve treatment-class counts independently of concept coverage.

Use the canonical locator set as a dependency. Do not silently revise locator legitimacy. If a coverage result exposes a suspected locator problem, record a formal dependency defect identifying the affected locator and coverage IDs, observed conflict, confidence, and required adjudication.

Private worker layout:

```text
workers/missing-access-audit/<chunk-id>/
├── missing-access-audit.<chunk-id>.json
├── missing-access-worker-receipt.json
├── worker-state.json
├── worker-manifest.json
└── missing-access-worker-recovery.zip
```

Publish exactly:

```text
validation/missing-access-audit-worker.<chunk-id>.json
```

Do not change the benchmark, normalized candidate, or canonical locator set. Do not perform global structure, density, scoring, item-assessment, or web-report work.

## Missing-access integration

Invoke:

```text
integrate-missing-access-audits --project [candidate-evaluation-repository] [pull-request-or-branch ...]
```

Use the same explicit, transactional coordinator pattern. Before merging:

1. require complete canonical locator-audit inputs and a valid canonical evaluation;
2. obtain fresh open-PR evidence directly from the GitHub connector/API;
3. enforce the exact one-report public allowlist;
4. resolve the exact private receipt and recovery root bound to every selected proposal;
5. verify frozen identities, ownership-plan hash, canonical locator-set identity, recovery inventory, and private/public hashes;
6. require unique chunk ownership;
7. verify exact required subject, reader-task, concept, locator-recall, and treatment denominators; and
8. reject missing, duplicate, foreign-chunk, incompatible, or conflicting judgments.

Validate the complete selected batch before merging any member. If one fails, merge none.

After successful preflight, merge only selected proposals, obtain fresh merged evidence, materialize exact accepted private bytes, record provenance, update manifest first and state last, and validate. Complete `missing_access_audit` only when every required chunk, subject, task, and treatment denominator is covered exactly once. Otherwise preserve validated partial completion. Create one cumulative private checkpoint and one shared-control commit.

## Private and public boundary

Keep private:

- complete locator and missing-access audits;
- detailed evidence ledgers and reconstructable paraphrases;
- worker receipts, state, manifests, and recovery ZIPs;
- normalized candidate, item inventory, locator packets, and ownership plans;
- source/candidate packets and PDFs; and
- connector evidence and coordinator binding records.

Each worker branch publishes exactly one aggregate report. A public report may contain only:

- evaluation ID and candidate ID without candidate content;
- chunk ID and source-unit label;
- immutable base commit and expected branch/base identities;
- source, candidate, benchmark, policy, page-map, chunk-manifest, normalized-candidate, inventory, packet, ownership-plan, and worker-artifact hashes as applicable;
- benchmark version and canonical hash;
- owned document-page ranges;
- aggregate denominators and judgment/status counts;
- aggregate severity and error-code counts;
- completion and source/candidate reconnection status;
- bounded aggregate limitations; and
- a public-safety result.

A public report must not contain:

- candidate headings, subheadings, complete paths, displayed locators/ranges, or cross-reference wording;
- source-subject labels whose combination reconstructs audit content;
- page-specific candidate/source comparisons;
- raw extraction, coordinates, exact or extended source text, or detailed evidence tied to candidate records;
- source/candidate PDFs or packets;
- Library identifiers or absolute local paths; or
- credentials, secrets, or tokens.

Generate public projections deterministically from a strict allowlist. Validate their schema, recursively reject forbidden keys, scan bounded free-text values, and inspect the exact outgoing diff. A passing schema alone does not establish publication safety.

## Recovery and explicit proposal binding

The public branch is a reviewable aggregate proposal. The private recovery root preserves the actual work. Neither becomes canonical until coordinator integration.

For each selected proposal, provide one structured private binding containing:

- the exact pull-request URL/number or branch ref;
- the exact private receipt path; and
- the exact recovery root containing the receipt-bound files.

Treat bindings as coordinator-private runtime input. Validate one-to-one cardinality: every selected proposal has one binding, every binding names one selected proposal, and no receipt or recovery root is reused ambiguously. Resolve only receipt-relative POSIX paths and exact hashes. Reject missing or extra bindings, ambiguous roots, traversal, absolute paths stored in portable artifacts, and content inferred from candidate or chunk IDs. Never sweep Library folders, `workers/`, or open pull requests.

Worker recovery ZIPs are private, deterministic inventories. Exclude restricted PDFs and the final receipt to avoid a self-referential hash cycle. Include the complete private JSON audit, worker state, worker manifest, and recovery metadata; bind the final receipt to the finished ZIP hash outside the archive. Validate the ZIP before publication and again during coordinator preflight.

## GitHub evidence

Treat GitHub state as externally observed evidence, not a caller assertion.

The worker or coordinator orchestrator must create evidence JSON directly from GitHub connector/API output. Validate:

- repository, pull-request number/URL, open or merged state, and chronology;
- expected base/head branches and immutable commits;
- exact commit count when the contract requires one commit;
- changed path allowlist;
- Git blob and downloaded file hashes; and
- observation time and freshness for coordinator preflight.

The worker's publication observation is immutable historical receipt evidence. Coordinator premerge evidence is a separate, fresh observation. Merged evidence is a third observation obtained only after merge and cannot predate premerge evidence.

The deterministic helper can validate a local evidence file's structure, hash, freshness, and bindings, but it cannot authenticate who created that file. Never accept evidence supplied by a user or worker for coordinator authority. Never treat an `evidence_source` string as authentication or a signature. Synthetic tests may construct evidence fixtures only to test deterministic validation.

## Deterministic helper

Use `scripts/parallel_candidate_audit_cli.py`. Keep denominator arithmetic, identity hashes, recovery validation, conflict detection, and stage completion out of model-maintained prose.

Provide these operations:

| Operation | Responsibility |
| --- | --- |
| `build-locator-worker` | Validate the locator packet/private audit, compute exact counts and hashes, build recovery metadata and the strict public projection, and create a pending private receipt. |
| `build-missing-access-worker` | Derive and hash deterministic subject/task ownership, validate the complete private audit and denominators, build recovery metadata/public projection, and create a pending receipt. |
| `bind-publication` | Bind one open exact-allowlist pull-request observation, public blob/file hashes, branch/base commits, and proposal identity into the private receipt. |
| `validate-worker` | Recompute schemas, hashes, identities, denominators, public safety, receipt bindings, and recovery completeness without mutating canonical state. |
| `preflight-batch` | Validate an explicit proposal/binding batch transactionally, enforce fresh API evidence and uniqueness, detect duplicates/conflicts, and produce a no-mutation integration plan. |
| `integrate-batch` | After merged evidence, materialize exact private bytes, record provenance, update manifest before state, and refuse any input that differs from preflight. |
| `completion` | Compute accepted chunks and exact locator-assignment or subject/task coverage, report missing/conflicting IDs, and decide whether the existing stage may complete. |

Validate content, schema, canonical hashes, file hashes, chronology, API-evidence freshness, repository/branch/base/commit identity, source/candidate reconnection, and cross-artifact bindings. Reuse established safe utility functions only when doing so cannot change existing candidate-preparation behavior. The helper performs no substantive judgment and does not modify candidate-preparation scripts or contracts.

## Help, status, next, and resume

`help` lists the four parallel commands beside their canonical stages and reports their dependencies and completion tests. `status` may report validated partial batch coverage and auxiliary availability.

`next` remains canonical and backward compatible:

- at stage 12 it names `audit-locators` and may separately offer locator workers/integration;
- at stage 13 it names `audit-missing-access` and may separately offer missing-access workers/integration; and
- it never offers missing-access work before canonical locator completion.

On resume, materialize the canonical study and only the explicitly selected worker recovery roots. Reconnect restricted source/candidate inputs by SHA-256, validate canonical state, then validate each selected worker. Do not infer completion from merged public reports alone; canonical private integration and manifest registration are required.

## Failure and rerun rules

- An existing worker branch is a hard stop; do not overwrite it.
- A publication denial leaves private recovery intact and returns `blocked`; do not retry the same denied write repeatedly.
- Any invalid member makes selected-batch preflight fail atomically; merge none.
- A partial successful batch remains resumable and does not complete its stage prematurely.
- An identical integrated chunk is idempotent; a different artifact, receipt, packet, ownership plan, or dependency for that chunk is a conflict.
- Changing locator packets invalidates corresponding locator receipts, reports, recovery, integrations, and all missing-access work that depends on them.
- Changing the canonical locator set, benchmark, subject/task ownership inputs, normalized candidate, inventory, policy, page map, chunk manifest, source, or candidate identity invalidates affected pending workers.
- Never repair a failed worker by editing its public aggregate report independently of the private artifact and receipt. Regenerate the worker result under a new collision-free branch after resolving the defect.
