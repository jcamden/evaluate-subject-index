# V7 scoring and migration commands

V7 uses `dimension_score_v7_cli.py` and `item_grade_v7_cli.py`. V4, V5, and V6 commands remain available only for artifacts under their historical identities.

## Sufficiency preflight

```bash
python evaluate-subject-index/scripts/dimension_score_v7_cli.py preflight \
  --input /path/to/dimension-calculation-input.json \
  --output /path/to/v7-preflight.json
```

Preflight requires an unambiguous structured treatment and fit mapping for every locator. It reports missing/contradictory fields and never reads rationale or evidence-summary prose.

## Derive structure-locator review

```bash
python evaluate-subject-index/scripts/dimension_score_v7_cli.py derive-structure-review \
  --normalized-candidate /path/to/candidate-index.v2.json \
  --item-inventory /path/to/item-inventory.v2.json \
  --structure-audit /path/to/structure-audit.json \
  --audit-mode full \
  --output /path/to/structure-locator-review.v7.json
```

The command binds exact input hashes and derives display counts, range spans, atomic counts, triggers, and dispositions. `migration_ready: false` means grouping failed or a triggered path still needs a supplemental architecture review.

## Calculate V7

```bash
python evaluate-subject-index/scripts/dimension_score_v7_cli.py calculate \
  --input /path/to/dimension-calculation-input.json \
  --structure-locator-review /path/to/structure-locator-review.v7.json \
  --output /path/to/dimension-calculations.v7.json
```

The calculation uses the review only for a deterministic active structure correction. It calculates Page-reference Reliability from `combined_credit`, never from diagnostic grades.

## Build V7 item projections

For a native V7 evaluation, first build the unchanged V6-compatible item-evidence projection with `item_grade_cli.py`, then replace only the V7 locator/display layer:

```bash
python evaluate-subject-index/scripts/item_grade_v7_cli.py build-assessments \
  --v6-compatible-items /path/to/item-assessments.v6-compatible.json \
  --calculation /path/to/dimension-calculations.v7.json \
  --structure-locator-review /path/to/structure-locator-review.v7.json \
  --output /path/to/item-assessments.v7.json
```

The command verifies both self-hashes and all schemas, requires exact calculation/item evidence identity, and replaces locator grades with exactly `100 × combined_credit`. It suppresses the old path-level reliability mean. If a historical structure penalty must be removed, use the migration command so the active structure and dependent item diagnostics are rebuilt together.

## Migrate V6 to V7

Create a schema-valid `subject-index-v6-to-v7-migration-input-v1` manifest containing exact hashes for the V6 calculation input, normalized candidate, item inventory, calculation, result, item assessments, web report, projection metadata, and every counterfactual view’s own inputs.

```bash
python evaluate-subject-index/scripts/dimension_score_v7_cli.py migrate-v6-to-v7 \
  --manifest /path/to/v7-migration-input.json \
  --output-directory /path/to/new-v7-projection
```

Use a new empty output directory. The migration refuses to overwrite outputs, alter history, infer range grouping from prose, copy a counterfactual score without recalculation, invent a new architecture judgment, or proceed with a required unmeasured/ambiguous locator.

## Validate

```bash
python -m py_compile evaluate-subject-index/scripts/*.py
python -m unittest discover -s evaluate-subject-index/tests -p 'test_*.py' -v
```

Also parse every JSON file, check all Draft 2020-12 schemas and local references, run repository link and leak checks, and repeat deterministic derivation/migration fixtures byte for byte. See [score-migration-v6-to-v7.md](score-migration-v6-to-v7.md) and [json-contracts-v7.md](json-contracts-v7.md).
