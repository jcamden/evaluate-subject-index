# Workflow and state machine

## Stage order

| Stage | Command | Completion artifact |
| --- | --- | --- |
| 1 | `initialize` | `evaluation-state.json` |
| 2 | `map-pages` | `page-map.json` |
| 3 | `define-chunks` | `chunk-manifest.json` |
| 4 | `define-policy` | `evaluation-policy.json` |
| 5 | `prepare-source-chunks` | chunk PDFs and sidecar maps |
| 6 | `discover-source-subjects` | all `source-subject-chunk.*.json` files |
| 7 | `freeze-source-benchmark` | `source-benchmark.json` |
| 8 | `normalize-index` | `candidate-index.json` |
| 9 | `prepare-locator-chunks` | all `candidate-locator-chunk.*.json` files and exception ledger |
| 10 | `audit-locators` | all `locator-audit.*.json` files |
| 11 | `audit-missing-access` | all `missing-access-audit.*.json` files |
| 12 | `audit-index-structure` | `structure-audit.json` |
| 13 | `score-index` | `evaluation-result.json` |
| 14 | `build-web-report` | `web-report.json` |

Each stage status is `not_started`, `in_progress`, `completed`, or `blocked`. A stage may start only when every earlier required stage is complete. `validate` may run at any time.

Each completion artifact is registered in `artifact-manifest.json` using a relative path, SHA-256, visibility, retention class, and frozen status. Save the manifest before marking the stage complete in `evaluation-state.json`. Chat text is never a completion artifact.

`checkpoint`, `export-bundle`, and `import-bundle` are persistence commands rather than evaluation stages. They do not change editorial judgments or dependency order. Read [storage-and-checkpoints.md](storage-and-checkpoints.md).

## Why the two directional audits are necessary

Index-to-source review asks, “Does this proposed heading and locator belong?” It measures precision and selectivity. It cannot discover an absent subject because the missing item never appears in the index.

Source-to-index review asks, “Can a reader retrieve every independently searchable, substantively treated source subject?” It measures meaningful coverage, locator recall, and missing access. The frozen source benchmark—not the candidate—defines that denominator.

The global pass asks, “Does the set of individually defensible records form a coherent navigation system?” It detects hierarchy and distribution problems that cannot be decided page by page.

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

Chapter chunking reduces context load and aligns judgments with the author's structure. It is not sufficient by itself because themes cross chapters. `freeze-source-benchmark` must perform a whole-book synthesis pass, and `audit-index-structure` must inspect the whole index.

## Resume behavior

`status` trusts neither filenames nor conversational memory alone. It checks the state file, hashes, manifests, and completion counts. `next` returns the earliest valid unfinished stage. If a completed artifact's hash changes, mark that stage and all dependent stages `blocked` until revalidated or rerun.

When resuming in another chat or environment, materialize the active Library folder or import the latest checkpoint, validate it, reconnect excluded restricted inputs by SHA-256, then run `status` and `next`.

## Reruns and invalidation

- Changing the source file invalidates page mapping and every later stage.
- Changing page mapping invalidates chunks and every later stage.
- Changing owned chunk ranges invalidates source chunk files, discovery, and every later stage.
- Changing context-only ranges invalidates source chunk files and any judgments that used them.
- Changing scope, audit mode, or uncertainty policy invalidates policy and every later stage.
- Changing benchmark meaning, priority, evidence, or reader tasks invalidates the benchmark and every candidate stage.
- Changing candidate normalization invalidates locator packets, locator audit, missing-access, structure, score, and web report stages.
- Adjudicating a judgment invalidates scoring and web reporting only unless it changes the benchmark.
- Changing presentation text without changing evaluation facts requires only rebuilding the web report.

Never overwrite a frozen artifact in place. Increment its version, compute a new hash, and retain provenance.

## Checkpoints

Create portable checkpoints after policy freeze, benchmark freeze, each candidate score, the final web report, and before a conversation/environment handoff. Portable bundles exclude restricted source/candidate files. A private-complete export may include them only at the user's request. Bundle creation does not publish anything.

## Comparison

The evaluation itself remains candidate-independent. A separate web layer may place completed results side by side only when their `comparison_key` fields match. If they do not match, the page must display `not_directly_comparable` and the mismatched fields.
