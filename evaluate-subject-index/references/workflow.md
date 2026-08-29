# Workflow and state machine

The numbered source, benchmark, candidate, and audit stages remain unchanged in V7. The current scoring-stage integration is specified in [workflow-v7.md](workflow-v7.md): native V7 adds a structured architecture-review decision layer, derives display/range/atomic metrics, and calculates with rubric V7/profile V3. V6-to-V7 score-only migration invalidates only active calculation/display projections after fail-closed sufficiency checks and preserves V4–V6 history.

## Stage order

| Stage | Command | Completion artifact |
| --- | --- | --- |
| 1 | `initialize` | `evaluation-state.json` |
| 2 | `map-pages` | `page-map.json` |
| 3 | `define-chunks` | `chunk-manifest.json` |
| 4 | `define-policy` | run-specific instance of the built-in `evaluation-policy.json` |
| 5 | `prepare-source-chunks` | chunk PDFs and sidecar maps |
| 6 | `discover-source-subjects` | all `source-subject-chunk.*.json` files |
| 7 | `synthesize-source-benchmark` | `source-benchmark.draft.vN.json` |
| 8 | `review-source-benchmark` | review inventory and `source-benchmark-review.vN.json` |
| 9 | `freeze-source-benchmark` | `source-benchmark.vN.json` |
| 10 | `normalize-index` | `candidate-index.json` and `item-inventory.json` |
| 11 | `prepare-locator-chunks` | all `candidate-locator-chunk.*.json` files and exception ledger |
| 12 | `audit-locators` | all `locator-audit.*.json` files |
| 13 | `audit-missing-access` | all `missing-access-audit.*.json` files |
| 14 | `audit-index-structure` | `structure-audit.json` |
| 15 | `score-index` | `item-assessments.json`, `dimension-calculations.json`, and `evaluation-result.json` |
| 16 | `build-web-report` | `web-report.json` |

Each stage status is `not_started`, `in_progress`, `completed`, or `blocked`. A stage may start only when every earlier required stage is complete. `validate` may run at any time.

Candidate preparation is a parallel worker lane, not a numbered state stage. It may begin after source identity, edition, page map, chunks, judgment policy, and audit mode are frozen, while source discovery or benchmark synthesis/review continues in candidate-blind contexts. Its version-one receipt retains a `subject-index-rubric-v4` compatibility marker for the historical preparation contract, but that marker is not the active score identity. `integrate-candidate-preparation` is blocked until final benchmark freeze; successful integration fulfills stage 10 (`candidate_normalization`) without changing the state schema or weakening the linear candidate-audit dependencies.

Parallel locator and missing-access workers are also auxiliary lanes, not numbered stages. Coordinator integration fulfills the existing stage 12 (`locator_audit`) or stage 13 (`missing_access_audit`). A partial accepted batch keeps that stage `in_progress`; only exact coverage of every required frozen chunk and denominator completes it. The canonical sequential commands remain valid and `next` continues to name them, while `help`, `status`, and `next` may report dependency-satisfied parallel alternatives separately.

Each completion artifact is registered in `artifact-manifest.json` using a relative path, SHA-256, visibility, retention class, and frozen status. Save the manifest before marking the stage complete in `evaluation-state.json`. Chat text is never a completion artifact.

`checkpoint`, `export-bundle`, and `import-bundle` are persistence commands rather than evaluation stages. They do not change editorial judgments or dependency order. Read [storage-and-checkpoints.md](storage-and-checkpoints.md).

## Why the two directional audits are necessary

Index-to-source review asks, “Does this proposed heading and locator belong?” It measures precision and selectivity. It cannot discover an absent subject because the missing item never appears in the index.

Benchmark-to-index review asks, “Can a reader retrieve every independently searchable, substantively treated source subject frozen in the benchmark?” It measures meaningful coverage, locator recall, and missing access. The candidate-blind, source-grounded frozen benchmark—not the candidate and not a fresh worker reading of the source—defines that denominator. Routine missing-access workers therefore use the benchmark plus the complete canonical locator-audit set; source re-entry is reserved for explicit centralized adjudication exceptions.

The global pass asks, “Does the set of individually defensible records form a coherent navigation system?” It detects hierarchy and distribution problems that cannot be decided page by page.

