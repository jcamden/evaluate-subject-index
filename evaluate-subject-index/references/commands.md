# Command reference

Commands are a prompt vocabulary implemented by the skill, not assumed to be native application slash commands. Return JSON by default. A human-readable explanation may accompany JSON when requested.

## `help [command]`

Show purpose, syntax, required inputs, generated artifact, dependencies, completion test, and likely next command. With no argument, return every command in workflow order and identify whether each is available, blocked, or complete from the current state.

## `initialize`

Required from the user: source file and, only when not clear from the file, source title/edition. Determine the document-page span from the file. Default to subject index, full audit, and `hybrid` storage when Library is available (`local` otherwise). Candidate input is optional and must not be opened yet.

Infer intended readership from the source. Do not ask unless confidence is low or the user identifies a different target. Record the label, `inferred` or `user_supplied` basis, confidence, and rationale. Create `evaluation-state.json` and `artifact-manifest.json`. Hash the source file, record edition identity if known, store no ephemeral absolute input path, and set every later workflow stage to `not_started`. Document pages are one-based ordinals in the supplied file; they are not assumed to equal page labels printed in the book.

## `status`

Read `evaluation-state.json`; validate it; return completed, active, blocked, and available stages, relevant artifact paths and hashes, and comparability warnings. Do no substantive evaluation.

## `next`

Return exactly the earliest dependency-satisfied incomplete stage, the command to run, required inputs, completion test, and blockers. Do not skip a dependency because later files happen to exist.

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

Use the fixed chapter-level density profile: target 8 locator-bearing complete heading paths and 20 expanded locator occurrences per 1,000 indexable source words; target bands 6–10 and 15–25; broad tolerance bands 4–12 and 10–30. Output schema-valid, canonically hashed `evaluation-policy.json` with policy profile `subject-index-standard-policy-v1` and rubric `subject-index-rubric-v4`.

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

Required: one candidate ID, restricted candidate PDF, candidate-evaluation repository, benchmark repository, validated source state, edition identity, expanded page map, chunk manifest, and frozen policy/rubric identities. Optional: immutable benchmark preparation ref and adapter (`auto`, `generic-pdf-layout`, or `indexerlabs-two-column`). Resolve and record the benchmark default-branch head once when no ref is supplied.

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

Before merging, verify the unchanged PR head, exact public paths, Git blob/file hashes, public safety, private hashes, candidate/source/edition/page-map/chunk/policy/rubric/audit identities, full QA set parity, and final benchmark compatibility. Resolve private recovery artifacts only from the explicitly supplied receipt/root; never sweep workers or Library. Both helper `preflight-integration` and `integrate` require a fresh GitHub-API-derived open-PR snapshot through `--publication-evidence <file>` and a GitHub-API-derived `candidate-benchmark-git-proof-v1` through `--benchmark-proof <file>`. The original publication evidence bound into the immutable receipt remains historical proof and does not expire, but it cannot replace the fresh premerge snapshot. Verify the benchmark proof's project, commit, path, blob, and file hashes before building `candidate-benchmark-lock.json`. Reject missing, caller-asserted, stale, or incompatible coordinator evidence; pending/missing locks; and any final page-map change.

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

## `audit-locators [chunk-id]`

Required: source chunk PDF, candidate locator chunk packet, policy, expanded page map, and chunk manifest.

For each supplied assignment, test whether its mapped source page substantively supports the complete heading path and preserves meaning/stance. Apply the scope, entity/example, compound-heading, and locator rules to every atomic path/page pair. Inspect local context pages as needed, but judge each owned assignment once. Output one item per locator assignment with `supported`, `partially_supported`, `unsupported`, or `uninspectable`, a concise public-safe evidence paraphrase, error codes, severity, and confidence. Keep any necessary exact quotation or extended evidence in a restricted ledger referenced by evidence ID; do not copy it into display summaries.

This command measures proposed-locator precision and entry legitimacy. It does not measure omissions or recall.

## `audit-missing-access [chunk-id]`

