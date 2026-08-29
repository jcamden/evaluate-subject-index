---
name: evaluate-subject-index
description: Run a repeatable, source-grounded evaluation of a finished subject index using a built-in standard policy. Use when a user wants to map PDF document pages to Arabic, Roman, prefixed, or irregular source labels; define and prepare audit chunks; discover substantively treated subjects serially or through parallel branch-and-pull-request workers; integrate distributed discoveries; synthesize, independently review, and freeze a candidate-blind source benchmark; prepare candidate intake, provenance, layout normalization, and full QA in an isolated parallel worker; normalize and route index locators; audit locators and missing access serially or through collision-safe chapter workers and coordinator integration; judge hierarchy, density, and navigation; persist outputs to Library or portable bundles; resume an evaluation; or produce JSON for a web report.
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
- `worker-discovery [chunk-id] --project [repository]`
- `integrate-discoveries --project [repository] [pull-request-or-branch ...]`
- `synthesize-source-benchmark`
- `review-source-benchmark`
- `freeze-source-benchmark`
- `worker-candidate-preparation [candidate-id] --project [repository] --benchmark-project [repository]`
- `integrate-candidate-preparation --project [repository] --benchmark-project [repository] --benchmark-ref [commit] [pull-request-or-branch]`
- `normalize-index`
- `prepare-locator-chunks`
- `prepare-locator-worker-prompts --project [repository]`
- `audit-locators [chunk-id]`
- `worker-locator-audit [chunk-id] --project [repository]`
- `integrate-locator-audits --project [repository] [pull-request-or-branch ...]`
- `audit-missing-access [chunk-id]`
- `worker-missing-access-audit [chunk-id] --project [repository]`
- `integrate-missing-access-audits --project [repository] [pull-request-or-branch ...]`
- `audit-index-structure`
- `preflight-v6-scoring`
- `score-index`
- `migrate-score-only`
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
4. Apply and freeze the built-in standard policy before discovery. After discovery, synthesize an unfrozen whole-source benchmark draft, review every required benchmark item independently in a fresh candidate-blind context, and only then freeze the source-subject graph, locator classes, and reader tasks. Hash the canonical policy and final benchmark JSON.
5. Audit the complete heading path at every expanded locator. This establishes locator precision, not coverage.
6. For each locator-audit chunk, include only paths having locator assignments mapped to document pages owned by that chunk. Preserve the complete path and in-chunk assignments; report but do not include other assignments.
7. Separately compare the frozen source-subject graph with the candidate. This establishes missing access and locator recall.
8. Judge hierarchy, terminology, cross-references, distribution, density, and mechanics globally after locator legitimacy is known.
9. Derive all six V6 ratings from validated raw ledger statuses with `subject-index-dimension-calculation-v2`. Retain strict substantive precision beside the scored weighted precision. Never submit diagnostic item grades, gates, or manually selected headline ratings as calculation inputs.
10. Preserve the original candidate. Normalization may make structure machine-readable but must not silently correct it.
11. Keep each candidate in an independent evaluation. Compare scores only if the source, benchmark, judgment-policy, page-map, chunk-manifest, inclusion-policy, audit-mode, uncertainty-policy, rubric, and dimension-calculation identities match.

Read [workflow.md](references/workflow.md) for the full state machine and [judgment-policy.md](references/judgment-policy.md) before making substantive judgments. Read [rubric.md](references/rubric.md) before scoring.

For customer-facing explanations and reports, read [customer-methodology.md](references/customer-methodology.md). Use its four-layer presentation hierarchy: overall result, six quality questions, supporting evidence, then full methodology. Keep technical detail available through progressive disclosure instead of placing it in the primary conclusion.

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

