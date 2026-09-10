# -*- coding: utf-8 -*-
"""
miniqweb: el subconjunto de QWeb con el que numa_fsm renderiza páginas de portal y mails.

La plantilla puede ser un fragmento: texto plano, varios elementos en la raíz, o el HTML que guarda
un campo Html (``<br>``, ``&nbsp;``). La salida se serializa como HTML.

Directivas:

- ``t-if`` / ``t-elif`` / ``t-else``, en elementos hermanos consecutivos.
- ``t-foreach`` + ``t-as``: repite el elemento. Define ``<as>``, ``<as>_value``, ``<as>_index``,
  ``<as>_size``, ``<as>_first``, ``<as>_last``, ``<as>_parity``, ``<as>_even``, ``<as>_odd`` y
  ``<as>_all``, que no salen del bucle. Un entero itera ``range(n)``; un dict, sus claves.
- ``t-while``: repite el elemento mientras la expresión sea verdadera, con un tope de iteraciones.
- ``t-set`` con ``t-value``, o con el contenido renderizado como valor.
- ``t-esc`` (texto escapado) y ``t-raw`` (markup insertado tal cual, sin evaluar directivas):
  reemplazan el contenido del elemento. ``None`` y ``False`` no emiten nada.
- ``t-att-<nombre>`` (con ``None`` o ``False`` se omite), ``t-att`` (dict o pares) y
  ``t-attf-<nombre>`` (``#{expr}``, ``{{ expr }}`` o ``{variable}``).
- Los elementos ``<t-break/>`` y ``<t-continue/>``, dentro de un bucle.

``<t>`` no genera elemento: aporta su texto y su contenido. Los comentarios no se emiten. Una
directiva que no está en esta lista es un error, no un atributo más.
"""
import html
import html.entities
import logging
import re

import lxml.etree
from lxml.etree import LxmlError
from markupsafe import Markup

from odoo import exceptions, _
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)

MAX_WHILE_ITERATIONS = 10000


class TBreak(Exception):
    pass


class TContinue(Exception):
    pass


xml_parser = lxml.etree.XMLParser(encoding='UTF-8',
                                  resolve_entities=False,
                                  strip_cdata=False,
                                  recover=True,
                                  ns_clean=True)

_FRAGMENT = 'miniqweb-fragment'
_VOID_ELEMENTS = ('area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param',
                  'source', 'track', 'wbr')
_VOID_CLOSE = re.compile(r'</(?:%s)\s*>' % '|'.join(_VOID_ELEMENTS), re.IGNORECASE)
_ATTRIBUTE_VALUE = r'"[^"]*"|\'[^\']*\'|[^\s"\'=<>`]+'
_START_TAG = re.compile(r'<([A-Za-z][\w:.-]*)((?:\s+[^\s"\'<>/=]+(?:\s*=\s*(?:%s))?)*)\s*(/?)>' % _ATTRIBUTE_VALUE)
_ATTRIBUTE = re.compile(r'\s+([^\s"\'<>/=]+)(?:\s*=\s*(%s))?' % _ATTRIBUTE_VALUE)
_XML_DECLARATION = re.compile(r'^\s*<\?xml[^>]*\?>')
_NAMED_ENTITY = re.compile(r'&([A-Za-z][A-Za-z0-9]*);')
_XML_ENTITIES = frozenset(('amp', 'lt', 'gt', 'quot', 'apos'))
_BARE_AMPERSAND = re.compile(r'&(?!(?:[A-Za-z][A-Za-z0-9]*|#[0-9]+|#[xX][0-9A-Fa-f]+);)')
_ATTF_PLACEHOLDER = re.compile(r'#\{(.+?)\}|\{\{(.+?)\}\}|\{([A-Za-z_][A-Za-z0-9_]*)\}')
_DIRECTIVES = frozenset(('t-if', 't-elif', 't-else', 't-foreach', 't-as', 't-while', 't-set', 't-value',
                         't-esc', 't-raw', 't-att'))


def _start_tag(match):
    name, attributes, closed = match.groups()

    def attribute(attribute_match):
        key, value = attribute_match.groups()
        if value is None:
            value = '"%s"' % key  # atributo booleano de HTML: multiple, checked, disabled…
        elif value[0] in '"\'':
            # XML no admite '<' en un valor: una expresión como t-att-title="'<br>'" se truncaba.
            value = value[0] + value[1:-1].replace('<', '&lt;') + value[-1]
        else:
            value = '"%s"' % value
        return ' %s=%s' % (key, value)

    if not closed and name.lower() in _VOID_ELEMENTS:
        closed = '/'
    return '<%s%s%s>' % (name, _ATTRIBUTE.sub(attribute, attributes), closed)


