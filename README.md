# Evaluate Subject Index

[![Validate](https://github.com/JCamden/evaluate-subject-index/actions/workflows/validate.yml/badge.svg)](https://github.com/JCamden/evaluate-subject-index/actions/workflows/validate.yml)

An agent skill for repeatable, source-grounded evaluation of finished back-of-book subject indexes using a versioned standard policy.

It evaluates one index independently against its source and a frozen policy. Compatible results can then be displayed side by side without treating another index as the gold standard.

**Customer-facing explanation:** [How the Subject Index Evaluation Works](evaluate-subject-index/references/customer-methodology.md) describes the process, score, density calibration, publication-readiness checks, and detailed criteria in plain language. It also defines the four-layer presentation strategy for web reports: overall result, six quality questions, supporting evidence, and full methodology.

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

The workflow also produces a separate diagnostic grade for every measured locator, complete heading path, displayed main heading and subheading, cross-reference, and frozen source subject. These grades use semantic color tokens and structured hover/focus/touch popovers explaining the factors, weights or caps, confidence, and evidence behind the grade. They do not replace or add up to the publication-level score. See [`item-grading.md`](evaluate-subject-index/references/item-grading.md).

## Standard policy and density calibration

The skill infers likely readership from the publication and records the evidence and confidence. It asks the user only when the audience is genuinely ambiguous or differs from the book's apparent readership. Routine scope, substantive-treatment, entity/example, locator, heading, compound-heading, cross-reference, uncertainty, and shipping-gate rules are built in rather than recreated for every run.

Density is measured by chapter using two permissive calibration targets:

- **8 locator-bearing complete heading paths per 1,000 indexable source words**
- **20 expanded locator occurrences per 1,000 indexable source words**

Target bands are 6–10 paths and 15–25 occurrences; broad tolerance bands are 4–12 paths and 10–30 occurrences. These are this framework's calibration points—not quotas, minimums, universal professional requirements, or hard ceilings. Density contributes at most five of 100 points and never controls which subjects enter the frozen source benchmark.

See [`standard-policy.md`](evaluate-subject-index/references/standard-policy.md).

For a clear explanation suitable for customers, see [How the Subject Index Evaluation Works](evaluate-subject-index/references/customer-methodology.md). The exact scoring formulas and technical anchors remain in [`rubric.md`](evaluate-subject-index/references/rubric.md).

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
worker-discovery [chunk-id] --project [repository]
integrate-discoveries --project [repository] [pull-request-or-branch ...]
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

## Parallel source discovery

Source discovery can be distributed safely across independent chats:

- `worker-discovery CHUNK-003 --project owner/repository` resolves the compatible source and checkpoint, creates an isolated branch such as `source-discovery/chunk-003`, validates one candidate-blind chapter artifact, stores a branch-scoped recovery copy, and opens an unmerged pull request containing only that chapter JSON.
- `integrate-discoveries --project owner/repository <PRs...>` validates an explicit pull-request batch before merging any member, rejects shared-control or restricted files, integrates accepted chapter artifacts together, updates canonical state and manifest once, creates one cumulative checkpoint, and only then advances downstream benchmark locks.

Parallel workers never edit canonical `evaluation-state.json`, `artifact-manifest.json`, cumulative checkpoints, or candidate-evaluation locks. See [`commands.md`](evaluate-subject-index/references/commands.md) and [`workflow.md`](evaluate-subject-index/references/workflow.md).

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

The state manager, standard-policy builder, checkpoint/export/import tooling, page-map expansion, chunk validation, locator routing, stable item inventory, diagnostic item grading, chapter-level density calculation, and scoring arithmetic otherwise use the Python standard library.

Install the PDF dependency with:

```bash
python -m pip install -r requirements.txt
```

## Validation

The included workflow checks JSON parsing, Python syntax, page-map expansion, chunk validation, candidate-locator routing, stable item identities, granular grades and popovers, rubric arithmetic, artifact registration, portable checkpoint creation, and safe resume.

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

python evaluate-subject-index/scripts/item_grade_cli.py build-inventory \
  --candidate evaluate-subject-index/tests/candidate-index.valid.json \
  --output /tmp/item-inventory.json

python evaluate-subject-index/scripts/item_grade_cli.py build-assessments \
  --candidate evaluate-subject-index/tests/candidate-index.valid.json \
  --inventory /tmp/item-inventory.json \
  --locator-audit evaluate-subject-index/tests/locator-audit.item-grading.valid.json \
  --missing-access-audit evaluate-subject-index/tests/missing-access-audit.item-grading.valid.json \
  --structure-audit evaluate-subject-index/tests/structure-audit.item-grading.valid.json \
  --audit-mode full \
  --output /tmp/item-assessments.json
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
