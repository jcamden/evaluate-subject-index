# Storage, checkpoints, and resume

## Authority

`evaluation-state.json` is the canonical control file. It records stage status and the artifact inventory. There is no separate artifact manifest.

Registered hashes are useful content identities for connecting records. They are not intended to prove that files were never altered. Validation therefore warns when registered files are unavailable or have changed, while structural errors and invalid stage ordering still fail.

## Suggested layout

```text
evaluation/
├── evaluation-state.json
├── source/
├── benchmark/
├── candidate/
├── validation/
└── reports/
```

All registered paths are relative to the evaluation directory. Restricted source and candidate material stays private. Portable exports omit restricted artifacts by default.

## When to checkpoint

Checkpoint when it reduces the cost of interruption—for example after benchmark freeze, candidate registration, a batch of audit chunks, scoring, or before moving work to another chat. It is optional and does not advance a stage.

```bash
python scripts/bundle_cli.py checkpoint \
  --state /path/to/evaluation/evaluation-state.json \
  --output /path/to/evaluation/checkpoint.zip
```

The checkpoint contains the current state and accessible registered artifacts. Creating a new checkpoint does not require presenting the hash of a previous one.

## Import and resume

```bash
python scripts/bundle_cli.py import-bundle \
  --input /path/to/checkpoint.zip \
  --output-dir /path/to/resumed-evaluation
```

Import rejects unsafe member paths, duplicates, links, malformed inventory, and a structurally invalid current state. It does not require the archive or each member to match a previously advertised checksum. Existing output files are not silently overwritten.

After import:

1. Run `state_cli.py validate`.
2. Review warnings for unavailable or changed artifacts.
3. Reconnect any restricted source or candidate input needed by the next operation.
4. Run `state_cli.py next` and continue.

An attachment, Library item, branch, or network transfer is simply a delivery route. Network failure is a reason to use another copy, not to abandon otherwise valid recoverable state.

## Concurrency

All cooperative writers use `.evaluation.lock` and atomically replace `evaluation-state.json`. An operation validates its complete selected batch before writing artifacts or state. Checkpoint creation is separate from state mutation, so an interrupted checkpoint does not invalidate the canonical run.
