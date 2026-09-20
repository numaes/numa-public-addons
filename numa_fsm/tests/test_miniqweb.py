# -*- coding: utf-8 -*-
"""
miniqweb: the subset of QWeb of the portal pages and the mails of numa_fsm.

Until 2026-09 it had nine happy-path tests and broke most of the common QWeb idioms:
plain text (exception), several roots (truncated silently), ``<t t-esc>`` (emitted nothing and
lost the following text), the text after a false ``t-if``, ``t-foreach`` with another directive
on the same element, ``<br>`` and ``&nbsp;`` of an Html field. Besides, ``t-raw`` evaluated the
directives of the content it inserted and the output was XML (an empty ``<div/>``, in HTML, opens a
div that swallows what follows). Each test here covers one of those cases.
"""
import re

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase

from ..models import miniqweb


def _compacto(html):
    """Without the whitespace between tags, to compare structure and not indentation."""
    return re.sub(r'>\s+<', '><', html.strip())


class TestMiniQweb(TransactionCase):

    def _render(self, template, **params):
        return miniqweb.render(template, **params)

    # ------------------------------------------------------------------------------------------ #
    # Long-standing cases (the output indentation changed: the text inside <t> is no longer lost)
    # ------------------------------------------------------------------------------------------ #
    def test_non_dynamic_content(self):
        result = self._render('''
        <data>
            <p>Esta es una prueba</p>
            <div>
                <span>Para ver como sale</span>
            </div>
        </data>
        ''')
        self.assertEqual(result, '''<data>
            <p>Esta es una prueba</p>
            <div>
                <span>Para ver como sale</span>
            </div>
        </data>''')

    def test_basic_parameters_sustitution(self):
        result = self._render('''
        <div>
            <span t-esc="a"/>
            <div>
                <span t-esc="b"/>
            </div>
        </div>
        ''', a=1, b=2)
        self.assertEqual(_compacto(result), '<div><span>1</span><div><span>2</span></div></div>')

    def test_basic_foreach(self):
        result = self._render('''
        <div>
            <t t-foreach="[1,2,3]" t-as="l">
                <span t-esc="l"/>
            </t>
        </div>
        ''')
        self.assertEqual(_compacto(result), '<div><span>1</span><span>2</span><span>3</span></div>')

    def test_basic_while(self):
        result = self._render('''
        <div>
            <t t-set="a" t-value="2"/>
            <t t-while="a > 0">
                <span t-esc="a"/>
                <t t-set="a" t-value="a-1"/>
            </t>
        </div>
        ''')
        self.assertEqual(_compacto(result), '<div><span>2</span><span>1</span></div>')

    def test_if(self):
        result = self._render('''
        <div>
            <span t-if="a == 1" t-esc="'Vale uno'"/>
            <span t-if="a == 2" t-esc="'Vale dos'"/>
            <span t-if="a != 1" t-esc="'NO vale uno'"/>
            <span t-if="a != 2" t-esc="'NO vale dos'"/>
        </div>
        ''', a=1)
        self.assertEqual(_compacto(result), '<div><span>Vale uno</span><span>NO vale dos</span></div>')

    def test_format(self):
        result = self._render('<div><span t-attf-value="esta es una prueba de {a} y {b}"/></div>', a=1, b=2)
        self.assertEqual(result, '<div><span value="esta es una prueba de 1 y 2"></span></div>')

    def test_esc(self):
        self.assertEqual(self._render('<div><span t-esc="\'esta es una prueba de esc\'"/></div>'),
                         '<div><span>esta es una prueba de esc</span></div>')

    def test_esc_escaped_chars(self):
        self.assertEqual(self._render('<div><span t-esc="text"/></div>', text='esta <es> una prueba de esc'),
                         '<div><span>esta &lt;es&gt; una prueba de esc</span></div>')

    def test_raw(self):
        self.assertEqual(self._render('<div><span t-raw="text"/></div>', text='esta <span>es una prueba</span> de raw'),
                         '<div><span>esta <span>es una prueba</span> de raw</span></div>')

    # ------------------------------------------------------------------------------------------ #
    # Fragments
    # ------------------------------------------------------------------------------------------ #
    def test_plain_text_is_a_valid_template(self):
        """It failed with AttributeError: the subject of a mail is plain text."""
        self.assertEqual(self._render('Pedido de documentación'), 'Pedido de documentación')

    def test_several_root_elements_are_all_rendered(self):
        """It kept the first one only, without warning."""
        self.assertEqual(self._render('<p>uno</p><p>dos</p>'), '<p>uno</p><p>dos</p>')
        self.assertEqual(self._render('texto <b>y</b> más'), 'texto <b>y</b> más')

    def test_xml_declaration_and_empty_templates(self):
        self.assertEqual(self._render('<?xml version="1.0"?>\n<div>x</div>'), '<div>x</div>')
        self.assertEqual(self._render(None), '')
        self.assertEqual(self._render(False), '')
        self.assertEqual(self._render(''), '')

    # ------------------------------------------------------------------------------------------ #
    # <t> and the text around what is not emitted
    # ------------------------------------------------------------------------------------------ #
    def test_t_esc_on_t_emits_the_value_and_keeps_the_following_text(self):
        """It emitted nothing and lost the text that followed."""
        self.assertEqual(self._render('<t t-esc="x"/>', x='valor'), 'valor')
        self.assertEqual(self._render('<p>Hola <t t-esc="x"/>, bienvenido</p>', x='Ana'),
                         '<p>Hola Ana, bienvenido</p>')

    def test_text_inside_t_is_kept(self):
        self.assertEqual(self._render('<p><t t-if="1">visible</t></p>'), '<p>visible</p>')

    def test_text_after_a_false_t_if_is_kept(self):
        self.assertEqual(self._render('<p>Hola <b t-if="0">x</b> mundo</p>'), '<p>Hola  mundo</p>')
        self.assertEqual(self._render('<p>a <t t-set="v" t-value="1"/>b</p>'), '<p>a b</p>')

    def test_comments_are_not_emitted_but_their_tail_is(self):
        self.assertEqual(self._render('<p>a<!-- nota -->b</p>'), '<p>ab</p>')

    # ------------------------------------------------------------------------------------------ #
    # Conditionals
    # ------------------------------------------------------------------------------------------ #
    def test_if_elif_else(self):
        template = '<t t-if="a == 1">uno</t>\n<t t-elif="a == 2">dos</t>\n<t t-else="">otro</t>'
        self.assertEqual(self._render(template, a=1), 'uno')
        self.assertEqual(self._render(template, a=2), 'dos')
        self.assertEqual(self._render(template, a=3), 'otro')

    def test_elif_or_else_without_if_is_an_error(self):
        with self.assertRaises(UserError):
            self._render('<t t-else="">x</t>')
        with self.assertRaises(UserError):
            self._render('<p>a</p><t t-elif="1">x</t>')

    # ------------------------------------------------------------------------------------------ #
    # Loops
    # ------------------------------------------------------------------------------------------ #
    def test_foreach_on_an_element_repeats_the_element(self):
        """With t-esc on the same element it failed with NameError: evaluated before the loop."""
        self.assertEqual(self._render('<ul><li t-foreach="[1,2]" t-as="i" t-esc="i"/></ul>'),
                         '<ul><li>1</li><li>2</li></ul>')

    def test_foreach_applies_t_if_per_item(self):
        self.assertEqual(self._render('<ul><li t-foreach="[1,2,3]" t-as="i" t-if="i != 2" t-esc="i"/></ul>'),
                         '<ul><li>1</li><li>3</li></ul>')

    def test_foreach_at_the_root_and_text_in_the_loop(self):
        self.assertEqual(self._render('<t t-foreach="[1,2]" t-as="i"><span t-esc="i"/></t>'),
                         '<span>1</span><span>2</span>')
        self.assertEqual(self._render('<p><t t-foreach="[1,2]" t-as="i"><t t-esc="i"/>;</t></p>'), '<p>1;2;</p>')

    def test_foreach_loop_variables(self):
        """They were '$as_index' and company: with '$' they could not be used in an expression."""
        template = '<t t-foreach="\'abc\'" t-as="c"><t t-esc="c_index"/><t t-esc="c"/><t t-if="not c_last">,</t></t>'
        self.assertEqual(self._render(template), '0a,1b,2c')
        self.assertEqual(self._render('<t t-foreach="d" t-as="k"><t t-esc="k"/>=<t t-esc="k_value"/>;</t>',
                                      d={'x': 1, 'y': 2}), 'x=1;y=2;')
        self.assertEqual(self._render('<t t-foreach="3" t-as="i"><t t-esc="i"/></t>'), '012')
        self.assertEqual(self._render('<t t-foreach="items" t-as="i"><t t-esc="i_size"/></t>', items=[7, 8]), '22')

    def test_loop_variables_do_not_leak(self):
        with self.assertRaises(ValueError):
            self._render('<t t-foreach="[1]" t-as="i"/><t t-esc="i"/>')

    def test_foreach_without_as_is_an_error(self):
        with self.assertRaises(UserError):
            self._render('<t t-foreach="[1]"/>')

    def test_break_and_continue(self):
        template = ('<t t-foreach="[1,2,3,4]" t-as="i">'
                    '<t t-if="i == 2"><t-continue/></t><t t-if="i == 4"><t-break/></t><t t-esc="i"/></t>')
        self.assertEqual(self._render(template), '13')
        with self.assertRaises(UserError):
            self._render('<t-break/>')

    def test_while_has_an_iteration_limit(self):
        with self.assertRaises(UserError):
            self._render('<t t-while="True">x</t>')

    # ------------------------------------------------------------------------------------------ #
    # Values: t-set, t-esc, t-raw
    # ------------------------------------------------------------------------------------------ #
    def test_set_with_value_or_body(self):
        self.assertEqual(self._render('<div><t t-set="a" t-value="3"/><span t-esc="a"/></div>'),
                         '<div><span>3</span></div>')
        self.assertEqual(self._render('<t t-set="saludo">Hola <b>Ana</b></t><p t-raw="saludo"/>'),
                         '<p>Hola <b>Ana</b></p>')

    def test_esc_of_none_false_and_zero(self):
        self.assertEqual(self._render('<span t-esc="v"/>', v=None), '<span></span>')
        self.assertEqual(self._render('<span t-esc="v"/>', v=False), '<span></span>')
        self.assertEqual(self._render('<span t-esc="v"/>', v=0), '<span>0</span>')

    def test_esc_escapes_and_replaces_the_content(self):
        self.assertEqual(self._render('<span t-esc="v"/>', v='a <b> & c'), '<span>a &lt;b&gt; &amp; c</span>')
        self.assertEqual(self._render('<span t-esc="v">viejo <b>x</b></span>', v='nuevo'), '<span>nuevo</span>')

    def test_raw_inserts_markup_without_evaluating_it(self):
        """It evaluated the directives of the content: if it came from the portal, it ran its
        expressions."""
        self.assertEqual(self._render('<div t-raw="h"/>', h='<span t-esc="secreto">x</span>', secreto='no'),
                         '<div><span t-esc="secreto">x</span></div>')
        self.assertEqual(self._render('<div t-raw="h"/>', h='solo texto'), '<div>solo texto</div>')
        self.assertEqual(self._render('<div t-raw="h"/>', h='<b>x</b> y'), '<div><b>x</b> y</div>')
        self.assertEqual(self._render('<div t-raw="h"/>', h=None), '<div></div>')

    # ------------------------------------------------------------------------------------------ #
    # Attributes
    # ------------------------------------------------------------------------------------------ #
    def test_att_escapes_and_omits_none_or_false(self):
        self.assertEqual(self._render('<a t-att-href="u">link</a>', u='/x?a=1&b=2'),
                         '<a href="/x?a=1&amp;b=2">link</a>')
        self.assertEqual(self._render('<a t-att-href="None" t-att-title="False" class="c">x</a>'),
                         '<a class="c">x</a>')
        self.assertEqual(self._render('<a t-att="{\'href\': \'/y\', \'rel\': None}">x</a>'), '<a href="/y">x</a>')

    def test_attf_expressions_variables_and_literal_braces(self):
        """With str.format, a literal brace (CSS, for example) broke with KeyError."""
        self.assertEqual(
            self._render('<a t-attf-href="/p/#{n + 1}/{nombre}" t-attf-style="a{b}">x</a>', n=1, nombre='z'),
            '<a href="/p/2/z" style="a{b}">x</a>')

    def test_unsupported_directive_is_an_error(self):
        """It was copied as one more attribute and the template came out broken without warning."""
        with self.assertRaisesRegex(UserError, 't-call'):
            self._render('<t t-call="x"/>')

    # ------------------------------------------------------------------------------------------ #
    # HTML
    # ------------------------------------------------------------------------------------------ #
    def test_html_from_an_html_field(self):
        """<br> ended up as <br>dos</br> and &nbsp; was deleted."""
        self.assertEqual(self._render('<p>uno<br>dos</p>'), '<p>uno<br>dos</p>')
        self.assertEqual(self._render('<p>a&nbsp;b</p>'), '<p>a\xa0b</p>')
        self.assertEqual(self._render('<p><img src="a.png"> texto</p>'), '<p><img src="a.png"> texto</p>')

    def test_html_attributes_without_value_or_quotes(self):
        """An attribute without a value is not XML: the parser dropped it, and the portal file input
        lost ``multiple`` (only one file could be uploaded)."""
        self.assertEqual(self._render('<input type="file" name="archivos" multiple>'),
                         '<input type="file" name="archivos" multiple>')
        self.assertEqual(self._render('<td colspan=2>x</td>'), '<td colspan="2">x</td>')

    def test_markup_inside_attribute_values_is_not_a_tag(self):
        self.assertEqual(self._render('<t t-if="a > 1">si</t>', a=2), 'si')
        self.assertEqual(self._render('<p t-att-title="\'<br>\'">x</p>'), '<p title="&lt;br&gt;">x</p>')

    def test_bare_ampersands(self):
        """A bare '&' is not XML: a URL with several parameters was lost."""
        self.assertEqual(self._render('<p>a & b <a href="/x?a=1&b=2">l</a> &amp; &#233;</p>'),
                         '<p>a &amp; b <a href="/x?a=1&amp;b=2">l</a> &amp; \xe9</p>')
        self.assertEqual(self._render('<t t-esc="a & b"/>', a=6, b=3), '2')

    def test_portal_form_keeps_its_structure(self):
        """The old engine put the form inside the input and closed it with </br>."""
        result = self._render('<form t-att-action="\'/d/\' + n"><input type="file" multiple>\n<br><br>\n'
                              '<button>Enviar</button></form><p>fin</p>', n='u1')
        self.assertEqual(result, '<form action="/d/u1"><input type="file" multiple>\n<br><br>\n'
                                 '<button>Enviar</button></form><p>fin</p>')

    def test_empty_elements_are_closed_as_html(self):
        """Serialized as XML, an empty <div/> in HTML opens a div that contains what follows."""
        self.assertEqual(self._render('<div class="x"/><p>sigue</p>'), '<div class="x"></div><p>sigue</p>')
