# JSON artifact contracts

The schemas in `schemas/` are machine-readable contracts. Each schema controls extensibility explicitly: strict preparation, publication, proof, lock, and integration contracts reject unexpected fields, while broader evaluation artifacts may preserve richer evidence where their schema permits it. Required identity, status, score, and provenance fields must remain stable.

| Artifact | Schema | Purpose |
| --- | --- | --- |
| Evaluation state | `evaluation-state.schema.json` | Resume, dependency, hash, and next-action state |
| Artifact manifest | `artifact-manifest.schema.json` | Portable relative paths, hashes, visibility, retention, and freeze state |
| Bundle metadata | `bundle-metadata.schema.json` | Checkpoint profile, control hashes, included paths, and exclusions |
| Compact page-map input | `page-map-input.schema.json` | User-approved document-page to source-label ranges |
| Expanded page map | `page-map.schema.json` | One record per original document page |
| Chunk manifest | `chunk-manifest.schema.json` | User-approved ownership and context ranges |
| Policy build input | `policy-build-input.schema.json` | Source-bound facts used to instantiate the standard policy |
| Historical policy | `evaluation-policy.schema.json` | V2 policy with legacy V4 rubric binding, retained for historical validation |
| Judgment policy | `evaluation-policy-v3.schema.json` | Run-specific standard policy with frozen scope, audience, gates, and density rules but no score identity |
| Source chunk | `source-subject-chunk.schema.json` | Candidate-blind chapter/page discoveries |
| Parallel discovery receipt | `parallel-source-discovery-receipt.schema.json` | Branch base, validation summary, publication scope, and PR handoff for one worker chunk |
| Benchmark draft | `source-benchmark-draft.schema.json` | Unfrozen whole-source synthesis awaiting independent review |
| Benchmark review inventory | `source-benchmark-review-inventory.schema.json` | Deterministic review denominators, queues, and diagnostics |
| Benchmark review | `source-benchmark-review.schema.json` | Independent candidate-blind editorial review and freeze recommendation |
| Benchmark | `source-benchmark.schema.json` | Final frozen whole-source subject graph and evidence denominator |
| Normalized candidate | `candidate-index-v2.schema.json` | Fidelity-preserving arbitrary-depth paths, displayed locators, mixed/multiple references, and private evidence joins |
| Item inventory | `item-inventory-v2.schema.json` | Stable identities for candidate-index-v2, including arbitrary heading depth and multiple references |
| Candidate reference | `candidate-ref.schema.json` | Candidate/source identity plus separate provenance, completeness, compatibility, and authoritative-fidelity findings |
| Layout profile | `candidate-layout-profile.schema.json` | Private aggregate PDF/layout and adapter facts used to derive the minimized public profile |
| Layout extraction | `candidate-layout-extraction.schema.json` | Private adapter-neutral page, region, line, coordinate, continuation, and extraction evidence |
| Normalization exceptions | `candidate-normalization-exceptions.schema.json` | Every malformed, unresolved, or fidelity-sensitive preparation exception |
| Normalization report | `candidate-normalization-report.schema.json` | Private aggregate normalization results and private artifact hashes |
| Normalization QA | `candidate-normalization-qa.schema.json` | Complete review denominators, page accounting, corrections, and fidelity gate |
| Preparation receipt | `candidate-preparation-receipt.schema.json` | Worker, repository, source/candidate, private/public hash, PR, recovery, and pending-lock handoff |
| Publication evidence | `candidate-preparation-publication-evidence.schema.json` | GitHub-API proof of the open unmerged one-commit exact-allowlist worker pull request |
| Merge evidence | `candidate-preparation-merge-evidence.schema.json` | GitHub-API proof that the selected exact-allowlist worker pull request closed and merged unchanged |
| Public preparation projection | `candidate-preparation-public-projection.schema.json` | Strict union of the three allowlisted aggregate public documents |
| Public preparation report | `candidate-preparation-report.schema.json` | Strict aggregate public projection with no reconstructable index content |
| Preparation recovery metadata | `candidate-preparation-bundle-metadata.schema.json` | Deterministic private recovery ZIP inventory and restricted exclusions |
| Candidate benchmark lock | `candidate-benchmark-lock.schema.json` | Final benchmark repository/commit/hash and all comparison identities required before candidate audit |
| Benchmark Git proof | `candidate-benchmark-git-proof.schema.json` | GitHub-API proof binding the selected final benchmark path and bytes to its commit |
| Candidate integration report | `candidate-preparation-integration.schema.json` | Selected proposal, immutable hashes, and transaction ordering for accepted preparation |
| Candidate integration checkpoint | `candidate-integration-checkpoint.schema.json` | Private post-integration bundle inventory and exclusions |
| Candidate locator chunk | `candidate-locator-chunk.schema.json` | Only paths and assignments owned by one audit chunk |
| Locator batch | `locator-audit.schema.json` | One judgment for every expanded candidate locator |
| Parallel locator worker receipt | `parallel-locator-audit-worker-receipt.schema.json` | Private identities, denominators, public binding, recovery inventory, and handoff for one chunk |
| Public locator worker report | `locator-audit-worker-report.schema.json` | Strict aggregate projection used by `aggregate_only` |
| Locator integration batch | `locator-audit-batch-integration.schema.json` | Explicit proposals, accepted private artifacts, provenance, conflicts, and stage-completion accounting |
| Missing-access batch | `missing-access-audit.schema.json` | Benchmark-to-index concept coverage and locator recall, with source-grounded benchmark lineage |
| Parallel missing-access worker receipt | `parallel-missing-access-worker-receipt.schema.json` | V2 worker receipts plus the coordinator-reconstructed public-artifact fallback, frozen dependencies, benchmark-first input mode, exact denominators, public binding, and recovery inventory |
| Public missing-access worker report | `missing-access-worker-report.schema.json` | V2 strict aggregate projection used by `aggregate_only` |
| Missing-access integration batch | `missing-access-batch-integration.schema.json` | Explicit proposals, locator dependencies, accepted private artifacts, provenance, and completion accounting |
| Candidate-audit open-PR evidence | `candidate-audit-open-pr-evidence.schema.json` | Current-attempt GitHub-API observation of one open exact-allowlist worker pull request |
| Candidate-audit merge evidence | `candidate-audit-merge-evidence.schema.json` | Post-merge GitHub-API observation that the selected pull request merged unchanged |
| Candidate-audit recovery metadata | `candidate-audit-worker-recovery.schema.json` | Deterministic private ZIP inventory, artifact hashes, and restricted exclusions |
| Candidate-audit coordinator reconstruction | `candidate-audit-coordinator-reconstruction.schema.json` | Self-hashed private provenance for a missing-access handoff reconstructed from complete public canonical audit bytes |
| Candidate-audit integration binding | `candidate-audit-integration-binding.schema.json` | One-to-one coordinator-private proposal, receipt, recovery-root, report, and evidence binding |
| Candidate-audit repository state | `candidate-audit-repository-state.schema.json` | Immutable base branch/commit and existing-branch collision evidence for worker setup |
| Historical structure audit | `structure-audit.schema.json` | V3 global audit retained for V4 validation and explicit migration |
| V5 structure audit | `structure-audit-v4.schema.json` | Global audit plus frozen audit mode, exact audit-set provenance, cosmetic mechanics status, and strict scoring context |
| V5 migration supplement | `v5-migration-supplement.schema.json` | Structure-bound historical-to-canonical audit-set reconciliation plus severity, recurrence, optional-subject, node-applicability, non-attempt, and reference-applicability provenance missing from an immutable V3 audit |
| Historical item assessments | `item-assessments.schema.json` | V1 diagnostic grades, semantic color tokens, popover factors, and evidence joins retained for historical results |
| V5 item assessments | `item-assessments-v2.schema.json` | Projection-safe V2 grades bound to the exact calculation evidence identity and item-inventory bytes, with complete unique ID-set accounting for every displayed item family |
| V6 combined locator state | `locator-evidence-state-v2.schema.json` | Cross-field judgment, treatment, scope, inspectability, and error-code consistency required before V6 credit assignment |
| V6 item assessments | `item-assessments-v3.schema.json` | V2 diagnostic policy with locator grades 100/70/25/0/neutral, per-locator reliability credit and disqualifiers, and unchanged stable item families |
| Density input | `density-input.schema.json` | Chapter word, path, and locator counts for deterministic density scoring |
| Shared V5/V6 calculation input | `dimension-calculation-input.schema.json` | Frozen audit mode plus exact paths and SHA-256 hashes for the canonical chunk manifest and complete raw scoring-ledger sets; the evidence semantics are unchanged in V6 |
| V5 dimension calculations | `dimension-calculations.schema.json` | Validated evidence identity plus strict denominators, raw component numerators/denominators, mappings, normalized components, cap evaluations, uncertainty bounds, rounding, ratings, weighted points, and score-migration context when applicable |
| V6 dimension calculations | `dimension-calculations-v2.schema.json` | V5 calculation provenance plus weighted and strict precision, per-locator reliability credits, tier/treatment/judgment counts, endpoint calculations, and V6 score-only migration context |
| Score migration | `score-migration.schema.json` | V1 historical compatibility plus portable V2 immutable V4 provenance, exact tool/methodology identity, old/new scores, per-input lineage, representation-correction separation, gate preservation, and comparability warning |
| Score-migration validation | `score-migration-validation.schema.json` | Post-projection receipt binding old result, calculation, migration, new result, web report, score views, and unchanged gates without a circular hash |
| Historical evaluation result | `evaluation-result.schema.json` | V4 scored result retained for validation and migration |
| V5 evaluation result | `evaluation-result-v6.schema.json` | V5 calculation binding, scorecard projection, exact item-assessment reference, separate gates, optional bound migration record, and decoupled comparison key |
| V6 evaluation result | `evaluation-result-v7.schema.json` | V6 calculation and V3 item binding, exact scorecard projection, public strict/weighted precision diagnostics, separate gates, and optional V5-to-V6 migration record |
| Historical web report | `web-report.schema.json` | V3 display payload retained as immutable history |
| V5 web report | `web-report-v4.schema.json` | Display-ready inputs, formulas, raw and normalized components, caps, bounds, rating, points, item-assessment binding, old/new migration comparison, explicit observed/counterfactual score views, and independent gate projection |
| V6 score migration | `score-migration-v5-to-v6.schema.json` | Immutable V5 artifact bytes and hashes, a bounded common artifact root with descendant-only bindings, frozen-evidence checks, old/new score and precision comparison, unchanged gates/selectivity, and calculation-only invalidation |
| V6 projection metadata | `v6-projection-metadata.schema.json` | Customer labels, gates, display content, comparison identities, and optional hash-bound counterfactual calculation/provenance inputs used to build V6 projections |
| V6 web report | `web-report-v5.schema.json` | Display-ready V6 scorecard, reconstructable reliability provenance, both precision measures, V3 item grades, gates outside arithmetic, and V5-to-V6 comparison |

