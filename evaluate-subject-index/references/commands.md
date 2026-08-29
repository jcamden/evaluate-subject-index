# Command reference

Commands are a prompt vocabulary implemented by the skill, not assumed to be native application slash commands. Return JSON by default. A human-readable explanation may accompany JSON when requested.

## `help [command]`

Show purpose, syntax, required inputs, generated artifact, dependencies, completion test, and likely next command. With no argument, return every canonical stage command plus applicable worker and coordinator commands in workflow order, and identify whether each is available, blocked, or complete from the current state. Label parallel commands as auxiliary lanes rather than numbered stages.

## `initialize`

Required from the user: source file and, only when not clear from the file, source title/edition. Determine the document-page span from the file. Default to subject index, full audit, and `hybrid` storage when Library is available (`local` otherwise). Candidate input is optional and must not be opened yet.

Infer intended readership from the source. Do not ask unless confidence is low or the user identifies a different target. Record the label, `inferred` or `user_supplied` basis, confidence, and rationale. Create `evaluation-state.json` and `artifact-manifest.json`. Hash the source file, record edition identity if known, store no ephemeral absolute input path, and set every later workflow stage to `not_started`. Document pages are one-based ordinals in the supplied file; they are not assumed to equal page labels printed in the book.

## `status`

Read `evaluation-state.json`; validate it; return completed, active, blocked, and available stages, relevant artifact paths and hashes, and comparability warnings. When a candidate audit stage can be parallelized, also report the applicable worker and coordinator alternatives without changing canonical stage order. Do no substantive evaluation.

## `next`

Return exactly the earliest dependency-satisfied incomplete stage, its canonical sequential command, required inputs, completion test, and blockers. Report dependency-satisfied worker or coordinator alternatives separately; never replace the canonical stage command or skip a dependency because later files happen to exist.

## `map-pages`

Required: user-supplied relationships between document-page ranges and the page labels used by the source and index.

Accept compact JSON, CSV, or a Markdown table, but convert it to `page-map-input.json` before expansion. Require document ranges to use one-based inclusive integers. Store every source/index page label as a JSON string—even `"1"`—because labels may be Roman numerals, prefixed values, alphabetic values, or exceptional literals.

Expand sequential segments and explicit-label segments to `page-map.json`, containing exactly one record per document page. Normalize labels only for matching; always retain their original display form. Reject ambiguous duplicate indexable labels, range-length mismatches, uncovered document pages, overlapping segments, and labels that cannot be expanded deterministically. Read [page-mapping-and-chunks.md](page-mapping-and-chunks.md).

## `define-chunks`

Required: user-approved one-based inclusive document-page ranges for each chunk and the expanded page map.

ChatGPT may propose chapter-based boundaries after inspecting the source, but the user must approve or supply the final ranges. Create `chunk-manifest.json` with stable chunk IDs, owned document-page ranges, optional context ranges, source unit labels, and packet order. Validate that every in-scope document page has exactly one owner and that context does not create duplicate ownership.

## `define-policy`

Instantiate and freeze [standard-policy.md](standard-policy.md) before subject discovery. Do not ask the user to create policies. Bind the standard policy to the exact source hash, one-based document-page span, page-map hash, chunk-manifest hash, inferred readership, audit mode, and source-specific availability/scope facts. Inspect the source to determine whether notes, captions, tables, and other eligible roles are present and inspectable.

Ask only when a matter role is genuinely ambiguous, a publisher specification conflicts with the default, or the user requests a deviation. Record every deviation with path, prior value, replacement, rationale, provenance, and freeze time.

Use the fixed chapter-level density profile: target 8 locator-bearing complete heading paths and 20 expanded locator occurrences per 1,000 indexable source words; target bands 6–10 and 15–25; broad tolerance bands 4–12 and 10–30. Output schema-valid, canonically hashed `subject-index-evaluation-policy-v3` with policy profile `subject-index-standard-policy-v1`. This policy freezes source judgment rules and gates but intentionally contains no score-rubric or dimension-calculation identity.

## `prepare-source-chunks`

Required: source PDF and validated chunk manifest.

Create one PDF per chunk containing the union of owned and context document pages, in original order. Also create a sidecar JSON mapping each chunk-PDF page back to the original one-based document page and source page label. Do not modify the source PDF. The candidate index must not be included in source-discovery packets.

## `discover-source-subjects [chunk-id]`

Required: source, policy, chunk manifest, and the assigned chapter/page range. Candidate indexes must not be present or inspected.

Read the complete owned range plus declared context pages. Determine which subjects are substantively treated under the standard coverage/selectivity rules, not merely which terms occur. Emit one `source-subject-chunk` JSON artifact containing subjects, priority, meaning/stance, relationships, acceptable terminology, evidence passages, locator classes, exclusions, uncertainty, and the unit's indexable source-word count. Do not impose a target number of subjects and do not use density calibration to prune or pad discovery.

The completion test is every owned document page inspected once, all page-level uncertainties recorded, and the artifact schema-valid.

## `worker-discovery [chunk-id] --project [repository]`

Required from the user: one chunk ID and a GitHub benchmark repository/project. Resolve the exact source and latest compatible validated checkpoint from the active project or Library when each is unambiguous; ask only when multiple or missing candidates prevent hash-safe selection. Accept an optional immutable base commit and base branch. When omitted, read the repository's default-branch head once and record that exact commit before work begins.

This is the parallel form of `discover-source-subjects`. Import the checkpoint into an isolated worker directory, reconnect the restricted source by SHA-256, and apply every normal candidate-blind discovery requirement. Do not inspect other source-subject chunks until the fresh source-led draft is complete; afterward use them only for schema and procedural consistency.

Default the worker branch to `source-discovery/<lowercase-chunk-id>`. Refuse to overwrite an existing branch. Produce the normal `source/source-subject-chunk.<chunk-id>.json` plus a branch-local `parallel-source-discovery-receipt-v1` generated with:

