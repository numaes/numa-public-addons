/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";

export class PermissionMatrix extends Component {
    static template = "numa_roles.PermissionMatrix";

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        
        this.state = useState({
            roles: [],
            permissions: [],
            permissionsByCategory: {},
            matrix: {}, // { roleId: { permissionId: true/false } }
            loading: true,
            saving: new Set(), // Set of "roleId-permissionId" keys being saved
        });

        onWillStart(async () => {
            await this.loadData();
        });
    }

    /**
     * Loads roles and permissions from the backend.
     * Groups permissions by category for better visualization.
     */
    async loadData() {
        try {
            this.state.loading = true;

            // Load roles (numa_type = 'role')
            const roles = await this.orm.searchRead(
                "res.groups",
                [["numa_type", "=", "role"]],
                {
                    fields: ["id", "name", "display_name", "implied_ids"],
                    order: "name asc",
                }
            );

            // Load permissions (numa_type = 'permission')
            const permissions = await this.orm.searchRead(
                "res.groups",
                [["numa_type", "=", "permission"]],
                {
                    // [20.0] `res.groups.category_id` is gone; groups are scoped by
                    // `privilege_id` (res.groups.privilege), which carries the name.
                    fields: ["id", "name", "display_name", "privilege_id", "comment", "technical_code"],
                    order: "privilege_id asc, name asc",
                }
            );

            // A many2one comes back as [id, display_name], so the second element is
            // already the label and no second read is needed. The old code went to
            // `ir.module.category` for it.
            const categoryIds = [...new Set(permissions.map(p => p.privilege_id && p.privilege_id[0]).filter(Boolean))];
            const categories = permissions
                .filter(p => p.privilege_id)
                .map(p => ({ id: p.privilege_id[0], name: p.privilege_id[1] }));

            const categoryMap = {};
            categories.forEach(cat => {
                categoryMap[cat.id] = cat.name;
            });

            // Build permissions by category structure
            const permissionsByCategory = {};
            permissions.forEach(perm => {
                const categoryId = perm.privilege_id ? perm.privilege_id[0] : null;
                const categoryName = categoryId ? (categoryMap[categoryId] || "Unscoped") : "Unscoped";
                
                if (!permissionsByCategory[categoryName]) {
                    permissionsByCategory[categoryName] = [];
                }
                
                permissionsByCategory[categoryName].push({
                    ...perm,
                    categoryName: categoryName,
                });
            });

            // Build matrix: check which permissions are in each role's implied_ids
            const matrix = {};
            roles.forEach(role => {
                matrix[role.id] = {};
                const rolePermissionIds = role.implied_ids || [];
                permissions.forEach(perm => {
                    matrix[role.id][perm.id] = rolePermissionIds.includes(perm.id);
                });
            });

            this.state.roles = roles;
            this.state.permissions = permissions;
            this.state.permissionsByCategory = permissionsByCategory;
            this.state.matrix = matrix;
            this.state.loading = false;

        } catch (error) {
            console.error("Error loading permission matrix data:", error);
            this.notification.add(
                _t("Could not load the permission matrix"),
                { type: "danger" }
            );
            this.state.loading = false;
        }
    }

    /**
     * Toggles a permission for a role.
     * Updates the matrix state optimistically and saves to backend.
     */
    async onTogglePermission(roleId, permissionId) {
        const key = `${roleId}-${permissionId}`;
        
        // Prevent double-clicks
        if (this.state.saving.has(key)) {
            return;
        }

        const currentValue = this.state.matrix[roleId][permissionId];
        const newValue = !currentValue;

        // Optimistic update
        this.state.matrix[roleId][permissionId] = newValue;
        this.state.saving.add(key);

        try {
            // Get current implied_ids for the role
            const role = this.state.roles.find(r => r.id === roleId);
            const currentImpliedIds = role.implied_ids || [];

            // Update implied_ids
            let newImpliedIds;
            if (newValue) {
                // Add permission
                newImpliedIds = [...currentImpliedIds, permissionId];
            } else {
                // Remove permission
                newImpliedIds = currentImpliedIds.filter(id => id !== permissionId);
            }

            // Save to backend
            await this.orm.write("res.groups", [roleId], {
                implied_ids: [[6, 0, newImpliedIds]],
            });

            // Update role data
            role.implied_ids = newImpliedIds;

        } catch (error) {
            console.error("Error updating permission:", error);
            
            // Revert optimistic update
            this.state.matrix[roleId][permissionId] = currentValue;
            
            this.notification.add(
                _t("Could not update the permission"),
                { type: "danger" }
            );
        } finally {
            this.state.saving.delete(key);
        }
    }

    /**
     * Checks if a cell is currently being saved.
     */
    isSaving(roleId, permissionId) {
        return this.state.saving.has(`${roleId}-${permissionId}`);
    }

    /**
     * Gets the permission display name with tooltip info.
     */
    getPermissionTooltip(permission) {
        const parts = [permission.display_name];
        if (permission.technical_code) {
            parts.push(_t("Code: %s", permission.technical_code));
        }
        if (permission.comment) {
            parts.push(permission.comment);
        }
        return parts.join("\n");
    }

    /**
     * Gets category names sorted alphabetically.
     */
    get categoryNames() {
        return Object.keys(this.state.permissionsByCategory).sort();
    }
}

// Register as client action
registry.category("actions").add("numa_roles.matrix_action", PermissionMatrix);