## Stable identifiers

Use opaque IDs rather than mutable labels:

- `SUBJ-*` for benchmark subjects;
- `PATH-*` for complete candidate heading paths;
- `DISPLAY-*` for displayed locator or range tokens;
- `RANGE-*` for displayed range groupings;
- `LOC-*` for expanded locator assignments;
- `NODE-*` for unique displayed main-heading and subheading nodes;
- `XREF-*` for individual cross-reference records;
- `CHUNK-*` for page ownership units;
- `TASK-*` for reader tasks; and
- `DEFECT-*` for underlying defects.

Use `subject-index-rubric-v6` and `subject-index-dimension-calculation-v2` for newly created V6 results. Preserve `subject-index-rubric-v4` and `subject-index-rubric-v5` artifacts under their original readers and validators. Never feed a historical headline rating, diagnostic item grade, or gate outcome into V6 calculation input.

V6 keeps the V5 frozen input contract because the locator ledgers already carry the necessary structured fields. It versions every artifact whose declared semantics change: calculations V2, result V7, item assessments V3, grading policy V2, web report V5, and V5-to-V6 migration V1. A shared input schema does not authorize reinterpretation of a V5 calculation or projection.

The shared calculation input binds the canonical manifest and complete frozen locator, missing-access, and structure ledgers by path and SHA-256. Both scorers reconstruct the candidate, source, benchmark, benchmark-lock, policy, page-map, chunk-manifest, normalized-candidate, item-inventory, structure-audit, locator-set, and missing-set identities. They reject incomplete or mixed chunk sets, duplicate logical treatment units, contradictory recomputable structure or density aggregates, and unsupported `not_applicable` claims.

