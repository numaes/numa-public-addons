# -*- coding: utf-8 -*-
"""
Las dos caras de una ``PolyReference``: el valor en Python y su forma en SQL.

Una PolyReference no tiene columna. Base y derivado comparten el id, así que el
"vínculo" hacia la base es el id del propio registro, y eso se dice dos veces:
con ``compute`` —el valor— y con ``compute_sql`` —la misma cosa como expresión
de consulta, que es lo que permite usar el campo en un dominio
(``domains.py:1021`` exige ``store`` o ``compute_sql``)—.

Odoo pide las dos juntas: ``compute_sql`` sin ``compute`` avisa *"makes sense
only if ... is a computed field"* (``fields.py:471-473``). numa_poly declaraba
sólo la segunda porque derivaba el valor en un ``__get__`` propio, en paralelo al
del framework.

``test_02`` es el que importa, y sale de haberse equivocado: declarar el
``compute`` y dejar el ``__get__`` puesto hacía desaparecer el aviso **sin que el
compute se ejecutara nunca** —medido: cero llamadas leyendo por atributo, por
``read()`` y por ``mapped()``—. Un compute declarado y muerto es decoración que
silencia un aviso, que es justo lo que el aviso quería evitar.
"""
from odoo.tests.common import TransactionCase, tagged

CONCRETO = 'test.poly.child.a'
VINCULO = 'base_id'


@tagged('post_install', '-at_install')
class TestPolyReferenceForms(TransactionCase):

    def _campo(self):
        return self.env[CONCRETO]._fields[VINCULO]

    def test_01_the_reference_declares_both_forms(self):
        campo = self._campo()
        self.assertTrue(campo.compute,
                        "sin compute, compute_sql no tiene de qué ser la traducción "
                        "y Odoo avisa al armar el campo")
        self.assertTrue(campo.compute_sql,
                        "sin compute_sql el campo no se puede usar en un dominio")

    def test_02_the_python_side_is_the_one_that_actually_runs(self):
        """Que el compute no sea decoración: tiene que correr al leer."""
        campo = self._campo()
        llamadas = []
        original = campo.compute

        def espia(records):
            llamadas.append(records._name)
            return original(records)

        espia.__name__ = 'espia_poly_reference'
        self.patch(campo, 'compute', espia)

        registro = self.env[CONCRETO].create({'base_field': 'dato'})
        self.env.invalidate_all()
        self.assertTrue(registro[VINCULO])
        self.assertTrue(llamadas, "leer el vínculo no ejecutó el compute declarado")

    def test_03_the_sql_form_agrees_with_the_python_one(self):
        """Las dos caras tienen que dar la misma respuesta.

        Leer usa el compute; buscar usa compute_sql y nunca pasa por Python. Si
        divergen, un dominio devuelve registros que el atributo contradice.
        """
        registro = self.env[CONCRETO].create({'base_field': 'dato'})
        self.env.flush_all()
        base = registro[VINCULO]
        self.assertTrue(base)

        encontrados = self.env[CONCRETO].search(
            [(VINCULO, '=', base.id), ('id', 'in', registro.ids)])
        self.assertEqual(encontrados, registro,
                         "el dominio no encuentra lo que el atributo afirma")

        # El camino con punto, que es el que usa la expresión SQL del vínculo.
        por_la_base = self.env[CONCRETO].search(
            [('%s.base_field' % VINCULO, '=', 'dato'), ('id', 'in', registro.ids)])
        self.assertEqual(por_la_base, registro)

    def test_04_reading_the_link_over_many_records_is_one_query(self):
        """El vínculo se resuelve sin ir a la base de datos: es el propio id."""
        registros = self.env[CONCRETO].create(
            [{'base_field': 'n%s' % n} for n in range(10)])
        self.env.invalidate_all()
        with self.assertQueryCount(__system__=0):
            bases = registros.mapped(VINCULO)
        self.assertEqual(len(bases), 10)
