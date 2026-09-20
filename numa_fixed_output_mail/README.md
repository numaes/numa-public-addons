# Fixed Output Mail (Force SMTP Sender)

**Odoo 20.0** | LGPL-3 | NUMA Extreme Systems

**Status: migrated to Odoo 20.0** (module version `20.0.1.0.0`). The migration found two
things that were broken before it: see [Migration to Odoo 20.0](#5-migration-to-odoo-200).

---

## 1. What it does

Adds a **Force SMTP Sender** switch to each outgoing mail server. When it is on and the
server has an `smtp_user`, every message sent through that server is rewritten so the
technical sender is that user, while the human-readable display name is preserved:

| Header | Value |
|---|---|
| `From` | the original display name, with the address forced to `smtp_user` |
| `Reply-To` | `smtp_user` |
| `Return-Path` | `smtp_user` |

If the switch is off, or the server has no `smtp_user`, nothing is touched.

## 2. Why

**The case this module is for is a multi-company installation whose companies do not share
a mail domain.** Each company has its own mailbox, and its people's mail must leave through
that mailbox — with that company's address on it, and with replies and bounces coming back
to it.

Underneath, the reason it cannot be left to the `From` header alone is that providers
require the `From` domain to match the credentials used to authenticate (SPF/DKIM/DMARC).
If Odoo puts an end user's personal mailbox in `From` while authenticating with the
company's account, alignment breaks.

### 2.0 What has to be configured

| | |
|---|---|
| One `ir.mail_server` per company | with that company's mailbox in **Username** (`smtp_user`) |
| **FROM Filtering** (`from_filter`) on each server | set to that company's domain, e.g. `alpha.example.com` |
| **Force SMTP Sender** | on, on each of them |
| One `mail.alias.domain` per company | pointed at from `res.company.alias_domain_id`, which is how Odoo already separates companies by domain |

The `from_filter` is not decoration, and it is not only Odoo's: **this module refuses to
force the sender when the server declares a `from_filter` that the message's `From` does
not match.** The reason is in 2.2.

### 2.1 What Odoo already does, and where this differs

Odoo has a mechanism of its own, and it is worth knowing before installing this module.
A mail server declares a `from_filter` — the addresses or domains it may send for — and
`ir_mail_server._prepare_email_message__` **encapsulates** the sender when the computed
envelope address is the alias domain's notification address and the message's `From` is
something else. `tools.mail.encapsulate_email` keeps the display name, so the result is
`"Juan Perez" <notifications@company.com>`, and `_alter_message__` writes it into the
`From` header.

Two differences decide whether this module adds anything:

| | Odoo's encapsulation | This module |
|---|---|---|
| Address forced into `From` | the **alias domain's** `default_from` — one per company | the **server's** `smtp_user` — one per outgoing server |
| When | only when the envelope resolves to that notification address | whenever the switch is on and the server has an `smtp_user` |
| `Reply-To` / `Return-Path` | untouched | pinned to `smtp_user` |

So if every outgoing mail should come from one company-wide notification address, Odoo
covers it and this module is not needed. If different departments send through different
SMTP accounts and each should own its own `From` and receive its own replies and bounces,
this module is what does that.

None of this is new in Odoo 20: the alias-domain machinery predates it. The overlap was
already there in 18.0.

For the multi-company case specifically, Odoo's mechanism gives every company the same
kind of address — its alias domain's `notifications@` — which is the right answer when
what matters is the domain. It is not the right answer when what matters is that replies
land in the mailbox a team actually reads.

### 2.2 The guard: one company's mail never leaves through another's mailbox

`ir.mail_server._find_mail_server` picks the server by `from_filter`, matching the full
address first and then the domain. When nothing matches it **still returns a server** —
the first one without a filter, or failing that any server at all, logging that nothing
matched.

That fallback is reasonable for Odoo, which then spoofs the From with the notification
address. It would be dangerous here: forcing the sender on a fallback server means taking
one company's mail out of another company's mailbox, with that other company's address on
it, silently.

So the rule is:

| Server's `from_filter` | Message's `From` | Forced? |
|---|---|---|
| empty | anything | yes — the server makes no claim, and there is nothing to cross |
| set, matches | | yes |
| set, does not match | | **no**, and a warning names the address, the server and its filter |

An empty `from_filter` is the single-company setup. In a multi-company database, leaving it
empty is what turns the fallback into a leak, which is why it is in the table in 2.0.

Forcing `Return-Path` is worth knowing about: Odoo takes the bounce address from that
header when it is set, so bounces reach the SMTP user instead of the alias domain's bounce
address. That is the intent — the departmental inbox gets them — but it does override the
default.

---

## 3. Installation

Depends only on `mail`. One boolean field and one inherited view.

---

## 4. Tests

```bash
odoo-bin -d <database> -i numa_fixed_output_mail --without-demo \
         --test-enable --test-tags=/numa_fixed_output_mail --stop-after-init
```

Fourteen tests, over two companies with their own domains, alias domains and servers.

The basics: the switch off changes nothing, the switch on without an `smtp_user` changes
nothing, the display name survives, a message with no display name gets the owning
company's, an address that already matches is left alone, no header is duplicated, and
`send_email` actually goes through the rewrite.

The multi-company part: the owning company is derived from the mailbox's domain, an
address belonging to another company is **not** claimed and says so in the log, a server
with no filter claims everything, each company goes out through its own mailbox, and the
routing this all rests on — `from_filter` deciding which server a `From` selects — is
asserted against Odoo's own `_find_mail_server`.

---

## 5. Migration to Odoo 20.0

### 5.1 The fallback display name never worked

When the `From` header carries no display name, the module is supposed to fall back to the
company name. The code read `self.company_id` — a field `ir.mail_server` does not have,
and never had, in 18.0 either. The `AttributeError` landed in the `except Exception`
around the rewrite, so the message was returned **untouched**: exactly the case the branch
exists for. It was logged as "Failed to enforce SMTP sender headers", so it was visible,
but nothing else said so.

It now derives the company from the mailbox's **domain**, through the `mail.alias.domain`
that a company points at. That is deliberate and not the same as `self.env.company`: in a
multi-company database the sending context is whoever happens to be running the cron,
which has nothing to do with whose mailbox is being used. The server's own name is the
last resort.

### 5.2 The test suite never ran

`tests/__init__.py` did not import the test module, and the tests referenced two demo mail
servers (`demo_mail_server_alpha`, `demo_mail_server_beta`) that no data file declares.
Both are fixed: the package imports the module, and the servers are built by the test.

While making them run, two of the old assertions turned out to be wrong: `EmailMessage`
normalises `"Juan Perez" <a@b>` to `Juan Perez <a@b>` when the header is set, because the
quotes are not needed. The expected values are built with `formataddr` now instead of
written by hand.

### 5.3 Smaller things

- The manifest had **no `version` key at all**; it is `20.0.1.0.0` now.
- `'base'` left `depends` — `mail` already brings it.
- `super(IrMailServer, self)` became `super()`, and the unused `_` import is gone.
- `README.rst` became this file, which is what the rest of the repository uses.

---

## 6. License and Author

- **Copyright:** NUMA Extreme Systems
- **License:** LGPL-3
- **Website:** [http://www.numaes.com](http://www.numaes.com)
