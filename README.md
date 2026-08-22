# Evaluate Subject Index

[![Validate](https://github.com/JCamden/evaluate-subject-index/actions/workflows/validate.yml/badge.svg)](https://github.com/JCamden/evaluate-subject-index/actions/workflows/validate.yml)

An agent skill for repeatable, source-grounded evaluation of finished back-of-book subject indexes using a versioned standard policy.

It evaluates one index independently against its source and a frozen policy. Compatible results can then be displayed side by side without treating another index as the gold standard.

## What it does

The workflow separates three questions that should not be conflated:

1. **What does the source substantively treat?** Build and freeze a candidate-blind source-subject benchmark.
2. **Are the candidate's headings and locators legitimate?** Audit every expanded locator assignment against the relevant source page.
3. **Does the complete index work as a navigation system?** Audit missing access, hierarchy, terminology, cross-references, organization, density, and mechanics.

The score uses six dimensions totaling 100 points:

| Dimension | Weight |
| --- | ---: |
| Meaningful coverage | 20 |
| Editorial selectivity, including density fit | 15 |
| Conceptual and stance fidelity | 15 |
| Page-reference reliability | 25 |
| Findability and navigation | 20 |
| Mechanics and consistency | 5 |

## Standard policy and density calibration

The skill infers likely readership from the publication and records the evidence and confidence. It asks the user only when the audience is genuinely ambiguous or differs from the book's apparent readership. Routine scope, substantive-treatment, entity/example, locator, heading, compound-heading, cross-reference, uncertainty, and shipping-gate rules are built in rather than recreated for every run.

Density is measured by chapter using two permissive calibration targets:

- **8 locator-bearing complete heading paths per 1,000 indexable source words**
- **20 expanded locator occurrences per 1,000 indexable source words**

Target bands are 6–10 paths and 15–25 occurrences; broad tolerance bands are 4–12 paths and 10–30 occurrences. These are this framework's calibration points—not quotas, minimums, universal professional requirements, or hard ceilings. Density contributes at most five of 100 points and never controls which subjects enter the frozen source benchmark.

See [`standard-policy.md`](evaluate-subject-index/references/standard-policy.md).

## Page labels and chunks

The workflow distinguishes:

- **Document pages:** one-based integer ordinals in the supplied PDF.
- **Source page labels:** strings used by the book and index, including `"12"`, `"xiv"`, `"A-12"`, or `"Plate 3"`.
- **Chunk-PDF pages:** local page ordinals in a derived source chunk, mapped back through a sidecar file.

Users supply or approve document-page ranges. Compact sequential or explicit label specifications expand into a canonical one-record-per-document-page map. Candidate locator assignments are then routed into minimal per-chunk packets containing only the complete heading paths and locators that must be audited for that chunk.

See [`page-mapping-and-chunks.md`](evaluate-subject-index/references/page-mapping-and-chunks.md) for the formats.

## Commands

Invoke the skill with `@evaluate-subject-index help` and use its command vocabulary:

```text
initialize
map-pages
define-chunks
define-policy
prepare-source-chunks
discover-source-subjects [chunk-id]
freeze-source-benchmark
normalize-index
prepare-locator-chunks
audit-locators [chunk-id]
audit-missing-access [chunk-id]
audit-index-structure
score-index
build-web-report
checkpoint
export-bundle
import-bundle
validate
status
next
```

`status` reports completed and blocked stages. `next` returns the earliest dependency-satisfied command, required inputs, and completion test. `define-policy` instantiates the standard policy with source-specific hashes, availability facts, and any documented deviations; it does not ask the user to invent policy.

## Storage and checkpoints

Required outputs are never left only in chat text or a temporary workspace. Each study uses portable relative paths, `evaluation-state.json`, and `artifact-manifest.json`; every registered artifact carries a hash, visibility, retention class, and frozen status.

Three storage modes are supported:

- `local`: local evaluation directory plus checkpoints before handoff.
- `library`: active study folder in ChatGPT Library plus milestone checkpoints.
- `hybrid`: local directory, Library persistence when available, and portable checkpoints. This is the recommended ChatGPT mode.

Portable ZIPs include public/private JSON evidence while excluding restricted source and candidate files. Private-complete ZIPs may include restricted inputs when explicitly requested. Safe imports reject traversal, absolute paths, duplicate members, and symlinks, then verify hashes before resume.

See [`storage-and-checkpoints.md`](evaluate-subject-index/references/storage-and-checkpoints.md).

## Repository layout

The installable skill package is in [`evaluate-subject-index/`](evaluate-subject-index/):

```text
evaluate-subject-index/
├── SKILL.md
├── agents/
├── assets/
├── references/
│   └── schemas/
├── scripts/
└── tests/
```

OpenAI's documentation describes a skill as a directory containing `SKILL.md` plus optional scripts, references, assets, and agent metadata. Standalone skill availability depends on the OpenAI product and environment; broader distribution can use a plugin package. See [Build skills](https://learn.chatgpt.com/docs/build-skills).

## Requirements

- Python 3.10 or newer
- [`pypdf`](https://pypi.org/project/pypdf/) for physically splitting source PDFs

The state manager, standard-policy builder, checkpoint/export/import tooling, page-map expansion, chunk validation, locator routing, chapter-level density calculation, and scoring arithmetic otherwise use the Python standard library.

Install the PDF dependency with:

```bash
python -m pip install -r requirements.txt
```

## Validation

The included workflow checks JSON parsing, Python syntax, page-map expansion, chunk validation, candidate-locator routing, rubric arithmetic, artifact registration, portable checkpoint creation, and safe resume.

Run the deterministic smoke tests locally:

```bash
python evaluate-subject-index/scripts/page_chunk_cli.py expand-page-map \
  --input evaluate-subject-index/tests/page-map-input.valid.json \
  --output /tmp/page-map.json

python evaluate-subject-index/scripts/page_chunk_cli.py validate-chunks \
  --input evaluate-subject-index/tests/chunk-manifest.input.json \
  --page-map /tmp/page-map.json \
  --output /tmp/chunk-manifest.json

python evaluate-subject-index/scripts/page_chunk_cli.py filter-candidate \
  --candidate evaluate-subject-index/tests/candidate-index.valid.json \
  --page-map /tmp/page-map.json \
  --chunks /tmp/chunk-manifest.json \
  --output-dir /tmp/locator-packets

python evaluate-subject-index/scripts/score_cli.py scorecard \
  --input evaluate-subject-index/tests/scorecard.valid.json

python evaluate-subject-index/scripts/policy_cli.py build \
  --input evaluate-subject-index/tests/policy-build-input.valid.json \
  --output /tmp/evaluation-policy.json

python evaluate-subject-index/scripts/score_cli.py density-profile \
  --input evaluate-subject-index/tests/density-chapters.valid.json \
  --output /tmp/density-profile.json
```

## Audit integrity

- Build the source benchmark before inspecting a candidate index.
- Instantiate and freeze standard policy v1, page mapping, chunk ownership, source-specific scope, density calibration, reader tasks, and uncertainty treatment before candidate scoring.
- Use both index-to-source and source-to-index audits; locator precision alone cannot reveal omissions.
- Preserve original candidate output and record every normalization.
- Compare evaluations only when their source, benchmark, rubric, mapping, scope, and audit-design identifiers match.
- Publish denominators, gates, evidence, limitations, and representative strengths as well as defects.

No copyrighted source books, candidate indexes, or evaluation results are included in this repository.

## License

MIT. See [`LICENSE`](LICENSE).
