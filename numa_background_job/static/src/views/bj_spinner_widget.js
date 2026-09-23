/** @odoo-module **/

/**
 * Background job widget: a progress bar, the last step reported, and a cancel button.
 *
 * Progress arrives over the bus. `res.background_job._notify_owner` sends a
 * `res.background_job/state` notification to the channel of the user who asked for the
 * job, so there is no channel to join here: the server already put the owner on it.
 * The initial state is read from the job itself on mount, since the form was loaded
 * before any notification was sent.
 */

import { BusPlugin } from "@bus/services/bus_plugin";
import { Component, onWillStart, onWillUnmount, proxy, usePlugin } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { deserializeDateTime, formatDateTime } from "@web/core/l10n/dates";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { ActionPlugin } from "@web/webclient/actions/action_plugin";

const NOTIFICATION_TYPE = "res.background_job/state";

const JOB_FIELDS = [
    "name",
    "state",
    "completion_rate",
    "current_status",
    "error",
    "initialized_on",
    "started_on",
    "ended_on",
    "aborted_on",
];

export class BJSpinner extends Component {
    static template = "numa_background_job.bj_spinner";
    static components = {};
    static props = {
        ...standardFieldProps,
        context: { type: Object, optional: true },
        domain: { type: [Array, Function], optional: true },
    };

    setup() {
        super.setup();

        this.orm = useService("orm");
        this.action = usePlugin(ActionPlugin);
        this.bus = usePlugin(BusPlugin);
        // Nothing has changed at mount time: what is read from the job came with the
        // form, so there is nothing to reload yet.
        this.mounted = false;

        this.state = proxy({
            spinner_name: "...",
            spinner_state: "init",
            state_msg: _t("Starting ..."),
            completion_rate: 0,
            current_status: "",
            error_msg: "",
            initialized_on: "",
            started_on: "",
            ended_on: "",
            aborted_on: "",
        });

        onWillStart(async () => {
            await this._getCurrentState();
            this.mounted = true;
        });

        // The owner hears about every job of theirs: only the one this widget shows matters.
        const onNotification = (payload) => {
            const id = this.jobId;
            if (!payload || (id && payload.id && payload.id !== id)) {
                return;
            }
            this._updateSpinner(payload);
        };
        const unsubscribe = this.bus.subscribe(NOTIFICATION_TYPE, onNotification);
        onWillUnmount(unsubscribe);
    }

    /** Id of the job this widget shows (the many2one on the record). */
    get jobId() {
        const value = this.props.record && this.props.record.data[this.props.name];
        if (!value) {
            return false;
        }
        return Array.isArray(value) ? value[0] : value.id || false;
    }

    // What the template reads. Getters, so the template keeps the names it always had
    // while the values come from the reactive state.
    get spinner_name() {
        return this.state.spinner_name;
    }
    get spinner_state() {
        return this.state.spinner_state;
    }
    get state_msg() {
        return this.state.state_msg;
    }
    get completion_rate() {
        return this.state.completion_rate;
    }
    get current_status() {
        return this.state.current_status;
    }
    get error_msg() {
        return this.state.error_msg;
    }

    /** How much is done, clamped to 0..100: the width of the coloured part. */
    get progress_pct() {
        const value = Math.round(Number(this.state.completion_rate) || 0);
        return Math.max(0, Math.min(100, value));
    }

    async click_abort() {
        const id = this.jobId;
        if (!id) {
            return;
        }
        await this.orm.call("res.background_job", "try_to_abort", [id]);
        this.state.spinner_state = "aborting";
        this.state.state_msg = _t("Aborting ...");
        // The job itself confirms it stopped, over the bus; if that never arrives, re-read.
        browser.setTimeout(() => this._getCurrentState(), 10000);
    }

    _updateSpinner(values) {
        values = values || {};
        const previous = this.state.spinner_state;
        Object.assign(this.state, {
            spinner_name: values.name || this.state.spinner_name,
            spinner_state: values.state || this.state.spinner_state,
            completion_rate: values.completion_rate || 0,
            current_status: values.current_status || "",
            error_msg: values.error || "",
            initialized_on: this._date(values.initialized_on) || this.state.initialized_on,
            started_on: this._date(values.started_on) || this.state.started_on,
            ended_on: this._date(values.ended_on) || this.state.ended_on,
            aborted_on: this._date(values.aborted_on) || this.state.aborted_on,
        });
        this.state.state_msg = this._stateMessage(this.state);
        if (this.mounted && previous !== "ended" && this.state.spinner_state === "ended") {
            this._reloadOnCompletion();
        }
    }

    /**
     * When a job ENDS WELL, the form still shows what was read when it was opened: the
     * record's state, its counters. The widget hears about the change over the bus, the
     * rest of the form does not, so the view is reloaded to show what was left behind.
     *
     * Only when it ends well. If it was cancelled or failed, nothing is touched: the user
     * has to be able to read the error and whatever was left half done.
     *
     * Nor is it reloaded while there are unsaved changes, which a reload would lose.
     */
    _reloadOnCompletion() {
        // A breath before reloading: the job commits its last batch right after saying
        // that it finished.
        browser.setTimeout(async () => {
            const record = this.props.record;
            if (record && (await record.isDirty())) {
                return; // unsaved changes: reloading would lose them
            }
            this.action.doAction({ type: "ir.actions.client", tag: "soft_reload" });
        }, 1500);
    }

    async _getCurrentState() {
        const id = this.jobId;
        if (!id) {
            return;
        }
        const values = await this.orm.read("res.background_job", [id], JOB_FIELDS);
        if (values && values.length) {
            this._updateSpinner(values[0]);
        }
    }

    /**
     * A job date, in the user's own timezone.
     *
     * Both the bus and the ORM send the date in UTC - the bus also sends the string
     * "False" when it is empty - so the widget used to show a time that did not match the
     * rest of the form: "Started: 20:00:57" next to an "Initialized 17:00:57" of the same
     * job.
     */
    _date(value) {
        if (!value || value === "False") {
            return "";
        }
        try {
            return formatDateTime(deserializeDateTime(value));
        } catch {
            return value; // unexpected format: better shown raw than lost
        }
    }

    /** What the state reads as, with whatever dates apply. */
    _stateMessage(data) {
        const messages = {
            init: _t("Initializing: ") + (data.initialized_on || ""),
            started: _t("Started: ") + (data.started_on || ""),
            ended:
                _t("Started: ") +
                (data.started_on || "") +
                _t(" - Ended: ") +
                (data.ended_on || ""),
            aborting: _t("Aborting ..."),
            aborted:
                _t("Started: ") +
                (data.started_on || "") +
                _t(" - Aborted: ") +
                (data.aborted_on || ""),
        };
        return messages[data.spinner_state] || _t("Starting ...");
    }
}

export const bjSpinnerField = {
    component: BJSpinner,
    displayName: _t("BJSpinner"),
    supportedOptions: [],
    supportedTypes: ["many2one"],
    extractProps: (_fieldInfo, dynamicInfo) => ({
        context: dynamicInfo.context,
        domain: dynamicInfo.domain,
    }),
};

registry.category("fields").add("bj_spinner", bjSpinnerField);