```bash
python scripts/parallel_discovery_cli.py worker-receipt \
  --state evaluation-state.json \
  --chunk-manifest source/chunk-manifest.json \
  --artifact source/source-subject-chunk.CHUNK-003.json \
  --chunk-id CHUNK-003 \
  --project owner/repository \
  --base-commit <40-character-sha> \
  --output workers/CHUNK-003/worker-discovery-receipt.json
```

Save worker recovery files to a chunk-specific Library folder so concurrent workers never replace canonical Library control files. The GitHub branch and pull request contain exactly one mergeable path: the chapter artifact. Do not include `evaluation-state.json`, `artifact-manifest.json`, checkpoints, PDFs, sidecars, raw extracted text, or worker receipts. Inspect the outgoing JSON for unexpected verbatim source text and secrets before publication.

Create one commit, push the branch, and open a pull request into the configured base branch. Do not merge the pull request or update a candidate evaluation repository. Include base commit, source and evaluation identities, chunk ranges, blindness status, page count, subject/priority/evidence counts, word count, artifact SHA-256, validation result, and limitations in the pull-request description.

The completion test is: the worker receipt validates; the recovery copy is durable; the branch contains exactly the allowed artifact; and an open, unmerged pull request reports the receipt facts. If GitHub publication is denied, the durable recovery copy satisfies work preservation but the command returns `blocked` with the exact denial.

## `integrate-discoveries --project [repository] [pull-request-or-branch ...]`

Required: the canonical validated study, GitHub benchmark repository/project, and an explicit list of worker pull requests or branches. Never discover or merge all open pull requests implicitly.

Act as the sole coordinator for shared state. Verify before any merge that every selected pull request:

- is open and targets the expected base branch;
- originates from the expected repository and `source-discovery/<chunk-id>` branch;
- changes exactly `source/source-subject-chunk.<chunk-id>.json`;
- contains no PDFs, sidecars, checkpoints, control files, raw source text, or unrelated changes; and
- has a unique chunk ID not already represented by a different frozen artifact.

Fetch every proposed artifact and validate the full set before merging any pull request. Use `scripts/parallel_discovery_cli.py integrate` in a disposable copy first when practical. Require matching evaluation, source, policy, page-map, and chunk-manifest hashes; exact owned/context pages; complete page review; valid subject/evidence structure; and preserved candidate blindness unless the user explicitly accepts a documented compromised run. If any proposed artifact fails, merge none.

After the full set passes, merge the selected pull requests, materialize the resulting base head, and integrate all newly merged artifacts into the canonical study in one transaction:

```bash
python scripts/parallel_discovery_cli.py integrate \
  --state evaluation-state.json \
  --chunk-manifest source/chunk-manifest.json \
  --artifact /path/to/source-subject-chunk.CHUNK-003.json \
  --artifact /path/to/source-subject-chunk.CHUNK-004.json
```

The helper copies each artifact to its canonical path, registers it as frozen/private/required, updates the manifest first and state last, and completes source discovery only when every manifest chunk has one active artifact. Then run `validate`, create one cumulative portable checkpoint, and make one shared-control commit on the base branch. Advance candidate-evaluation benchmark locks only to that canonical integration commit, never to an unintegrated worker branch.

The completion test is: all selected PRs are merged; their exact artifact hashes are registered; canonical validation succeeds; a cumulative checkpoint exists; shared control files are committed once; and downstream benchmark locks identify the new canonical commit.

## `synthesize-source-benchmark`

Required: all validated source-subject chunk artifacts and frozen policy. Candidate indexes must remain unseen.

Perform a whole-source reconciliation: merge genuine duplicate concepts without collapsing meaningful distinctions, preserve defensible alternate access, connect cross-chapter treatments, resolve relationships when evidence permits, perform a source-first omission pass, reconcile priorities, consolidate evidence, freeze neither the artifact nor its conclusions, and assign stable `SUBJ-*`, `REL-*`, and `TASK-*` identifiers. Output schema-valid `source-benchmark.draft.vN.json` with schema `source-subject-benchmark-draft-v1` and a synthesis record. Register it as private, required, and unfrozen.

The completion test is that every active chunk artifact is represented, page coverage is complete, the candidate remained unseen, and the deterministic review inventory can be generated without structural errors.

## `review-source-benchmark`

Required: the synthesis draft, exact source, policy, chunk artifacts, and a fresh context that has not seen any candidate index.

Run `scripts/benchmark_review_cli.py screen` to create `validation/source-benchmark-review-inventory.json`. Reconnect the source by SHA-256 and independently review every required ID in full mode. Revisit cross-chapter concepts, disposition unresolved relationships, inspect fallback-generated tasks, check semantic boundaries, meaning, stance, priority, acceptable access, evidence sufficiency, and perform a fresh source-first omission search. Record all decisions and proposed changes in `validation/source-benchmark-review.vN.json`; do not silently edit the draft.

Run `validate-review`. Full mode requires exact review coverage of every inventory queue and an approving recommendation before freeze. Pilot review records a declared sample and limitations, sets `public_claims_allowed` to false, and cannot authorize freeze. Read [benchmark-review.md](benchmark-review.md).

## `freeze-source-benchmark`

Required: synthesis draft, review inventory, completed independent review ledger, policy, and any approved revised benchmark.

Apply every approved change, preserve frozen identity fields, and output `source-benchmark.vN.json` with schema `source-subject-benchmark-v2` and a canonical SHA-256 hash. Run `scripts/benchmark_review_cli.py validate-final`; do not complete the stage if review validation or hash recomputation fails. Candidate blindness must be `preserved` for public full-evaluation claims.

`retain_draft` keeps canonical benchmark content and version. `approve_revised` requires a changed final benchmark and incremented version. Any substantive post-freeze edit creates a new version and invalidates results tied to the previous hash.