Use `scripts/state_cli.py` for deterministic state initialization, status, dependency-aware next-step selection, state transitions, artifact registration, hashing, manifest updates, and validation. Use `scripts/policy_cli.py` to instantiate and hash the score-independent judgment policy. Use `scripts/bundle_cli.py` for portable/private checkpoints, exports, artifact inventories, and safe imports. Use `scripts/page_chunk_cli.py` to expand page-label maps, validate user-approved chunk ranges, split source PDFs, and create locator-only chunk packets. Use `scripts/benchmark_review_cli.py` to enumerate benchmark-review denominators and enforce full-review and final-freeze gates. Use `scripts/item_grade_cli.py --grading-policy subject-index-item-grading-v2` to create V6 diagnostic grades. Use `scripts/dimension_score_v6_cli.py` for current V6 sufficiency preflight, deterministic calculation, V5-to-V6 score-only migration, and result/web projection validation. Current V5-to-V6 records bind sibling version directories through one bounded ancestor-only artifact root and descendant-only paths; do not work around path validation by duplicating, moving, or hand-editing frozen artifacts. Keep `scripts/dimension_score_cli.py` available for immutable V5 results and historical V4-to-V5 migration. `scripts/score_cli.py scorecard` is historical V4 validation only; its density helper remains available for V4 artifacts. Do not ask the language model to maintain arithmetic, item-grade aggregation, or workflow state when a script can do it.

Use `scripts/parallel_discovery_cli.py` for distributed discovery. `worker-receipt` validates one candidate-blind chapter artifact against canonical source, policy, page-map, and chunk hashes without mutating shared state. `integrate` validates all supplied worker artifacts before copying or registering any of them, then updates the canonical manifest and state once.

Use `scripts/candidate_preparation_cli.py` for isolated candidate preparation. Candidate preparation is mechanical fidelity work, not candidate evaluation: it may extract layout, normalize delivered records, expand locators through the frozen page map, construct the item inventory, and account for every normalized item without consulting benchmark subjects or making quality judgments. Use `scripts/candidate_layout_adapters.py` for the common geometry contract and adapter registry. Read [candidate-preparation.md](references/candidate-preparation.md) before either candidate-preparation command.

Use `scripts/parallel_candidate_audit_cli.py` for parallel locator and missing-access audit workers and coordinator integration. It deterministically binds validated worker artifacts to the public artifact selected by the frozen publication profile, validates identities and denominators, preflights explicit batches, integrates accepted bytes, and computes stage completion. It does not replace the canonical locator-audit or missing-access judgment schemas. Read [publication-profiles.md](references/publication-profiles.md) before selecting or changing public artifact behavior.

When a `public_evaluation_artifacts` missing-access proposal contains the exact canonical audit but the coordinator cannot materialize the worker receipt or recovery ZIP because of a storage-transfer failure, use the guarded `reconstruct-public-handoff` operation. Recompute the complete audit, frozen identities, ownership, exact denominators, public safety, and fresh GitHub proposal binding; then create a new private coordinator-labeled receipt and recovery bundle. Never describe this as validation of the unavailable worker bytes, never use it for `aggregate_only` or locator audits, and never skip transactional batch preflight.

Missing-access review is benchmark-first. Its routine worker evidence is the frozen source benchmark, complete normalized candidate and inventory, and complete canonical locator-audit set. The source SHA-256 remains a frozen lineage identity, but missing-access workers do not reconnect or inspect the source PDF, chunk PDF, or sidecar. Preserve multiple benchmark evidence records that describe the same subject, document page, and locator class as one treatment unit with all evidence IDs attached. Route genuine benchmark ambiguity to explicit exception adjudication; never let a worker silently reinterpret the benchmark or canonical locator judgments.

Before rendering locator-worker prompts, require `worker_prompt_cli.py` to inspect and hash-verify the referenced checkpoint and confirm that its explicit `configuration.publication_profile` equals the prompt pack. Prompt prose never overrides missing checkpoint state. For an authorized legacy pre-audit checkpoint, use the guarded `bundle_cli.py migrate-publication-profile` operation, validate the migrated bundle, and update the prompt pack to its new checkpoint hash.

If authenticated ChatGPT Library checkpoint transfer returns HTTP 502, stop retrying that transfer and return a resumable `checkpoint_transfer_http_502` blocker. Ask the user to attach the exact checkpoint to the same worker conversation, naming its canonical filename and expected SHA-256 plus byte length when known. On resume, treat the attachment only as an alternate byte-delivery route: verify its exact hash before opening it, validate its complete member inventory and canonical evaluation, import it into the same isolated worker scope, and continue the original command. A filename or attachment alone is never authority, a hash mismatch is a hard failure, and this recovery does not apply to authorization, not-found, schema, or integrity errors. Read [storage-and-checkpoints.md](references/storage-and-checkpoints.md) for the required blocker and resume contract.

