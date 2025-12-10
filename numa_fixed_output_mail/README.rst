Fixed Output Mail (Force SMTP Sender)
=====================================

Overview
--------
This module ensures that outgoing emails sent via a company's SMTP server use the SMTP user's email address as the technical sender, while preserving the original human‑readable display name. It also aligns the ``Reply-To`` and ``Return-Path`` headers to the SMTP user to improve deliverability and ensure replies/bounces reach the departmental inbox.

Key Features
------------
- Adds a boolean option "Force SMTP Sender" on each ``ir.mail_server``.
- When enabled and ``smtp_user`` is configured, outgoing messages are rewritten as:
  - ``From``: keeps the original display name, forces the email address to ``smtp_user``.
  - ``Reply-To``: set to ``smtp_user``.
  - ``Return-Path``: set to ``smtp_user``.
- If the option is disabled or no ``smtp_user`` is set, behavior remains unchanged.

Rationale
---------
Some SMTP providers require that the ``From`` domain matches credentials (SPF/DKIM/DMARC). If Odoo uses the end user's personal mailbox in ``From`` while sending through a generic departmental SMTP account, deliverability, alignment, and reply flows can break. This module fixes that by forcing the sender to the SMTP user's address while preserving the display name.

Configuration
-------------
1. Go to Settings → Technical → Email → Outgoing Mail Servers.
2. Open the server used by a given company.
3. Set the SMTP credentials (``smtp_user`` / ``smtp_pass``) and enable "Force SMTP Sender".
4. Save.

Multi-Company
-------------
The option is configured per ``ir.mail_server`` and naturally supports multi‑company databases where each company uses its own server and sender identity.

Security & Compatibility
------------------------
- No new models or access rights are introduced; only a field on ``ir.mail_server``.
- Uses Python's standard library ``email.utils`` to manipulate headers safely.
- Tested with Odoo 18.0.

Limitations
-----------
- The module does not attempt to select a mail server; it only adjusts headers for the server actually used by Odoo.
- It does not modify message bodies or attachments.

Credits
-------
Author: Numa / Contributors
License: LGPL-3