## `worker-candidate-preparation [candidate-id] --project [repository] --benchmark-project [repository]`

Required: one candidate ID, restricted candidate PDF, candidate-evaluation repository, benchmark repository, validated source state, edition identity, expanded page map, chunk manifest, frozen judgment-policy identity, and the version-one preparation-compatibility marker. That marker remains `subject-index-rubric-v4`; it is not the active V5 score identity. Optional: immutable benchmark preparation ref and adapter (`auto`, `generic-pdf-layout`, or `indexerlabs-two-column`). Resolve and record the benchmark default-branch head once when no ref is supplied.

Run in an isolated context that is not used for source discovery, synthesis, or benchmark review. Do not inspect benchmark subjects. Use the common adapter contract to capture geometry and reading order, normalize every delivered hierarchy level, locator/range, and cross-reference without editorial repair, expand locators through the frozen ordered page map, build candidate-index-v2 and item-inventory-v2, and complete the full normalization QA ledger described in [candidate-preparation.md](candidate-preparation.md). Candidate preparation may precede final benchmark freeze because it makes no candidate-quality judgment and does not mutate canonical state.

Create a candidate-specific private recovery root and a deterministic preparation-portable ZIP excluding the candidate PDF. Generate a private receipt that binds every source/candidate/preparation identity and private hash. Default the branch to `candidate-preparation/<normalized-candidate-id>` and refuse an existing branch.

Publish exactly:

```text
candidate/candidate-ref.json
candidate/layout-profile.json
validation/candidate-preparation-report.json
```

Validate these files against strict public schemas, run the outgoing content scan, inspect the exact diff, create one commit, push one branch, and open one unmerged pull request. If the repository is completely empty, one prior parentless bootstrap commit on `main` must contain exactly `README.md` and `.gitignore`, with GitHub-observed preceding empty state and complete two-blob root-tree evidence; otherwise the exception is forbidden. Query the GitHub API for schema-valid publication evidence and pass it to the helper with `bind-publication --publication-evidence <file>`; the helper must not trust caller assertions about PR state, branches, commits, commit count, or changed files. Record the evidence hash, PR number/URL, base/head branches and commits, and Git blob/file hashes in the finalized private receipt. Do not publish any PDF, raw extraction, normalized index, inventory, detailed QA, private recovery path, absolute path, Library ID, checkpoint, credential, or secret.

The command succeeds only when candidate bytes are verified, all private artifacts validate, full QA is complete, the recovery ZIP exists, the public projection passes its exact allowlist and safety scan, and an open unmerged pull request identifies the receipt facts. It returns `blocked` after one explicit publication denial without repeatedly retrying.

## `integrate-candidate-preparation --project [repository] --benchmark-project [repository] --benchmark-ref [commit] [pull-request-or-branch]`

Required: canonical v4 evaluation state, exactly one explicit preparation PR or branch, its matching private receipt/recovery root, candidate-evaluation repository, benchmark repository, and explicit final canonical benchmark commit. The final source benchmark must be frozen and canonically hashed.

Before merging, verify the unchanged PR head, exact public paths, Git blob/file hashes, public safety, private hashes, candidate/source/edition/page-map/chunk/policy/preparation-marker/audit identities, full QA set parity, and final benchmark compatibility. Resolve private recovery artifacts only from the explicitly supplied receipt/root; never sweep workers or Library. Both helper `preflight-integration` and `integrate` require a GitHub-API-derived open-PR snapshot acquired for the current integration attempt through `--publication-evidence <file>` and a GitHub-API-derived `candidate-benchmark-git-proof-v1` through `--benchmark-proof <file>`. The original publication evidence bound into the immutable receipt remains historical proof and does not expire, but it cannot replace the current-attempt premerge snapshot. Evidence timestamps record provenance and chronology and have no elapsed-time TTL. Verify the benchmark proof's project, commit, path, blob, and file hashes before building `candidate-benchmark-lock.json`. Reject missing, caller-asserted, or incompatible coordinator evidence; pending/missing locks; and any final page-map change.

The helper authenticates neither a local file nor its author: `evidence_source` is a format discriminator, not a signature. The coordinator must create these files only from its own direct GitHub connector/API observations and must reject an evidence file furnished by the user or worker. Deterministic fixtures are permitted only in the synthetic test suite.

After all preflight checks pass, merge the public-safe proposal. Query the GitHub API again, materialize strict `candidate-preparation-merge-evidence-v1` directly from connector output, and pass it through required `integrate --merge-evidence <file>`; never accept user-authored assertions as API evidence. The merged proof must bind the selected PR, closed/merged state, base/head/merge commits, one-commit count, and exact three path/blob/file hashes. Copy the exact accepted private worker bytes to versioned canonical paths, register them and the lock, update the artifact manifest first and evaluation state last, complete the existing `candidate_normalization` stage, run complete validation, and checkpoint. The benchmark lock records `premerge_evidence_sha256`, `merge_evidence_sha256`, the exact public blob map, and the benchmark repository path/blob/proof hash/observation; the integration report records both PR-evidence hashes plus `benchmark_proof_sha256`. Leave `locator_chunk_preparation` as the earliest available candidate-audit stage. Do not update the benchmark repository and do not modify normalized candidate content during integration.

## `normalize-index`

Required: original candidate index, page mapping, and a frozen compatible benchmark. This is the serial post-freeze alternative to `worker-candidate-preparation` plus `integrate-candidate-preparation`.

Parse every main heading, every delivered subheading level, complete heading path, displayed locator/range, and cross-reference. Expand ranges to individual locator assignments while preserving the displayed form. Create stable IDs and retain raw candidate text or coordinates privately. Emit only candidate-index-v2 and item-inventory-v2. Never repair wording, filing, hierarchy, locators, or references silently. Preserve third-level headings and mixed locator/reference records for later judgment.