def _as_xml(template):
    """El HTML de un campo Html, como XML que lxml puede parsear: sin declaración, con los elementos
    vacíos cerrados, los atributos con valor entre comillas y las entidades con nombre como
    referencias numéricas. Un atributo sin valor no es XML válido, y el parser tolerante lo
    descartaba: el ``multiple`` del input de archivos del portal se perdía."""
    text = _XML_DECLARATION.sub('', template)
    text = _VOID_CLOSE.sub('', text)
    text = _START_TAG.sub(_start_tag, text)

    def entity(match):
        name = match.group(1)
        if name in _XML_ENTITIES or name not in html.entities.name2codepoint:
            return match.group(0)
        return '&#%d;' % html.entities.name2codepoint[name]

    # Un '&' suelto (una URL con varios parámetros, "a & b") no es XML válido.
    return _BARE_AMPERSAND.sub('&amp;', _NAMED_ENTITY.sub(entity, text))


def _parse(template):
    """Parsea un fragmento dentro de un elemento contenedor. Devuelve el contenedor o None."""
    source = '<%s>%s</%s>' % (_FRAGMENT, _as_xml(str(template)), _FRAGMENT)
    try:
        return lxml.etree.fromstring(source.encode('UTF-8'), parser=xml_parser)
    except LxmlError:
        _logger.exception('miniqweb: unexpected parsing error in template %r', template)
        raise


def _evaluate(expression, params):
    return safe_eval(expression, locals_dict=params)


def _text(value):
    return '' if value is None or value is False else str(value)


def _append_text(target, text):
    """Agrega texto al final de lo ya emitido en ``target``: a la cola del último hijo, o a su texto."""
    if not text:
        return
    if len(target):
        last = target[-1]
        last.tail = (last.tail or '') + text
    else:
        target.text = (target.text or '') + text


def _append_markup(target, value):
    """Inserta markup al final de ``target``, tal cual: sus directivas no se evalúan."""
    if value is None or value is False:
        return
    fragment = _parse(value)
    if fragment is None:
        return
    _append_text(target, fragment.text)
    for child in list(fragment):
        target.append(child)


def _serialize_children(element):
    parts = [html.escape(element.text or '', quote=False)]
    parts.extend(lxml.etree.tostring(child, method='html', encoding='unicode') for child in element)
    return ''.join(parts)


def _check_directives(node, attributes):
    for name in attributes:
        if name.startswith('t-') and name not in _DIRECTIVES and not name.startswith(('t-att-', 't-attf-')):
            raise exceptions.UserError(_('Unsupported template directive %s in <%s>') % (name, node.tag))


def _render_children(source, target, params):
    """Renderiza el texto y los hijos de ``source`` al final de ``target``."""
    _append_text(target, source.text)
    chain = None
    for child in source:
        if isinstance(child.tag, str):
            chain = _render_node(child, target, params, chain)
        # Un comentario o una instrucción de procesamiento no se emite, pero su cola sí.
        _append_text(target, child.tail)


def _render_node(node, target, params, chain, attributes=None):
    """Renderiza ``node`` al final de ``target``.

    Devuelve el estado de la cadena t-if / t-elif / t-else para el hermano siguiente: None fuera de
    una cadena, True si ya se tomó una rama, False si todavía no."""
    if node.tag == 't-break':
        raise TBreak()
    if node.tag == 't-continue':
        raise TContinue()
    if attributes is None:
        attributes = dict(node.attrib)
        _check_directives(node, attributes)

    if 't-foreach' in attributes:
        _render_foreach(node, attributes, target, params)
        return None
    if 't-while' in attributes:
        _render_while(node, attributes, target, params)
        return None

    if 't-if' in attributes:
        if not _evaluate(attributes['t-if'], params):
            return False
        following = True
    elif 't-elif' in attributes:
        if chain is None:
            raise exceptions.UserError(_('t-elif without a preceding t-if in <%s>') % node.tag)
        if chain or not _evaluate(attributes['t-elif'], params):
            return chain
        following = True
    elif 't-else' in attributes:
        if chain is None:
            raise exceptions.UserError(_('t-else without a preceding t-if in <%s>') % node.tag)
        if chain:
            return None
        following = None
    else:
        following = None

    _render_body(node, attributes, target, params)
    return following


