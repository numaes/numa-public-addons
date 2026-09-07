# Making an existing database polymorphic

Installing a polymorphic module where records already exist leaves those records without
their polymorphic rows. `numa_poly` reconstructs them, and this note is the procedure —
plus the one situation the reconstruction cannot resolve on its own.

## What "incomplete" costs

A record with no base row is not merely missing a feature. Three failures follow, and
two of them are silent:

| operation | what happens without the base row |
|---|---|
| read a base field | answers the field's default (safe, deliberate) |
| search on a base field | returns nothing, with no error |
| write a base field | accepted and discarded, with no error |
| anything that *references* the record | ForeignKeyViolation, from inside a model the caller never mentioned |

The last one is what people report. A `purchase.order.line` without its
`numa_planning_node` row takes the whole purchase order down as soon as it is saved,
because the bridge then creates an allocation pointing at that row.

## The one id space

`create` allocates every polymorphic id from `ir_poly_base_id_seq`, so an id identifies
a record across the whole polymorphic universe — and across the *bases* too, since a
base is a model in its own right whose standalone records spend ids from its own
sequence.

Pre-existing records do not come from that sequence. A `res.partner` and a
`purchase.order.line` both numbered from 1 hold thousands of the same ids, and only one
of them can have the `ir.poly_base` row under each. That is an **id collision**, and the
only real fix is for one of the two records to move.

`_poly_renumber_rank` decides which. The model referenced by more foreign keys keeps its
ids — a partner is pointed at from several hundred tables and a purchase order line from
a handful, so the line moves. Row count breaks ties.

## Procedure

Back up first, with the database stopped. The renumbering rewrites primary keys of real
business data.

```bash
createdb -T <db> <db>-pre-transition
odoo-bin -c odoo.config -d <db> -u numa_poly --stop-after-init
```

`-u numa_poly` is enough: updating it rebuilds the registry and `init()` then runs for
every model, including ones whose module was not named. Do **not** use `-u all`.

The upgrade does not finish the job — it leaves records with `post_pending = true`, and
that pass is what rebuilds dependency links and planning roots. It is driven by the
`ir_cron_poly_backfill_pending` cron (hourly). Trigger it rather than waiting:

```python
env['ir.poly_base']._cron_poly_backfill_pending(); env.cr.commit()
```

## Before you start: the census

On an unfamiliar database, look before upgrading:

```python
for entry in env['ir.poly_base']._poly_collision_census(sample=5):
    print(entry['concrete_model'], entry['count'], entry['claimed_by'])
```

Each line is a model whose records cannot claim their ids, how many, and what holds
them. That count is how many rows the upgrade will renumber. If it is large, or if the
model is one with external integrations keyed by id, decide deliberately rather than
letting the upgrade decide:

```python
# Report only — the backfill will then leave the collisions alone and mark the pairs
# 'blocked' instead of 'done'.
env['ir.config_parameter'].sudo().set_param('numa_poly.renumber_collisions', '0')

# Or see exactly what would move, without moving it:
env['purchase.order.line']._poly_renumber_colliding(dry_run=True)
```

## Verifying

```sql
-- every pair closed, nothing blocked, no collisions left
select state, count(*), sum(collisions) from numa_poly_backfill_pair group by 1;

-- the post-processing pass has drained
select count(*) filter (where post_pending) from numa_poly_backfill;

-- what was reconstructed, and a readable map of the polymorphic universe
select concrete_model, base_model, records_created from numa_poly_backfill_pair
 where records_created > 0 order by 3 desc;
```

A pair in `blocked` is the honest state of a model that still has collisions; it is
never marked `done` over records that have no base row of their own.

Records the migration had to guess at are listed in `numa.poly.backfill` with
`reviewed = false` — including any whose required base column had no value to carry
across and got a placeholder.

## While the transition is still running

None of the above has to be finished for the system to be usable. Reads answer defaults,
and any write to an incomplete record builds its rows first — as does any write that
merely *points at* one, which is what keeps a purchase order openable while its lines
are still being migrated. The guard costs one indexed lookup per write.

The exception is a record whose id is taken: it cannot be completed at all, so writing to
it raises a `UserError` naming the model that holds the id. Everything else carries on;
an unrelated record that merely references the blocked one logs a warning rather than
failing.
