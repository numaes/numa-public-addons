/** @odoo-module **/


import {
    EventBus,
    Component,
} from "@odoo/owl";
import { _lt, _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

export class BJSpinner extends Component {
    setup() {
        super.setup();

        this.name = parent.name;
        this.options = this.nodeOptions || {};

        self = this;

        const bus_service = this.env.services.bus_service;
        bus_service.addChannel('res.background_job');
        bus_service.addEventListener('notification', ({ detail: notifications }) => {
            for (const { payload, type } of notifications) {
                if (type === 'background_job.state_change') {
                    self._get_current_state();
                }
            }
        });

        bus_service.start();
    }

    onWillUnmount() {
        core.bus.off('res.background_job', 'background_job', this._onNotification);
        super.onWillUnmount();
    }

    async click_abort() {
        const orm = this.env.services.orm;

        let record_id = this.props.value && this.props.value[0];
        let self = this
        if (record_id) {
            orm.try_to_abort(
                'res.background_job',
                [record_id]
            );

            this.spinner_state = 'aborting';
            this.render();
        }
    }

    async _get_current_state() {
        const orm = this.env.services.orm;

        let record_id = this.props.value && this.props.value[0];
        let self = this;
        if (record_id) {
            let values = await orm.read(
                'res.background_job',
                [record_id],
                [
                    'name',
                    'state',
                    'completion_rate',
                    'current_status',
                    'error',
                    'initialized_on',
                    'started_on',
                    'ended_on',
                    'aborted_on'
                ]
            );

            let vals = values[0];

            this.spinner_name = vals.name;
            this.spinner_state = vals.state;
            this.completion_rate = vals.completion_rate;
            this.current_status = vals.current_status;
            this.error_msg = vals.error;
            this.initialized_on = vals.initialized_on;
            this.started_on = vals.started_on;
            this.ended_on = vals.ended_on;
            this.aborted_on = vals.aborted_on;

            this.render();
        }
    }
}
BJSpinner.bus = new EventBus();

BJSpinner.template = "numa_background_job.bj_spinner";
BJSpinner.components = {
};
BJSpinner.defaultProps = { dynamicPlaceholder: false };
BJSpinner.props = {
    ...standardFieldProps,
    spinner_name: {type: String},
    spinner_state: {type: String},
    state_msg: {type: String},
    completion_rate: {type: Number},
    current_status: {type: String},
    error_msg: {type: String},
    initialized_on: {type: String},
    started_on: {type: String},
    ended_on: {type: String},
    aborted_on: {type: String}
};

BJSpinner.displayName = _lt("BJSpinner");
BJSpinner.supportedTypes = ["many2one"];

BJSpinner.extractProps = ({ attrs, field }) => {
    let state_msg = {
        init: _t('Initializing: ') + moment.utc(attrs.initialized_on).utcOffset(-3).format('DD-MM-YYYY HH:mm:ss'),
        started: _t('Started: ') + moment.utc(attrs.started_on).utcOffset(-3).format('DD-MM-YYYY HH:mm:ss'),
        ended: _t('Started: ') + moment.utc(attrs.started_on).utcOffset(-3).format('DD-MM-YYYY HH:mm:ss') +
            _t(' - Ended: ') + moment.utc(attrs.ended_on).utcOffset(-3).format('DD-MM-YYYY HH:mm:ss') +
            _t(' - Duración: ') + moment.utc(moment.utc(attrs.ended_on, 'DD-MM-YYYY HH:mm:ss.SSS').diff(moment.utc(attrs.started_on, 'DD-MM-YYYY HH:mm:ss.SSS'))).format('HH:mm:ss.SSS'),
        aborting: _t('Aborting ...'),
        aborted: _t('Started: ') + moment.utc(attrs.started_on).utcOffset(-3).format('DD-MM-YYYY HH:mm:ss') +
            _t(' - Aborted: ') + moment.utc(attrs.aborted_on).utcOffset(-3).format('DD-MM-YYYY HH:mm:ss') +
            _t(' - Duración: ') + moment.utc(moment.utc(attrs.aborted_on, 'DD-MM-YYYY HH:mm:ss.SSS').diff(moment.utc(attrs.started_on, 'DD-MM-YYYY HH:mm:ss.SSS'))).format('HH:mm:ss.SSS')
    }[attrs.spinner_state]
    if (!state_msg) {
        state_msg = '';
    }

    return {
        state_msg: state_msg || _t('Starting ...'),
        spinner_name: attrs.spinner_name || '...',
        spinner_state: attrs.spinner_state || 'init',
        completion_rate: attrs.completion_rate || 0,
        current_status: attrs.current_status || '...',
        error_msg: attrs.error_msg || '',
        initialized_on: attrs.initialized_on || '',
        started_on: attrs.started_on || '',
        ended_on: attrs.ended_on || '',
        aborted_on: attrs.aborted_on || ''
    };
};

registry.category("fields").add("bj_spinner", BJSpinner);

