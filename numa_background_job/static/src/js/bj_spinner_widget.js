/** @odoo-module **/


import { Component } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { serializeDateTime } from "@web/core/l10n/dates";
import { useBus, useService } from "@web/core/utils/hooks";

export class BJSpinner extends Component {
    static template = "numa_background_job.BJSpinner";
    static components = {};
    static defaultProps = { dynamicPlaceholder: false };
    static props = {
        ...standardFieldProps,
        spinner_name: {type: String, optional: true },
        spinner_state: {type: String, optional: true },
        state_msg: {type: String, optional: true },
        completion_rate: {type: Number, optional: true },
        current_status: {type: String, optional: true },
        error_msg: {type: String, optional: true },
        initialized_on: {type: String, optional: true },
        started_on: {type: String, optional: true },
        ended_on: {type: String, optional: true },
        aborted_on: {type: String, optional: true },
        context: { type: Object, optional: true },
        domain: { type: [Array, Function], optional: true },
    };

    setup() {
        super.setup();

        this.orm = useService("orm");
        this.busService = this.env.services.bus_service;

        this.name = parent.name;
        this.options = this.nodeOptions || {};

        const self = this;

        this.busService = this.env.services.bus_service;

        this.channel = "res.background.job"
        this.busService.addChannel(this.channel)
        this.busService.subscribe("notification", this._update_spinner.bind(this))
    }

    onWillUnmount() {
        this.busService.unsubscribe('res.background.job', 'notification');
        super.onWillUnmount();
    }

    async click_abort() {
        const orm = this.env.services.orm;

        let record_id = this.props.value && this.props.value[0];
        let self = this
        if (record_id) {
            this.orm.call(
                'res.background.job',
                'try_to_abort',
                [record_id]
            );

            this.spinner_state = 'aborting';
            this.render();
            const self = this;
            setTimeout(() => self._get_current_state(), 10000);

            if (this.spinner_state === 'started') {
                const self = this;
                setTimeout(() => self._get_current_state(), 10000);
            }
        }
    }

    async _update_spinner(vals) {
        vals = vals || {};
        this.spinner_name = vals.name || this.spinner_name;
        this.spinner_state = vals.state || this.state;
        this.completion_rate = vals.completion_rate || 0;
        this.current_status = vals.current_status || '';
        this.error_msg = vals.error || '';
        this.initialized_on = vals.initialized_on;
        this.started_on = vals.started_on;
        this.ended_on = vals.ended_on;
        this.aborted_on = vals.aborted_on;

        this.render();
    }

    async _get_current_state() {
        const orm = this.env.services.orm;

        let record_id = this.props.value && this.props.value[0];
        let self = this;
        if (record_id) {
            let values = await this.orm.call(
                'res.background_job',
                'read',
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

            this._update_spinner();
        }
    }
}

export const bjSpinnerField = {
    component: BJSpinner,
    displayName: _t("BJSpinner"),
    supportedOptions: [],
    supportedTypes: ["many2one"],
    extractProps: ({ attrs, field }, dynamicInfo) => {
        let state_msg = {
            init: _t('Initializing: ') + attrs.initialized_on,
            started: _t('Started: ') + attrs.started_on,
            ended: _t('Started: ') + attrs.started_on +
                _t(' - Ended: ') + attrs.ended_on +
                _t(' - Duration: ') + attrs.ended_on + '-' + attrs.started_on,
            aborting: _t('Aborting ...'),
            aborted: _t('Started: ') + attrs.started_on +
                _t(' - Aborted: ') + attrs.aborted_on +
                _t(' - Duration: ') + attrs.aborted_on + ' - ' + attrs.started_on
        }[attrs.spinner_state]

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
            aborted_on: attrs.aborted_on || '',
            context: dynamicInfo.context,
            domain: dynamicInfo.domain,
        };
    }
};

registry.category("fields").add("bj_spinner", bjSpinnerField);
