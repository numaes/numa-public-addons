# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class ResGroups(models.Model):
    """
    Extension of res.groups to implement RBAC (Role-Based Access Control).
    
    This module separates the concepts of "Roles" and "Permissions" while
    maintaining technical compatibility with Odoo's native res.groups model.
    
    Architecture:
    - Permissions: Atomic access units (e.g., 'perm_approve_discount'). 
                   Not assigned directly to users.
    - Roles: Collections of permissions (e.g., 'role_sales_manager'). 
             Assigned to users.
    - System: Native Odoo groups (Legacy).
    """
    _inherit = 'res.groups'

    numa_type = fields.Selection(
        [
            ('role', 'Rol'),
            ('permission', 'Permiso'),
            ('system', 'Sistema/Legacy'),
        ],
        string='Tipo',
        required=True,
        default='system',
        help="Tipo de grupo: Rol (asignable a usuarios), Permiso (unidad atómica), "
             "o Sistema (grupos nativos de Odoo)"
    )

    technical_code = fields.Char(
        string='Código Técnico',
        readonly=True,
        copy=False,
        help="Código técnico único e inmutable para permisos. "
             "Solo requerido si tipo es 'permission'. "
             "Ejemplo: 'perm_approve_discount', 'perm_view_dashboard'"
    )

    is_template = fields.Boolean(
        string='Es Plantilla',
        default=False,
        help="Marca roles que vienen definidos por código vs roles creados por usuario. "
             "Útil para distinguir roles del sistema de roles personalizados."
    )

    # Computed field to show permission count for roles
    permission_count = fields.Integer(
        string='Permisos',
        compute='_compute_permission_count',
        help="Número de permisos incluidos en este rol"
    )

    @api.depends('implied_ids', 'implied_ids.numa_type')
    def _compute_permission_count(self):
        """Compute the number of permissions included in this role."""
        for group in self:
            if group.numa_type == 'role':
                # Count only permissions (not other roles or system groups)
                group.permission_count = len(
                    group.implied_ids.filtered(lambda g: g.numa_type == 'permission')
                )
            else:
                group.permission_count = 0

    @api.constrains('numa_type', 'users')
    def _check_permission_no_users(self):
        """
        Constraint: A permission (numa_type='permission') cannot have users assigned.
        
        Permissions are atomic units that should only be included in roles,
        not assigned directly to users.
        """
        for group in self:
            if group.numa_type == 'permission' and group.users:
                raise ValidationError(
                    _("Un permiso (tipo 'permission') no puede tener usuarios asignados directamente. "
                      "Los permisos deben ser incluidos en roles, y los roles son los que se asignan a usuarios.\n\n"
                      "Grupo: %s") % group.name
                )

    @api.constrains('numa_type', 'implied_ids', 'implied_ids.numa_type')
    def _check_permission_no_role_inheritance(self):
        """
        Constraint: A permission cannot inherit from a role (avoid logical cycles).
        
        Permissions should only inherit from other permissions or system groups,
        not from roles. This maintains the logical hierarchy: Roles -> Permissions -> System.
        """
        for group in self:
            if group.numa_type == 'permission':
                # Check if any implied group is a role
                role_implied = group.implied_ids.filtered(lambda g: g.numa_type == 'role')
                if role_implied:
                    raise ValidationError(
                        _("Un permiso no puede heredar de un rol. "
                          "La jerarquía lógica es: Roles -> Permisos -> Sistema.\n\n"
                          "Grupo: %s\n"
                          "Roles heredados incorrectamente: %s") % (
                            group.name,
                            ', '.join(role_implied.mapped('name'))
                        )
                    )

    @api.constrains('numa_type', 'technical_code')
    def _check_technical_code_required(self):
        """
        Constraint: technical_code is required and unique for permissions.
        
        Permissions must have a technical_code to ensure they can be referenced
        programmatically and to avoid duplicates.
        """
        for group in self:
            if group.numa_type == 'permission':
                if not group.technical_code:
                    raise ValidationError(
                        _("El campo 'Código Técnico' es obligatorio para permisos.\n\n"
                          "Grupo: %s") % group.name
                    )
                
                # Check uniqueness (excluding self)
                duplicate = self.search([
                    ('technical_code', '=', group.technical_code),
                    ('id', '!=', group.id),
                    ('numa_type', '=', 'permission')
                ], limit=1)
                
                if duplicate:
                    raise ValidationError(
                        _("El código técnico '%s' ya existe para otro permiso.\n\n"
                          "Grupo actual: %s\n"
                          "Grupo existente: %s") % (
                            group.technical_code,
                            group.name,
                            duplicate.name
                        )
                    )

    @api.constrains('technical_code')
    def _check_technical_code_immutable(self):
        """
        Constraint: technical_code cannot be changed once set (immutable).
        
        This ensures that programmatic references to permissions remain stable.
        """
        for group in self:
            if group.technical_code and group._origin.technical_code:
                if group.technical_code != group._origin.technical_code:
                    raise ValidationError(
                        _("El código técnico no puede ser modificado una vez establecido.\n\n"
                          "Grupo: %s\n"
                          "Código original: %s\n"
                          "Código intentado: %s") % (
                            group.name,
                            group._origin.technical_code,
                            group.technical_code
                        )
                    )

    @api.model_create_multi
    def create(self, vals_list):
        """
        Override create to set default numa_type and validate technical_code.
        """
        for vals in vals_list:
            # Set default numa_type if not provided
            if 'numa_type' not in vals:
                vals['numa_type'] = 'system'
            
            # For permissions, ensure technical_code is set
            if vals.get('numa_type') == 'permission' and not vals.get('technical_code'):
                # Try to generate from name if not provided
                if vals.get('name'):
                    # Generate technical_code from name: lowercase, replace spaces with underscores
                    name = vals['name'].lower().strip()
                    technical_code = 'perm_' + name.replace(' ', '_').replace('-', '_')
                    # Remove special characters
                    technical_code = ''.join(c for c in technical_code if c.isalnum() or c == '_')
                    vals['technical_code'] = technical_code
                    _logger.info(
                        f"Auto-generated technical_code '{technical_code}' for permission '{vals['name']}'"
                    )
        
        return super().create(vals_list)

    def write(self, vals):
        """
        Override write to prevent changing numa_type from permission to other types
        if technical_code is set, and to prevent changing technical_code.
        """
        # Prevent changing numa_type from 'permission' if technical_code exists
        if 'numa_type' in vals:
            for group in self:
                if group.numa_type == 'permission' and vals['numa_type'] != 'permission':
                    if group.technical_code:
                        raise ValidationError(
                            _("No se puede cambiar el tipo de un permiso que tiene código técnico.\n\n"
                              "Grupo: %s\n"
                              "Código técnico: %s") % (group.name, group.technical_code)
                        )
        
        # Prevent changing technical_code if it was already set
        if 'technical_code' in vals:
            for group in self:
                if group._origin.technical_code and vals['technical_code'] != group._origin.technical_code:
                    raise ValidationError(
                        _("El código técnico no puede ser modificado.\n\n"
                          "Grupo: %s") % group.name
                    )
        
        return super().write(vals)

    def unlink(self):
        """
        Prevent deletion of template roles/permissions (optional safety measure).
        """
        # Optional: Add protection for template records
        # Uncomment if you want to prevent deletion of template records
        # template_records = self.filtered('is_template')
        # if template_records:
        #     raise ValidationError(
        #         _("No se pueden eliminar roles/permisos que son plantillas del sistema.\n\n"
        #           "Registros: %s") % ', '.join(template_records.mapped('name'))
        #     )
        return super().unlink()
