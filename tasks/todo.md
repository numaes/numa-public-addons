# Odoo 20.0 migration of `numa-public-addons`

## Status

Every module in the repository carries a `20.0.x` manifest and installs on a clean
database. What remains is verification: a module with no tests is a module whose dead
code has not been found yet, which has been the rule rather than the exception here.

## Done

| Wave | Modules |
| --- | --- |
| 1 | `numa_poly`, `numa_poly_test`, `numa_big_id`, `numa_exceptions` |
| 2 | `numa_fsm`, `numa_fsm_hr`, `numa_fsm_crm`, `numa_fsm_pubsub`, `numa_asynch_exec`, `numa_background_job`, `numa_background_job_test`, `numa_roles`, `numa_imap`, `numa_fixed_output_mail`, `numa_web_relative_dates` |
| 3 | `numa_physical_product` (+ its four bridges), `numa_product_variant`, `numa_real_time_observability` (+ `_test`) |
| 4 | `numa_synch`, `numa_synch_slave`, `numa_synch_master`, `numa_synch_ai_assisted`, `numa_synch_ai_assisted_numa_ai` |

Deleted: `numa_periodic_services` (unused, at the user's instruction).

## Wave 5 — the modules that had no test of their own

- [x] `numa_physical_product_sale` — 15 tests. It priced nothing outside the form.
- [x] `numa_physical_product_stock` — 16 tests. No stock could move with it installed,
      and every per-line dimension it recorded was silently discarded.
- [x] `numa_physical_product_invoice` — 13 tests. It overwrote the shipped weight with
      the catalogue's, and never resynced on a write.
- [x] `numa_physical_product_purchase` — 12 tests. Nothing in it worked at all;
      eleven of the twelve go red against the previous code.
- [x] `numa_synch_ai_assisted_numa_ai` — the seam it implements is covered from this
      side by `numa_synch_ai_assisted` (10 tests). Its own three lines cannot be
      exercised here: `numa_ai` lives in `numa-addons-20.0` and is still at
      `18.0.1.0.7`, so the bridge has no second half to install against yet.

`numa_real_time_observability` is covered by `numa_real_time_observability_test`
(18 tests) and needs nothing further.

## Known open items, reported and not yet fixed

- [x] **`website` + `numa_poly` in the same run.** Fixed. `numa_poly` carried a full
  copy of core's `_write_multi`, and the copy was a version behind on the SQL that
  merges a translated jsonb column: Odoo 20 passes it the pair
  `(is_partial, translations)`, the copy treated it as the bare dict, and Postgres
  answered the object-concatenated-with-array with an array. Every translated field
  written through a polymorphic model was stored as `[{...}, false, {...}]`, and the
  next read died in `StoredTranslations`. The override is `super()` plus its two own
  lines now, and `numa_poly_test` has five tests on it (two go red against the fork).
- **`numa_product_variant`'s browser tour stops at step 19 of 21.** The three JS
  breakages ahead of it are fixed; the last one is not.