Run `scripts/item_grade_cli.py build-inventory` over `candidate-index.v2.json` and output `item-inventory.v2.json`. The inventory must deterministically enumerate every `PATH-*`, `LOC-*`, unique heading-level `NODE-*`, and cross-reference `XREF-*`. Register both files as required private artifacts of candidate normalization. The inventory contains identities and display relationships, not judgments.

Every expanded locator assignment must retain `source_page_label` as a string and resolve to exactly one `document_page` through the frozen page map. Expand displayed ranges by resolving both endpoint labels and walking the ordered document pages within the same mapping segment; do not assume Arabic arithmetic. Mark unresolved or ambiguous labels explicitly; do not guess from an apparent numeric offset.

## `prepare-locator-chunks`

Required: normalized candidate, expanded page map, validated chunk manifest, and a final `candidate-benchmark-lock-v1` whose candidate, page-map, and chunk-manifest identities match those exact inputs. Pass the lock to `scripts/page_chunk_cli.py filter-candidate` with `--benchmark-lock`; never route locator packets from a pending or missing lock.

Create one `candidate-locator-chunk.*.json` packet per chunk. Include a candidate path only when it has at least one resolved locator assignment whose `document_page` is owned by that chunk. Include the complete heading path and only the assignments owned by the chunk. Retain the original displayed locator or range and report `other_locator_assignment_count`, but do not send the other assignments.

Do not include unrelated headings, containers, or cross-references in locator-audit packets. They remain available to the later global structure audit. Reject unresolved locators from routing and place them in a separate exception ledger.

## `prepare-locator-worker-prompts --project [candidate-evaluation-repository]`

Required: completed validated locator-packet preparation; exact candidate-evaluation and benchmark identities; immutable candidate-repository base branch and commit observed directly from GitHub; a validated cumulative portable checkpoint and its Library folder; an evaluation-specific Library worker root; and, for every selected chunk, the packet path/hash/assignment count plus exact Library paths, materialization destinations, and SHA-256 hashes for the restricted source PDF and page sidecar.

Create `locator-worker-prompt-pack-v1.json` from validated artifacts and direct GitHub observations, never from conversational memory. Copy the effective frozen `configuration.publication_profile` into the pack; omitted legacy packs default to `aggregate_only`. Before rendering, confirm that every selected default branch `locator-audit/<lowercase-chunk-id>` is absent; record the immutable base commit once and still require each launched worker to recheck for collision. Run:

```bash
python scripts/worker_prompt_cli.py render-locator-pack \
  --input locator-worker-prompt-pack-v1.json \
  --checkpoint /path/to/validated-locator-packets-checkpoint-portable.zip \
  --output worker-locator-audit-prompts.md
```

The renderer must hash-verify the checkpoint and require its explicit `configuration.publication_profile` to equal the prompt pack profile. A legacy checkpoint that omits the field is a hard preflight failure, even when the prompt states a profile. Migrate an eligible pre-audit checkpoint explicitly with `bundle_cli.py migrate-publication-profile`, validate the resulting bundle, update `checkpoint_sha256`, and only then render prompts.

Generate exactly one self-contained prompt per selected chunk. Every prompt must identify all frozen hashes and denominators; reconnect and hash-verify the exact restricted PDF and sidecar; use the chunk-scoped recovery root and branch; and publish only the one artifact selected by `configuration.publication_profile`. Include this post-publication sequence: obtain a direct GitHub observation, run `bind-publication` so it rebuilds the recovery ZIP and replaces the preliminary receipt with a `published_unmerged` receipt, rerun `validate-worker`, then save the final publication-bound canonical receipt and receipt-bound recovery ZIP to `<evaluation-library-root>/workers/locator-audit/<chunk-id>/` without renaming either file. Require verification of the exact PR URL, head commit, public-artifact hash, audit hash, receipt hash, and recovery-ZIP hash, and forbid any later PR modification or merge by the worker. Read [publication-profiles.md](publication-profiles.md).

Save the prompt pack beside the canonical integration checkpoint. The completion test is: its input specification is hash-grounded; every selected chunk appears exactly once; all Library recovery roots are evaluation- and chunk-specific; every canonical receipt/ZIP filename remains unchanged; and every prompt contains the final publication-bound replacement instruction. This command prepares launch text only and does not run workers, create branches, or open pull requests.

## `audit-locators [chunk-id]`

Required: source chunk PDF, candidate locator chunk packet, policy, expanded page map, and chunk manifest.

For each supplied assignment, test whether its mapped source page substantively supports the complete heading path and preserves meaning/stance. Apply the scope, entity/example, compound-heading, and locator rules to every atomic path/page pair. Inspect local context pages as needed, but judge each owned assignment once. Output one item per locator assignment with `supported`, `partially_supported`, `unsupported`, or `uninspectable`, a concise public-safe evidence paraphrase, error codes, severity, and confidence. Keep any necessary exact quotation or extended evidence in a restricted ledger referenced by evidence ID; do not copy it into display summaries.

This command measures proposed-locator precision and entry legitimacy. It does not measure omissions or recall.

This remains the sequential command. It uses the same substantive judgment contract and canonical `locator-audit-v1` artifact as `worker-locator-audit`.

## `worker-locator-audit [chunk-id] --project [candidate-evaluation-repository]`

Required: one exact chunk ID and candidate-evaluation repository; completed and validated candidate normalization; final candidate benchmark lock; complete locator-packet preparation; the corresponding locator-only packet; the exact source chunk and sidecar reconnected by source SHA-256; frozen policy, page map, and chunk manifest; normalized candidate and item inventory; an immutable candidate-repository base commit; and one unique empty local private worker recovery root. Pass only `--recovery-root`; the helper derives `locator-audit-worker-receipt.json` and `locator-audit-worker-recovery.zip` beneath it and preflights the boundary before audit validation. Persist those files to the Library worker folder only after local publication binding and validation succeed.

