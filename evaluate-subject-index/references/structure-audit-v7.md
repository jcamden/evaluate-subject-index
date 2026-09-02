# Structure audit — V7

Native V7 structure audits use `structure-audit-v5`.

For each complete path, retain three distinct quantities:

- `displayed_locator_count`: one per delivered singleton or continuous range;
- inclusive span for each continuous range; and
- `atomic_assignment_count`: expanded page assignments used for support auditing.

Use displayed locators for locator-string review and atomic assignments for reliability work. Review is triggered by more than six displayed locators or a continuous range longer than ten pages. Exactly six and ten do not trigger.

A trigger is not a scored defect. A defect requires structured evidence that the entry combines conceptually distinct treatments, a useful subdivision or alternative access route exists, and the current presentation materially harms retrieval. The audit must preserve the display-to-atomic mapping, evidence IDs, review decision, and applicable defect IDs.

Current validation rejects missing range ownership, inconsistent counts, trigger-only defects, and triggered cases that are silently treated as pass or fail without review.