Required: frozen benchmark, normalized candidate, locator judgments, source, and chunk manifest.

For each frozen essential or major source subject owned by the chunk, test whether the candidate provides a plausible direct or cross-referenced access route, preserves required distinctions, and includes principal/supporting/conclusion passages under policy. Test important subsidiary or localized subjects when frozen as scored. Exclude nonindexable or unavailable source matter from denominators. Output concept coverage, locator recall, missing routes, missed treatments, and reader-task results. This is the source-to-index pass that prevents circular evaluation.

## `audit-index-structure`

Required: complete normalized candidate, all locator judgments, all missing-access judgments, and policy.

Judge the index globally under the heading/access, cross-reference, coherence, and mechanics rules: heading clarity, parent-child truth, sibling parallelism, direct access, underdivision, overdivision, fragmentation, terminology consistency, every cross-reference, filing, mechanics, distribution, and long undivided locator strings. Measure both frozen density metrics for each chapter using indexable source words and use source-word-weighted aggregation. Output `structure-audit.json` with item-level defects, chapter measurements, target disclosure, and metrics.

Use the frozen item inventory. Judge every `NODE-*` separately for conceptual/stance fidelity, heading/access architecture, and mechanics. Judge every `XREF-*` as supported, partially supported, unsupported, or uninspectable. Record completion counts against the inventory and include node/reference evidence IDs. A main-heading node judgment concerns that heading's wording and organizational role; do not hide a weak child by averaging its descendants.

Do not decide that a parent-child relation is valid merely because the child locator is valid; test whether the relationship expressed by the full path is true and useful.

## `score-index`

Required: normalized candidate, item inventory, and all audits complete and schema-valid.

First run `scripts/item_grade_cli.py build-assessments` and produce `item-assessments.json` under [item-grading.md](item-grading.md). In full mode, require one judgment for every resolved locator, heading node, and cross-reference. In pilot mode, retain unsampled inventory items with neutral `not_measured` grades. Every item must carry `grade`, `color_token`, component factors, public-safe popover content, confidence where applicable, and evidence IDs. Register the complete artifact as private by default because its labels and locators may reproduce the candidate; publishing a full colored index requires a separate rights and disclosure decision.

Then calculate the rubric from evidence ledgers, report denominators, apply critical gates, and produce `evaluation-result.json`. Reference the exact item-assessment path, hash, policy version, and summary. Use half-point dimension ratings only after calculating their supporting metrics. The total is a quality summary, not a percent correct. Diagnostic item grades do not add to or replace it. Do not override an item ledger to produce a preferred grade.

## `build-web-report`

Required: valid evaluation result and selected representative examples.

Create `web-report.json` using the web schema and the public presentation strategy in [customer-methodology.md](customer-methodology.md). Organize the report in four layers: (1) overall result and publication-readiness status, (2) six plain-language quality questions, (3) measured evidence and representative examples, and (4) complete methodology, scope, and limitations. Make layers three and four expandable in the web interface.

Include a plain-language grade, scorecard, measured rates, density profile and result, gates, strengths, consequential defects, balanced examples, methodology, comparability key, disclosure, and limitations. Reference the complete `item-assessments.json` artifact by relative path and hash. Publish its semantic color legend and specify that interfaces read colors from `grade.color_token` and hover/focus content from `popover`. Ensure keyboard and touch access as well as hover, pair every color with a text label or icon, and render not-measured items neutrally. State explicitly that this framework targets 8 locator-bearing paths and 20 locator occurrences per 1,000 indexable source words, evaluated by chapter as permissive calibration rather than quotas. Avoid copyrighted source excerpts beyond what is necessary to verify a judgment. Never require a customer to interpret raw internal artifacts to understand a score; link every displayed conclusion to supporting evidence IDs for optional inspection.

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

## `validate`

Validate current state, artifact manifest parity, relative paths, artifact presence and hashes, dependency order, schema conformance, coverage denominators, score arithmetic, and comparison key. Return errors and warnings separately. Validation success does not certify editorial judgments; it certifies structural and arithmetic consistency.
