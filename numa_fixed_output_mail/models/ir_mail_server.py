from email.utils import parseaddr, formataddr

from odoo import api, fields, models, _
import logging

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
        """If current server has smtp_user and force_smtp_sender, rewrite headers.

        - Preserve display name from the existing 'From' header, if any.
        - Force address to self.smtp_user for 'From', 'Reply-To', and 'Return-Path'.
        """
        self.ensure_one()
        smtp_user = (self.smtp_user or '').strip()
        if not (self.force_smtp_sender and smtp_user):
            return message

        try:
            # Get display name from current From
            current_from = message.get('From') or ''
            display_name, _addr = parseaddr(current_from)
            # Fallback display name from company or server name if no name at all
            if not display_name:
                display_name = self.company_id and self.company_id.name or (self.name or '')

            forced_from = formataddr((display_name, smtp_user))

            # Replace or set headers safely
            for header, value in (
                ('From', forced_from),
                ('Reply-To', smtp_user),
                ('Return-Path', smtp_user),
            ):
                if message.get(header):
                    del message[header]
                message[header] = value

            _logger.debug(
                "[numa_fixed_output_mail] Forced sender headers via server %s (id=%s): From=%s, Reply-To=%s, Return-Path=%s",
                self.name,
                self.id,
                forced_from,
                smtp_user,
                smtp_user,
            )
        except Exception:  # pragma: no cover - log and continue
            _logger.exception("Failed to enforce SMTP sender headers; sending with original headers.")
        return message

    @api.model
    def send_email(self, message, mail_server_id=None, smtp_server=None, smtp_port=None,
                   smtp_user=None, smtp_password=None, smtp_encryption=None,
                   smtp_ssl_certificate=None, smtp_ssl_private_key=None,
                   smtp_debug=False, smtp_session=None):

        """Override to enforce headers prior to sending when flagged.

        Maintains standard behavior when not enabled or without smtp_user.
        """
        # Determine which server record is effectively used
        if mail_server_id:
            server = self.browse(mail_server_id)
        else:
            default_server, mail_from = self._find_mail_server(message.get('From', ''))
            if default_server:
                server = default_server
            else:
                # default to get default server from super; we still call super
                server = None

        if server and server.force_smtp_sender and server.smtp_user:
            message = server._force_sender_on_message(message)

        return super(IrMailServer, self).send_email(
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
