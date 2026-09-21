# -*- coding: utf-8 -*-
"""The rules of the discipline, and the API that makes it usable.

The module had no tests, and it could not be installed either: an `@api.constrains` named
`users`, a field `res.groups` has not had since Odoo 20 renamed it to `user_ids`, which
fails at registry setup, and the views hid pages with `attrs=`, removed in 17.0. So none
of what follows had ever been checked against a running database.
"""
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestNumaRoles(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Group = cls.env['res.groups']
        cls.perm_read = Group.create({
            'name': 'Read the ledger', 'numa_type': 'permission',
            'technical_code': 'perm_read_ledger'})
        cls.perm_sign = Group.create({
            'name': 'Sign off', 'numa_type': 'permission',
            'technical_code': 'perm_sign_off'})
        cls.role_clerk = Group.create({
            'name': 'Clerk', 'numa_type': 'role',
            'implied_ids': [(6, 0, cls.perm_read.ids)]})
        cls.role_manager = Group.create({
            'name': 'Manager', 'numa_type': 'role',
            'implied_ids': [(6, 0, (cls.role_clerk | cls.perm_sign).ids)]})
        cls.user = cls.env['res.users'].create({
            'name': 'Empleado', 'login': 'numa_roles_probe',
            'group_ids': [(6, 0, cls.role_clerk.ids)]})

    # ------------------------------------------------------------------
    # The rules
    # ------------------------------------------------------------------

    def test_01_a_permission_is_not_assigned_to_anybody(self):
        """The rule the whole module rests on. It could never have run before: the
        constraint watched `users`, which is `user_ids` in Odoo 20."""
        with self.assertRaises(ValidationError):
            self.perm_read.user_ids = [(4, self.user.id)]

    def test_02_a_role_is_assigned(self):
        self.assertIn(self.role_clerk, self.user.group_ids)

    def test_03_a_permission_does_not_contain_a_role(self):
        with self.assertRaises(ValidationError):
            self.perm_read.implied_ids = [(4, self.role_clerk.id)]

    def test_04_a_permission_needs_a_code(self):
        """A code is derived from the name when none is given, so the only way to end up
        without one is a name that has nothing to derive from."""
        with self.assertRaises(ValidationError):
            self.env['res.groups'].create({
                'name': '...', 'numa_type': 'permission'})

    def test_05_a_code_is_derived_when_none_is_given(self):
        permiso = self.env['res.groups'].create({
            'name': 'Approve Discount', 'numa_type': 'permission'})
        self.assertEqual(permiso.technical_code, 'perm_approve_discount')

    def test_06_a_code_is_unique(self):
        with self.assertRaises(Exception):
            self.env['res.groups'].create({
                'name': 'Otra cosa', 'numa_type': 'permission',
                'technical_code': 'perm_read_ledger'})
            self.env.flush_all()

    def test_07_a_code_does_not_move(self):
        """Other code refers to it by that name. The module carried this as an
        `@api.constrains`, which runs after the write and therefore compared the new
        value with itself: it could never fire."""
        with self.assertRaises(ValidationError):
            self.perm_read.technical_code = 'perm_something_else'

    def test_08_a_permission_with_a_code_stays_a_permission(self):
        with self.assertRaises(ValidationError):
            self.perm_read.numa_type = 'system'

    # ------------------------------------------------------------------
    # Counting
    # ------------------------------------------------------------------

    def test_09_a_role_counts_the_permissions_it_reaches(self):
        """Through other roles too. Counting only `implied_ids` answered a different
        question, and a role built out of roles reported zero."""
        self.assertEqual(self.role_clerk.permission_count, 1)
        self.assertEqual(self.role_manager.permission_count, 2)

    def test_10_a_permission_counts_nothing(self):
        self.assertEqual(self.perm_read.permission_count, 0)

    # ------------------------------------------------------------------
    # The API
    # ------------------------------------------------------------------

    def test_11_a_user_holds_what_their_role_bundles(self):
        self.assertTrue(self.user.has_permission('perm_read_ledger'))

    def test_12_a_user_does_not_hold_what_it_does_not(self):
        self.assertFalse(self.user.has_permission('perm_sign_off'))

    def test_12b_the_answer_is_about_the_user_not_the_environment(self):
        """The first version short-circuited on `self.env.su`, so it said yes to
        everybody whenever it was called from a sudo'd environment -- which is most of
        the places a business rule runs. A check that says yes to everyone is worse than
        no check, because it looks like one."""
        self.assertFalse(self.user.sudo().has_permission('perm_sign_off'))
        self.assertTrue(self.user.sudo().has_permission('perm_read_ledger'))

    def test_12c_root_holds_everything(self):
        raiz = self.env.ref('base.user_root')
        self.assertTrue(raiz.has_permission('perm_sign_off'))
        self.assertTrue(raiz.has_permission('perm_read_ledger'))

    def test_13_a_permission_reached_through_another_role_counts(self):
        """Manager includes Clerk, which includes the read permission. Two levels up."""
        self.user.group_ids = [(6, 0, self.role_manager.ids)]
        self.assertTrue(self.user.has_permission('perm_read_ledger'))
        self.assertTrue(self.user.has_permission('perm_sign_off'))

    def test_14_an_unknown_code_is_not_held(self):
        """And it does not raise: a rule asking about a permission somebody removed
        should deny, not crash."""
        self.assertFalse(self.user.has_permission('perm_that_does_not_exist'))
        self.assertFalse(self.user.has_permission(''))

    def test_15_the_lookup_finds_the_permission_by_code(self):
        self.assertEqual(
            self.env['res.groups'].numa_permission('perm_read_ledger'), self.perm_read)
        self.assertFalse(self.env['res.groups'].numa_permission('perm_nope'))
