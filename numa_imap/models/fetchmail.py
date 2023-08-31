import email
import base64

try:
    from xmlrpc import client as xmlrpclib
except ImportError:
    import xmlrpclib

from odoo import models, fields, api, _
from datetime import datetime, date, timedelta

import logging

_logger = logging.getLogger(__name__)

DT_FORMAT = "%Y-%m-%d %H:%M:%S"


class FetchmailServer(models.Model):
    """Incoming POP/IMAP mail server account"""

    _inherit = 'fetchmail.server'

    last_uid_validity = fields.Integer('Last validity identifier')
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
                from_day = fields.Date.today() - timedelta(days=7)

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
                                response, folder_data = imap_server.select(folder_name)
                                current_uid_validity = int(imap_server.response('UIDVALIDITY')[1][0])

                                selected = True
                                first_uid = ((server.last_uid or 0) \
                                                 if server.last_uid_validity and \
                                                    current_uid_validity == server.last_uid_validity else 0) + 1

                                _logger.info(f'IMAP Server: '
                                             f'current_uid_validity: {current_uid_validity}, '
                                             f'server.uid_validity: {server.last_uid_validity}, '
                                             f'first_uid: {first_uid}, server.last_uid: {server.last_uid}')

                                if server.last_uid and current_uid_validity == server.last_uid_validity:
                                    result, data = imap_server.search(
                                        None,
                                        f'(UID {first_uid}:*)'
                                    )
                                    newMsgs = sorted([int(m) for m in data[0].split() if int(m) > server.last_uid])
                                else:
                                    result, data = imap_server.search(
                                        None,
                                        f'(SINCE {initial_date(server)})'
                                    )
                                    newMsgs = sorted([int(m) for m in data[0].split()])

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
                                    if current_uid_validity != server.last_uid_validity:
                                        server.last_uid_validity = current_uid_validity

                                    _logger.info(f'IMAP Server: last_uid: {server.last_uid}, '
                                                 f'last_uid_validity:{server.last_uid_validity}')

                                    self.env.cr.commit()
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


