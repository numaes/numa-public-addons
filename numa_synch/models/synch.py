from odoo import models, fields
from odoo import exceptions, api, _

import logging
_logger = logging.getLogger(__name__)


class SynchRemote(models.Model):
    _name = 'synch.remote'
    _description = 'Servidor remoto'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char('Name')
    type = fields.Selection([('undetermined', 'Indeterminado')], 'Type', required=True, default='undetermined')

    def getRemoteId(self, local_obj):
        self.ensure_one()
        linkModel = self.env['synch.link']
        irModelModel = self.env['ir.model']
        model = irModelModel.search([('name', '=', local_obj._name)], limit=1)
        return linkModel.getRemoteId(self, model, local_obj.id)

    def getLocalObj(self, model, remote_id):
        self.ensure_one()
        linkModel = self.env['synch.link']
        return linkModel.getLocalObj(self, model, remote_id)

    def setRemoteId(self, local_obj, remote_id):
        self.ensure_one()
        linkModel = self.env['synch.link']
        return linkModel.setRemoteId(self, local_obj, remote_id)

    def setLocalObj(self, remote_id, local_obj):
        self.ensure_one()
        linkModel = self.env['synch.link']
        return linkModel.setLocalId(self, remote_id, local_obj)

    def getTimestamp(self, modelName):
        self.ensure_one()
        timestampModel = self.env['synch.timestamp']
        irModelModel = self.env['ir.model']

        model = irModelModel.search([('name', '=', modelName)], limit=1)

        if model:
            ts = timestampModel.search([('remote', '=', self.id),
                                        ('model', '=', model.id)],
                                       limit=1)
            if ts:
                return ts.last_update
            else:
                return None
        else:
            raise UserWarning(_('Model non existent %s') % modelName)

    def setTimestamp(self, modelName, ts=None):
        self.ensure_one()
        timestampModel = self.env['synch.timestamp']

        irModelModel = self.env['ir.model']

        model = irModelModel.search([('name', '=', modelName)], limit=1)

        if model:
            if not ts:
                ts = fields.Datetime.now()

            tsRecord = timestampModel.search([('remote', '=', self.id),
                                              ('model', '=', model.id)],
                                             limit=1)
            if tsRecord:
                tsRecord.last_update = ts
            else:
                timestampModel.create(dict(
                    remote=self.id,
                    model=model.id,
                    last_update=ts,
                ))
        else:
            raise UserWarning(_('Model non existent %s') % modelName)


    def action_synch(self):
        raise exceptions.MissingError(_('Not implemented'))


class SynchLog(models.Model):
    _name = 'synch.log'
    _description = 'Log de remoto'
    _order = 'timestamp desc'

    remote = fields.Many2one('synch.remote', 'Remote')
    timestamp = fields.Datetime('Timestamp', default=fields.Datetime.now)
    message = fields.Text('Message')


class SynchLink(models.Model):
    _name = 'synch.link'
    _description = 'Vínculo objecto local/remoto'

    remote = fields.Many2one('synch.remote', 'Remote')
    model = fields.Many2one('ir.model', 'Model')
    remote_id = fields.Char('Remote ID')
    local_id = fields.Integer('Local ID')

    @api.model
    def getRemoteId(self, remote, model, local_id):
        link = self.search([('remote', '=', remote.id),
                            ('model', '=', model.id),
                            ('local_id', '=', local_id)], limit=1)

        return link.remote_id if link else None

    @api.model
    def getLocalObj(self, remote, model, remote_id):
        ir_modelModel = self.env['ir.model']
        irmodel = ir_modelModel.search([('name', '=', model._name)])

        link = self.search([('remote', '=', remote.id),
                            ('model', '=', irmodel.id),
                            ('remote_id', '=', remote_id)], limit=1)

        if link:
            obj = model.browse(link.local_id)

            if obj.exists():
                return obj
            else:
                link.unlink()

        return None

    @api.model
    def setRemoteId(self, remote, local_obj, remote_id):
        ir_modelModel = self.env['ir.model']
        model = ir_modelModel.search([('name', '=', local_obj._name)])

        link = self.search([('remote', '=', remote.id),
                            ('model', '=', model.id),
                            ('remote_id', '=', remote_id)], limit=1)
        if not link:
            link = self.create(dict(
                remote=remote.id,
                model=model.id,
                remote_id=remote_id,
                local_id=local_obj.id,
            ))

        return link

    @api.model
    def setLocalObj(self, remote, remote_id, local_obj):
        ir_modelModel = self.env['ir_model']
        model = ir_modelModel.search([('name', '=', local_obj._name)])

        link = self.search([('remote', '=', remote.id),
                            ('model', '=', model.id),
                            ('remote_id', '=', remote_id)])
        if link:
            link.local_id = local_obj.id
        else:
            self.create(dict(
                remote=remote_id,
                model=model.id,
                remote_id=remote_id,
                local_id= local_obj.id,
            ))


class SynchTimestamp(models.Model):
    _name = 'synch.timestamp'
    _description = 'Objecto remoto timestamp'

    remote = fields.Many2one('synch.remote', 'Remote')
    model = fields.Many2one('ir.model', 'Model')
    last_update = fields.Datetime('Last update')
