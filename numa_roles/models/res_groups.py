# -*- coding: utf-8 -*-
"""RBAC on top of ``res.groups``: roles are assigned, permissions are not.

Odoo has one concept where role-based access control has two. A group both *grants*
something and *is granted* to people, so a security model written in groups says what
someone can do only by listing every group they carry, and nothing keeps that list from
drifting into a pile.

This module does not add a mechanism -- everything still runs on ``res.groups`` and
``implied_ids``, and nothing here is needed at runtime for access checks. It adds a
**discipline**, and enforces it:

* a **permission** is an atomic unit of access, carries a stable ``technical_code``, and
  is never assigned to a user directly;
* a **role** is a named bundle of permissions, and is the only thing a user gets;
* a **system** group is a native Odoo group, left alone.

[20.0] A word on naming, because core took the word. Odoo 20 replaced ``ir.model.access``
and ``ir.rule`` with ``ir.access``, whose ``kind`` is ``permission`` or ``restriction``.
That is a permission on **one model**; a permission here is a group that bundles several
of those and means something to the business ("approve a discount"). They sit at different
levels and both names are right in their own vocabulary.
"""
import logging

from odoo import _, api, fields, models, SUPERUSER_ID
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

TYPE_ROLE = 'role'
TYPE_PERMISSION = 'permission'
TYPE_SYSTEM = 'system'


