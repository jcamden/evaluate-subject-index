---
name: evaluate-subject-index
description: Run a repeatable, source-grounded V7 evaluation of a finished subject index, including page mapping, source-first benchmark construction, candidate normalization, locator and missing-access audits, scoring, reporting, checkpoints, and resume.
---

# Evaluate Subject Index

Evaluate one finished subject index against its source and a frozen policy. Use only the current V7 workflow; this skill does not migrate or validate historical V4–V6 evaluations.

## Method

1. Map one-based document pages to source page labels. Store labels as strings and require the user to approve chunk boundaries.
2. Freeze the standard V7 policy, then discover source subjects before exposing the candidate index to the discovery context.
3. Synthesize, independently review, and freeze the candidate-blind benchmark.
4. Preserve the delivered candidate while mechanically normalizing its complete hierarchy and locator assignments from the published layout contract.
5. Audit locator support by complete heading path, then audit missing access against the frozen benchmark.
6. Judge global structure only after the locator and missing-access ledgers are complete.
7. Calculate the six V7 dimensions from validated ledgers. Do not ask a model to maintain arithmetic or workflow state.
8. Produce structured JSON and a web-report projection.

Use [standard-policy-v7.md](references/standard-policy-v7.md), [judgment-policy-v7.md](references/judgment-policy-v7.md), and [rubric-v7.md](references/rubric-v7.md) for substantive decisions. Default to a full audit. A pilot may calibrate the method but cannot support full-index claims.

## Current command surface

- `scripts/state_cli.py`: initialize, inspect, validate, and advance the single canonical state.
- `scripts/page_chunk_cli.py`: page mapping and chunk preparation.
- `scripts/policy_cli.py`: instantiate the standard policy.
- `scripts/parallel_discovery_cli.py`: validate and register source-discovery chunks.
- `scripts/benchmark_review_cli.py`: benchmark screening, independent review, and freeze validation.
- `scripts/candidate_preparation_cli.py`: validate the published candidate-layout contract, then normalize and locally register candidate preparation.
- `scripts/parallel_candidate_audit_cli.py`: validate or register locator and missing-access chunks created in separate chats.
- `scripts/dimension_score_v7_cli.py` and `scripts/item_grade_v7_cli.py`: current deterministic V7 calculation and projection.
- `scripts/bundle_cli.py`: optional checkpoints, exports, artifact listing, and resume imports.
- `scripts/worker_prompt_cli.py`: render locator-worker prompt packs from a structurally valid checkpoint.

## State and artifacts

`evaluation-state.json` is the single source of truth. It contains the stage statuses and artifact inventory. Do not create or maintain a second manifest.

Artifact SHA-256 values are stable content labels used to join related JSON records. They are not security attestations. State validation reports missing or changed local artifact bytes as warnings; it does not block resume merely because a previously recorded checksum differs.

Keep source and candidate files restricted. Keep public reports free of source text, secrets, absolute paths, and storage-provider identifiers.

## Checkpoints and resume

Create checkpoints at useful milestones and before a likely conversation or network boundary. Checkpointing is a durability feature, not a mandatory stage gate.

A checkpoint contains the canonical state plus accessible registered artifacts. Portable checkpoints omit restricted files. Import validates archive path safety, member inventory, and the current state shape, but does not require an old archive hash or member hashes to match. After import, reconnect unavailable restricted inputs explicitly and continue from `state_cli.py next`.

Read [storage-and-checkpoints.md](references/storage-and-checkpoints.md) before exporting or resuming.

## Parallel chats

Parallel work is divided by deterministic chunk ownership. Workers return complete current-schema JSON artifacts. The coordinator validates the selected files together and registers them in the single state.

Branches, pull requests, and chat attachments may be used for transport or review, but GitHub receipts, blob proofs, merge evidence, recovery receipts, and matching checkpoint hashes are not prerequisites for canonical registration. Registration completes an audit stage only when every frozen chunk denominator is covered exactly once.

Candidate preparation is mechanical and benchmark-blind. Candidate input must match [candidate-layout-extraction.schema.json](references/schemas/candidate-layout-extraction.schema.json); convert it before invoking the skill if necessary. Then run `normalize`, `validate-private`, and `register`. It does not require a publication workflow.

Read [candidate-preparation.md](references/candidate-preparation.md) and [parallel-candidate-audits.md](references/parallel-candidate-audits.md).

## Scoring

Native V7 uses `structure-audit-v5`, `locator-audit-v2`, `subject-index-dimension-calculations-v4`, `subject-index-item-assessments-v5`, result V9, and web report V7. Page treatment and complete-path fit are independent axes combined with `min(T,F)`. Diagnostic item grades are not a seventh dimension and do not replace the dimension calculation.

This repository intentionally exposes no legacy migration commands or compatibility workflow. Runtime commands and schemas cover the current workflow only.

## Output contract

Prefer JSON artifacts and concise JSON responses:

```json
{
  "command": "status",
  "ok": true,
  "evaluation_id": "example",
  "state": "source_subject_discovery",
  "artifacts_written": [],
  "next_actions": [],
  "warnings": []
}
```

Represent `not_measured`, `uninspectable`, and `uncertain` explicitly rather than converting them to failures or zeros. Compare independent evaluations only when their source, benchmark, page map, chunks, policy, audit mode, rubric, and calculation-profile identities match.

## References

- [workflow.md](references/workflow.md)
- [storage-and-checkpoints.md](references/storage-and-checkpoints.md)
- [candidate-preparation.md](references/candidate-preparation.md)
- [parallel-candidate-audits.md](references/parallel-candidate-audits.md)
- [benchmark-review.md](references/benchmark-review.md)
- [page-mapping-and-chunks.md](references/page-mapping-and-chunks.md)
- [structure-audit-v7.md](references/structure-audit-v7.md)
- [customer-methodology-v7.md](references/customer-methodology-v7.md)
- [json-contracts-v7.md](references/json-contracts-v7.md)
