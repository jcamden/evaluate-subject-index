# Score-only migration from rubric V5 to V6

## Purpose

V6 changes only Page-reference Reliability arithmetic. A qualifying V5 evaluation may reuse its frozen evidence and produce a new calculation/result projection without repeating source discovery or candidate auditing. The migration is score-only: it never rewrites V5 history or changes a judgment.

## Qualification preflight

The migration accepts the original hash-bound calculation input plus immutable V5 calculation, result, item-assessment binding, and web-report artifacts. It validates those V5 projections under their historical schemas, then verifies that every frozen locator assignment explicitly and consistently provides:

- `judgment`;
- `treatment_class`;
- `source_scope_status`;
- `error_codes` and applicable structured defects; and
- an explicit `uninspectable` state where evidence is unavailable or ambiguous.

If a required field is missing or a combined state is contradictory, preflight returns one locator-specific `missing_requirements` record with the field/state errors. Migration stops. It does not read narrative rationales to guess a treatment class and does not reopen source pages automatically.

Preflight treats the frozen judgment as authoritative for the 1.00 and 0.50 tiers. `partially_supported` may coexist with substantive, mixed, passing-mention, attribution-only, citation-only, or incidental-example treatment, and diagnostic `SCP`, `CMP`, `CON`, or `STA` codes do not override a positive reliability judgment. Those codes remain frozen evidence for their existing dimensions, defects, caps, gates, and disclosures. For `unsupported` evidence, treatment class and applicable disqualifiers continue to distinguish limited 0.25 weak-presence credit from zero.

```bash
python evaluate-subject-index/scripts/dimension_score_v6_cli.py migration-preflight \
  --input /evaluation/dimension-calculation-input.json \
  --historical-calculation /evaluation/history/v5/dimension-calculations.json \
  --historical-result /evaluation/history/v5/evaluation-result.json \
  --historical-web-report /evaluation/history/v5/web-report.json \
  --output /evaluation/migrations/v5-to-v6-preflight.json
```

`sufficient: true` means only that the structured evidence is adequate for deterministic V6 arithmetic. It does not re-certify the editorial judgments.

## Preserved artifacts and facts

Migration byte-checks and preserves:

- source benchmark and candidate-blind discovery lineage;
- normalized candidate and representation-correction provenance;
- locator judgments and treatment classes;
- missing-access and expected-treatment judgments;
- structure judgments and defect ownership;
- publication-gate outcomes;
- the historical V5 calculation and result;
- V5 item-assessment identity; and
- immutable V5 web-report provenance.

The migration record stores the exact path, file SHA-256, canonical calculation identity, evidence identity, old/new scorecard, precision comparison, gate hash and arrays, frozen input lineage, and methodology commit.

Only active calculation-derived artifacts are invalidated: dimension calculations, evaluation result, item assessments, and web report. Upstream benchmark, preparation, audit, and gate evidence are not invalidated. Historical artifacts stay present under their V5 identities.

## Migration operation

```bash
python evaluate-subject-index/scripts/dimension_score_v6_cli.py score-only-migration \
  --input /evaluation/dimension-calculation-input.json \
  --historical-calculation /evaluation/history/v5/dimension-calculations.json \
  --historical-result /evaluation/history/v5/evaluation-result.json \
  --historical-web-report /evaluation/history/v5/web-report.json \
  --calculations-output /evaluation/calculations/dimension-calculations.v6.json \
  --migration-record-output /evaluation/migrations/v5-to-v6.json \
  --methodology-commit 0123456789abcdef0123456789abcdef01234567 \
  --migration-timestamp 2026-08-29T12:00:00Z
```

The operation derives `subject-index-dimension-calculations-v2`, verifies that historical and migrated strict substantive precision are equal, records the new weighted precision, copies gates identically, and writes `subject-index-score-migration-v5-to-v6-v1`. Output paths may not overwrite or alias any frozen input or historical artifact.

Upgrade the exact projection-safe V5 item artifact with the same locator and structure evidence, then build the result and web projections:

```bash
python evaluate-subject-index/scripts/item_grade_cli.py upgrade-v6-assessments \
  --item-assessments /evaluation/history/v5/item-assessments.v2.json \
  --locator-audit /evaluation/audits/locator-audit.*.json \
  --structure-audit /evaluation/audits/structure-audit.json \
  --output /evaluation/calculations/item-assessments.v3.json

python evaluate-subject-index/scripts/dimension_score_v6_cli.py build-projections \
  --calculation /evaluation/calculations/dimension-calculations.v6.json \
  --item-assessments /evaluation/calculations/item-assessments.v3.json \
  --metadata /evaluation/calculations/v6-projection-metadata.json \
  --migration-record /evaluation/migrations/v5-to-v6.json \
  --evaluation-result-output /evaluation/results/evaluation-result.v7.json \
  --web-report-output /evaluation/results/web-report.v5.json

python evaluate-subject-index/scripts/dimension_score_v6_cli.py validate-projections \
  --calculation /evaluation/calculations/dimension-calculations.v6.json \
  --evaluation-result /evaluation/results/evaluation-result.v7.json \
  --web-report /evaluation/results/web-report.v5.json
```

When immutable V5 history includes a representation-adjusted counterfactual, calculate its V6 view separately from the frozen adjusted input and add `counterfactual_score_views` to `subject-index-v6-projection-metadata-v1`. Each configured view supplies a unique ID and label, a complete V6 calculation reference, and at least one provenance-artifact reference with role, schema, relative path, and SHA-256. The projection builder resolves and hash-checks every referenced byte, derives the displayed score from the referenced calculation, preserves causal attribution `separate_evidentiary_correction_not_methodology_effect`, and rebases all paths into the web report. It never accepts a manually supplied score.

Projection validation reconstructs the scorecard and precision values, resolves and hash-verifies the V3 item artifact, checks every grade-25 explanation, and requires the web gate projection to equal the result and, for migrations, the immutable V5 gate array. It also resolves every score-view calculation and provenance artifact, verifies V6 calculation self-hashes and shared source/evaluation identities, and requires migrated counterfactual IDs plus all historical representation-provenance hashes to survive into V6. A nonexistent, altered, aliased-primary, cross-evaluation, or unproven counterfactual fails validation.

## Compatibility and interpretation

V4 and V5 schemas, calculators, migration support, and validators remain available. V5 totals and V6 totals are not directly comparable because Page-reference Reliability uses a different precision input. The migration comparison therefore presents old and new values side by side with explicit formula identities; it does not revise the historical V5 number.

Do not use this path for an audit whose locator ledger lacks the structured treatment/scope/disqualifier data. Complete the missing evidence through an authorized adjudication process instead of inferring it from prose. This methodology change does not authorize an Oxford migration or any candidate-specific calibration.
