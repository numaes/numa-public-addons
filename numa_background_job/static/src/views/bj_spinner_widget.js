/** @odoo-module **/


import {
    useBus,
    useChildRef,
    useForwardRefToParent,
    useOwnedDialogs,
    useService,
} from "@web/core/utils/hooks";
import { _lt } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

const { Component, useRef } = owl;

export class BJSpinner extends Component {
    setup() {
        this.name = parent.name;
        this.options = this.nodeOptions || {};

        this.state = "init";
        this.completion_rate = 0;
        this.current_status = 'unknown';
        this.error_msg = '';
        this.widget_state = 'init';
        this.initialized_on = '';
        this.started_on = '';
        this.ended_on = '';
        this.aborted_on = '';

        onMounted(this.onMounted);
        onWillUnmount(this.onWillUnmount);
    }
    onMounted() {
        core.bus.on('onNotification', this, this._onNotification);
        this._get_current_state();
    }
    onWillUnmount() {
        core.bus.off('onNotification', this, this._barcodeScanned);
        this._super();
    }
    _click_abort(event) {
        let record_id = this.value || false;
        let self = this
        if (record_id) {
            return this._rpc({
                model: 'res.background_job',
                method: 'try_to_abort',
                args: [
                    [record_id],
                ],
            }).then(function (values) {
                self.state = 'aborting';
                resolve();
            });
        }
    }

    _get_current_state() {
        let record_id = this.value && this.value.res_id;
        let self = this;
        if (record_id) {
            return this._rpc({
                model: 'res.background_job',
                method: 'read',
                args: [
                    [record_id],
                    [
                        'state',
                        'completion_rate',
                        'current_status',
                        'error',
                        'initialized_on',
                        'started_on',
                        'ended_on',
                        'aborted_on'
                    ],
                ],
            }).then(function (values) {
                self.state = values[0]['state'];
                if (self.state === 'ended' || self.state === 'aborted') {
                    self.widget_state = 'ended';
                } else {
                    self.widget_state = 'running';
                }
                self.completion_rate = values[0]['completion_rate'];
                self.current_status = values[0]['current_status'];
                self.error_msg = values[0]['error'];
                self.initialized_on = values[0]['initialized_on'];
                self.started_on = values[0]['started_on'];
                self.ended_on = values[0]['ended_on'];
                self.aborted_on = values[0]['aborted_on'];

                this._onChange();
                this._render();

            });
        }
    }
}

BJSpinner.template = "numa_background_job.bj_spinner";
BJSpinner.components = {
};
BJSpinner.defaultProps = { dynamicPlaceholder: false };
BJSpinner.props = {
    ...standardWidgetProps,
    name: {type: String},
    state: {type: String},
    state_msg: {type: String},
    completion_rate: {type: Number},
    current_status: {type: String},
    error_msg: {type: String},
    widget_state: {type: String},
    initialized_on: {type: String},
    started_on: {type: String},
    ended_on: {type: String},
    aborted_on: {type: String},
};

BJSpinner.displayName = _lt("BJSpinner");
BJSpinner.supportedTypes = ["many2one"];

BJSpinner.extractProps = ({ attrs, field }) => {
    let state_msg = {
        init: _t('Initializing: ') + moment.utc(this.initialized_on).utcOffset(offset).format('DD-MM-YYYY HH:mm:ss'),
        started: _t('Started: ') + moment.utc(this.started_on).utcOffset(offset).format('DD-MM-YYYY HH:mm:ss'),
        ended: _t('Started: ') + moment.utc(this.started_on).utcOffset(offset).format('DD-MM-YYYY HH:mm:ss') + _t(' - Ended: ') + moment.utc(this.ended_on).utcOffset(offset).format('DD-MM-YYYY HH:mm:ss') + _t(' - Duración: ') + moment.utc(moment(this.ended_on, 'DD-MM-YYYY HH:mm:ss.SSS').diff(moment(this.started_on, 'DD-MM-YYYY HH:mm:ss.SSS'))).format('HH:mm:ss.SSS'),
        aborting: _t('Aborting ...'),
        aborted: _t('Started: ') + moment.utc(this.started_on).utcOffset(offset).format('DD-MM-YYYY HH:mm:ss') + _t(' - Aborted: ') + moment.utc(this.aborted_on).utcOffset(offset).format('DD-MM-YYYY HH:mm:ss') + _t(' - Duración: ') + moment.utc(moment(this.aborted_on, 'DD-MM-YYYY HH:mm:ss.SSS').diff(moment(this.started_on, 'DD-MM-YYYY HH:mm:ss.SSS'))).format('HH:mm:ss.SSS')
    }[this.state];
    if (!state_msg) {
        state_msg = '';
    }

    return {
        name: field.name,
        state: field.state,
        state_msg: state_msg,
        completion_rate: field.completion_rate,
        current_status: field.current_status,
        error_msg: field.error_msg,
        widget_state: field.widget_state,
        initialized_on: field.initialized_on,
        started_on: field.initialized_on,
        ended_on: field.ended_on,
        aborted_on: field.aborted_on,
    };
};

