import email
import base64
try:
    from xmlrpc import client as xmlrpclib
except ImportError:
    import xmlrpclib

from odoo import models, fields, api, _
from datetime import datetime, date, timedelta

import logging
_logger=logging.getLogger(__name__)

DT_FORMAT = "%Y-%m-%d %H:%M:%S"


class FetchmailServer(models.Model):
    """Incoming POP/IMAP mail server account"""

    _inherit = 'fetchmail.server'

    last_uid = fields.Integer('Last received UID')
    initially_from = fields.Date('Initial load, from date')

    def fetch_mail(self):
        """ WARNING: meant for cron usage only - will commit() after each email! """
        additionnal_context = {
            'fetchmail_cron_running': True
        }
        MailThread = self.env['mail.thread']

        def initial_date(fetchmail_server):
            if fetchmail_server.initially_from:
                from_day = fetchmail_server.initially_from
            else:
                from_day = fields.Date.today()

            monthNames = {
                1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr",
                5: "May", 6: "Jun", 7: "Jul", 8: "Aug",
                9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"
            }
            return f'{from_day.day}-{monthNames[from_day.month]}-{from_day.year}'

        for server in self:
            _logger.info('start checking for new emails on %s server %s', server.server_type, server.name)
            additionnal_context['default_fetchmail_server_id'] = server.id
            additionnal_context['default_message_type'] = 'email'
            count, failed = 0, 0
            imap_server = None
            selected = False
            if server.server_type == 'imap':
                try:
                    imap_server = server.connect()
                    response, data = imap_server.list()
                    if response == 'OK':
                        for entry in data:
                            flags, folder_name = entry.decode().split(' "/" ')
                            if '\\All' in flags:
                                imap_server.select(folder_name)
                                selected = True
                                result, data = imap_server.search(
                                    None,
                                    f'(UID {(server.last_uid or 0) + 1}:* SENTSINCE {initial_date(server)})'
                                )
                                newMsgs = sorted([int(m) for m in data[0].split() if int(m) > server.last_uid])
                                for num in newMsgs:
                                    _logger.info(f'Getting mail with UID {num} from server {server.name}')
                                    res_id = None
                                    result, data = imap_server.fetch(bytes(str(num), 'ascii'), '(BODY.PEEK[])')
                                    try:
                                        res_id = MailThread.with_context(**additionnal_context).message_process(
                                            server.object_id.model,
                                            data[0][1],
                                            save_original=server.original,
                                            strip_attachments=(not server.attach))
                                        _logger.info(f'Mail with UID {num} from server {server.name} was processed')
                                    except Exception:
                                        _logger.info('Failed to process mail from %s server %s.',
                                                     server.server_type,
                                                     server.name,
                                                     exc_info=True)
                                        failed += 1
                                    this_uid = int(num)
                                    if this_uid > (server.last_uid or 0):
                                        server.last_uid = int(num)
                                    self._cr.commit()
                                    count += 1
                                _logger.info("Fetched %d email(s) on %s server %s; %d succeeded, %d failed.",
                                             count,
                                             server.server_type,
                                             server.name,
                                             (count - failed),
                                             failed)
                                break
                        server.write({'date': fields.Datetime.now()})
                        server.env.cr.commit()
                except Exception:
                    _logger.info("General failure when trying to fetch mail from %s server %s.",
                                 server.server_type,
                                 server.name,
                                 exc_info=True)
                    server.env.cr.rollback()
                finally:
                    if imap_server:
                        if selected:
                            imap_server.close()
                        imap_server.logout()
            else:
                super(FetchmailServer, server).fetch_mail()
        return True


class MailMessage(models.Model):
    _inherit = "mail.message"

    fetchmail_server_id = fields.Many2one('fetchmail.server', "Inbound Mail Server", readonly=True, index=True)


class MailThread(models.AbstractModel):
    _inherit = 'mail.thread'

    @api.model
    def message_process(self, model, message, custom_values=None,
                        save_original=False, strip_attachments=False,
                        thread_id=None):
        """ Process an incoming RFC2822 email message, relying on
            ``mail.message.parse()`` for the parsing operation,
            and ``message_route()`` to figure out the target model.

            Once the target model is known, its ``message_new`` method
            is called with the new message (if the thread record did not exist)
            or its ``message_update`` method (if it did).

           :param string model: the fallback model to use if the message
               does not match any of the currently configured mail aliases
               (may be None if a matching alias is supposed to be present)
           :param message: source of the RFC2822 message
           :type message: string or xmlrpclib.Binary
           :type dict custom_values: optional dictionary of field values
                to pass to ``message_new`` if a new record needs to be created.
                Ignored if the thread record already exists, and also if a
                matching mail.alias was found (aliases define their own defaults)
           :param bool save_original: whether to keep a copy of the original
                email source attached to the message after it is imported.
           :param bool strip_attachments: whether to strip all attachments
                before processing the message, in order to save some space.
           :param int thread_id: optional ID of the record/thread from ``model``
               to which this mail should be attached. When provided, this
               overrides the automatic detection based on the message
               headers.
        """
        # extract message bytes - we are forced to pass the message as binary because
        # we don't know its encoding until we parse its headers and hence can't
        # convert it to utf-8 for transport between the mailgate script and here.
        if isinstance(message, xmlrpclib.Binary):
            message = bytes(message.data)
        if isinstance(message, str):
            message = message.encode('utf-8')
        message = email.message_from_bytes(message, policy=email.policy.SMTP)

        # parse the message, verify we are not in a loop by checking message_id is not duplicated
        msg_dict = self.message_parse(message, save_original=save_original)
        if strip_attachments:
            msg_dict.pop('attachments', None)

        existing_msg_ids = self.env['mail.message'].search([('message_id', '=', msg_dict['message_id'])], limit=1)
        if existing_msg_ids:
            _logger.info('Ignored mail from %s to %s with Message-Id %s: found duplicated Message-Id during processing',
                         msg_dict.get('email_from'), msg_dict.get('to'), msg_dict.get('message_id'))
            return False

        if save_original:
            filtered_msg = dict(
                message_type='email',
                message_id=msg_dict['message_id'],
                subject=msg_dict['subject'],
                email_from=msg_dict['email_from'],
                email_cc=msg_dict['cc'],
                email_to=msg_dict['recipients'],
                references=msg_dict['references'],
                date=msg_dict['date'],
                state='received',
                body=msg_dict['body'],
                body_html=msg_dict['body'],
            )
            new_mail = self.env['mail.mail'].create(filtered_msg)
            if not strip_attachments:
                new_mail.attachment_ids = [
                    (0, 0, {'name': a.fname,
                            'datas': base64.b64encode(a.content) if isinstance(a.content, bytes) else
                                     a.content}) for a in msg_dict['attachments']
                ]
            self.env.cr.commit()

        # find possible routes for the message
        routes = self.message_route(message, msg_dict, model, thread_id, custom_values)
        thread_id = self._message_route_process(message, msg_dict, routes)
        return thread_id

