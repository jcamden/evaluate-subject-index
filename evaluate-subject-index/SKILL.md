---
name: evaluate-subject-index
description: Run a repeatable, source-grounded evaluation of a finished subject index using a built-in standard policy. Use when a user wants to map PDF document pages to Arabic, Roman, prefixed, or irregular source labels; define and prepare audit chunks; discover substantively treated subjects; freeze a candidate-blind source benchmark; normalize and route index locators; audit every locator; find missing access; judge hierarchy, density, and navigation; persist outputs to Library or portable bundles; resume an evaluation; or produce JSON for a web report.
---

# Evaluate Subject Index

Evaluate one finished subject index against its source and a frozen policy. Treat comparison as a later display operation over independently completed, compatible evaluations.

## Command interface

Interpret the first token after the skill name as a command. In ChatGPT use phrases such as `@evaluate-subject-index help`; in Codex prompts, `$evaluate-subject-index status` also works.

Supported commands:

- `help [command]`
- `initialize`
- `status`
- `next`
- `map-pages`
- `define-chunks`
- `define-policy`
- `prepare-source-chunks`
- `discover-source-subjects [chunk-id]`
- `freeze-source-benchmark`
- `normalize-index`
- `prepare-locator-chunks`
- `audit-locators [chunk-id]`
- `audit-missing-access [chunk-id]`
- `audit-index-structure`
- `score-index`
- `build-web-report`
- `checkpoint`
- `export-bundle`
- `import-bundle`
- `validate`

Read [commands.md](references/commands.md) for inputs, outputs, dependencies, and command-specific behavior. If no command is supplied, run `status` when a state file is present; otherwise run `help`.

## Non-negotiable method

1. Discover source subjects before inspecting a candidate index. If the candidate was visible in the same context, label candidate blindness `compromised` and recommend rerunning discovery in a fresh context for public claims.
2. Distinguish one-based document-page ordinals from source page labels. Store every source label as a string, including Arabic, Roman, prefixed, alphabetic, and exceptional labels. Expand the user-supplied mapping to one record per document page before chunking or locator filtering.
3. Require the user to approve document-page ranges for every chunk. Use chapters as the primary intellectual units, but never infer final boundaries silently. Use context overlap without assigning the same document page to two judgment owners.
4. Apply and freeze the built-in standard policy before candidate scoring. Infer readership from the source unless genuinely ambiguous; record the inference and ask only about material deviations. Freeze source-specific scope facts, the source-subject graph, locator classes, and reader tasks. Hash the canonical policy and benchmark JSON.
5. Audit the complete heading path at every expanded locator. This establishes locator precision, not coverage.
6. For each locator-audit chunk, include only paths having locator assignments mapped to document pages owned by that chunk. Preserve the complete path and in-chunk assignments; report but do not include other assignments.
7. Separately compare the frozen source-subject graph with the candidate. This establishes missing access and locator recall.
8. Judge hierarchy, terminology, cross-references, distribution, density, and mechanics globally after locator legitimacy is known.
9. Derive scores from item-level ledgers. Do not award ratings from overall impressions, index length alone, or resemblance to another index.
10. Preserve the original candidate. Normalization may make structure machine-readable but must not silently correct it.
11. Keep each candidate in an independent evaluation. Compare scores only if source hash, benchmark hash, rubric version, page-label map, chunk manifest, inclusion policy, audit mode, and uncertainty policy match.

Read [workflow.md](references/workflow.md) for the full state machine and [judgment-policy.md](references/judgment-policy.md) before making substantive judgments. Read [rubric.md](references/rubric.md) before scoring.

## Built-in policy

Use [standard-policy.md](references/standard-policy.md) for every evaluation. Do not ask the user to invent named-entity, example, locator, hierarchy, cross-reference, uncertainty, gate, or density policies. At `define-policy`, instantiate the versioned standard policy with the frozen source hashes and source-specific scope/availability facts. Ask only when the source is ambiguous, the user requests a documented deviation, or a publisher specification conflicts with the default.

