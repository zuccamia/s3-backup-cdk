# S3 Object Backup System (AWS CDK)

Event-driven object backup: every object put into a **Src** S3 bucket is
replicated into a **Dst** bucket (retaining the latest 3 copies per key),
and every deletion in Src is asynchronously reflected in Dst by a
scheduled Cleaner lambda after a 10s grace period. Every copy is tracked
in a DynamoDB table (Table T) so the flow requires no scans.

## Architecture

```
    PUT/DELETE on Src                        Schedule (1 min)
     (via EventBridge)                        (via EventBridge)
            │                                       │
            ▼                                       ▼
 ┌─────────────────────┐               ┌─────────────────────┐
 │   ReplicatorStack   │               │     CleanerStack    │
 │     Replicator λ    │               │       Cleaner λ     │
 └──────────┬──────────┘               └──────────┬──────────┘
            │                                     │
            │  read Src / copy+del Dst /          │  query GSI /
            │  put+update Table T                 │  del Dst / del Table T
            │                                     │
            ▼                                     ▼
 ┌───────────────────────────────────────────────────────────┐
 │                        DataStack                          │
 │   Src bucket   Dst bucket   Table T + DeletedIndex GSI    │
 └───────────────────────────────────────────────────────────┘
```

**Flow:**
- **PUT on Src** → EventBridge → Replicator → `CopyObject` to Dst,
  `PutItem` in Table T, evict oldest via `Query(base, PK=OriginalKey)` +
  `DeleteObject` + `DeleteItem` if count > 3.
- **DELETE on Src** → EventBridge → Replicator → `Query(base,
  PK=OriginalKey)` → `UpdateItem` on each row to set `DeletedAt` +
  `DeletedFlag="DELETED"`. S3 copies are left in Dst.
- **Every 1 min** → EventBridge → Cleaner → `Query(GSI DeletedIndex,
  DeletedFlag="DELETED" AND DeletedAt < now-10s)` → per hit,
  `DeleteObject` in Dst then `DeleteItem` in Table T.

## Table T schema

**Base table** — `(OriginalKey, CreatedAt)` composite primary key. Every
copy is its own row; rows sharing the same `OriginalKey` represent the
current set of copies of a single Src object.

| Attribute     | Type | Role                                          | Present when             |
|---------------|------|-----------------------------------------------|--------------------------|
| `OriginalKey` | S    | Partition key — the Src object name           | always                   |
| `CreatedAt`   | N    | Sort key — epoch ms when the copy was made    | always                   |
| `CopyKey`     | S    | Name of the copy in Dst                       | always                   |
| `DeletedAt`   | N    | Epoch ms when the original was deleted in Src | only after DELETE event  |
| `DeletedFlag` | S    | Constant `"DELETED"` — sparse-GSI partition   | only after DELETE event  |

**Sparse GSI `DeletedIndex`** — projection `ALL`. Only rows with
`DeletedFlag` set appear in the index, so the Cleaner queries disowned
copies without scanning the table.

| Attribute     | Role                                                                |
|---------------|---------------------------------------------------------------------|
| `DeletedFlag` | GSI partition key (constant `"DELETED"` — sparse)                   |
| `DeletedAt`   | GSI sort key — lets Cleaner range-query `DeletedAt < now-grace`     |

All three access patterns (Replicator PUT count, Replicator DELETE
marking, Cleaner sweep) are `Query`, never `Scan`.

## Prerequisites

- Python 3.9+
- Node.js (for the CDK CLI, invoked via `npx`)
- AWS credentials configured (`aws configure` or env vars)

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Running local tests

Dev-only dependencies (pytest + moto for in-process AWS mocks) live in a
separate file so the runtime deploy stays lean:

```bash
pip install -r requirements-dev.txt
pytest
```

The suite covers Replicator/Cleaner handler business logic against
mocked S3 + DynamoDB, and CDK synth-time assertions on all three
stacks. It requires no AWS credentials and runs in a few seconds.

## One-time per account/region

```bash
npx aws-cdk bootstrap
```

## Preview

Optional — synthesize the CloudFormation templates to `cdk.out/` without
deploying, to eyeball what CDK will submit:

```bash
npx aws-cdk synth
```

## Deploy

The app defines three stacks (`DataStack`, `ReplicatorStack`,
`CleanerStack`). Deploy them all with:

```bash
npx aws-cdk deploy --all
```

`--all` is required because `cdk deploy` defaults to failing when
multiple stacks are present. CDK resolves the linear dependency chain
(Data → Replicator, Data → Cleaner) automatically. Cross-stack
references (bucket names, table name, GSI name) are wired through
CloudFormation exports.

Stack outputs (bucket names, table name, GSI name) are printed at the
end of the deploy and are also visible in the CloudFormation console.

## Testing

After `cdk deploy --all`, grab the bucket and table names from the
outputs and:

```bash
# 1. Upload — expect a copy in Dst and a row in Table T
aws s3 cp hello.txt s3://<SRC_BUCKET>/hello.txt
aws s3 ls  s3://<DST_BUCKET>/
aws dynamodb query --table-name <TABLE> \
  --key-condition-expression "OriginalKey = :k" \
  --expression-attribute-values '{":k":{"S":"hello.txt"}}'

# 2. Upload again 4 more times — expect at most 3 copies in Dst and 3 rows
for i in 1 2 3 4; do aws s3 cp hello.txt s3://<SRC_BUCKET>/hello.txt; sleep 1; done

# 3. Delete from Src — rows get marked (DeletedAt/DeletedFlag), copies remain
aws s3 rm s3://<SRC_BUCKET>/hello.txt

# 4. Wait ~70s (10s grace + up to 60s until next Cleaner tick) — Dst empties
aws s3 ls  s3://<DST_BUCKET>/
aws dynamodb scan --table-name <TABLE> --select COUNT
```

