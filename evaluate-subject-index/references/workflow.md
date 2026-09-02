# Workflow and state machine

The current V7 evaluation uses one linear 16-stage state machine and one control file, `evaluation-state.json`.

| Stage | Typical completion artifact |
| --- | --- |
| initialize | state and source identity |
| page_mapping | expanded page map |
| chunk_definition | approved chunk manifest |
| define_policy | run-specific standard V7 policy |
| source_chunk_preparation | chunk PDFs and sidecars |
| source_subject_discovery | all source-subject chunks |
| benchmark_synthesis | benchmark draft |
| benchmark_review | independent review ledger |
| benchmark_freeze | frozen benchmark |
| candidate_normalization | normalized candidate and inventory |
| locator_chunk_preparation | all locator packets |
| locator_audit | all locator-audit V2 chunks |
| missing_access_audit | all missing-access chunks |
| structure_audit | global structure-audit V5 |
| scoring | V7 calculation, item assessments, result V9 |
| web_report | web report V7 |

Each stage is `not_started`, `in_progress`, `completed`, or `blocked`. A stage completes only after every prior stage is complete and at least one current artifact for that stage is registered. Audit stages require complete frozen-denominator coverage, not merely one artifact.

## Single source of truth

State contains the artifact inventory. Writers validate the selected operation, write artifacts, and atomically replace state while holding `.evaluation.lock`. There is no separate manifest and no two-control-file commit order.

Hashes inside policy, benchmark, and audit records provide stable identity joins and catch accidental input mix-ups. A local artifact checksum mismatch is a warning during resume, not proof of tampering and not an automatic stage blocker.

## Source-first sequence

Source discovery happens before candidate exposure. Synthesis creates a draft; independent candidate-blind review authorizes benchmark freeze. The two candidate audit directions remain separate:

- Index to source asks whether each proposed complete path and locator is supported.
- Benchmark to index asks whether every required subject and reader task has useful access.

The global structure pass then judges whether individually defensible records form a coherent navigation system.

## Chunk ownership

Use intellectual units such as chapters. The user approves every inclusive document-page range. Context pages may overlap, but every in-scope page has exactly one judgment owner. Keep complete heading paths intact and route only the locator assignments owned by the chunk.

Parallel chats may work on independent chunks. A coordinator validates the selected returned artifacts and registers them together. Branches and pull requests are optional collaboration mechanisms, not evaluation evidence.

## Candidate preparation

Candidate preparation is mechanical and may run separately, provided it does not expose benchmark content to extraction or normalization. It preserves the original hierarchy, records uncertainty, expands locators, builds the item inventory, and accounts for all delivered items. Local registration after benchmark freeze fulfills `candidate_normalization`.

## Checkpoints

Checkpoint, export, and import are persistence operations rather than stages. Create checkpoints when interruption risk justifies them. They do not advance state and do not require a previous checkpoint hash. Import performs archive-safety and current-state validation, then resume proceeds from the earliest unfinished stage.

## Invalidation

Invalidate from the earliest changed substantive input:

- Source changes invalidate page mapping and everything later.
- Page-map or owned-range changes invalidate affected chunks and everything later.
- Policy or benchmark meaning changes invalidate dependent judgment stages.
- Candidate normalization changes invalidate locator packets and later candidate stages.
- Locator-audit changes invalidate missing-access and later stages.
- Judgment changes invalidate structure, scoring, and reporting as applicable.
- Presentation-only changes require only rebuilding the web report.

Registering an updated judgment artifact makes it the current version in state. Recompute dependent outputs from the earliest affected stage.

## Current-only policy

Runtime commands accept the current V7 workflow. Historical migrations and backward-compatibility lanes are intentionally not part of this state machine. Broader schema consolidation remains deferred pending the possible TypeScript migration.