Infer intended readership from the title, publisher, paratext, genre, terminology, and presentation. Record `label`, `basis: inferred`, `confidence`, and a short rationale. If evidence supports more than one audience, record a combined label. Ask the user only when confidence is low or they say the index targets a different readership; then record `basis: user_supplied`. Readership informs reader tasks and terminology expectations but never relaxes locator truth or source fidelity.

Keep the frozen benchmark exhaustive and source-led. Never prune or pad benchmark subjects to meet index-density calibration points; density evaluates only the finished candidate.

## Output contract

Default to JSON artifacts and concise JSON responses because results are intended for web presentation. Every response must include:

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

Use the schemas in `references/schemas/`. Put display-ready facts in structured fields, retain complete evidence ledgers, and identify `not_measured`, `uninspectable`, and `uncertain` explicitly rather than treating them as failures or zeros.

Use `scripts/state_cli.py` for deterministic state initialization, status, dependency-aware next-step selection, state transitions, artifact registration, hashing, manifest updates, and validation. Use `scripts/policy_cli.py` to instantiate and hash the built-in policy. Use `scripts/bundle_cli.py` for portable/private checkpoints, exports, artifact inventories, and safe imports. Use `scripts/page_chunk_cli.py` to expand page-label maps, validate user-approved chunk ranges, split source PDFs, and create locator-only chunk packets. Use `scripts/score_cli.py` for chapter-level density and score arithmetic. Do not ask the language model to maintain arithmetic or workflow state when a script can do it.

## Persistence rule

Never leave a required artifact only in chat text or an ephemeral workspace. Keep the canonical representation in a user-selected evaluation directory with relative paths, `evaluation-state.json`, and `artifact-manifest.json`. Validate and hash each artifact, persist it, update the manifest, and update state last. In ChatGPT, prefer `hybrid` storage when Library is available: save the active study folder to Library and produce downloadable checkpoints. Otherwise use `local` and provide a checkpoint before a conversation boundary. Read [storage-and-checkpoints.md](references/storage-and-checkpoints.md) before initializing, checkpointing, exporting, importing, or resuming a study.

Keep restricted source/candidate files and long evidence separate from public output. Portable bundles contain control files plus public/private JSON evidence but exclude restricted files by default. Private-complete bundles may include restricted inputs only when the user requests and is authorized to retain them.

## Full audit and pilot modes

Default to `full`. In full mode, inspect every in-scope source page, every delivered record, every expanded locator assignment, every essential and major benchmark subject, every cross-reference, and every structural flag.

Use `pilot` only when requested or needed to calibrate policy. Report sample design and denominators; never turn pilot results into full-index claims. A pilot and a full audit are not directly comparable.

## Density rule

Use two built-in chapter-level calibration targets based on indexable source words: 8 locator-bearing complete heading paths and 20 expanded locator occurrences per 1,000 words. Treat them as calibration points, never quotas, minimums, or hard ceilings. Use target bands of 6–10 paths and 15–25 occurrences, broad tolerance bands of 4–12 paths and 10–30 occurrences, and source-word-weighted chapter aggregation. Preserve chapter outliers as diagnostics rather than forcing uniformity. Score density once within Editorial Selectivity; score actual omissions, clutter, and navigation failures from their own evidence, not from size again. Publish the targets, bands, observed chapter distribution, and their limited five-point contribution. See [rubric.md](references/rubric.md).

## Resource routing

- Command behavior and help: [commands.md](references/commands.md)
- State sequence, chunking, ownership, and rerun rules: [workflow.md](references/workflow.md)
- Page-label mapping and chunk input formats: [page-mapping-and-chunks.md](references/page-mapping-and-chunks.md)
- Subject, locator, omission, hierarchy, and uncertainty judgments: [judgment-policy.md](references/judgment-policy.md)
- Built-in scope, content, architecture, locator, cross-reference, density, and shipping-gate rules: [standard-policy.md](references/standard-policy.md)
- Weights, metrics, density penalty, gates, grades, and public claims: [rubric.md](references/rubric.md)
- Machine-readable artifact map: [json-contracts.md](references/json-contracts.md)
- Storage modes, study layout, checkpoints, imports, and public/private separation: [storage-and-checkpoints.md](references/storage-and-checkpoints.md)