## Parallel source discovery

Use `worker-discovery` when independent chats should discover different chunks concurrently. Require a chunk ID and GitHub project/repository. Resolve an immutable base commit, derive the default branch `source-discovery/<lowercase-chunk-id>`, and stop if that branch already exists. Import the same validated checkpoint in an isolated worker directory, reconnect the exact source by SHA-256, perform normal candidate-blind discovery, and generate a worker receipt. Keep branch-local recovery control files and checkpoints under a chunk-specific Library worker folder.

Publish only `source/source-subject-chunk.<chunk-id>.json` on the worker branch. Create one commit and one pull request into the configured base branch; never merge it, update canonical control files, publish a worker checkpoint, or update a candidate evaluation repository. Before a public write, inspect the exact JSON for unexpected verbatim source text or secrets and keep the allowed public path explicit. Treat the command invocation naming the repository as authorization for this bounded branch and pull-request workflow; stop for any materially broader publication. After one explicit Auto-review denial, preserve the Library recovery copy and report the rationale without retrying the same action.

Use `integrate-discoveries` only in a coordinating chat. Require the project plus explicit pull-request numbers, URLs, or branch refs; never sweep or merge unspecified pull requests. First verify every selected change is open, targets the expected base, changes exactly one allowed chapter artifact, and contains no restricted or shared control files. Fetch all artifacts and validate them together with `parallel_discovery_cli.py`; if any fails, merge none. After the full set passes, merge the selected pull requests, materialize the resulting base head, run the integration helper once, validate canonical state and manifest, create one cumulative portable checkpoint, and commit the shared control-file update. Update any candidate evaluation benchmark lock only after that canonical integration commit. Record merged PRs, commits, chunk IDs, artifact hashes, and the new benchmark head.

## Benchmark synthesis, review, and freeze

Do not collapse synthesis and QA into one stage. `synthesize-source-benchmark` produces an unfrozen whole-source draft from all validated chunk artifacts. `review-source-benchmark` runs in a fresh context with the candidate unseen and reconnects the exact source by SHA-256. In full mode it reviews every subject, relationship, and reader task by ID, revisits every cross-chapter subject, dispositions every unresolved relationship, inspects every fallback reader task, and performs an independent source-first omission pass. `freeze-source-benchmark` is the final gate over the draft, review inventory, review ledger, and final benchmark.

Run `scripts/benchmark_review_cli.py screen` before editorial review, then `validate-review` and `validate-final`. Treat duplicate, near-duplicate, priority-distribution, and unresolved-relationship flags as diagnostic prompts, never quotas or automatic decisions. Pilot review may be sampled but cannot authorize a freeze or public completeness claims. Read [benchmark-review.md](references/benchmark-review.md) before any of these commands.

Create item grades as a separate diagnostic layer under [item-grading.md](references/item-grading.md). Grade every measured locator, complete path, heading node, cross-reference, and frozen source subject; emit neutral `not_measured` records for unaudited pilot items. Include a public-safe popover payload with factors, weights or caps, confidence, explanations, and evidence IDs for every assessment. Never sum item grades into the overall 100-point result.

## Parallel candidate preparation

Candidate preparation may begin after the source SHA-256, edition identity, expanded page map, chunk manifest, policy profile/hash, legacy preparation-compatibility marker, and audit mode are frozen. That version-one marker remains `subject-index-rubric-v4` and is not the active V6 score identity. Preparation does not require a synthesized, reviewed, or frozen benchmark. Run it in an isolated worker context that does not expose candidate material to any source-discovery, synthesis, or benchmark-review context. Normalized candidate data is never benchmark evidence, and a publisher index is never ground truth.

This is a current-only preparation contract: use `candidate-index-v2`, `item-inventory-v2`, and v4 evaluation state. When the one existing preparation predates these contracts and no candidate judgment has begun, regenerate that preparation in place, rerun full QA, and replace its pending receipt and recovery bundle. Do not retain compatibility readers for superseded preparation artifacts. If candidate judgment has begun, refuse the rewrite and create a new evaluation identity.

