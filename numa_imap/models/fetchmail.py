# -*- coding: utf-8 -*-
"""Fetch IMAP mail by UID instead of by the ``\\Seen`` flag.

What this module is for, stated against what Odoo already does
--------------------------------------------------------------

Odoo's IMAP fetch selects INBOX, searches ``(UNSEEN)``, and clears the ``\\Seen`` flag
right after downloading each message, restoring it only once the message was processed
(``mail/models/fetchmail.py``, ``OdooIMAP4``). So "leave the mails unread on the server"
has been core behaviour since 18.0 at least; that was this module's old summary and it
no longer says anything.

What is still missing in core, and is what this module does:

* **The flag is not a reliable bookmark.** Anything else that opens the mailbox -- a phone
  client, a webmail, a colleague -- marks messages as seen, and ``(UNSEEN)`` then skips
  them for good. Tracking the highest processed **UID** does not care who else reads.
* **UIDVALIDITY is honoured.** If the server renumbers the mailbox, the bookmark resets
  instead of silently skipping everything.
* **``BODY.PEEK[]``** never sets the flag in the first place, instead of setting it and
  clearing it again. A connection that drops between those two steps leaves the message
  marked read in core; with PEEK there is nothing to undo.
* **The ``\\All`` folder** is selected rather than INBOX, so mail that a server-side rule
  filed away is still imported.
* **An initial window.** ``initially_from`` bounds the first import; without it the
  default is the last seven days, instead of the whole mailbox.

[20.0] Where it hooks in changed. Up to 18.0 this module overrode ``fetch_mail()``, which
was the whole fetch loop. Odoo 20 split it: ``fetch_mail()`` is now the button, the cron
calls ``_fetch_mails()``, and the loop lives in ``_fetch_mail()``, which drives an
**IMAP connection object** with ``check_unread_messages`` / ``retrieve_unread_messages``
/ ``handled_message``. The old override would have kept compiling and simply stopped
being called by the cron.

That split is an improvement for this module: the whole forked loop -- transactions,
commits, error handling, cron progress -- goes back to core, and what is left is the
connection object, which is the only part that was ever different.
"""
import logging
from datetime import timedelta

from email.message import EmailMessage

from odoo import api, fields, models
from odoo.addons.mail.models.fetchmail import OdooIMAP4, OdooIMAP4_SSL
from odoo.tools import BinaryBytes

_logger = logging.getLogger(__name__)

# IMAP wants its dates in this shape, and only in English.
IMAP_MONTHS = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
    7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec",
}
# How many UIDs to ask for in one search. The server answers with what exists in the
# range; a window keeps the request bounded on a mailbox with a long history.
UID_WINDOW = 500


def _as_bytes(content):
    """``message_parse`` hands back str, bytes or an EmailMessage, depending on the part."""
    if isinstance(content, bytes):
        return content
    if isinstance(content, EmailMessage):
        return content.as_bytes()
    return str(content).encode('utf-8')


def format_imap_date(day):
    """``date(2026, 9, 5)`` -> ``'5-Sep-2026'``, which is what SINCE/SENTSINCE want."""
    return '%s-%s-%s' % (day.day, IMAP_MONTHS[day.month], day.year)


class NumaUidIMAP4Mixin:
    """Retrieve by UID range and PEEK, leaving the flags alone.

    The connection carries the ``fetchmail.server`` record so that it can move the
    bookmark as messages are handled. That write lands on the server's own cursor, which
    core commits after each message batch, so a crash re-processes at worst a few messages
    -- and ``message_process`` drops duplicates by Message-Id.
    """

    def numa_bind(self, server):
        self._numa_server = server
        self._numa_validity = None
        self._numa_messages = None
        return self

    def _numa_select_all_folder(self):
        """Select the ``\\All`` folder, falling back to INBOX.

        Gmail and friends expose an ``\\All`` special-use folder that holds archived mail
        too. A server without one answers with plain folders, and INBOX is the right
        answer there.
        """
        response, data = self.list()
        if response == 'OK':
            for entry in data or ():
                flags, _sep, folder_name = entry.decode().partition(' "/" ')
                if '\\All' in flags:
                    return folder_name
        return 'INBOX'

    def check_unread_messages(self):
        server = self._numa_server
        folder = self._numa_select_all_folder()
        response, folder_data = self.select(folder)
        if response != 'OK':
            raise OSError("Cannot select IMAP folder %s: %s" % (folder, folder_data))
        self._numa_validity = int(folder_data[0].decode('utf-8'))

        first_uid = server._numa_first_uid(self._numa_validity)
        since = format_imap_date(server._numa_initial_date())
        _result, data = self.search(
            None, '(UID %d:%d SENTSINCE %s)' % (first_uid, first_uid + UID_WINDOW, since))

        last_uid = server.last_uid or 0
        self._numa_messages = sorted(
            int(num) for num in (data[0].split() if data and data[0] else ()) if int(num) > last_uid)
        self._numa_messages.reverse()
        return len(self._numa_messages)

    def retrieve_unread_messages(self):
        assert self._numa_messages is not None
        while self._numa_messages:
            num = self._numa_messages.pop()
            # PEEK: read without setting \Seen, so there is nothing to undo afterwards.
            _result, data = self.fetch(bytes(str(num), 'ascii'), '(BODY.PEEK[])')
            yield num, data[0][1]

    def handled_message(self, num):
        """Move the bookmark. The flags are deliberately left as the user left them."""
        server = self._numa_server
        uid = int(num)
        values = {}
        if uid > (server.last_uid or 0):
            values['last_uid'] = uid
        if self._numa_validity != server.last_uid_validity:
            values['last_uid_validity'] = self._numa_validity
        if values:
            server.write(values)

    def disconnect(self):
        if self._numa_messages is not None:
            self.close()
        self.logout()


