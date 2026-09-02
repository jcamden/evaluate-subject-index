# Customer methodology — V7

The evaluation compares a finished subject index with its source using a benchmark prepared without seeing the candidate index. It reports six dimensions, evidence-backed findings, item-level explanations, and an overall result.

## Evaluation sequence

1. Map and chunk the source.
2. Freeze the evaluation policy and source benchmark.
3. Prepare the candidate index into normalized paths and atomic locator assignments.
4. Audit locator support, missing access, structure, cross-references, and density.
5. Calculate current V7 dimensions and render the report.

Parallel chats may process independent frozen chunks. Their output becomes canonical only after local validation and registration in `evaluation-state.json`.

## Reliability method

Each locator receives two structured assessments: how much relevant treatment is present on the referenced page and how well the complete index path fits that treatment. The lower of those two credits is used, preventing one good axis from hiding a failure on the other. Expected-treatment recall is then combined with weighted locator precision using an F1 calculation.

Free-text rationale explains structured decisions but never supplies a score. Uninspectable material is represented through explicit uncertainty rather than guessed.

## Structure method

A continuous page range counts as one displayed locator for scanning and subdivision review, while its pages remain separate atomic assignments for support auditing. More than six displayed locators or a range longer than ten pages triggers review, not an automatic penalty. A defect requires evidence that the structure materially harms retrieval and that a meaningful conceptual alternative exists.

## Reproducibility

The state file records the active configuration and artifact inventory. Hashes link related records and catch accidental mix-ups; they are not security attestations. Checkpoints are optional recovery snapshots and do not have to match an earlier archive checksum to resume.

This repository supports the current V7 workflow only.
