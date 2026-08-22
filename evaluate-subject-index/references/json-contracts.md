# JSON artifact contracts

The schemas in `schemas/` are web-oriented contracts. Additional fields are allowed so an implementation can preserve richer evidence, but required identity, status, score, and provenance fields must remain stable.

| Artifact | Schema | Purpose |
| --- | --- | --- |
| Evaluation state | `evaluation-state.schema.json` | Resume, dependency, hash, and next-action state |
| Artifact manifest | `artifact-manifest.schema.json` | Portable relative paths, hashes, visibility, retention, and freeze state |
| Bundle metadata | `bundle-metadata.schema.json` | Checkpoint profile, control hashes, included paths, and exclusions |
| Compact page-map input | `page-map-input.schema.json` | User-approved document-page to source-label ranges |
| Expanded page map | `page-map.schema.json` | One record per original document page |
| Chunk manifest | `chunk-manifest.schema.json` | User-approved ownership and context ranges |
| Policy build input | `policy-build-input.schema.json` | Source-bound facts used to instantiate the standard policy |
| Policy | `evaluation-policy.schema.json` | Run-specific instance of standard policy v1 with frozen scope, audience provenance, gates, and density rules |
| Source chunk | `source-subject-chunk.schema.json` | Candidate-blind chapter/page discoveries |
| Benchmark | `source-benchmark.schema.json` | Frozen whole-source subject graph and evidence denominator |
| Normalized candidate | `candidate-index.schema.json` | Complete paths, references, and expanded locator assignments |
| Item inventory | `item-inventory.schema.json` | Stable path, locator, heading-node, and cross-reference identities for display and audit joins |
| Candidate locator chunk | `candidate-locator-chunk.schema.json` | Only paths and assignments owned by one audit chunk |
| Locator batch | `locator-audit.schema.json` | One judgment for every expanded candidate locator |
| Missing-access batch | `missing-access-audit.schema.json` | Source-to-index concept coverage and locator recall |
| Structure audit | `structure-audit.schema.json` | Global hierarchy, navigation, cross-reference, mechanics, and density evidence |
| Item assessments | `item-assessments.schema.json` | Diagnostic grades, semantic color tokens, popover factors, and evidence joins for every display item |
| Density input | `density-input.schema.json` | Chapter word, path, and locator counts for deterministic density scoring |
| Evaluation result | `evaluation-result.schema.json` | Auditable scores, metrics, gates, and comparison key |
| Web report | `web-report.schema.json` | Display-ready narrative and evidence cards |

## Stable identifiers

Use opaque IDs rather than mutable labels:

- `SUBJ-*` for benchmark subjects;
- `PATH-*` for complete candidate heading paths;
- `LOC-*` for expanded locator assignments;
- `NODE-*` for unique displayed main-heading and subheading nodes;
- `XREF-*` for individual cross-reference records;
- `CHUNK-*` for page ownership units;
- `TASK-*` for reader tasks; and
- `DEFECT-*` for underlying defects.

Use `subject-index-rubric-v4` for newly created results. Its density payload must preserve both standardized targets, target and broad tolerance bands, chapter-level measurements, source-word-weighted aggregation, and the five-point maximum contribution.

Use `subject-index-item-grading-v1` for diagnostic item grades. Keep it separate from the rubric version. Every item assessment requires a semantic color token, explicit grade scope, evidence IDs, and a public-safe popover with structured factors. A null score must use `grade_neutral` and `not_measured`; never convert unknown or uninspectable evidence to zero.

## Null and missing data

Use explicit measurement states such as `measured`, `not_measured`, `uninspectable`, and `not_applicable`. Do not encode unknown values as zero. Rates contain numerator, denominator, value, and excluded counts.

## Canonical hashes

For frozen JSON artifacts, remove the artifact's own hash field, serialize UTF-8 JSON with keys sorted and compact separators, then compute SHA-256. Record schema version, generator version, timestamp, input hashes, and superseded artifact hash when applicable.

Use relative POSIX paths rooted at the evaluation directory in state and manifests. Never store ephemeral absolute paths or make canonical identity depend on a Library ID. Register each artifact only after validation; update state last. Read [storage-and-checkpoints.md](storage-and-checkpoints.md).

## Web safety

The web report and item assessments should reference evidence IDs and short paraphrases. Keep exact quotations and long copyrighted passages in a restricted audit artifact when lawful, not in either public payload. Preserve candidate labels separately from any organizer blind key until scores are frozen.