## Design decisions

### One row per copy (PutItem), not one row per original (UpdateItem list)

Table T stores **one row per copy**, so a `Query(PK=OriginalKey)` returns
the full set of copies sorted by `CreatedAt`. Evicting the oldest is
`items[0]` — no list manipulation. The sparse GSI works naturally
because each disowned copy is its own indexed entry.

The alternative — one row per original with a list of `CopyKey` values
updated via `UpdateItem` — would require load-modify-write on the list
(racier under concurrent PUTs) and awkward GSI modeling (DDB can't index
list elements cleanly).

The spec uses the word "updated" ("Table T needs to be updated to
reflect the mapping"). This is used **semantically** — Table T's state
must reflect the new mapping. In our design that's satisfied by adding a
new row via `PutItem`; we do not literally invoke `UpdateItem` on the
PUT path.

### Hard delete in Cleaner (DeleteItem), not soft delete

The Cleaner uses `DeleteItem` on each disowned row after removing the
S3 copy. Soft-delete alternatives (clearing `DeletedFlag`, setting a
`"CLEANED"` sentinel, or leaning on DDB TTL) were rejected because:

- **Replicator's ≤3-copy count runs against the base table**, not the
  GSI. Any zombie row from a soft delete would inflate that count and
  break the eviction cap unless every base-table query grew a
  `FilterExpression`.
- **The spec has no audit requirement** — we aren't asked to preserve
  history of cleaned copies.
- **TTL fires within 48 hours** — completely wrong granularity for a 10s
  grace period, and it only removes the DDB row (not the S3 object).

Hard delete keeps the base table and the sparse GSI in sync with zero
application logic.

### Ordering: S3 first, DDB second (Cleaner)

If the Cleaner crashes between the two writes, the row stays disowned
and the next run reprocesses it. S3 `DeleteObject` is idempotent, so
re-deleting is a no-op. The reverse ordering would risk orphaning copies
in Dst with no row pointing at them.

## Known limitations

1. **Replicator PUT count race.** The "put new row then check if count >
   3" pattern is not atomic. Two concurrent PUTs on the same
   `OriginalKey` can both add and both evict, potentially leaving 4
   copies for one turn. Mitigation would require a conditional write or
   a monotonic version counter — not implemented.

2. **`CreatedAt` millisecond collision.** The SK is `epoch_ms` (Number).
   Two PUTs of the same key in the same millisecond produce identical
   `(OriginalKey, CreatedAt)` pairs, and the second `PutItem` silently
   overwrites the first. Mitigation would be to change the SK to a
   String like `f"{ts_ms}#{uuid4()}"`, or to add a
   `ConditionExpression="attribute_not_exists(CreatedAt)"` retry loop.

3. **Cleaner partial failure.** If the Cleaner crashes between S3 delete
   and DDB delete, the row is reprocessed next tick. Safe because S3
   delete is idempotent; ordering is chosen to avoid orphans (see above).

4. **Overlapping Cleaner runs.** If a single Cleaner invocation takes
   longer than 60s, the next scheduled invocation overlaps. Both may
   target the same rows; S3 delete is idempotent and `DeleteItem` on a
   missing key is a silent no-op in DynamoDB, so the overlap is safe.

## Future considerations

### Audit / history of deleted copies

The current design hard-deletes rows once the Cleaner processes them, so
no record of a copy survives past the 10s grace period. If the
requirement later grows to include an audit trail — "which copies of
which originals existed, when were they created, when were they
cleaned?" — the cleanest extensions are:

- **Repartition on the GSI.** Change the Cleaner to
  `UpdateItem(SET DeletedFlag = "CLEANED", CleanedAt = now)` instead of
  `DeleteItem`. The row falls out of the `"DELETED"` GSI partition
  (Cleaner query still returns nothing stale), the base table retains
  the row indefinitely, and a separate `Query(GSI, DeletedFlag="CLEANED")`
  becomes an audit view. Trade-off: base-table growth is unbounded, and
  Replicator's `Query(PK=OriginalKey)` for the ≤3-copy count would need
  a `FilterExpression="attribute_not_exists(CleanedAt)"` to ignore
  audit rows.

- **Separate audit table.** Keep Table T hard-deleting as today, and
  `PutItem` an entry into a second table (e.g. `Table T_Audit`) right
  before the Cleaner's `DeleteItem`. Isolates read/write patterns:
  Replicator and Cleaner never scan the audit table, and Table T stays
  small. Trade-off: an extra write per cleaned copy and one more
  resource to provision.

Either option requires more storage and slightly more careful ordering,
but neither changes the S3-first-then-DDB failure semantics.

## Teardown

```bash
npx aws-cdk destroy --all
```

Both buckets are created with `auto_delete_objects=True` and
`removal_policy=DESTROY`, so `cdk destroy` fully cleans up all
resources including any objects left in Src/Dst.

## Layout

```
app.py                             # wires the three stacks
stacks/
  data_stack.py                    # Src + Dst buckets, Table T, DeletedIndex GSI
  replicator_stack.py              # Replicator λ + EventBridge S3 rule
  cleaner_stack.py                 # Cleaner λ + EventBridge schedule
lambdas/
  replicator/handler.py            # PUT: copy + cap at 3. DELETE: mark disowned.
  cleaner/handler.py               # Query GSI, delete S3 then row.
requirements.txt                   # aws-cdk-lib, constructs
cdk.json                           # CDK config + feature flags
```

The lambda handlers only depend on `boto3`, which is bundled in the
AWS Lambda Python runtime, so no packaging or Docker bundling is
required at deploy time.