class ResGroups(models.Model):
    _inherit = 'res.groups'

    numa_type = fields.Selection(
        [
            (TYPE_ROLE, 'Role'),
            (TYPE_PERMISSION, 'Permission'),
            (TYPE_SYSTEM, 'System / Legacy'),
        ],
        string='Type',
        required=True,
        default=TYPE_SYSTEM,
        index=True,
        help="Role: assigned to users, and bundles permissions.\n"
             "Permission: an atomic unit of access, never assigned to a user directly.\n"
             "System: a native Odoo group, left as it is.",
    )

    technical_code = fields.Char(
        string='Technical Code',
        copy=False,
        index='btree_not_null',
        help="Stable identifier for a permission, so that code can ask for it by name "
             "instead of by database id. Required for permissions, and immutable once "
             "set. For example: 'perm_approve_discount'.",
    )

    is_template = fields.Boolean(
        string='Is a Template',
        default=False,
        help="Marks what came from code rather than from somebody using the interface. "
             "Useful when reviewing what a database has grown on top of what was shipped.",
    )

    permission_count = fields.Integer(
        string='Permissions',
        compute='_compute_permission_count',
        help="How many permissions this role bundles, counting the ones it reaches "
             "through other roles.",
    )

    _technical_code_unique = models.UniqueIndex(
        '(technical_code) WHERE technical_code IS NOT NULL',
        'A technical code identifies one permission, and it is already taken.',
    )

    # ------------------------------------------------------------------
    # Computed
    # ------------------------------------------------------------------

    @api.depends('numa_type', 'all_implied_ids', 'all_implied_ids.numa_type')
    def _compute_permission_count(self):
        """Count the permissions a role reaches, not only the ones it names.

        [20.0] Over ``all_implied_ids``, the transitive closure Odoo 20 exposes
        (``res_groups.py:79``). Counting only ``implied_ids`` answered a different
        question -- how many permissions somebody typed into this form -- and a role
        built out of other roles reported zero.
        """
        for group in self:
            if group.numa_type == TYPE_ROLE:
                group.permission_count = len(
                    group.all_implied_ids.filtered(lambda g: g.numa_type == TYPE_PERMISSION))
            else:
                group.permission_count = 0

    # ------------------------------------------------------------------
    # The rules of the discipline
    # ------------------------------------------------------------------

    @api.constrains('numa_type', 'user_ids')
    def _check_permission_no_users(self):
        """A permission is not assigned to anybody: roles are.

        [20.0] The field is ``user_ids``; ``res.groups.users`` does not exist any more
        (``res_groups.py:23``). An ``@api.constrains`` naming a field that is not there
        fails at registry setup, so this module did not install at all.
        """
        for group in self:
            if group.numa_type == TYPE_PERMISSION and group.user_ids:
                raise ValidationError(_(
                    "A permission cannot be assigned to users directly. Put it in a role "
                    "and assign the role.\n\nPermission: %(name)s\nUsers: %(users)s",
                    name=group.name,
                    users=', '.join(group.user_ids.mapped('login')),
                ))

    @api.constrains('numa_type', 'implied_ids', 'implied_ids.numa_type')
    def _check_permission_no_role_inheritance(self):
        """A permission does not contain a role: the hierarchy runs one way.

        Roles -> permissions -> system groups. A permission that pulled in a role would
        hand whoever holds it everything that role bundles, which is the pile this module
        exists to prevent.
        """
        for group in self:
            if group.numa_type != TYPE_PERMISSION:
                continue
            roles = group.implied_ids.filtered(lambda g: g.numa_type == TYPE_ROLE)
            if roles:
                raise ValidationError(_(
                    "A permission cannot include a role. The hierarchy is roles -> "
                    "permissions -> system groups.\n\nPermission: %(name)s\n"
                    "Roles it includes: %(roles)s",
                    name=group.name, roles=', '.join(roles.mapped('name')),
                ))

    @api.constrains('numa_type', 'technical_code')
    def _check_technical_code_required(self):
        """A permission without a code cannot be asked for by name."""
        for group in self:
            if group.numa_type == TYPE_PERMISSION and not group.technical_code:
                raise ValidationError(_(
                    "A permission needs a technical code, which is how code asks for "
                    "it.\n\nPermission: %(name)s", name=group.name))

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('numa_type') == TYPE_PERMISSION and not vals.get('technical_code'):
                vals['technical_code'] = self._numa_code_from_name(vals.get('name') or '')
                _logger.info("Derived technical code %r for permission %r",
                             vals['technical_code'], vals.get('name'))
        return super().create(vals_list)

    def write(self, vals):
        """Guard what must not move once it is set.

        The technical code is a name other code depends on, and the type of a permission
        is what keeps that name meaningful. Both are refused here rather than in an
        ``@api.constrains``: a constraint runs *after* the write, when the stored value
        is already the new one, so it has nothing to compare against. The module carried
        such a constraint and it could never fire -- ``_origin`` on a stored record
        returns the record itself (``models.py:5936``), so it compared a value to itself.
        """
        if 'technical_code' in vals:
            for group in self.filtered('technical_code'):
                if vals['technical_code'] != group.technical_code:
                    raise ValidationError(_(
                        "A technical code cannot be changed once it is set: other code "
                        "refers to it.\n\nPermission: %(name)s\nCurrent: %(current)s\n"
                        "Attempted: %(new)s",
                        name=group.name, current=group.technical_code,
                        new=vals['technical_code']))

        if vals.get('numa_type') and vals['numa_type'] != TYPE_PERMISSION:
            offenders = self.filtered(
                lambda g: g.numa_type == TYPE_PERMISSION and g.technical_code)
            if offenders:
                raise ValidationError(_(
                    "A permission with a technical code cannot stop being a permission: "
                    "code refers to it by that code.\n\n%(names)s",
                    names='\n'.join('%s (%s)' % (g.name, g.technical_code) for g in offenders)))

        return super().write(vals)

    # ------------------------------------------------------------------
    # The API other modules are meant to use
    # ------------------------------------------------------------------

    @api.model
    def _numa_code_from_name(self, name):
        """``'Approve Discount'`` -> ``'perm_approve_discount'``."""
        slug = (name or '').strip().lower().replace(' ', '_').replace('-', '_')
        slug = ''.join(c for c in slug if c.isalnum() or c == '_')
        return 'perm_%s' % slug if slug else ''

    @api.model
    def numa_permission(self, technical_code):
        """The permission with that code, or an empty recordset."""
        return self.sudo().search(
            [('numa_type', '=', TYPE_PERMISSION), ('technical_code', '=', technical_code)],
            limit=1)


class ResUsers(models.Model):
    _inherit = 'res.users'

    def has_permission(self, technical_code):
        """Whether this user holds the permission with that code.

        This is what makes the discipline usable from code: a business rule asks
        ``user.has_permission('perm_approve_discount')`` instead of naming a group's XML
        id, and the security model can be rearranged -- split a role, rename it, move the
        permission into a different bundle -- without touching the rule.

        [20.0] Answered with ``all_group_ids`` (``res_users.py:252``), the user's groups
        including everything they imply, so a permission reached through a role two
        levels up counts. Root holds everything, as everywhere else in Odoo.

        The question is about **this user**, not about how the code asking happens to be
        running. An earlier version short-circuited on ``self.env.su`` and therefore
        answered True for anybody whenever it was called from a sudo'd environment --
        which is most of the places a business rule runs. A permission check that says
        yes to everyone is worse than no permission check, because it looks like one.
        """
        self.ensure_one()
        if not technical_code:
            return False
        if self.id == SUPERUSER_ID:
            return True
        permission = self.env['res.groups'].numa_permission(technical_code)
        return bool(permission) and permission in self.sudo().all_group_ids