Import the validated candidate checkpoint in isolation and verify every source, candidate, benchmark, policy, page-map, chunk-manifest, normalized-candidate, inventory, and packet identity. Audit every packet assignment exactly once, preserve the complete heading path, exclude foreign-chunk assignments, and use only `supported`, `partially_supported`, `unsupported`, or `uninspectable`. Store public-safe paraphrased evidence, evidence IDs, error codes, severity, and confidence in the complete `locator-audit-v1` artifact. Its publication visibility is selected by the frozen profile. Do not perform missing-access, global-structure, density, item-assessment, scoring, or reporting work.

Default the branch to `locator-audit/<lowercase-chunk-id>` and refuse an existing branch. Preserve the audit, receipt, worker state, worker manifest, and recovery ZIP beneath `workers/locator-audit/<chunk-id>/` before publication. In `aggregate_only`, publish exactly `validation/locator-audit-worker.<chunk-id>.json`. In `public_evaluation_artifacts`, publish the exact validated audit bytes at `candidate/locator-audits/locator-audit.<chunk-id>.v1.json`. Use one commit and one open, unmerged pull request; never publish the receipt or recovery material, update canonical state or manifests, merge the pull request, or modify the benchmark repository.

Use `scripts/parallel_candidate_audit_cli.py build-locator-worker`, `bind-publication`, and `validate-worker`. After opening the pull request, obtain a direct GitHub observation and run `bind-publication`; it deterministically rebuilds the recovery ZIP, replaces the preliminary receipt with a `published_unmerged` receipt, and writes the integration binding against the final hashes. Rerun `validate-worker`, then replace the preliminary Library `locator-audit-worker-receipt.json` and recovery ZIP with the final publication-bound canonical files in the same chunk-specific folder. Verify the final receipt's exact PR URL, head commit, public/audit hashes, receipt hash, and ZIP hash; do not rename the files or modify the pull request afterward. Read [parallel-candidate-audits.md](parallel-candidate-audits.md) and [publication-profiles.md](publication-profiles.md). The completion test is: exact assignment accounting and all hashes validate; the final publication-bound receipt and receipt-bound ZIP are durable in Library; the selected public artifact passes its profile-specific strict allowlist and safety scan; and the one-file pull request remains open and unmerged. A publication denial preserves private recovery and returns `blocked`. Coordinator preflight rejects a preliminary receipt even when a separate binding file exists.

## `integrate-locator-audits --project [candidate-evaluation-repository] [pull-request-or-branch ...]`

Required: the canonical validated candidate study, candidate repository, the complete frozen locator-packet set covering every chunk in the chunk manifest, an explicit nonempty list of locator-worker pull requests or branches, and one explicit private receipt/recovery-root binding for each proposal. Never sweep open pull requests, worker folders, or Library, and never infer private recovery material from a candidate or chunk ID.

Act as the sole coordinator. Distinguish global inputs from wave-scoped inputs: retrieve and hash-verify exactly one canonical locator packet for every frozen chunk, while limiting pull-request selections, worker bindings, receipts, and recovery roots to the explicitly selected wave. Obtain open-PR evidence directly from the GitHub connector/API for the current integration attempt and every selected proposal. Before merging anything, verify the complete packet-set coverage, expected base, `locator-audit/<chunk-id>` head branch, immutable commits, exact one-file public allowlist, public hashes and safety, unique chunk ownership, matching private receipt and recovery bytes, all frozen identities, exact packet and owned-page denominators, and one judgment for every selected packet assignment. Reject overlaps, duplicate or missing assignment IDs, foreign assignments, caller-authored API evidence, and conflicting reintegration. Preflight the complete selected batch transactionally with `scripts/parallel_candidate_audit_cli.py preflight-batch`, passing all frozen packets through repeated `--locator-packet` arguments even for a partial wave; if any member fails, merge none.

After the complete selected batch passes, merge only those proposals and obtain post-merge PR evidence directly from the connector/API. Run `integrate-batch` once with the same complete frozen locator-packet set used for preflight to materialize the exact accepted audits at versioned canonical paths with profile-appropriate visibility, record worker/PR/commit/receipt/recovery provenance, update the artifact manifest before state, and validate the canonical evaluation. Partial batches leave `locator_audit` in progress; complete it only when every frozen locator chunk has one accepted, conflict-free audit whose assignment union exactly matches all packets. Create one cumulative private checkpoint and one shared-control commit. An identical already-integrated chunk is recognized idempotently; different bytes for that chunk are rejected.

## `audit-missing-access [chunk-id]`

Required: frozen benchmark, normalized candidate, complete canonical locator judgments, policy, page map, and chunk manifest. Source PDF and chunk bytes are not routine inputs.

For each frozen essential or major source subject owned by the chunk, test whether the candidate provides a plausible direct or cross-referenced access route, preserves required distinctions, and includes principal/supporting/conclusion passages under policy. Test important subsidiary or localized subjects when frozen as scored. Exclude nonindexable or unavailable source matter from denominators. Output concept coverage, locator recall, missing routes, missed treatments, and reader-task results. This is the source-to-index pass that prevents circular evaluation.

This remains the sequential command. It uses the same benchmark-first substantive judgment contract and canonical `missing-access-audit-v1` artifact as `worker-missing-access-audit`. A separate source adjudication may inspect the source only for explicitly recorded uncertain or uninspectable exceptions.

## `worker-missing-access-audit [chunk-id] --project [candidate-evaluation-repository]`

