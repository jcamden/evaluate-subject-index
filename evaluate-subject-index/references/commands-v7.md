# V7 scoring and migration commands

V7 uses `dimension_score_v7_cli.py` and `item_grade_v7_cli.py`. V4, V5, and V6 commands remain available only for artifacts under their historical identities.

## Sufficiency preflight

```bash
python evaluate-subject-index/scripts/dimension_score_v7_cli.py preflight \
  --input /path/to/dimension-calculation-input.json \
  --output /path/to/v7-preflight.json
```

Preflight assigns every frozen locator exactly once to `deterministically_compatible`, `unresolved_complete_path_fit`, or `invalid_or_contradictory_state`. It reports group counts and unresolved-reason counts, never reads rationale or evidence-summary prose, and exposes `aggregate_v7_score_available: false`. Ordinary bare `LOC_POS` uses `bare_loc_pos_without_fit_cause`; an eligible disagreement among individually valid legacy structured classifiers uses `legacy_structured_fit_classification_conflict_requires_adjudication` under `F-COMPAT-LEGACY-FIT-CONFLICT-TO-SUPPLEMENT-V1`. In tool patch `dimension-score-cli-v7.0.5`, that conflict record preserves a frozen `treatment_class: "absent"` unchanged when present. `unavailable` is not an unresolved treatment: its valid judgment contract is `uninspectable`, which follows the deterministic bounded route.

For ordinary unresolved states, preflight emits only public-safe structured locator/path IDs, reason codes, present judgment, treatment, scope, structured codes, applicable defect IDs, and `complete_path_fit_category` as the missing classifier. A conflict record additionally preserves each participating classifier's source-artifact role, stable record identity, structured basis, code/severity, and independently implied category/rule plus explicit no-prose/no-precedence/no-history-change declarations. It emits no source excerpt, rationale, candidate display text, private page evidence, credit, grade, dimension score, total, or aggregate score. Invalid identity, schema, assignment, artifact, or broader contradiction states remain outside the unresolved set and stop processing.

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
  --locator-audit /path/to/locator-audit.CHUNK-001.v2.json \
  --output /path/to/item-assessments.v7.json
```

Repeat `--locator-audit` once per chunk. The command verifies both self-hashes and all schemas, requires exact calculation/item evidence identity, and replaces locator grades with exactly `100 × combined_credit` while preserving locator-specific evidence and conditional fit rationale. It suppresses the old path-level reliability mean. If a historical structure penalty must be removed, use the migration command so the active structure and dependent item diagnostics are rebuilt together.

## Migrate V6 to V7

Create a schema-valid `subject-index-v6-to-v7-migration-input-v1` manifest containing exact hashes for the V6 calculation input, normalized candidate, item inventory, calculation, result, item assessments, web report, projection metadata, and every counterfactual view’s own inputs.

After a fail-closed `review_required` result has received an authorized narrow
architecture follow-up, add `supplemental_architecture_review` to the canonical
view and to every affected counterfactual view. The referenced artifact must
validate as `subject-index-v7-architecture-review-supplement-v1`; its sorted
decision paths must equal the mechanically unresolved trigger set exactly.
Omit the field when no supplemental decision is needed.

After an unsupplemented stop on unresolved complete-path fit, add `locator_fit_supplement` only to the affected canonical or counterfactual view. A new artifact must validate as `subject-index-v7-locator-fit-supplement-v2`; historical V1 inputs remain compatibility-readable. Its sorted decisions must equal the independently derived unresolved locator-ID set exactly. Each V2 decision supplies an existing fit category plus `public_safe_rationale` or a hash-bound validated rationale-ledger reference, never a numerical credit. For a conflict-routed locator, it resolves the prospective V7 fit axis without selecting a historically “correct” classifier or rewriting either record. A separately bound artifact is required for every counterfactual unless all relevant artifact identities independently validate as identical.

```bash
python evaluate-subject-index/scripts/dimension_score_v7_cli.py migrate-v6-to-v7 \
  --manifest /path/to/v7-migration-input.json \
  --output-directory /path/to/new-v7-projection
```

Use a new empty output directory. The migration refuses to overwrite outputs, alter history, infer range grouping from prose, copy a counterfactual score without recalculation, invent a new architecture judgment, or proceed with a required unmeasured/ambiguous locator.

The migration recalculates V6 from its original input, derives unsupplemented compatibility and the complete unresolved fit set, and only then reads a locator-fit supplement. A supplement therefore cannot rebind, repair, or replace frozen V6 evidence. Architecture and locator-fit supplements have separate contracts. Locator-fit file/self hashes and exact scope are carried into the calculation, item assessments, migration, result, web report, projection metadata, and validation receipt; historical inputs remain unchanged.

## Validate

Validate either historical or current V7 artifacts through the explicit version-dispatching reader:

```bash
python evaluate-subject-index/scripts/dimension_score_v7_cli.py validate-artifact \
  --artifact /path/to/v7-artifact.json
```

Then run the repository suite:

```bash
python -m py_compile evaluate-subject-index/scripts/*.py
python -m unittest discover -s evaluate-subject-index/tests -p 'test_*.py' -v
```

Also parse every JSON file, check all Draft 2020-12 schemas and local references, run repository link and leak checks, and repeat deterministic derivation/migration fixtures byte for byte. See [score-migration-v6-to-v7.md](score-migration-v6-to-v7.md) and [json-contracts-v7.md](json-contracts-v7.md).