V6 calculation V2 stores exact decimal base and post-cap values as strings, final half-step ratings and two-decimal points as JSON numbers, and every dimension's bound input artifacts, denominators, exclusion reasons, mappings, components, caps, endpoints, rounding, rating, weight, and points. Page-reference Reliability additionally retains every locator credit and disqualifier plus both precision measures. A migrated V2 calculation carries a hash-covered `migration_context` that resolves its V5-to-V6 record and exact historical V5 calculation, result, and web-report hashes. Current migration records declare an ancestor-only `artifact_path_root`; all individual historical and migrated artifact paths are normalized descendants, and validation rejects path or symlink escape. Historical V6 records without that field remain record-directory-relative. Projection validation resolves and hash-checks those immutable historical artifacts, reruns the V5 projection validator, checks frozen input lineage and evidence identity, preserves representation-correction provenance through the unchanged historical projections, requires gate arrays and hashes to match exactly, and reconstructs the V6 result and web comparison. Native V6 projections are validated through the same calculation, item, precision, scorecard, and gate reconstruction path without migration fields.

Every V6 score view is calculation-backed. The primary view must resolve to the supplied canonical calculation. Each counterfactual must resolve to a distinct `subject-index-dimension-calculations-v2` artifact with a valid canonical hash, matching evaluation/audit identity and shared candidate/source/benchmark/policy/page-map/chunk lineage, a displayed score equal to its calculated total, and at least one resolved, hash-matching provenance artifact. Migrated V6 reports additionally preserve the immutable V5 counterfactual IDs and every historical representation-provenance hash.

