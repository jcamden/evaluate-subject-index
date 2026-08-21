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
| Policy | `evaluation-policy.schema.json` | Frozen scope, audit, uncertainty, gates, and density rules |
| Source chunk | `source-subject-chunk.schema.json` | Candidate-blind chapter/page discoveries |
| Benchmark | `source-benchmark.schema.json` | Frozen whole-source subject graph and evidence denominator |
| Normalized candidate | `candidate-index.schema.json` | Complete paths, references, and expanded locator assignments |
| Candidate locator chunk | `candidate-locator-chunk.schema.json` | Only paths and assignments owned by one audit chunk |
| Locator batch | `locator-audit.schema.json` | One judgment for every expanded candidate locator |
| Missing-access batch | `missing-access-audit.schema.json` | Source-to-index concept coverage and locator recall |
| Structure audit | `structure-audit.schema.json` | Global hierarchy, navigation, cross-reference, mechanics, and density evidence |
| Evaluation result | `evaluation-result.schema.json` | Auditable scores, metrics, gates, and comparison key |
| Web report | `web-report.schema.json` | Display-ready narrative and evidence cards |

## Stable identifiers

Use opaque IDs rather than mutable labels:

- `SUBJ-*` for benchmark subjects;
- `PATH-*` for complete candidate heading paths;
- `LOC-*` for expanded locator assignments;
- `CHUNK-*` for page ownership units;
- `TASK-*` for reader tasks; and
- `DEFECT-*` for underlying defects.

## Null and missing data

Use explicit measurement states such as `measured`, `not_measured`, `uninspectable`, and `not_applicable`. Do not encode unknown values as zero. Rates contain numerator, denominator, value, and excluded counts.

## Canonical hashes

For frozen JSON artifacts, remove the artifact's own hash field, serialize UTF-8 JSON with keys sorted and compact separators, then compute SHA-256. Record schema version, generator version, timestamp, input hashes, and superseded artifact hash when applicable.

Use relative POSIX paths rooted at the evaluation directory in state and manifests. Never store ephemeral absolute paths or make canonical identity depend on a Library ID. Register each artifact only after validation; update state last. Read [storage-and-checkpoints.md](storage-and-checkpoints.md).

## Web safety

The web report should reference evidence IDs and short paraphrases. Keep long copyrighted passages in a restricted audit artifact when lawful, not in the public payload. Preserve candidate labels separately from any organizer blind key until scores are frozen.