Required: one exact chunk ID and candidate repository; completed candidate normalization and locator-packet preparation; a canonically complete locator-audit stage; a valid canonical evaluation; frozen final benchmark; complete normalized candidate and inventory; the complete canonical locator-audit set; source/candidate identities; frozen policy, page map, and chunk manifest; immutable candidate-repository base commit; and one unique empty local private worker recovery root. Pass only `--recovery-root`; the helper derives `missing-access-worker-receipt.json` and `missing-access-worker-recovery.zip` beneath it and preflights the boundary before loading frozen inputs or validating the audit. Persist those files to the Library worker folder only after local publication binding and validation succeed. Do not supply or inspect the source PDF, source chunk, or sidecar. A per-chunk locator result never satisfies the complete-locator-stage gate.

If Library resolves the required checkpoint metadata but its authenticated agent-side transfer returns HTTP 502, stop before audit work with `checkpoint_transfer_http_502` and ask the user to attach the exact named checkpoint to the same conversation. Include its expected SHA-256 and byte length when known. Resume from the original command only after verifying the attached archive hash, all member hashes and lengths, and canonical validation; do not retry the failing Library transfer or treat the attachment filename as proof.

If Library resolves the required checkpoint metadata but its authenticated agent-side transfer returns HTTP 502, stop before audit work with `checkpoint_transfer_http_502` and ask the user to attach the exact named checkpoint to the same conversation. Include its expected SHA-256 and byte length when known. Resume from the original command only after verifying the attached archive hash, all member hashes and lengths, and canonical validation; do not retry the failing Library transfer or treat the attachment filename as proof.

For every scored benchmark subject and reader task deterministically owned by the chunk, test direct and cross-reference access, preserved distinctions and stance, principal/supporting/synthesis-or-conclusion treatments, realistic first-lookup success, locator recall, missed treatments, and missing routes. Account for required subject IDs and task IDs exactly once and preserve concept-coverage and locator-recall denominators separately. The helper coalesces multiple benchmark evidence records for one subject/page/class into one treatment unit and requires every coalesced evidence ID in that treatment judgment. Record severity, confidence, uncertainty, evidence IDs, and any formal locator dependency defect without silently reinterpreting frozen inputs. Use uncertain or uninspectable for a benchmark ambiguity and name the evidence needed for centralized source adjudication.

Default the branch to `missing-access-audit/<lowercase-chunk-id>` and refuse an existing branch. Preserve the complete audit, receipt, state, manifest, and recovery ZIP beneath `workers/missing-access-audit/<chunk-id>/`. In `aggregate_only`, publish exactly `validation/missing-access-audit-worker.<chunk-id>.json`. In `public_evaluation_artifacts`, publish the exact validated audit bytes at `candidate/missing-access-audits/missing-access-audit.<chunk-id>.v1.json`. Use one commit and one open, unmerged pull request. Do not publish receipts or recovery data, change the benchmark or candidate, perform global-structure or density work, score, report, update canonical state, or merge the pull request.

Use `scripts/parallel_candidate_audit_cli.py build-missing-access-worker`, `bind-publication`, and `validate-worker`. After opening the pull request, obtain a direct GitHub observation and run `bind-publication`; it preserves that historical observation inside a deterministically rebuilt recovery ZIP, replaces the preliminary receipt with a `published_unmerged` receipt, and writes the integration binding against the final hashes. Rerun `validate-worker`, then replace the preliminary Library `missing-access-worker-receipt.json` and recovery ZIP with the final publication-bound canonical files in the same chunk-specific folder. Verify the final receipt's exact PR URL, head commit, public/audit hashes, receipt hash, and ZIP hash; do not rename the files or modify the pull request afterward. Read [parallel-candidate-audits.md](parallel-candidate-audits.md) and [publication-profiles.md](publication-profiles.md). The completion test is: exact subject/task and treatment accounting plus all hashes validate; the final publication-bound receipt and receipt-bound ZIP are durable in Library; the selected public artifact passes its profile-specific allowlist and safety scan; and the one-file pull request remains open and unmerged. Coordinator preflight rejects a preliminary receipt even when a separate binding file exists, while allowing a fresh observation of the exact unchanged proposal.

## `integrate-missing-access-audits --project [candidate-evaluation-repository] [pull-request-or-branch ...]`

Required: a valid canonical study with complete integrated locator audits; candidate repository; an explicit nonempty list of missing-access worker pull requests or branches; and one explicit private receipt/recovery-root binding for every proposal. Never sweep or infer proposals or private recovery material.

Obtain current-attempt open-PR evidence directly from the GitHub connector/API. Validate the exact one-file public allowlist, unique chunk ownership, all frozen identities and dependency hashes, the complete canonical locator-audit set, each private recovery artifact, and exact subject, reader-task, concept-coverage, treatment, and locator-recall denominators. Reject missing, duplicated, foreign-chunk, or conflicting judgments and any incompatible locator-audit dependency. Preflight the entire selected batch with `preflight-batch`; merge none when any member fails.

When the frozen profile is `public_evaluation_artifacts` and an agent-side storage-transfer error alone makes a selected worker receipt or recovery ZIP unavailable, run `parallel_candidate_audit_cli.py reconstruct-public-handoff` before batch preflight. Supply the exact public canonical audit downloaded from that PR, fresh direct open-PR evidence, every canonical locator audit, all frozen inputs, one new isolated private recovery root, and the explicit selection. The operation revalidates the complete audit and produces a coordinator-labeled receipt, recovery ZIP, and ordinary worker binding. It is forbidden for `aggregate_only`, locator audits, incomplete public bytes, or substantive validation failures. It does not authorize a merge and does not replace `preflight-batch`.

After successful preflight, merge only the selected proposals, obtain post-merge PR evidence, and run `integrate-batch` once. Materialize exact private bytes at versioned canonical paths, record complete provenance, update manifest first and state last, and validate. Partial batches leave `missing_access_audit` in progress; complete it only when all required chunks, subjects, reader tasks, and treatment denominators are accepted exactly once. Then create one cumulative private checkpoint and one shared-control commit. Recognize identical reintegration idempotently and reject conflicting bytes.