Historical V5 calculation V1, result V6, item V2, web-report V4, and V4-to-V5 migration artifacts continue to use their unchanged schemas and validators. V6 never rewrites or reinterprets those documents. Cross-reference inapplicability and every other unchanged dimension rule retain the V5 evidence and denominator semantics documented in [rubric-v5.md](rubric-v5.md).

The judgment-policy/benchmark identity and score identity are separate. Comparison keys pin both `judgment_policy_sha256` and the scoring pair (`rubric_version`, `dimension_calculation_profile`). A scoring-only change may reuse frozen discovery, benchmark, preparation, and audit artifacts only when deterministic preflight proves the complete chunk set, exact audit-set identities, uniform upstream identities, frozen audit mode, and V5 scoring context are sufficient.

Use `subject-index-item-grading-v2` with `subject-index-item-assessments-v3` for V6 diagnostic grades. Keep the grading policy separate from the rubric version. V5 continues to use `subject-index-item-grading-v1` and `subject-index-item-assessments-v2`. Every item assessment requires a semantic color token, explicit grade scope, evidence IDs, and a public-safe popover with structured factors. A null score must use `grade_neutral` and `not_measured`; never convert unknown or uninspectable evidence to zero.

The V6 reliability record stores the original, assessable, uninspectable, and not-measured locator counts; counts by judgment, treatment class, and credit tier; every locator's credit, rationale, and disqualifiers; weighted and strict precision numerators, denominators, values, and bounds; treatment recall; weighted F1; pre-cap rating; central and endpoint cap evaluations; applied cap; uncertainty endpoints; rounding; final rating; dimension weight; and points. Both `evaluation-result-v7` and `web-report-v5` expose `precision_diagnostics` with `weighted_locator_precision` and `strict_substantive_precision`. See [web-report-fields-v5.md](web-report-fields-v5.md).