class NumaIMAP4(NumaUidIMAP4Mixin, OdooIMAP4):
    pass


class NumaIMAP4_SSL(NumaUidIMAP4Mixin, OdooIMAP4_SSL):
    pass


class FetchmailServer(models.Model):
    """Incoming POP/IMAP mail server account"""

    _inherit = 'fetchmail.server'

    last_uid_validity = fields.Integer(
        'Last validity identifier', readonly=True, copy=False,
        help="UIDVALIDITY of the folder the last time it was read. When the server "
             "changes it, the UIDs it handed out before mean nothing and the bookmark "
             "is reset.")
    last_uid = fields.Integer(
        'Last received UID', readonly=True, copy=False,
        help="Highest UID already processed. This is the bookmark; the read/unread flag "
             "is not used.")
    initially_from = fields.Date(
        'Initial load, from date',
        help="How far back to look the first time. Left empty, the last seven days.")

    def _numa_initial_date(self):
        """The floor of the SENTSINCE window."""
        self.ensure_one()
        return self.initially_from or (fields.Date.today() - timedelta(days=7))

    def _numa_first_uid(self, current_validity):
        """The first UID to ask for, given the folder's current UIDVALIDITY.

        Resuming means ``last_uid + 1``. But a UID is only meaningful together with the
        UIDVALIDITY it was issued under: if the server changed it, the stored bookmark
        points at nothing and the read starts from 1. Never seen before, same thing.
        """
        self.ensure_one()
        if not self.last_uid_validity or current_validity != self.last_uid_validity:
            return 1
        return (self.last_uid or 0) + 1

    def _connect__(self, allow_archived=False):  # noqa: PLW3201
        """Return the UID-tracking connection for IMAP servers.

        Core builds ``OdooIMAP4`` / ``OdooIMAP4_SSL`` here. We want the same object with
        three methods replaced, so rather than duplicating the login and TLS handling we
        let core connect and re-class the instance. POP servers are untouched.
        """
        connection = super()._connect__(allow_archived=allow_archived)
        if self._get_connection_type() != 'imap':
            return connection
        connection.__class__ = NumaIMAP4_SSL if isinstance(connection, OdooIMAP4_SSL) else NumaIMAP4
        return connection.numa_bind(self)


class MailMessage(models.Model):
    _inherit = "mail.message"

    # Core keeps this on mail.mail, not on mail.message, yet it sets
    # `default_fetchmail_server_id` in the context while processing incoming mail
    # (mail/models/fetchmail.py). Declaring the field here is what makes that default
    # land, so an imported message says which server brought it in.
    fetchmail_server_id = fields.Many2one(
        'fetchmail.server', "Inbound Mail Server", readonly=True, index='btree_not_null')


class MailThread(models.AbstractModel):
    _inherit = 'mail.thread'

    @api.model
    def message_process(self, model, message, custom_values=None,
                        save_original=False, strip_attachments=False,
                        thread_id=None):
        """Keep a copy of the original as a ``mail.mail``, then let core route it.

        [20.0] This used to be a copy of core's ``message_process`` with the copy-keeping
        inserted in the middle. The fork was written against 18.0 and had drifted: core
        has since added an advisory lock that makes the duplicate check reliable under
        concurrency, bounce-loop detection by headers, sender-loop detection, and
        ``_message_parse_post_process``. The fork had none of it, and silently.

        Doing only the extra work and delegating costs one extra parse of the message
        when ``save_original`` is on, which is an opt-in setting on the server.
        """
        if save_original:
            self._numa_keep_original(message, strip_attachments=strip_attachments)
        return super().message_process(
            model, message, custom_values=custom_values, save_original=save_original,
            strip_attachments=strip_attachments, thread_id=thread_id)

    @api.model
    def _numa_keep_original(self, message, strip_attachments=False):
        """Store the incoming message as a ``mail.mail`` in 'received' state.

        Core's ``save_original`` attaches the raw source to the resulting
        ``mail.message``. This keeps a readable copy of its own, which is what survives
        when routing finds no destination for the mail.
        """
        parsed = self.message_parse(message, save_original=False)
        copy = self.env['mail.mail'].create({
            'message_type': 'email',
            'message_id': parsed['message_id'],
            'subject': parsed['subject'],
            'email_from': parsed['email_from'],
            'email_cc': parsed.get('cc'),
            'email_to': parsed.get('recipients'),
            'references': parsed.get('references'),
            'date': parsed.get('date'),
            'state': 'received',
            'body': parsed['body'],
            'body_html': parsed['body'],
        })
        if not strip_attachments and parsed.get('attachments'):
            copy.attachment_ids = [
                (0, 0, {'name': a.fname, 'raw': BinaryBytes(_as_bytes(a.content)),
                        'type': 'binary', 'description': a.fname})
                for a in parsed['attachments']
                if a.content is not None
            ]
        return copy
