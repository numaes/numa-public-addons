# Numa Synch Master — the central server

**Odoo 20.0** | LGPL-3 | NUMA Extreme Systems

**Status: migrated to Odoo 20.0** (module version `20.0.1.0.0`). Before the migration
**no Slave could talk to it and no batch could be written**: see
[What was found](#what-was-found-before-migrating).

Turns an Odoo instance into the Master of the synchronization system. It exposes one
endpoint, and applies what arrives there with a two-phase write.

## The endpoint

### `POST /numa_synch/api/v1/sync_batch`

Flat JSON in, flat JSON out (`type='json2'`), authenticated with an API key in an
`Authorization: Bearer` header (`auth='bearer'`, `bearer_scope='rpc'`).

Request:

```json
{
  "slave_token": "uuid-string",
  "records": [
    {
      "model": "res.partner",
      "local_id": 123,
      "vals": {"name": "Partner Name", "email": "partner@example.com"},
      "write_date": "2024-01-01T12:00:00"
    }
  ],
  "meta": {"system": {...}, "models": {...}}
}
```

Answer:

```json
{
  "status": "success",
  "message": "Processed 5 records",
  "updated_mappings": [{"model": "res.partner", "slave_id": 123, "master_id": 456}]
}
```

A refusal has the same shape with `"status": "error"` and a `message`. That is
deliberate: a Slave that cannot parse the reply cannot record what the Master did
accept, and would send the same batch again.

An empty `records` list is accepted and writes nothing. That is what the Slave's
**Test Connection** button sends: it proves the URL resolves and the key is accepted,
without touching data.

## Two-phase write

A batch is a graph, and a graph has no safe order. So:

1. **Skeleton** — every record is created or matched with its scalar fields only, and
   gets its mapping immediately.
2. **Decoration** — relational fields are written, translating each reference through
   the mappings that phase 1 just produced.

By phase 2 every record in the batch has a Master id, so a record may point at one that
comes after it in the same batch, or at itself.

A reference that still cannot be resolved — the Slave has not synchronised the target
yet — drops that one field and keeps the record. Losing the record instead would lose
it silently and for good; without the field, the next batch can complete it.

## Conflict resolution

Last Write Wins, on `write_date`. If the incoming record is newer the change is applied
and the chatter says where it came from; if the Master's copy is newer or equal the
change is ignored and the chatter says so. An incoming record with no `write_date` is
applied.

## Safety

- **Namespace** — only models named by an active `incoming` or `bidirectional` rule are
  written. Everything else in a batch is logged and dropped. Without this, whoever holds
  a Slave's API key chooses which models to write to.
- **Reference** — an unresolvable reference costs a field, not a record.
- **Identity** — a `(model, slave local id, slave token)` triple always resolves to the
  same Master record, so a retried batch updates rather than duplicates. Two Slaves that
  both have a record 71 get two Master records.
- **Schema** — a batch carrying metadata is checked against the local model hashes
  before anything is written.

## Setup

1. **Rules** — *Synchronization › Synchronization Rules*, one per model, with a domain
   filter and a direction that includes `incoming`.
2. **API key** — *Settings › Users & Companies › API Keys*, for the user the Slave will
   act as. The key is shown once. It must be a global key (no scope), which is what
   `bearer_scope='rpc'` accepts.
3. **Hand the Slave** the Master URL, the database name and that key.

## Dependencies

`numa_synch`, and nothing else.

`sale`, `stock` and `account` used to be declared, and nothing in the module refers to
any of them. What the Master accepts is decided by the synchronization rules, and a rule
can only name a model that is installed — so the three bought nothing and made the
Master impossible to put on a database that does not sell, stock or invoice. The test
suite now runs on a database with none of them installed.

## What was found before migrating

This module had never answered a Slave. Four separate things saw to that, each on its
own sufficient.

1. **The two halves spoke different protocols.** The route was declared `type='json'`,
   which is JSON-RPC: it reads the payload out of a `{"params": {...}}` envelope and
   answers inside a `{"result": ...}` one. The Slave has always posted a flat body and
   always read a flat answer. Every batch came back as an envelope the Slave could not
   parse, and was logged as an unknown error.
2. **The authentication did not match either.** `auth='user'` wants a session cookie,
   which a server-to-server client does not have; the `Authorization: Bearer` header the
   Slave does send went unread. In Odoo 20 `auth='bearer'` checks exactly that header
   against `res.users.apikeys`, which is the handshake the Slave was written for.
3. **The endpoint's first line did not exist.** It read `request.jsonrequest`, which has
   not been an attribute of `request` since 17.0. It raised `AttributeError`, the
   blanket `except Exception` turned that into an "Internal server error" answer, and
   that answer went back with HTTP 200 — so on the Slave, `Test Connection` reported
   success.
4. **And the engine raised before looking at a record.** The batch was wrapped in
   `with self.env.context(sync_mode=True, tracking_disable=True):`. `env.context` is a
   read-only mapping: not callable, not a context manager. It is `with_context` now, on
   an inner method, which is what the line was reaching for.

And one guard that rejected everything it was meant to let through:

- `_process_record_phase1` checked the model with `model = self.env[model_name]`
  followed by `if not model:`. An empty recordset is falsy, so **every** model failed
  the check — every record of every batch was logged as "Model ... does not exist" and
  dropped. The question being asked is membership, and `model_name in self.env` is how
  it is asked.

Four `_logger` calls also had one more placeholder than arguments, which would have
raised inside the error handler that was trying to report the original problem.

## Tests

```bash
odoo-bin -d <database> -u numa_synch_master --without-demo \
         --test-enable --test-tags=/numa_synch_master --stop-after-init
```

Twenty-seven tests, where there were none.

Nineteen are on the engine: that a batch runs end to end at all, that it runs under the
synchronization context, the namespace refusals, the forward reference resolved in
phase 2, many2many translation, the unresolvable reference costing only a field, one bad
record not sinking the batch, idempotence on retry, two Slaves not colliding, both
directions of Last Write Wins, a mapping to a deleted record being rebuilt, and the
field-level handling of scalars, unknown names and compressed binaries.

Eight are on the wire. Two read what the route declares — `json2`, and `bearer` with the
`rpc` scope — and six go over real HTTP with a generated API key: a batch that creates a
record, the empty batch that is the connection test, two refusals delivered in the body,
and both ways of arriving without a valid key. All eight go red against the route as it
was declared before the migration.

## Author

Gustavo Marino <gamarino@numaes.com>