## `audit-index-structure`

Required: complete normalized candidate, all locator judgments, all missing-access judgments, and policy.

Judge the index globally under the heading/access, cross-reference, coherence, and mechanics rules: heading clarity, parent-child truth, sibling parallelism, direct access, underdivision, overdivision, fragmentation, terminology consistency, every cross-reference, filing, mechanics, distribution, and long undivided locator strings. Measure both frozen density metrics for each chapter using indexable source words and use source-word-weighted aggregation. Preserve the raw chapter word counts, but derive locator occurrences from the chunk's expected stable locator IDs and locator-bearing paths from its unique `PATH-*` judgments; the V5 scorer independently reconstructs those counts and rejects drift. Output `structure-audit.json` with item-level defects, chapter measurements, target disclosure, and metrics.

Use the frozen item inventory. Judge every `NODE-*` separately for conceptual/stance fidelity, heading/access architecture, and mechanics. Judge every `XREF-*` as supported, partially supported, unsupported, or uninspectable. Record completion counts against the inventory and include node/reference evidence IDs. A main-heading node judgment concerns that heading's wording and organizational role; do not hide a weak child by averaging its descendants.

For a new V5 evaluation, use `structure-audit-v4` and freeze `audit_mode` plus `v5_scoring_context`. Record the candidate-attempt classification, genuine cross-reference applicability basis, every optional subject's benchmark-bound scored/excluded decision, a one-to-one benchmark-grounded basis for every genuinely inapplicable node component, and structured cap-relevant defects. Every scoring defect must state its dimension owner, compatible defect code, severity and operational basis, retrieval consequence, affected item/source/structure IDs, root-cause family, counts, denominators, reconstructable rates, and high-priority-access flag. A cap cannot trigger from prose alone. Do not edit a historical `structure-audit-v3`; bind any migration supplement to its exact SHA-256, its recorded historical locator/missing-access set hashes, and canonical set hashes recomputed over the same frozen files.

Do not decide that a parent-child relation is valid merely because the child locator is valid; test whether the relationship expressed by the full path is true and useful.

## `score-index`

Required: normalized candidate, item inventory, and all audits complete and schema-valid.

First run `scripts/item_grade_cli.py build-assessments` and produce `subject-index-item-assessments-v2` under [item-grading.md](item-grading.md). In full mode, require one judgment for every resolved locator, heading node, cross-reference, path, and expected source subject. In pilot mode, retain unsampled inventory items with neutral `not_measured` grades. Every item must carry `grade`, `color_token`, component factors, public-safe popover content, confidence where applicable, and evidence IDs. Bind the exact V5 calculation evidence identity and exact item-inventory artifact; the five assessment arrays and their summaries must exhaust the corresponding inventory or expected-subject ID sets without duplicates. Register the complete artifact as private by default because its labels and locators may reproduce the candidate; publishing a full colored index requires a separate rights and disclosure decision.

Create `subject-index-dimension-calculation-input-v1` containing only the audit mode plus exact paths and SHA-256 hashes for the canonical user-approved chunk manifest, all locator audits, all missing-access audits, the structure audit, and—only for a V3 historical structure audit—the hash-bound migration supplement. The supplied ledgers must cover every manifest chunk exactly once and must agree on every frozen candidate, source, benchmark, policy, page-map, chunk-manifest, normalized-candidate, and item-inventory identity. The manifest must retain user approval, required full-scope coverage, unique ownership, complete scope coverage, and a reconstructable self-hash. The input audit mode must equal the mode frozen in the structure audit or migration supplement. Run:

```text
python scripts/dimension_score_cli.py preflight --input dimension-calculation-input.json
python scripts/dimension_score_cli.py calculate --input dimension-calculation-input.json --output dimension-calculations.json
```

The ordinary `calculate` command is only for a new `structure-audit-v4`. If the input binds a historical `structure-audit-v3`, it returns `score_only_migration_required`; use `migrate-score-only` with the exact historical V4 result so its gates cannot be bypassed. The canonical helper validates every referenced schema and hash, reconstructs and verifies the exact locator- and missing-access-audit set hashes, carries the validated candidate and upstream evidence identities into the calculation artifact, derives all six ratings from raw statuses, computes missing-data endpoint bounds, evaluates every cap (triggered or not), applies only the most restrictive cap, and uses `Decimal` with `ROUND_HALF_UP`. Full mode stops on any required `not_measured` item. A numeric dimension is published only when both bounds have the same public rating and applied-cap identity.

Create a new `subject-index-evaluation-result-v6` binding the exact `subject-index-dimension-calculations-v1` path, artifact hash, and calculation profile. Reference the V2 item-assessment artifact by its exact relative path, file hash, schema, grading policy, and summary. Projection validation resolves those bytes and verifies its item-inventory artifact, exact calculation evidence identity, complete assessment ID sets, and summary counts. Publication-readiness gates are copied as independent claim restrictions and never enter score arithmetic. Diagnostic item grades remain non-additive. Qualitative anchors may warn after calculation but cannot select or override a number.

After creating the result and web report, validate both projections against the exact calculation bytes:

```text
python scripts/dimension_score_cli.py validate-projections --calculation dimension-calculations.json --evaluation-result evaluation-result.json --web-report web-report.json
```

This rejects duplicate or omitted dimensions and any drift in the result candidate/evidence identity, comparison key, scorecard, headline total, web scorecard formula details, calculation path/hash binding, resolved item-assessment bytes or identity, result/web item-assessment agreement, or result/web gate projection.

## `preflight-v5-scoring`