The diagnostic item layer asks, “What should a customer see when inspecting this particular locator, complete path, heading node, reference, or omitted source subject?” It deterministically derives grades and popover factors from the three completed audit directions. It does not create new editorial judgments and does not replace the publication-level rubric.

## Standard policy and minimal elicitation

Infer readership during initialization and instantiate [standard-policy.md](standard-policy.md) at `define-policy`. Do not pause to ask the user to select routine content, entity, example, locator, heading, cross-reference, uncertainty, gate, or density rules. Pause only for a material ambiguity, a publisher specification, or an explicit requested deviation. Record the evidence and provenance of every inference or override.

Use source discovery to establish what deserves access; use locator audit to test proposed path/page legitimacy; use missing-access audit to test source-to-index coverage; and use structure audit to test the index as a whole. Density is measured only in the structure audit. Source discovery records indexable word counts for its denominator but never targets a subject count.

## Chapter chunking

Use the source's intellectual units first:

1. Identify proposed chapter boundaries in one-based document-page ordinals, not source page labels or chunk-PDF ordinals.
2. Ask the user to supply or approve every final inclusive document-page range. ChatGPT may propose boundaries but must not freeze inferred ranges without approval.
3. Make one chapter one chunk when practical.
4. If a chapter is too large for a reliable pass, split it into deterministic sections of roughly 40–60 document pages, preferably at source section boundaries.
5. Permit 1–2 context pages on either side. Declare `owned_document_page_ranges` and `context_document_page_ranges`; only owned pages create judgments.
6. Assign each in-scope document page to exactly one owner. Hash the expanded page map and chunk manifest before auditing.
7. Split the source PDF from the approved manifest and preserve a sidecar map from each chunk-PDF page to the original document page and source label.
8. Keep a complete heading path together, but route only its expanded locator assignments whose mapped document pages belong to the current chunk. Do not send the rest of the index in a locator-audit chunk.

Chapter chunking reduces context load and aligns judgments with the author's structure. It is not sufficient by itself because themes cross chapters. `synthesize-source-benchmark` performs the whole-book reconciliation, `review-source-benchmark` independently checks it, and `audit-index-structure` inspects the whole index.

## Parallel source-discovery workers

Parallelism changes ownership, not editorial policy. Every worker starts from the same compatible checkpoint and immutable benchmark commit, reconnects the same source hash, and owns exactly one chunk artifact. Worker branches must be append-only with respect to the canonical study: each branch adds one unique `source/source-subject-chunk.<chunk-id>.json` and does not edit `evaluation-state.json`, `artifact-manifest.json`, checkpoints, or benchmark locks.

Use one branch and Library recovery folder per chunk. Default branch names to `source-discovery/<lowercase-chunk-id>` and refuse collisions. A worker pull request remains open for coordinator review and must not merge itself. The worker receipt records the immutable base, source identity, canonical hashes, validation counts, allowed publication path, and forbidden content; it is a handoff record, not a canonical study artifact.

The coordinator owns all fan-in operations. It receives an explicit PR/branch allowlist, verifies the complete diff and every artifact before merging any member of the selected batch, then merges only validated artifact-only PRs. After the branch artifacts exist on the base branch, integrate them together, update the canonical manifest and state once, validate, checkpoint, and commit the shared control files. Advance candidate benchmark locks only after that commit.

This two-phase pattern prevents lost updates:

1. **Fan-out:** immutable common base → independent chunk artifacts and PRs.
2. **Fan-in:** validate all selected PRs → merge artifact files → one canonical state/manifest/checkpoint update.

If a selected batch contains any invalid, incompatible, unexpected, or restricted change, merge none of that batch. A later coordinator run may integrate a corrected subset explicitly.

## Parallel candidate-preparation workers

Parallel candidate preparation uses the same fan-out/fan-in ownership pattern with a different privacy boundary. One isolated worker owns one candidate, its private recovery artifacts, and one public-safe pull request. It receives only frozen source-level identities and never receives benchmark subjects. Benchmark discovery, synthesis, and review workers never receive candidate artifacts.

