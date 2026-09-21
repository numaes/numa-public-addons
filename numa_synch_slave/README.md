# Numa Synch Slave — the branch node

**Odoo 20.0** | LGPL-3 | NUMA Extreme Systems

**Status: migrated to Odoo 20.0** (module version `20.0.1.0.0`). Before the migration it
**did not install**, and what it sent went well past what it was configured to send:
see [What was found](#what-was-found-before-migrating).

Turns an Odoo instance into a branch node. On a schedule it finds what changed locally,
serialises it, posts it to the Master, and records the ids that come back.

## Setup

### 1. Rules

*Synchronization › Synchronization Rules*, one per model, with a domain filter and a
direction that includes `outgoing`. The rules are also the namespace: nothing outside
them leaves this node.

### 2. The connection

*Synchronization › Slave Connections*:

| Field | Meaning |
| --- | --- |
| Master URL | the Master's base URL, e.g. `https://my-odoo.com` |
| Master Database | the database name on the Master |
| API Key | a global API key generated on the Master |
| Slave Token | a UUID, generated here, never edited — this node's identity |
| Batch Size | records per request (default 100; 50–200 is the useful range) |
| Sync Interval | how often the connection's own cron runs |
| Scheduled Time | or, instead, one run a day at a given hour |

Each connection creates, updates and deletes its own `ir.cron` record. There is also a
legacy global cron, shipped inactive, that would run every connection at once.

### 3. Test Connection

Sends an empty batch. It proves the URL resolves and the key is accepted, and writes
nothing on either side. A refusal is reported with the Master's own reason.

### 4. Run Sync Now

Runs one cycle immediately, and raises if any batch was refused.

## A cycle

1. **Discovery** — for each rule, the records matching `get_delta_domain(last_sync_date)`:
   the rule's filter ANDed with `write_date >` the last successful cycle.
2. **Dependencies** — a breadth-first walk over many2one fields, so a record's targets
   arrive with it. The walk stays inside the rules: a dependency no rule covers is not
   followed and not sent.
3. **Serialization** — scalars as themselves, many2one as references, binary and stored
   computed fields according to the rule.
4. **Transport** — split into batches and posted to
   `/numa_synch/api/v1/sync_batch` with `Authorization: Bearer <api key>`. The metadata
   that describes this node's schema travels with the first batch only.
5. **Response** — the ids the Master returns are written into the mapping table, and
   committed, so a cycle that fails at batch 300 keeps the 299 already accepted.
6. **Finalization** — `last_sync_date` moves **only** if every batch was accepted.
   Moving it on a failure would silently drop everything that cycle was carrying.

## Dependencies

`numa_synch`, and the `requests` Python library.

## What was found before migrating

The module did not install, and would not have worked if it had.

- **`ir.cron` lost `numbercall` and `doall`.** Both were set, in the shipped cron data
  and in the cron each connection builds. The data file failed to parse, so the install
  stopped there. The two values said "run until deactivated" and "do not catch up on
  missed runs", which is the only behaviour `ir.cron` has now — there is nothing left to
  pass.
- **`create` takes a list.** The override was declared `@api.model def create(self, vals)`
  and Odoo 20 has no shim left for that, so any caller that batches — an import,
  `load()`, copying several records at once — passed the list straight through and
  `vals['slave_token'] = ...` died with "list indices must be integers". Creating one
  connection at a time happened to work, which is why nothing noticed.
- **`numa.synch.engine` had to become an `AbstractModel`.** Odoo 20 refuses an extension
  that would turn an abstract model into a concrete one (`model_classes.py:256`).
- **The views still used 17.0 syntax** — `attrs="{'invisible': ...}"` and `<tree>` — and
  `ir.model.access.csv` is `ir.access.csv` now, with read and manage split.

And two that no version change would have fixed:

- **`Test Connection` reported success on every refusal.** It read the HTTP status code
  alone, and the Master answers its refusals with HTTP 200 and an error body. A rejected
  token, an unknown model, a mismatched schema — all of them came back to the operator
  as "Connection test successful!", and the first real cycle then failed with nothing to
  point at. It reads the body now, and repeats the Master's reason.
- **The dependency walk left the namespace.** It appended whatever it reached. A rule
  covering `res.partner` therefore pulled in the partner's company, its currency, its
  salesperson — and serialised `res.users` rows, every stored field on them, onto the
  wire. The Master dropped them on arrival for exactly this reason, which is the only
  thing that kept it from being worse. The walk is now bounded by the rules, on this end
  as well.

The mid-cycle `cr.commit()` is kept — it is what makes a partial cycle worth something —
but it is skipped under test, where the cursor belongs to the test's own transaction.

## Tests

```bash
odoo-bin -d <database> -u numa_synch_slave --without-demo \
         --test-enable --test-tags=/numa_synch_slave --stop-after-init
```

Thirty-two tests, where there were none.

Seventeen on the connection: creating several at once, token generation, the cron being
created, moved, deactivated and deleted with its connection, a scheduled time landing on
the right hour, the four validation constraints, and `Test Connection` across a success
body, a refusal body, an answer that is not JSON, and a rejected key.

Fifteen on the engine: batching, the flat payload and its header, metadata travelling
with the first batch only, the three ways a batch fails without crashing, the returned
ids becoming mappings, what does and does not need syncing, discovery staying inside the
rules, an inactive connection sending nothing, and `last_sync_date` moving on a
successful cycle and not on a failed one.

## Author

Gustavo Marino <gamarino@numaes.com>
