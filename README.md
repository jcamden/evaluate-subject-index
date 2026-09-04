# Evaluate Subject Index

A source-grounded, current-V7 workflow for evaluating a finished subject index.

The repository separates four questions:

1. What subjects and reader tasks does the source require?
2. Are the candidate's paths and locators supported by the cited pages?
3. Can readers reach every required subject?
4. Does the whole index form a coherent navigation system?

Validated ledgers feed deterministic V7 scoring and report projection.

## Setup

```bash
python -m pip install -r requirements.txt
```

## Current workflow

The canonical run is `evaluation-state.json` (state schema V5). It is the only control inventory; there is no artifact manifest.

```text
initialize → page map → chunks → policy
  → source discovery → benchmark synthesis/review/freeze
  → candidate normalization → locator packets
  → locator audit → missing-access audit → structure audit
  → V7 scoring → web report
```

Important helpers:

- `state_cli.py` — initialize, validate, inspect, and advance state.
- `bundle_cli.py` — optional recovery checkpoints and imports.
- `candidate_preparation_cli.py` — normalize, validate, and register a contract-valid candidate.
- `parallel_candidate_audit_cli.py` — validate/register audit chunks returned by separate chats.
- `dimension_score_v7_cli.py` — current V7 preflight, structure review, and calculation.
- `item_grade_v7_cli.py` — current V7 item projection.

See [SKILL.md](evaluate-subject-index/SKILL.md) and [workflow.md](evaluate-subject-index/references/workflow.md) for the operating contract.

## Optional input converter

The evaluation skill is format-agnostic. Its input boundary is the published [`candidate-layout-extraction-v1` schema](evaluate-subject-index/references/schemas/candidate-layout-extraction.schema.json).

[`subject_index_converter.py`](utilities/subject_index_converter.py) is a separate convenience utility for the PDF, Markdown, plain-text, and Indexia HTML exports currently in use. It emits that contract without making those formats part of the skill:

```bash
python utilities/subject_index_converter.py \
  --candidate-id example \
  --input /path/to/index.pdf \
  --output /path/to/candidate-layout-extraction.v1.json

python utilities/subject_index_converter.py \
  --candidate-id example \
  --url https://www.indexia.tech/public/example \
  --snapshot /path/to/indexia-snapshot.html \
  --output /path/to/candidate-layout-extraction.v1.json
```

The converter snapshots URL input so the JSON hash remains tied to exact bytes. It performs mechanical extraction only; evaluation and editorial judgment remain in the skill.

## Checkpoints

Checkpoints are recovery snapshots, not integrity proofs or mandatory stage gates.

```bash
python evaluate-subject-index/scripts/bundle_cli.py checkpoint \
  --state /path/to/evaluation/evaluation-state.json \
  --output /path/to/checkpoint.zip

python evaluate-subject-index/scripts/bundle_cli.py import-bundle \
  --input /path/to/checkpoint.zip \
  --output-dir /path/to/resumed-evaluation
```

Import validates archive safety, inventory, and current state structure. It does not require a previously advertised archive or member checksum. Registered artifact hashes remain useful content identities, but changed or unavailable local bytes are resume warnings rather than tamper failures.

## Parallel chats

Chunk workers return current-schema JSON artifacts. The coordinator validates and registers selected files directly in state. Branches and pull requests are optional review/transport tools; GitHub receipts, blob proofs, merge evidence, recovery receipts, and matching checkpoint hashes are not required.

## Compatibility policy

Only the current V7 workflow is exposed. Historical V4–V6 migration commands and compatibility tests have been removed. Broad schema consolidation is intentionally deferred while a TypeScript migration is evaluated.

## Test

```bash
python -m unittest discover -s evaluate-subject-index/tests -p 'test_*.py' -v
python -m unittest discover -s utilities/tests -p 'test_*.py' -v
```

The GitHub workflow parses schemas and fixtures, compiles helpers, and runs the unit suite without duplicating those tests in long inline shell scripts.

## License

Copyright (c) 2026 John Camden.

This project is licensed under the GNU Affero General Public License, version 3 only (`AGPL-3.0-only`). See [LICENSE](LICENSE). Third-party components remain subject to their own licenses; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

PyMuPDF and MuPDF are available under the GNU AGPL v3 or a separate commercial license from Artifex. This repository uses them under the GNU AGPL v3 and does not grant an Artifex commercial license.