registry.category("fields").add("bj_spinner", BJSpinner);


odoo.define('numa_backgroud_job.bj_spinner_widget', function (require) {
    "use strict";
    /** @odoo-module **/
    let core = require('web.core');
    let AbstractField = require('web.AbstractField');

    var FieldBJSpinner = AbstractField.extend({
        supportedFieldTypes: ['many2one'],
        template: 'bj_spinner',
        events: _.extend({}, AbstractField.prototype.events, {
            'click': '_click_abort'
        }),

        init: function () {
            /* Execution widget: Attributes options:
            */
            this._super.apply(this, arguments);

            this.name = parent.name;
            this.options = this.nodeOptions || {};

            this.state = "init";
            this.completion_rate = 0;
            this.current_status = 'unknown';
            this.error_msg = '';
            this.widget_state = 'init';
            this.initialized_on = '';
            this.started_on = '';
            this.ended_on = '';
            this.aborted_on = '';
        },

        on_attach_callback() {
            core.bus.on('onNotification', this, this._onNotification);
            this._get_current_state();
        },

        destroy: function () {
            core.bus.off('onNotification', this, this._barcodeScanned);
            this._super();
        },

        start: function () {
            this._super.apply(this, arguments);
            this.get_current_state();
        },

        _click_abort: function (event) {
            let record_id = this.value || false;
            let self = this
            if (record_id) {
                return this._rpc({
                    model: 'res.background_job',
                    method: 'try_to_abort',
                    args: [
                        [record_id],
                    ],
                }).then(function (values) {
                    self.state = 'aborting';
                    resolve();
                });
            }
        },

        _get_current_state: function () {
            let record_id = this.value && this.value.res_id;
            let self = this;
            if (record_id) {
                return this._rpc({
                    model: 'res.background_job',
                    method: 'read',
                    args: [
                        [record_id],
                        [
                            'state',
                            'completion_rate',
                            'current_status',
                            'error',
                            'initialized_on',
                            'started_on',
                            'ended_on',
                            'aborted_on'
                        ],
                    ],
                }).then(function (values) {
                    self.state = values[0]['state'];
                    if (self.state === 'ended' || self.state === 'aborted') {
                        self.widget_state = 'ended';
                    } else {
                        self.widget_state = 'running';
                    }
                    self.completion_rate = values[0]['completion_rate'];
                    self.current_status = values[0]['current_status'];
                    self.error_msg = values[0]['error'];
                    self.initialized_on = values[0]['initialized_on'];
                    self.started_on = values[0]['started_on'];
                    self.ended_on = values[0]['ended_on'];
                    self.aborted_on = values[0]['aborted_on'];

                    this._onChange();
                    this._render();

                });
            }
        },

        _render: async function () {
            let tz = this.getSession().user_context.tz;
            let offset = 0;
            if (tz === 'America/Argentina/Buenos_Aires') {
                offset = -180;
            }
            let state_msg = {
                init: _t('Initializing: ') + moment.utc(this.initialized_on).utcOffset(offset).format('DD-MM-YYYY HH:mm:ss'),
                started: _t('Started: ') + moment.utc(this.started_on).utcOffset(offset).format('DD-MM-YYYY HH:mm:ss'),
                ended: _t('Started: ') + moment.utc(this.started_on).utcOffset(offset).format('DD-MM-YYYY HH:mm:ss') + _t(' - Ended: ') + moment.utc(this.ended_on).utcOffset(offset).format('DD-MM-YYYY HH:mm:ss') + _t(' - Duración: ') + moment.utc(moment(this.ended_on, 'DD-MM-YYYY HH:mm:ss.SSS').diff(moment(this.started_on, 'DD-MM-YYYY HH:mm:ss.SSS'))).format('HH:mm:ss.SSS'),
                aborting: _t('Aborting ...'),
                aborted: _t('Started: ') + moment.utc(this.started_on).utcOffset(offset).format('DD-MM-YYYY HH:mm:ss') + _t(' - Aborted: ') + moment.utc(this.aborted_on).utcOffset(offset).format('DD-MM-YYYY HH:mm:ss') + _t(' - Duración: ') + moment.utc(moment(this.aborted_on, 'DD-MM-YYYY HH:mm:ss.SSS').diff(moment(this.started_on, 'DD-MM-YYYY HH:mm:ss.SSS'))).format('HH:mm:ss.SSS')
            }[this.state];
            if (!state_msg) {
                state_msg = '';
            }
            this.$el.find(".o_bjprogressbar_state").text(state_msg);
            this.$el.find(".o_bjprogressbar_value").text(this.completion_rate + ' %');
            this.$el.find(".o_bjprogressbar_indicator").width((this.completion_rate || 0) + '%');
            this.$el.find(".o_bjprogressbar_message").html(this.current_status || ' ');
            this.$el.find(".o_bjprogressbar_error").html('<pre>' + (this.error_msg || ' ') + '</pre>');
            this.$el.find(".o_bjprogressbar_indicator").css('background-color', '#C0C0C0');

            if (this.state === 'started') {
                this.$el.find(".o_bjprogressbar").show();
                this.$el.find(".o_bjprogressbar_indicator").css('background-color', '#C0C0C0');
                this.$el.find(".o_bjprogressbar_abort").show();
                this.$el.find(".o_bjprogressbar_message").show();
                this.$el.find(".o_bjprogressbar_error").hide();
            } else if (this.state === 'aborted' || this.state === 'aborting') {
                this.$el.find(".o_bjprogressbar").show();
                this.$el.find(".o_bjprogressbar_indicator").css('background-color', '#C080C0');
                this.$el.find(".o_bjprogressbar_abort").hide();
                this.$el.find(".o_bjprogressbar_message").show();
                this.$el.find(".o_bjprogressbar_error").show();
            } else if (this.state === 'init') {
                this.$el.find(".o_bjprogressbar").show();
                this.$el.find(".o_bjprogressbar_abort").show();
                this.$el.find(".o_bjprogressbar_message").show();
                this.$el.find(".o_bjprogressbar_error").hide();
            } else if (this.state === 'ended') {
                this.$el.find(".o_bjprogressbar").show();
                this.$el.find(".o_bjprogressbar_abort").hide();
                this.$el.find(".o_bjprogressbar_indicator").css('background-color', '#80C080');
                this.$el.find(".o_bjprogressbar_message").show();
                this.$el.find(".o_bjprogressbar_error").show();
            } else {
                this.$el.find(".o_bjprogressbar_state").text(state_msg);
                this.$el.find(".o_bjprogressbar").show();
                this.$el.find(".o_bjprogressbar_abort").hide();
                this.$el.find(".o_bjprogressbar_message").hide();
                this.$el.find(".o_bjprogressbar_error").hide();
            }
        },

        _onNotification: function (notifications) {
            let self = this;
            _.each(notifications, function (notification) {
                self._handleNotification(notification);
            });
        },

        _handleNotification: function (notification) {
            if (notification[0] === 'res.background_job') {
                let current_state = notification[1];
                if (this.value && current_state['id'] === this.value.res_id) {
                    this.state = current_state['state'];
                    this.completion_rate = current_state['completion_rate'];
                    this.current_status = current_state['current_status'];
                    this.error_msg = current_state['error'];
                    this.initialized_on = current_state['initialized_on'];
                    this.started_on = current_state['started_on'];
                    this.ended_on = current_state['ended_on'];
                    this.aborted_on = current_state['aborted_on'];
                    this._render();
                }
            }
        },
    });

    /**
     * Registry of form fields, called by :js:`instance.web.FormView`.
     *
     * All referenced classes must implement FieldInterface. Those represent the classes whose instances
     * will substitute to the <field> tags as defined in OpenERP's views.
     */

    return {
        bj_spinner: FieldBJSpinner,
    };

});

