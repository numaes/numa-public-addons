from odoo import fields, models, api, tools, _, SUPERUSER_ID
from odoo.exceptions import ValidationError

import logging
_logger = logging.getLogger(__name__)


class GroupRoleCategory(models.Model):
	_name = 'res.group_role_category'
	_description = 'Group Role Category'
	_parent_name = "parent_category_id"
	_parent_store = True
	_rec_name = 'complete_name'
	_order = 'complete_name'

	name = fields.Char('Name', required=True)
	complete_name = fields.Char(
		'Complete Name', compute='_compute_complete_name',
		store=True)
	description = fields.Html('Description')
	active = fields.Boolean('Active', default=True)
	parent_category_id = fields.Many2many('res.group_category', 'Parent category')

	@api.depends('name', 'parent_id.complete_name')
	def _compute_complete_name(self):
		for category in self:
			if category.parent_id:
				category.complete_name = '%s / %s' % (category.parent_id.complete_name, category.name)
			else:
				category.complete_name = category.name

	@api.constrains('parent_id')
	def _check_category_recursion(self):
		if not self._check_recursion():
			raise ValidationError(_('You cannot create recursive role categories.'))
		return True

	@api.model
	def name_create(self, name):
		return self.create({'name': name}).name_get()[0]

	_sql_constraints = [('name_uniq', 'unique (name, parent_category_id)',
						 'Category name should be unique!')]


class Groups(models.Model):
	_inherit = 'res.groups'

	@tools.ormcache()
	def _get_default_role_category_id(self):
		# Deletion forbidden (at least through unlink)
		return self.env.ref('numa_role.group_category_all')

	def _read_group_role_category_id(self, categories, domain, order):
		category_model = self.env['res.group_role_category']

		role_category_ids = self.env.context.get('default_role_category_id')
		if not role_category_ids and self.env.context.get('group_expand'):
			role_category_ids = category_model._search([], order=order, access_rights_uid=SUPERUSER_ID)
		return category_model.browse(role_category_ids)

	is_role = fields.Boolean('Is a role?')
	role_category_id = fields.Many2one(
		'res.group_role_category', 'Category',
		change_default=True, default=_get_default_role_category_id, group_expand='_read_group_role_category_id',
		required=True, help="Select role category for the current role group")


class Users(models.Model):
	_inherit = 'res.users'

	def _default_groups(self):
		default_user = self.env.ref('base.default_user', raise_if_not_found=False)
		return (default_user or self.env['res.users']).sudo().groups_id

	role_ids = fields.Many2many(
		'res.groups', 'res_groups_users_rel', 'uid', 'gid',
		string='Roles',
		compute='get_role_ids',
		inverse='set_role_ids',
		domain=[('is_role', '=', True), ('active', '=', True)])

	def get_role_ids(self):
		group_model = self.env['res.group']

		for user in self:
			user.role_ids = group_model.browse([g.id for g in user.group_ids if g.is_role])

	def set_role_ids(self):
		for user in self:
			user.group_ids = user.role_ids