The preparation worker may extract layout, normalize delivered content, expand locators through the page map, create item identities, and prove complete normalization accounting. These are fidelity operations. It cannot make candidate-quality judgments or update shared state. Its branch contains only the three strict public projections; complete normalized content remains private.

The coordinator owns the fan-in. It validates one explicitly named PR/branch and one explicitly named private receipt/recovery root, resolves the explicit final benchmark commit, and obtains current-attempt premerge-publication and benchmark Git evidence directly from connector/API output. After merging only the public-safe proposal, it obtains separate merged-PR API evidence, creates a compatible benchmark lock binding all evidence hashes and the public blobs, and registers the exact private bytes. User-authored assertions never substitute for API evidence. The manifest is updated before state, and state is updated once. Read [candidate-preparation.md](candidate-preparation.md).

## Parallel candidate-audit workers

Use this schedule; do not overlap locator and missing-access workers across the stage boundary:

```text
candidate preparation worker
        ↓
integrate candidate preparation
        ↓
prepare locator chunks
        ↓
locator-audit workers in parallel
        ↓
integrate explicit locator-audit PR batches
        ↓
missing-access workers in parallel
        ↓
integrate explicit missing-access PR batches
        ↓
single global structure audit
        ↓
item assessments and scoring
        ↓
web report
```

Every locator worker owns exactly one frozen locator packet. Every missing-access worker owns the exact benchmark subjects and reader tasks assigned to one chunk by the deterministic ownership rule. Workers retain receipts and recovery checkpoints privately. Each public branch contains one artifact selected by the frozen publication profile: an aggregate safety-checked report in `aggregate_only`, or the exact strictly validated canonical audit in `public_evaluation_artifacts`. Neither mode publishes source documents, recovery data, or shared controls. Workers never update canonical state, manifests, benchmark locks, cumulative checkpoints, integration records, or later-stage artifacts. Read [publication-profiles.md](publication-profiles.md).

The coordinator receives an explicit proposal list plus a one-to-one private receipt/recovery binding for each member. It obtains current-attempt GitHub evidence directly from connector/API output, validates the whole selected batch in a disposable area, and merges none if any member fails. After merging the selected public-safe artifacts, it obtains post-merge evidence, materializes exact audit bytes with profile-appropriate visibility, records provenance, saves the manifest before state, validates, checkpoints, and makes one shared-control commit. Partial batches are supported without permitting missing-access work before full canonical locator completion.

The global structure audit remains coordinated and single because its judgment unit is the index as a whole. Read [parallel-candidate-audits.md](parallel-candidate-audits.md) for ownership, privacy, recovery, integration, and evidence contracts.

## Benchmark QA gate

The benchmark is not frozen when synthesis ends. Synthesis creates a draft; a fresh, candidate-blind reviewer then checks the draft against the exact source and complete deterministic review inventory. Full review requires exact ID coverage for every subject, relationship, reader task, cross-chapter subject, unresolved relationship, and fallback reader task, plus an independent omission pass. Only an approving full review can authorize the final freeze. Read [benchmark-review.md](benchmark-review.md).

The workflow retains state schema v4 for storage compatibility and adds `configuration.scoring_identity` for `subject-index-rubric-v5` plus `subject-index-dimension-calculation-v1`. `configuration.rubric_version` remains the legacy preparation/judgment compatibility field and is not used as the V5 score identity. An isolated preparation receipt does not alter canonical state and can be integrated only into the same compatible evaluation after final benchmark freeze.

## Resume behavior

`status` trusts neither filenames nor conversational memory alone. It checks the state file, hashes, manifests, and completion counts. `next` returns the earliest valid unfinished stage. If a completed artifact's hash changes, mark that stage and all dependent stages `blocked` until revalidated or rerun.

For `locator_audit` and `missing_access_audit`, `next` retains the canonical sequential command. Parallel worker and coordinator operations are reported as auxiliary alternatives only when their exact dependency gates are satisfied. Missing-access worker availability requires the entire canonical locator-audit stage, not merely the matching chunk.

When resuming in another chat or environment, materialize the active Library folder or import the latest checkpoint, validate it, reconnect only the restricted inputs required by the next operation, then run `status` and `next`. Missing-access workers do not reconnect source PDFs or sidecars; source-grounded discovery, benchmark review, locator audit, and explicit source-adjudication exceptions do.

