odoo.define('numa_backgroud_job.bj_spinner_widget', function (require) {
"use strict";

var bus_service = require('bus.BusService');
var core = require('web.core');
var Widget = require('web.Widget');
var fieldRegistry = require('web.field_registry')
var AbstractField = require('web.AbstractField');

var _t = core._t;
var QWeb = core.qweb;

var FieldBJSpinner = AbstractField.extend({
    supportedFieldTypes: ['many2one'],
    template: 'bj_spinner',
    events: {
        'click': 'click_abort'
    },

    init: function(parent, options) {
        /* Execution widget: Attributes options:
        */
        this._super.apply(this, arguments);

        this.name = parent.name;
                this.options = _.extend({
        }, options || {});

        this.state = "unknown";
        this.completion_rate = 0;
        this.current_status = 'desconocido';
        this.error_msg = '';
        this.widget_state = 'init';
        this.initialized_on = '';
        this.started_on = '';
        this.ended_on = '';
        this.aborted_on = '';
        this.call('bus_service', 'addChannel', 'res.background_job');
        this.call('bus_service', 'startPolling');
    },

    start: function() {
        this.get_current_state();
        this.call('bus_service', 'onNotification', this, this._onNotification);
    },

    destroy: function() {
        this.widget_state = 'ended';
        this._super.apply(this, arguments);
    },

    initialize_content: function () {
        var record_id = this.get('value');
        if (record_id) {
            this.widget_state = 'running';
        }
        this.field_manager.on("view_content_has_changed", this, this.get_current_state);
        this.get_current_state();
    },

    click_abort: function (event) {
        var classes = $(event.target).attr("class");
        if (classes == 'o_bjprogressbar_abort') {
            var record_id = this.get('value');
            var self = this
            if (record_id) {
                var model = new Model('res.background_job');
                return this._rpc({
                    model: 'res.background_job',
                    method: 'try_to_abort',
                    args: [
                        [record_id],
                    ],
                }).then(function (values) {
                    self.state = 'aborting';
                    self.render_value();
                });
            }
        }
    },

    get_current_state: function () {
        var record_id = this.value && this.value.res_id;
        var self = this
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
                        'error'
                    ],
                ],
            }).then(function (values) {
                self.state = values[0]['state'];
                if (self.state == 'ended' || self.state == 'aborted') {
                    self.widget_state = 'ended';
                }
                else {
                    self.widget_state = 'running';
                }
                self.completion_rate = values[0]['completion_rate'];
                self.current_status = values[0]['current_status'];
                self.error_msg = values[0]['error'];
                self.render_value();
            });
        };
    },

    render_value: function () {
        var state_msg = {
            init: _t('Initializing: ') + moment(this.initialized_on).format('DD-MM-YYYY HH:mm:ss'),
            started: _t('Started: ') + moment(this.started_on).format('DD-MM-YYYY HH:mm:ss'),
            ended: _t('Started: ') + moment(this.started_on).format('DD-MM-YYYY HH:mm:ss') + _t(' - Ended: ') + moment(this.ended_on).format('DD-MM-YYYY HH:mm:ss') + _t(' - Duración: ') + moment.utc(moment(this.ended_on, 'DD-MM-YYYY HH:mm:ss.SSS').diff(moment(this.started_on, 'DD-MM-YYYY HH:mm:ss.SSS'))).format('HH:mm:ss.SSS'),
            aborting: _t('Aborting ...'),
            aborted: _t('Started: ') + moment(this.started_on).format('DD-MM-YYYY HH:mm:ss') + _t(' - Aborted: ') + moment(this.aborted_on).format('DD-MM-YYYY HH:mm:ss') + _t(' - Duración: ') + moment.utc(moment(this.aborted_on, 'DD-MM-YYYY HH:mm:ss.SSS').diff(moment(this.started_on, 'DD-MM-YYYY HH:mm:ss.SSS'))).format('HH:mm:ss.SSS')
        }[this.state];
        if (!state_msg) {
            state_msg = '';
        }
        this.$el.find(".o_bjprogressbar_state").text(state_msg);
        this.$el.find(".o_bjprogressbar_value").text(this.completion_rate + ' %');
        this.$el.find(".o_bjprogressbar_indicator").width((this.completion_rate || 0) + '%');
        this.$el.find(".o_bjprogressbar_message").html(this.current_status || ' ');
        this.$el.find(".o_bjprogressbar_error").html('<pre>' + (this.error_msg || ' ') + '</pre>');
        this.$el.find(".o_bjprogressbar_indicator").css('background-color','#C0C0C0');

        if (this.state == 'started') {
            this.$el.find(".o_bjprogressbar").show();
            this.$el.find(".o_bjprogressbar_indicator").css('background-color','#C0C0C0');
            this.$el.find(".o_bjprogressbar_abort").show();
            this.$el.find(".o_bjprogressbar_message").show();
            this.$el.find(".o_bjprogressbar_error").hide();
        }
        else if (this.state == 'aborted' || this.state == 'aborting') {
            this.$el.find(".o_bjprogressbar").show();
            this.$el.find(".o_bjprogressbar_indicator").css('background-color','#C080C0');
            this.$el.find(".o_bjprogressbar_abort").hide();
            this.$el.find(".o_bjprogressbar_message").show();
            this.$el.find(".o_bjprogressbar_error").show();
        }
        else if (this.state == 'init') {
            this.$el.find(".o_bjprogressbar").show();
            this.$el.find(".o_bjprogressbar_abort").show();
            this.$el.find(".o_bjprogressbar_message").show();
            this.$el.find(".o_bjprogressbar_error").hide();
        }
        else if (this.state == 'ended') {
            this.$el.find(".o_bjprogressbar").show();
            this.$el.find(".o_bjprogressbar_abort").hide();
            this.$el.find(".o_bjprogressbar_indicator").css('background-color','#80C080');
            this.$el.find(".o_bjprogressbar_message").show();
            this.$el.find(".o_bjprogressbar_error").show();
        }
        else {
			this.$el.find(".o_bjprogressbar_state").text(state_msg);
            this.$el.find(".o_bjprogressbar").show();
            this.$el.find(".o_bjprogressbar_abort").hide();
            this.$el.find(".o_bjprogressbar_message").hide();
            this.$el.find(".o_bjprogressbar_error").hide();
        }
    },

    _onNotification: function (notifications) {
        var self = this;
        _.each(notifications, function (notification) {
            self._handleNotification(notification);
        });
    },

    _handleNotification: function(notification){
        if (notification[0] == 'res.background_job') {
            var current_state = notification[1];
            if (this.value && current_state['id'] == this.value.res_id) {
                this.state = current_state['state'];
                this.completion_rate = current_state['completion_rate'];
                this.current_status = current_state['current_status'];
                this.error_msg = current_state['error'];
                this.render_value();
            };
        }
    },
});

/**
 * Registry of form fields, called by :js:`instance.web.FormView`.
 *
 * All referenced classes must implement FieldInterface. Those represent the classes whose instances
 * will substitute to the <field> tags as defined in OpenERP's views.
 */

fieldRegistry.add('bj_spinner', FieldBJSpinner)

return {
    BJ_spinner: FieldBJSpinner,
};

});
