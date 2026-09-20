# -*- coding: utf-8 -*-
import logging
from email.utils import formataddr, parseaddr

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class IrMailServer(models.Model):
    _inherit = 'ir.mail_server'

    force_smtp_sender = fields.Boolean(
        string="Force SMTP Sender",
        help=(
            "When enabled, outgoing messages sent via this server will use the SMTP user "
            "address as the From/Reply-To/Return-Path, preserving the original display name."
        ),
    )

    def _force_sender_on_message(self, message):
        """Rewrite the sender headers when this server asks for it.

        - Preserve the display name from the existing ``From`` header, if any.
        - Force the address to ``smtp_user`` for ``From``, ``Reply-To`` and
          ``Return-Path``.

        Forcing ``Return-Path`` is deliberate and worth knowing about: Odoo takes the
        bounce address from that header when it is set
        (``ir_mail_server._prepare_email_message__``), so bounces go to the SMTP user
        instead of the alias domain's bounce address. That is the point -- the
        departmental inbox gets them -- but it does override the default.
        """
        self.ensure_one()
        smtp_user = (self.smtp_user or '').strip()
        if not (self.force_smtp_sender and smtp_user):
            return message

        try:
            # Get the display name from the current From
            current_from = message.get('From') or ''
            display_name, _addr = parseaddr(current_from)
            # Fall back to the company or the server name when there is no name at all.
            # This used to read `self.company_id`, a field `ir.mail_server` does not have
            # and never had. The AttributeError landed in the `except` below, so a message
            # whose From carried no display name was returned UNTOUCHED -- the one case
            # this branch exists for. It was at least logged, as an "enforce failed".
            if not display_name:
                display_name = self.env.company.name or self.name or ''

            forced_from = formataddr((display_name, smtp_user))

            # Replace or set the headers safely
            for header, value in (
                ('From', forced_from),
                ('Reply-To', smtp_user),
                ('Return-Path', smtp_user),
            ):
                if message.get(header):
                    del message[header]
                message[header] = value

            _logger.debug(
                "[numa_fixed_output_mail] Forced sender headers via server %s (id=%s): "
                "From=%s, Reply-To=%s, Return-Path=%s",
                self.name, self.id, forced_from, smtp_user, smtp_user,
            )
        except Exception:  # pragma: no cover - log and continue
            _logger.exception(
                "Failed to enforce SMTP sender headers; sending with original headers.")
        return message

    @api.model
    def send_email(self, message, mail_server_id=None, smtp_server=None, smtp_port=None,
                   smtp_user=None, smtp_password=None, smtp_encryption=None,
                   smtp_ssl_certificate=None, smtp_ssl_private_key=None,
                   smtp_debug=False, smtp_session=None):
        """Enforce the headers before sending, when the server asks for it.

        The rewrite has to happen before ``super()``, not inside
        ``_prepare_email_message__``: ``send_email`` opens the SMTP session with
        ``smtp_from=message['From']`` (``ir_mail_server.py:814``), so a From rewritten
        any later would authenticate under the old address.

        Behaviour is unchanged when the flag is off or there is no ``smtp_user``.
        """
        # Determine which server record is effectively used
        if mail_server_id:
            server = self.browse(mail_server_id)
        else:
            default_server, _mail_from = self._find_mail_server(message.get('From', ''))
            server = default_server or None

        if server and server.force_smtp_sender and server.smtp_user:
            message = server._force_sender_on_message(message)

        return super().send_email(
            message,
            mail_server_id=mail_server_id,
            smtp_server=smtp_server,
            smtp_port=smtp_port,
            smtp_user=smtp_user,
            smtp_password=smtp_password,
            smtp_encryption=smtp_encryption,
            smtp_ssl_certificate=smtp_ssl_certificate,
            smtp_ssl_private_key=smtp_ssl_private_key,
            smtp_debug=smtp_debug,
            smtp_session=smtp_session,
        )
