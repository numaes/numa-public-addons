# Numa Roles

**Odoo 20.0** | LGPL-3 | NUMA Extreme Systems

**Status: migrated to Odoo 20.0** (module version `20.0.1.0.0`). Before the migration it
**did not install**, and had not since 17.0 — see
[What was found](#6-what-was-found-before-migrating).

---

## 1. The idea

Odoo has one concept where role-based access control has two. A group both *grants*
something and *is granted* to people, so a security model written in groups can only say
what somebody may do by listing every group they carry — and nothing stops that list from
growing into a pile nobody can audit.

This module does not add a mechanism. Everything still runs on `res.groups` and
`implied_ids`, and nothing here is consulted when Odoo checks access. What it adds is a
**discipline**, and enforces it:

| | |
|---|---|
| **Permission** | an atomic unit of access, with a stable technical code. Never assigned to a user. |
| **Role** | a named bundle of permissions. The only thing a user gets. |
| **System** | a native Odoo group, left alone. |

The rules are constraints, not conventions: a permission with users attached is refused, a
permission that includes a role is refused, a permission without a code is refused, and a
code does not change once it is set.

## 2. What makes it worth using: asking by name

```python
if order.user_id.has_permission('perm_approve_discount'):
    ...
```

A business rule asks for a permission by name instead of naming a group's XML id. The
security model can then be rearranged — split a role, rename it, move the permission into
a different bundle — without touching the rule. The answer resolves through
`all_group_ids`, so a permission reached through a role two levels up counts.

The question is about **that user**, not about how the calling code happens to be running:
a `sudo()` environment does not turn the answer into yes.

## 3. What Odoo 20 does and does not do here

Odoo 20 reworked groups considerably, and it is worth being precise about the overlap:

| Odoo 20 has | What it is | Does it replace this? |
|---|---|---|
| `res.groups.privilege` ("Scope") | a label that groups groups in the UI | No. It organises the list; it does not separate what is assignable from what is atomic. |
| `disjoint_ids` | groups that cannot be held together | No, and it composes fine with roles. |
| `all_implied_ids` / `all_implied_by_ids` | the transitive closure, exposed | No — but this module now uses it instead of walking by hand. |
| `ir.access` with `kind = permission / restriction` | replaces `ir.model.access` + `ir.rule` | No. That is a permission on **one model**; a permission here bundles several and means something to the business. Different levels, same word. |

So the separation this module enforces is still not in core, and the word "permission" now
means two things in the same database. That is worth knowing before adopting it, and it is
the one real argument against.

---

## 4. Installation and use

Depends on `web`. Adds four fields to `res.groups`, one method to `res.users`, three menus
under **Settings → Roles and Permissions**, and a permission matrix — a client action
where roles are columns, permissions are rows, and a tick adds or removes.

Two example permissions and a role are shipped as **demo** data, so an empty database can
be looked at without a production one growing examples.

## 5. Tests

```bash
odoo-bin -d <database> -i numa_roles --without-demo \
         --test-enable --test-tags=/numa_roles --stop-after-init
```

Nineteen tests: each rule of the discipline, the derived and immutable technical code, the
permission count through nested roles, and the lookup API — including that it answers
about the user and not the environment, that root holds everything, and that an unknown
code denies rather than raising.

---

## 6. What was found before migrating

The module was written for 18.0 and never ran. Four things, each enough on its own:

1. **`@api.constrains('numa_type', 'users')`.** `res.groups.users` is `user_ids` in Odoo
   20. A constraint naming a field that does not exist fails at registry setup, so the
   module could not be installed at all.
2. **The views hid pages with `attrs="{'invisible': [...]}"`**, which Odoo removed in
   17.0 and rejects outright in 20.0. So the module had not installed since 17.0 either —
   it was written against an Odoo that was already two versions old.
3. **The pages it inherited do not exist.** It targeted `users`, `view_access`,
   `rule_groups`, `menu_access` and `implied_ids`; the 20.0 group form has `user_ids`,
   `inherit_groups`, `access_rights` and `menus`. It also used `<tree>` and
   `category_id`, gone since 17.0 and 20.0 respectively.
4. **`security/ir.model.access.csv` granted read, write, create and unlink on
   `res.groups` to every user** — an empty `group_id` column means everybody. A module
   about access control was handing out the ability to edit groups. Removed: core already
   governs who may touch `res.groups`.

And three that were quieter:

- **`_check_technical_code_immutable` could never fire.** It compared
  `group.technical_code` with `group._origin.technical_code`, and `_origin` on a stored
  record returns the record itself (`models.py:5936`), so it compared a value with itself.
  The live guard is the one in `write()`, which is where it belongs — a constraint runs
  *after* the write and has nothing left to compare.
- **`permission_count` counted only `implied_ids`**, so a role built out of other roles
  reported zero. It now counts over `all_implied_ids`.
- **The example records were loaded as data, not as demo**, so every production install
  grew two permissions and a role, named in Spanish.

One thing was found while writing the new API rather than in the old code, and it is worth
recording because it is the kind of bug that looks like a feature:
`has_permission` first short-circuited on `self.env.su`, which meant it answered **yes to
anybody** whenever it was called from a sudo'd environment — most of the places a business
rule runs. A permission check that says yes to everyone is worse than no check, because it
looks like one. The test suite caught it.

---

## 7. License and Author

- **Copyright:** NUMA Extreme Systems
- **License:** LGPL-3
- **Website:** [http://www.numaes.com](http://www.numaes.com)