`worker-candidate-preparation` prepares exactly one candidate, creates complete private normalization and QA artifacts plus a private recovery bundle, and opens one public-safe pull request. It must not perform locator-support, missing-access, structural-quality, density, scoring, or reporting work; modify canonical evaluation state; inspect benchmark subjects; or merge its pull request. Its default branch is `candidate-preparation/<normalized-candidate-id>`, and an existing branch is a hard stop. The public branch may contain only `candidate/candidate-ref.json`, `candidate/layout-profile.json`, and `validation/candidate-preparation-report.json`. An empty repository may receive one root bootstrap commit on `main` containing exactly `README.md` and `.gitignore`; bind GitHub-observed empty-state, parentless-commit, and exact two-blob-tree evidence in the receipt.

`integrate-candidate-preparation` is the sole coordinator authority. Require one explicit pull request or branch and an explicit final benchmark commit. Treat GitHub-API publication evidence acquired directly for the current integration attempt and final-benchmark Git proof as required observed preflight evidence; after merge, require a separate GitHub-API merged-pull-request observation. Create every API evidence JSON directly from connector output, never from user-authored assertions about branch state, commits, paths, or bytes. Both helper preflight and integration require `--publication-evidence` and `--benchmark-proof`. Evidence timestamps support provenance and chronology only; they never expire by elapsed wall-clock time. The historical publication evidence bound into the immutable receipt does not replace the distinct, strictly later premerge snapshot, and merged evidence cannot predate that snapshot. If an integration attempt is interrupted, reacquire current GitHub observations before resuming. Before merging anything, validate the unchanged public diff, matching private recovery artifacts, full QA denominators, candidate/source/page-map/chunk/policy/preparation-marker/audit/edition identities, and the final benchmark canonical hash. Then merge the public-safe proposal, pass the post-merge observation as `integrate --merge-evidence <file>`, copy the exact accepted private normalization bytes to versioned canonical paths, write `candidate-benchmark-lock.json`, register all artifacts in the manifest, update state last, validate, and checkpoint. This fulfills the existing `candidate_normalization` stage and leaves the next stage at locator-packet preparation. Do not add a parallel-preparation state stage or update the benchmark repository.

The JSON evidence helpers validate shape, chronology, exact object identities, hashes, and cross-artifact bindings; they cannot authenticate who created a local file. The trusted acquisition boundary is the orchestrator's direct GitHub connector/API call. Never accept an evidence file supplied by the user or worker, and never treat the `evidence_source` field itself as an attestation. Synthetic tests may construct fixtures only to exercise deterministic validation.

Preserve every delivered hierarchy level and every mixed or malformed record during preparation. A third-level heading is retained in candidate schema v2 and later fails the applicable quality gate; it is not flattened, repaired, or discarded. Keep extraction confidence separate from editorial judgment and keep authoritative-copy fidelity separate from internal PDF completeness.

## Parallel candidate audits

After locator packets are complete, locator-audit workers may run concurrently by chunk. Only `integrate-locator-audits` may accept their private artifacts and advance the existing `locator_audit` stage. Missing-access workers remain blocked until every locator audit is canonically integrated and the evaluation validates; only then may they run concurrently by chunk, with `integrate-missing-access-audits` advancing the existing `missing_access_audit` stage. These lanes add no numbered state stages, and the sequential commands remain valid alternatives.

Locator workers are source-grounded and reconnect their exact source chunk and sidecar. Missing-access workers are derivative comparison workers: they use the frozen benchmark graph as the source-grounded denominator and the complete canonical locator-audit set as the validated candidate-page dependency. Do not distribute source PDFs or sidecars to missing-access workers. If those frozen derivatives are insufficient for a defensible judgment, record the item as uncertain or uninspectable with the evidence needed for a separate source-adjudication exception.