def _render_foreach(node, attributes, target, params):
    name = attributes.get('t-as')
    if not name:
        raise exceptions.UserError(_('t-foreach without t-as in <%s>') % node.tag)
    collection = _evaluate(attributes['t-foreach'], params)
    if collection is None or isinstance(collection, bool):
        items = []
    elif isinstance(collection, int):
        items = list(range(collection))
    else:
        items = list(collection)
    rest = {key: value for key, value in attributes.items() if key not in ('t-foreach', 't-as')}
    size = len(items)
    loop_params = dict(params)
    for index, item in enumerate(items):
        parity = 'odd' if index % 2 else 'even'
        loop_params.update({
            name: item,
            name + '_value': collection[item] if isinstance(collection, dict) else item,
            name + '_index': index,
            name + '_size': size,
            name + '_first': index == 0,
            name + '_last': index == size - 1,
            name + '_parity': parity,
            name + '_even': parity == 'even',
            name + '_odd': parity == 'odd',
            name + '_all': collection,
        })
        try:
            _render_node(node, target, loop_params, None, rest)
        except TContinue:
            continue
        except TBreak:
            break


def _render_while(node, attributes, target, params):
    rest = {key: value for key, value in attributes.items() if key != 't-while'}
    iterations = 0
    while _evaluate(attributes['t-while'], params):
        iterations += 1
        if iterations > MAX_WHILE_ITERATIONS:
            raise exceptions.UserError(
                _('t-while exceeded %s iterations in <%s>') % (MAX_WHILE_ITERATIONS, node.tag))
        try:
            _render_node(node, target, params, None, rest)
        except TContinue:
            continue
        except TBreak:
            break


def _render_body(node, attributes, target, params):
    if 't-set' in attributes:
        if 't-value' in attributes:
            value = _evaluate(attributes['t-value'], params)
        else:
            holder = lxml.etree.Element(_FRAGMENT)
            _render_children(node, holder, params)
            value = Markup(_serialize_children(holder))
        params[attributes['t-set']] = value
        return

    if node.tag == 't':
        container = target
    else:
        container = lxml.etree.SubElement(target, node.tag)
        _set_attributes(container, attributes, params)

    if 't-esc' in attributes:
        _append_text(container, _text(_evaluate(attributes['t-esc'], params)))
    elif 't-raw' in attributes:
        _append_markup(container, _evaluate(attributes['t-raw'], params))
    else:
        _render_children(node, container, params)


def _set_attributes(element, attributes, params):
    for name, value in attributes.items():
        if name.startswith('t-attf-'):
            element.set(name[len('t-attf-'):], _format(value, params))
        elif name.startswith('t-att-'):
            _set_attribute(element, name[len('t-att-'):], _evaluate(value, params))
        elif name == 't-att':
            values = _evaluate(value, params)
            for key, val in (values.items() if isinstance(values, dict) else values or ()):
                _set_attribute(element, key, val)
        elif not name.startswith('t-'):
            element.set(name, value)


def _set_attribute(element, name, value):
    if value is None or value is False:
        element.attrib.pop(name, None)
    else:
        element.set(name, str(value))


def _format(template, params):
    def placeholder(match):
        expression, jinja_expression, variable = match.groups()
        if variable is not None:
            return _text(params[variable]) if variable in params else match.group(0)
        return _text(_evaluate(expression or jinja_expression, params))

    return _ATTF_PLACEHOLDER.sub(placeholder, template)


def render(template: str, **params) -> str:
    """Renderiza ``template`` con ``params``. Devuelve HTML, sin espacios al principio ni al final."""
    if template is None or template is False:
        return ''
    fragment = _parse(template)
    if fragment is None:
        return ''
    output = lxml.etree.Element(_FRAGMENT)
    try:
        _render_children(fragment, output, params)
    except TBreak:
        trace_msg = _('<t-break> out of loop construction!')
        _logger.error(trace_msg)
        raise exceptions.UserError(trace_msg)
    except TContinue:
        trace_msg = _('<t-continue> out of loop construction!')
        _logger.error(trace_msg)
        raise exceptions.UserError(trace_msg)
    return _serialize_children(output).strip()
