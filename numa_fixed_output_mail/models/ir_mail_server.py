# -*- coding: utf-8 -*-
import logging
from email.utils import formataddr, parseaddr

from odoo import api, fields, models
from odoo.tools.mail import email_domain_extract, email_normalize

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

    def _numa_owner_company(self):
        """The company this mailbox belongs to, or an empty recordset.

        Outgoing mail servers are not company-scoped in Odoo: what ties a mailbox to a
        company is its **domain**. Each company points at a ``mail.alias.domain``
        (``res.company.alias_domain_id``), so the domain of ``smtp_user`` answers the
        question, and it answers it the same way from a cron as from a user session --
        which ``self.env.company`` does not.
        """
        self.ensure_one()
        domain = email_domain_extract(email_normalize(self.smtp_user or '') or '')
        if not domain:
            return self.env['res.company']
        alias_domain = self.env['mail.alias.domain'].sudo().search(
            [('name', '=ilike', domain)], limit=1)
        return alias_domain.company_ids[:1]

    def _numa_may_force(self, email_from):
        """Whether this server may claim ``email_from`` as its own.

        A ``from_filter`` is the server's statement about which addresses it sends for.
        When it is set and the address is outside it, this server was picked as a
        fallback -- ``_find_mail_server`` returns one anyway, logging that nothing
        matched -- and forcing the sender there would take one company's mail out of
        another company's mailbox. In a multi-company database where the companies do
        not share a domain, that is the failure this whole module exists to avoid, so
        the flag is not honoured in that case.

        With no ``from_filter`` the server makes no claim, and the switch is taken at
        face value: that is the single-company setup, where there is nothing to cross.
        """
        self.ensure_one()
        if not self.from_filter:
            return True
        return self._match_from_filter(email_from, self.from_filter)

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

        if not self._numa_may_force(message.get('From') or ''):
            _logger.warning(
                "[numa_fixed_output_mail] Not forcing the sender: %s is outside the "
                "from_filter of server %s (%s). This server was a fallback for an "
                "address it does not serve; rewriting From to %s would send it out of "
                "another mailbox.",
                message.get('From'), self.name, self.from_filter, smtp_user)
            return message

        try:
            # Get the display name from the current From
            current_from = message.get('From') or ''
            display_name, _addr = parseaddr(current_from)
            # Fall back to the company that owns this mailbox, then to the server's own
            # name, when there is no display name at all.
            # This used to read `self.company_id`, a field `ir.mail_server` does not have
            # and never had. The AttributeError landed in the `except` below, so a message
            # whose From carried no display name was returned UNTOUCHED -- the one case
            # this branch exists for. It was at least logged, as an "enforce failed".
            if not display_name:
                company = self._numa_owner_company()
                display_name = company.name or self.name or ''

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
