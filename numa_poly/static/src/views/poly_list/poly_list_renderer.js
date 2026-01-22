/** @odoo-module **/

import { ListRenderer } from "@web/views/list/list_renderer";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { Component, useState } from "@odoo/owl";

/**
 * Dialog component for selecting polymorphic subclass type
 */
class PolyTypeSelectionDialog extends Component {
    static template = "numa_poly.PolyTypeSelectionDialog";
    static components = { Dialog };
    static props = {
        subclasses: Array,
        onConfirm: Function,
        onCancel: Function,
        close: Function,
    };

    setup() {
        this.state = useState({ selectedModel: null });
    }

    onSelect(model) {
        this.state.selectedModel = model;
    }

    onConfirm() {
        if (this.state.selectedModel) {
            this.props.onConfirm(this.state.selectedModel);
            this.props.close();
        }
    }

    onCancel() {
        this.props.onCancel();
        this.props.close();
    }
}

/**
 * Polymorphic List Renderer
 * 
 * Extends ListRenderer to handle polymorphic record creation and navigation.
 * Key behaviors:
 * - Bypasses inline editing, opens records in dialogs
 * - Handles polymorphic navigation based on concrete_model_id
 * - Supports polymorphic creation with subclass selection
 */
export class PolyListRenderer extends ListRenderer {
    setup() {
        super.setup();
        this.actionService = useService("action");
        this.rpc = useService("rpc");
        this.dialog = useService("dialog");
    }

    /**
     * Override onCellClicked to bypass inline edit mode.
     * Directly opens the record instead of entering edit mode.
     */
    onCellClicked(column, record) {
        // Bypass edit mode, directly open the record
        this.onOpenRecord(record);
    }

    /**
     * Override onOpenRecord to handle polymorphic navigation.
     * Opens the concrete model's form view based on concrete_model_id.
     * 
     * Note: concrete_model_id is a Many2one to ir.model, so we need to
     * extract the model name from the record.
     */
    async onOpenRecord(record) {
        const concreteModelId = record.data.concrete_model_id;
        
        if (concreteModelId) {
            // concrete_model_id is a Many2one [id, display_name]
            // We need to get the model name from ir.model
            let modelName = null;
            
            if (Array.isArray(concreteModelId)) {
                // Many2one format: [id, display_name]
                // We need to fetch the model name via RPC
                const modelId = concreteModelId[0];
                if (modelId) {
                    try {
                        const modelData = await this.rpc("/web/dataset/call_kw", {
                            model: "ir.model",
                            method: "read",
                            args: [[modelId], ["model"]],
                            kwargs: {},
                        });
                        if (modelData && modelData[0]) {
                            modelName = modelData[0].model;
                        }
                    } catch (error) {
                        console.error("Error fetching model name:", error);
                    }
                }
            } else if (typeof concreteModelId === 'object' && concreteModelId.model) {
                // If the record already has the model field
                modelName = concreteModelId.model;
            } else if (typeof concreteModelId === 'string') {
                // Fallback: assume it's already the model name
                modelName = concreteModelId;
            }
            
            if (modelName) {
                // Open the concrete model's form view
                await this.actionService.doAction({
                    type: "ir.actions.act_window",
                    res_model: modelName,
                    res_id: record.resId,
                    views: [[false, "form"]],
                    target: "new", // Open in dialog
                    context: {
                        ...this.props.context,
                    },
                });
            } else {
                // Fallback to default behavior if we can't determine the model
                super.onOpenRecord(record);
            }
        } else {
            // Fallback to default behavior if no concrete_model_id
            super.onOpenRecord(record);
        }
    }

    /**
     * Override onAdd to handle polymorphic creation.
     * 
     * Flow:
     * 1. Fetch available subclasses via RPC
     * 2. If 0 subclasses: fallback to super.onAdd()
     * 3. If 1 subclass: directly open form for that subclass
     * 4. If >1 subclasses: show selection dialog, then open form
     * 5. When form is saved, backend create method processes poly_payload
     */
    async onAdd(ev) {
        try {
            // Step A: Fetch available subclasses
            const model = this.props.list.resModel;
            const subclasses = await this.rpc("/web/dataset/call_kw", {
                model: model,
                method: "get_poly_subclasses_info",
                args: [],
                kwargs: {},
            });

            // Step B: Handle based on number of subclasses
            if (!subclasses || subclasses.length === 0) {
                // Fallback to default behavior
                return super.onAdd(ev);
            }

            let selectedModel = null;
            if (subclasses.length === 1) {
                // Single subclass, use it directly
                selectedModel = subclasses[0].model;
            } else {
                // Multiple subclasses, show selection dialog
                selectedModel = await this._showTypeSelectionDialog(subclasses);
                if (!selectedModel) {
                    // User cancelled
                    return;
                }
            }

            // Step C: Open form dialog for the selected subclass
            // 
            // NOTE: The current implementation creates a virtual record with default values
            // and opens a form. For a production implementation, you may want to:
            // 1. Use a custom form component that captures data before save
            // 2. Intercept the form's save action to extract data
            // 3. Use a two-step process: form -> capture -> inject payload -> create virtual record
            //
            // Current approach: Create virtual record with defaults, then open form.
            // The backend's create method will process poly_payload when the parent is saved.
            
            // Get default values for the selected model
            const defaultValues = await this.rpc("/web/dataset/call_kw", {
                model: selectedModel,
                method: "default_get",
                args: [],
                kwargs: {
                    context: {
                        ...this.props.context,
                        default_parent_id: this.props.record.resId,
                    },
                },
            });

            // Create initial payload with defaults and concrete_model_id
            const initialPayload = {
                concrete_model_id: selectedModel,
                ...defaultValues,
            };
            const jsonPayload = JSON.stringify(initialPayload);

            // Create a virtual record in the list with the payload
            // This allows the record to appear in the list immediately
            const commonValues = {
                concrete_model_id: selectedModel,
                poly_payload: jsonPayload,
            };

            // Add common display fields if available
            if (defaultValues && defaultValues.name) {
                commonValues.name = defaultValues.name;
            }

            // Create the virtual record
            await this.props.list.createRecord({
                values: commonValues,
            });

            // Open the form for the selected model
            // The user can fill it and save normally.
            // When the parent record is saved, the backend create method
            // will process the poly_payload and merge it with the form data.
            await this.actionService.doAction({
                type: "ir.actions.act_window",
                res_model: selectedModel,
                views: [[false, "form"]],
                target: "new",
                context: {
                    ...this.props.context,
                    create: true,
                    default_parent_id: this.props.record.resId,
                },
            });

        } catch (error) {
            console.error("Error in polymorphic onAdd:", error);
            // Fallback to default behavior on error
            return super.onAdd(ev);
        }
    }

    /**
     * Show dialog to select polymorphic subclass type
     */
    async _showTypeSelectionDialog(subclasses) {
        return new Promise((resolve) => {
            let resolved = false;
            const confirm = (model) => {
                if (!resolved) {
                    resolved = true;
                    resolve(model);
                }
            };
            const cancel = () => {
                if (!resolved) {
                    resolved = true;
                    resolve(null);
                }
            };
            
            this.dialog.add(PolyTypeSelectionDialog, {
                subclasses: subclasses,
                onConfirm: confirm,
                onCancel: cancel,
                close: () => {
                    if (!resolved) {
                        resolved = true;
                        resolve(null);
                    }
                },
            });
        });
    }
}

PolyListRenderer.template = "numa_poly.PolyListRenderer";