## Null and missing data

Use explicit measurement states such as `measured`, `not_measured`, `uninspectable`, and `not_applicable`. Do not encode unknown values as zero. Rates contain numerator, denominator, value, and excluded counts. In full mode any required `not_measured` item blocks scoring. `uninspectable` items receive lower/upper calculations and permit a number only when both the rounded rating and cap outcome are stable. Selectivity excludes source-unavailable, out-of-scope, and ambiguous subjects from its denominator; those states are not repurposed as candidate selectivity uncertainty.

## Canonical hashes

For frozen JSON artifacts, remove the artifact's own hash field, serialize UTF-8 JSON with keys sorted and compact separators, then compute SHA-256. Drafts also receive a deterministic canonical hash in the review inventory, but that hash does not imply freeze. Record schema version, generator version, timestamp, input hashes, and superseded artifact hash when applicable.

Use relative POSIX paths rooted at the evaluation directory in state and manifests. Never store ephemeral absolute paths or make canonical identity depend on a Library ID. Register each artifact only after validation; update state last. Read [storage-and-checkpoints.md](storage-and-checkpoints.md).

Candidate normalization uses candidate-index-v2 and subject-index-item-inventory-v2 only. V2 preserves any delivered third or deeper hierarchy level and `cross_references[]`; it does not imply that those structures satisfy the standard policy. Preparation artifacts remain benchmark-independent, while `candidate-benchmark-lock.json` binds the accepted normalization to the final compatible benchmark before auditing.

Parallel candidate audits reuse `locator-audit-v1` and `missing-access-audit-v1` as their complete judgment formats. Worker receipts, public artifacts, GitHub evidence, recovery metadata, and batch-integration records wrap and bind those canonical artifacts; they do not define alternative scoring or judgment policies. `aggregate_only` keeps the complete audits private and publishes their strict aggregate reports. `public_evaluation_artifacts` publishes the exact validated audits under an additional exact-key, bounded-text, path, and secret allowlist. Read [publication-profiles.md](publication-profiles.md).

Public worker-report schemas are strict allowlists. Permit only aggregate identities, immutable hashes, owned ranges, denominator and status counts, severity/error-code counts, completion, stage-appropriate input-verification status, limitations, the private artifact hash, and a public-safety result. Locator reports record source/chunk/sidecar reconnection; missing-access reports record source lineage through the frozen benchmark plus candidate and canonical locator-set verification. Reject candidate headings or subheadings, complete paths, displayed locators or ranges, cross-reference wording, reconstructable source-subject labels, page-specific comparisons, raw extraction, coordinates, exact or extended source text, detailed evidence tied to candidate records, PDFs, Library identifiers, absolute paths, credentials, and secrets.

Publication and merge evidence schemas validate shape, chronology, branch/base/commit identities, changed paths, Git blob/file hashes, and cross-artifact bindings. Evidence timestamps are retained for provenance and ordering but have no elapsed-time TTL. The schemas do not authenticate who created a local JSON file. The coordinator must materialize current-attempt evidence directly from its own GitHub connector/API output; an `evidence_source` string is a format discriminator, never an attestation.

## Web safety

The web report and item assessments should reference evidence IDs and short paraphrases. Keep exact quotations and long copyrighted passages in a restricted audit artifact when lawful, not in either public payload. Preserve candidate labels separately from any organizer blind key until scores are frozen.
