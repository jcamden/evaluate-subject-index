# Candidate preparation

Candidate preparation converts the delivered index into current structured artifacts without judging its quality or consulting benchmark subjects.

## Workflow

1. `extract` reads the authoritative candidate and records layout evidence.
2. `normalize` preserves every delivered hierarchy level and expands locator assignments through the frozen page map.
3. `validate-private` checks full fidelity and denominator accounting.
4. `register` validates the preparation again, records the final benchmark lock, copies no publication evidence, and advances `candidate_normalization` in `evaluation-state.json`.

The current contract uses `candidate-index-v2`, `subject-index-item-inventory-v2`, and evaluation state V5. Superseded preparation formats are not accepted.

## Separation from judgment

Preparation may identify extraction uncertainty, malformed layout, and unresolved locators. It must not repair the delivered hierarchy, classify source support, identify omissions, judge structure, or calculate scores. The benchmark is used at registration only to bind the completed preparation to the frozen evaluation, not as extraction evidence.

## Parallel and remote work

Preparation can happen in another chat or checkout. Return the validated preparation directory and register it locally. A branch or pull request is optional review infrastructure; GitHub evidence, worker receipts, recovery ZIPs, and merge proofs are not part of the canonical contract.

Use checkpoints before or after preparation when they are helpful for recovery. Resume does not depend on reproducing the previous checkpoint hash.
