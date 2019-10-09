#-*- coding: utf-8 -*-

from odoo import fields, models, api,_
from lxml import etree
from lxml.builder import E

import logging
_logger = logging.getLogger(__name__)


class Group(models.Model):
	_inherit = 'res.groups'

	is_role = fields.Boolean('Is role?')
	type_ids = fields.Many2many('res.groups_type', 'res_groups_type_rel', 'type_id', 'group_id', string='Types')


	@api.model
	def _update_user_groups_view(self):
		""" Modify the view with xmlid ``base.user_groups_view``, which inherits
			the user form view, and show just the roles.
		"""
		if self._context.get('install_mode'):
			# use installation/admin language for translatable names in the view
			user_context = self.env['res.users'].context_get()
			self = self.with_context(**user_context)

		# We have to try-catch this, because at first init the view does not
		# exist but we are already creating some basic groups.
		view = self.env.ref('base.user_groups_view', raise_if_not_found=False)
		if view and view.exists() and view._name == 'ir.ui.view':
			xml = E.field(E.group(*([]), col="2"), E.group(*([]), col="4"), name="groups_id", position="after")
			xml.addprevious(etree.Comment("GENERATED AUTOMATICALLY BY GROUPS"))
			xml_content = etree.tostring(xml, pretty_print=True, xml_declaration=True, encoding="utf-8")
			if not view.check_access_rights('write', raise_exception=False):
				# erp manager has the rights to update groups/users but not
				# to modify ir.ui.view
				if self.env.user.has_group('base.group_erp_manager'):
					view = view.sudo()
			view.with_context(lang=None).write({'arch': xml_content, 'arch_fs': False})


class Users(models.Model):
	_inherit = 'res.users'

	def _default_groups(self):
		default_user = self.env.ref('base.default_user', raise_if_not_found=False)
		return (default_user or self.env['res.users']).sudo().groups_id


	groups_id = fields.Many2many('res.groups', 'res_groups_users_rel', 'uid', 'gid', string='Groups', default=_default_groups)


class ResGroupsType(models.Model):
	_name = 'res.groups_type'

	name = fields.Char('Type', required=True)
	description = fields.Char('Description')
	active = fields.Boolean('Active', default=True)

	_sql_constraints = [('name_uniq', 'unique (name)', 'El Tipo de Grupo no debe Repetirse!')]