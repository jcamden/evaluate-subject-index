# Built-in standard policy — V7

Use the current V7 schemas and commands only.

## Locator utility

Treat page treatment and complete-path fit as separate facts and use the lower score:

\[
L_j=\min(T_j,F_j),\qquad G_j=100L_j
\]

Treatment ceilings are 1.00 for substantive treatment, 0.70 for mixed treatment, 0.25 for weak presence, and zero for absence or an invalid destination. Fit ceilings are 1.00 exact, 0.70 partial, 0.35 minor mismatch, 0.15 major mismatch, and zero for no fit. Uninspectable locators enter neutral bounds. Required `not_measured` records block a full calculation.

Use only structured current-audit fields. Rationale and evidence prose may explain a decision but cannot produce a more favorable category or score. `LOC_POS` records a consequence and cannot establish a fit cause by itself. Malformed, incomplete, identity-inconsistent, or contradictory states fail validation.

Editorial Selectivity remains separate. Strict substantive precision remains public. Caps and gates remain independent.

## Locator strings and ranges

A delivered singleton or continuous range is one displayed locator. A range can own many atomic page assignments.

- Use displayed locators for locator-string and subdivision review.
- Use inclusive span for long-range review.
- Use atomic assignments for support auditing, precision, recall, and routing.

More than six displayed locators or a range longer than ten pages triggers review. The threshold alone is not a defect. A scored architecture problem requires structured evidence that the entry combines conceptually distinguishable treatments, a useful alternative organization exists, and the current form materially harms retrieval.

## Checkpoints and identity

Checkpoint archives are recovery snapshots. Resume requires safe structure and current state, not equality with an earlier checksum. Artifact hashes remain content labels that help detect accidental input mix-ups.
