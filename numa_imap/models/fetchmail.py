# -*- coding: utf-8 -*-
##############################################################################
#
#    NUMA Extreme Systems.
#  
#    Copyright (C) 2013 NUMA Extreme Systems (<http:www.numaes.com>).
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

from odoo import models, fields, api, _
from datetime import datetime, timedelta

import logging
_logger=logging.getLogger(__name__)

DT_FORMAT = "%Y-%m-%d %H:%M:%S"


class FetchmailServer(models.Model):
    """Incoming POP/IMAP mail server account"""

    _inherit = 'fetchmail.server'

    last_uid = fields.Integer('Last received UID')

    @api.multi
    def fetch_mail(self):
        """ WARNING: meant for cron usage only - will commit() after each email! """
        additionnal_context = {
            'fetchmail_cron_running': True
        }
        MailThread = self.env['mail.thread']

        def initial_date():
            return '1-Mar-2019'

            now = datetime.now()
            last_week = now - timedelta(seconds=60 * 60 * 24 * 7)
            monthNames = {
                1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr",
                5: "May", 6: "Jun", 7: "Jul", 8: "Aug",
                9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"
            }
            return f'{last_week.day}-{monthNames[last_week.month]}-{last_week.year}'

        for server in self:
            _logger.info('start checking for new emails on %s server %s', server.type, server.name)
            additionnal_context['default_fetchmail_server_id'] = server.id
            additionnal_context['default_message_type'] = 'email'
            count, failed = 0, 0
            imap_server = None
            selected = False
            if server.type == 'imap':
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
                                    f'(UID {(server.last_uid or 0) + 1}:* SENTSINCE {initial_date()})'
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
                                                     server.type,
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
                                             server.type,
                                             server.name,
                                             (count - failed),
                                             failed)
                                break
                        server.write({'date': fields.Datetime.now()})
                        server.env.cr.commit()
                except Exception:
                    _logger.info("General failure when trying to fetch mail from %s server %s.",
                                 server.type,
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

    fetchmail_server_id = fields.Many2one('fetchmail.server', "Inbound Mail Server", readonly=True, index=True, oldname='server_id')
