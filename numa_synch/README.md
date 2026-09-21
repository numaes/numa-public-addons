# Numa Synch — core

**Odoo 20.0** | LGPL-3 | NUMA Extreme Systems

**Status: migrated to Odoo 20.0** (module version `20.0.1.0.0`). Two of the things this
module is responsible for did not work before the migration: see
[What was found](#what-was-found-before-migrating).

The foundation of an offline-first synchronization system. It carries no network code
and no scheduled jobs; it is the library that `numa_synch_master` and
`numa_synch_slave` are built on.

## What it provides

### Identity mapping — `numa.synch.map`

A record's id is local to the node that created it. This table is what lets two
databases talk about the same record without sharing an id space.

| Field | Meaning |
| --- | --- |
| `model_id` / `model_name` | the model the pair belongs to |
| `local_id` | the id in this database |
| `remote_id` | the id in the other one |
| `node_token` | which node the other one is (a Slave UUID, or `MASTER`) |
| `last_sync_date` | when the pair was last confirmed |

- `get_remote_id(model_name, local_id, node_token)`
- `get_local_id(model_name, remote_id, node_token)`
- `set_mapping(model_name, local_id, remote_id, node_token, last_sync_date=None)` —
  idempotent, so a replayed batch does not create a second pair.

`(model_id, local_id, node_token)` is unique. That is load-bearing: with two rows for
one record, `get_remote_id` answers with whichever comes first, and the record starts
arriving at the other end under two identities.

### Synchronization rules — `numa.synch.rule`

What is synchronised, in which direction, and which slice of it.

| Field | Meaning |
| --- | --- |
| `model_id` | the model the rule covers |
| `domain_filter` | which of its records, in Odoo domain syntax |
| `direction` | `bidirectional`, `outgoing` or `incoming` |
| `sync_binary_fields` | binary fields are opt-in: they dominate a payload |
| `binary_max_size_mb` | anything larger is skipped (default 10) |
| `binary_compress` | gzip before base64 (default on) |
| `sync_computed_fields` | stored computed fields travel; non-stored ones do not |
| `recalculate_computed` | recompute non-stored ones on arrival |

`get_delta_domain(last_sync_date)` ANDs the rule's filter with
`write_date > last_sync_date`, which is the whole of the delta detection. With no last
sync date it returns the filter alone — the first cycle sends everything.

The set of rules is also the **namespace**: both ends refuse anything no rule names.

### Serialization — `numa.synch.engine`

An abstract model. Both sides inherit it and add their own half.

- `_serialize_record(record, sync_rule=None)` → `(vals, dependencies)`. Scalars travel
  as themselves; a many2one travels as `{'__type__': 'ref', 'model': ..., 'id': ...}`,
  because a raw id means nothing on the other side; system and related fields stay home.
- `_parse_incoming_ref(ref_dict, source_node)` resolves such a reference through the
  mapping table, and answers `False` when it cannot.
- `_serialize_binary_field` / `_deserialize_binary_field` — gzip plus base64, with the
  size limit applied before anything is put on the wire.
- `_get_system_metadata`, `_compute_model_hash`, `_validate_metadata` — the handshake.
  A batch carries the sender's Odoo version and a hash of each model's field
  signatures; the receiver refuses a batch built against a different schema rather than
  writing part of it.

`SchemaMismatch` (a `UserError`) is raised for the schema case specifically, so that a
downstream module can offer to reconcile the two schemas. A version mismatch and absent
metadata stay plain `UserError`: nothing can repair those, and nothing should catch them.

## Dependencies

`mail`, `web`.

## What was found before migrating

Two of this module's own guarantees were not in force.

- **The unique index did not exist.** It was declared with `_sql_constraints`, which
  Odoo 20 ignores with a warning (`model_classes.py:175`). It is a `models.UniqueIndex`
  now, and there is a test that inserts the duplicate.
- **The domain-filter constraint could not refuse anything.** `numa_synch_rule.py`
  never imported `ValidationError`, so `_check_domain_filter` died with
  `NameError: name 'ValidationError' is not defined` the moment it found a bad filter.
  The user saw a server error naming neither the field nor the reason, and the rule was
  not saved for a reason nobody could read.

And one genuine 20.0 break, which stopped every cycle before it began:

- **`ir.config_parameter.get_param` is gone.** The untyped `get_param`/`set_param` pair
  was replaced by typed accessors — `get_str`, `get_bool`, `get_int`, `get_float`, each
  carrying its own default. `_get_system_metadata` read `database.uuid` through the old
  one and raised `AttributeError`; since the metadata is built at the start of every
  synchronization cycle, no batch could leave a Slave at all.

The module also shipped a `tests/standalone_test.py` whose body was `try: pass`, and an
empty `tests/__init__.py`, so nothing in it ever ran. It has been replaced.

## Tests

```bash
odoo-bin -d <database> -u numa_synch --without-demo \
         --test-enable --test-tags=/numa_synch --stop-after-init
```

Thirty-nine tests, where there were none. They cover the mapping table (both
directions, idempotence, per-node and per-model id spaces, the unique index, the
refusals), the rules (the delta window actually excluding what has not changed, and the
domain-filter constraint now refusing), and the engine (references, binary round trip
and size limit, the model hash, and each of the three ways the handshake can refuse).

`test_18` asserts that a schema mismatch is refused and names the model, but does not
pin the wording: `numa_synch_ai_assisted` catches that one to try to map the two
schemas onto each other, and rewords it when it cannot.

## Author

Gustavo Marino <gamarino@numaes.com>
