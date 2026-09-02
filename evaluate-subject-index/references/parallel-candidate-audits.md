# Parallel candidate audits

Locator and missing-access audits can be divided among chats by frozen chunk ownership. Parallelism changes transport, not judgment rules or the state machine.

## Locator audits

Each chat receives the current checkpoint or equivalent evaluation files plus one locator packet. It returns one `locator-audit-v2` artifact covering every and only the packet's assignments.

Validate without mutation:

```bash
python scripts/parallel_candidate_audit_cli.py validate-audits \
  --audit-kind locator \
  --audit locator-audit.CHUNK-001.json \
  --locator-packet locator-packet.CHUNK-001.json \
  ...frozen-input-arguments...
```

Use `register-audits` with the same inputs to copy validated files to the canonical candidate audit directory and update the single state. Partial batches leave `locator_audit` in progress. Full frozen-chunk coverage completes it.

## Missing-access audits

Missing-access work starts only after locator auditing is complete. Each worker uses the frozen benchmark, normalized candidate and inventory, and complete registered locator-audit set. Source PDFs are not routine inputs.

Pass `--audit-kind missing_access`, the audit files being registered, and one `--locator-audit` for every frozen chunk. Completion requires exact coverage of owned subjects, reader tasks, and treatments.

## Recovery and collaboration

Create checkpoints at useful batch boundaries, especially before handing work to another chat or when network interruption is likely. A checkpoint is a resumable snapshot; it is not a proof object and no previous checkpoint checksum is required.

Workers may return files through attachments, shared storage, branches, or pull requests. Canonical registration requires valid current artifacts and exact chunk denominators. It does not require GitHub API snapshots, PR receipts, blob hashes, merge evidence, publication bindings, or recovery receipts.

## Safety

- Validate all selected files before mutating state.
- Do not assign a document page or judgment ID to multiple chunks.
- Do not publish restricted source or candidate material.
- Do not silently overwrite a different already-registered audit; resolve that content conflict explicitly.
- Keep checkpointing separate from registration so checkpoint failure cannot roll back accepted work.
