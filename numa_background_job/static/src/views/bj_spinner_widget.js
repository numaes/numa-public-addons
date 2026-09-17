/** @odoo-module **/

/**
 * Widget del trabajo de fondo: barra de avance, último paso y botón de cancelar.
 *
 * El avance llega por el bus (`res.background_job.refresh_state` manda un `notification` al canal
 * `res.background_job` con el id del trabajo). El estado inicial se lee del propio trabajo al
 * montar: antes se tomaba de atributos del XML que nadie completa, así que el widget arrancaba
 * vacío hasta la primera notificación.
 */

import { Component, onWillStart, onWillUnmount, useState } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

const CAMPOS = [
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
    static defaultProps = { dynamicPlaceholder: false };
    static props = {
        ...standardFieldProps,
        spinner_name: { type: String, optional: true },
        spinner_state: { type: String, optional: true },
        state_msg: { type: String, optional: true },
        completion_rate: { type: Number, optional: true },
        current_status: { type: String, optional: true },
        error_msg: { type: String, optional: true },
        initialized_on: { type: String, optional: true },
        started_on: { type: String, optional: true },
        ended_on: { type: String, optional: true },
        aborted_on: { type: String, optional: true },
        context: { type: Object, optional: true },
        domain: { type: [Array, Function], optional: true },
    };

    setup() {
        super.setup();

        this.orm = useService("orm");
        this.action = useService("action");
        this.busService = this.env.services.bus_service;
        this.channel = "res.background_job";
        // Al montar todavía no hubo transición: lo que se lee del trabajo ya vino con el
        // formulario, así que no corresponde recargar nada.
        this.montado = false;

        this.state = useState({
            spinner_name: this.props.spinner_name || "...",
            spinner_state: this.props.spinner_state || "init",
            state_msg: this.props.state_msg || _t("Starting ..."),
            completion_rate: this.props.completion_rate || 0,
            current_status: this.props.current_status || "",
            error_msg: this.props.error_msg || "",
            initialized_on: this.props.initialized_on || "",
            started_on: this.props.started_on || "",
            ended_on: this.props.ended_on || "",
            aborted_on: this.props.aborted_on || "",
        });

        // El bus avisa el avance de TODOS los trabajos: sólo se atiende el que muestra este widget.
        this.onNotification = (payload) => {
            const id = this.jobId;
            if (!payload || (id && payload.id && payload.id !== id)) {
                return;
            }
            this._update_spinner(payload);
        };

        onWillStart(async () => {
            await this._get_current_state();
            this.montado = true;
        });

        if (this.busService) {
            this.busService.addChannel(this.channel);
            this.busService.subscribe("notification", this.onNotification);
            onWillUnmount(() => {
                this.busService.unsubscribe("notification", this.onNotification);
            });
        }
    }

    /** Id del trabajo que muestra el widget (el many2one del registro). */
    get jobId() {
        const valor = this.props.record && this.props.record.data[this.props.name];
        if (!valor) {
            return false;
        }
        return Array.isArray(valor) ? valor[0] : valor.id || false;
    }

    // Lo que lee la plantilla. Van como getters para que el template siga escribiéndose con los
    // nombres de siempre y los valores salgan del estado reactivo.
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

    /** Porcentaje ya recorrido, acotado a 0..100: es el ancho de la porción con color. */
    get progress_pct() {
        const valor = Math.round(Number(this.state.completion_rate) || 0);
        return Math.max(0, Math.min(100, valor));
    }

    async click_abort() {
        const id = this.jobId;
        if (!id) {
            return;
        }
        await this.orm.call("res.background_job", "try_to_abort", [id]);
        this.state.spinner_state = "aborting";
        this.state.state_msg = _t("Aborting ...");
        // El cierre lo confirma el propio trabajo por el bus; si no llegara, se relee.
        browser.setTimeout(() => this._get_current_state(), 10000);
    }

    _update_spinner(vals) {
        vals = vals || {};
        const anterior = this.state.spinner_state;
        Object.assign(this.state, {
            spinner_name: vals.name || this.state.spinner_name,
            spinner_state: vals.state || this.state.spinner_state,
            completion_rate: vals.completion_rate || 0,
            current_status: vals.current_status || "",
            error_msg: vals.error || "",
            initialized_on: vals.initialized_on || this.state.initialized_on,
            started_on: vals.started_on || this.state.started_on,
            ended_on: vals.ended_on || this.state.ended_on,
            aborted_on: vals.aborted_on || this.state.aborted_on,
        });
        this.state.state_msg = this._state_msg(this.state);
        if (this.montado && anterior !== "ended" && this.state.spinner_state === "ended") {
            this._recargar_al_terminar();
        }
    }

    /**
     * Cuando el trabajo TERMINA BIEN, el formulario sigue mostrando lo que se leyó al abrirlo (el
     * estado del registro, los contadores): el widget se entera por el bus, el resto no. Se recarga
     * la vista para que lo que se ve sea lo que quedó.
     *
     * Sólo al terminar bien. Si se canceló o falló, no se toca nada: el usuario tiene que poder
     * leer el mensaje de error y lo que quedó a medias.
     *
     * Tampoco se recarga si hay cambios sin guardar: recargar los perdería.
     */
    _recargar_al_terminar() {
        // Un respiro antes de recargar: el trabajo confirma su última tanda justo después de
        // avisar que terminó.
        browser.setTimeout(async () => {
            const registro = this.props.record;
            if (registro && (await registro.isDirty())) {
                return;         // hay cambios sin guardar: recargar los perdería
            }
            this.action.doAction({ type: "ir.actions.client", tag: "soft_reload" });
        }, 1500);
    }

    async _get_current_state() {
        const id = this.jobId;
        if (!id) {
            return;
        }
        const valores = await this.orm.read("res.background_job", [id], CAMPOS);
        if (valores && valores.length) {
            this._update_spinner(valores[0]);
        }
    }

    /** Descripción del estado, con las fechas que correspondan. */
    _state_msg(datos) {
        const mensajes = {
            init: _t("Initializing: ") + (datos.initialized_on || ""),
            started: _t("Started: ") + (datos.started_on || ""),
            ended:
                _t("Started: ") +
                (datos.started_on || "") +
                _t(" - Ended: ") +
                (datos.ended_on || ""),
            aborting: _t("Aborting ..."),
            aborted:
                _t("Started: ") +
                (datos.started_on || "") +
                _t(" - Aborted: ") +
                (datos.aborted_on || ""),
        };
        return mensajes[datos.spinner_state] || _t("Starting ...");
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
