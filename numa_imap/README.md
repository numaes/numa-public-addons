# NUMA IMAP

**Odoo 20.0** | LGPL-3 | NUMA Extreme Systems

**Status: migrated to Odoo 20.0** (module version `20.0.1.0.0`). Both what the module is
for and where it hooks in changed: see [Migration to Odoo 20.0](#5-migration-to-odoo-200).

---

## 1. What it is for

Odoo reads an IMAP mailbox by searching for `UNSEEN` messages. That makes the **read flag
the bookmark**, and the read flag belongs to everyone: a phone client, a webmail or a
colleague opening the mailbox marks messages as seen, and Odoo then skips them for good.

This module reads by **UID** instead.

| | Odoo | This module |
|---|---|---|
| Bookmark | the `\Seen` flag | the highest processed UID, checked against UIDVALIDITY |
| Fetch | `(RFC822)`, then clear `\Seen`, then set it after processing | `BODY.PEEK[]`, which never sets the flag |
| Folder | INBOX | the `\All` folder when the server has one |
| First run | whatever is unseen | bounded by `initially_from`, or the last seven days |

It also keeps a readable copy of each incoming message as a `mail.mail` when the server
has *Keep Original* on, and records on `mail.message` which server brought a message in.

### 1.1 Why PEEK rather than clearing the flag

Odoo sets the flag and clears it again. A connection that drops between the two leaves the
message marked read on the server, and with the flag as the bookmark that message is
lost. `BODY.PEEK[]` never sets it, so there is nothing to undo.

### 1.2 Why UIDVALIDITY matters

A UID only means something together with the UIDVALIDITY it was issued under. When a
server renumbers a folder, resuming at `last_uid + 1` would skip every message below it —
silently, and permanently. The module stores both and resets the bookmark when they
disagree.

---

## 2. Installation

Depends on `mail`. Adds three fields to `fetchmail.server` and one to `mail.message`.

The UID fields are read-only in the UI: they are a bookmark the module keeps, not a
setting. `initially_from` is the one to fill in.

---

## 3. Scope

Only IMAP. POP servers keep Odoo's connection untouched — POP has no UIDs to track.

---

## 4. Tests

```bash
odoo-bin -d <database> -i numa_imap --without-demo \
         --test-enable --test-tags=/numa_imap --stop-after-init
```

Nine tests over the bookmark, which is the decision this module exists to change: a
mailbox never read starts at 1, resuming asks for the next UID, a changed UIDVALIDITY
resets it, a bookmark with no validity is not trusted, the initial window defaults to a
week and can be set, IMAP dates are formatted the way IMAP wants, POP is left alone, and
an imported message records its server.

The IMAP conversation itself is not tested: exercising it needs a server, and a fake one
would only assert that the fake behaves like the fake.

---

## 5. Migration to Odoo 20.0

### 5.1 The module's headline feature had already become core

The old summary was *"leave read mails from IMAP servers as unread on server"*. Odoo does
that itself, and has since 18.0 at least: `OdooIMAP4.retrieve_unread_messages` clears
`\Seen` right after downloading, and `handled_message` sets it only once the message was
processed.

What is still missing in core is everything in the table above — above all, not depending
on a flag that other mail clients also write. The description now says that instead.

### 5.2 The hook moved, and the old one would have gone quiet

Up to 18.0 this module overrode `fetch_mail()`, which was the whole fetch loop. Odoo 20
split it three ways:

- `fetch_mail()` is the button,
- `_fetch_mails()` is what the cron calls,
- `_fetch_mail()` holds the loop, and drives an **IMAP connection object** with
  `check_unread_messages` / `retrieve_unread_messages` / `handled_message` / `disconnect`.

An override of `fetch_mail()` still compiles and is still called by the button, but the
cron no longer goes through it. The module would have looked installed and done nothing on
every scheduled fetch.

The split is good news here: the forked loop — transactions, per-message commits, error
handling, cron progress — goes back to core, and what is left is the connection object,
which is the only part that was ever different. `_connect__` re-classes the instance core
builds, so login and TLS are not duplicated either.

### 5.3 `message_process` was a fork, and had drifted

The module carried a copy of core's `message_process` with the copy-keeping inserted in
the middle. The copy was written against an older core, which has since added an advisory
lock that makes the duplicate check reliable under concurrency, bounce-loop detection by
headers, sender-loop detection, and `_message_parse_post_process`. The fork had none of
it, and nothing said so.

It now does only the extra work and delegates. That costs one extra parse of the message
when *Keep Original* is on, which is an opt-in setting on the server.

### 5.4 Smaller things

- `fetchmail` stopped being a module: `fetchmail.server` lives in `mail`, so `depends`
  is `['mail']` and the inherited view is `mail.view_email_server_form`.
- `security/ir.model.access.csv` had only a header row and `security/security.xml` only
  empty `<data>` tags, under an `<openerp>` root that has not been the document element
  since 8.0. Both are gone.
- The form no longer shows `child_ids` on `mail.message`, which was there for debugging.
- `last_uid` and `last_uid_validity` are readonly and `copy=False`: duplicating a server
  used to carry someone else's bookmark.

---

## 6. License and Author

- **Copyright:** NUMA Extreme Systems
- **License:** LGPL-3
- **Website:** [http://www.numaes.com](http://www.numaes.com)