Run `dimension_score_cli.py preflight` against frozen ledgers before a new V5 calculation or historical migration. It never mutates evidence and returns actionable missing requirements, including all independently enumerable density and full-mode omissions after prerequisite integrity checks pass; fix prerequisite failures and rerun until sufficient. It rejects omitted or duplicate chunks, mixed frozen identities, caller-only audit-mode relabeling, audit-set hashes that do not match the supplied canonical bytes, and any recomputable structure/density aggregate that disagrees with stable locator, path, or cross-reference IDs. A historical `structure-audit-v3` without the V5 provenance needed for severity, recurrence, non-attempt, optional-subject, node-component applicability, or reference-applicability decisions is insufficient until a reviewed `subject-index-v5-migration-supplement-v1` is bound to the exact V3 structure hash, its historical set hashes, and the canonical set hashes of the same frozen files. A public aggregate or export whose bytes cannot satisfy that reconciliation is not a migration input.

## `migrate-score-only`

Required: sufficient V5 preflight, exact frozen ledgers, and an immutable historical V4 result. Run `dimension_score_cli.py score-only-migration` with separate calculation and migration-record outputs. The helper rejects output/input path aliasing, proves all input-ledger and historical-result bytes are unchanged, emits `subject-index-score-migration-v1`, and embeds the migration-record path plus historical result and gate hashes in the V5 calculation's `migration_context`; ordinary calculation refuses V3 ledgers. It marks V4/V5 totals not directly comparable. Gate preservation is recorded only after the historical result's candidate, source, benchmark, policy, page-map, chunk-manifest, normalized-candidate, item-inventory, structure-audit, locator-set, missing-set, and audit-mode identities match the frozen V5 evidence. State and projection validation both resolve the context-bound record, its exact historical V4 result, its exact V5 calculation, and its frozen ledgers before accepting it. The new V6 result must bind that same exact migration record and copy the historical `critical_gates`; `validate-projections` rejects a changed gate set, a substituted migration record, or a native V5 calculation that claims a migration. Never overwrite or relabel the V4 result. Use `state_cli.py set-score-calculation-profile --state ... --preflight ... --calculation-input ...` to rerun the authoritative preflight from the frozen input and reset only scoring and web reporting after exact agreement is established. Every manifest, locator audit, missing-access audit, structure audit, and supplement supplied to that command must resolve to the same path and hash as a frozen, required artifact registered under the corresponding completed stage in both evaluation state and artifact manifest; matching `evaluation_id` alone is never sufficient.

## `build-web-report`

Required: valid evaluation result and selected representative examples.

Create `subject-index-web-report-v4` using the web schema and the public presentation strategy in [customer-methodology.md](customer-methodology.md). Organize the report in four layers: (1) overall result and publication-readiness status, (2) six plain-language quality questions, (3) measured evidence and representative examples, and (4) complete methodology, scope, and limitations. Make layers three and four expandable in the web interface.

Include a plain-language grade, scorecard, measured rates, density profile and result, gates, strengths, consequential defects, balanced examples, methodology, comparability key, disclosure, and limitations. Bind the calculation artifact and expose structured formula inputs, denominators, components, evaluated caps, uncertainty bounds, rounding, rating, and weighted-points arithmetic without parsing prose. Reference the complete `item-assessments.json` artifact by relative path and hash. Publish its semantic color legend and specify that interfaces read colors from `grade.color_token` and hover/focus content from `popover`. Ensure keyboard and touch access as well as hover, pair every color with a text label or icon, and render not-measured items neutrally. State explicitly that this framework targets 8 locator-bearing paths and 20 locator occurrences per 1,000 indexable source words, evaluated by chapter as permissive calibration rather than quotas. Avoid copyrighted source excerpts beyond what is necessary to verify a judgment. Never require a customer to interpret raw internal artifacts to understand a score; link every displayed conclusion to supporting evidence IDs for optional inspection.

## `checkpoint`

Required: valid state and artifact manifest.

Create an in-progress ZIP using `scripts/bundle_cli.py checkpoint`. Default to the `portable` profile, which includes control files and all available public/private registered artifacts but excludes restricted source/candidate files. Use `private-complete` only when the user requests it and has authority to retain the restricted inputs. Return bundle path, hash, inclusion/exclusion counts, and warnings. Do not register a checkpoint inside itself.

Checkpoint after policy freeze, benchmark freeze, candidate scoring, web reporting, and before a chat/environment handoff.

## `export-bundle`

Required: valid state and artifact manifest.

Create a named delivery ZIP using the same profiles and validation as `checkpoint`. A portable export is the interoperable default. Exporting is not publishing: never send the bundle to a repository, website, or third party without a separate user request.

## `import-bundle`

Required: checkpoint/export ZIP and a new or empty evaluation directory.

Use `scripts/bundle_cli.py import-bundle`. Reject traversal, absolute paths, duplicate members, and symlink-like entries. Verify state and manifest hashes plus every included registered artifact. Report restricted exclusions as `reconnect_required`; reconnect those inputs by SHA-256 before dependent work. Then run `validate`, `status`, and `next`.

For an authorized publication-profile correction to a legacy pre-audit checkpoint, use:

```text
python scripts/bundle_cli.py migrate-publication-profile \
  --input old-checkpoint.zip \
  --output migrated-checkpoint.zip \
  --from-profile aggregate_only \
  --publication-profile public_evaluation_artifacts
```

The migration validates the original bundle and all included manifest hashes, requires the declared source profile to match the effective legacy profile, refuses checkpoints containing candidate-audit work or started downstream judgment stages, writes the profile explicitly, recomputes bundle metadata and hashes, and preserves every substantive artifact byte. Replace a persisted checkpoint only after validating the migrated output and updating every prompt-pack checkpoint hash that refers to it.

## `validate`

Validate current state, artifact manifest parity, relative paths, artifact presence and hashes, dependency order, schema conformance, coverage denominators, score arithmetic, and comparison key. Return errors and warnings separately. Validation success does not certify editorial judgments; it certifies structural and arithmetic consistency.
