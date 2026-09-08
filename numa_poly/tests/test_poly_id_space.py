# -*- coding: utf-8 -*-
"""
Un solo asignador para todo el espacio de ids compartido.

Un registro polimórfico y sus componentes comparten un id, así que todas esas tablas viven
en un mismo espacio. Cada una nació con su propio ``SERIAL``, y por lo tanto con su propia
secuencia: treinta asignadores repartiendo sobre un mismo espacio. Que no chocaran dependía
de que absolutamente toda alta pasara por ``create()`` de poly, que provee el id explícito y
nunca usa el ``DEFAULT`` de la columna.

Cualquier inserción por fuera disparaba la secuencia propia de la tabla, que no sabe nada
del espacio compartido. Y el síntoma dependía de la tabla: donde ``MAX(id)`` era alto
explotaba con clave duplicada, y donde era bajo entregaba 1, 2, 3 — libres en esa tabla y
ocupados en el espacio. Eso no falla, corrompe. Son las 560 colisiones de producción.

Ver doc/ID_SPACE.md.
"""
from odoo.tests import tagged, TransactionCase

from ..models.poly import POLY_ID_SEQUENCE


@tagged('post_install', '-at_install')
class TestPolyIdSpace(TransactionCase):

    def _shared_tables(self):
        """Toda tabla del espacio: la de cada modelo polimórfico y las de sus bases."""
        tables = set()
        for name in self.env.registry.models:
            model = self.env[name]
            getter = getattr(model, '_poly_get_depend_models', None)
            if not getter:
                continue
            depends = model._poly_get_depend_models()
            if not depends:
                continue
            if getattr(model, '_table', None):
                tables.add(model._table)
            for base_name in depends:
                if base_name in self.env and getattr(self.env[base_name], '_table', None):
                    tables.add(self.env[base_name]._table)
        return sorted(tables)

    def _column_default(self, table):
        self.env.cr.execute("""SELECT column_default FROM information_schema.columns
                                WHERE table_schema = current_schema()
                                  AND table_name = %s AND column_name = 'id'""", (table,))
        row = self.env.cr.fetchone()
        return (row and row[0]) or ''

    def test_01_every_shared_table_draws_from_the_one_allocator(self):
        """La invariante estructural: ninguna tabla del espacio con secuencia propia."""
        tables = self._shared_tables()
        self.assertTrue(tables, "no se detectó ninguna tabla polimórfica")

        propias = [t for t in tables if POLY_ID_SEQUENCE not in self._column_default(t)]

        self.assertFalse(
            propias,
            "estas tablas del espacio compartido todavía reparten ids por su cuenta, y una "
            "inserción que no pase por create() les va a entregar un id ya ocupado:\n  %s"
            % '\n  '.join('%s -> %s' % (t, self._column_default(t) or '(sin default)')
                          for t in propias))

    def test_02_a_raw_insert_lands_in_the_shared_space(self):
        """El camino que corrompía: insertar sin pasar por el ORM.

        Antes tomaba de la secuencia propia de la tabla. Ahora toma del asignador único, y
        el id que recibe está libre en todo el espacio.
        """
        cr = self.env.cr
        table = 'conversation_bot'
        if not self.env['ir.model'].sudo().search([('model', '=', 'conversation.bot')]):
            self.skipTest("conversation.bot no está instalado")

        cr.execute("SELECT last_value FROM %s" % POLY_ID_SEQUENCE)
        antes = cr.fetchone()[0]
        cr.execute("INSERT INTO %s DEFAULT VALUES RETURNING id" % table)
        nuevo = cr.fetchone()[0]

        self.assertGreater(nuevo, antes - 1,
                           "el insert crudo no tomó su id del asignador único")

        ocupadas = [t for t in self._shared_tables() if t != table
                    and self._id_exists(t, nuevo)]
        self.assertFalse(
            ocupadas,
            "el id %s que recibió el insert crudo ya estaba en uso en %s" % (nuevo, ocupadas))

    def _id_exists(self, table, record_id):
        self.env.cr.execute("SELECT 1 FROM %s WHERE id = %%s" % table, (record_id,))
        return bool(self.env.cr.fetchone())

    def test_03_claiming_is_idempotent(self):
        """Se re-aplica en cada actualización, así que tiene que poder correr dos veces."""
        model = self.env['res.partner']
        antes = self._column_default(model._table)

        model._poly_claim_shared_id_space()
        model._poly_claim_shared_id_space()

        self.assertEqual(self._column_default(model._table), antes,
                         "reclamar dos veces cambió algo")
        self.assertIn(POLY_ID_SEQUENCE, self._column_default(model._table))

    def test_04_non_polymorphic_models_are_left_alone(self):
        """El espacio compartido es de quien participa; el resto conserva su secuencia."""
        default = self._column_default('ir_logging')
        self.assertNotIn(
            POLY_ID_SEQUENCE, default,
            "ir.logging no participa de ninguna jerarquía polimórfica y no debería estar "
            "consumiendo del asignador compartido")