Each worker preserves its complete audit, receipt, state, manifest, and recovery bundle before publishing exactly one public artifact on a unique branch. `aggregate_only` publishes the aggregate report; `public_evaluation_artifacts` publishes the exact validated canonical audit at its deterministic candidate path. After opening the pull request, the worker obtains a direct GitHub observation, runs `bind-publication`, reruns `validate-worker`, and replaces the preliminary Library receipt and recovery ZIP with the final publication-bound canonical files in that chunk's recovery folder. A coordinator accepts only explicitly named pull requests or branches, each bound one-to-one to an explicitly named private receipt and recovery root. For locator integration, it must retrieve and pass the complete frozen locator-packet set to both `preflight-batch` and `integrate-batch`, even when the selected proposal wave covers only some chunks; only proposal selections and worker bindings are wave-scoped. It obtains current-attempt GitHub evidence directly from connector/API output, validates the entire selected batch before merging any member, registers exact bytes with profile-appropriate visibility, updates the manifest before state, and completes a stage only at full frozen-manifest coverage.

For candidate-audit worker builds, supply one unique empty local `--recovery-root`. The helper derives the canonical receipt and recovery-ZIP filenames directly beneath that root and preflights containment, symlinks, collisions, and emptiness before loading frozen inputs or validating the audit. Do not select separate receipt or ZIP destinations and do not pass a remote Library destination as the local builder root. After `bind-publication` and `validate-worker` succeed locally, persist the two final canonical files to the chunk-specific Library recovery folder as a distinct durability step.

The missing-access coordinator may substitute a helper-generated reconstructed handoff only under the narrow public-artifact fallback above. The reconstructed private recovery must retain the complete public audit bytes, deterministic ownership plan, reconstructed state/manifest, current open-PR evidence, and a self-hashed reconstruction record. Preserve any worker-declared receipt and recovery hashes as unmaterialized provenance when available.

Read [parallel-candidate-audits.md](references/parallel-candidate-audits.md) before either worker or integration command.

## Persistence rule

Never leave a required artifact only in chat text or an ephemeral workspace. Keep the canonical representation in a user-selected evaluation directory with relative paths, `evaluation-state.json`, and `artifact-manifest.json`. Validate and hash each artifact, persist it, update the manifest, and update state last. In ChatGPT, prefer `hybrid` storage when Library is available: save the active study folder to Library and produce downloadable checkpoints. Otherwise use `local` and provide a checkpoint before a conversation boundary. Read [storage-and-checkpoints.md](references/storage-and-checkpoints.md) before initializing, checkpointing, exporting, importing, or resuming a study.

Keep restricted source/candidate files and long evidence separate from public output. Portable bundles contain control files plus public/private JSON evidence but exclude restricted files by default. Private-complete bundles may include restricted inputs only when the user requests and is authorized to retain them.

## Full audit and pilot modes

Default to `full`. In full mode, inspect every in-scope source page, delivered record, expanded locator assignment, required frozen subject, reader task, expected treatment, heading-node component, cross-reference, and structural flag. Any required `not_measured` item blocks V6 scoring; the 95% provisional rule never converts an incomplete full audit into a score.

Use `pilot` only when requested or needed to calibrate policy. Report sample design and denominators; never turn pilot results into full-index claims. A pilot and a full audit are not directly comparable.

## V6 scoring and migration

At the global structure audit, produce `structure-audit-v4` and freeze `audit_mode` plus `v5_scoring_context`: candidate-attempt status, genuine cross-reference applicability, optional-subject scoring decisions, a benchmark-grounded basis for every genuinely inapplicable node component, and structured cap-relevant defects. Each defect requires a dimension owner and compatible code, operational severity basis, retrieval consequence, affected item and audited section IDs, root-cause family, reconstructable counts and rates, and the high-priority-route flag. Free text alone never triggers a cap. A historical `structure-audit-v3` stays byte-identical and requires a separately reviewed supplement bound to its exact SHA-256, its recorded historical locator/missing-access set hashes, and canonical set hashes recomputed over those same frozen files.

At `score-index`, create `subject-index-item-assessments-v3` under `subject-index-item-grading-v2`. It must bind the exact item-inventory artifact and complete calculation evidence identity and exhaust the locator, path, node, cross-reference, and expected source-subject ID sets exactly once. Build `subject-index-dimension-calculation-input-v1` using the frozen audit mode plus exact paths and SHA-256 hashes for the canonical chunk manifest and every scoring ledger; run `dimension_score_v6_cli.py preflight`, then `calculate` to create `subject-index-dimension-calculations-v2`. Preflight must prove all V5 integrity/sufficiency rules plus an explicit consistent combined state for every locator; never infer treatment from rationale prose. Page-reference Reliability uses credits 1/0.5/0.25/0 and weighted F1, while strict substantive precision stays visible. Bind the calculation and exact V3 item path/hash in `subject-index-evaluation-result-v7` and `subject-index-web-report-v5`; run `validate-projections` before publication. Never submit item grades, gates, or manually selected ratings. Preserve all V5 caps and gates as separate claim restrictions.

