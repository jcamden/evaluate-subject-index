# Command reference

Commands are a prompt vocabulary implemented by the skill, not assumed to be native application slash commands. Return JSON by default. A human-readable explanation may accompany JSON when requested.

## `help [command]`

Show purpose, syntax, required inputs, generated artifact, dependencies, completion test, and likely next command. With no argument, return every command in workflow order and identify whether each is available, blocked, or complete from the current state.

## `initialize`

Required: source file, source title, document-page count or document-page span, index type, intended readership, audit mode (`full` or `pilot`), storage mode (`local`, `library`, or `hybrid`), and evaluation directory. Candidate input is optional and must not be opened yet.

Create `evaluation-state.json` and `artifact-manifest.json`. Hash the source file, record edition identity if known, store no ephemeral absolute input path, and set every workflow stage to `not_started`. Document pages are one-based ordinals in the supplied file; they are not assumed to equal page labels printed in the book. Use `hybrid` in ChatGPT when Library is available and `local` otherwise.

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

Freeze provisional project rules before subject discovery:

- exact source, one-based document-page span, frozen page-label map, chunk manifest, and included/excluded matter;
- named-entity, examples, heading-depth, locator, and cross-reference policies;
- intended readers and index type;
- full or pilot audit design and uncertainty treatment;
- critical gates;
- density metrics with ideal and acceptable bands; and
- rubric version.

Output `evaluation-policy.json`. The density profile can be informed by source length, genre, complexity, audience, and publisher specification, but never by candidate sizes. A universal density band must not be invented when no defensible specification exists; mark the metric `descriptive_only` until calibrated.

## `prepare-source-chunks`

Required: source PDF and validated chunk manifest.

Create one PDF per chunk containing the union of owned and context document pages, in original order. Also create a sidecar JSON mapping each chunk-PDF page back to the original one-based document page and source page label. Do not modify the source PDF. The candidate index must not be included in source-discovery packets.

## `discover-source-subjects [chunk-id]`

Required: source, policy, chunk manifest, and the assigned chapter/page range. Candidate indexes must not be present or inspected.

Read the complete owned range plus declared context pages. Determine which subjects are substantively treated, not merely which terms occur. Emit one `source-subject-chunk` JSON artifact containing subjects, priority, meaning/stance, relationships, acceptable terminology, evidence passages, locator classes, exclusions, and uncertainty. Do not impose a target number of subjects.

The completion test is every owned document page inspected once, all page-level uncertainties recorded, and the artifact schema-valid.

## `freeze-source-benchmark`

Required: all source-subject chunk artifacts and policy.

Merge duplicate concepts, preserve defensible alternate access, resolve cross-chapter relationships, perform a source-first omission/synthesis pass, freeze reader tasks, and assign stable concept IDs. Output `source-benchmark.json` with a canonical SHA-256 hash. Candidate blindness must be recorded as `preserved`, `compromised`, or `not_claimed`.

Any substantive post-freeze edit creates a new benchmark version and invalidates results tied to the previous hash.

## `normalize-index`

Required: original candidate index and page mapping.

Parse every main heading, subheading, complete heading path, locator/range, and cross-reference. Expand ranges to individual locator assignments while preserving the displayed form. Create stable IDs and retain raw source text or coordinates. Output `candidate-index.json` plus a normalization report. Never repair wording, filing, locators, or references silently.

Every expanded locator assignment must retain `source_page_label` as a string and resolve to exactly one `document_page` through the frozen page map. Expand displayed ranges by resolving both endpoint labels and walking the ordered document pages within the same mapping segment; do not assume Arabic arithmetic. Mark unresolved or ambiguous labels explicitly; do not guess from an apparent numeric offset.

## `prepare-locator-chunks`

Required: normalized candidate, expanded page map, and validated chunk manifest.

Create one `candidate-locator-chunk.*.json` packet per chunk. Include a candidate path only when it has at least one resolved locator assignment whose `document_page` is owned by that chunk. Include the complete heading path and only the assignments owned by the chunk. Retain the original displayed locator or range and report `other_locator_assignment_count`, but do not send the other assignments.

Do not include unrelated headings, containers, or cross-references in locator-audit packets. They remain available to the later global structure audit. Reject unresolved locators from routing and place them in a separate exception ledger.

## `audit-locators [chunk-id]`

Required: source chunk PDF, candidate locator chunk packet, policy, expanded page map, and chunk manifest.

For each supplied assignment, test whether its mapped source page substantively supports the complete heading path and preserves meaning/stance. Inspect local context pages as needed, but judge each owned assignment once. Output one item per locator assignment with `supported`, `partially_supported`, `unsupported`, or `uninspectable`, evidence, error codes, severity, and confidence.

This command measures proposed-locator precision and entry legitimacy. It does not measure omissions or recall.

## `audit-missing-access [chunk-id]`

Required: frozen benchmark, normalized candidate, locator judgments, source, and chunk manifest.

For each frozen essential or major source subject owned by the chunk, test whether the candidate provides a plausible direct or cross-referenced access route, preserves required distinctions, and includes principal/supporting/conclusion passages under policy. Output concept coverage, locator recall, missing routes, missed treatments, and reader-task results. This is the source-to-index pass that prevents circular evaluation.

## `audit-index-structure`

Required: complete normalized candidate, all locator judgments, all missing-access judgments, and policy.

Judge the index globally: heading clarity, parent-child truth, sibling parallelism, direct access, underdivision, overdivision, fragmentation, terminology consistency, cross-reference validity, filing, mechanics, distribution, long undivided locator strings, and frozen density metrics. Output `structure-audit.json` with item-level defects and metrics.

Do not decide that a parent-child relation is valid merely because the child locator is valid; test whether the relationship expressed by the full path is true and useful.

## `score-index`

Required: all audits complete and schema-valid.

Calculate the rubric from evidence ledgers, report denominators, apply critical gates, and produce `evaluation-result.json`. Use half-point dimension ratings only after calculating their supporting metrics. The total is a quality summary, not a percent correct. Do not override an item ledger to produce a preferred grade.

## `build-web-report`

Required: valid evaluation result and selected representative examples.

Create `web-report.json` using the web schema. Include a plain-language grade, scorecard, measured rates, density profile and result, gates, strengths, consequential defects, balanced examples, methodology, comparability key, disclosure, and limitations. Avoid copyrighted source excerpts beyond what is necessary to verify a judgment.

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
