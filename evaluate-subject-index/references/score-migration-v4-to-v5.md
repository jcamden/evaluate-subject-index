# Score-only migration from rubric V4 to V5

## Why V5 exists

V4 deterministically calculated density and weighted points, but it accepted five dimension ratings and the substantive-selectivity rating after an evaluator selected them from qualitative anchors. The supporting ledgers were traceable, but the final evidence-to-rating conversion was not mechanically reproducible.

V5 replaces that boundary with `subject-index-dimension-calculation-v1`. It derives all six ratings from raw ledger statuses, explicit denominators, fixed credit mappings and component weights, structured non-additive caps, uncertainty bounds, and decimal half-up rounding. Diagnostic item grades remain a separate display layer. Publication-readiness gates remain separate claim restrictions.

## What does not change

A score-profile change does not itself alter:

- the source, page-label map, chunks, or scope;
- candidate-blind discovery, benchmark synthesis, independent review, or frozen benchmark;
- candidate bytes, layout extraction, normalization, or inventory;
- locator, missing-access, structure, or item-assessment judgments; or
- gate policy, gate evidence, or gate outcomes.

The benchmark remains valid because it records what the source substantively treats and what readers need to find; it is not a score-conversion formula.

## Qualification preflight

Run:

```bash
python scripts/dimension_score_cli.py preflight \
  --input dimension-calculation-input.v1.json \
  --output v5-migration-sufficiency.json
```

The preflight hash-verifies every input and reports `sufficient` plus actionable missing requirements without changing any artifact. Because later ledger checks depend on earlier identity integrity, fix prerequisite failures and rerun until sufficient; once prerequisites pass, independent density and full-mode omissions are enumerated together. It requires the canonical user-approved, full-scope chunk manifest as a hash-bound input and requires its chunk IDs to match the locator, missing-access, and structure-density sets exactly; rejects mixed candidate, benchmark, policy, chunk-manifest, normalization, or inventory identities; binds the requested audit mode to frozen provenance; verifies canonical locator/missing-access set hashes; and rejects global or chapter count aggregates that contradict recomputable stable locator, path, or cross-reference IDs. A mutually consistent subset cannot substitute for the manifest's complete set. A full audit with any required `not_measured` item is not scoreable. Historical `structure-audit-v3` inputs require a separately reviewed `subject-index-v5-migration-supplement-v1`, bound to the exact structure audit, the audit-set hashes recorded by that historical ledger, and the canonical hashes recomputed over the exact same frozen audit files. The supplement's fixed reconciliation basis records the hash-algorithm transition; it cannot excuse different audit bytes. It also supplies any V5 severity, recurrence, optional-subject, node-applicability, cross-reference-applicability, or non-attempt provenance absent from the immutable V3 audit.

The supplement does not change the old audit. It makes existing judgments operationally explicit. A free-text rationale cannot trigger a cap, and the tool must not invent missing severity or recurrence evidence.

## Migration operation

After a sufficient preflight, run:

```bash
python scripts/dimension_score_cli.py score-only-migration \
  --input dimension-calculation-input.v1.json \
  --historical-result candidate/history/evaluation-result.v4.json \
  --calculations-output candidate/dimension-calculations.v1.json \
  --migration-record-output candidate/score-migration.v4-to-v5.json
```

The helper:

- validates an explicit historical `subject-index-rubric-v4` result against the retained V4 result schema and requires the same evaluation identity as the ledgers;
- verifies frozen input hashes before and after calculation;
- rejects resolved-path, symbolic-link, and hard-link output aliases, then produces a distinct V5 calculation artifact and migration record;
- proves that no input-ledger or historical-result byte changed;
- compares the historical candidate, source, benchmark, policy, page map, chunk manifest, normalized candidate, item inventory, structure audit, both audit sets, and audit mode to the supplied frozen evidence before it records unchanged gate outcomes; and
- records the historical-result and historical-gate hashes inside the calculation's canonical `migration_context`; and
- records that V4 and V5 totals are not directly comparable.

Do not overwrite the historical result or relabel it as V5. Build the V5 `subject-index-evaluation-result-v6` and `subject-index-web-report-v4` as new active artifacts, with links back to immutable history. The V6 result must hash-bind the emitted `subject-index-score-migration-v1` record and copy the historical `critical_gates` exactly. It must also hash-bind a `subject-index-item-assessments-v2` artifact whose five assessment families exactly exhaust the bound item inventory and expected source-subject set and whose evidence identity exactly matches the calculation. The web report must point to that same item-assessment file and reproduce the result's gate set and canonical gate hash. Run `validate-projections` against the calculation, result, and web report. Validation rejects incomplete, duplicated, or foreign item assessments, changed gates, substituted migration artifacts, and any result/web projection drift.

A public export is not automatically a migration checkpoint. If its structure audit binds a different locator-audit set from the supplied public locator files, preflight must fail even when the displayed aggregate metrics agree. Use a canonical private checkpoint whose hashes match; never waive the mismatch or reinterpret judgments to make a migration pass.

## Workflow invalidation

After the preflight succeeds, `state_cli.py set-score-calculation-profile --preflight ... --calculation-input ...` independently reruns the authoritative preflight and requires the supplied preflight JSON to match exactly. It also requires every supplied chunk manifest, locator audit, missing-access audit, structure audit, and migration supplement to resolve to the exact path and hash of a frozen, required artifact under its canonical completed stage in both evaluation state and artifact manifest. It verifies source, evaluation, and audit-mode identity, plus candidate identity when state carries it; a foreign ledger set with the same `evaluation_id` is rejected. It then adopts `subject-index-rubric-v5` plus `subject-index-dimension-calculation-v1`. It resets only the `scoring` and `web_report` stages, preserves every earlier stage, records both input hashes, and leaves historical artifacts in place but marks prior scoring/report registrations inactive for the new identity. Scoring can complete only after the exact adopted inputs are authoritatively recalculated and a schema-valid V6 result—bound to that already registered calculation and a projection-safe V2 item artifact—passes reconstruction and projection validation. Web reporting similarly requires the active validated result and matching V4 report.

## Calibration status

The V5 thresholds are approved normative safeguards, not empirically fitted targets. Synthetic adversarial tests and the published Oxford metric regression protect implementation behavior. A blind dry run on a materially different complete evaluation is required before describing the profile as empirically calibrated. Any later threshold change requires a new profile version.