For a V5 evaluation, run `dimension_score_v6_cli.py migration-preflight` with the immutable V5 calculation, result, and web report. Stop with a locator-specific missing-field report if the ledgers cannot distinguish judgment, treatment, scope, disqualifiers, and inspectability; do not reopen the source. After sufficient preflight, run `score-only-migration` with the exact methodology commit and UTC timestamp. Preserve frozen benchmark/preparation/audit bytes, V5 calculations/result/web provenance, representation correction provenance, strict precision, and gates. Invalidate only active calculation/result/item/web projections, then build separately versioned V6 projections bound to `subject-index-score-migration-v5-to-v6-v1`. Do not migrate the Oxford evaluation implicitly or tune credits to its outcome. Read [score-migration-v5-to-v6.md](references/score-migration-v5-to-v6.md). Historical V4-to-V5 migration remains documented in [score-migration-v4-to-v5.md](references/score-migration-v4-to-v5.md).

## Density rule

Use two built-in chapter-level calibration targets based on indexable source words: 8 locator-bearing complete heading paths and 20 expanded locator occurrences per 1,000 words. Treat them as calibration points, never quotas, minimums, or hard ceilings. Use target bands of 6–10 paths and 15–25 occurrences, broad tolerance bands of 4–12 paths and 10–30 occurrences, and source-word-weighted chapter aggregation. Preserve chapter outliers as diagnostics rather than forcing uniformity. Score density once within Editorial Selectivity; score actual omissions, clutter, and navigation failures from their own evidence, not from size again. Publish the targets, bands, observed chapter distribution, and their limited five-point contribution. See [rubric.md](references/rubric.md).

## Resource routing

- Command behavior and help: [commands.md](references/commands.md)
- State sequence, chunking, ownership, and rerun rules: [workflow.md](references/workflow.md)
- Page-label mapping and chunk input formats: [page-mapping-and-chunks.md](references/page-mapping-and-chunks.md)
- Subject, locator, omission, hierarchy, and uncertainty judgments: [judgment-policy.md](references/judgment-policy.md)
- Built-in scope, content, architecture, locator, cross-reference, density, and shipping-gate rules: [standard-policy.md](references/standard-policy.md)
- Deterministic dimension formulas, caps, uncertainty, rounding, weights, and score interpretation: [rubric.md](references/rubric.md)
- V5-to-V6 score-only migration: [score-migration-v5-to-v6.md](references/score-migration-v5-to-v6.md)
- Historical V4 preservation and score-only V5 migration: [score-migration-v4-to-v5.md](references/score-migration-v4-to-v5.md)
- Methodology version identities and compatibility: [version-history.md](references/version-history.md)
- V6 sensitivity and adversarial mixtures: [v6-sensitivity-analysis.md](references/v6-sensitivity-analysis.md)
- V6 web-report fields and display rules: [web-report-fields-v5.md](references/web-report-fields-v5.md)
- Customer-facing method, presentation layers, and expandable evaluation criteria: [customer-methodology.md](references/customer-methodology.md)
- Per-locator, path, heading, reference, omission grades and popover contract: [item-grading.md](references/item-grading.md)
- Independent benchmark synthesis, QA, and final-freeze gates: [benchmark-review.md](references/benchmark-review.md)
- Machine-readable artifact map: [json-contracts.md](references/json-contracts.md)
- Parallel candidate preparation, adapters, QA, publication safety, and benchmark locking: [candidate-preparation.md](references/candidate-preparation.md)
- Public artifact modes and exact canonical-audit publication contracts: [publication-profiles.md](references/publication-profiles.md)
- Parallel locator and missing-access workers, coordinator integration, privacy, and recovery: [parallel-candidate-audits.md](references/parallel-candidate-audits.md)
- Storage modes, study layout, checkpoints, imports, and public/private separation: [storage-and-checkpoints.md](references/storage-and-checkpoints.md)
