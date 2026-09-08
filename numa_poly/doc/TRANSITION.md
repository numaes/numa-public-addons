# Making an existing database polymorphic

Installing a polymorphic module where records already exist leaves those records without
their polymorphic rows. `numa_poly` reconstructs them **during the install, on its own**.
There is nothing to prepare and nothing to plan: which module makes which model
polymorphic on which database is not knowable in advance, so no step here may depend on
somebody having anticipated it.

This note says what the mechanism does, so that its log lines are readable and so that
the rare case where it needs a decision is recognisable. It is not a checklist.

## What happens on install

```bash
odoo-bin -c odoo.config -d <db> -u <the module>
```

`init()` runs for every model the module touches, and for each polymorphic one:

1. **Collisions are resolved first.** A record whose id already belongs to another model
   is moved to a free id, together with everything that points at it.
2. **Missing rows are built**, deepest base first, for every record that has none.
3. **What could not be finished is handed to the cron** — a table too large to migrate
   inside the upgrade, a base that was not ready, a failure. `init()` never asks a person
   to re-run anything: it puts the model on the deferred list, and
   `ir_cron_poly_backfill_pending` works through it in batches until there is nothing
   left, then drops it. A model it cannot finish stays on the list rather than being
   quietly forgotten.
4. **Post-processing** — dependency links, planning roots, anything that needs a fully
   loaded registry — is flagged during the insert and run by the same cron.

The cron runs hourly. Nothing waits on it: while a record is still incomplete, reads
answer the declared defaults, and any write to it — or any write that merely *points* at
it — builds its rows first. That is what keeps a purchase order openable while its lines
are still being migrated. It costs one indexed lookup per write.

To not wait for the hour, in a shell:

```python
env['ir.poly_base']._cron_poly_backfill_pending(); env.cr.commit()
```

## Why a record can collide, and who moves

`create` allocates every polymorphic id from `ir_poly_base_id_seq`, so an id identifies a
record across the whole polymorphic universe — and across the *bases* too, since a base
is a model in its own right whose standalone records spend ids from its own sequence.

Pre-existing records do not come from that sequence. A `res.partner` and a
`purchase.order.line` both numbered from 1 hold thousands of the same ids, and only one
of them can have the `ir.poly_base` row under each.

`_poly_renumber_rank` decides which one moves, and it decides so that nobody has to:
**the model referenced by more foreign keys keeps its ids**. A partner is pointed at from
several hundred tables and a purchase order line from a handful, so the line moves. Row
count breaks ties, the model name breaks what is left, so the order is total and the
same on every run.

Everything that points at a moved row moves with it — real foreign keys read from
`pg_constraint` rather than from a list somebody maintains, plus the `(model, id)`
references Postgres knows nothing about: attachments, messages, followers, external ids.
The row and its foreign keys move in a single statement, because a foreign key declared
`NO ACTION` is checked at the end of the statement and not before.

## Reading the result

```sql
-- every pair closed, nothing blocked, no collisions left
select state, count(*), sum(collisions) from numa_poly_backfill_pair group by 1;

-- the post-processing pass has drained
select count(*) filter (where post_pending) from numa_poly_backfill;

-- what was reconstructed: also a readable map of an installation's polymorphic universe
select concrete_model, base_model, records_created from numa_poly_backfill_pair
 where records_created > 0 order by 3 desc;
```

A pair in `blocked` is the honest state of a model that still has collisions it was not
allowed to resolve. A pair is never marked `done` over records that have no base row of
their own — that mistake is what left a third of a customer database without an identity
while every pair claimed to be finished.

Records the migration had to guess at are in `numa.poly.backfill` with `reviewed = false`
— including any whose required base column had no value to carry across and got a
placeholder.

## The two knobs, and when they are worth reaching for

Neither is part of installing. They exist for the case where you want to know the size of
what is about to happen, or to stop it.

**`_poly_collision_census()`** answers "how many primary keys is this going to rewrite,
and for which models":

```python
for entry in env['ir.poly_base']._poly_collision_census(sample=5):
    print(entry['concrete_model'], entry['count'], entry['claimed_by'])
```

Run before the install it is a forecast; run after it should be empty. The cron logs it
on every pass, so a deployment with no shell still hears about a model that could not
claim its ids.

**`numa_poly.renumber_collisions = 0`** stops the renumbering. The backfill then reports
the collisions and marks the pairs `blocked` instead of resolving them. Worth setting
only when the ids of a specific model are load-bearing outside the database — an external
integration keyed by `res.partner` id, say — and you want to decide by hand which side
gives way. `_poly_renumber_colliding(dry_run=True)` shows the plan without moving
anything.

## Databases migrated before 18.0.1.1.0

Until that version the backfill accepted *any* row under a record's id as proof of its
own work, so it closed pairs over records that had never owned their ids. The
pre-migration re-opens every closed pair, so the corrected scan looks at them again on
the next `-u numa_poly`. Nothing else is needed.

---

Sobre el espacio de ids que comparten un registro polimórfico y sus componentes —un solo
asignador para todas las tablas, por qué sincronizar no alcanzaba, y qué consumo tiene—
ver [ID_SPACE.md](ID_SPACE.md).
