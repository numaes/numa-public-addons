from odoo import models, fields, api, exceptions, _, SUPERUSER_ID
from datetime import timedelta
from odoo.addons import numa_exceptions

import logging

_logger = logging.getLogger(__name__)


class PeriodicServices(models.Model):
    _name = 'base.periodic_service'
    _description = 'Periodic Services'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char('Name')
    state = fields.Selection(
        [
            ('draft', 'Configuration'),
            ('testing', 'Testing'),
            ('running', 'In operation'),
            ('maintenance', 'Maintenance'),
            ('canceled', 'Canceled'),
        ],
        string='State',
        copy=False,
        tracking=3,
        default='draft',
        readonly=True,
    )

    type = fields.Selection(
        [],
        'Service type',
        readonly=True,
        states={'draft': [('readonly', False)]},
    )

    next_execution = fields.Datetime(
        'Next execution',
        readonly=True,
        states={'draft': [('readonly', False)],
                'testing': [('readonly', False)],
                'maintenance': [('readonly', True)]},
    )
    interval_value = fields.Integer(
        'Repetition interval',
        readonly=True,
        states={'draft': [('readonly', False)]},
    )
    interval_type = fields.Selection(
        [
            ('minutes', 'Minutes'),
            ('hours', 'Hours'),
            ('days', 'Days'),
        ],
        'Interval unit',
        readonly=True,
        states={'draft': [('readonly', False)]},
    )

    error_treatment = fields.Selection(
        [
            ('retry_forever', 'Retry forever'),
            ('retry_with_limit', 'Retry with limit'),
        ],
        'Error treatment',
        readonly=True,
        required=True,
        default='retry_forever',
        states={
            'draft': [('readonly', False)],
            'testing': [('readonly', False)],
            'maintenance': [('readonly', False)],
        },
    )

    error_count = fields.Integer('Current error count')
    error_limit = fields.Integer('Error count limit')

    def on_start_running(self):
        pass

    def on_stop_running(self):
        pass

    def action_test(self):
        for service in self:
            if service.state not in ['draft', 'running', 'maintenance']:
                continue

            if service.state in ['running', 'maintenance']:
                service.on_stop_running()

            service.state = 'testing'

    def action_into_operation(self):
        for service in self:
            if service.state not in ['draft', 'testing', 'maintenance']:
                continue

            if not service.next_execution or \
               not service.interval_type or \
               not service.interval_value:
                raise exceptions.UserError(
                    _('You must configure the next excecution point in time before going into operation')
                )

            service.on_start_running()

            service.state = 'running'

    def action_into_maintenance(self):
        for service in self:
            if service.state not in ['running']:
                continue

            service.state = 'maintenance'

    def action_cancel(self):
        for service in self:
            if service.state not in ['cancel']:
                continue

            service.state = 'canceled'

    def action_into_configuration(self):
        for service in self:
            if service.state not in ['testing', 'maintenance']:
                continue

            service.state = 'draft'

    def trigger(self):
        raise exceptions.UserError(_('Configuration error. At service trigger no processing could be executed.\n'
                                     'Please check the configuration of periodic service %s') % self.name)

    @api.model
    def dispatch(self):
        _logger.info('Starting periodic service dispatch')

        now = fields.Datetime.now()
        services_to_trigger = self.search(
            [
                ('state', '=', 'running'),
                ('next_execution', '!=', False),
                ('next_execution', '<=', now)
            ]
        )

        for service in services_to_trigger.sudo():
            now = fields.Datetime.now()
            zero_delta = timedelta(seconds=0)
            try:
                _logger.info(f'Starting periodic service {service.name}')
                service.trigger()
                _logger.info(f'Ending periodic service {service.name}')
                next_trigger = service.next_execution \
                    + (timedelta(minutes=service.interval_value)
                       if service.interval_type == 'minutes' else zero_delta) \
                    + (timedelta(hours=service.interval_value)
                       if service.interval_type == 'hours' else zero_delta) \
                    + (timedelta(days=service.interval_value)
                       if service.interval_type == 'days' else zero_delta)
                service.next_execution = next_trigger
                service.error_count = 0
                service.env.cr.commit()
            except Exception as e:
                service.env.cr.rollback()
                _logger.warning(f'Unexpected exception on service {service.name}, exception {e}')
                numa_exceptions.models.register_exception(
                    service.name,
                    'trigger',
                    [],
                    self.env.db,
                    self.env.user.id,
                    e
                )

                service.message_post(
                    subject=_('Unexpected exception executing service'),
                    body=_('Execution at %s: unexpected exception\n%s') % (now, e),
                )

                service.error_count += 1
                if service.error_treatment == 'retry_with_limit':
                    if service.error_count >= service.error_limit:
                        service.action_into_maintenance()

                service.env.cr.commit()

        _logger.info('Ending periodic service dispatch')

