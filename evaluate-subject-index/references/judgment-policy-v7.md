# Judgment policy — V7

Make judgments from source evidence and current structured contracts. Do not infer a score from rationale prose.

## Locator judgments

- `supported`: the complete path accurately identifies substantive relevant treatment.
- `partially_supported`: relevant treatment exists but the path or treatment is materially incomplete.
- `unsupported`: the destination does not substantively support the complete path.
- `uninspectable`: the evidence cannot be inspected; represent this as uncertainty.

Record treatment class, source scope, error codes, severity, evidence IDs, and any current structured defects consistently. Malformed, contradictory, or incomplete combinations fail validation.

## Missing access

Judge every expected benchmark treatment assigned to the chunk. Record whether it was found, missed, excluded by policy, or uninspectable. Full mode requires complete, non-overlapping denominator coverage.

## Structure

Numerical locator-string and range thresholds trigger review only. A defect requires structured evidence of conceptual distinctions, a useful alternative organization, and material retrieval harm. Prose may explain that decision but cannot substitute for the structured evidence.

## Independence

Benchmark construction remains candidate-blind. Worker artifacts are accepted through local validation and registration; Git history and checkpoint hashes are not evaluation evidence.