## Reruns and invalidation

- Changing the source file invalidates page mapping and every later stage.
- Changing page mapping invalidates chunks and every later stage.
- Changing owned chunk ranges invalidates source chunk files, discovery, and every later stage.
- Changing context-only ranges invalidates source chunk files and any judgments that used them.
- Changing scope, audit mode, or uncertainty policy invalidates policy and every later stage.
- Changing the standard judgment policy or an operative judgment rule invalidates policy and every later stage.
- Changing only `configuration.scoring_identity` after a sufficient deterministic preflight invalidates `scoring` and `web_report` only. The adoption command must independently reproduce preflight and resolve every manifest/audit/structure input to the same path, hash, stage, type, frozen flag, and required retention recorded in both canonical state and its artifact manifest; a foreign same-evaluation ledger set cannot authorize the change. It preserves discovery, benchmark synthesis/review/freeze, candidate preparation, locator audits, missing-access audits, and structure judgments. Preserve prior score/result/report artifacts as history rather than deleting or overwriting them, but mark their state and manifest registrations inactive for the new score identity. A calculation may mark scoring in progress only after authoritative reconstruction from the adopted inputs; only its projection-valid V6 result may complete scoring, and only a V4 web report validated against that active result may complete web reporting.
- Correcting only the recorded readership rationale without changing its label or any operative rule does not invalidate judgments; changing the readership label invalidates reader tasks, benchmark synthesis, and every candidate stage.
- Changing the synthesis draft invalidates benchmark review, final freeze, and every candidate stage. Changing review dispositions invalidates final freeze and every candidate stage. Changing final benchmark meaning, priority, evidence, or reader tasks creates a new version and invalidates every candidate stage.
- Changing source edition identity, page mapping, chunk identity, judgment policy, or audit mode invalidates any pending candidate-preparation receipt. A score-calculation-profile change alone does not. A preparation worker may survive benchmark-content revisions only when every receipt-bound source-level identity remains exact.
- Changing prepared candidate bytes, layout extraction, normalization, inventory, exception ledger, or QA invalidates the worker receipt, public projection, recovery bundle, and any pending integration. Never edit accepted normalization during integration.
- Changing candidate normalization or item inventory invalidates locator packets, locator audit, missing-access, structure, item assessments, score, and web report stages.
- Changing a locator packet invalidates its locator worker receipt, public report, recovery bundle, integrated audit, and every dependent missing-access artifact. Changing the accepted canonical locator-audit set invalidates all pending missing-access worker receipts, reports, and integrations.
- Changing missing-access ownership inputs, required subject/task denominators, or the canonical locator dependency invalidates the affected missing-access worker receipt, public report, recovery bundle, and integrated artifact.
- Adjudicating a judgment invalidates item assessments, scoring, and web reporting only unless it changes the benchmark.
- Changing presentation text without changing evaluation facts requires only rebuilding the web report.

Never overwrite a frozen artifact in place. Increment its version, compute a new hash, and retain provenance.

For score-only V4-to-V5 migration, first run the no-mutation sufficiency preflight against exact ledger hashes. If a historical structure audit lacks V5 scoring context, stop and report the required hash-bound supplement fields. After sufficiency, set the score profile, write a distinct calculation and migration record, then rebuild the active evaluation result and web report. Do not reopen benchmark or audit stages, reinterpret evidence, replace historical V4 artifacts, or change gate states when gate rules and evidence are unchanged.

## Checkpoints

Create portable checkpoints after policy freeze, final benchmark freeze, each candidate score, the final web report, and before a conversation/environment handoff. Portable bundles exclude restricted source/candidate files. A private-complete export may include them only at the user's request. Bundle creation does not publish anything.

## Comparison

The evaluation itself remains candidate-independent. A separate web layer may place completed results side by side only when the complete `comparison_key` matches: source SHA-256, benchmark SHA-256, judgment-policy SHA-256, page-map SHA-256, chunk-manifest SHA-256, inclusion policy, audit mode, uncertainty policy, rubric version, and dimension-calculation profile. If any field differs, including V4 versus V5 score identity, display `not_directly_comparable` and name the mismatches.
